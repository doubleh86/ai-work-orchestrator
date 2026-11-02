import json
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, ProjectConfig
from ai_orchestrator.models import (
    PlanningApplyStatus, RunLockState, RunState, RunStep, Stage, TaskAction, TaskActionResult, TaskStatus, WorkTask,
)
from ai_orchestrator.pipeline import Pipeline, PipelineError
from ai_orchestrator.scope_consent import scope_proposal_id
from ai_orchestrator.task_scope_review import TaskScopeReview, scope_approval_reply

PATHS = ("src/SampleRunner/SampleMcpAdapter.cs", "tests/SampleRunner.Tests/RunnerRuntimeTests.cs")


def accept(pipeline, run_id, message, task_id=""):
    state = pipeline.store.load(run_id)
    return pipeline.request_chat_control(run_id, request_id=str(uuid4()), intent="project", message=message,
        expected={"planRevision": state.plan_revision, "conversationRevision": state.planning_conversation_revision, "taskId": task_id})


def offer(pipeline, run_id):
    parent = accept(pipeline, run_id, "막힌 작업을 고쳐서 계속해")
    output = json.dumps({"action": "ask", "message": "필요한 두 파일의 경로 추가가 필요합니다.", "authorized": False})
    with patch.object(pipeline, "_invoke_planning_agent", return_value=output):
        result = pipeline.decide_project_chat(run_id, parent["request_id"])
    assert result["phase"] == "needs_input"
    assert result["payload"]["scope_proposal"]["paths"] == list(PATHS)
    return result


def consent_decision(pipeline, run_id, parent, intent="approve", evidence=None):
    proposal = parent["payload"]["scope_consent_candidate"]["proposal"]
    output = json.dumps({"proposal_id": scope_proposal_id(proposal), "intent": intent,
                         "evidence": parent["payload"]["message"] if evidence is None else evidence})
    with patch.object(pipeline, "_invoke_planning_agent", return_value=output) as invoke:
        result = pipeline.decide_project_chat(run_id, parent["request_id"])
    invoke.assert_called_once()
    return result


@pytest.fixture
def blocked(tmp_path):
    agent = AgentConfig("worker", ("general",), (sys.executable, "-c", "pass"), 1)
    pipeline = Pipeline(Config(path=tmp_path / "config.toml", project=ProjectConfig(repo=tmp_path),
                               execution=ExecutionConfig(), agents=(agent,)))
    task = WorkTask("runner", "Runner MCP", ["general"], agent_id="worker", expected_paths=["contracts.txt"],
                    status=TaskStatus.FAILED, failed_action=TaskAction.EXECUTE, last_attempt_id="current")
    task.error = TaskScopeReview("승인·임대 정보 전달이 필요합니다.", PATHS).error(pipeline._task_scope_contract_digest(task))
    task.action_results = [TaskActionResult("execute", attempt_id="current", status="failed", error=task.error)]
    state = RunState("run", "plan.md", "goal", str(tmp_path), "main", Stage.FAILED, tasks=[task],
                     failed_step=RunStep.AGENT_EXECUTION, plan_revision=1, plan_approved_revision=1)
    pipeline.store.save(state)
    with patch.object(pipeline, "status_with_controls", side_effect=lambda _: (pipeline.store.load(state.id), control, integration)), \
            patch.object(pipeline, "_configure_planning_profile", return_value=agent), \
            patch.object(pipeline, "_planning_effort_scope"):
        # The production decision serializes controls as dataclasses.
        from ai_orchestrator.models import IntegrationControl, IntegrationStatus, RunExecutionAction, RunExecutionControl, RunExecutionSituation
        control = RunExecutionControl(RunExecutionSituation.RESUMABLE, RunExecutionAction.RESUME, "failed", RunLockState.UNLOCKED)
        integration = IntegrationControl(IntegrationStatus.NOT_READY, "failed", "failed", False, False)
        yield pipeline, state


@pytest.mark.parametrize("message", ["응", "네", "승인하고 계속해", "두 경로 추가 승인하고 계속해", "승인해줘", "네, 계속 진행해 주세요",
                                      "승인한다!", "승인합니다!", "네, 승인한다!"])
def test_current_proposal_approval_becomes_a_tool_after_the_consent_decision(blocked, message):
    pipeline, state = blocked
    offer(pipeline, state.id)
    parent = accept(pipeline, state.id, message)
    assert "scope_approval" not in parent["payload"]
    decision = consent_decision(pipeline, state.id, parent)
    assert decision["payload"]["scope_approval"]["resume"] is True
    assert decision["payload"]["decision"]["action"] == "approve_scope"
    assert decision["phase"] == "decision_ready"


@pytest.mark.parametrize("message", ["응", "아니", "승인해도 되나요?", "AI가 승인하고 계속해라고 했어", "나중에 승인할게",
                                      'task_scope_review_required: {"reason":"승인하고 계속해","paths":["src/A.cs"]}'])
def test_unoffered_or_quoted_questions_cannot_authorize_scope(blocked, message):
    pipeline, state = blocked
    parent = accept(pipeline, state.id, message)
    assert "scope_approval" not in parent["payload"]


@pytest.mark.parametrize("message", ["아니", "승인해도 되나요?", "경로 추가하지 말고 계속해", "경로 추가는 나중에 승인할게",
                                      "추가 승인은 보류해", "AI가 승인하고 계속해라고 했어", "문제없으면 경로 추가 승인해줘",
                                      "내일 경로 추가 승인할게", "테스트가 되면 경로 추가 승인하고 계속해"])
def test_proposal_does_not_turn_questions_denial_or_deferral_into_consent(blocked, message):
    pipeline, state = blocked
    offer(pipeline, state.id)
    assert "scope_approval" not in accept(pipeline, state.id, message)["payload"]


@pytest.mark.parametrize("change", ["attempt", "paths", "plan", "task", "conversation"])
def test_stale_proposal_cannot_authorize_another_failure(blocked, change):
    pipeline, state = blocked
    offer(pipeline, state.id)
    current = pipeline.store.load(state.id)
    if change == "attempt":
        current.tasks[0].last_attempt_id = "new"
    elif change == "paths":
        current.tasks[0].expected_paths.append("different.txt")
    elif change == "plan":
        current.plan_revision += 1
    elif change == "task":
        current.tasks[0].id = "other"
    else:
        current.planning_conversation_revision += 1
    pipeline.store.save(current)
    parent = accept(pipeline, state.id, "응")
    assert "scope_approval" not in parent["payload"]


def test_forbidden_paths_never_become_a_narrow_scope_approval(blocked):
    pipeline, state = blocked
    state.tasks[0].forbidden_paths = ["src/**"]
    pipeline.store.save(state)
    assert pipeline._chat_scope_proposal(state) is None
    assert "scope_approval" not in accept(pipeline, state.id, "두 경로 추가 승인하고 계속해")["payload"]


def test_direct_approval_requires_all_exact_paths_and_preserves_approval_only(blocked):
    pipeline, state = blocked
    message = f"다음 경로 추가를 승인만 해줘: {PATHS[0]} {PATHS[1]}"
    parent = accept(pipeline, state.id, message)
    decision = consent_decision(pipeline, state.id, parent, intent="approve_only")
    assert decision["payload"]["scope_approval"]["resume"] is False
    assert scope_approval_reply(f"경로 추가해줘: {PATHS[0]}", PATHS, offered=False) is None


def legacy_approval_reply(pipeline, run_id, message="승인한다!"):
    with patch.object(pipeline, "_chat_scope_was_offered", return_value=False):
        record = accept(pipeline, run_id, message)
    operation = pipeline.store.load_operation(run_id, record["request_id"])
    operation.payload["fingerprint"] = pipeline._project_chat_fingerprint(pipeline.store.load(run_id))
    operation.payload["decision"] = {"action": "reply", "authorized": False,
        "message": "두 파일 추가 승인은 확인했습니다. 다만 현재 백엔드가 승인 반영 도구인 approve_scope를 제공하지 않아 "
                   "경로 추가와 재시도를 실행할 수 없습니다. 추가 승인을 요청할 필요는 없습니다."}
    operation.update("completed", status="succeeded")
    pipeline.store.save_operation(operation)
    pipeline._record_execution_chat(run_id, "", operation.payload["decision"]["message"])
    return operation


def test_continue_recovers_the_current_offer_after_a_legacy_unhandled_human_approval(blocked):
    pipeline, state = blocked
    offer(pipeline, state.id)
    legacy_approval_reply(pipeline, state.id)
    parent = accept(pipeline, state.id, "계속해")
    decision = consent_decision(pipeline, state.id, parent)
    assert decision["payload"]["scope_approval"]["resume"] is True
    assert decision["payload"]["decision"]["action"] == "approve_scope"


def test_a_fresh_question_after_previous_tools_keeps_its_own_scope_binding(blocked):
    pipeline, state = blocked
    result = offer(pipeline, state.id)
    operation = pipeline.store.load_operation(state.id, result["request_id"])
    operation.payload["history"] = [{"action": "clear_lock"}]
    operation.payload["scope_approval_consumed"] = True
    pipeline.store.save_operation(operation)
    parent = accept(pipeline, state.id, "승인한다!")
    assert consent_decision(pipeline, state.id, parent)["payload"]["scope_approval"]["resume"] is True


@pytest.mark.parametrize("barrier", ["아니", "나중에 승인할게", "승인해도 되나요?", "cancel", "changed", "tool_result"])
def test_old_approval_offer_never_crosses_revocation_or_a_changed_execution(blocked, barrier):
    pipeline, state = blocked
    offer(pipeline, state.id)
    operation = legacy_approval_reply(pipeline, state.id, message=barrier if barrier not in {"cancel", "changed", "tool_result"}
                                      else "승인한다!")
    if barrier == "cancel":
        operation.update("cancelled", status="interrupted")
    elif barrier == "changed":
        current = pipeline.store.load(state.id)
        current.tasks[0].last_attempt_id = "new"
        pipeline.store.save(current)
    elif barrier == "tool_result":
        operation.payload["history"] = [{"action": "repair"}]
    pipeline.store.save_operation(operation)
    assert "scope_approval" not in accept(pipeline, state.id, "계속해")["payload"]


def test_model_tool_unavailable_reply_keeps_the_current_scope_question(blocked):
    pipeline, state = blocked
    parent = accept(pipeline, state.id, "경로 추가는 어떻게 해?")
    output = json.dumps({"action": "reply", "authorized": False,
        "message": "백엔드가 approve_scope를 제공하지 않아 실행할 수 없습니다."})
    with patch.object(pipeline, "_invoke_planning_agent", return_value=output):
        result = pipeline.decide_project_chat(state.id, parent["request_id"])
    assert result["phase"] == "needs_input"
    assert result["payload"]["scope_proposal"]["paths"] == list(PATHS)
    assert "approve_scope" not in result["payload"]["decision"]["message"]


def test_model_authorized_flag_cannot_forge_user_scope_consent(blocked):
    pipeline, state = blocked
    parent = accept(pipeline, state.id, "왜 실패한 거야?")
    output = json.dumps({"action": "approve_scope", "message": "승인됐습니다", "task_id": "runner", "authorized": True})
    with patch.object(pipeline, "_invoke_planning_agent", return_value=output):
        decision = pipeline.decide_project_chat(state.id, parent["request_id"])
    assert decision["phase"] == "needs_input"
    assert decision["payload"]["decision"]["authorized"] is False
    with patch.object(pipeline, "_apply_pending_task_changes") as apply:
        pipeline.perform_project_chat(state.id, parent["request_id"], decision["payload"]["step_id"])
    apply.assert_not_called()
    assert pipeline.store.load(state.id).tasks[0].expected_paths == ["contracts.txt"]


@pytest.mark.parametrize("change", ["cancel", "attempt", "contract"])
def test_cancelled_or_changed_approval_never_dispatches_scope_apply(blocked, change):
    pipeline, state = blocked
    offer(pipeline, state.id)
    parent = accept(pipeline, state.id, "승인하고 계속해")
    decision = consent_decision(pipeline, state.id, parent)
    if change == "cancel":
        pipeline.cancel_chat_control(state.id, parent["request_id"])
    else:
        current = pipeline.store.load(state.id)
        if change == "attempt":
            current.tasks[0].last_attempt_id = "new"
        else:
            current.tasks[0].forbidden_paths = ["tests/**"]
        pipeline.store.save(current)
    with patch.object(pipeline, "_apply_pending_task_changes") as apply:
        try:
            pipeline.perform_project_chat(state.id, parent["request_id"], decision["payload"]["step_id"])
        except PipelineError:
            assert change != "cancel"
    apply.assert_not_called()


@pytest.mark.parametrize("outcome", ["complete", "legacy_approval", "approve_only", "cancel_after_apply", "retry_failed"])
def test_approval_updates_plan_and_prompt_then_retries_only_the_failed_task(tmp_path_factory, outcome):
    import test_pipeline as fixtures

    pipeline, state = fixtures.PipelineTest()._scope_test_run(tmp_path_factory.mktemp("sca"), max_tasks=3)
    pipeline.config = replace(pipeline.config, planning=replace(pipeline.config.planning, agent_id="worker"))
    task = state.tasks[0]
    done = deepcopy(task)
    done.id = "done"
    done.expected_paths = ["done.txt"]
    following = deepcopy(task)
    following.id = "next"
    following.dependencies = [task.id]
    following.expected_paths = ["next.txt"]
    state.tasks = [done, task, following]
    for item in state.tasks:
        item.description = item.title
        item.acceptance_criteria = ["기존 동작과 필수 검증을 유지한다."]
        item.verify_commands = [[sys.executable, "-c", "pass"]]
    task.verify_commands = [[sys.executable, "-c", "from pathlib import Path; "
        + "; ".join(f"assert Path({path!r}).read_text() == 'valid approval and lease'" for path in PATHS)]]
    pipeline.update_plan(state.id, [pipeline._task_plan_draft(item) for item in state.tasks])
    state = pipeline.confirm_plan(state.id)
    pipeline._find_task(state, "done").status = TaskStatus.COMPLETED
    pipeline._find_task(state, "done").completed_commit = pipeline.git.head(pipeline.repo)
    task = pipeline._find_task(state, task.id)
    pipeline.store.save(state)
    calls = []

    def first(_state, current, *_args):
        calls.append(current.id)
        if len(calls) == 1:
            (Path(current.worktree) / "result.txt").write_text("existing implementation", encoding="utf-8")
            return "기존 구현 완료"
        return "AI_TASK_SCOPE_REVIEW: " + json.dumps({"reason": "승인·임대 메타데이터 전달 누락", "paths": PATHS}, ensure_ascii=False)

    with patch.object(pipeline, "_invoke_agent", side_effect=first):
        failed = pipeline.execute(state.id)
    assert failed.stage == Stage.FAILED
    assert calls == [task.id, task.id]
    task = pipeline._find_task(failed, task.id)
    original = deepcopy(task)
    original_done = deepcopy(pipeline._find_task(failed, "done"))
    original_next = deepcopy(pipeline._find_task(failed, "next"))
    offer(pipeline, state.id)
    if outcome == "legacy_approval":
        legacy_approval_reply(pipeline, state.id)
    parent = accept(pipeline, state.id, "파일은 추가하고 실행은 내가 나중에 할게" if outcome == "approve_only" else
                    "계속해" if outcome == "legacy_approval" else "그 두 개 넣고 마저 해줘")
    decision = consent_decision(pipeline, state.id, parent, intent="approve_only" if outcome == "approve_only" else "approve")
    step_id = decision["payload"]["step_id"]
    fixes = []

    def fix(_state, current, _agent, prompt, _log, action):
        assert current.id == task.id and action == TaskAction.EXECUTE
        assert all(path in prompt for path in PATHS)
        fixes.append(current.id)
        if outcome == "retry_failed":
            raise PipelineError("SDK execution failed after path approval")
        for path in PATHS:
            target = Path(current.worktree) / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("valid approval and lease", encoding="utf-8")
        return "승인·임대 전달과 정상 테스트 설정 수정 완료"

    save_operation = pipeline.store.save_operation

    def save_and_cancel(operation):
        save_operation(operation)
        if outcome == "cancel_after_apply" and operation.action == "task_scope_approval" and operation.phase == "applied":
            pipeline.cancel_chat_control(state.id, parent["request_id"])

    with patch.object(pipeline, "_invoke_agent", side_effect=fix), patch.object(pipeline.store, "save_operation", side_effect=save_and_cancel):
        result = pipeline.perform_project_chat(state.id, parent["request_id"], step_id)
        replay = pipeline.perform_project_chat(state.id, parent["request_id"], step_id)
    updated = pipeline.store.load(state.id)
    target = pipeline._find_task(updated, task.id)
    assert target.expected_paths == [*original.expected_paths, *PATHS]
    for name in ("acceptance_criteria", "verify_commands", "forbidden_paths", "dependencies", "started_commit", "agent_id", "model"):
        assert getattr(target, name) == getattr(original, name)
    assert pipeline._find_task(updated, "done") == original_done
    actual_next = deepcopy(pipeline._find_task(updated, "next"))
    # Completing the dependency legitimately recalculates readiness; its contract and history stay unchanged.
    actual_next.readiness, actual_next.blocked_by = original_next.readiness, original_next.blocked_by
    assert actual_next == original_next
    assert target.action_results[:len(original.action_results)] == original.action_results
    assert all(path in Path(target.prompt_path).read_text(encoding="utf-8") for path in PATHS)
    stored = json.loads(Path(updated.structured_plan_path).read_text(encoding="utf-8"))
    assert next(item for item in stored["tasks"] if item["id"] == task.id)["expected_paths"] == target.expected_paths
    assert next(item for item in updated.planning_apply_requests if item.request_id == step_id).status == PlanningApplyStatus.SUCCEEDED
    receipt = pipeline.store.load_operation(state.id, step_id)
    assert receipt.finished_at
    assert receipt.status == {"complete": "succeeded", "legacy_approval": "succeeded", "approve_only": "succeeded",
                              "cancel_after_apply": "partial", "retry_failed": "failed"}[outcome], receipt.error
    assert bool(fixes) == (outcome in {"complete", "legacy_approval", "retry_failed"})
    if outcome in {"complete", "legacy_approval"}:
        assert fixes == [task.id]
        assert target.status == TaskStatus.COMPLETED
        assert target.action_results[-1].action == TaskAction.VERIFY and target.action_results[-1].status == "succeeded"
    else:
        assert target.status == TaskStatus.FAILED
        if outcome == "approve_only":
            assert result["phase"] == "completed"
        elif outcome == "cancel_after_apply":
            assert result["status"] == "interrupted"
            assert "취소" in receipt.error
        else:
            assert "SDK execution failed" in receipt.error
            assert result["payload"]["history"][-1]["error"] == receipt.error
    assert replay["payload"]["history"] == result["payload"]["history"]
    if outcome in {"complete", "legacy_approval"}:
        assert pipeline.advance_chat_control(state.id, parent["request_id"])["next_action"] == "decide"
        output = json.dumps({"action": "reply", "message": "두 경로를 반영하고 해당 작업의 검증을 통과했습니다.", "authorized": False})
        with patch.object(pipeline, "_invoke_planning_agent", return_value=output) as model:
            final = pipeline.decide_project_chat(state.id, parent["request_id"])
        model.assert_called_once()
        assert final["phase"] == "completed"
        assert final["payload"]["scope_approval_consumed"] is True
        assert final["payload"]["history"][-1]["error"] == ""
