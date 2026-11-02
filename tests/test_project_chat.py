import json
import uuid
from contextlib import nullcontext
from dataclasses import replace
from unittest.mock import patch

import pytest

from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, ProjectConfig
from ai_orchestrator.models import (
    ExecutionControlRecord, IntegrationControl, IntegrationStatus, RunExecutionAction, RunExecutionControl,
    RunExecutionSituation, RunLockState, RunState, RunStep, Stage, TaskAction, TaskStatus, WorkTask,
)
from ai_orchestrator.pipeline import Pipeline, PipelineError
from ai_orchestrator.project_chat import MAX_REPAIRS, parse_decision


@pytest.fixture
def project_chat(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    agent = AgentConfig(id="planner", capabilities=("general",), command=("fake",), provider_id="custom")
    pipeline = Pipeline(Config(path=tmp_path / "config.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=(agent,)))
    state = RunState(id="group", spec_path="plan.md", spec_digest="goal", repo_path=str(repo), main_branch="main",
                     summary="기존 목표", stage=Stage.PLANNED, plan_revision=1, plan_approved_revision=1,
                     tasks=[WorkTask(id="task", title="기존 작업", capabilities=["general"], acceptance_criteria=["original criterion"])])
    pipeline.store.save(state)
    control = RunExecutionControl(RunExecutionSituation.READY, RunExecutionAction.EXECUTE, "ready", RunLockState.UNLOCKED)
    integration = IntegrationControl(IntegrationStatus.NEEDS_VERIFICATION, "verify", "needs_verification", False, False)
    with patch.object(pipeline, "status_with_controls", side_effect=lambda _: (pipeline.store.load(state.id), control, integration)), \
         patch.object(pipeline, "_configure_planning_profile", return_value=agent), \
         patch.object(pipeline, "_planning_effort_scope", return_value=nullcontext()), \
         patch.object(pipeline, "_invoke_planning_agent") as invoke:
        yield pipeline, state, invoke, control, integration


def accept(pipeline, state, message="막힌 거 해결하고 계속해줘"):
    return pipeline.request_chat_control(state.id, request_id=str(uuid.uuid4()), intent="project", message=message,
        expected={"planRevision": state.plan_revision, "conversationRevision": state.planning_conversation_revision, "taskId": ""},
        profile={"planningAgentId": "planner", "planningModel": "chosen", "planningReasoningEffort": "high"})


def decide(pipeline, state, invoke, parent, action, **values):
    invoke.return_value = json.dumps({"action": action, "message": "현재 확인한 결과입니다.", "authorized": action not in {"reply", "ask"}, **values})
    return pipeline.decide_project_chat(state.id, parent["request_id"])


def perform(pipeline, state, decision):
    return pipeline.perform_project_chat(state.id, decision["request_id"], decision["payload"]["step_id"])


@pytest.mark.parametrize("output", ["작업 완료", "{}", '{"action":"push","message":"push","authorized":true}',
    '{"action":"continue","message":"go","authorized":false}',
    '{"action":"continue","message":"go","authorized":true,"command":"rm -rf"}',
    '{"action":"repair","message":"fix","authorized":true}'])
def test_invalid_or_unauthorized_model_output_never_becomes_a_tool(output):
    with pytest.raises((ValueError, TypeError)):
        parse_decision(output)


def test_question_and_scope_change_finish_without_execution(project_chat):
    pipeline, state, invoke, *_ = project_chat
    before = pipeline.store.load(state.id).tasks
    for action, message in [("reply", "왜 멈춘 거야?"), ("ask", "완료 조건 없애고 배포해")]:
        parent = accept(pipeline, state, message)
        result = decide(pipeline, state, invoke, parent, action)
        assert result["status"] == "succeeded"
        assert pipeline.advance_chat_control(state.id, parent["request_id"])["next_action"] == "none"
        assert pipeline.store.load(state.id).tasks == before
    args = invoke.call_args
    assert args.args[1].review_sandbox_mode == "read-only"
    assert args.args[1].review_approval_mode == "deny-all"
    assert "available_actions" in args.args[2] and "live owner" in args.args[2]
    assert pipeline._configure_planning_profile.call_args.kwargs["planning_model"] == "chosen"


def test_continue_executes_once_then_ai_reports_actual_result(project_chat):
    pipeline, state, invoke, *_ = project_chat
    parent = accept(pipeline, state)
    decision = decide(pipeline, state, invoke, parent, "continue")

    def finish(run_id, **_):
        current = pipeline.store.load(run_id)
        current.tasks[0].status = TaskStatus.COMPLETED
        current.stage = Stage.READY_TO_MERGE
        pipeline.store.save(current)
        return current

    with patch.object(pipeline, "_resume", side_effect=finish) as resume:
        result = perform(pipeline, state, decision)
        perform(pipeline, state, decision)
        resume.assert_called_once()
    assert result["phase"] == "observed"
    assert result["payload"]["history"][0]["completed"] == 1
    final = decide(pipeline, state, invoke, parent, "reply")
    assert final["status"] == "succeeded"
    assert '"completed": 1' in invoke.call_args.args[2]


@pytest.mark.parametrize("change", ["plan", "conversation", "attempt", "execution", "cancel"])
def test_late_ai_action_cannot_change_a_new_target(project_chat, change):
    pipeline, state, invoke, *_ = project_chat
    parent = accept(pipeline, state)
    decision = decide(pipeline, state, invoke, parent, "continue")
    current = pipeline.store.load(state.id)
    if change == "plan":
        current.tasks[0].acceptance_criteria.append("new criterion")
    elif change == "conversation":
        current.planning_conversation_revision += 1
    elif change == "attempt":
        current.tasks[0].last_attempt_id = "another"
    elif change == "execution":
        pipeline.store.save_execution_control(ExecutionControlRecord(state.id, "new", "task", 1))
    else:
        pipeline.cancel_chat_control(state.id, parent["request_id"])
    pipeline.store.save(current)
    with patch.object(pipeline, "_resume") as resume:
        if change == "cancel":
            assert perform(pipeline, state, decision)["status"] == "interrupted"
        else:
            with pytest.raises(PipelineError, match="변경"):
                perform(pipeline, state, decision)
        resume.assert_not_called()


def test_active_or_unknown_lock_cannot_be_cleared(project_chat):
    pipeline, state, invoke, control, integration = project_chat
    for lock in [RunLockState.ACTIVE, RunLockState.UNVERIFIABLE, RunLockState.MALFORMED]:
        assert "clear_lock" not in pipeline._project_chat_actions(state, replace(control, lock_state=lock), integration, 0)
    parent = accept(pipeline, state)
    decision = decide(pipeline, state, invoke, parent, "clear_lock")
    with patch.object(pipeline, "clear_run_lock") as clear, pytest.raises(PipelineError, match="실행할 수 없는"):
        perform(pipeline, state, decision)
    clear.assert_not_called()


def test_refine_preserves_contract_and_round_trips_notes(project_chat):
    pipeline, state, invoke, *_ = project_chat
    parent = accept(pipeline, state)
    decision = decide(pipeline, state, invoke, parent, "refine", task_id="task", instruction="현재 구현의 예외 처리를 확인한다.")
    result = perform(pipeline, state, decision)
    assert result["phase"] == "observed"
    saved = pipeline.store.load(state.id)
    assert saved.tasks[0].acceptance_criteria == ["original criterion"]
    assert saved.plan_revision == saved.plan_approved_revision == 1
    assert saved.tasks[0].description == state.tasks[0].description
    assert saved.tasks[0].implementation_notes == ["현재 구현의 예외 처리를 확인한다."]
    assert RunState.from_dict(saved.to_dict()).tasks[0].implementation_notes == saved.tasks[0].implementation_notes


def test_failed_repairs_are_bounded_and_failure_is_not_success(project_chat):
    pipeline, state, invoke, *_ = project_chat
    state.stage, state.failed_step = Stage.FAILED, RunStep.AGENT_EXECUTION
    state.tasks[0].status = TaskStatus.FAILED
    pipeline.store.save(state)
    parent = accept(pipeline, state)

    def fail(*_, **__):
        saved = pipeline.store.load(state.id)
        saved.tasks[0].last_attempt_id = str(uuid.uuid4())
        saved.failure_message = "검증 실패"
        pipeline.store.save(saved)
        raise PipelineError("검증 실패")

    with patch.object(pipeline, "task_retry_context", return_value={"fingerprint": "f", "recovery": {"fingerprint": "r"}}), \
         patch.object(pipeline, "repair_task_from_chat", side_effect=fail) as repair:
        for _ in range(MAX_REPAIRS):
            decision = decide(pipeline, state, invoke, parent, "repair", task_id="task", instruction="실패 원인 수정")
            result = perform(pipeline, state, decision)
            assert result["phase"] == "observed"
            assert result["payload"]["history"][-1]["error"] == "검증 실패"
        decision = decide(pipeline, state, invoke, parent, "repair", task_id="task", instruction="한 번 더")
        with pytest.raises(PipelineError, match="실행할 수 없는"):
            perform(pipeline, state, decision)
        assert repair.call_count == MAX_REPAIRS


def test_cancellation_while_ai_is_thinking_discards_its_command(project_chat):
    pipeline, state, invoke, *_ = project_chat
    parent = accept(pipeline, state)

    def cancel(*_, **__):
        pipeline.cancel_chat_control(state.id, parent["request_id"])
        return '{"action":"continue","message":"실행","authorized":true}'

    invoke.side_effect = cancel
    with pytest.raises(PipelineError, match="취소"):
        pipeline.decide_project_chat(state.id, parent["request_id"])
    assert pipeline.advance_chat_control(state.id, parent["request_id"])["next_action"] == "none"


def test_transport_failure_is_not_replayed_after_restart(project_chat):
    pipeline, state, invoke, *_ = project_chat
    parent = accept(pipeline, state)
    decision = decide(pipeline, state, invoke, parent, "continue")
    suspended = pipeline.advance_chat_control(state.id, parent["request_id"], suspend=True)
    assert suspended["operation"]["status"] == "partial"
    with patch.object(pipeline, "_resume") as resume:
        perform(pipeline, state, decision)
        resume.assert_not_called()


def test_actual_repair_entry_keeps_parent_and_executes_with_saved_profiles(project_chat):
    pipeline, state, invoke, *_ = project_chat
    state.stage, state.failed_step = Stage.FAILED, RunStep.AGENT_EXECUTION
    state.tasks[0].status = TaskStatus.FAILED
    pipeline.store.save(state)
    parent = accept(pipeline, state)
    decision = decide(pipeline, state, invoke, parent, "repair", task_id="task", instruction="원인을 수정하고 검증한다.")
    context = {"can_save": True, "fingerprint": "failure", "recovery": {"fingerprint": "recovery", "can_execute": True}}

    def finish(current, **kwargs):
        assert kwargs["recover_saved_profiles"] is True
        assert pipeline.store.load_operation(state.id, parent["request_id"]).phase == "acting"
        current.tasks[0].status = TaskStatus.COMPLETED
        current.stage, current.failed_step, current.failure_message = Stage.READY_TO_MERGE, None, ""
        pipeline.store.save(current)
        return current

    with patch.object(pipeline, "_task_retry_context", return_value=context), \
         patch.object(pipeline, "_task_recovery_capability", return_value={"can_execute": True, "fingerprint": "recovery"}), \
         patch.object(pipeline, "_execute", side_effect=finish) as execute:
        result = perform(pipeline, state, decision)
    execute.assert_called_once()
    assert result["phase"] == "observed"
    assert len(pipeline.store.load_revision_requests(state.id)) == 1
    assert pipeline.store.load(state.id).tasks[0].acceptance_criteria == state.tasks[0].acceptance_criteria


def test_stale_lock_resolution_then_resume_uses_observable_execution_lock(project_chat):
    pipeline, state, invoke, control, integration = project_chat
    stale = replace(control, lock_state=RunLockState.STALE)
    state.stage, state.active_step = Stage.EXECUTING, RunStep.AGENT_EXECUTION
    state.tasks[0].status = TaskStatus.RUNNING
    pipeline.store.save(state)
    parent = accept(pipeline, state, "잠금해제 하고 계속 진행해줘")
    with patch.object(pipeline, "status_with_controls", side_effect=lambda _: (pipeline.store.load(state.id), stale, integration)), \
         patch.object(pipeline, "clear_run_lock") as clear:
        decision = decide(pipeline, state, invoke, parent, "clear_lock")
        perform(pipeline, state, decision)
        clear.assert_called_once_with(state.id, approved=True)
    decision = decide(pipeline, state, invoke, parent, "continue")

    def resume(*_, **__):
        assert pipeline.store.inspect_lock(state.id).operation == "resume"
        current = pipeline.store.load(state.id)
        current.tasks[0].status, current.active_step = TaskStatus.COMPLETED, None
        current.stage = Stage.READY_TO_MERGE
        pipeline.store.save(current)
        return current

    with patch.object(pipeline, "_resume", side_effect=resume):
        assert perform(pipeline, state, decision)["phase"] == "observed"


def test_a_user_stop_during_execution_ends_autonomous_followup(project_chat):
    pipeline, state, invoke, control, integration = project_chat
    parent = accept(pipeline, state)
    decision = decide(pipeline, state, invoke, parent, "continue")
    stopped = False

    def resume(*_, **__):
        nonlocal stopped
        stopped = True
        return pipeline.store.load(state.id)

    def status(_):
        current = replace(control, stop_phase="stopped", stop_request_id="user-stop", execution_id="new-execution") if stopped else control
        return pipeline.store.load(state.id), current, integration

    with patch.object(pipeline, "_resume", side_effect=resume), patch.object(pipeline, "status_with_controls", side_effect=status):
        assert perform(pipeline, state, decision)["status"] == "interrupted"
    assert pipeline.advance_chat_control(state.id, parent["request_id"])["next_action"] == "none"


def test_concurrent_goal_change_is_not_adopted_as_own_progress(project_chat):
    pipeline, state, invoke, *_ = project_chat
    parent = accept(pipeline, state)
    decision = decide(pipeline, state, invoke, parent, "continue")

    def change(*_, **__):
        current = pipeline.store.load(state.id)
        current.plan_revision += 1
        pipeline.store.save(current)
        return current

    with patch.object(pipeline, "_resume", side_effect=change):
        result = perform(pipeline, state, decision)
    assert result["status"] == "failed"
    assert "계획 또는 대화" in result["error"]


def test_saved_advice_reaches_the_actual_executor_without_replacing_original_instructions(project_chat):
    pipeline, state, *_ = project_chat
    state.tasks[0].implementation_notes = ["오류 경로를 먼저 확인한다."]
    with patch.object(pipeline, "_run_executor", side_effect=RuntimeError("executor probe")) as executor:
        with pytest.raises(RuntimeError, match="executor probe"):
            pipeline._run_task_attempt(state, state.tasks[0], TaskAction.EXECUTE, prompt="Original task and acceptance criteria")
    prompt = executor.call_args.args[2]
    assert "Original task and acceptance criteria" in prompt
    assert "오류 경로를 먼저 확인한다." in prompt
