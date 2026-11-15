"""Build and validate execution policy snapshots."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol

from ..config import AgentConfig
from ..effort_policy import EffortModePreview
from ..errors import PipelineError
from ..models import (
    EffortMode, EffortProfileSnapshot, EffortReviewSnapshot, ProfileSource, ResolvedEffortPolicy, RunState, WorkTask, utc_now,
    EffortPolicyState, RunStep, Stage,
)
from .profiles import ReviewerCompatibility


def build_execution_policy_snapshot(
    state: RunState, preview: EffortModePreview, *, agents: Mapping[str, AgentConfig], default_planning_agent_id: str,
) -> ResolvedEffortPolicy:
    planning: EffortProfileSnapshot | None = None
    planning_agent_id = state.planning_agent_id or default_planning_agent_id
    if planning_agent_id:
        planning_agent = agents.get(planning_agent_id)
        if planning_agent is None:
            raise PipelineError(f"unknown Planning agent: {planning_agent_id}")
        planning = EffortProfileSnapshot(
            planning_agent.id, planning_agent.provider_id, state.planning_model or planning_agent.model,
            state.planning_reasoning_effort, state.planning_profile_source,
        )
    task_profiles = tuple(
        (
            task.id,
            EffortProfileSnapshot(
                task.agent_id, task.provider_id, task.model, task.reasoning_effort, task.profile_source,
            ),
        )
        for task in state.tasks
    )
    previews = {item.task_id: item for item in preview.tasks}
    reviews = tuple(
        EffortReviewSnapshot(
            task_id=task.id,
            required=previews[task.id].review.required,
            optional=bool(task.reviewer_agent_id) and not previews[task.id].review.required,
            reason=("focused_code_change_review" if task.review_policy_added else previews[task.id].review.reason),
            reviewer_agent_id=task.reviewer_agent_id,
            policy_added=task.review_policy_added,
            replaces_existing_review=(
                preview.mode == EffortMode.FOCUSED and bool(task.reviewer_agent_id)
                and not task.review_policy_added and not previews[task.id].review.required
            ),
            reviewer_provider_id=task.reviewer_provider_id,
            reviewer_model=task.reviewer_model,
        )
        for task in state.tasks
    )
    return ResolvedEffortPolicy(
        str(uuid.uuid4()), 3, preview.mode, "execution", state.plan_revision, planning, task_profiles,
        reviews, preview.manual_exception_ids, preview.unsupported_effects, utc_now(),
    )


@dataclass(frozen=True, slots=True)
class ExecutionPolicyValidator:
    agents: Mapping[str, AgentConfig]
    load_profiles: Callable[[str], dict[str, dict[str, object]]]
    escalation_matches: Callable[[WorkTask, EffortProfileSnapshot, ResolvedEffortPolicy], bool]
    quota_matches: Callable[[WorkTask, EffortProfileSnapshot, ResolvedEffortPolicy, dict[str, object]], bool]

    def validate(self, state: RunState, policy: ResolvedEffortPolicy) -> None:
        if not state.plan_is_approved or state.plan_revision != policy.plan_revision:
            raise PipelineError("started effort policy no longer matches the approved plan revision")
        profiles = dict(policy.task_profiles)
        reviews = {item.task_id: item for item in policy.review_decisions}
        if set(profiles) != {task.id for task in state.tasks} or set(reviews) != set(profiles):
            raise PipelineError("started effort policy task set differs from the RunState plan")
        manual_receipts = self.load_profiles(state.id)
        for task in state.tasks:
            expected = profiles[task.id]
            if (
                task.agent_id, task.provider_id, task.model, task.reasoning_effort, task.profile_source
            ) != (
                expected.agent_id, expected.provider_id, expected.model, expected.reasoning_effort, expected.profile_source
            ):
                receipt = manual_receipts.get(f"{task.id}@{policy.policy_id}", {})
                selected = {"agent_id": task.agent_id, "model": task.model, "reasoning_effort": task.reasoning_effort}
                if not self.escalation_matches(task, expected, policy) and not self.quota_matches(
                        task, expected, policy, receipt) and (
                        receipt.get("applied_policy_id") != policy.policy_id or receipt.get("plan_revision") != policy.plan_revision
                        or receipt.get("policy_baseline") != expected.to_dict() or receipt.get("selection") != selected
                        or task.profile_source != ProfileSource.MANUAL):
                    raise PipelineError(f"started effort policy profile differs for task {task.id}")
            worker = self.agents.get(task.agent_id)
            if worker is None or worker.provider_id != task.provider_id:
                raise PipelineError(f"started effort policy worker runtime differs for task {task.id}")
            review = reviews[task.id]
            if task.reviewer_agent_id != review.reviewer_agent_id or task.review_policy_added != review.policy_added:
                raise PipelineError(f"started effort policy review differs for task {task.id}")
            if policy.policy_version >= 2 and (
                task.reviewer_provider_id != review.reviewer_provider_id or task.reviewer_model != review.reviewer_model
            ):
                raise PipelineError(f"started effort policy reviewer profile differs for task {task.id}")
            if task.reviewer_agent_id:
                reviewer = self.agents.get(task.reviewer_agent_id)
                if reviewer is None or (
                    policy.policy_version >= 2
                    and (reviewer.provider_id, reviewer.model) != (review.reviewer_provider_id, review.reviewer_model)
                ):
                    raise PipelineError(f"started effort policy reviewer runtime differs for task {task.id}")


class SavedExecutionPreview(Protocol):
    def __call__(
        self, state: RunState, selected: EffortMode, policy_revision: int, *, preserve_execution_profiles: bool = False,
        runtime_excluded_task_ids: frozenset[str] = frozenset(),
    ) -> EffortModePreview:
        ...


class CurrentExecutionPreview(Protocol):
    def __call__(self, run_id: str, mode: EffortMode | str, *, expected_revision: int) -> EffortModePreview:
        ...


@dataclass(frozen=True, slots=True)
class ExecutionPolicyPreflight:
    read_agents: Callable[[], Mapping[str, AgentConfig]]
    require_confirmed_plan: Callable[[RunState], None]
    saved_preview: SavedExecutionPreview
    current_preview: CurrentExecutionPreview
    available_agent: Callable[[str, str], AgentConfig]
    reviewer_compatible: ReviewerCompatibility

    def prepare(
        self, state: RunState, saved_policy: EffortPolicyState, *, agent_overrides: dict[str, str] | None,
        model_overrides: dict[str, str] | None, reasoning_effort_overrides: dict[str, str] | None,
        recover_saved_profiles: bool = False, check_blocked_task_ids: frozenset[str] = frozenset(),
    ) -> EffortModePreview | None:
        if recover_saved_profiles and (state.archive or not (
            state.stage == Stage.EXECUTING or state.stage == Stage.FAILED and state.failed_step == RunStep.AGENT_EXECUTION
        )):
            raise PipelineError("saved effort profiles can only recover an existing task execution")
        mode = (saved_policy.recovery_mode(state.plan_revision) if recover_saved_profiles
                else saved_policy.pending_execution_mode or saved_policy.selected_mode)
        if mode is None:
            return None
        if state.stage == Stage.FAILED and state.failed_step != RunStep.AGENT_EXECUTION:
            raise PipelineError("effort execution can resume only an agent execution failure")
        if agent_overrides or model_overrides or reasoning_effort_overrides:
            raise PipelineError("edit and reconfirm the plan before overriding a selected effort policy profile")
        self.require_confirmed_plan(state)
        if recover_saved_profiles or check_blocked_task_ids:
            preview = self.saved_preview(
                state, mode, saved_policy.revision, preserve_execution_profiles=recover_saved_profiles,
                runtime_excluded_task_ids=check_blocked_task_ids,
            )
        else:
            preview = self.current_preview(state.id, mode, expected_revision=saved_policy.revision)
        if preview.plan_revision != state.plan_revision or preview.requires_plan_review:
            raise PipelineError("policy_plan_review_required: selected effort mode differs from the approved plan")
        if any(effect.endswith(":reviewer_unavailable") or effect.endswith(":mode_profile_baseline_missing")
               for effect in preview.unsupported_effects):
            raise PipelineError("policy_plan_review_required: effort policy has an unavailable reviewer or missing profile baseline")
        for task in state.tasks:
            worker = self.read_agents().get(task.agent_id)
            if worker is None or worker.provider_id != task.provider_id:
                raise PipelineError(f"policy_plan_review_required: worker profile differs for task {task.id}")
            if not task.reviewer_agent_id:
                continue
            reviewer = (self.read_agents().get(task.reviewer_agent_id) if task.id in check_blocked_task_ids
                        else self.available_agent(task.reviewer_agent_id, "review"))
            if reviewer is None or (reviewer.provider_id, reviewer.model) != (task.reviewer_provider_id, task.reviewer_model) or (
                not self.reviewer_compatible(task, reviewer, policy_added=task.review_policy_added)
            ):
                raise PipelineError(f"policy_plan_review_required: reviewer profile differs for task {task.id}")
        return preview
