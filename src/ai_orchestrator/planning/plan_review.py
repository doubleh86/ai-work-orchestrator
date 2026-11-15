"""Plan confirmation inputs and exclusions under caller-owned locks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from ..effort_policy import EffortModePreview
from ..errors import PipelineError
from ..models import EffortMode, EffortPolicyState, RunState, TaskStatus, WorkTask
from .contracts import Plan, PlanningError
from .validation import validate_task_graph, validate_user_checks


class ConfirmationEffortPreview(Protocol):
    def __call__(self, run_id: str, mode: EffortMode, *, expected_revision: int) -> EffortModePreview: ...


@dataclass(frozen=True, slots=True)
class PlanConfirmation:
    load_policy: Callable[[str], EffortPolicyState]
    preview: ConfirmationEffortPreview
    protected_bootstrap: Callable[[RunState], WorkTask | None]
    validate_draft: Callable[[RunState, list[dict[str, object]]], Plan]
    task_draft: Callable[[WorkTask], dict[str, object]]
    plan_paths: Callable[[RunState], tuple[list[str], list[str]]]

    def prepare(
        self, state: RunState, run_id: str, *, expected_revision: int | None, expected_bootstrap_digest: str,
    ) -> Plan:
        if expected_revision is not None and state.plan_revision != expected_revision:
            raise PipelineError("검토한 계획이 변경되었습니다. 현재 계획을 다시 확인해 주세요.")
        if expected_bootstrap_digest and (state.bootstrap_spec is None or state.bootstrap_spec.digest != expected_bootstrap_digest):
            raise PipelineError("검토한 기본 구조 범위가 변경되었습니다. 현재 계획을 다시 확인해 주세요.")
        effort_policy = self.load_policy(run_id)
        if effort_policy.selected_mode is not None:
            preview = self.preview(
                run_id, effort_policy.selected_mode, expected_revision=effort_policy.revision
            )
            if preview.requires_plan_review:
                raise PipelineError("selected effort mode must be applied to the plan before confirmation")
        protected_bootstrap = self.protected_bootstrap(state)
        if any(task.status != TaskStatus.PENDING and task is not protected_bootstrap for task in state.tasks):
            raise PipelineError("task plan cannot be confirmed after execution has started")
        if state.plan_revision == 0:
            state.revise_plan()
        if all(
            task.description and task.capabilities and task.acceptance_criteria and task.expected_paths and task.verify_commands
            for task in state.tasks
        ):
            plan = self.validate_draft(state, [self.task_draft(task) for task in state.tasks])
        else:
            try:
                ordered_tasks = validate_task_graph(state.tasks)
            except PlanningError as exc:
                raise PipelineError(f"invalid task plan: {exc}") from exc
            source_paths, instruction_paths = self.plan_paths(state)
            plan = Plan(
                summary=state.summary or f"Task {len(state.tasks)}개 계획",
                server_work=state.server_work,
                tasks=ordered_tasks,
                source_paths=source_paths,
                instruction_paths=instruction_paths,
            )
        state.tasks = [
            protected_bootstrap if protected_bootstrap is not None and task.id == protected_bootstrap.id else task
            for task in plan.tasks
        ]
        state.tasks = validate_task_graph(state.tasks)
        state.refresh_task_readiness()
        return plan


@dataclass(frozen=True, slots=True)
class TaskPlanExclusion:
    plan_paths: Callable[[RunState], tuple[list[str], list[str]]]
    write_plan: Callable[[RunState, Plan], None]
    save_state: Callable[[RunState], None]

    def exclude_locked(self, state: RunState, selected_ids: list[str]) -> RunState:
        tasks_by_id = {task.id: task for task in state.tasks}
        unknown_ids = sorted(set(selected_ids) - set(tasks_by_id))
        if unknown_ids:
            raise PipelineError("unknown tasks: " + ", ".join(unknown_ids))
        non_pending_ids = sorted(task_id for task_id in selected_ids if tasks_by_id[task_id].status != TaskStatus.PENDING)
        if non_pending_ids:
            raise PipelineError("only pending tasks can be excluded: " + ", ".join(non_pending_ids))

        selected = set(selected_ids)
        remaining = [task for task in state.tasks if task.id not in selected]
        if not remaining:
            raise PipelineError("cannot exclude every task from a planned run")
        dependent_tasks = {
            task.id: sorted(selected.intersection(task.dependencies)) for task in remaining if selected.intersection(task.dependencies)
        }
        if dependent_tasks:
            details = "; ".join(f"{task_id} -> {', '.join(dependencies)}" for task_id, dependencies in sorted(dependent_tasks.items()))
            raise PipelineError("remaining tasks depend on excluded tasks: " + details)

        try:
            tasks = validate_task_graph(remaining)
            validate_user_checks(tasks, state.user_check_plan)
        except PlanningError as exc:
            raise PipelineError(f"invalid task plan: {exc}") from exc
        state.tasks = tasks
        state.refresh_task_readiness()
        state.revise_plan()
        source_paths, instruction_paths = self.plan_paths(state)
        self.write_plan(
            state,
            Plan(
                summary=state.summary,
                server_work=state.server_work,
                tasks=state.tasks,
                source_paths=source_paths,
                instruction_paths=instruction_paths,
            ),
        )
        state.add_event("planning", "tasks excluded from execution plan: " + ", ".join(selected_ids))
        self.save_state(state)
        return state


def protected_greenfield_bootstrap(state: RunState) -> WorkTask | None:
    if state.repository_intent != "new_project" or state.greenfield_phase != "feature_plan_ready":
        return None
    bootstrap = next((task for task in state.tasks if task.id == "project-bootstrap"), None)
    if bootstrap is None or bootstrap.status not in {TaskStatus.COMPLETED, TaskStatus.MERGED}:
        return None
    return bootstrap
