"""Prepare and persist effort plan profiles through caller-owned APIs."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol

from ..config import AgentConfig
from ..effort_policy import EffortModePreview
from ..errors import PipelineError
from ..models import EffortMode, EffortPolicyRevisionError, EffortPolicyState, ProfileSource, ReviewStatus, RunState, TaskStatus
from ..planning.contracts import Plan
from ..planning.validation import validate_task_graph
from .profiles import ReviewerCompatibility


@dataclass(frozen=True, slots=True)
class EffortPlanChange:
    state: RunState
    changed: bool
    planning_changed: bool


@dataclass(frozen=True, slots=True)
class EffortPlanApplicator:
    agents: Mapping[str, AgentConfig]
    default_planning_agent_id: str
    available_agent: Callable[[str, str], AgentConfig]
    reviewer_compatible: ReviewerCompatibility
    is_selectable: Callable[[AgentConfig, str], bool]

    def prepare(
        self, state: RunState, preview: EffortModePreview, *, reviewer_agent_ids: dict[str, str] | None = None,
    ) -> EffortPlanChange:
        if any(effect.endswith(":mode_profile_baseline_missing") for effect in preview.unsupported_effects):
            raise PipelineError("cannot apply effort mode without the original routing reasoning profile")
        if any(effect.endswith(":reviewer_unavailable") for effect in preview.unsupported_effects):
            raise PipelineError("effort mode plan has an unavailable required or existing reviewer")
        if any(item.review.requires_reviewer and not item.review.policy_added for item in preview.tasks):
            raise PipelineError("required review needs a reviewer in the plan before applying the effort mode")
        reviewer_choices = reviewer_agent_ids or {}
        added_ids = {item.task_id for item in preview.tasks if item.review.policy_added}
        if set(reviewer_choices) != added_ids:
            raise PipelineError("focused review requires an explicit reviewer for each newly reviewed task")
        tasks_by_id = {task.id: task for task in state.tasks}
        reviewers: dict[str, AgentConfig] = {}
        for task_id, reviewer_id in reviewer_choices.items():
            task = tasks_by_id[task_id]
            reviewer = self.available_agent(reviewer_id, "review")
            if not self.reviewer_compatible(task, reviewer, policy_added=True):
                raise PipelineError(f"reviewer must use a different provider for task {task_id}")
            if not (set(task.capabilities) & set(reviewer.capabilities) or "general" in reviewer.capabilities):
                raise PipelineError(f"reviewer lacks required capability for task {task_id}")
            if not self.is_selectable(reviewer, "review"):
                raise PipelineError(f"reviewer is not selectable for task {task_id}")
            reviewers[task_id] = reviewer
        updated = deepcopy(state)
        changed = False
        planning_changed = preview.planning_reasoning is not None and (
            updated.planning_reasoning_effort != preview.planning_reasoning.reasoning_effort
            or (updated.planning_model or self.agents[updated.planning_agent_id or self.default_planning_agent_id].model)
            != preview.planning_reasoning.model
            or updated.planning_profile_source != preview.planning_reasoning.profile_source
        )
        if planning_changed and preview.planning_reasoning is not None:
            if updated.planning_profile_source != ProfileSource.MODE and preview.planning_reasoning.profile_source == ProfileSource.MODE:
                updated.planning_effort_baseline_reasoning = updated.planning_reasoning_effort
            elif preview.planning_reasoning.profile_source != ProfileSource.MODE:
                updated.planning_effort_baseline_reasoning = None
            updated.planning_reasoning_effort = preview.planning_reasoning.reasoning_effort
            updated.planning_model = preview.planning_reasoning.model
            updated.planning_profile_source = preview.planning_reasoning.profile_source
            changed = True
        for task, item in zip(updated.tasks, preview.tasks, strict=True):
            if (task.reasoning_effort != item.reasoning.reasoning_effort or task.profile_source != item.reasoning.profile_source
                    or task.model != item.reasoning.model):
                if task.profile_source != ProfileSource.MODE and item.reasoning.profile_source == ProfileSource.MODE:
                    task.effort_baseline_reasoning = task.reasoning_effort
                elif item.reasoning.profile_source != ProfileSource.MODE:
                    task.effort_baseline_reasoning = None
                task.reasoning_effort = item.reasoning.reasoning_effort
                task.model = item.reasoning.model
                task.profile_source = item.reasoning.profile_source
                changed = True
            if item.reasoning.selection_reason:
                task.model_selection_reason = item.reasoning.selection_reason
            if item.review.policy_removed:
                task.reviewer_agent_id = ""
                task.reviewer_provider_id = ""
                task.reviewer_model = ""
                task.review_policy_added = False
                task.review_status = ReviewStatus.NOT_REQUIRED
                changed = True
            elif item.review.policy_added:
                reviewer = reviewers[task.id]
                task.reviewer_agent_id = reviewer.id
                task.reviewer_provider_id = reviewer.provider_id
                task.reviewer_model = reviewer.model
                task.review_policy_added = True
                task.review_status = ReviewStatus.PENDING
                changed = True
        return EffortPlanChange(updated, changed, planning_changed)


class EffortPlanPreview(Protocol):
    def __call__(self, run_id: str, mode: EffortMode, *, expected_revision: int) -> EffortModePreview: ...


class EffortPlanPreparation(Protocol):
    def __call__(
        self, state: RunState, preview: EffortModePreview, *, reviewer_agent_ids: dict[str, str] | None,
    ) -> EffortPlanChange: ...


@dataclass(frozen=True, slots=True)
class EffortPlanApplication:
    load_policy: Callable[[str], EffortPolicyState]
    preview: EffortPlanPreview
    prepare: EffortPlanPreparation
    plan_paths: Callable[[RunState], tuple[list[str], list[str]]]
    write_plan: Callable[[RunState, Plan], None]
    save_state: Callable[[RunState], None]
    chat_exists: Callable[[str], bool]
    save_chat: Callable[[RunState], None]

    def apply_locked(
        self, state: RunState, run_id: str, selected: EffortMode, *, expected_policy_revision: int,
        expected_plan_revision: int, reviewer_agent_ids: dict[str, str] | None,
    ) -> RunState:
        if state.archive or any(task.status != TaskStatus.PENDING for task in state.tasks):
            raise PipelineError("effort mode cannot change a plan after task execution has started")
        policy = self.load_policy(run_id)
        if policy.revision != expected_policy_revision:
            raise EffortPolicyRevisionError(
                f"effort policy revision mismatch: expected {expected_policy_revision}, actual {policy.revision}"
            )
        if state.plan_revision != expected_plan_revision:
            raise PipelineError(
                f"plan revision mismatch: expected {expected_plan_revision}, actual {state.plan_revision}"
            )
        if policy.selected_mode != selected:
            raise PipelineError("effort mode must be saved before applying it to the plan")
        preview = self.preview(run_id, selected, expected_revision=expected_policy_revision)
        change = self.prepare(state, preview, reviewer_agent_ids=reviewer_agent_ids)
        updated, changed, planning_changed = change.state, change.changed, change.planning_changed
        if changed:
            updated.tasks = validate_task_graph(updated.tasks)
            updated.refresh_task_readiness()
            updated.revise_plan()
            source_paths, instruction_paths = self.plan_paths(state)
            self.write_plan(
                updated,
                Plan(
                    summary=updated.summary, server_work=updated.server_work, tasks=updated.tasks,
                    source_paths=source_paths, instruction_paths=instruction_paths,
                ),
            )
            updated.add_event("planning", f"effort mode {selected.value} applied to plan revision {updated.plan_revision}")
            self.save_state(updated)
            if planning_changed and self.chat_exists(run_id):
                self.save_chat(updated)
        return updated
