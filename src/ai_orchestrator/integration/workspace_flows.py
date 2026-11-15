"""WorkspaceFlows with explicit phase and persistence dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from ..codex_sdk import CodexSdkManager
from ..git import GitWorkspace, GitWorktree, LOCAL_GIT_TIMEOUT_SECONDS
from ..integration import WorkspaceInspector, WorkspaceLifecycle
from ..integration.workspace_access import WorkspaceAccess
from ..models import ArchiveCleanupTarget, RunState, WorkTask, WorkspaceStatus
from ..persistence.integration_records import WorkspaceFlowsRecords


@dataclass
class WorkspaceFlows:
    records: WorkspaceFlowsRecords
    workspace: WorkspaceAccess
    read_git: Callable[[], GitWorkspace]
    read_repo: Callable[[], Path]
    state_root: Callable[[], Path]
    sdk: Callable[[], CodexSdkManager | None]

    def lifecycle(self) -> WorkspaceLifecycle:
        layout = self.workspace.layout()
        return WorkspaceLifecycle(self.read_git(), layout, WorkspaceInspector(self.read_git(), layout), self.read_repo(), self.state_root())


    def workspace_status(
        self,
        state: RunState,
        task: WorkTask,
        registered: dict[Path, GitWorktree],
        *,
        require_unlocked: bool = True,
        non_interactive: bool = False,
        deadline: float | None = None,
    ) -> WorkspaceStatus:
        return self.workspace.inspector().status(state, task, registered, require_unlocked=require_unlocked, non_interactive=non_interactive,
            deadline=deadline, inspect_lock=lambda: self.records.inspect_lock(state.id))


    def cleanup_shared_workspace(self, state: RunState) -> None:
        def on_deferred(error: Exception) -> None:
            state.add_event("workspace", f"shared run workspace cleanup deferred: {error}")
            self.records.save(state)

        def discard_idle_clients() -> None:
            if self.sdk() is not None:
                self.sdk().discard_idle_clients()

        self.lifecycle().cleanup_shared(state, discard_idle_clients=discard_idle_clients, on_deferred=on_deferred)
        state.add_event("workspace", "shared run worktree and local branch cleaned")
        self.records.save(state)


    def ensure_main_worktree_ready(self) -> None:
        self.read_git().ensure_clean(ignored_untracked_roots=(self.state_root(),), non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        self.read_git().ensure_main_branch(non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)


    def result_workspace(self, state: RunState) -> tuple[Path, str, str]:
        return self.workspace.inspector().result_workspace(state)


    def run_deletion_targets(
        self,
        state: RunState,
        registered: dict[Path, GitWorktree],
        *,
        additional_expected_worktrees: tuple[Path, ...] = (),
        remaining_timeout: Callable[[], float] | None = None,
    ) -> list[tuple[str, Path, WorkTask]]:
        return self.lifecycle().deletion_targets(state, registered, additional_expected_worktrees=additional_expected_worktrees,
            remaining_timeout=remaining_timeout)


    def run_deletion_verification_worktree(
        self,
        state: RunState,
        registered: dict[Path, GitWorktree],
        *,
        remaining_timeout: Callable[[], float] | None = None,
    ) -> Path | None:
        return self.lifecycle().deletion_verification_path(state, registered, remaining_timeout=remaining_timeout)


    def run_deletion_conflict_worktree(self, state: RunState, registered: dict[Path, GitWorktree]) -> Path | None:
        return self.lifecycle().deletion_conflict_path(state, registered)


    def cleanup_archive_target(self, state: RunState, target: ArchiveCleanupTarget) -> None:
        return self.lifecycle().cleanup_archive_target(state, target)


    def archive_cleanup_targets(
        self, state: RunState, registered: dict[Path, GitWorktree]
    ) -> list[ArchiveCleanupTarget]:
        return self.lifecycle().archive_cleanup_targets(state, registered)
