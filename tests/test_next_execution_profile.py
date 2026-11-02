import json
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, NVIDIA_MODEL_PRESETS, ProjectConfig
from ai_orchestrator.models import (
    EffortExecutionBinding, EffortPolicyState, ProfileSource, RunState, RunStep, Stage, TaskAction, TaskActionResult, TaskStatus, WorkTask,
)
from ai_orchestrator.nvidia_agent import nvidia_credential_scope
from ai_orchestrator.pipeline import Pipeline, PipelineError
from ai_orchestrator.store import RunLockedError

NVIDIA_MODEL = NVIDIA_MODEL_PRESETS[0]


def expected(task: WorkTask) -> dict[str, str]:
    return {"agent_id": task.agent_id, "model": task.model, "reasoning_effort": task.reasoning_effort,
            "last_attempt_id": task.last_attempt_id, "status": task.status.value}


@pytest.fixture
def profile_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with nvidia_credential_scope("fixture-key"):
        codex = AgentConfig("codex", ("general",), (), 2, provider_id="codex", model="gpt-6.1-sol")
        config = Config(path=tmp_path / "config.toml", project=ProjectConfig(repo=tmp_path), execution=ExecutionConfig(), agents=(codex,))
        pipeline = Pipeline(config, codex_sdk=Mock())
        monkeypatch.setattr(pipeline, "_resolve_executable", lambda _: sys.executable)
        task = WorkTask("task", "실패한 작업", ["general"], agent_id=codex.id, provider_id="codex", model=codex.model,
                        reasoning_effort="high", status=TaskStatus.FAILED, failed_action=TaskAction.VERIFY,
                        description="보존할 설명", expected_paths=["src/**"], last_attempt_id="old-attempt", error="원래 검증 오류",
                        effective_model=codex.model, worktree="preserved-worktree", started_commit="old-baseline",
                        action_results=[TaskActionResult("verify", attempt_id="old-attempt", status="failed", error="원래 검증 오류")])
        done = WorkTask("done", "완료한 작업", ["general"], status=TaskStatus.COMPLETED, completed_commit="old-completed")
        state = RunState("profile-run", "plan.md", "digest", str(tmp_path), "main", stage=Stage.FAILED,
                         failed_step=RunStep.AGENT_EXECUTION, failure_message="원래 실패", tasks=[done, task],
                         plan_revision=3, plan_approved_revision=3)
        state.refresh_task_readiness()
        pipeline.store.save(state)
        path = pipeline.store.run_dir(state.id) / "plan.json"
        path.write_text(json.dumps({"summary": "계획", "source_paths": [], "instruction_paths": [], "tasks": []}), encoding="utf-8")
        state.structured_plan_path = str(path)
        pipeline.store.save(state)
        yield pipeline, state


def save(pipeline: Pipeline, state: RunState, **changes: object) -> RunState:
    task = state.tasks[-1]
    agent = next(agent for agent in pipeline.config.agents if agent.provider_id == "nvidia")
    values = {"agent_id": agent.id, "model": NVIDIA_MODEL, "reasoning_effort": "", "expected_profile": expected(task), **changes}
    return pipeline.update_task_execution_profile(state.id, task.id, **values)


@pytest.mark.parametrize("status", [TaskStatus.PENDING, TaskStatus.FAILED])
@pytest.mark.parametrize("provider,model,effort", [("nvidia", NVIDIA_MODEL, ""), ("codex", "gpt-6.1-terra", "ultra")])
def test_save_next_profile_preserves_failure_results_approval_and_task_contract(profile_run, status, provider, model, effort) -> None:
    pipeline, state = profile_run
    state.tasks[-1].status = status
    if status == TaskStatus.PENDING:
        state.stage, state.failed_step = Stage.EXECUTING, None
    state.refresh_task_readiness()
    pipeline.store.save(state)
    original = state.to_dict()
    selection = {"agent_id": next(agent.id for agent in pipeline.config.agents if agent.provider_id == provider),
                 "model": model, "reasoning_effort": effort}
    updated = save(pipeline, state, **selection)
    task = updated.tasks[-1]
    assert (task.provider_id, task.model, task.reasoning_effort, task.profile_source) == (provider, model, effort, ProfileSource.MANUAL)
    for field in ("description", "error", "action_results", "last_attempt_id", "effective_model", "worktree", "started_commit", "expected_paths"):
        assert updated.to_dict()["tasks"][-1][field] == original["tasks"][-1][field]
    assert updated.to_dict()["tasks"][0] == original["tasks"][0]
    assert (updated.stage, updated.failure_message, updated.plan_revision, updated.plan_approved_revision) == (
        state.stage, state.failure_message, 3, 3
    )
    if status == TaskStatus.FAILED:
        assert task.failed_action == TaskAction.EXECUTE
    stored = json.loads(Path(updated.structured_plan_path).read_text(encoding="utf-8"))["tasks"][-1]
    assert (stored["provider_id"], stored["model"], stored["reasoning_effort"]) == (provider, model, effort)
    restored = pipeline.store.load(state.id).tasks[-1]
    assert (restored.provider_id, restored.model, restored.reasoning_effort) == (provider, model, effort)
    repeated = save(pipeline, updated, **selection)
    assert repeated.to_dict() == updated.to_dict()


@pytest.mark.parametrize("change", ["stage", "active_step", "active_task", "completed", "waiting", "stopped", "stale_attempt", "stale_model"])
def test_rejects_active_protected_and_stale_changes_without_writing(profile_run, change) -> None:
    pipeline, state = profile_run
    stale = expected(state.tasks[-1])
    if change == "stage":
        state.failed_step = RunStep.VERIFY
    elif change == "active_step":
        state.active_step = RunStep.AGENT_EXECUTION
    elif change == "active_task":
        state.tasks[0].status = TaskStatus.RUNNING
    elif change in {"completed", "waiting", "stopped"}:
        state.tasks[-1].status = TaskStatus(change)
    elif change == "stale_attempt":
        state.tasks[-1].last_attempt_id = "new-attempt"
    else:
        state.tasks[-1].model = "new-model"
    pipeline.store.save(state)
    original = pipeline.store.load(state.id).to_dict()
    plan = Path(state.structured_plan_path).read_bytes()
    with pytest.raises(PipelineError):
        save(pipeline, state, expected_profile=stale)
    assert pipeline.store.load(state.id).to_dict() == original
    assert Path(state.structured_plan_path).read_bytes() == plan


@pytest.mark.parametrize("lock", ["run", "planning"])
def test_rejects_real_execution_and_planning_locks(profile_run, lock) -> None:
    pipeline, state = profile_run
    guard = pipeline.store.lock(state.id, "execute") if lock == "run" else pipeline.store.planning_chat_lock(state.id)
    with guard, pytest.raises(RunLockedError):
        save(pipeline, state)
    assert pipeline.store.load(state.id).tasks[-1].provider_id == "codex"


@pytest.mark.parametrize("binding_status", ["prepared", "started"])
def test_unfinished_policy_binding_is_not_changed(profile_run, monkeypatch, binding_status) -> None:
    pipeline, state = profile_run
    binding = EffortExecutionBinding("request", "policy", 1, 3, "", "at", "at", binding_status)
    monkeypatch.setattr(pipeline.store, "load_effort_policy", lambda _: EffortPolicyState(execution_bindings=(binding,)))
    with pytest.raises(PipelineError, match="실행 예약"):
        save(pipeline, state)
    assert pipeline.store.load(state.id).tasks[-1].provider_id == "codex"


@pytest.mark.parametrize("changes", [{"agent_id": "missing"}, {"model": "missing-model"}, {"reasoning_effort": "high"}])
def test_invalid_selected_profile_never_falls_back(profile_run, changes) -> None:
    pipeline, state = profile_run
    with pytest.raises(PipelineError):
        save(pipeline, state, **changes)
    assert pipeline.store.load(state.id).tasks[-1].provider_id == "codex"


def test_incompatible_reviewer_and_capability_are_preserved_on_failure(profile_run) -> None:
    pipeline, state = profile_run
    task = state.tasks[-1]
    agent = next(agent for agent in pipeline.config.agents if agent.provider_id == "nvidia")
    task.reviewer_agent_id, task.reviewer_provider_id = agent.id, agent.provider_id
    pipeline.store.save(state)
    with pytest.raises(PipelineError, match="리뷰 AI"):
        save(pipeline, state)
    task.reviewer_agent_id = ""
    narrow = AgentConfig("narrow", ("other",), (sys.executable, "-c", "pass"), provider_id="custom")
    pipeline.agents[narrow.id] = narrow
    pipeline.store.save(state)
    with pytest.raises(PipelineError, match="역량"):
        save(pipeline, state, agent_id=narrow.id, model="")
    assert pipeline.store.load(state.id).tasks[-1].provider_id == "codex"


def active_pending(pipeline: Pipeline, state: RunState) -> None:
    state.stage, state.failed_step, state.active_step = Stage.EXECUTING, None, RunStep.AGENT_EXECUTION
    state.tasks[0].status, state.tasks[0].active_action = TaskStatus.RUNNING, TaskAction.EXECUTE
    state.tasks[-1].status = TaskStatus.PENDING
    state.refresh_task_readiness()
    pipeline.store.save(state)


def test_running_owner_keeps_state_while_pending_profile_survives_progress_saves(profile_run, monkeypatch) -> None:
    pipeline, state = profile_run
    active_pending(pipeline, state)
    remote = Pipeline(pipeline.config, codex_sdk=Mock())
    monkeypatch.setattr(remote, "_resolve_executable", lambda _: sys.executable)
    original = state.to_dict()
    plan = Path(state.structured_plan_path).read_bytes()
    with pipeline.store.lock(state.id, "execute"):
        saved = save(remote, state)
        assert saved.tasks[-1].provider_id == "nvidia"
        assert pipeline.store.load(state.id).to_dict() == original
        assert Path(state.structured_plan_path).read_bytes() == plan
        state.tasks[0].update_progress("implementing", "현재 작업 진행")
        pipeline.store.save(state)
        visible = remote.execution_profile_view(remote.store.load(state.id))
        assert visible.tasks[-1].provider_id == "nvidia"
        assert visible.tasks[0].progress_detail == "현재 작업 진행"
        assert state.tasks[-1].provider_id == "codex"
        state.tasks[0].status, state.tasks[0].active_action = TaskStatus.COMPLETED, None
        with pipeline.store.planning_chat_lock(state.id):
            assert pipeline._apply_queued_execution_profiles(state)
            assert not pipeline._apply_queued_execution_profiles(state)
        assert state.tasks[-1].provider_id == "nvidia"
        assert pipeline.store.load(state.id).tasks[-1].profile_source == ProfileSource.MANUAL
        assert state.tasks[-1].last_attempt_id == "old-attempt"
        assert "task" not in pipeline.store.load_task_execution_profiles(state.id)
        assert json.loads(Path(state.structured_plan_path).read_text(encoding="utf-8"))["tasks"][-1]["provider_id"] == "nvidia"


def test_queued_profile_can_be_changed_again_and_rejects_old_visible_snapshot(profile_run) -> None:
    pipeline, state = profile_run
    active_pending(pipeline, state)
    with pipeline.store.lock(state.id, "resume"):
        visible = save(pipeline, state)
        with pytest.raises(PipelineError, match="최신 설정"):
            save(pipeline, state)
        updated = save(pipeline, visible, agent_id="codex", model="gpt-6.1-sol", reasoning_effort="medium")
        assert updated.tasks[-1].reasoning_effort == "medium"
        assert state.tasks[-1].reasoning_effort == "high"


@pytest.mark.parametrize("status", [TaskStatus.RUNNING, TaskStatus.REVIEWING, TaskStatus.COMPLETED, TaskStatus.FAILED])
def test_dispatch_winning_the_lock_prevents_saving_over_a_started_task(profile_run, status) -> None:
    pipeline, state = profile_run
    active_pending(pipeline, state)
    snapshot = deepcopy(state)
    state.tasks[-1].status = status
    pipeline.store.save(state)
    with pipeline.store.lock(state.id, "execute"), pytest.raises(PipelineError, match="아직 시작하지 않은"):
        save(pipeline, snapshot)
    assert not pipeline.store.task_execution_profiles_path(state.id).exists()


def test_pending_queue_honors_planning_lock_and_other_run_operations(profile_run) -> None:
    pipeline, state = profile_run
    active_pending(pipeline, state)
    with pipeline.store.lock(state.id, "execute"), pipeline.store.planning_chat_lock(state.id), pytest.raises(RunLockedError):
        save(pipeline, state)
    with pipeline.store.lock(state.id, "merge"), pytest.raises(RunLockedError):
        save(pipeline, state)


def test_changed_plan_rejects_queued_profile_at_dispatch_and_preserves_failure(profile_run) -> None:
    pipeline, state = profile_run
    active_pending(pipeline, state)
    with pipeline.store.lock(state.id, "execute"):
        save(pipeline, state)
        state.tasks[0].status, state.tasks[0].active_action = TaskStatus.COMPLETED, None
        state.plan_revision += 1
        with pipeline.store.planning_chat_lock(state.id), pytest.raises(PipelineError, match="상태 또는 계획"):
            pipeline._apply_queued_execution_profiles(state)
    failed = pipeline.store.load(state.id)
    assert failed.stage == Stage.FAILED and failed.failed_step == RunStep.AGENT_EXECUTION
    assert "상태 또는 계획" in failed.failure_message
    assert failed.tasks[-1].provider_id == "codex"


def test_malformed_next_execution_profile_is_not_treated_as_an_empty_queue(profile_run) -> None:
    pipeline, state = profile_run
    path = pipeline.store.task_execution_profiles_path(state.id)
    path.write_text('{"schema_version": 1, "profiles": {"task": {"selection": null}}}', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid next execution profile"):
        pipeline.execution_profile_view(state)


@pytest.mark.parametrize("interruption", ["state_save", "queue_consumption"])
def test_interrupted_profile_application_preserves_selection_and_can_resume(profile_run, monkeypatch, interruption) -> None:
    pipeline, state = profile_run
    active_pending(pipeline, state)
    with pipeline.store.lock(state.id, "execute"):
        save(pipeline, state)
        state.tasks[0].status, state.tasks[0].active_action = TaskStatus.COMPLETED, None
        pipeline.store.save(state)
        original_save = pipeline.store.save
        original_profiles = pipeline.store.save_task_execution_profiles

        def save_profiles(run_id, profiles):
            if "task" not in profiles:
                raise OSError("interrupted queue consumption")
            original_profiles(run_id, profiles)

        if interruption == "state_save":
            monkeypatch.setattr(pipeline.store, "save", Mock(side_effect=OSError("interrupted state save")))
        else:
            monkeypatch.setattr(pipeline.store, "save_task_execution_profiles", save_profiles)
        with pipeline.store.planning_chat_lock(state.id), pytest.raises(OSError, match="interrupted"):
            pipeline._apply_queued_execution_profiles(state)
        monkeypatch.setattr(pipeline.store, "save", original_save)
        monkeypatch.setattr(pipeline.store, "save_task_execution_profiles", original_profiles)
        restored = pipeline.store.load(state.id)
        assert pipeline.execution_profile_view(restored).tasks[-1].provider_id == "nvidia"
        assert "task" in pipeline.store.load_task_execution_profiles(state.id)
        with pipeline.store.planning_chat_lock(state.id):
            pipeline._apply_queued_execution_profiles(restored)
        assert pipeline.store.load(state.id).tasks[-1].provider_id == "nvidia"
        assert "task" not in pipeline.store.load_task_execution_profiles(state.id)
        assert pipeline.store.load_task_execution_profiles(state.id)["task@unbound"]["selection"]["model"] == NVIDIA_MODEL


@pytest.mark.parametrize("queued", [False, True])
def test_finishing_execution_during_planning_chat_preserves_pending_selection(profile_run, monkeypatch, queued) -> None:
    pipeline, state = profile_run
    active_pending(pipeline, state)
    with pipeline.store.lock(state.id, "execute"):
        if queued:
            save(pipeline, state)
        state.tasks[0].status, state.tasks[0].active_action = TaskStatus.COMPLETED, None
        state.active_step = None
        pipeline.store.save(state)
        monkeypatch.setattr(pipeline, "_execute_with_bound_policy", lambda current, **_: current)
        with pipeline.store.planning_chat_lock(state.id):
            returned = pipeline._execute(state, manual=False)
        assert returned.stage == Stage.EXECUTING
        if queued:
            assert pipeline.execution_profile_view(returned).tasks[-1].provider_id == "nvidia"
            assert "task" in pipeline.store.load_task_execution_profiles(state.id)
            assert "대기 모델 선택을 보존" in returned.events[-1].message
        else:
            assert not pipeline.store.task_execution_profiles_path(state.id).exists()
