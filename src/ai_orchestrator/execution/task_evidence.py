"""Task scope ownership, diagnostic records and code-style evidence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, Sequence

from ..code_style import inspect_task_code_style
from ..errors import PipelineError
from ..git_contracts import GitError, LOCAL_GIT_TIMEOUT_SECONDS
from ..models import RunState, TaskAction, TaskActionResult, TaskStatus, WorkTask, utc_now
from ..planning.contracts import PlanningError
from ..planning.validation import task_path_matches
from ..task_scope_review import TaskScopeReview, stored_scope_review, task_scope_report

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..git import GitWorkspace


class TaskStyleEvidence(Protocol):
    def __call__(
        self, state: RunState, task: WorkTask, result: TaskActionResult, *,
        failed_command: Sequence[str] | None = None, unavailable_command: Sequence[str] | None = None,
    ) -> None: ...


def scope_contract_digest(task: WorkTask) -> str:
    return hashlib.sha256(json.dumps([task.expected_paths, task.forbidden_paths], ensure_ascii=False).encode()).hexdigest()


def scope_path_matches(path: str, rule: str) -> bool:
    try:
        return task_path_matches(path, rule)
    except PlanningError as exc:
        raise PipelineError(str(exc)) from exc


def task_scope_review(task: WorkTask) -> TaskScopeReview | None:
    if task.status != TaskStatus.FAILED or task.failed_action not in {None, TaskAction.EXECUTE, TaskAction.REVISE}:
        return None
    latest = task.action_results[-1] if task.action_results else None
    if (latest is None or latest.status != "failed" or latest.action not in {TaskAction.EXECUTE, TaskAction.REVISE}
            or not task.last_attempt_id or latest.attempt_id != task.last_attempt_id
            or task.failed_action is not None and latest.action != task.failed_action):
        return None
    try:
        review = stored_scope_review(task.error)
        if review is not None:
            if review.contract and review.contract != scope_contract_digest(task) and (
                not review.paths or scope_review_paths_allowed(task, review)
            ):
                return None
            return review
        if "produced no commit" not in task.error:
            return None
        review = task_scope_report(latest.worker_response, legacy=True)
    except ValueError:
        return None  # The original response/error remains visible as diagnostic evidence.
    if review is not None and review.paths and scope_review_paths_allowed(task, review):
        return None
    return review


def scope_review_paths_allowed(task: WorkTask, review: TaskScopeReview) -> bool:
    return all(
        not any(scope_path_matches(path, rule) for rule in task.forbidden_paths)
        and (not task.expected_paths or any(scope_path_matches(path, rule) for rule in task.expected_paths))
        for path in review.paths
    )


def refresh_task_code_style_evidence(
    state: RunState,
    task: WorkTask,
    result: TaskActionResult,
    *,
    failed_command: Sequence[str] | None = None,
    unavailable_command: Sequence[str] | None = None,
) -> None:
    if state.code_style_snapshot is None:
        return
    result.code_style_evidence = inspect_task_code_style(
        Path(task.worktree),
        state.code_style_snapshot,
        result.changed_paths,
        passed_commands=result.passed_commands,
        failed_command=failed_command,
        unavailable_command=unavailable_command,
    )


@dataclass(frozen=True, slots=True)
class TaskScopeInspector:
    git: GitWorkspace
    run_directory: Callable[[str], Path]
    shared_workspace: Callable[[RunState], bool]

    def exclusions(self, state: RunState, task: WorkTask, head: str) -> dict[str, list[str]]:
        if not self.shared_workspace(state) or not any(item.id == task.id for item in state.tasks):
            return {}
        worktree = Path(task.worktree).resolve()
        if state.execution_worktree and worktree != Path(state.execution_worktree).resolve():
            return {}
        history = set(self.git.commit_ids_between(
            worktree, task.started_commit, head, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
        ))
        if not history:
            return {}
        ranges: dict[tuple[str, str], set[str]] = {}

        def action_commits(result: TaskActionResult) -> set[str]:
            if result.result_commit not in history or not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", result.baseline_commit):
                return set()
            key = (result.baseline_commit, result.result_commit)
            if key not in ranges:
                ranges[key] = set(self.git.commit_ids_between(
                    worktree, *key, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
                )) & history
            return ranges[key]

        owned = set().union(*(action_commits(result) for result in task.action_results
                              if result.action in {TaskAction.EXECUTE.value, TaskAction.REVISE.value}))
        excluded: dict[str, list[str]] = {}
        for other in state.tasks:
            if (other.id == task.id or other.status not in {TaskStatus.COMPLETED, TaskStatus.MERGED}
                    or not other.worktree or Path(other.worktree).resolve() != worktree or other.completed_commit not in history):
                continue
            for result in other.action_results:
                if result.status != "succeeded" or result.action not in {TaskAction.EXECUTE.value, TaskAction.REVISE.value, TaskAction.VERIFY.value}:
                    continue
                if result.result_commit in history and result.result_commit not in self.git.merge_base(
                    worktree, result.result_commit, other.completed_commit, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
                ):
                    continue
                for commit in action_commits(result) - owned:
                    if other.id not in excluded.setdefault(commit, []):
                        excluded[commit].append(other.id)
        return excluded

    def record_check(self, state: RunState, task: WorkTask, record: dict[str, object]) -> Path:
        path = self.run_directory(state.id) / "logs" / f"{task.id}-scope.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            payload = {"at": utc_now(), "run_id": state.id, "plan_revision": state.plan_revision,
                       "task_id": task.id, "attempt_id": task.last_attempt_id, **record}
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return path

    def validate(self, task: WorkTask, state: RunState | None = None) -> list[str] | None:
        if not task.expected_paths and not task.forbidden_paths:
            return
        if not task.started_commit:
            raise PipelineError(f"task {task.id} has no original scope baseline; start a new plan")
        record: dict[str, object] = {"event": "task-scope-check", "baseline": task.started_commit,
                                    "expected_paths": list(task.expected_paths), "forbidden_paths": list(task.forbidden_paths)}
        try:
            head = self.git.head(Path(task.worktree), non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            excluded = self.exclusions(state, task, head) if state is not None else {}
            record.update(head=head, excluded_completed_commits=excluded)
            options = {"excluded_commits": list(excluded)} if excluded else {}
            paths = self.git.task_changed_paths(
                Path(task.worktree), task.started_commit, **options, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
            )
        except GitError as exc:
            if state is not None:
                self.record_check(state, task, {**record, "status": "lookup_failed", "error": str(exc)})
            raise
        violations: list[str] = []
        for path in paths:
            if any(scope_path_matches(path, rule) for rule in task.forbidden_paths):
                violations.append(f"forbidden path: {path!r}")
            elif task.expected_paths and not any(scope_path_matches(path, rule) for rule in task.expected_paths):
                violations.append(f"outside expected_paths: {path!r}")
        record.update(status="failed" if violations else "passed", checked_paths=paths, violations=violations)
        scope_log = self.record_check(state, task, record) if state is not None else None
        if violations:
            raise PipelineError(
                f"task {task.id} change scope violation; baseline={task.started_commit}; checked_paths={paths!r}; "
                f"expected_paths={task.expected_paths!r}; forbidden_paths={task.forbidden_paths!r}; "
                f"excluded_completed_commits={list(excluded)!r}; scope_log={scope_log}; "
                + "; ".join(violations)
            )
        return paths

    def has_recorded_implementation(self, task: WorkTask, head: str, *, action_start: int = 0) -> bool:
        if not task.verify_commands:
            return False
        for result in reversed(task.action_results[action_start:]):
            if (result.action not in {TaskAction.EXECUTE.value, TaskAction.REVISE.value} or result.status != "succeeded"
                    or not result.baseline_commit or not result.result_commit or result.baseline_commit == result.result_commit):
                continue
            if result.result_commit == head or result.result_commit in self.git.merge_base(
                Path(task.worktree), result.result_commit, head, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
            ):
                return True
        return False
