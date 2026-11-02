import sys
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, PlanningConfig, ProjectConfig, RoutingConfig
from ai_orchestrator.codex_sdk import CodexSdkAccountStatus
from ai_orchestrator.desktop_rpc import DesktopApplication, RpcService, _LONG_RUNNING_RPC_METHODS, _STATUS_RPC_METHODS
from ai_orchestrator.models import EffortMode, EffortPolicyRevisionError, ProfileSource, RunState, RunStep, Stage, TaskAction, TaskStatus, WorkTask
from ai_orchestrator.pipeline import Pipeline, PipelineError


@pytest.fixture
def pipeline(tmp_path: Path) -> Pipeline:
    config = Config(
        path=tmp_path / "orchestrator.toml", project=ProjectConfig(repo=tmp_path), execution=ExecutionConfig(),
        agents=(
            AgentConfig("worker", ("general",), (), 2, provider_id="codex", model="gpt-6.1-sol"),
            AgentConfig("reviewer", ("general",), (sys.executable, "-c", "pass"), 2, provider_id="local"),
        ),
        planning=PlanningConfig(agent_id="worker"), routing=RoutingConfig(default_provider="codex"),
    )
    result = Pipeline(config, codex_sdk=Mock())
    result._codex_sdk.account_status.return_value = CodexSdkAccountStatus(True, "chatgpt", "로그인됨")
    task = WorkTask(
        "t01", "Update app", ["general"], agent_id="worker", provider_id="codex", model="gpt-6.1-sol",
        reasoning_effort="medium", profile_source=ProfileSource.ROUTING, expected_paths=["src/**"],
        description="Change app", acceptance_criteria=["Works"], verify_commands=[[sys.executable, "-c", "pass"]],
    )
    result.store.save(RunState(
        "run-mode", "plan.md", "digest", str(tmp_path), "main", stage=Stage.PLANNED, summary="Plan",
        plan_revision=1, plan_approved_revision=1, tasks=[task],
        planning_agent_id="worker", planning_provider_id="codex", planning_reasoning_effort="medium",
        planning_profile_source=ProfileSource.ROUTING,
    ))
    return result


def test_legacy_control_and_preview_are_read_only(pipeline: Pipeline) -> None:
    original = pipeline.store.state_path("run-mode").read_bytes()
    control = pipeline.effort_control("run-mode")
    preview = pipeline.desktop_effort_mode_preview("run-mode", "focused", expected_revision=0)
    assert control["selected_mode"] is None and control["current_policy"] is None
    assert control["can_select_plan"] and control["can_reserve"]
    assert preview["tasks"][0]["reviewer_options"] == [
        {"agent_id": "worker", "provider_id": "codex", "model": "gpt-6.1-sol"},
        {"agent_id": "reviewer", "provider_id": "local", "model": ""},
    ]
    assert preview["requires_plan_review"] and preview["can_apply"]
    assert pipeline.store.state_path("run-mode").read_bytes() == original
    assert not pipeline.store.effort_policy_path("run-mode").exists()
    pipeline._codex_sdk.account_status.assert_called_once()
    pipeline._codex_sdk.run_turn.assert_not_called()


def test_logged_out_reviewers_are_hidden_without_changing_saved_profiles(pipeline: Pipeline) -> None:
    original = pipeline.store.state_path("run-mode").read_bytes()
    pipeline._codex_sdk.account_status.return_value = CodexSdkAccountStatus(False, "none", "로그인 필요")
    preview = pipeline.desktop_effort_mode_preview("run-mode", "focused", expected_revision=0)
    assert [option["provider_id"] for option in preview["tasks"][0]["reviewer_options"]] == ["local"]
    assert pipeline.store.state_path("run-mode").read_bytes() == original
    pipeline.config = replace(pipeline.config, agents=(pipeline.agents["worker"],))
    preview = pipeline.desktop_effort_mode_preview("run-mode", "focused", expected_revision=0)
    assert preview["tasks"][0]["reviewer_options"] == []
    assert not preview["can_apply"]
    pipeline._codex_sdk.run_turn.assert_not_called()


@pytest.mark.parametrize("reviewer_id", ["worker", "reviewer"])
def test_save_does_not_apply_and_apply_requires_explicit_review(pipeline: Pipeline, reviewer_id: str) -> None:
    request_id = str(uuid.uuid4())
    selected = pipeline.set_effort_mode("run-mode", "focused", expected_revision=0, request_id=request_id)
    assert pipeline.store.load("run-mode").tasks[0].reasoning_effort == "medium"
    with pytest.raises(PipelineError, match="explicit reviewer"):
        pipeline.apply_effort_mode_to_plan("run-mode", "focused", expected_policy_revision=1, expected_plan_revision=1)
    updated = pipeline.apply_effort_mode_to_plan(
        "run-mode", "focused", expected_policy_revision=1, expected_plan_revision=1, reviewer_agent_ids={"t01": reviewer_id},
    )
    assert selected.revision == 1
    assert updated.tasks[0].reasoning_effort == "high" and updated.tasks[0].reviewer_agent_id == reviewer_id
    assert updated.plan_revision == 2 and updated.plan_approved_revision != updated.plan_revision
    assert not pipeline.effort_control("run-mode")["requires_plan_review"]


@pytest.mark.parametrize("separate_profile", [False, True])
def test_codex_review_survives_edit_confirmation_and_uses_separate_turn(pipeline: Pipeline, separate_profile: bool) -> None:
    worker = pipeline.agents["worker"]
    reviewer = replace(worker, id="codex-review", model="gpt-6-sol") if separate_profile else worker
    agents = (worker, reviewer) if separate_profile else (worker,)
    pipeline.config = replace(pipeline.config, agents=agents)
    pipeline.agents = {agent.id: agent for agent in agents}
    pipeline.set_effort_mode("run-mode", "focused", expected_revision=0, request_id=str(uuid.uuid4()))
    assert not pipeline.store.load("run-mode").tasks[0].reviewer_agent_id
    preview = pipeline.desktop_effort_mode_preview("run-mode", "focused", expected_revision=1)
    assert preview["can_apply"]
    assert {item["agent_id"] for item in preview["tasks"][0]["reviewer_options"]} == set(pipeline.agents)
    applied = pipeline.apply_effort_mode_to_plan(
        "run-mode", "focused", expected_policy_revision=1, expected_plan_revision=1, reviewer_agent_ids={"t01": reviewer.id},
    )
    draft = pipeline._task_plan_draft(applied.tasks[0])
    draft["title"] = "Renamed app task"
    edited = pipeline.update_plan("run-mode", [draft])
    assert edited.tasks[0].reviewer_agent_id == reviewer.id and edited.tasks[0].review_policy_added
    confirmed = pipeline.confirm_plan("run-mode")
    assert confirmed.plan_is_approved
    unchanged = pipeline.desktop_effort_mode_preview("run-mode", "focused", expected_revision=1)
    assert not unchanged["tasks"][0]["review"]["policy_added"]
    assert unchanged["tasks"][0]["reviewer_options"] == []
    pipeline._codex_sdk.run_turn.assert_not_called()
    pipeline._codex_sdk.run_turn.return_value = "done"

    def invoke(current: RunState, **_: object) -> RunState:
        task = current.tasks[0]
        task.worktree = current.repo_path
        for action, agent in ((TaskAction.EXECUTE, worker), (TaskAction.REVIEW, reviewer)):
            pipeline._invoke_agent(current, task, agent, action.value, Path(task.worktree) / f"{action.value}.log", action)
        return current

    with patch.object(pipeline, "_execute_with_bound_policy", side_effect=invoke):
        pipeline.execute("run-mode")
    execution, review = [call.args[0] for call in pipeline._codex_sdk.run_turn.call_args_list]
    assert execution.conversation_id == review.conversation_id == ""
    assert execution.invocation_id != review.invocation_id
    assert execution.sandbox_mode == "workspace-write" and review.sandbox_mode == "read-only"
    assert review.approval_mode == "deny-all" and review.model == reviewer.model
    assert execution.reasoning_effort == "high" and review.reasoning_effort == ""


@pytest.mark.parametrize("provider,capabilities,available", [
    ("codex", ("general",), True), ("codex", ("other",), True),
    ("codex", ("general",), False), ("local", ("general",), True), ("claude", ("general",), True),
])
def test_review_candidate_eligibility_matches_apply(
    pipeline: Pipeline, provider: str, capabilities: tuple[str, ...], available: bool,
) -> None:
    worker = replace(pipeline.agents["worker"], provider_id=provider, capabilities=capabilities, command=(sys.executable, "-c", "pass"))
    pipeline.config = replace(pipeline.config, agents=(worker,))
    pipeline.agents = {worker.id: worker}
    state = pipeline.store.load("run-mode")
    state.tasks[0].provider_id = ""  # Legacy task: use the assigned worker's effective provider.
    if provider != "codex":
        state.tasks[0].model = state.tasks[0].reasoning_effort = ""
        state.planning_model = state.planning_reasoning_effort = ""
    pipeline.store.save(state)
    pipeline.set_effort_mode("run-mode", "focused", expected_revision=0, request_id=str(uuid.uuid4()))
    with patch.object(pipeline, "_agent_is_available", return_value=available):
        preview = pipeline.desktop_effort_mode_preview("run-mode", "focused", expected_revision=1)
        eligible = provider == "codex" and capabilities == ("general",) and available
        assert bool(preview["tasks"][0]["reviewer_options"]) == eligible
        assert preview["can_apply"] == eligible
        if not eligible:
            with pytest.raises(PipelineError, match="unavailable"):
                pipeline.apply_effort_mode_to_plan(
                    "run-mode", "focused", expected_policy_revision=1, expected_plan_revision=1,
                    reviewer_agent_ids={"t01": worker.id},
                )
            assert not pipeline.store.load("run-mode").tasks[0].reviewer_agent_id


def test_running_reservation_uses_short_lock_and_preserves_snapshot(pipeline: Pipeline) -> None:
    pipeline.set_effort_mode("run-mode", "balanced", expected_revision=0, request_id=str(uuid.uuid4()))
    state = pipeline.store.load("run-mode")
    snapshot = pipeline._resolved_execution_policy(state, pipeline.preview_effort_mode("run-mode", "balanced", expected_revision=1))
    execution_id = str(uuid.uuid4())
    pipeline.store.prepare_effort_execution("run-mode", snapshot, execution_request_id=execution_id, expected_revision=1)
    state.stage = Stage.EXECUTING
    state.active_policy_id = snapshot.policy_id
    state.active_execution_request_id = execution_id
    state.tasks[0].status = TaskStatus.RUNNING
    pipeline.store.save(state)
    pipeline.store.start_effort_execution("run-mode", execution_id)
    original = pipeline.store.state_path(state.id).read_bytes()
    reserve_id = str(uuid.uuid4())
    with pipeline.store.lock(state.id, "execute"):
        reserved = pipeline.set_effort_mode(state.id, "economy", target="next_execution", expected_revision=1, request_id=reserve_id)
        assert pipeline.set_effort_mode(state.id, "economy", target="next_execution", expected_revision=1, request_id=reserve_id) == reserved
        control = pipeline.effort_control(state.id)
        assert control["current_policy"]["mode"] == "balanced"
        assert control["pending_execution_mode"] == "economy"
        assert not control["can_apply_plan"] and control["can_reserve"]
        pipeline.cancel_effort_reservation(state.id, expected_revision=reserved.revision, request_id=str(uuid.uuid4()))
    assert pipeline.store.state_path(state.id).read_bytes() == original
    assert pipeline.store.load_effort_policy(state.id).policy(snapshot.policy_id) == snapshot


def test_policy_revision_stage_and_read_consistency_are_guarded(pipeline: Pipeline) -> None:
    old = pipeline.store.load("run-mode")
    pipeline.set_effort_mode(old.id, "economy", expected_revision=0, request_id=str(uuid.uuid4()))
    with pytest.raises(EffortPolicyRevisionError):
        pipeline.set_effort_mode(old.id, "focused", target="next_execution", expected_revision=0, request_id=str(uuid.uuid4()))
    state = pipeline.store.load(old.id)
    state.stage = Stage.FAILED
    state.failed_step = RunStep.AGENT_EXECUTION
    pipeline.store.save(state)
    control = pipeline.effort_control(state.id, expected_state=old)
    assert not control["consistent"] and not control["can_reserve"]
    assert pipeline.effort_control(state.id)["can_reserve"]
    with pytest.raises(ValueError, match="stage changed"):
        pipeline.store.set_effort_mode(state.id, "focused", target="next_execution", expected_revision=1,
                                      request_id=str(uuid.uuid4()), expected_stage=Stage.PLANNED)
    state.stage = Stage.VERIFIED
    pipeline.store.save(state)
    with pytest.raises(PipelineError, match="다음 실행 예약"):
        pipeline.set_effort_mode(state.id, "focused", target="next_execution", expected_revision=1, request_id=str(uuid.uuid4()))


def test_broken_policy_is_not_hidden_as_legacy(pipeline: Pipeline) -> None:
    state = pipeline.store.load("run-mode")
    state.active_policy_id = str(uuid.uuid4())
    pipeline.store.save(state)
    with pytest.raises(PipelineError, match="inconsistent"):
        pipeline.effort_control(state.id)
    state.active_policy_id = ""
    pipeline.store.save(state)
    pipeline.store.effort_policy_path(state.id).write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        pipeline.effort_control(state.id)


def test_desktop_status_exposes_policy_and_adapter_calls(pipeline: Pipeline) -> None:
    application = DesktopApplication.__new__(DesktopApplication)
    with patch.object(application, "_pipeline", return_value=pipeline):
        result = application.status("project", "run-mode")
        assert result["effort_control"]["selected_mode"] is None
        rpc = RpcService(application)
        rpc.dispatch("runs.setEffortMode", {"projectName": "project", "runId": "run-mode", "mode": "economy",
                     "target": "planning", "expectedPolicyRevision": 0, "requestId": str(uuid.uuid4())})
        compared = rpc.dispatch("runs.previewEffortMode", {"projectName": "project", "runId": "run-mode",
                               "mode": "economy", "expectedRevision": 1})
        assert compared["mode"] == "economy"
        updated = rpc.dispatch("runs.applyEffortModeToPlan", {"projectName": "project", "runId": "run-mode",
                               "mode": "economy", "expectedPolicyRevision": 1, "expectedPlanRevision": 1, "reviewerAgentIds": {}})
        assert updated.tasks[0].reasoning_effort == "medium"
    assert "runs.previewEffortMode" in _STATUS_RPC_METHODS
    assert "runs.applyEffortModeToPlan" in _LONG_RUNNING_RPC_METHODS
    assert not {"runs.setEffortMode", "runs.cancelEffortReservation"} & (_STATUS_RPC_METHODS | _LONG_RUNNING_RPC_METHODS)


@pytest.mark.parametrize("method,field,value", [
    ("runs.previewEffortMode", "expectedRevision", True),
    ("runs.setEffortMode", "expectedPolicyRevision", -1),
    ("runs.cancelEffortReservation", "expectedPolicyRevision", "1"),
    ("runs.applyEffortModeToPlan", "expectedPlanRevision", None),
    ("runs.applyEffortModeToPlan", "reviewerAgentIds", {"t01": 2}),
])
def test_rpc_rejects_malformed_mode_contract(method: str, field: str, value: object) -> None:
    application = Mock()
    params = {"projectName": "project", "runId": "run-mode", "mode": "balanced", "target": "planning",
              "requestId": str(uuid.uuid4()), "expectedRevision": 0, "expectedPolicyRevision": 0,
              "expectedPlanRevision": 1, "reviewerAgentIds": {}, field: value}
    with pytest.raises(ValueError):
        RpcService(application).dispatch(method, params)
    assert not application.mock_calls
