"""Task workspaces, execution files and preserved dependency baselines."""

from __future__ import annotations

from ..models import Stage

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..errors import PipelineError
from ..git_contracts import GitError, LOCAL_GIT_TIMEOUT_SECONDS
from ..models import RunState, TaskAction, TaskStatus, WorkTask, WorkspaceLocation

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..git import GitWorkspace


@dataclass(frozen=True, slots=True)
class TaskWorkspacePreparation:
    git: GitWorkspace
    shared_workspace: Callable[[RunState], bool]
    find_task: Callable[[RunState, str], WorkTask]

    def merge_dependencies(self, state: RunState, task: WorkTask) -> None:
        for dependency_id in task.execution_dependencies:
            dependency = self.find_task(state, dependency_id)
            if dependency.status != TaskStatus.COMPLETED:
                raise PipelineError(f"task {task.id} dependency is not completed: {dependency_id}")
        if self.shared_workspace(state):
            return
        worktree = Path(task.worktree)
        for dependency_id in task.execution_dependencies:
            dependency = self.find_task(state, dependency_id)
            if self.git.contains_branch(worktree, dependency.branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS):
                continue
            try:
                self.git.merge_into(
                    worktree,
                    dependency.branch,
                    f"merge dependency {dependency.id} into {task.id}",
                    non_interactive=True,
                    timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
                )
            except GitError as exc:
                self.git.abort_merge(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
                raise PipelineError(f"dependency merge failed for {task.id} at {dependency.id}: {exc}") from exc
            state.add_event("dependency", f"{dependency.id} merged into {task.id} worktree")

    def record_start_commit(self, task: WorkTask) -> None:
        if task.started_commit:
            worktree = Path(task.worktree)
            current_head = self.git.head(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            execution_results = [
                result for result in task.action_results
                if result.action in {TaskAction.EXECUTE.value, TaskAction.REVISE.value} and result.baseline_commit
            ]
            if execution_results and task.started_commit not in self.git.merge_base(
                worktree, task.started_commit, current_head, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
            ):
                raise PipelineError(f"task {task.id} scope baseline is not an ancestor of HEAD: {task.started_commit}")
            task_changed_head = False
            for result in execution_results:
                if not result.result_commit:
                    # An interrupted attempt may have committed before its result was recorded.
                    task_changed_head = current_head != result.baseline_commit
                elif result.result_commit not in {result.baseline_commit, task.started_commit}:
                    result_after_start = task.started_commit in self.git.merge_base(
                        worktree, task.started_commit, result.result_commit,
                        non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
                    )
                    result_in_head = result.result_commit in self.git.merge_base(
                        worktree, result.result_commit, current_head,
                        non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
                    )
                    task_changed_head = result_after_start and result_in_head
                if task_changed_head:
                    break
            if not task_changed_head:
                task.started_commit = current_head
                task.completed_commit = ""
            return
        if (task.expected_paths or task.forbidden_paths) and (
            task.attempt_count or task.failed_action or task.status == TaskStatus.WAITING
        ):
            raise PipelineError(f"task {task.id} has no original scope baseline; start a new plan")
        task.started_commit = self.git.head(Path(task.worktree), non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        task.completed_commit = ""


@dataclass(frozen=True, slots=True)
class TaskExecutionRecords:
    run_directory: Callable[[str], Path]
    save_state: Callable[[RunState], None]


@dataclass(frozen=True, slots=True)
class TaskExecutionPreparation:
    repo: Path
    git: GitWorkspace
    records: TaskExecutionRecords
    workspace_location: Callable[[RunState], WorkspaceLocation]
    uses_shared_workspace: Callable[[RunState], bool]
    shared_branch_name: Callable[[str], str]
    shared_worktree_path: Callable[[RunState], Path]
    shared_boundary: Callable[[RunState], tuple[str, Path]]
    managed_roots: Callable[[Path], tuple[Path, ...]]
    run_worktree_root: Callable[[RunState], Path]
    prompt: Callable[[RunState, WorkTask, str], str]

    def prepare(self, state: RunState, *, task_ids: set[str] | None = None, persist: bool = True) -> None:
        prompt_dir = self.records.run_directory(state.id) / "prompts"
        log_dir = self.records.run_directory(state.id) / "logs"
        prompt_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)
        spec_path = state.spec_snapshot_path or state.spec_path
        if not spec_path or not Path(spec_path).is_file():
            raise PipelineError(f"task prompt source is missing or not a file: {spec_path or '<empty>'}")
        spec = Path(spec_path).read_text(encoding="utf-8")
        location = self.workspace_location(state)
        if state.workspace_location is None:
            state.workspace_location = location
            state.add_event("workspace", f"workspace root fixed from {location.source.value}: {location.root}")
        self.git.ensure_managed_workspace_excluded(
            Path(location.root), non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
        )
        if self.uses_shared_workspace(state):
            branch = self.shared_branch_name(state.id)
            worktree = self.shared_worktree_path(state)
            if state.execution_branch and state.execution_branch != branch:
                raise PipelineError(f"run branch does not match its deterministic shared boundary: {state.execution_branch} != {branch}")
            if state.execution_worktree and Path(state.execution_worktree).resolve() != worktree.resolve():
                raise PipelineError(f"run worktree does not match its deterministic shared boundary: {state.execution_worktree} != {worktree}")
            if state.execution_branch or state.execution_worktree:
                branch, worktree = self.shared_boundary(state)
                registered = {
                    item.path.resolve(): item
                    for item in self.git.list_worktrees(non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
                }
                entry = registered.get(worktree.resolve())
                if entry is None or entry.branch != branch or not worktree.is_dir():
                    raise PipelineError("shared run workspace is not registered on its expected branch")
            else:
                start_point = state.base_commit or self.git.head(
                    self.repo, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
                )
                self.git.prepare_worktree(
                    worktree,
                    branch,
                    start_point,
                    ignored_untracked_roots=self.managed_roots(worktree),
                    non_interactive=True,
                    timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
                )
                state.add_event("workspace", "shared run worktree prepared")
            state.execution_branch = branch
            state.execution_worktree = str(worktree)
        else:
            worktree_root = self.run_worktree_root(state)
        selected_tasks = [task for task in state.tasks if task_ids is None or task.id in task_ids]
        for task in selected_tasks:
            if self.uses_shared_workspace(state):
                branch = state.execution_branch
                worktree = Path(state.execution_worktree)
            else:
                branch = f"ai/{state.id}/{task.id}"
                worktree = worktree_root / task.id
            if task.branch and task.branch != branch:
                raise PipelineError(f"task {task.id} branch does not match prepared branch: {task.branch} != {branch}")
            if task.worktree and Path(task.worktree).resolve() != worktree.resolve():
                raise PipelineError(f"task {task.id} worktree is outside its prepared path: {task.worktree} != {worktree}")
            if not self.uses_shared_workspace(state) and not (task.branch and task.worktree):
                start_point = state.base_commit or self.git.head(self.repo, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
                self.git.prepare_worktree(
                    worktree,
                    branch,
                    start_point,
                    ignored_untracked_roots=self.managed_roots(worktree),
                    non_interactive=True,
                    timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
                )
            prompt_path = prompt_dir / f"{task.id}.md"
            prompt_path.write_text(self.prompt(state, task, spec), encoding="utf-8")
            task.branch = branch
            task.worktree = str(worktree)
            task.prompt_path = str(prompt_path)
            task.log_path = str(log_dir / f"{task.id}.log")
        if persist:
            self.records.save_state(state)


def advance_completed_tasks(state: RunState) -> None:
    if all(task.status == TaskStatus.COMPLETED for task in state.tasks) and not state.integration_user_checks_pending():
        state.transition(Stage.READY_TO_MERGE, "all agent tasks completed")
