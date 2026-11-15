from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import ProjectConfig, resolve_workspace_location
from ..errors import PipelineError
from ..models import (
    ExecutionWorkspaceMode,
    RunState,
    RunStep,
    Stage,
    TaskStatus,
    WorkTask,
    WorkspaceLocation,
    WorkspaceLocationSource,
)


def uses_shared_workspace(state: RunState) -> bool:
    return state.workspace_mode == ExecutionWorkspaceMode.SHARED


def shared_run_branch_name(run_id: str) -> str:
    return f"ai/{run_id}"


def integration_branch_name(run_id: str) -> str:
    return f"ai-integration/{run_id}"


def workspace_is_integrated(state: RunState, task: WorkTask) -> bool:
    if task.status != TaskStatus.MERGED:
        return False
    if state.stage in {Stage.MERGED, Stage.VERIFIED, Stage.PUSHED, Stage.DEPLOYED}:
        return True
    return state.stage == Stage.FAILED and state.failed_step in {RunStep.VERIFY, RunStep.PUSH, RunStep.DEPLOY}


@dataclass(frozen=True, slots=True)
class WorkspaceLayout:
    project: ProjectConfig

    def managed_state_roots(self, worktree: Path) -> tuple[Path, ...]:
        configured = Path(self.project.state_dir).expanduser()
        if configured.is_absolute():
            return ()
        selected_worktree = worktree.expanduser().resolve()
        state_root = (selected_worktree / configured).resolve()
        if state_root == selected_worktree or not state_root.is_relative_to(selected_worktree):
            return ()
        return (state_root,)

    def location(self, state: RunState) -> WorkspaceLocation:
        if state.workspace_location is not None:
            root = Path(state.workspace_location.root).expanduser()
            if not root.is_absolute():
                raise PipelineError(f"workspace_location_conflict: workspace root is not absolute: {root}")
            return WorkspaceLocation(
                root=str(root.resolve()),
                source=state.workspace_location.source,
                layout_version=state.workspace_location.layout_version,
                notice_code=state.workspace_location.notice_code,
            )

        recorded_roots: set[Path] = set()

        def record(worktree_value: str, expected_leaf: str) -> None:
            if not worktree_value:
                return
            worktree = Path(worktree_value).expanduser().resolve()
            if worktree.name != expected_leaf or worktree.parent.name != state.id:
                raise PipelineError(f"workspace_location_conflict: recorded worktree is outside the run layout: {worktree}")
            recorded_roots.add(worktree.parent.parent)

        if uses_shared_workspace(state):
            record(state.execution_worktree, "work")
            for task in state.tasks:
                record(task.worktree, "work")
        else:
            for task in state.tasks:
                record(task.worktree, task.id)
        if len(recorded_roots) > 1:
            roots = ", ".join(str(root) for root in sorted(recorded_roots, key=str))
            raise PipelineError(f"workspace_location_conflict: recorded worktrees use different roots: {roots}")
        if recorded_roots:
            return WorkspaceLocation(root=str(next(iter(recorded_roots))), source=WorkspaceLocationSource.LEGACY_RECORD)
        return resolve_workspace_location(self.project)

    def root(self, state: RunState) -> Path:
        return Path(self.location(state).root).resolve()

    def run_root(self, state: RunState) -> Path:
        worktree_root = self.root(state)
        run_root = (worktree_root / state.id).resolve()
        if run_root.parent != worktree_root:
            raise PipelineError(f"invalid run id: {state.id}")
        return run_root

    def shared_path(self, state: RunState) -> Path:
        return self.run_root(state) / "work"

    def shared_boundary(self, state: RunState) -> tuple[str, Path]:
        expected_branch = shared_run_branch_name(state.id)
        expected_worktree = self.shared_path(state).resolve()
        branch = state.execution_branch or expected_branch
        worktree = Path(state.execution_worktree).expanduser().resolve() if state.execution_worktree else expected_worktree
        if branch != expected_branch or worktree != expected_worktree:
            raise PipelineError("shared run workspace is outside its deterministic boundary")
        mismatched = [
            task.id
            for task in state.tasks
            if (task.branch and task.branch != branch) or (task.worktree and Path(task.worktree).expanduser().resolve() != worktree)
        ]
        if mismatched:
            raise PipelineError("tasks do not share the run workspace boundary: " + ", ".join(mismatched))
        return branch, worktree

    def verification_path(self, state: RunState) -> Path:
        return self.run_root(state) / ".verification"
