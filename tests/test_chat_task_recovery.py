from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import uuid

import pytest

from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, ProjectConfig
from ai_orchestrator.models import (
    ExecutionControlRecord, PlanningMessage, PlanningMessageRole, RunArchive, RunState, RunStep, Stage,
    TaskAction, TaskActionResult, TaskStatus, WorkTask,
)
from ai_orchestrator.pipeline import Pipeline, PipelineError


@pytest.fixture
def recovery(tmp_path: Path) -> tuple[Pipeline, RunState]:
    repo = tmp_path / "repo"
    repo.mkdir()
    agent = AgentConfig("claude", ("general",), (), provider_id="claude", model="opus")
    pipeline = Pipeline(Config(path=tmp_path / "config.toml", project=ProjectConfig(repo=repo),
                               execution=ExecutionConfig(), agents=(agent,)))
    state = RunState(
        id="chat-recovery", spec_path="", spec_digest="digest", repo_path=str(repo), main_branch="main",
        stage=Stage.FAILED, failed_step=RunStep.AGENT_EXECUTION, plan_revision=3, plan_approved_revision=3,
        planning_conversation_revision=2,
        planning_messages=[PlanningMessage(PlanningMessageRole.USER, "왜 실패했어?"),
                           PlanningMessage(PlanningMessageRole.ASSISTANT, "제한 시간을 늘리기 전에 멈춘 테스트를 찾아 수정하세요.")],
        tasks=[WorkTask("done", "완료 작업", ["general"], status=TaskStatus.COMPLETED, completed_commit="a" * 40),
               WorkTask("broken", "테스트 복구", ["general"], status=TaskStatus.FAILED, failed_action=TaskAction.VERIFY,
                        agent_id="claude", provider_id="claude", model="opus", last_attempt_id="old-attempt",
                        error="test timed out", acceptance_criteria=["all tests pass"], verify_commands=[["test", "all"]]),
               WorkTask("next", "후속 작업", ["general"], dependencies=["broken"])],
    )
    state.refresh_task_readiness()
    pipeline.store.save(state)
    return pipeline, state


def request(pipeline: Pipeline, state: RunState, **overrides: object) -> dict[str, object]:
    return {"request_id": str(uuid.uuid4()), "message": "고쳐서 계속해줘",
            "fingerprint": pipeline.task_retry_context(state.id, "broken")["fingerprint"],
            "conversation_revision": state.planning_conversation_revision, **overrides}


def test_chat_repair_saves_advice_before_execution_and_preserves_contract_and_completed_work(recovery) -> None:
    pipeline, state = recovery
    arguments = request(pipeline, state)
    original = deepcopy(state.tasks)

    def execute(current: RunState, *, manual: bool, recover_saved_profiles: bool) -> RunState:
        assert manual is False
        assert recover_saved_profiles is True
        assert pipeline.store.inspect_lock(state.id).operation == "retry-task"
        saved = pipeline.store.load_revision_requests(state.id)
        assert len(saved) == 1
        assert saved[0]["handling"] == "same_task_retry"
        assert "멈춘 테스트를 찾아 수정" in saved[0]["text"]
        assert "고쳐서 계속해줘" in pipeline._result_revision_retry_instruction(state.id, "broken")
        assert current.tasks[1].failed_action == TaskAction.EXECUTE, "verification-only retry would bypass the requested correction"
        assert current.tasks[0] == original[0]
        assert current.tasks[2] == original[2]
        assert (current.tasks[1].agent_id, current.tasks[1].provider_id, current.tasks[1].model) == ("claude", "claude", "opus")
        assert current.tasks[1].verify_commands == original[1].verify_commands
        assert current.tasks[1].acceptance_criteria == original[1].acceptance_criteria
        assert current.tasks[1].error == "test timed out"
        assert current.planning_messages[-2].text == "고쳐서 계속해줘"
        assert "복구 작업을 시작" in current.planning_messages[-1].text
        assert current.planning_conversation_revision == 2, "operational receipts are not unapplied plan changes"
        current.tasks[1].status = TaskStatus.COMPLETED
        current.tasks[2].status = TaskStatus.COMPLETED
        current.stage = Stage.READY_TO_MERGE
        current.failed_step = None
        pipeline.store.save(current)
        return current

    with patch.object(pipeline, "_execute", side_effect=execute) as run:
        result = pipeline.repair_task_from_chat(state.id, "broken", **arguments)
        replay = pipeline.repair_task_from_chat(state.id, "broken", **arguments)
    assert result.stage == replay.stage == Stage.READY_TO_MERGE
    assert run.call_count == 1
    assert len(pipeline.store.load(state.id).planning_messages) == 4
    assert len(pipeline.store.list_runs()) == 1


@pytest.mark.parametrize("change", ["task", "conversation", "planning", "active", "another_failure", "waiting", "archive"])
def test_changed_or_ineligible_recovery_never_saves_instructions_or_executes(recovery, change: str) -> None:
    pipeline, state = recovery
    arguments = request(pipeline, state)
    if change == "task":
        state.tasks[1].last_attempt_id = "new-attempt"
    elif change == "conversation":
        state.planning_conversation_revision += 1
    elif change == "planning":
        state.failed_step = RunStep.PLANNING
    elif change == "active":
        state.active_step = RunStep.AGENT_EXECUTION
    elif change == "another_failure":
        state.tasks[2].status = TaskStatus.FAILED
    elif change == "waiting":
        state.tasks[2].status = TaskStatus.WAITING
    else:
        state.archive = RunArchive("now", "rev", "snapshot", "manifest", "summary", "fingerprint")
    pipeline.store.save(state)
    with patch.object(pipeline, "_execute") as execute:
        with pytest.raises(PipelineError):
            pipeline.repair_task_from_chat(state.id, "broken", **arguments)
    execute.assert_not_called()
    assert pipeline.store.load_revision_requests(state.id) == []
    assert len(pipeline.store.load(state.id).planning_messages) == 2


def test_chat_instruction_save_failure_does_not_start_or_claim_recovery(recovery) -> None:
    pipeline, state = recovery
    arguments = request(pipeline, state)
    with patch.object(pipeline.store, "save_revision_requests", side_effect=OSError("disk full")), patch.object(pipeline, "_execute") as run:
        with pytest.raises(OSError, match="disk full"):
            pipeline.repair_task_from_chat(state.id, "broken", **arguments)
    run.assert_not_called()
    assert len(pipeline.store.load(state.id).planning_messages) == 2


def test_failed_execution_is_not_replayed_and_does_not_hide_failure(recovery) -> None:
    pipeline, state = recovery
    arguments = request(pipeline, state)
    with patch.object(pipeline, "_execute", side_effect=PipelineError("worker failed again")) as run:
        with pytest.raises(PipelineError, match="worker failed again"):
            pipeline.repair_task_from_chat(state.id, "broken", **arguments)
        replay = pipeline.repair_task_from_chat(state.id, "broken", **arguments)
        with pytest.raises(PipelineError, match="같은 요청 ID"):
            pipeline.repair_task_from_chat(state.id, "broken", **{**arguments, "message": "수정해줘"})
    assert run.call_count == 1
    assert replay.stage == Stage.FAILED and replay.tasks[1].status == TaskStatus.FAILED
    assert replay.tasks[2].status == TaskStatus.PENDING


def test_chat_recovery_will_not_run_while_another_request_holds_the_run_lock(recovery) -> None:
    pipeline, state = recovery
    arguments = request(pipeline, state)
    with pipeline.store.lock(state.id, "execute"), patch.object(pipeline, "_execute") as run:
        with pytest.raises(Exception, match="lock"):
            pipeline.repair_task_from_chat(state.id, "broken", **arguments)
    run.assert_not_called()
    assert pipeline.store.load_revision_requests(state.id) == []


@pytest.mark.parametrize("source", ["other_task", "older_attempt"])
def test_other_task_or_previous_attempt_advice_is_not_copied_to_the_current_recovery(recovery, source: str) -> None:
    pipeline, state = recovery
    if source == "other_task":
        state.planning_messages[0].text = "질문 대상 Task: done · 완료 작업\n내용을 설명해 주세요."
    else:
        state.planning_messages[-1].at = "2026-01-01T00:00:00+00:00"
        state.tasks[1].action_results = [TaskActionResult("verify", status="failed", finished_at="2026-01-02T00:00:00+00:00")]
    pipeline.store.save(state)
    with patch.object(pipeline, "_execute", side_effect=lambda current, **_: current):
        pipeline.repair_task_from_chat(state.id, "broken", **request(pipeline, state))
    instruction = pipeline.store.load_revision_requests(state.id)[0]["text"]
    assert "별도 상담 없음" in instruction
    assert state.planning_messages[-1].text not in instruction


@pytest.mark.parametrize("phase", ["stopped", "stopping", "confirmation_required", "finished"])
def test_stopped_task_recovers_only_after_the_matching_stop_is_confirmed(recovery, phase: str) -> None:
    pipeline, state = recovery
    state.stage = Stage.EXECUTING
    state.failed_step = None
    task = state.tasks[1]
    task.status = TaskStatus.STOPPED
    task.stop_request_id = str(uuid.uuid4())
    task.action_results = [TaskActionResult("execute", attempt_id=task.last_attempt_id, status="interrupted", error="stopped")]
    pipeline.store.save(state)
    pipeline.store.save_execution_control(ExecutionControlRecord(
        run_id=state.id, execution_id=str(uuid.uuid4()), scope="task", owner_pid=123, phase=phase,
        stop_request_id=task.stop_request_id, task_id=task.id,
    ))
    context = pipeline.task_retry_context(state.id, task.id)
    assert context["can_save"] is (phase == "stopped")

    def execute(current: RunState, *, manual: bool, recover_saved_profiles: bool) -> RunState:
        assert manual is False
        assert recover_saved_profiles is True
        restored = current.tasks[1]
        assert restored.status == TaskStatus.PENDING
        assert restored.failed_action == TaskAction.EXECUTE
        assert restored.action_results[-1].status == "interrupted"
        assert restored.stop_request_id == task.stop_request_id
        assert "멈춘 테스트" in pipeline._result_revision_retry_instruction(state.id, task.id)
        assert current.tasks[0].completed_commit == "a" * 40
        return current

    with patch.object(pipeline, "_execute", side_effect=execute) as run:
        if phase == "stopped":
            pipeline.repair_task_from_chat(state.id, task.id, **request(pipeline, state))
            run.assert_called_once()
        else:
            with pytest.raises(PipelineError):
                pipeline.repair_task_from_chat(state.id, task.id, **request(pipeline, state))
            run.assert_not_called()


def test_chat_stop_records_one_command_without_changing_the_plan_or_task_results(recovery) -> None:
    pipeline, state = recovery
    execution_id = str(uuid.uuid4())
    pipeline.store.save_execution_control(ExecutionControlRecord(
        run_id=state.id, execution_id=execution_id, scope="task", owner_pid=123,
        active_targets={"broken": {"task_title": "테스트 복구", "attempt_id": "old-attempt", "invocation_id": "invocation"}},
    ))
    params = {"request_id": str(uuid.uuid4()), "execution_id": execution_id, "scope": "task", "task_id": "broken",
              "attempt_id": "old-attempt", "invocation_id": "invocation", "chat_message": "현재 진행 멈춰줘"}
    receipt = pipeline.request_stop(state.id, **params)
    replay = pipeline.request_stop(state.id, **params)
    assert receipt.phase == replay.phase == "stopping"
    saved = pipeline.store.load(state.id)
    assert saved.tasks == state.tasks
    assert saved.planning_conversation_revision == state.planning_conversation_revision
    assert [item.text for item in saved.planning_messages].count("현재 진행 멈춰줘") == 1
    assert "중지 요청을 접수" in saved.planning_messages[-1].text


def test_verification_repair_records_one_chat_command_on_repeated_delivery(recovery) -> None:
    pipeline, state = recovery
    state.stage = Stage.READY_TO_MERGE
    state.failed_step = None
    pipeline.store.save(state)
    params = {"request_id": str(uuid.uuid4()), "chat_message": "검증 오류 복구 진행해줘"}
    with patch.object(pipeline, "_verify_locked", return_value=state) as verify:
        pipeline.verify_and_repair(state.id, **params)
        pipeline.verify_and_repair(state.id, **params)
    verify.assert_called_once()
    saved = pipeline.store.load(state.id)
    assert [item.text for item in saved.planning_messages].count(params["chat_message"]) == 1
    assert saved.planning_conversation_revision == state.planning_conversation_revision
