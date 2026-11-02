from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from ai_orchestrator.config import Config, ExecutionConfig, ProjectConfig
from ai_orchestrator.models import (
    ExecutionControlRecord, RunExecutionAction, RunExecutionSituation, RunLockState, RunLockStatus,
    RunState, RunStep, Stage, TaskStatus, WorkTask,
)
from ai_orchestrator.pipeline import Pipeline, PipelineError


@pytest.fixture
def completed_run(tmp_path: Path) -> tuple[Pipeline, RunState]:
    repo = tmp_path / "repo"
    repo.mkdir()
    pipeline = Pipeline(Config(path=tmp_path / "config.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=()))
    state = RunState(
        id="completed", repo_path=str(repo), main_branch="main", stage=Stage.READY_TO_MERGE,
        spec_path="", spec_digest="fixture", tasks=[WorkTask("task", "Completed task", ["general"], status=TaskStatus.COMPLETED)],
    )
    state.verified_main_head = "main-commit"
    state.verified_integration_head = "integration-commit"
    pipeline.store.save(state)
    return pipeline, state


@pytest.mark.parametrize("stage", [Stage.READY_TO_MERGE, Stage.VERIFIED, Stage.WORK_BRANCH_PUSHED, Stage.MERGED, Stage.PUSHED, Stage.DEPLOYED])
@pytest.mark.parametrize("phase", ["stopped", "confirmation_required", "finished"])
def test_completed_stages_never_resume_from_historical_execution_records(completed_run, stage, phase):
    pipeline, state = completed_run
    state.stage = stage
    state.failed_step = RunStep.PLANNING
    state.failure_message = "historical failure"
    record = ExecutionControlRecord(run_id=state.id, execution_id="old", scope="verification", owner_pid=123, phase=phase)
    before = state.to_dict()
    control = pipeline._run_execution_control(state, RunLockStatus(run_id=state.id, state=RunLockState.UNLOCKED), record)
    expected = RunExecutionSituation.STATUS_UNKNOWN if phase == "confirmation_required" else RunExecutionSituation.TASKS_COMPLETE
    assert control.situation == expected
    assert control.action == RunExecutionAction.NONE
    assert state.to_dict() == before
    assert (state.verified_main_head, state.verified_integration_head) == ("main-commit", "integration-commit")


@pytest.mark.parametrize("lock_state", [RunLockState.ACTIVE, RunLockState.STALE, RunLockState.UNVERIFIABLE, RunLockState.MALFORMED])
def test_completed_run_lock_remains_authoritative_for_execution_and_merge(completed_run, lock_state):
    pipeline, state = completed_run
    state.stage = Stage.VERIFIED
    lock = RunLockStatus(run_id=state.id, state=lock_state, operation="verify-and-repair")
    record = ExecutionControlRecord(run_id=state.id, execution_id="old", scope="verification", owner_pid=123, phase="stopped")
    pipeline.git = Mock()
    pipeline.git.remote_configured.return_value = False
    pipeline.git.branch_head.side_effect = lambda branch, **_kwargs: "main-commit" if branch == "main" else "integration-commit"
    pipeline.git.current_branch.return_value = "main"
    pipeline.git.has_uncommitted_changes.return_value = False
    pipeline.git.branch_exists.return_value = True
    execution = pipeline._run_execution_control(state, lock, record)
    integration = pipeline._integration_control(state, lock)
    assert execution.action == RunExecutionAction.NONE
    assert execution.situation != RunExecutionSituation.RESUMABLE
    assert not integration.can_verify
    assert not integration.can_apply_main
    pipeline.git.run.assert_not_called()


@pytest.mark.parametrize("stage", [Stage.READY_TO_MERGE, Stage.VERIFIED, Stage.WORK_BRANCH_PUSHED, Stage.MERGED])
def test_rejected_resume_does_not_replace_execution_evidence_or_run_tasks(completed_run, stage):
    pipeline, state = completed_run
    state.stage = stage
    pipeline.store.save(state)
    pipeline.store.save_execution_control(
        ExecutionControlRecord(run_id=state.id, execution_id="preserved", scope="verification", owner_pid=123, phase="stopped")
    )
    before = {path.name: path.read_bytes() for path in pipeline.store.run_dir(state.id).glob("*.json")}
    with patch.object(pipeline, "_execution_session") as session, patch.object(pipeline, "_resume") as resume:
        with pytest.raises(PipelineError, match="has no resumable failure"):
            pipeline.resume(state.id)
    session.assert_not_called()
    resume.assert_not_called()
    after = {path.name: path.read_bytes() for path in pipeline.store.run_dir(state.id).glob("*.json")}
    assert after == before


def test_real_failure_and_interrupted_execution_still_offer_resume(completed_run):
    pipeline, state = completed_run
    pipeline.git.current_branch = Mock(return_value="main")
    lock = RunLockStatus(run_id=state.id, state=RunLockState.UNLOCKED)
    for stage in [Stage.EXECUTING, Stage.FAILED]:
        state.stage = stage
        state.failed_step = RunStep.AGENT_EXECUTION if stage == Stage.FAILED else None
        control = pipeline._run_execution_control(state, lock)
        assert control.action == RunExecutionAction.RESUME


def test_verified_merge_eligibility_keeps_existing_backend_conditions(completed_run):
    pipeline, state = completed_run
    pipeline.git = Mock()
    pipeline.git.remote_configured.return_value = False
    pipeline.git.branch_head.side_effect = lambda branch, **_kwargs: "main-commit" if branch == "main" else "integration-commit"
    pipeline.git.current_branch.return_value = "main"
    pipeline.git.has_uncommitted_changes.return_value = False
    pipeline.git.branch_exists.return_value = True
    lock = RunLockStatus(run_id=state.id, state=RunLockState.UNLOCKED)
    for stage, can_verify, can_merge in [(Stage.READY_TO_MERGE, True, False), (Stage.VERIFIED, False, True), (Stage.MERGED, False, False)]:
        state.stage = stage
        control = pipeline._integration_control(state, lock)
        assert (control.can_verify, control.can_apply_main) == (can_verify, can_merge)
