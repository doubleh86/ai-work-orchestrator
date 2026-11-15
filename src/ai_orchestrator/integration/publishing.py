"""Push preflight and remote evidence under caller-owned approval."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..errors import PipelineError
from ..git import GitWorkspace, LOCAL_GIT_TIMEOUT_SECONDS
from ..models import OperationRecord, PushReceipt, RunState, Stage, TaskStatus


@dataclass(frozen=True, slots=True)
class PushPreflight:
    git: GitWorkspace
    shared_boundary: Callable[[RunState], tuple[str, Path]]
    ensure_clean: Callable[[Path], None]
    invalidate: Callable[[RunState, str], None]
    ensure_main_ready: Callable[[], None]

    def shared(self, state: RunState, run_id: str) -> tuple[str, str]:
        if state.stage != Stage.VERIFIED:
            raise PipelineError(f"run {run_id} is at '{state.stage.value}', expected {Stage.VERIFIED.value}")
        self.git.ensure_main_branch(non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        branch, worktree = self.shared_boundary(state)
        self.ensure_clean(worktree)
        branch_head = self.git.branch_head(branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        if branch_head != state.verified_integration_head:
            self.invalidate(state, "shared work branch changed after verification")
            raise PipelineError("shared work branch changed after verification; run verification again")
        return branch, branch_head

    def isolated(self, state: RunState, run_id: str) -> None:
        if state.stage not in {Stage.MERGED, Stage.VERIFIED}:
            raise PipelineError(f"run {run_id} is at '{state.stage.value}', expected one of: {Stage.MERGED.value}, {Stage.VERIFIED.value}")
        if not all(task.status == TaskStatus.MERGED for task in state.tasks):
            raise PipelineError("push requires task branches to be merged into main")
        self.ensure_main_ready()


@dataclass(frozen=True, slots=True)
class PushConfirmation:
    git: GitWorkspace
    save_operation: Callable[[OperationRecord], None]
    remote: Callable[[], str]

    def confirm(
        self, state: RunState, operation: OperationRecord, *, scope: str, branch: str, local_commit: str,
    ) -> None:
        operation.update("confirming_remote")
        self.save_operation(operation)
        remote = self.remote()
        remote_commit = self.git.remote_branch_head(remote, branch)
        expected_commit = local_commit.lower()
        if remote_commit != expected_commit:
            raise PipelineError(
                f"remote branch commit does not match pushed commit: {remote}/{branch} "
                f"(expected {local_commit}, found {remote_commit})"
            )
        receipt = PushReceipt(
            scope=scope,
            remote=remote,
            branch=branch,
            local_commit=expected_commit,
            remote_commit=remote_commit,
            operation_request_id=operation.request_id,
        )
        if not any(
            existing.scope == receipt.scope
            and existing.remote == receipt.remote
            and existing.branch == receipt.branch
            and existing.local_commit == receipt.local_commit
            and existing.remote_commit == receipt.remote_commit
            for existing in state.push_receipts
        ):
            state.push_receipts.append(receipt)
        operation.result_commit = remote_commit
