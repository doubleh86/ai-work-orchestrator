from pathlib import Path
from unittest.mock import patch
import uuid

import pytest

from ai_orchestrator.config import Config, ProjectConfig, ExecutionConfig
from ai_orchestrator.models import (
    ExecutionControlRecord, OperationRecord, RunArchive, IntegrationControl, IntegrationStatus, RunExecutionAction, RunExecutionControl, RunExecutionSituation,
    RunLockState, RunState, RunStep, Stage, TaskStatus, WorkTask,
)
from ai_orchestrator.pipeline import Pipeline, PipelineError


@pytest.fixture
def control(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    pipeline = Pipeline(Config(path=tmp_path / "config.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=()))
    state = RunState(id="group", spec_path="plan.md", spec_digest="digest", repo_path=str(repo), main_branch="main",
                     stage=Stage.FAILED, failed_step=RunStep.AGENT_EXECUTION,
                     tasks=[WorkTask(id="task", title="Original", capabilities=["general"], status=TaskStatus.FAILED,
                                     last_attempt_id="attempt", error="test failed")])
    pipeline.store.save(state)
    execution = RunExecutionControl(RunExecutionSituation.RESUMABLE, RunExecutionAction.RESUME, "stopped", RunLockState.UNLOCKED)
    integration = IntegrationControl(IntegrationStatus.NEEDS_VERIFICATION, "verify", "needs_verification", False, False)
    expected = {"planRevision": state.plan_revision, "conversationRevision": state.planning_conversation_revision,
                "executionId": "", "scope": "", "taskId": "task", "attemptId": "attempt", "invocationId": ""}
    with patch.object(pipeline, "status_with_controls", side_effect=lambda _: (pipeline.store.load(state.id), execution, integration)):
        yield pipeline, state, expected


def accept(pipeline, state, expected):
    return pipeline.request_chat_control(state.id, request_id=str(uuid.uuid4()), intent="repair", message="고쳐서 계속해줘", expected=expected)


def test_parent_receipt_is_idempotent_and_does_not_increment_discussion(control):
    pipeline, state, expected = control
    record = accept(pipeline, state, expected)
    again = pipeline.request_chat_control(state.id, request_id=record["request_id"], intent="repair", message="고쳐서 계속해줘", expected=expected)
    assert record["payload"]["recovery_id"] == again["payload"]["recovery_id"]
    saved = pipeline.store.load(state.id)
    assert saved.planning_conversation_revision == state.planning_conversation_revision
    assert [item.text for item in saved.planning_messages].count("고쳐서 계속해줘") == 1


@pytest.mark.parametrize("change", ["attempt", "plan", "conversation"])
def test_real_target_changes_block_recovery_and_leave_a_reason(control, change):
    pipeline, state, expected = control
    record = accept(pipeline, state, expected)
    current = pipeline.store.load(state.id)
    if change == "attempt":
        current.tasks[0].last_attempt_id = "new-attempt"
    elif change == "plan":
        current.plan_revision += 1
    else:
        current.planning_conversation_revision += 1
    pipeline.store.save(current)
    result = pipeline.advance_chat_control(state.id, record["request_id"])
    assert result["next_action"] == "none"
    assert result["operation"]["phase"] == "blocked"
    assert pipeline.store.load(state.id).planning_messages[-1].text


def test_cancel_after_advance_rejects_the_late_child_before_any_work(control):
    pipeline, state, expected = control
    parent = accept(pipeline, state, expected)
    next_step = pipeline.advance_chat_control(state.id, parent["request_id"])
    assert next_step["next_action"] == "repair"
    cancelled = pipeline.cancel_chat_control(state.id, parent["request_id"])
    assert cancelled["phase"] == "cancelled"
    params = next_step["params"]
    with patch.object(pipeline, "_execute") as execute, pytest.raises(PipelineError, match="취소"):
        pipeline.repair_task_from_chat(state.id, "task", request_id=params["requestId"], message=params["message"],
                                      fingerprint=params["fingerprint"], conversation_revision=params["conversationRevision"],
                                      parent_request_id=parent["request_id"])
    execute.assert_not_called()


def test_child_repair_claims_once_and_preserves_parent_identity(control):
    pipeline, state, expected = control
    parent = accept(pipeline, state, expected)
    next_step = pipeline.advance_chat_control(state.id, parent["request_id"])
    params = next_step["params"]

    def execute(current, **_):
        assert pipeline.cancel_chat_control(current.id, parent["request_id"])["phase"] == "repairing"
        current.tasks[0].status = TaskStatus.COMPLETED
        current.stage = Stage.READY_TO_MERGE
        pipeline.store.save(current)
        return current

    kwargs = dict(request_id=params["requestId"], message=params["message"], fingerprint=params["fingerprint"],
                  conversation_revision=params["conversationRevision"], parent_request_id=parent["request_id"])
    with patch.object(pipeline, "_execute", side_effect=execute) as work:
        pipeline.repair_task_from_chat(state.id, "task", **kwargs)
        with pytest.raises(PipelineError):
            pipeline.repair_task_from_chat(state.id, "task", **kwargs)
    assert work.call_count == 1
    assert pipeline.store.load_operation(state.id, parent["request_id"]).phase == "completed"
    assert [item.text for item in pipeline.store.load(state.id).planning_messages].count("고쳐서 계속해줘") == 1


@pytest.mark.parametrize("stage", [Stage.EXECUTING, Stage.VERIFIED, Stage.PUSHED])
def test_reply_interruption_keeps_original_run_and_tasks(control, stage):
    pipeline, state, _ = control
    state.stage = stage
    state.active_step = None
    pipeline.store.save(state)
    baseline = pipeline.store.load(state.id)
    request_id = str(uuid.uuid4())
    pipeline.begin_planning_request(state.id, request_id=request_id, kind="chat")
    result = pipeline.finish_planning_request(state.id, request_id=request_id, phase="interrupted")
    saved = pipeline.store.load(state.id)
    assert result["phase"] == "interrupted"
    assert saved.stage == stage
    assert saved.tasks == baseline.tasks
    assert saved.planning_conversation_revision == state.planning_conversation_revision


def test_planned_reply_interruption_is_not_a_planning_failure(control):
    pipeline, state, _ = control
    state.stage = Stage.PLANNED
    state.failed_step = None
    state.active_step = RunStep.PLANNING
    pipeline.store.save(state)
    baseline = pipeline.store.load(state.id)
    request_id = str(uuid.uuid4())
    pipeline.begin_planning_request(state.id, request_id=request_id, kind="chat")
    pipeline.finish_planning_request(state.id, request_id=request_id, phase="interrupted")
    saved = pipeline.store.load(state.id)
    assert saved.stage == Stage.PLANNED and saved.active_step is None and saved.failed_step is None


@pytest.mark.parametrize("phase", ["stopping", "confirmation_required", "stopped"])
def test_stop_and_repair_requires_confirmed_stop_receipt_and_unlock(control, phase):
    pipeline, state, expected = control
    state.stage = Stage.EXECUTING
    state.tasks[0].status = TaskStatus.RUNNING
    state.tasks[0].active_invocation_id = "invocation"
    pipeline.store.save(state)
    expected.update(executionId="execution", scope="task", invocationId="invocation")
    active = RunExecutionControl(RunExecutionSituation.RUNNING, RunExecutionAction.NONE, "running", RunLockState.ACTIVE,
                                 execution_id="execution", stop_scope="task", can_stop=True)
    integration = IntegrationControl(IntegrationStatus.NEEDS_VERIFICATION, "verify", "needs_verification", False, False)
    parent = pipeline.request_chat_control(state.id, request_id=str(uuid.uuid4()), intent="stop_repair", message="멈추고 복구해줘", expected=expected)
    with patch.object(pipeline, "status_with_controls", return_value=(pipeline.store.load(state.id), active, integration)):
        first = pipeline.advance_chat_control(state.id, parent["request_id"])
    assert first["next_action"] == "stop"
    stop = OperationRecord(first["params"]["requestId"], state.id, "stop", "digest", phase)
    pipeline.store.claim_operation(stop)
    if phase == "stopped":
        state.tasks[0].status = TaskStatus.STOPPED
        state.tasks[0].active_invocation_id = ""
        state.tasks[0].stop_request_id = stop.request_id
        pipeline.store.save(state)
        pipeline.store.save_execution_control(ExecutionControlRecord(state.id, "execution", "task", 1, phase="stopped", stop_request_id=stop.request_id))
    stopped = RunExecutionControl(RunExecutionSituation.RESUMABLE, RunExecutionAction.RESUME, "stopped",
                                  RunLockState.UNLOCKED if phase == "stopped" else RunLockState.ACTIVE,
                                  execution_id="execution", stop_scope="task", stop_phase=phase)
    with patch.object(pipeline, "status_with_controls", return_value=(pipeline.store.load(state.id), stopped, integration)):
        result = pipeline.advance_chat_control(state.id, parent["request_id"])
    assert result["next_action"] == ("repair" if phase == "stopped" else "none")
    if phase == "confirmation_required":
        assert result["operation"]["status"] == "failed"


def test_execution_change_between_advance_and_child_claim_is_rejected(control):
    pipeline, state, expected = control
    parent = accept(pipeline, state, expected)
    params = pipeline.advance_chat_control(state.id, parent["request_id"])["params"]
    pipeline.store.save_execution_control(ExecutionControlRecord(state.id, "another-execution", "task", 1))
    with patch.object(pipeline, "_execute") as work, pytest.raises(PipelineError, match="대상 실행"):
        pipeline.repair_task_from_chat(state.id, "task", request_id=params["requestId"], message=params["message"],
                                      fingerprint=params["fingerprint"], conversation_revision=params["conversationRevision"],
                                      parent_request_id=parent["request_id"])
    work.assert_not_called()


def test_archived_reply_interruption_writes_only_chat_sidecar(control):
    pipeline, state, _ = control
    state.stage = Stage.PUSHED
    state.archive = RunArchive("now", "revision", "snapshot", "manifest", "summary", "fingerprint")
    pipeline.store.save(state)
    path = pipeline.store.state_path(state.id)
    original = path.read_bytes()
    request_id = str(uuid.uuid4())
    owner = pipeline.begin_planning_request(state.id, request_id=request_id, kind="chat")
    assert owner["kind"] == "archived_chat"
    pipeline.finish_planning_request(state.id, request_id=request_id, phase="interrupted")
    assert path.read_bytes() == original
    saved = pipeline.store.load(state.id)
    assert saved.archive and saved.stage == Stage.PUSHED
    assert saved.planning_messages[-1].text.startswith("답변을 중단")


def test_apply_request_is_reclassified_before_interruption(control):
    pipeline, state, _ = control
    record = pipeline.begin_planning_request(state.id, request_id=str(uuid.uuid4()), kind="chat", message="반영해줘")
    assert record["kind"] == "replan"
