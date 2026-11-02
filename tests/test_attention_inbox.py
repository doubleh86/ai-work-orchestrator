from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from ai_orchestrator.config import Config, ExecutionConfig, ProjectConfig
from ai_orchestrator.models import (
    DirectionChangeRequest, DirectionChangeStatus, RunArchive, RunLockState, RunLockStatus,
    RunState, RunStep, Stage, TaskStatus, WorkTask,
)
from ai_orchestrator.pipeline import Pipeline


def pipeline_at(root: Path, *, remote: bool = True, deploy: bool = False) -> Pipeline:
    pipeline = Pipeline(Config(
        path=root / "orchestrator.toml", project=ProjectConfig(repo=root), agents=(),
        execution=ExecutionConfig(deploy_command=("deploy",) if deploy else ()),
    ))
    pipeline.git = Mock()
    pipeline.git.remote_configured.return_value = remote
    pipeline.git.current_branch.return_value = "main"
    return pipeline


def run(stage: Stage, **fields: object) -> RunState:
    state = RunState("group", "plan.md", "digest", "repo", "main", stage, summary="작업 그룹",
                     tasks=[WorkTask("task", "작업", ["general"])])
    for key, value in fields.items():
        setattr(state, key, value)
    return state


@pytest.mark.parametrize(("stage", "fields", "kind", "view"), [
    (Stage.NEEDS_CLARIFICATION, {}, "planning_questions", "planning"),
    (Stage.FAILED, {"failed_step": RunStep.PLANNING}, "planning_recovery", "planning"),
    (Stage.FAILED, {"failed_step": RunStep.VERIFY}, "failure_recovery", "operations"),
    (Stage.PLANNED, {"plan_revision": 2, "plan_approved_revision": 1}, "plan_confirmation", "tasks"),
    (Stage.PLANNED, {"plan_revision": 2, "plan_approved_revision": 2}, "execution_start", "tasks"),
    (Stage.EXECUTING, {}, "resume", "tasks"),
    (Stage.READY_TO_MERGE, {}, "verification", "operations"),
    (Stage.VERIFIED, {}, "main_review", "operations"),
    (Stage.WORK_BRANCH_PUSHED, {}, "main_review", "operations"),
    (Stage.MERGED, {}, "main_push", "operations"),
])
def test_current_decision_routes_to_existing_screen(tmp_path: Path, stage: Stage, fields: dict[str, object], kind: str, view: str) -> None:
    pipeline = pipeline_at(tmp_path)
    state = run(stage, **fields)
    pipeline.store.save(state)
    with patch.object(pipeline.store, "save") as save:
        items = pipeline.attention_item_summaries()
    assert [(item["kind"], item["view"], item["status"]) for item in items] == [(kind, view, "actionable")]
    assert items[0]["run_id"] == state.id
    save.assert_not_called()


def test_one_primary_decision_updates_after_failure_and_manual_completion(tmp_path: Path) -> None:
    pipeline = pipeline_at(tmp_path)
    state = run(Stage.FAILED, failed_step=RunStep.AGENT_EXECUTION, failure_message="검증 실패")
    state.tasks[0].status = TaskStatus.FAILED
    state.tasks.append(WorkTask("manual", "수동 확인", ["general"], status=TaskStatus.WAITING))
    pipeline.store.save(state)
    failed = pipeline.attention_item_summaries()
    assert [(item["kind"], item["task_id"]) for item in failed] == [("failure_recovery", "task")]
    assert failed[0]["reason"] == "검증 실패"

    state.stage = Stage.EXECUTING
    state.failed_step = None
    state.tasks[0].status = TaskStatus.COMPLETED
    pipeline.store.save(state)
    assert [(item["kind"], item["task_id"]) for item in pipeline.attention_item_summaries()] == [("manual_completion", "manual")]
    state.tasks[1].status = TaskStatus.COMPLETED
    state.stage = Stage.PUSHED
    pipeline.store.save(state)
    assert pipeline.attention_item_summaries() == []


def test_direction_requests_remain_until_applied(tmp_path: Path) -> None:
    pipeline = pipeline_at(tmp_path)
    state = run(Stage.EXECUTING, direction_change_requests=[
        DirectionChangeRequest("old", "이전 요청", "", "", status=DirectionChangeStatus.QUEUED),
        DirectionChangeRequest("new", "현재 요청", "", "", status=DirectionChangeStatus.AWAITING_CONFIRMATION),
    ])
    pipeline.store.save(state)
    assert [item["kind"] for item in pipeline.attention_item_summaries()] == ["direction_review"]
    for request in state.direction_change_requests:
        request.status = DirectionChangeStatus.APPLIED
    pipeline.store.save(state)
    assert [item["kind"] for item in pipeline.attention_item_summaries()] == ["resume"]


def test_live_locks_exclude_waiting_decisions_and_stale_locks_require_check(tmp_path: Path) -> None:
    pipeline = pipeline_at(tmp_path)
    state = run(Stage.NEEDS_CLARIFICATION)
    pipeline.store.save(state)
    with pipeline.store.lock(state.id, "planning-chat"):
        assert pipeline.attention_item_summaries() == []
    with pipeline.store.planning_chat_lock(state.id):
        assert pipeline.attention_item_summaries() == []
    with patch.object(pipeline.store, "inspect_lock", return_value=RunLockStatus(state.id, RunLockState.STALE)):
        with patch.object(pipeline.store, "clear_stale_lock") as clear:
            items = pipeline.attention_item_summaries()
        clear.assert_not_called()
    assert [(item["kind"], item["status"]) for item in items] == [("status_check", "check_required")]


def test_chat_query_failure_and_changing_lock_are_not_empty_success(tmp_path: Path) -> None:
    pipeline = pipeline_at(tmp_path)
    state = run(Stage.NEEDS_CLARIFICATION)
    pipeline.store.save(state)
    with patch.object(pipeline.store, "inspect_planning_chat_lock", side_effect=OSError("cannot read")):
        assert pipeline.attention_item_summaries()[0]["status"] == "check_required"
    with patch.object(pipeline.store, "inspect_planning_chat_lock", side_effect=[
        RunLockStatus(state.id, RunLockState.UNLOCKED), RunLockStatus(state.id, RunLockState.ACTIVE),
    ]):
        assert pipeline.attention_item_summaries()[0]["status"] == "check_required"


@pytest.mark.parametrize("stage", [Stage.PUSHED, Stage.DEPLOYED])
def test_finished_and_archived_groups_do_not_request_another_approval(tmp_path: Path, stage: Stage) -> None:
    pipeline = pipeline_at(tmp_path)
    state = run(stage)
    pipeline.store.save(state)
    assert pipeline.attention_item_summaries() == []
    state.stage = Stage.VERIFIED
    state.archive = RunArchive("now", "revision", "snapshot", "manifest", "summary", "fingerprint")
    pipeline.store.save(state)
    assert pipeline.attention_item_summaries() == []


def test_local_completion_and_configured_deployment(tmp_path: Path) -> None:
    pipeline = pipeline_at(tmp_path, remote=False)
    state = run(Stage.MERGED)
    pipeline.store.save(state)
    assert pipeline.attention_item_summaries() == []
    deploying = pipeline_at(tmp_path, remote=False, deploy=True)
    assert [item["kind"] for item in deploying.attention_item_summaries()] == ["deployment"]
    state.stage = Stage.PUSHED
    deploying.store.save(state)
    assert [item["kind"] for item in deploying.attention_item_summaries()] == ["deployment"]


def test_unavailable_execution_is_not_an_actionable_start(tmp_path: Path) -> None:
    pipeline = pipeline_at(tmp_path)
    pipeline.git.current_branch.return_value = "feature"
    state = run(Stage.PLANNED)
    pipeline.store.save(state)
    item = pipeline.attention_item_summaries()[0]
    assert item["status"] == "check_required"
    assert "Main" in item["reason"]
