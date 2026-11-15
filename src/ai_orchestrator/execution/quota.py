"""Record automatic quota fallbacks at a caller-owned dispatch boundary."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Callable, Mapping

from ..account_usage import AccountUsage, quota_exhausted
from ..config import AgentConfig, RoutingConfig
from ..errors import PipelineError, ProviderRequestLimitError
from ..models import EffortMode, EffortProfileSnapshot, ProfileSource, ResolvedEffortPolicy, RunState, RunStep, TaskStatus, WorkTask, utc_now
from ..planning import Plan, PlanningError, assign_plan_agents
from .profile_requests import TaskProfileRecords
from .profiles import ReviewerCompatibility, task_execution_profile_snapshot


def apply_quota_profile(task: WorkTask, receipt: dict[str, object]) -> None:
    selected = EffortProfileSnapshot.from_dict(receipt["quota_fallback"])
    task.agent_id, task.provider_id = selected.agent_id, selected.provider_id
    task.model, task.reasoning_effort, task.profile_source = selected.model, selected.reasoning_effort, selected.profile_source
    task.effort_baseline_reasoning = receipt["quota_baseline_reasoning"]
    task.model_selection_reason = receipt["quota_model_selection_reason"]
    task.routing_reason = f"{receipt['quota_exhausted_provider']} 한도 소진 → {selected.provider_id} 자동 전환"
    task.routing_confidence = 1.0


def quota_fallback_matches(
    task: WorkTask, expected: EffortProfileSnapshot, policy: ResolvedEffortPolicy, receipt: dict[str, object], *,
    escalation_matches: Callable[[WorkTask, EffortProfileSnapshot, ResolvedEffortPolicy], bool],
) -> bool:
    if ("quota_fallback" not in receipt or receipt.get("applied_policy_id") != policy.policy_id
            or receipt.get("plan_revision") != policy.plan_revision or receipt.get("policy_baseline") != expected.to_dict()
            or expected.profile_source not in {ProfileSource.MODE, ProfileSource.ROUTING}):
        return False
    selected = EffortProfileSnapshot.from_dict(receipt["quota_fallback"])
    actual = EffortProfileSnapshot(task.agent_id, task.provider_id, task.model, task.reasoning_effort, task.profile_source)
    return actual == selected or escalation_matches(task, selected, policy)


@dataclass(frozen=True, slots=True)
class QuotaFallbackService:
    agents: Mapping[str, AgentConfig]
    configured_agents: tuple[AgentConfig, ...]
    routing: RoutingConfig
    records: TaskProfileRecords
    read_usage: Callable[[str], AccountUsage]
    is_selectable: Callable[[AgentConfig, str], bool]
    connected_providers: Callable[[set[str]], set[str]]
    reviewer_compatible: ReviewerCompatibility
    shared_workspace: Callable[[RunState], bool]
    refresh_plan: Callable[[RunState], None]

    def apply(self, state: RunState, ready: list[WorkTask]) -> None:
        """Check account limits at a dispatch boundary, before any task starts."""
        profiles = self.records.load_requests(state.id)
        policy = self.records.load_policy(state.id).policy(state.active_policy_id) if state.active_policy_id else None
        if state.active_policy_id and policy is None:
            raise PipelineError("started effort execution policy snapshot is missing")
        mode = policy.mode if policy else self.records.load_policy(state.id).selected_mode or EffortMode.BALANCED
        connected_agents: tuple[AgentConfig, ...] | None = None
        for task in ready:
            if (task.status != TaskStatus.PENDING or task.active_action or task.attempt_count or task.last_attempt_id or task.action_results):
                continue
            key = f"{task.id}@{state.active_policy_id or 'unbound'}"
            receipt = profiles.get(key, {})
            # A receipt is durable before RunState, allowing an interrupted save
            # to resume the same approved automatic selection without guessing.
            if ("quota_fallback" in receipt and receipt["plan_revision"] == state.plan_revision
                    and receipt["expected"] == task_execution_profile_snapshot(task)):
                apply_quota_profile(task, receipt)
                state.add_event("routing", f"{task.id} · {task.routing_reason}")
                self.records.save_state(state)
                self.refresh_plan(state)
            if not quota_exhausted(self.read_usage(task.provider_id)):
                continue
            fixed_rule = any(set(task.capabilities) & set(rule.capabilities) for rule in self.routing.rules)
            if task.profile_source not in {ProfileSource.MODE, ProfileSource.ROUTING} or fixed_rule:
                message = f"{task.provider_id} 사용 한도를 모두 사용했습니다. 직접 지정한 작업 AI를 변경하거나 한도 초기화를 기다려 주세요."
                state.fail_step(RunStep.AGENT_EXECUTION, message)
                self.records.save_state(state)
                raise ProviderRequestLimitError(message)
            if connected_agents is None:
                candidates = tuple(
                    agent for agent in self.configured_agents if not agent.manual_only and self.is_selectable(agent, "execute")
                )
                connected = self.connected_providers({agent.provider_id for agent in candidates})
                connected_agents = tuple(
                    agent for agent in candidates if agent.provider_id in connected
                    and not quota_exhausted(self.read_usage(agent.provider_id))
                )
            alternatives = tuple(
                agent for agent in connected_agents if agent.provider_id != task.provider_id
                and (not task.reviewer_agent_id or self.reviewer_compatible(
                    replace(task, agent_id=agent.id, provider_id=agent.provider_id), self.agents[task.reviewer_agent_id],
                    policy_added=task.review_policy_added,
                ))
            )
            if not self.shared_workspace(state):
                alternatives = tuple(
                    replace(agent, max_tasks=max(0, agent.max_tasks - sum(
                        other.id != task.id and other.agent_id == agent.id for other in ready
                    ))) for agent in alternatives
                )
            proposed = deepcopy(task)
            proposed.agent_id = proposed.provider_id = proposed.model = proposed.reasoning_effort = ""
            proposed.profile_source = ProfileSource.ROUTING
            proposed.effort_baseline_reasoning = None
            try:
                assign_plan_agents(
                    Plan("quota fallback", False, [proposed]), alternatives,
                    replace(self.routing, rules=(), review_required=False, balance_providers=True),
                    sequential=self.shared_workspace(state), effort_mode=mode,
                )
            except PlanningError as exc:
                message = f"{task.provider_id} 사용 한도를 모두 사용했습니다. 전환 가능한 연결 AI가 없습니다. AI 연결이나 한도 초기화를 확인해 주세요."
                state.fail_step(RunStep.AGENT_EXECUTION, message)
                self.records.save_state(state)
                raise ProviderRequestLimitError(message) from exc
            selected = EffortProfileSnapshot(
                proposed.agent_id, proposed.provider_id, proposed.model, proposed.reasoning_effort, proposed.profile_source,
            )
            profiles[key] = {
                "expected": task_execution_profile_snapshot(task), "plan_revision": state.plan_revision, "saved_at": utc_now(),
                "selection": {"agent_id": proposed.agent_id, "model": proposed.model, "reasoning_effort": proposed.reasoning_effort},
                "applied_policy_id": state.active_policy_id,
                "policy_baseline": dict(policy.task_profiles)[task.id].to_dict() if policy else None,
                "quota_fallback": selected.to_dict(), "quota_exhausted_provider": task.provider_id,
                "quota_baseline_reasoning": proposed.effort_baseline_reasoning,
                "quota_model_selection_reason": proposed.model_selection_reason,
            }
            self.records.save_requests(state.id, profiles)
            apply_quota_profile(task, profiles[key])
            state.add_event("routing", f"{task.id} · {task.routing_reason}")
            self.records.save_state(state)
            self.refresh_plan(state)
