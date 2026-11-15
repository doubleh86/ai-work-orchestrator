"""Dependency, risk, deferred and user-check scheduling rules."""

from __future__ import annotations

from ..errors import PipelineError
from ..models import RiskLevel, RunState, TaskReadiness, TaskStatus, WorkTask


def deferred_execution_task_ids(state: RunState) -> set[str]:
    deferred = {task.id for task in state.tasks if task.status == TaskStatus.DEFERRED}
    while deferred:
        dependents = {task.id for task in state.tasks if deferred.intersection(task.execution_dependencies)} - deferred
        if not dependents:
            break
        deferred.update(dependents)
    return deferred


def waiting_for_user_checks(state: RunState) -> bool:
    blocked = state.user_check_blocked_task_ids()
    remaining = {task.id for task in state.tasks if task.status not in {TaskStatus.COMPLETED, TaskStatus.MERGED}}
    if not remaining:
        return state.integration_user_checks_pending()
    return bool(remaining & blocked) and remaining <= blocked | deferred_execution_task_ids(state)


def ready_tasks(state: RunState, candidates: list[WorkTask]) -> list[WorkTask]:
    state.refresh_task_readiness()
    plan_index = {task.id: index for index, task in enumerate(state.tasks)}
    risk_order = {RiskLevel.HIGH: 0, RiskLevel.MEDIUM: 1, RiskLevel.LOW: 2}
    ready = [task for task in candidates if task.readiness == TaskReadiness.READY]
    return sorted(ready, key=lambda task: (risk_order[task.risk_level], plan_index.get(task.id, len(plan_index))))


def commit_queue_tasks(state: RunState) -> list[WorkTask]:
    tasks = list(state.tasks)
    tasks_by_id = {task.id: task for task in tasks}
    plan_index = {task.id: index for index, task in enumerate(tasks)}
    risk_order = {RiskLevel.HIGH: 0, RiskLevel.MEDIUM: 1, RiskLevel.LOW: 2}
    remaining = set(tasks_by_id)
    completed: set[str] = set()
    ordered: list[WorkTask] = []
    while remaining:
        ready = [
            tasks_by_id[task_id]
            for task_id in remaining
            if all(dependency in completed for dependency in tasks_by_id[task_id].execution_dependencies)
        ]
        if not ready:
            unresolved = ", ".join(sorted(remaining, key=lambda task_id: plan_index[task_id]))
            raise PipelineError(f"commit queue has unresolved dependencies: {unresolved}")
        selected = min(ready, key=lambda task: (risk_order[task.risk_level], plan_index[task.id]))
        ordered.append(selected)
        completed.add(selected.id)
        remaining.remove(selected.id)
    return ordered
