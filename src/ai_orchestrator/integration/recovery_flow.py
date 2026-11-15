"""RecoveryFlow with explicit feature and persistence dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, ContextManager
from ..git import GitWorkspace
from ..integration import RecoveryRecords, RecoveryWorkflow, uses_shared_workspace
from ..integration.workspace_access import WorkspaceAccess
from ..models import OperationRecord, RunState
from ..persistence.execution_records import RecoveryFlowRecords
from ..planning.conversation import task_plan_draft
from ..planning.lifecycle import PlanningLifecycle
from ..planning.policy_scope import PlanningPolicyScope


@dataclass
class RecoveryFlow:
    records: RecoveryFlowRecords
    workspace: WorkspaceAccess
    read_git: Callable[[], GitWorkspace]
    read_repo: Callable[[], Path]
    planning_lifecycle: PlanningLifecycle
    planning_policy: PlanningPolicyScope

    def recovery_workflow(self) -> RecoveryWorkflow:
        return RecoveryWorkflow(
            git=self.read_git(), repo=self.read_repo(),
            records=RecoveryRecords(
                load_run=self.records.load,
                list_runs=self.records.list_runs, claim=self.records.claim_operation, load=self.records.load_operation,
                save=self.records.save_operation, load_result=self.records.load_operation_result,
                save_result=self.records.save_operation_result, inspect_lock=self.records.inspect_lock,
                latest=self.records.latest_operation,
            ),
            shared_boundary=self.workspace.shared_workspace_boundary, ensure_clean=self.workspace.ensure_worktree_clean,
            task_draft=task_plan_draft, uses_shared_workspace=uses_shared_workspace,
        )


    def recovery_plan(self, state: RunState, *, progress_callback: Callable[[str], None] | None = None) -> dict[str, object]:
        return self.recovery_workflow().plan(state, progress_callback=progress_callback)


    def integrate_recovery_commits(self, worktree: Path, baseline: str, commits: list[str]) -> str:
        return self.read_git().recover_commits(
            worktree, baseline, commits, ignored_untracked_roots=self.workspace.worktree_managed_state_roots(worktree),
        )


    def replan_recovery_tasks(self, state: RunState) -> RunState:
        with self.planning_policy.scope(state, purpose="recovery_planning"):
            return self.planning_lifecycle.apply_pending(state)


    def claim_recovery_operation(
        self,
        state: RunState,
        action: str,
        request_id: str,
        payload: dict[str, object],
        phase: str,
        *,
        resume_request_id: str = "",
    ) -> tuple[OperationRecord, bool]:
        return self.recovery_workflow().claim(state, action, request_id, payload, phase, resume_request_id=resume_request_id)


    def recovery_preview_input(self, state: RunState) -> dict[str, object]:
        return self.recovery_workflow().preview_input(state)


    def replayed_recovery_result(self, operation: OperationRecord) -> dict[str, object] | None:
        return self.recovery_workflow().replay(operation)


    def validate_recovery_replan_resume(
        self, state: RunState, operation: OperationRecord, fingerprint: str, source_ids: list[str]
    ) -> str:
        return self.recovery_workflow().resume_replanning(state, operation, fingerprint, source_ids)


    def fail_recovery_operation(self, operation: OperationRecord, error: Exception) -> None:
        return self.recovery_workflow().fail(operation, error)
