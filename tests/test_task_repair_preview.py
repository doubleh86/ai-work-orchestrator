from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from ai_orchestrator.config import Config, ExecutionConfig, ProjectConfig
from ai_orchestrator.models import (
    PlanningApplyRequest, PlanningApplyStatus, RunLockState, RunLockStatus, RunState, RunStep, Stage, TaskAction, TaskActionResult, TaskStatus, WorkTask,
)
from ai_orchestrator.progress import ProgressObservation
from ai_orchestrator.pipeline import Pipeline, PipelineError
from ai_orchestrator.planner import Plan
from ai_orchestrator.store import RunLockedError


def fixture(root: Path) -> tuple[Pipeline, RunState]:
    pipeline = Pipeline(Config(path=root / "config.toml", project=ProjectConfig(repo=root), execution=ExecutionConfig(), agents=()))
    spec = root / "spec.md"
    spec.write_text("Plan", encoding="utf-8")
    state = RunState("repair", str(spec), "digest", str(root), "main", Stage.FAILED,
                     failed_step=RunStep.AGENT_EXECUTION, spec_snapshot_path=str(spec), planning_conversation_revision=1,
                     tasks=[WorkTask("task", "실패 Task", ["general"], status=TaskStatus.FAILED, error="test failed",
                                     last_attempt_id="current",
                                     action_results=[TaskActionResult(
                                         "execute", attempt_id="current", status="failed", worker_response="worker result",
                                     )])])
    pipeline.store.save(state)
    return pipeline, state


def test_retry_instruction_is_saved_once_without_plan_generation_or_task_mutation(tmp_path: Path) -> None:
    pipeline, state = fixture(tmp_path)
    before = pipeline.store.state_path(state.id).read_bytes()
    fingerprint = pipeline.task_retry_context(state.id, "task")["fingerprint"]
    request_id = str(uuid4())
    with patch.object(pipeline, "_build_plan") as build, patch.object(pipeline, "_execute") as execute:
        saved = pipeline.save_task_retry_instruction(state.id, "task", request_id=request_id, text="  fix assertion  ", fingerprint=fingerprint)
        replay = pipeline.save_task_retry_instruction(state.id, "task", request_id=request_id, text="fix assertion", fingerprint=fingerprint)
        build.assert_not_called()
        execute.assert_not_called()
    assert saved == replay
    assert saved["instruction_current"]
    assert len(pipeline.store.load_revision_requests(state.id)) == 1
    assert pipeline.store.state_path(state.id).read_bytes() == before
    reloaded = Pipeline(pipeline.config)
    assert "fix assertion" in reloaded._result_revision_retry_instruction(state.id, "task")
    task = state.tasks[0]
    task.prompt_path = str(tmp_path / "task.md")
    Path(task.prompt_path).write_text("original contract", encoding="utf-8")
    with (patch.object(pipeline, "_run_executor") as run, patch.object(pipeline, "_run_task_verification"),
          patch.object(pipeline, "_record_task_result"), patch.object(pipeline.git, "head", return_value="a" * 40)):
        pipeline._run_task(state, task)
    assert "fix assertion" in run.call_args.args[2]
    assert "original contract" in run.call_args.args[2]


def test_retry_instruction_rejects_old_failure_and_conflicting_request_id(tmp_path: Path) -> None:
    pipeline, state = fixture(tmp_path)
    fingerprint = pipeline.task_retry_context(state.id, "task")["fingerprint"]
    request_id = str(uuid4())
    pipeline.save_task_retry_instruction(state.id, "task", request_id=request_id, text="fix", fingerprint=fingerprint)
    with pytest.raises(PipelineError, match="다른 수정 지시"):
        pipeline.save_task_retry_instruction(state.id, "task", request_id=request_id, text="different", fingerprint=fingerprint)
    state.tasks[0].error = "another attempt failed"
    pipeline.store.save(state)
    assert not pipeline.task_retry_context(state.id, "task")["instruction_current"]
    with pytest.raises(PipelineError, match="변경됐습니다"):
        pipeline.save_task_retry_instruction(state.id, "task", request_id=str(uuid4()), text="fix", fingerprint=fingerprint)
    state.tasks[0].expected_paths = ["different.py"]
    pipeline.store.save(state)
    assert pipeline._result_revision_retry_instruction(state.id, "task") == ""


def test_retry_context_does_not_present_an_older_response_as_this_failed_attempt(tmp_path: Path) -> None:
    pipeline, state = fixture(tmp_path)
    assert pipeline.task_retry_context(state.id, "task")["response"] == "worker result"
    state.tasks[0].last_attempt_id = "new-attempt"
    state.tasks[0].action_results.append(TaskActionResult("execute", attempt_id="new-attempt", status="failed", error="no response"))
    pipeline.store.save(state)
    assert pipeline.task_retry_context(state.id, "task")["response"] == ""


@pytest.mark.parametrize("step", [RunStep.VERIFY, RunStep.PLANNING, RunStep.MERGE])
def test_other_failure_steps_are_not_individual_retry_targets(tmp_path: Path, step: RunStep) -> None:
    pipeline, state = fixture(tmp_path)
    state.failed_step = step
    pipeline.store.save(state)
    context = pipeline.task_retry_context(state.id, "task")
    assert not context["can_save"]
    with pytest.raises(PipelineError, match="개별 Task"):
        pipeline.save_task_retry_instruction(state.id, "task", request_id=str(uuid4()), text="fix", fingerprint=context["fingerprint"])


def test_active_execution_blocks_instruction_and_preview_status_is_read_only(tmp_path: Path) -> None:
    pipeline, state = fixture(tmp_path)
    context = pipeline.task_retry_context(state.id, "task")
    with pipeline.store.lock(state.id, "retry-task"):
        assert not pipeline.task_retry_context(state.id, "task")["can_save"]
        assert pipeline.planning_preview_status(state.id)["phase"] == "check_required"
        with pytest.raises(RunLockedError):
            pipeline.save_task_retry_instruction(state.id, "task", request_id=str(uuid4()), text="fix", fingerprint=context["fingerprint"])
    with pipeline.store.planning_chat_lock(state.id), patch.object(pipeline, "_build_plan") as build:
        assert all(pipeline.planning_preview_status(state.id)["phase"] == "chat" for _ in range(16))
        assert not pipeline.planning_preview_status(state.id)["can_generate"]
        build.assert_not_called()
    assert pipeline.planning_preview_status(state.id)["phase"] == "idle"


def test_preview_reports_generation_activity_and_reuses_candidate_for_another_request(tmp_path: Path) -> None:
    pipeline, state = fixture(tmp_path)
    proposal = deepcopy(state.tasks)
    proposal[0].status = TaskStatus.PENDING
    proposal[0].action_results = []
    proposal[0].description = "new description"
    observed = []

    def build(*args: object, **kwargs: object) -> Plan:
        observed.append(pipeline.planning_preview_status(state.id))
        return Plan(summary="plan", server_work=False, tasks=proposal)

    before = pipeline.store.state_path(state.id).read_bytes()
    with patch.object(pipeline, "_build_plan", side_effect=build) as builder:
        first = pipeline.preview_planning_apply(state.id, request_id=str(uuid4()))
        second = pipeline.preview_planning_apply(state.id, request_id=str(uuid4()))
    assert first == second
    assert builder.call_count == 1
    assert observed[0]["phase"] == "generating"
    assert observed[0]["request_id"] == first["request_id"]
    assert observed[0]["last_activity_at"] == ""
    assert observed[0]["active_operations"][0]["stage_changed_at"]
    assert pipeline.planning_preview_status(state.id)["phase"] == "ready"
    assert pipeline.store.state_path(state.id).read_bytes() == before


def test_generation_failure_is_visible_and_not_read_as_an_idle_recreate(tmp_path: Path) -> None:
    pipeline, state = fixture(tmp_path)
    with patch.object(pipeline, "_build_plan", side_effect=PipelineError("provider failed")):
        with pytest.raises(PipelineError, match="provider failed"):
            pipeline.preview_planning_apply(state.id, request_id=str(uuid4()))
    status = pipeline.planning_preview_status(state.id)
    assert status["phase"] == "failed"
    assert status["error"] == "provider failed"
    assert status["can_generate"]


def test_applied_receipt_is_recovered_but_a_new_discussion_can_generate_again(tmp_path: Path) -> None:
    pipeline, state = fixture(tmp_path)
    proposal = deepcopy(state.tasks)
    proposal[0].status = TaskStatus.PENDING
    proposal[0].action_results = []
    with patch.object(pipeline, "_build_plan", return_value=Plan(summary="plan", server_work=False, tasks=proposal)):
        preview = pipeline.preview_planning_apply(state.id, request_id=str(uuid4()))
    state.planning_apply_requests.append(PlanningApplyRequest(
        request_id=preview["request_id"], conversation_revision=1, plan_revision=0,
        context_snapshot="", status=PlanningApplyStatus.SUCCEEDED,
    ))
    state.planning_applied_conversation_revision = 1
    state.plan_revision += 1
    pipeline.store.save(state)
    result = pipeline.planning_preview_status(state.id)
    assert result["phase"] == "applied"
    assert result["preview"]["status"] == "applied"
    state.planning_conversation_revision += 1
    pipeline.store.save(state)
    result = pipeline.planning_preview_status(state.id)
    assert result["phase"] == "idle"
    assert result["can_generate"]
    assert result["preview"] is None


@pytest.mark.parametrize(("lock_state", "phase"), [(RunLockState.STALE, "interrupted"), (RunLockState.UNVERIFIABLE, "check_required")])
def test_owner_end_and_unknown_owner_have_distinct_states(tmp_path: Path, lock_state: RunLockState, phase: str) -> None:
    pipeline, state = fixture(tmp_path)
    lock = RunLockStatus(run_id=state.id, state=lock_state, reason="owner check")
    with patch.object(pipeline.store, "inspect_planning_chat_lock", return_value=lock):
        assert pipeline.planning_preview_status(state.id)["phase"] == phase


def saved_candidate(pipeline: Pipeline, state: RunState) -> dict[str, object]:
    proposal = deepcopy(state.tasks)
    proposal[0].status = TaskStatus.PENDING
    proposal[0].action_results = []
    proposal[0].description = "updated description"
    with patch.object(pipeline, "_build_plan", return_value=Plan(summary="plan", server_work=False, tasks=proposal)):
        return pipeline.preview_planning_apply(state.id, request_id=str(uuid4()))


@pytest.mark.parametrize(("action", "kind"), [(TaskAction.EXECUTE, "task_execute"), (TaskAction.REVIEW, "task_review"),
                                           (TaskAction.VERIFY, "task_verify")])
def test_ready_candidate_is_secondary_to_active_task_and_reads_do_not_create_activity(tmp_path: Path, action: TaskAction, kind: str) -> None:
    pipeline, state = fixture(tmp_path)
    candidate = saved_candidate(pipeline, state)
    ready = pipeline.planning_preview_status(state.id)
    assert ready["can_apply"] and ready["work_state"] == "idle"
    task = state.tasks[0]
    task.active_action = action
    task.last_attempt_started_at = "2026-10-02T00:00:00+00:00"
    task.progress_observation = ProgressObservation(
        "current", "invocation", "running_command", phase_started_at="2026-10-02T00:01:00+00:00",
        last_event_received_at="2026-10-02T00:02:00+00:00", evidence_kind="provider_event",
    )
    state.active_step = RunStep.AGENT_EXECUTION
    pipeline.store.save(state)
    before = pipeline.store.state_path(state.id).read_bytes()
    with pipeline.store.lock(state.id, "retry-task"), patch.object(pipeline, "_build_plan") as build:
        first = pipeline.planning_preview_status(state.id)
        second = pipeline.planning_preview_status(state.id)
        assert first["work_state"] == "active"
        assert first["preview"]["preview_id"] == candidate["preview_id"]
        assert not first["can_apply"] and not first["can_generate"]
        assert first["active_operations"] == second["active_operations"]
        operation = first["active_operations"][0]
        assert operation["kind"] == kind and operation["task_id"] == task.id
        assert operation["started_at"] == task.last_attempt_started_at
        assert operation["stage_changed_at"] == task.progress_observation.phase_started_at
        assert operation["last_activity_at"] == task.progress_observation.last_event_received_at
        build.assert_not_called()
    assert pipeline.store.state_path(state.id).read_bytes() == before
    task.active_action = None
    task.last_attempt_started_at = ""
    task.progress_observation = None
    state.active_step = None
    pipeline.store.save(state)
    assert pipeline.planning_preview_status(state.id)["can_apply"]
    state.planning_conversation_revision += 1
    pipeline.store.save(state)
    assert not pipeline.planning_preview_status(state.id)["can_apply"]


def test_local_verification_stage_changes_are_not_ai_activity_and_concurrent_chat_is_separate(tmp_path: Path) -> None:
    pipeline, state = fixture(tmp_path)
    saved_candidate(pipeline, state)
    task = state.tasks[0]
    task.active_action = TaskAction.VERIFY
    task.last_attempt_started_at = "2026-10-02T00:00:00+00:00"
    task.progress_observation = ProgressObservation(
        "current", "local:verify", "verifying_command", phase_started_at="2026-10-02T00:01:00+00:00",
        last_event_received_at="2026-10-02T00:02:00+00:00", evidence_kind="local_phase",
    )
    pipeline.store.save(state)
    with pipeline.store.lock(state.id, "retry-task"), pipeline.store.planning_chat_lock(state.id):
        result = pipeline.planning_preview_status(state.id)
        assert [item["kind"] for item in result["active_operations"]] == ["planning_chat", "task_verify"]
        assert result["last_activity_at"] == ""
        assert result["active_operations"][1]["stage_changed_at"] == task.progress_observation.phase_started_at
        assert not result["can_apply"]


def test_candidate_with_chat_running_and_plan_apply_has_actual_owner_start_without_old_activity(tmp_path: Path) -> None:
    pipeline, state = fixture(tmp_path)
    candidate = saved_candidate(pipeline, state)
    state.add_event("planning_progress", "old AI activity")
    state.events[-1].at = "2020-01-01T00:00:00+00:00"
    pipeline.store.save(state)
    for operation, kind in [("planning-chat", "planning_chat"), ("planning-preview-apply", "plan_apply")]:
        lock_context = pipeline.store.planning_chat_lock(state.id) if operation == "planning-chat" else pipeline.store.lock(state.id, operation)
        with lock_context:
            result = pipeline.planning_preview_status(state.id)
            assert result["preview"]["preview_id"] == candidate["preview_id"]
            item = result["active_operations"][0]
            assert item["kind"] == kind and item["started_at"]
            assert item["last_activity_at"] == "" and not result["can_apply"]


def test_changed_owner_and_abandoned_active_step_never_publish_ready_to_apply(tmp_path: Path) -> None:
    pipeline, state = fixture(tmp_path)
    saved_candidate(pipeline, state)
    unlocked = RunLockStatus(state.id, RunLockState.UNLOCKED)
    active = RunLockStatus(state.id, RunLockState.ACTIVE, operation="execute", acquired_at="2026-10-02T00:00:00+00:00")
    with patch.object(pipeline.store, "inspect_lock", side_effect=[unlocked, active]):
        result = pipeline.planning_preview_status(state.id)
    assert result["work_state"] == "unknown" and not result["can_apply"]
    assert result["active_operations"] == []
    state.active_step = RunStep.AGENT_EXECUTION
    pipeline.store.save(state)
    result = pipeline.planning_preview_status(state.id)
    assert result["work_state"] == "unknown" and result["phase"] == "check_required" and not result["can_apply"]


def test_other_group_lock_does_not_change_this_candidate_availability(tmp_path: Path) -> None:
    pipeline, state = fixture(tmp_path)
    saved_candidate(pipeline, state)
    other = deepcopy(state)
    other.id = "other"
    pipeline.store.save(other)
    with pipeline.store.lock(other.id, "execute"), pipeline.store.planning_chat_lock(other.id):
        result = pipeline.planning_preview_status(state.id)
        assert result["work_state"] == "idle" and result["active_operations"] == [] and result["can_apply"]
