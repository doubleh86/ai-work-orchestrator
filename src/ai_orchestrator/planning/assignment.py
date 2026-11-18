from __future__ import annotations

from collections import Counter

from ..codex_model_preferences import CODEX_MODEL_PRESETS, codex_model_order, enabled_codex_models
from ..config import AgentConfig, RoutingConfig, supported_models, supported_reasoning_efforts
from ..model_selection import automatic_claude_profile, select_claude_model, select_codex_model
from ..models import EffortMode, ProfileSource, ReviewStatus, WorkTask
from .contracts import Plan, PlanningError


def assign_plan_agents(
    plan: Plan,
    agents: tuple[AgentConfig, ...],
    routing: RoutingConfig | None = None,
    *,
    execution_agent_ids: set[str] | None = None,
    additional_models: dict[str, tuple[str, ...]] | None = None,
    sequential: bool = False,
    effort_mode: EffortMode | None = None,
    preserved_profile_ids: frozenset[str] = frozenset(),
) -> Plan:
    if plan.questions:
        raise PlanningError("cannot assign agents while clarification is required")
    assign_agents(
        plan.tasks, agents, routing or RoutingConfig(), execution_agent_ids=execution_agent_ids,
        additional_models=additional_models, sequential=sequential, effort_mode=effort_mode, preserved_profile_ids=preserved_profile_ids,
    )
    return plan


def select_agent_for_provider(task: WorkTask, agents: tuple[AgentConfig, ...], provider_id: str, *, purpose: str) -> AgentConfig:
    return _select_agent(task, agents, Counter(), provider_id=provider_id, purpose=purpose)


def assign_task_agent_overrides(
    tasks: list[WorkTask],
    agents: tuple[AgentConfig, ...],
    routing: RoutingConfig,
    overrides: dict[str, str],
    *,
    locked_task_ids: set[str] | None = None,
    sequential: bool = False,
) -> None:
    task_ids = {task.id for task in tasks}
    unknown_tasks = set(overrides) - task_ids
    if unknown_tasks:
        raise PlanningError("unknown task provider overrides: " + ", ".join(sorted(unknown_tasks)))
    locked = set(locked_task_ids or ())
    unknown_locked_tasks = locked - task_ids
    if unknown_locked_tasks:
        raise PlanningError("unknown locked tasks: " + ", ".join(sorted(unknown_locked_tasks)))
    locked_overrides = locked & set(overrides)
    if locked_overrides:
        raise PlanningError("locked tasks cannot be overridden: " + ", ".join(sorted(locked_overrides)))

    agents_by_id = {agent.id: agent for agent in agents}
    assigned: Counter[str] = Counter()
    for task in tasks:
        if task.id not in locked:
            continue
        selected = agents_by_id.get(task.agent_id)
        if selected is None:
            raise PlanningError(f"unknown execution agent for locked task {task.id}: {task.agent_id}")
        if not sequential and assigned[selected.id] >= selected.max_tasks:
            raise PlanningError(f"not enough execution agent capacity for task '{task.title}'")
        assigned[selected.id] += 1
        if routing.review_required or task.reviewer_agent_id:
            reviewer = agents_by_id.get(task.reviewer_agent_id)
            if reviewer is None:
                raise PlanningError(f"unknown review agent for locked task {task.id}: {task.reviewer_agent_id}")
            if not sequential and assigned[reviewer.id] >= reviewer.max_tasks:
                raise PlanningError(f"not enough review agent capacity for task '{task.title}'")
            assigned[reviewer.id] += 1

    for task in tasks:
        if task.id in locked:
            continue
        overridden = task.id in overrides
        selected_id = overrides.get(task.id, task.agent_id)
        selected = agents_by_id.get(selected_id)
        if selected is None:
            raise PlanningError(f"unknown execution agent for task {task.id}: {selected_id}")
        if not sequential and assigned[selected.id] >= selected.max_tasks:
            raise PlanningError(f"not enough execution agent capacity for task '{task.title}'")
        desired = set(task.capabilities)
        overlap = len(desired & set(selected.capabilities))
        if overlap == 0 and "general" not in selected.capabilities:
            raise PlanningError(f"provider {selected.provider_id} has no execution agent capability for task '{task.title}'")

        changed = task.agent_id != selected.id
        task.agent_id = selected.id
        task.provider_id = selected.provider_id
        if overridden:
            task.model = selected.model
            if selected.provider_id == "codex" and (not task.model or task.model in CODEX_MODEL_PRESETS):
                task.model = codex_model_order(preferred=task.model)[0]
        if changed:
            task.routing_reason = "user selected execution provider"
            task.routing_confidence = 1.0
        assigned[selected.id] += 1

        if routing.review_required or task.reviewer_agent_id:
            reviewer = _select_agent(task, agents, assigned, excluded_provider=selected.provider_id, purpose="review", sequential=sequential)
            task.reviewer_agent_id = reviewer.id
            task.reviewer_provider_id = reviewer.provider_id
            task.reviewer_model = reviewer.model
            task.review_status = ReviewStatus.PENDING
            assigned[reviewer.id] += 1


def assign_agents(
    tasks: list[WorkTask],
    agents: tuple[AgentConfig, ...],
    routing: RoutingConfig,
    *,
    execution_agent_ids: set[str] | None = None,
    additional_models: dict[str, tuple[str, ...]] | None = None,
    sequential: bool = False,
    effort_mode: EffortMode | None = None,
    preserved_profile_ids: frozenset[str] = frozenset(),
) -> None:
    assigned: Counter[str] = Counter()
    provider_assignments: Counter[str] = Counter()
    execution_agents = tuple(agent for agent in agents if agent.id in execution_agent_ids) if execution_agent_ids is not None else agents
    for task in tasks:
        recommended_provider = task.provider_id.strip().casefold()
        recommended_model = task.model.strip()
        recommended_effort = task.reasoning_effort.strip().casefold()
        manual = task.profile_source == ProfileSource.MANUAL
        if manual:
            provider_id = recommended_provider
            selectable_agents = tuple(agent for agent in execution_agents if agent.id == task.agent_id and agent.provider_id == provider_id)
            if not selectable_agents:
                raise PlanningError(f"사용자가 선택한 실행 AI를 사용할 수 없습니다: {task.id} · {task.agent_id}")
            reason = task.routing_reason or "user selected execution profile"
            confidence = task.routing_confidence
        elif recommended_provider:
            provider_id = recommended_provider
            reason = "planning AI recommended execution profile"
            confidence = 1.0
            selectable_agents = execution_agents
        else:
            if recommended_model or recommended_effort:
                raise PlanningError(f"task {task.id} execution profile requires provider_id")
            provider_id, reason, confidence, selectable_agents = _route_provider(
                task, routing, execution_agents, assigned, provider_assignments, sequential=sequential,
            )
        selected = _select_agent(task, selectable_agents, assigned, provider_id=provider_id, purpose="execution", sequential=sequential)
        codex_models = enabled_codex_models() if selected.provider_id == "codex" else None
        if codex_models is not None and not manual:
            available_models = codex_models
        else:
            configured = tuple(agent.model for agent in agents if agent.provider_id == selected.provider_id and agent.model)
            extra_models = (additional_models or {}).get(selected.provider_id, ())
            available_models = supported_models(selected.provider_id, (*configured, *extra_models))
        saved_codex_model = manual and task.id in preserved_profile_ids and codex_models is not None and recommended_model in CODEX_MODEL_PRESETS
        if recommended_model and recommended_model not in available_models and not saved_codex_model:
            available = ", ".join(available_models) or "provider default only"
            raise PlanningError(
                f"task {task.id} recommends unsupported model for {selected.provider_id}: {recommended_model}; available: {available}"
            )
        selected_model = recommended_model if manual else recommended_model or selected.model
        if manual and selected.provider_id == "codex" and not selected_model:
            selected_model = codex_model_order(enabled=codex_models)[0]
        if recommended_effort:
            effort_model = recommended_model if codex_models is not None and not manual else selected_model
            supported_efforts = supported_reasoning_efforts(selected.provider_id, effort_model)
            if recommended_effort not in supported_efforts:
                available = ", ".join(supported_efforts) or "provider default only"
                raise PlanningError(
                    f"task {task.id} recommends unsupported reasoning effort for "
                    f"{selected.provider_id}/{effort_model or 'default model'}: "
                    f"{recommended_effort}; available: {available}"
                )
        task.agent_id = selected.id
        task.provider_id = selected.provider_id
        task.model = selected_model
        task.reasoning_effort = recommended_effort
        task.profile_source = ProfileSource.MANUAL if manual else ProfileSource.ROUTING
        task.routing_reason = reason
        task.routing_confidence = confidence
        if selected.provider_id == "codex" and not manual:
            decision = select_codex_model(
                effort_mode or EffortMode.BALANCED, purpose="task", task=task, reasoning_effort=recommended_effort, enabled=codex_models,
            )
            task.model, task.reasoning_effort = decision.model, decision.reasoning_effort
            task.profile_source = ProfileSource.MODE
            task.effort_baseline_reasoning = recommended_effort
            task.model_selection_reason = decision.reason
        elif selected.provider_id == "claude" and automatic_claude_profile(task.profile_source, selected_model):
            decision = select_claude_model(effort_mode or EffortMode.BALANCED, purpose="task", task=task, reasoning_effort=recommended_effort)
            task.model = decision.model
            task.reasoning_effort = recommended_effort if manual and recommended_effort else decision.reasoning_effort
            task.profile_source = ProfileSource.MANUAL if manual and recommended_effort else ProfileSource.MODE
            task.effort_baseline_reasoning = recommended_effort
            task.model_selection_reason = decision.reason
        assigned[selected.id] += 1
        provider_assignments[selected.provider_id] += 1

        if routing.review_required:
            reviewer = _select_agent(task, agents, assigned, excluded_provider=selected.provider_id, purpose="review", sequential=sequential)
            task.reviewer_agent_id = reviewer.id
            task.reviewer_provider_id = reviewer.provider_id
            task.reviewer_model = reviewer.model
            task.review_status = ReviewStatus.PENDING
            assigned[reviewer.id] += 1


def _route_provider(
    task: WorkTask,
    routing: RoutingConfig,
    agents: tuple[AgentConfig, ...],
    assigned: Counter[str],
    provider_assignments: Counter[str],
    *,
    sequential: bool,
) -> tuple[str, str, float, tuple[AgentConfig, ...]]:
    desired = set(task.capabilities)
    matches: list[tuple[int, int, str, tuple[str, ...]]] = []
    for index, rule in enumerate(routing.rules):
        overlap = len(desired & set(rule.capabilities))
        if overlap:
            matches.append((overlap, -index, rule.provider_id, rule.capabilities))
    if matches:
        overlap, _, provider_id, capabilities = max(matches)
        confidence = round(overlap / max(1, len(desired)), 2)
        matched = ", ".join(sorted(desired & set(capabilities)))
        return provider_id, f"routing rule matched: {matched}", confidence, agents
    if routing.balance_providers:
        capable_agents = tuple(
            agent for agent in agents if not agent.manual_only and (desired & set(agent.capabilities) or "general" in agent.capabilities)
        )
        runtime_agents = tuple(agent for agent in capable_agents if agent.provider_id != "custom" or agent.command)
        automatic_agents = runtime_agents or capable_agents
        candidates: dict[str, int] = {}
        for agent in automatic_agents:
            overlap = len(desired & set(agent.capabilities))
            if not sequential and assigned[agent.id] >= agent.max_tasks:
                continue
            candidates[agent.provider_id] = max(candidates.get(agent.provider_id, 0), overlap)
        if not candidates:
            raise PlanningError(f"no available execution agent with capability and capacity for task '{task.title}'")
        provider_id = min(candidates, key=lambda value: (
            provider_assignments[value], -candidates[value], value != routing.default_provider, value,
        ))
        return provider_id, "connected provider workload balance", 1.0, automatic_agents
    if routing.default_provider:
        return routing.default_provider, "project default provider", 0.5, agents
    return "", "legacy capability assignment", 1.0, agents


def _select_agent(
    task: WorkTask,
    agents: tuple[AgentConfig, ...],
    assigned: Counter[str],
    *,
    provider_id: str = "",
    excluded_provider: str = "",
    purpose: str,
    sequential: bool = False,
) -> AgentConfig:
    desired = set(task.capabilities)
    eligible = [
        agent
        for agent in agents
        if (not agent.manual_only or agent.provider_id == provider_id)
        and (not provider_id or agent.provider_id == provider_id) and (not excluded_provider or agent.provider_id != excluded_provider)
    ]
    if not eligible:
        provider_message = provider_id or f"different from {excluded_provider}"
        raise PlanningError(f"no {purpose} agent for provider {provider_message}: '{task.title}'")
    candidates = []
    for agent in eligible:
        overlap = len(desired & set(agent.capabilities))
        general = int("general" in agent.capabilities)
        has_capacity = sequential or assigned[agent.id] < agent.max_tasks
        candidates.append((has_capacity, overlap, general, -assigned[agent.id], agent.id, agent))
    candidates.sort(reverse=True, key=lambda item: item[:5])
    has_capacity, overlap, general, _, _, selected = candidates[0]
    if not has_capacity:
        raise PlanningError(f"not enough {purpose} agent capacity for task '{task.title}'")
    if overlap == 0 and not general:
        raise PlanningError(f"provider {selected.provider_id} has no {purpose} agent capability for task '{task.title}'")
    return selected
