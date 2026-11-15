from __future__ import annotations

import re
from fnmatch import fnmatchcase
from functools import cache
from graphlib import CycleError, TopologicalSorter
from pathlib import PurePosixPath

from ..models import PlanningMode, TaskReadiness, UserCheck, WorkTask
from .contracts import TASK_ID, Plan, PlanningError


def _topological_tasks(tasks: list[WorkTask]) -> list[WorkTask]:
    by_id = {task.id: task for task in tasks}
    for task in tasks:
        for dependency in task.execution_dependencies:
            if dependency == task.id:
                raise PlanningError(f"task {task.id} cannot depend on itself")
            if dependency not in by_id:
                raise PlanningError(f"task {task.id} has unknown dependency: {dependency}")

    ordered: list[WorkTask] = []
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(task: WorkTask) -> None:
        if task.id in visited:
            return
        if task.id in visiting:
            start = visiting.index(task.id)
            cycle = " -> ".join([*visiting[start:], task.id])
            raise PlanningError(f"cyclic task dependency: {cycle}")
        visiting.append(task.id)
        for dependency in task.execution_dependencies:
            visit(by_id[dependency])
        visiting.pop()
        visited.add(task.id)
        ordered.append(task)

    for task in tasks:
        visit(task)
    for task in ordered:
        task.blocked_by = task.execution_dependencies
        task.readiness = TaskReadiness.BLOCKED if task.blocked_by else TaskReadiness.READY
    return ordered


def validate_user_checks(tasks: list[WorkTask], checks: list[UserCheck]) -> None:
    if not checks:
        return
    if len(checks) > 32:
        raise PlanningError("사용자 확인은 최대 32개까지 제출할 수 있습니다.")
    graph = TopologicalSorter({task.id: task.execution_dependencies for task in tasks})
    task_ids = {task.id for task in tasks}
    check_ids: set[str] = set()
    for check in checks:
        if not TASK_ID.fullmatch(check.id) or check.id in task_ids or check.id in check_ids:
            raise PlanningError(f"사용자 확인 ID가 올바르지 않거나 중복됩니다: {check.id}")
        if (not check.title.strip() or not check.instructions.strip() or not check.acceptance_criteria
                or any(not criterion.strip() for criterion in check.acceptance_criteria)):
            raise PlanningError(f"사용자 확인의 제목, 안내, 완료 기준이 필요합니다: {check.id}")
        referenced_tasks = set(check.blocks_task_ids)
        if check.after_task_id:
            referenced_tasks.add(check.after_task_id)
        if missing := referenced_tasks - task_ids:
            raise PlanningError(f"사용자 확인 {check.id}에 등록되지 않은 작업이 있습니다: {', '.join(sorted(missing))}")
        check_ids.add(check.id)
        graph.add(check.id, *((check.after_task_id,) if check.after_task_id else ()))
        for task_id in check.blocks_task_ids:
            graph.add(task_id, check.id)
    try:
        tuple(graph.static_order())
    except CycleError as exc:
        raise PlanningError("작업과 사용자 확인에 순환 의존성이 있습니다: " + " → ".join(exc.args[1])) from exc


def validate_task_graph(tasks: list[WorkTask]) -> list[WorkTask]:
    task_ids: set[str] = set()
    for task in tasks:
        if not TASK_ID.fullmatch(task.id):
            raise PlanningError(f"invalid task id: {task.id}")
        if task.id in task_ids:
            raise PlanningError(f"duplicate task id: {task.id}")
        task_ids.add(task.id)
        validate_prerequisite_flag(task.is_prerequisite)
        for rule in [*task.expected_paths, *task.forbidden_paths]:
            _path_rule_parts(rule)
        overlap = set(task.expected_paths) & set(task.forbidden_paths)
        if overlap:
            paths = ", ".join(sorted(overlap))
            raise PlanningError(f"task {task.id} paths cannot be both expected and forbidden: {paths}")
    if not tasks:
        raise PlanningError("task plan must not be empty")
    return _schedule_conflicting_tasks(tasks)


def validate_prerequisite_flag(value: object) -> bool:
    if not isinstance(value, bool):
        raise PlanningError("is_prerequisite must be a boolean")
    return value


def _path_rule_parts(rule: str) -> tuple[str, ...]:
    parsed = PurePosixPath(rule)
    if (
        not parsed.parts
        or parsed.is_absolute()
        or ".." in parsed.parts
        or "\\" in rule
        or re.match(r"^[a-zA-Z]:", rule)
    ):
        raise PlanningError(f"invalid task change scope rule: {rule!r}")
    return parsed.parts


def task_path_matches(path: str, rule: str) -> bool:
    parts = tuple(path.split("/"))
    pattern = _path_rule_parts(rule)
    if not any(character in rule for character in "*?["):
        return parts[: len(pattern)] == pattern

    @cache
    def matches(path_index: int, rule_index: int) -> bool:
        if rule_index == len(pattern):
            return path_index == len(parts)
        if pattern[rule_index] == "**":
            return matches(path_index, rule_index + 1) or (path_index < len(parts) and matches(path_index + 1, rule_index))
        return path_index < len(parts) and fnmatchcase(parts[path_index], pattern[rule_index]) and matches(path_index + 1, rule_index + 1)

    return matches(0, 0)


def task_paths_may_overlap(first: str, second: str) -> bool:
    left = _path_rule_parts(first)
    right = _path_rule_parts(second)
    if not any(character in first for character in "*?["):
        left += ("**",)
    if not any(character in second for character in "*?["):
        right += ("**",)
    pending = [(0, 0)]
    visited: set[tuple[int, int]] = set()
    while pending:
        i, j = pending.pop()
        if (i, j) in visited:
            continue
        visited.add((i, j))
        if i == len(left) and j == len(right):
            return True
        if i < len(left) and left[i] == "**":
            pending.append((i + 1, j))
        if j < len(right) and right[j] == "**":
            pending.append((i, j + 1))
        if i == len(left) or j == len(right):
            continue
        a, b = left[i], right[j]
        a_glob = any(character in a for character in "*?[")
        b_glob = any(character in b for character in "*?[")
        compatible = (a_glob and b_glob) or (fnmatchcase(b, a) if a_glob else fnmatchcase(a, b))
        if compatible:
            pending.append((i if a == "**" else i + 1, j if b == "**" else j + 1))
    return False


def _schedule_conflicting_tasks(tasks: list[WorkTask]) -> list[WorkTask]:
    for task in tasks:
        task.conflict_dependencies = []
        task.conflict_group = []
    ordered = _topological_tasks(tasks)
    pairs: list[tuple[WorkTask, WorkTask]] = []
    neighbors: dict[str, set[str]] = {task.id: set() for task in tasks}
    for index, first in enumerate(ordered):
        for second in ordered[index + 1 :]:
            if not any(task_paths_may_overlap(a, b) for a in first.expected_paths for b in second.expected_paths):
                continue
            pairs.append((first, second))
            neighbors[first.id].add(second.id)
            neighbors[second.id].add(first.id)
            if first.is_prerequisite != second.is_prerequisite:
                prerequisite, consumer = (first, second) if first.is_prerequisite else (second, first)
                if prerequisite.id not in consumer.execution_dependencies:
                    consumer.conflict_dependencies.append(prerequisite.id)
    try:
        ordered = _topological_tasks(ordered)
    except PlanningError as exc:
        raise PlanningError(f"conflict prerequisite contradicts dependencies: {exc}") from exc
    positions = {task.id: index for index, task in enumerate(ordered)}
    for first, second in pairs:
        earlier, later = sorted((first, second), key=lambda task: positions[task.id])
        if earlier.id not in later.execution_dependencies:
            later.conflict_dependencies.append(earlier.id)
    ordered = _topological_tasks(ordered)
    visited: set[str] = set()
    for task in ordered:
        if task.id in visited or not neighbors[task.id]:
            continue
        component: set[str] = set()
        pending = [task.id]
        while pending:
            current = pending.pop()
            if current in component:
                continue
            component.add(current)
            pending.extend(neighbors[current] - component)
        visited.update(component)
        group = [item.id for item in ordered if item.id in component]
        for item in ordered:
            if item.id in component:
                item.conflict_group = list(group)
    return ordered


def validate_plan_document_references(
    plan: Plan, *, required_instruction_paths: frozenset[str], has_source_root: bool, indexed_source_paths: frozenset[str],
    planning_mode: PlanningMode, require_directory_task_draft: bool, greenfield_bootstrap: bool,
) -> None:
    missing_instruction_paths = sorted(required_instruction_paths - set(plan.instruction_paths))
    if missing_instruction_paths:
        raise PlanningError("planning result omitted active repository instructions: " + ", ".join(missing_instruction_paths))
    if has_source_root:
        unknown_source_paths = sorted(set(plan.source_paths) - indexed_source_paths)
        if unknown_source_paths:
            raise PlanningError("source_paths contains documents outside the planning " "source index: " + ", ".join(unknown_source_paths))
        if not plan.source_paths and not (
            (planning_mode == PlanningMode.DIRECTED or greenfield_bootstrap) and plan.questions and not plan.tasks
        ):
            raise PlanningError("directory planning result requires source_paths")
        if require_directory_task_draft and plan.questions and not plan.tasks:
            raise PlanningError("directory planning clarification requires best-effort tasks from inspected sources")


def validate_planning_phase(
    plan: Plan, *, greenfield_bootstrap: bool, greenfield_initial: bool, greenfield_feature: bool,
) -> None:
    if greenfield_bootstrap:
        if greenfield_initial and plan.tasks:
            raise PlanningError("new project Planning must present technology choices before creating a bootstrap Task")
        if not plan.tasks and not plan.tech_stack_options and not plan.questions:
            raise PlanningError("new project Planning must return one to three structured technology stack options")
        if plan.tasks:
            if plan.tech_stack_options:
                raise PlanningError("project-bootstrap Planning cannot return technology stack options")
            if plan.questions:
                raise PlanningError("new project Planning cannot mix unresolved questions with a bootstrap Task")
            if len(plan.tasks) != 1 or plan.tasks[0].id != "project-bootstrap":
                raise PlanningError("new project Planning requires exactly one project-bootstrap Task")
            if plan.tasks[0].dependencies:
                raise PlanningError("project-bootstrap cannot depend on feature Tasks")
    elif plan.tech_stack_options:
        raise PlanningError("technology stack options are only valid for new project Planning")
    if greenfield_feature and any(task.id == "project-bootstrap" for task in plan.tasks):
        raise PlanningError("feature Planning cannot return the project-bootstrap Task")
