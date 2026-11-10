import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, PlanningConfig, ProjectConfig, RoutingConfig
from ai_orchestrator.effort_policy import EffortPolicyError, resolve_reasoning_profile
from ai_orchestrator.model_selection import select_claude_model
from ai_orchestrator.models import EffortMode, ProfileSource, RiskLevel, RunState, RunStep, Stage, TaskAction, WorkTask
from ai_orchestrator.pipeline import Pipeline, PipelineError
from ai_orchestrator.planner import Plan, assign_plan_agents


def ordinary_task(**changes):
    task = WorkTask("feature", "목록 필터 추가", ["frontend"], description="선택한 조건으로 목록을 필터링한다.",
                    expected_paths=["src/List.tsx", "src/List.css"], risk_level=RiskLevel.MEDIUM)
    return replace(task, **changes)


def configured_pipeline(path: Path, *, planning: bool = False) -> Pipeline:
    worker = AgentConfig("worker", ("general", "frontend", "backend", "planning"), ("claude", "-p"),
                         provider_id="claude", model="sonnet")
    return Pipeline(Config(path=path / "config.toml", project=ProjectConfig(path), execution=ExecutionConfig(), agents=(worker,),
                           planning=PlanningConfig(agent_id="worker" if planning else ""), routing=RoutingConfig(review_required=False)))


@pytest.mark.parametrize("mode,model,effort", [(EffortMode.ECONOMY, "sonnet", "low"), (EffortMode.BALANCED, "sonnet", "medium"),
                                              (EffortMode.FOCUSED, "opus", "high")])
def test_ordinary_claude_work_uses_sonnet_except_in_focused_mode(mode, model, effort):
    decision = select_claude_model(mode, purpose="task", task=ordinary_task())
    assert (decision.model, decision.reasoning_effort) == (model, effort)
    assert decision.reason


@pytest.mark.parametrize("changes", [
    {"risk_level": RiskLevel.HIGH}, {"description": "인증·권한 계약을 수정한다."}, {"capabilities": ["architecture"]},
    {"description": "동시 요청의 race condition을 해결한다."}, {"is_prerequisite": True}, {"conflict_group": "shared"},
    {"expected_paths": []}, {"expected_paths": ["src/**"]}, {"expected_paths": [f"src/module-{n}.py" for n in range(6)]},
])
def test_critical_complex_or_unbounded_work_uses_opus_including_economy(changes):
    for mode in EffortMode:
        decision = select_claude_model(mode, purpose="task", task=ordinary_task(**changes))
        assert decision.model == "opus" and decision.reasoning_effort in {"high", "xhigh"}


def test_claude_reasoning_and_planning_do_not_silently_select_unsupported_profiles():
    for purpose in ["planning", "chat", "recovery", "conflict_resolution"]:
        for mode in EffortMode:
            assert select_claude_model(mode, purpose=purpose).model == "opus"
    assert select_claude_model(EffortMode.BALANCED, purpose="task", task=ordinary_task(), reasoning_effort="high").model == "sonnet"
    stronger = select_claude_model(EffortMode.BALANCED, purpose="task", task=ordinary_task(), reasoning_effort="xhigh")
    assert (stronger.model, stronger.reasoning_effort) == ("opus", "xhigh")
    with pytest.raises(EffortPolicyError, match="unsupported reasoning effort"):
        resolve_reasoning_profile(mode="balanced", provider_id="claude", model="sonnet", reasoning_effort="ultra",
                                  profile_source="routing", purpose="task", task=ordinary_task())


def test_manual_legacy_and_specific_model_ids_keep_their_selected_models(tmp_path):
    for source, model in [(ProfileSource.MANUAL, "sonnet"), (ProfileSource.MANUAL, "opus"), (ProfileSource.LEGACY, "sonnet"),
                          (ProfileSource.ROUTING, "claude-sonnet-5"), (ProfileSource.MODE, "custom-claude-model")]:
        result = resolve_reasoning_profile(mode="focused", provider_id="claude", model=model, reasoning_effort="high",
                                           profile_source=source, baseline_reasoning_effort="high", purpose="task",
                                           task=ordinary_task(risk_level=RiskLevel.HIGH))
        assert result.model == model
    task = ordinary_task(profile_source=ProfileSource.MANUAL, model="sonnet", agent_id="worker", provider_id="claude")
    assign_plan_agents(Plan("manual", False, [task]), configured_pipeline(tmp_path).config.agents,
                       RoutingConfig(review_required=False), effort_mode=EffortMode.FOCUSED)
    assert task.model == "sonnet" and task.profile_source == ProfileSource.MANUAL
    auto_model = resolve_reasoning_profile(mode="balanced", provider_id="claude", model="", reasoning_effort="high",
                                          profile_source="manual", purpose="task", task=ordinary_task(risk_level=RiskLevel.HIGH))
    assert (auto_model.model, auto_model.reasoning_effort, auto_model.profile_source) == ("opus", "high", ProfileSource.MANUAL)
    missing = resolve_reasoning_profile(mode="focused", provider_id="claude", model="sonnet", reasoning_effort="high",
                                        profile_source="mode", purpose="task", task=ordinary_task())
    assert missing.model == "sonnet" and missing.unsupported_effects == ("mode_profile_baseline_missing",)


def test_claude_assignment_preview_snapshot_and_invocation_use_the_same_model(tmp_path):
    pipeline = configured_pipeline(tmp_path)
    tasks = [ordinary_task(), ordinary_task(id="sensitive", risk_level=RiskLevel.HIGH)]
    assign_plan_agents(Plan("features", False, tasks), pipeline.config.agents, pipeline.config.routing,
                       effort_mode=EffortMode.BALANCED, sequential=True)
    assert [task.model for task in tasks] == ["sonnet", "opus"]
    assert all(task.profile_source == ProfileSource.MODE and task.model_selection_reason for task in tasks)
    state = RunState("claude-models", "", "", str(tmp_path), "main", stage=Stage.PLANNED,
                     plan_revision=1, plan_approved_revision=1, tasks=tasks)
    pipeline.store.save(state)
    for task in tasks:
        preview = resolve_reasoning_profile(mode="balanced", provider_id="claude", model=task.model,
                                            reasoning_effort=task.reasoning_effort, profile_source=task.profile_source,
                                            baseline_reasoning_effort=task.effort_baseline_reasoning, purpose="task", task=task)
        assert (preview.model, preview.reasoning_effort) == (task.model, task.reasoning_effort)
    pipeline.set_effort_mode(state.id, "balanced", expected_revision=0, request_id=str(uuid.uuid4()))
    pipeline._begin_effort_execution(state, agent_overrides=None, model_overrides=None, reasoning_effort_overrides=None)
    restored = pipeline.store.load(state.id)
    policy = pipeline.store.load_effort_policy(state.id).policy(restored.active_policy_id)
    assert [profile.model for _, profile in policy.task_profiles] == ["sonnet", "opus"]
    pipeline._validate_effort_execution_snapshot(restored, policy)
    for task in restored.tasks:
        task.worktree = str(tmp_path)
        task.prompt_path = str(tmp_path / f"{task.id}.md")
        Path(task.prompt_path).write_text("approved fixture task", encoding="utf-8")
        with patch.object(pipeline, "_invoke_provider_command", return_value="done") as invoke:
            pipeline._invoke_agent(restored, task, pipeline.agents[task.agent_id], "implement", tmp_path / "agent.log", TaskAction.EXECUTE)
        assert invoke.call_args.kwargs["model"] == task.model


def test_previously_started_sonnet_snapshot_is_preserved_even_when_new_policy_would_choose_opus(tmp_path):
    pipeline = configured_pipeline(tmp_path)
    task = ordinary_task(risk_level=RiskLevel.HIGH, agent_id="worker", provider_id="claude", model="sonnet",
                         reasoning_effort="high", profile_source=ProfileSource.MODE, effort_baseline_reasoning="high")
    state = RunState("old-claude", "", "", str(tmp_path), "main", stage=Stage.PLANNED,
                     plan_revision=1, plan_approved_revision=1, tasks=[task])
    pipeline.store.save(state)
    pipeline.store.set_effort_mode(state.id, "balanced", target="planning", expected_revision=0, request_id=str(uuid.uuid4()))
    changed = pipeline._effort_mode_preview(state, EffortMode.BALANCED, 1)
    assert changed.requires_plan_review and changed.tasks[0].reasoning.model == "opus"
    with pytest.raises(PipelineError, match="policy_plan_review_required"):
        pipeline._begin_effort_execution(state, agent_overrides=None, model_overrides=None, reasoning_effort_overrides=None)
    preview = pipeline._effort_mode_preview(state, EffortMode.BALANCED, 1, preserve_execution_profiles=True)
    policy = pipeline._resolved_execution_policy(state, preview)
    request_id = str(uuid.uuid4())
    pipeline.store.prepare_effort_execution(state.id, policy, execution_request_id=request_id, expected_revision=1)
    state.active_policy_id, state.active_execution_request_id = policy.policy_id, request_id
    pipeline.store.save(state)
    pipeline.store.start_effort_execution(state.id, request_id)
    state.stage, state.failed_step = Stage.FAILED, RunStep.AGENT_EXECUTION
    pipeline.store.save(state)
    pipeline.store.set_effort_mode(state.id, "focused", target="next_execution", expected_revision=1, request_id=str(uuid.uuid4()))
    with patch("ai_orchestrator.effort_policy.select_claude_model", side_effect=AssertionError("must reuse the started snapshot")):
        assert pipeline._begin_effort_execution(state, agent_overrides=None, model_overrides=None, reasoning_effort_overrides=None) == request_id
    assert pipeline.store.load(state.id).tasks[0].model == "sonnet"
    assert pipeline.store.load_effort_policy(state.id).pending_execution_mode == EffortMode.FOCUSED


def test_automatic_claude_planning_is_pinned_and_matches_invocation_without_changing_manual_choice(tmp_path):
    pipeline = configured_pipeline(tmp_path, planning=True)
    state = RunState("claude-plan", "", "", str(tmp_path), "main", stage=Stage.PLANNED,
                     planning_agent_id="worker", planning_provider_id="claude", planning_model="sonnet",
                     planning_profile_source=ProfileSource.ROUTING)
    pipeline.store.save(state)
    pipeline._pin_automatic_planning_profile(state)
    assert (state.planning_model, state.planning_reasoning_effort) == ("opus", "high")
    prompt = tmp_path / "planning.md"
    prompt.write_text("fixture plan", encoding="utf-8")
    for source, model in [(ProfileSource.ROUTING, "sonnet"), (ProfileSource.MANUAL, "sonnet"),
                          (ProfileSource.LEGACY, "sonnet"), (ProfileSource.ROUTING, "claude-sonnet-5")]:
        state.planning_profile_source, state.planning_model, state.planning_reasoning_effort = source, model, "medium"
        with patch.object(pipeline, "_invoke_provider_command", return_value="plan") as invoke:
            pipeline._invoke_planning_agent(state, pipeline.agents["worker"], "fixture plan", prompt, tmp_path / "planning.log")
        assert invoke.call_args.kwargs["model"] == ("opus" if source == ProfileSource.ROUTING and model == "sonnet" else model)


def test_new_claude_plan_is_ready_for_confirmation_without_an_extra_mode_apply(tmp_path):
    pipeline = configured_pipeline(tmp_path, planning=True)
    state = RunState("fresh-claude", "", "", str(tmp_path), "main", stage=Stage.REVIEWED,
                     planning_agent_id="worker", planning_provider_id="claude", planning_model="sonnet",
                     planning_profile_source=ProfileSource.ROUTING)
    pipeline.store.save(state)
    plan = Plan("feature", False, [ordinary_task()])
    assign_plan_agents(plan, pipeline.config.agents, pipeline.config.routing, sequential=True)
    with patch.object(pipeline, "_planning_execution_agents", return_value=pipeline.config.agents):
        pipeline._apply_plan(state, plan)
    preview = pipeline.preview_effort_mode(state.id, "balanced", expected_revision=0)
    assert not preview.requires_plan_review
    assert state.planning_model == "opus" and state.tasks[0].model == "sonnet"
