from copy import deepcopy
from dataclasses import replace
from unittest.mock import Mock
import uuid

import pytest

from ai_orchestrator.account_usage import AccountUsage, AccountUsageCache, QuotaWindow, quota_exhausted
from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, ProjectConfig, RoutingConfig, RoutingRule
from ai_orchestrator.models import (
    EffortMode, ExecutionWorkspaceMode, ProfileSource, RiskLevel, RunState, Stage, TaskAction, TaskActionResult, TaskStatus, WorkTask,
)
from ai_orchestrator.pipeline import Pipeline, PipelineError, ProviderRequestLimitError, TaskVerificationFailure
from ai_orchestrator.planner import Plan, assign_plan_agents


@pytest.mark.parametrize("usage,exhausted", [
    (AccountUsage("available", QuotaWindow(100, 200)), True),
    (AccountUsage("available", QuotaWindow(100, 99)), False),
    (AccountUsage("available", QuotaWindow(0), QuotaWindow(100)), True),
    (AccountUsage("available", QuotaWindow(99.9)), False),
    (AccountUsage("error", QuotaWindow(100)), False),
    (AccountUsage("unavailable"), False), (AccountUsage("api_key"), False),
])
def test_only_confirmed_unexpired_limits_exclude_a_provider(usage, exhausted):
    assert quota_exhausted(usage, now=100) is exhausted


def test_cache_expires_at_reset_and_does_not_share_account_results(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("ai_orchestrator.account_usage.time.time", lambda: clock[0])
    monkeypatch.setattr("ai_orchestrator.account_usage.time.monotonic", lambda: clock[0])
    reader = Mock(side_effect=[AccountUsage("available", QuotaWindow(100, 105)), AccountUsage("available", QuotaWindow(0))])
    cache = AccountUsageCache(reader)
    assert quota_exhausted(cache.read("codex"))
    clock[0] = 104
    assert quota_exhausted(cache.read("codex")) and reader.call_count == 1
    clock[0] = 105
    assert not quota_exhausted(cache.read("codex")) and reader.call_count == 2
    other = AccountUsageCache(Mock(return_value=AccountUsage("api_key")))
    assert other.read("codex").status == "api_key"


@pytest.fixture
def quota_run(tmp_path, monkeypatch, request):
    options = getattr(request, "param", {})
    mode = EffortMode(options.get("mode", "balanced"))
    provider = options.get("provider", "codex")
    agents = (
        AgentConfig("codex", ("general",), (), 10, provider_id="codex", model="gpt-6.1-sol"),
        AgentConfig("claude", ("general",), ("claude",), 10, provider_id="claude", model="sonnet"),
    )
    usage = {"codex": AccountUsage("available", QuotaWindow(100)), "claude": AccountUsage("available", QuotaWindow(5))}
    reader = Mock(side_effect=lambda provider: usage[provider])
    pipeline = Pipeline(Config(path=tmp_path / "orchestrator.toml", project=ProjectConfig(repo=tmp_path), execution=ExecutionConfig(), agents=agents,
                               routing=RoutingConfig(review_required=False)), codex_sdk=Mock(), account_usage_reader=reader)
    monkeypatch.setattr(pipeline, "_agent_is_available", lambda agent, action: True)
    monkeypatch.setattr(pipeline, "_connected_provider_ids", lambda providers: set(providers))
    task = WorkTask("task", "문구 변경", ["general"], expected_paths=["src/message.tsx"], agent_id=provider, provider_id=provider,
                    risk_level=RiskLevel.LOW)
    assign_plan_agents(Plan("plan", False, [task]), agents, pipeline.config.routing, effort_mode=mode)
    state = RunState("quota-run", "", "", str(tmp_path), "main", stage=Stage.PLANNED,
                     plan_revision=1, plan_approved_revision=1, tasks=[task])
    pipeline.store.save(state)
    pipeline.store.set_effort_mode(state.id, mode, target="planning", expected_revision=0, request_id=str(uuid.uuid4()))
    preview = pipeline._effort_mode_preview(state, mode, 1, preserve_execution_profiles=True)
    policy = pipeline._resolved_execution_policy(state, preview)
    request_id = str(uuid.uuid4())
    pipeline.store.prepare_effort_execution(state.id, policy, execution_request_id=request_id, expected_revision=1)
    state.active_policy_id, state.active_execution_request_id = policy.policy_id, request_id
    state.stage = Stage.EXECUTING
    pipeline.store.save(state)
    pipeline.store.start_effort_execution(state.id, request_id)
    return pipeline, state, usage, reader, policy


def test_pending_auto_task_switches_model_and_restores_against_frozen_policy(quota_run):
    pipeline, state, usage, reader, policy = quota_run
    before = deepcopy(state.tasks[0])
    pipeline._apply_quota_fallbacks(state, state.tasks)
    task = state.tasks[0]
    assert (task.agent_id, task.provider_id, task.model, task.profile_source) == ("claude", "claude", "sonnet", ProfileSource.MODE)
    assert task.description == before.description and task.expected_paths == before.expected_paths
    assert state.plan_is_approved and state.plan_revision == 1
    assert "한도 소진" in task.routing_reason
    restored = pipeline.store.load(state.id)
    pipeline._validate_effort_execution_snapshot(restored, policy)
    # Resuming must retain the recorded fallback rather than reselect Opus.
    assert pipeline._begin_effort_execution(restored, agent_overrides=None, model_overrides=None,
                                            reasoning_effort_overrides=None) == state.active_execution_request_id
    restored.tasks[0].model = "opus"
    with pytest.raises(PipelineError, match="profile differs"):
        pipeline._validate_effort_execution_snapshot(restored, policy)


def test_claude_exhaustion_uses_codex_and_does_not_select_manual_only_provider(quota_run):
    pipeline, state, usage, reader, policy = quota_run
    task = state.tasks[0]
    task.agent_id, task.provider_id, task.model = "claude", "claude", "opus"
    usage["claude"], usage["codex"] = usage["codex"], usage["claude"]
    pipeline._apply_quota_fallbacks(state, [task])
    assert (task.agent_id, task.provider_id) == ("codex", "codex")
    assert task.model.startswith("gpt-")


@pytest.mark.parametrize("change", ["running", "completed", "attempt", "manual", "legacy", "rule"])
def test_protected_tasks_are_not_automatically_moved(quota_run, change):
    pipeline, state, usage, reader, policy = quota_run
    task = state.tasks[0]
    if change in {"running", "completed"}:
        task.status = TaskStatus(change)
    elif change == "attempt":
        task.last_attempt_id, task.attempt_count = "previous-attempt", 1
    elif change in {"manual", "legacy"}:
        task.profile_source = ProfileSource(change)
    else:
        pipeline.config = replace(pipeline.config, routing=replace(pipeline.config.routing, rules=(RoutingRule(("general",), "codex"),)))
    original = deepcopy(task)
    if change in {"manual", "legacy", "rule"}:
        with pytest.raises(ProviderRequestLimitError, match="한도"):
            pipeline._apply_quota_fallbacks(state, [task])
    else:
        pipeline._apply_quota_fallbacks(state, [task])
    assert task == original


@pytest.mark.parametrize("status", ["error", "unavailable", "api_key"])
def test_unknown_usage_does_not_reassign_tasks(quota_run, status):
    pipeline, state, usage, reader, policy = quota_run
    usage["codex"] = AccountUsage(status)
    original = deepcopy(state.tasks[0])
    pipeline._apply_quota_fallbacks(state, state.tasks)
    assert state.tasks[0] == original


@pytest.mark.parametrize("reason", ["exhausted", "disconnected", "manual_only", "capability", "review_contract"])
def test_no_compatible_alternative_stops_visibly_without_starting(quota_run, monkeypatch, reason):
    pipeline, state, usage, reader, policy = quota_run
    if reason == "exhausted":
        usage["claude"] = AccountUsage("available", weekly=QuotaWindow(100))
    elif reason == "disconnected":
        monkeypatch.setattr(pipeline, "_connected_provider_ids", lambda providers: {"codex"})
    elif reason in {"manual_only", "capability"}:
        alternative = replace(pipeline.config.agents[1], **({"manual_only": True} if reason == "manual_only" else {"capabilities": ("other",)}))
        pipeline.config = replace(pipeline.config, agents=(pipeline.config.agents[0], alternative))
    else:
        state.tasks[0].reviewer_agent_id, state.tasks[0].reviewer_provider_id = "claude", "claude"
    with pytest.raises(ProviderRequestLimitError, match="전환 가능한 연결 AI가 없습니다"):
        pipeline._apply_quota_fallbacks(state, state.tasks)
    restored = pipeline.store.load(state.id)
    assert restored.stage == Stage.FAILED and "사용 한도" in restored.failure_message
    assert restored.tasks[0].provider_id == "codex" and restored.tasks[0].attempt_count == 0


def test_quota_block_releases_binding_so_the_user_can_change_ai(quota_run, monkeypatch):
    pipeline, state, usage, reader, policy = quota_run
    usage["claude"] = AccountUsage("available", QuotaWindow(100))
    monkeypatch.setattr(pipeline, "_task_scope_review", lambda task: None)
    monkeypatch.setattr(pipeline, "_execute_with_bound_policy", lambda current, **kwargs: pipeline._apply_quota_fallbacks(current, current.tasks))
    with pytest.raises(ProviderRequestLimitError):
        pipeline._execute(state, manual=False)
    restored = pipeline.store.load(state.id)
    assert not restored.active_policy_id and not restored.active_execution_request_id
    assert pipeline.store.load_effort_policy(state.id).binding(state.active_execution_request_id).status == "finished"
    monkeypatch.setattr(pipeline, "_resolve_executable", lambda command: "fixture-runtime")
    selected = pipeline.update_task_execution_profile(
        state.id, "task", agent_id="claude", model="sonnet", reasoning_effort="medium",
        expected_profile=pipeline._task_execution_profile_snapshot(restored.tasks[0]),
    )
    assert selected.tasks[0].profile_source == ProfileSource.MANUAL and selected.tasks[0].provider_id == "claude"


def test_interrupted_state_save_replays_durable_selection(quota_run, monkeypatch):
    pipeline, state, usage, reader, policy = quota_run
    original_save = pipeline.store.save
    monkeypatch.setattr(pipeline.store, "save", Mock(side_effect=OSError("interrupted")))
    with pytest.raises(OSError, match="interrupted"):
        pipeline._apply_quota_fallbacks(state, state.tasks)
    restored = pipeline.store.load(state.id)
    assert restored.tasks[0].provider_id == "codex"
    monkeypatch.setattr(pipeline.store, "save", original_save)
    pipeline._apply_quota_fallbacks(restored, restored.tasks)
    assert restored.tasks[0].provider_id == "claude"
    pipeline._validate_effort_execution_snapshot(pipeline.store.load(state.id), policy)


def test_initial_automatic_candidates_exclude_confirmed_exhaustion(quota_run):
    pipeline, state, usage, reader, policy = quota_run
    usage["claude"] = AccountUsage("error")
    assert [agent.provider_id for agent in pipeline._planning_execution_agents() if not agent.manual_only] == ["claude"]


def test_parallel_fallback_does_not_exceed_existing_agent_capacity(quota_run):
    pipeline, state, usage, reader, policy = quota_run
    alternative = replace(pipeline.config.agents[1], max_tasks=1)
    pipeline.config = replace(pipeline.config, agents=(pipeline.config.agents[0], alternative))
    state.workspace_mode = ExecutionWorkspaceMode.ISOLATED
    occupied = WorkTask("other", "other", ["general"], agent_id="claude", provider_id="claude")
    with pytest.raises(ProviderRequestLimitError, match="전환 가능한"):
        pipeline._apply_quota_fallbacks(state, [state.tasks[0], occupied])


@pytest.mark.parametrize("quota_run", [{"provider": "claude", "mode": "economy"}], indirect=True)
def test_fallback_keeps_codex_code_failure_escalation_and_snapshot_evidence(quota_run, tmp_path):
    pipeline, state, usage, reader, policy = quota_run
    usage["claude"], usage["codex"] = usage["codex"], usage["claude"]
    pipeline._apply_quota_fallbacks(state, state.tasks)
    task = state.tasks[0]
    assert task.model == "gpt-6-luna"
    task.status = TaskStatus.RUNNING
    task.action_results.append(TaskActionResult(TaskAction.VERIFY, status="failed", verification_failure_kind="command_failed"))
    pipeline._promote_automatic_model(state, task, TaskVerificationFailure(task.id, ["check"], "assertion failed", tmp_path / "check.log"))
    assert task.model == "gpt-6.1-sol"
    pipeline._validate_effort_execution_snapshot(state, policy)


def test_dispatch_invokes_the_replacement_only_after_saving_selection(quota_run, monkeypatch, tmp_path):
    pipeline, state, usage, reader, policy = quota_run
    for name in ["_ensure_verification_policy", "_require_confirmed_profiles", "_ensure_execution_workspace_ready", "_prepare_tasks",
                 "_merge_task_dependencies", "_record_task_start_commit", "_preflight_task_environment", "_advance_completed_tasks"]:
        monkeypatch.setattr(pipeline, name, Mock())
    monkeypatch.setattr(pipeline, "_apply_queued_changes_after_batch", lambda state: None)
    invocations = []

    def run_task(current, task, action):
        assert task.status == TaskStatus.RUNNING and task.provider_id == "claude"
        pipeline._validate_effort_execution_snapshot(pipeline.store.load(current.id), policy)
        task.worktree = str(tmp_path)
        task.prompt_path = str(tmp_path / "prompt.md")
        monkeypatch.setattr(pipeline, "_invoke_provider_command", Mock(return_value="done"))
        pipeline._invoke_agent(current, task, pipeline.agents[task.agent_id], "implement", tmp_path / "task.log", action)
        invocations.append(pipeline._invoke_provider_command.call_args.kwargs["model"])

    monkeypatch.setattr(pipeline, "_run_task", run_task)
    result = pipeline._execute_with_bound_policy(state, manual=False, excluded_task_ids=set())
    assert invocations == ["sonnet"] and result.tasks[0].status == TaskStatus.COMPLETED
