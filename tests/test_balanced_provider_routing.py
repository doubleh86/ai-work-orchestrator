from dataclasses import replace

import pytest

from ai_orchestrator.config import AgentConfig, ConfigError, RoutingConfig, RoutingRule, create_default_config, load_config
from ai_orchestrator.models import ProfileSource, ReviewStatus, WorkTask
from ai_orchestrator.planner import PLAN_MARKER, Plan, PlanningError, assign_plan_agents, parse_structured_plan, planning_prompt


AGENTS = (
    AgentConfig("codex", ("backend", "general"), (), 10, provider_id="codex", model="gpt-6.1-sol"),
    AgentConfig("claude", ("backend", "general"), ("claude",), 10, provider_id="claude", model="sonnet"),
)


def tasks(count=4):
    return [WorkTask(str(index), "작업", ["backend"]) for index in range(count)]


def assign(selected_tasks, *, agents=AGENTS, routing=None, available=None, sequential=True):
    plan = Plan("분배", False, selected_tasks)
    assign_plan_agents(plan, agents, routing or RoutingConfig(default_provider="codex"),
                       execution_agent_ids=available, sequential=sequential)
    return plan.tasks


def test_auto_profiles_balance_by_provider_and_resolve_models_without_adding_review():
    selected = assign(tasks(6))
    assert [task.provider_id for task in selected] == ["codex", "claude"] * 3
    assert [task.model for task in selected] == ["gpt-6.1-sol", "opus"] * 3
    assert all(task.profile_source == ProfileSource.MODE for task in selected)
    assert all(task.review_status == ReviewStatus.NOT_REQUIRED and not task.reviewer_agent_id for task in selected)
    assert all(task.routing_reason == "connected provider workload balance" for task in selected)


def test_multiple_codex_agents_do_not_outvote_one_claude_agent():
    agents = (*AGENTS, replace(AGENTS[0], id="codex-extra"))
    selected = assign(tasks(8), agents=agents)
    assert [task.provider_id for task in selected].count("claude") == 4


def test_default_provider_breaks_equal_workload_and_capability_ties():
    selected = assign(tasks(2), routing=RoutingConfig(default_provider="claude"))
    assert [task.provider_id for task in selected] == ["claude", "codex"]


def test_capability_and_capacity_limit_automatic_candidates():
    agents = (replace(AGENTS[0], max_tasks=1), replace(AGENTS[1], capabilities=("backend",), max_tasks=2))
    selected = assign(tasks(3), agents=agents, sequential=False)
    assert [task.provider_id for task in selected] == ["codex", "claude", "claude"]
    selected = assign([WorkTask("ui", "화면", ["frontend"])], agents=agents)
    assert selected[0].provider_id == "codex"
    with pytest.raises(PlanningError, match="capacity"):
        assign(tasks(4), agents=agents, sequential=False)


def test_unavailable_agents_are_not_used_when_recommendation_is_empty():
    selected = assign(tasks(), available={"claude"})
    assert all(task.provider_id == "claude" for task in selected)
    with pytest.raises(PlanningError, match="no available execution agent"):
        assign(tasks(1), available=set())


def test_manual_recommended_and_rule_profiles_are_preserved():
    manual = WorkTask("manual", "직접 선택", ["backend"], agent_id="codex", provider_id="codex",
                      model="gpt-6.1-sol", reasoning_effort="high", profile_source=ProfileSource.MANUAL)
    recommended = WorkTask("recommend", "추천", ["backend"], provider_id="codex", model="gpt-6.1-sol", reasoning_effort="max")
    selected = assign([manual, recommended, *tasks(2)])
    assert [(task.provider_id, task.reasoning_effort) for task in selected[:2]] == [("codex", "high"), ("codex", "max")]
    assert manual.profile_source == ProfileSource.MANUAL
    assert all(task.provider_id == "claude" for task in selected[2:])
    routing = RoutingConfig(default_provider="codex", rules=(RoutingRule(("backend",), "codex"),))
    assert all(task.provider_id == "codex" for task in assign(tasks(), routing=routing))
    with pytest.raises(PlanningError, match="사용자가 선택한 실행 AI"):
        assign([manual], available={"claude"})


def test_manual_only_provider_never_participates_in_automatic_balance():
    nvidia = AgentConfig("nvidia", ("general",), ("opencode",), 10, provider_id="nvidia", manual_only=True)
    selected = assign(tasks(9), agents=(*AGENTS, nvidia))
    assert {task.provider_id for task in selected} == {"codex", "claude"}


def test_fixed_routing_opt_out_and_required_cross_review_are_preserved():
    routing = RoutingConfig(default_provider="codex", balance_providers=False)
    assert all(task.provider_id == "codex" for task in assign(tasks(), routing=routing))
    selected = assign(tasks(), routing=replace(routing, balance_providers=True, review_required=True))
    assert [task.provider_id for task in selected] == ["codex", "claude", "codex", "claude"]
    assert all(task.reviewer_provider_id != task.provider_id and task.review_status == ReviewStatus.PENDING for task in selected)


def test_legacy_manual_custom_profiles_do_not_replace_capable_runtime_agents():
    manual = AgentConfig("manual", ("general",), ())
    planner = AgentConfig("planner", ("planning",), ("fixture",))
    assert assign(tasks(1), agents=(manual, planner))[0].agent_id == "manual"
    assert {task.provider_id for task in assign(tasks(), agents=(*AGENTS, manual))} == {"codex", "claude"}


def test_balance_config_defaults_opt_out_and_validation(tmp_path):
    path = create_default_config(tmp_path / "orchestrator.toml", tmp_path)
    assert load_config(path).routing.balance_providers is True
    original = path.read_text(encoding="utf-8")
    path.write_text(original.replace("balance_providers = true\n", ""), encoding="utf-8")
    assert load_config(path).routing.balance_providers is True
    path.write_text(original.replace("balance_providers = true", "balance_providers = false"), encoding="utf-8")
    assert load_config(path).routing.balance_providers is False
    path.write_text(original.replace("balance_providers = true", 'balance_providers = "false"'), encoding="utf-8")
    with pytest.raises(ConfigError, match="balance_providers must be a boolean"):
        load_config(path)


def test_planning_guidance_uses_balancing_only_when_enabled():
    prompt = planning_prompt("작업", execution_agents=AGENTS)
    assert "equally suitable providers" in prompt
    assert "Provider `claude`" in prompt and "Provider `codex`" in prompt
    assert "equally suitable providers" not in planning_prompt("작업", execution_agents=AGENTS, balance_providers=False)
    example = next(line for line in prompt.splitlines() if line.startswith(PLAN_MARKER))
    selected = parse_structured_plan(example).tasks[0]
    assert (selected.provider_id, selected.model, selected.reasoning_effort) == ("", "", "")
