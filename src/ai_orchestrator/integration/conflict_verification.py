"""Conflict follow-up receipts outside the caller's apply lock."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..git import GitError, GitWorkspace, LOCAL_GIT_TIMEOUT_SECONDS
from ..models import OperationRecord, RunState


@dataclass(frozen=True, slots=True)
class ConflictVerificationRecords:
    load_run: Callable[[str], RunState]
    save_state: Callable[[RunState], None]
    save_operation: Callable[[OperationRecord], None]
    run_lock: Callable[[str, str], AbstractContextManager[None]]


@dataclass(frozen=True, slots=True)
class ConflictResolutionVerification:
    git: GitWorkspace
    records: ConflictVerificationRecords
    verify: Callable[[str], RunState]

    def finish(
        self, state: RunState, *, run_id: str, conflict_id: str,
        operation: OperationRecord, candidate_worktree: Path | None,
    ) -> RunState:
        if candidate_worktree is not None:
            try:
                self.git.discard_detached_worktree(
                    candidate_worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
                )
                with self.records.run_lock(run_id, "conflict-resolution-cleanup"):
                    state = self.records.load_run(run_id)
                    if state.integration_conflict and state.integration_conflict.candidate:
                        state.integration_conflict.candidate.worktree = ""
                        self.records.save_state(state)
            except GitError:
                pass
        known_verification_attempts = {attempt.id for attempt in state.verification_attempts}
        try:
            verified = self.verify(run_id)
        except Exception as exc:
            with self.records.run_lock(run_id, "conflict-resolution-verification-result"):
                state = self.records.load_run(run_id)
                if state.integration_conflict:
                    state.integration_conflict.error = f"해결안 적용 완료 · 전체 검증 실패: {exc}"
                    for attempt in state.verification_attempts:
                        if attempt.id not in known_verification_attempts:
                            state.link_recovery_verification(state.integration_conflict.id, attempt.id)
                self.records.save_state(state)
            operation.update("verification_failed", status="failed", error=str(exc), error_code="verification_failed")
            self.records.save_operation(operation)
            raise
        for attempt in verified.verification_attempts:
            if attempt.id not in known_verification_attempts:
                verified.link_recovery_verification(conflict_id, attempt.id)
        self.records.save_state(verified)
        operation.result_commit = verified.verified_integration_head or operation.result_commit
        operation.update("succeeded", status="succeeded")
        self.records.save_operation(operation)
        return verified
