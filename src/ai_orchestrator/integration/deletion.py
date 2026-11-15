"""Remove owned run workspaces using the caller's shared time budget."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from ..errors import PipelineError
from ..git import GitError, GitWorkspace, GitWorktree
from ..models import RunDeletion, RunState, WorkTask


class DeletionVerificationWorkspace(Protocol):
    def __call__(
        self,
        state: RunState,
        registered: dict[Path, GitWorktree],
        *,
        remaining_timeout: Callable[[], float] | None = None,
    ) -> Path | None:
        ...


class DeletionTargets(Protocol):
    def __call__(
        self,
        state: RunState,
        registered: dict[Path, GitWorktree],
        *,
        additional_expected_worktrees: tuple[Path, ...] = (),
        remaining_timeout: Callable[[], float] | None = None,
    ) -> list[tuple[str, Path, WorkTask]]:
        ...


RUN_DELETION_TIMEOUT_SECONDS = 60


@dataclass(frozen=True, slots=True)
class RunWorkspaceDeletion:
    git: GitWorkspace
    verification_worktree: DeletionVerificationWorkspace
    conflict_worktree: Callable[[RunState, dict[Path, GitWorktree]], Path | None]
    run_root: Callable[[RunState], Path]
    targets: DeletionTargets
    integration_branch: Callable[[str], str]
    save_state: Callable[[RunState], None]

    def remove(self, state: RunState, *, remaining_timeout: Callable[[], float]) -> RunDeletion:
        registered = {worktree.path: worktree for worktree in self.git.list_worktrees(non_interactive=True, timeout_seconds=remaining_timeout())}
        verification_worktree = self.verification_worktree(state, registered, remaining_timeout=remaining_timeout)
        conflict_worktree = self.conflict_worktree(state, registered)
        conflict_root = (self.run_root(state) / ".conflict-resolution").resolve()
        additional_worktrees = tuple(
            path for path in (verification_worktree, conflict_worktree, conflict_root if conflict_root.exists() else None) if path is not None
        )
        targets = self.targets(
            state, registered, additional_expected_worktrees=additional_worktrees, remaining_timeout=remaining_timeout
        )
        integration_branch = self.integration_branch(state.id)
        integration_owners = [item.path for item in registered.values() if item.branch == integration_branch]
        if integration_owners:
            raise PipelineError(f"작업 그룹을 삭제할 수 없습니다. 통합 branch가 다른 worktree에서 사용 중입니다: {integration_owners[0]}")
        worktree_count = sum(1 for _, worktree, _ in targets if worktree in registered or worktree.exists())
        if verification_worktree is not None and (
            verification_worktree in registered or verification_worktree.exists()
        ):
            worktree_count += 1
        if conflict_worktree is not None and (conflict_worktree in registered or conflict_worktree.exists()):
            worktree_count += 1
        branch_count = sum(
            1 for branch, _, _ in targets if self.git.branch_exists(branch, non_interactive=True, timeout_seconds=remaining_timeout())
        )
        if self.git.branch_exists(integration_branch, non_interactive=True, timeout_seconds=remaining_timeout()):
            branch_count += 1
        try:
            if verification_worktree is not None:
                if verification_worktree in registered:
                    self.git.remove_worktree(verification_worktree, force=True, non_interactive=True, timeout_seconds=remaining_timeout())
                elif (verification_worktree / ".git").exists():
                    self.git.remove_orphaned_worktree_residue(
                        verification_worktree, non_interactive=True, timeout_seconds=remaining_timeout()
                    )
                else:
                    self.git.remove_worktree_residue(verification_worktree)
            if conflict_worktree is not None:
                if conflict_worktree in registered:
                    self.git.remove_worktree(conflict_worktree, force=True, non_interactive=True, timeout_seconds=remaining_timeout())
                elif conflict_worktree.exists():
                    self.git.remove_worktree_residue(conflict_worktree)
            if conflict_root.is_dir() and not any(conflict_root.iterdir()):
                conflict_root.rmdir()
            for branch, worktree, _ in targets:
                if worktree in registered:
                    self.git.remove_worktree(worktree, force=True, non_interactive=True, timeout_seconds=remaining_timeout())
                elif (worktree / ".git").exists():
                    self.git.remove_orphaned_worktree_residue(
                        worktree, non_interactive=True, timeout_seconds=remaining_timeout()
                    )
                elif worktree.exists():
                    self.git.remove_worktree_residue(worktree)
                if self.git.branch_exists(branch, non_interactive=True, timeout_seconds=remaining_timeout()):
                    self.git.delete_branch(branch, force=True, non_interactive=True, timeout_seconds=remaining_timeout())
            if self.git.branch_exists(integration_branch, non_interactive=True, timeout_seconds=remaining_timeout()):
                self.git.delete_branch(integration_branch, force=True, non_interactive=True, timeout_seconds=remaining_timeout())
            group_root = self.run_root(state)
            if group_root.is_dir():
                group_root.rmdir()
        except (GitError, OSError) as exc:
            state.add_event("workspace", f"run deletion failed: {exc}")
            self.save_state(state)
            raise PipelineError(f"작업 그룹 삭제에 실패했습니다: {exc}") from exc
        result = RunDeletion(
            run_id=state.id, summary=state.summary, task_count=len(state.tasks), worktree_count=worktree_count, branch_count=branch_count
        )
        return result
