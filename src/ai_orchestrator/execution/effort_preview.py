"""Compose effort previews from agents and availability callbacks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from ..config import AgentConfig
from ..effort_policy import (
    EffortModePreview, EffortTaskPreview, ReasoningDecision, ReviewDecision, resolve_reasoning_profile, resolve_review_decision,
)
from ..errors import PipelineError
from ..models import EffortMode, ProfileSource, RunState, TaskStatus
from .profiles import ReviewerCompatibility


@dataclass(frozen=True, slots=True)
class EffortPreviewBuilder:
    agents: Mapping[str, AgentConfig]
    configured_agents: tuple[AgentConfig, ...]
    default_planning_agent_id: str
    review_required: bool
    reviewer_compatible: ReviewerCompatibility
    is_selectable: Callable[[AgentConfig, str], bool]
    is_available: Callable[[AgentConfig, str], bool]

    def build(
        self, state: RunState, selected: EffortMode, policy_revision: int, *, preserve_execution_profiles: bool = False,
        runtime_excluded_task_ids: frozenset[str] = frozenset(),
    ) -> EffortModePreview:
        planning: ReasoningDecision | None = None
        planning_agent_id = state.planning_agent_id or self.default_planning_agent_id
        if planning_agent_id and not preserve_execution_profiles:
            agent = self.agents.get(planning_agent_id)
            if agent is None:
                raise PipelineError(f"unknown Planning agent: {planning_agent_id}")
            planning = resolve_reasoning_profile(
                mode=selected,
                provider_id=agent.provider_id,
                model=state.planning_model or agent.model,
                reasoning_effort=state.planning_reasoning_effort,
                profile_source=state.planning_profile_source,
                baseline_reasoning_effort=state.planning_effort_baseline_reasoning,
                purpose="planning",
                configured_model=agent.model,
            )
        previews: list[EffortTaskPreview] = []
        manual_ids: list[str] = []
        unsupported: list[str] = []
        requires_review = False
        for task in state.tasks:
            agent = self.agents.get(task.agent_id)
            provider = task.provider_id or (agent.provider_id if agent is not None else "")
            if not provider:
                raise PipelineError(f"task {task.id} has no assigned execution provider")
            model = task.model or (agent.model if agent is not None else "")
            if preserve_execution_profiles:
                reasoning = ReasoningDecision(selected, provider, model, task.reasoning_effort, task.profile_source)
            else:
                reasoning = resolve_reasoning_profile(
                    mode=selected,
                    provider_id=provider,
                    model=model,
                    reasoning_effort=task.reasoning_effort,
                    profile_source=task.profile_source,
                    baseline_reasoning_effort=task.effort_baseline_reasoning,
                    purpose="task", task=task,
                )
            reviewer_available = bool(task.reviewer_agent_id) or any(
                self.reviewer_compatible(task, candidate, policy_added=True)
                and (set(task.capabilities) & set(candidate.capabilities) or "general" in candidate.capabilities)
                and self.is_selectable(candidate, "review")
                for candidate in self.configured_agents
            )
            review = resolve_review_decision(
                mode=selected,
                required=self.review_required,
                explicitly_requested=bool(task.reviewer_agent_id) and not task.review_policy_added and not self.review_required,
                reviewer_agent_id=task.reviewer_agent_id,
                is_code_change=bool(task.expected_paths),
                is_automatic=not preserve_execution_profiles and task.status == TaskStatus.PENDING and bool(task.agent_id),
                reviewer_available=reviewer_available,
            )
            if not preserve_execution_profiles and task.review_policy_added and selected != EffortMode.FOCUSED and not review.required:
                review = ReviewDecision(False, False, False, False, "mode_review_removed", policy_removed=True)
            if task.reviewer_agent_id and not review.policy_removed and task.id not in runtime_excluded_task_ids:
                existing_reviewer = self.agents.get(task.reviewer_agent_id)
                if existing_reviewer is None or not self.is_available(existing_reviewer, "review"):
                    unsupported.append(f"{task.id}:reviewer_unavailable")
                    requires_review = True
            if task.profile_source == ProfileSource.MANUAL:
                manual_ids.append(task.id)
            if task.profile_source == ProfileSource.LEGACY and selected != EffortMode.BALANCED:
                unsupported.append(f"{task.id}:legacy_profile_preserved")
            unsupported.extend(f"{task.id}:{effect}" for effect in (*reasoning.unsupported_effects, *review.unsupported_effects))
            if task.status != TaskStatus.PENDING and (
                reasoning.reasoning_effort != task.reasoning_effort or reasoning.model != task.model
                or reasoning.profile_source != task.profile_source
            ):
                unsupported.append(f"{task.id}:started_task_profile_locked")
                reasoning = ReasoningDecision(selected, provider, model, task.reasoning_effort, task.profile_source)
            if task.status == TaskStatus.PENDING and (
                reasoning.reasoning_effort != task.reasoning_effort
                or reasoning.model != task.model
                or reasoning.profile_source != task.profile_source
                or review.policy_added or review.policy_removed
            ):
                requires_review = True
            if review.requires_reviewer or review.unsupported_effects:
                requires_review = True
            previews.append(EffortTaskPreview(task.id, task.reasoning_effort, reasoning, review, task.reviewer_agent_id))
        if planning is not None:
            unsupported.extend(f"planning:{effect}" for effect in planning.unsupported_effects)
            if (planning.reasoning_effort != state.planning_reasoning_effort or planning.profile_source != state.planning_profile_source
                    or planning.model != (state.planning_model or self.agents[planning_agent_id].model)):
                requires_review = True
        return EffortModePreview(
            selected, policy_revision, state.plan_revision, planning, tuple(previews), tuple(manual_ids),
            tuple(unsupported), requires_review,
        )
