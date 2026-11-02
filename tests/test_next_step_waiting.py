from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from ai_orchestrator.config import Config, ExecutionConfig, ProjectConfig
from ai_orchestrator.desktop_rpc import DesktopApplication
from ai_orchestrator.models import (
    IntegrationControl, IntegrationStatus, RunExecutionAction, RunExecutionControl, RunExecutionSituation,
    RiskLevel, RunLockState, RunStep, RunState, Stage, TaskActionResult, TaskReadiness, TaskStatus, WorkTask,
)
from ai_orchestrator.notifications import retry_wait_event
from ai_orchestrator.pipeline import Pipeline


def fixture(root: Path) -> tuple[Pipeline, RunState]:
    pipeline = Pipeline(Config(path=root / "config.toml", project=ProjectConfig(repo=root), execution=ExecutionConfig(), agents=()))
    pipeline.git = Mock()
    pipeline.git.current_branch.return_value = "main"
    pipeline.git.remote_configured.return_value = True
    state = RunState("waiting", "plan.md", "digest", str(root), "main", Stage.FAILED,
                     failed_step=RunStep.AGENT_EXECUTION, plan_revision=1, plan_approved_revision=1,
                     tasks=[WorkTask("fix", "수정 대상", ["general"], status=TaskStatus.FAILED, last_attempt_id="failed-1"),
                            WorkTask("next", "다음 작업", ["general"], dependencies=["fix"])])
    state.refresh_task_readiness()
    pipeline.store.save(state)
    return pipeline, state


def instruction(pipeline: Pipeline, state: RunState) -> str:
    request_id = str(uuid4())
    fingerprint = pipeline.task_retry_context(state.id, "fix")["fingerprint"]
    pipeline.save_task_retry_instruction(state.id, "fix", request_id=request_id, text="fix test", fingerprint=fingerprint)
    return request_id


def current_prompt(pipeline: Pipeline) -> dict[str, object] | None:
    state = pipeline.store.load("waiting")
    return pipeline.waiting_prompt(state, pipeline._summary_execution_control(state))


def complete(pipeline: Pipeline, state: RunState, **kwargs: object) -> RunState:
    assert kwargs["selected_task_ids"] == {"fix"}
    assert kwargs["retry_selected"]
    state.stage = Stage.EXECUTING
    state.failed_step = None
    state.failure_message = ""
    state.tasks[0].status = TaskStatus.COMPLETED
    state.tasks[0].last_attempt_id = "succeeded-2"
    state.tasks[0].last_attempt_finished_at = "2026-10-01T03:00:00+00:00"
    state.tasks[0].completed_commit = "a" * 40
    state.tasks[0].action_results.append(TaskActionResult("verify", attempt_id="succeeded-2", status="succeeded"))
    state.refresh_task_readiness()
    if all(task.status == TaskStatus.COMPLETED for task in state.tasks):
        state.stage = Stage.READY_TO_MERGE
    pipeline.store.save(state)
    return state


def test_saved_instruction_records_one_event_without_execution_and_requires_the_same_failure(tmp_path: Path) -> None:
    pipeline, state = fixture(tmp_path)
    with patch.object(pipeline, "_execute") as execute:
        request_id = instruction(pipeline, state)
        fingerprint = pipeline.task_retry_context(state.id, "fix")["fingerprint"]
        pipeline.save_task_retry_instruction(state.id, "fix", request_id=request_id, text="fix test", fingerprint=fingerprint)
    execute.assert_not_called()
    assert current_prompt(pipeline)["action"] == "retry"
    restored = pipeline.store.load(state.id)
    assert len([event for event in pipeline.store.load_notification_events(state.id) if event.summary_code == "task_retry_required"]) == 1
    restored.tasks[0].last_attempt_id = "different-failure"
    pipeline.store.save(restored)
    assert current_prompt(pipeline) is None


def test_only_successful_selected_retry_offers_the_ready_remaining_task(tmp_path: Path) -> None:
    pipeline, state = fixture(tmp_path)
    instruction(pipeline, state)
    with patch.object(pipeline, "_execute", side_effect=lambda state, **kwargs: complete(pipeline, state, **kwargs)):
        result = pipeline.retry_task(state.id, "fix")
    assert result.tasks[1].status == TaskStatus.PENDING
    prompt = current_prompt(pipeline)
    assert (prompt["action"], prompt["remaining_count"], prompt["next_task_id"]) == ("resume", 1, "next")
    assert pipeline.attention_item_summaries()[0]["title"] == "남은 Task 계속"
    with patch.object(pipeline.git, "current_branch") as branch, patch.object(pipeline.git, "head") as head:
        first = pipeline.notifications()
        second = pipeline.notifications()
    branch.assert_not_called()
    head.assert_not_called()
    assert first == second
    assert len([event for event in first["items"] if event["summary_code"] == "remaining_tasks_resume_required"]) == 1


def test_ordinary_completion_and_retry_failure_do_not_make_recovery_success_events(tmp_path: Path) -> None:
    pipeline, state = fixture(tmp_path)
    instruction(pipeline, state)
    with patch.object(pipeline, "_execute", side_effect=RuntimeError("retry failed")), pytest.raises(RuntimeError):
        pipeline.retry_task(state.id, "fix")
    assert not any(event.summary_code == "remaining_tasks_resume_required" for event in pipeline.store.load_notification_events(state.id))
    state = pipeline.store.load(state.id)
    complete(pipeline, state, selected_task_ids={"fix"}, retry_selected=True)
    assert current_prompt(pipeline) is None


def test_last_recovered_task_offers_verification_instead_of_group_resume(tmp_path: Path) -> None:
    pipeline, state = fixture(tmp_path)
    state.tasks.pop()
    pipeline.store.save(state)
    instruction(pipeline, state)
    with patch.object(pipeline, "_execute", side_effect=lambda state, **kwargs: complete(pipeline, state, **kwargs)):
        result = pipeline.retry_task(state.id, "fix")
    integration = IntegrationControl(IntegrationStatus.NEEDS_VERIFICATION, "ready", "tasks_complete", True, False)
    prompt = pipeline.waiting_prompt(result, pipeline._summary_execution_control(result), integration)
    assert prompt["action"] == "verify"
    assert prompt["remaining_count"] == 0
    assert not any(event.summary_code == "remaining_tasks_resume_required" for event in pipeline.store.load_notification_events(state.id))
    with pipeline.store.lock(state.id, "verify"):
        assert current_prompt(pipeline) is None


@pytest.mark.parametrize("status", [TaskStatus.FAILED, TaskStatus.WAITING, TaskStatus.STOPPED])
def test_other_unresolved_tasks_take_priority_over_resuming(tmp_path: Path, status: TaskStatus) -> None:
    pipeline, state = fixture(tmp_path)
    instruction(pipeline, state)
    with patch.object(pipeline, "_execute", side_effect=lambda state, **kwargs: complete(pipeline, state, **kwargs)):
        pipeline.retry_task(state.id, "fix")
    state = pipeline.store.load(state.id)
    state.tasks[1].status = status
    pipeline.store.save(state)
    assert current_prompt(pipeline) is None


def test_changed_plan_blocked_successor_active_planning_and_unknown_execution_have_no_resume_prompt(tmp_path: Path) -> None:
    pipeline, state = fixture(tmp_path)
    instruction(pipeline, state)
    with patch.object(pipeline, "_execute", side_effect=lambda state, **kwargs: complete(pipeline, state, **kwargs)):
        pipeline.retry_task(state.id, "fix")
    state = pipeline.store.load(state.id)
    control = pipeline._summary_execution_control(state)
    with pipeline.store.planning_chat_lock(state.id):
        assert pipeline.waiting_prompt(state, control) is None
    with pipeline.store.lock(state.id, "resume"):
        assert pipeline.waiting_prompt(state, control) is None
    unknown = RunExecutionControl(RunExecutionSituation.STATUS_UNKNOWN, RunExecutionAction.NONE, "unknown", RunLockState.UNVERIFIABLE)
    assert pipeline.waiting_prompt(state, unknown) is None
    state.tasks[1].readiness = TaskReadiness.BLOCKED
    assert pipeline.waiting_prompt(state, control) is None
    state.tasks[1].readiness = TaskReadiness.READY
    state.plan_revision += 1
    assert pipeline.waiting_prompt(state, control) is None


def test_intentional_stop_and_stale_success_record_do_not_repeat_resume_prompt(tmp_path: Path) -> None:
    pipeline, state = fixture(tmp_path)
    instruction(pipeline, state)
    with patch.object(pipeline, "_execute", side_effect=lambda state, **kwargs: complete(pipeline, state, **kwargs)):
        pipeline.retry_task(state.id, "fix")
    state = pipeline.store.load(state.id)
    control = RunExecutionControl(RunExecutionSituation.RESUMABLE, RunExecutionAction.RESUME, "stopped", RunLockState.UNLOCKED,
                                  stop_phase="stopped", dispatch_paused=True)
    assert pipeline.waiting_prompt(state, control) is None
    state.tasks[0].completed_commit = "b" * 40
    assert pipeline.waiting_prompt(state, pipeline._summary_execution_control(state)) is None


def test_next_task_matches_scheduler_priority_without_modifying_run(tmp_path: Path) -> None:
    pipeline, state = fixture(tmp_path)
    state.tasks[1].risk_level = RiskLevel.LOW
    state.tasks.append(WorkTask("priority", "우선 작업", ["general"], risk_level=RiskLevel.HIGH, dependencies=["fix"]))
    pipeline.store.save(state)
    instruction(pipeline, state)
    with patch.object(pipeline, "_execute", side_effect=lambda state, **kwargs: complete(pipeline, state, **kwargs)):
        pipeline.retry_task(state.id, "fix")
    state = pipeline.store.load(state.id)
    before = state.to_dict()
    stored = pipeline.store.state_path(state.id).read_bytes()
    prompt = pipeline.waiting_prompt(state, pipeline._summary_execution_control(state))
    assert (prompt["next_task_id"], prompt["remaining_count"]) == ("priority", 2)
    assert state.to_dict() == before
    assert pipeline.store.state_path(state.id).read_bytes() == stored


def test_event_storage_is_immutable_rejects_collision_and_does_not_hide_corruption(tmp_path: Path) -> None:
    pipeline, state = fixture(tmp_path)
    original = pipeline.store.state_path(state.id).read_bytes()
    event = retry_wait_event(state, str(tmp_path), state.tasks[0], "receipt", occurred_at="2026-10-01T03:00:00+00:00")
    pipeline.store.save_notification_event(event)
    pipeline.store.save_notification_event(replace(event, occurred_at="2026-10-02T03:00:00+00:00", run_title="new title"))
    assert pipeline.store.load_notification_events(state.id) == [event]
    assert pipeline.store.state_path(state.id).read_bytes() == original
    collision = replace(event, event_id=event.event_id[:16] + ("0" if event.event_id[16] != "0" else "1") + event.event_id[17:])
    with pytest.raises(ValueError, match="different evidence"):
        pipeline.store.save_notification_event(collision)
    assert pipeline.store.load_notification_events(state.id) == [event]
    path = pipeline.store.run_dir(state.id) / "notifications" / f"{event.event_id[:16]}.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid notification event"):
        pipeline.notifications()


@pytest.mark.parametrize("change", ["failure", "same_attempt", "changed_contract", "manual_successor"])
def test_resume_event_requires_a_new_verified_attempt_and_no_other_blocker(tmp_path: Path, change: str) -> None:
    pipeline, state = fixture(tmp_path)
    instruction(pipeline, state)

    def execute(state: RunState, **kwargs: object) -> RunState:
        result = complete(pipeline, state, **kwargs)
        if change == "failure":
            result.stage = Stage.FAILED
            result.tasks[0].status = TaskStatus.FAILED
        elif change == "same_attempt":
            result.tasks[0].last_attempt_id = "failed-1"
        elif change == "changed_contract":
            result.tasks[0].expected_paths = ["other.py"]
        else:
            result.tasks[1].status = TaskStatus.WAITING
        pipeline.store.save(result)
        return result

    with patch.object(pipeline, "_execute", side_effect=execute):
        pipeline.retry_task(state.id, "fix")
    assert not any(event.summary_code == "remaining_tasks_resume_required" for event in pipeline.store.load_notification_events(state.id))


def test_desktop_status_exposes_current_waiting_evidence_without_running_or_rewriting_tasks(tmp_path: Path) -> None:
    pipeline, state = fixture(tmp_path)
    instruction(pipeline, state)
    saved = pipeline.store.state_path(state.id).read_bytes()
    app = DesktopApplication(Mock(), codex_sdk=Mock())
    with patch.object(app, "_pipeline", return_value=pipeline), patch.object(pipeline, "_execute") as execute:
        result = app.status("project", state.id)
    assert result["waiting_prompt"]["action"] == "retry"
    assert result["waiting_prompt"]["task_id"] == "fix"
    assert result["stage"] == "failed"
    execute.assert_not_called()
    assert pipeline.store.state_path(state.id).read_bytes() == saved
