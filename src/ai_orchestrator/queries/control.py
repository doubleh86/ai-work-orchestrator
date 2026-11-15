"""Read run controls with lock snapshots and existing Git evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..git import GitError
from ..integration import IntegrationInspector, uses_shared_workspace
from ..models import ExecutionControlRecord, IntegrationControl, RunExecutionAction, RunExecutionControl, RunExecutionSituation
from ..models import RunLockState, RunLockStatus, RunState
from ..run_queries import BranchSnapshot, run_execution_control
from ..execution import deferred_execution_task_ids, waiting_for_user_checks


@dataclass(frozen=True, slots=True)
class RunControlQueries:
    inspect_lock: Callable[[str], RunLockStatus]
    load_control: Callable[[str], ExecutionControlRecord | None]
    read_branch: Callable[[], str]
    inspector: Callable[[], IntegrationInspector]

    def branch_snapshot(self) -> BranchSnapshot:
        try:
            return BranchSnapshot(branch=self.read_branch())
        except (GitError, OSError) as exc:
            return BranchSnapshot(error=str(exc))

    def integration_control(self, state: RunState, lock: RunLockStatus) -> IntegrationControl:
        return self.inspector().control(state, lock)

    def execution_control(
        self, state: RunState, lock: RunLockStatus, execution_record: ExecutionControlRecord | None = None
    ) -> RunExecutionControl:
        return run_execution_control(
            state, lock, execution_record,
            waiting_for_user_checks=lambda: waiting_for_user_checks(state),
            read_branch=self.branch_snapshot,
            deferred_task_ids=lambda: deferred_execution_task_ids(state),
            has_main_push_recovery=lambda: self.inspector().main_push_recovery_source(state) is not None,
            uses_shared_workspace=lambda: uses_shared_workspace(state),
        )

    def summary_control(self, state: RunState) -> RunExecutionControl:
        try:
            lock_before = self.inspect_lock(state.id)
            execution_record = self.load_control(state.id)
            lock_after = self.inspect_lock(state.id)
        except (OSError, ValueError):
            return RunExecutionControl(
                situation=RunExecutionSituation.STATUS_UNKNOWN,
                action=RunExecutionAction.NONE,
                reason="작업 그룹 상태를 확인하지 못했습니다.",
                lock_state=RunLockState.UNVERIFIABLE,
            )
        if lock_before != lock_after:
            return RunExecutionControl(
                situation=RunExecutionSituation.STATUS_UNKNOWN,
                action=RunExecutionAction.NONE,
                reason="목록을 확인하는 동안 실행 잠금이 변경되었습니다.",
                lock_state=lock_after.state,
                operation=lock_after.operation,
            )
        return self.execution_control(state, lock_after, execution_record)
