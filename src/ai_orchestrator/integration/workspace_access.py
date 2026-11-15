"""WorkspaceAccess with explicit feature and persistence dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, ContextManager
from ..config import ProjectConfig
from ..git import GitWorkspace, LOCAL_GIT_TIMEOUT_SECONDS
from ..integration import IntegrationInspector, WorkspaceInspector, WorkspaceLayout
from ..models import OperationRecord, RunState
from ..persistence.execution_records import WorkspaceAccessRecords


@dataclass
class WorkspaceAccess:
    records: WorkspaceAccessRecords
    integration_inspector: Callable[[], IntegrationInspector]
    project_settings: Callable[[], ProjectConfig]
    read_git: Callable[[], GitWorkspace]

    def shared_main_push_recovery_source(self, state: RunState) -> OperationRecord | None:
        return self.integration_inspector().main_push_recovery_source(state)


    def layout(self) -> WorkspaceLayout:
        return WorkspaceLayout(self.project_settings())


    def inspector(self) -> WorkspaceInspector:
        return WorkspaceInspector(self.read_git(), self.layout())


    def worktree_managed_state_roots(self, worktree: Path) -> tuple[Path, ...]:
        return self.layout().managed_state_roots(worktree)


    def ensure_worktree_clean(self, worktree: Path, *, timeout_seconds: float = LOCAL_GIT_TIMEOUT_SECONDS) -> None:
        return self.inspector().ensure_clean(worktree, timeout_seconds=timeout_seconds)


    def worktree_is_clean(self, worktree: Path, *, non_interactive: bool = False, timeout_seconds: float | None = None) -> bool:
        return self.inspector().is_clean(worktree, non_interactive=non_interactive, timeout_seconds=timeout_seconds)


    def ensure_execution_workspace_ready(self) -> None:
        self.read_git().ensure_repository(non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        self.read_git().ensure_main_branch(non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)


    def workspace_state(self, state: RunState | str) -> RunState:
        return state if isinstance(state, RunState) else self.records.load(state)


    def run_worktree_root(self, state: RunState | str) -> Path:
        return self.layout().run_root(self.workspace_state(state))


    def shared_workspace_boundary(self, state: RunState) -> tuple[str, Path]:
        return self.layout().shared_boundary(state)


    def verification_worktree_path(self, state: RunState | str) -> Path:
        return self.layout().verification_path(self.workspace_state(state))
