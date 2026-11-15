"""MainApplyFlow with explicit phase and persistence dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from ..config import ExecutionConfig, ProjectConfig
from ..errors import PipelineError
from ..execution.operation_lifecycle import RunStepLifecycle
from ..execution.task_workflows import TaskWorkflows
from ..git import GitError, GitWorkspace, LOCAL_GIT_TIMEOUT_SECONDS, run_command
from ..integration import IntegrationInspector, integration_branch_name, main_apply_review
from ..integration.main_preflight import SharedMainApplyPreflight
from ..integration.operations import GitOperationRecorder
from ..integration.publishing import PushConfirmation, PushPreflight
from ..integration.verification_flow import VerificationFlow
from ..integration.workspace_access import WorkspaceAccess
from ..integration.workspace_flows import WorkspaceFlows
from ..models import IntegrationControl, OperationRecord, RunLockStatus, RunState, RunStep, Stage, TaskStatus
from ..persistence.integration_records import MainApplyFlowRecords


@dataclass
class MainApplyFlow:
    records: MainApplyFlowRecords
    inspector: Callable[[], IntegrationInspector]
    tasks: TaskWorkflows
    read_repo: Callable[[], Path]
    verification: VerificationFlow
    workspace: WorkspaceAccess
    steps: RunStepLifecycle
    project_settings: Callable[[], ProjectConfig]
    read_git: Callable[[], GitWorkspace]
    state_root: Callable[[], Path]
    workspaces: WorkspaceFlows
    execution_settings: Callable[[], ExecutionConfig]

    def main_apply_recovery_ready(
        self, state: RunState, operation: OperationRecord, lock: RunLockStatus, remote_configured: bool,
        *, require_stale_locks: bool = True,
    ) -> bool:
        return self.inspector().recovery_ready(state, operation, lock, remote_configured, require_stale_locks=require_stale_locks)


    def main_apply_review(self, state: RunState, integration: IntegrationControl) -> dict[str, object]:
        return main_apply_review(state, integration, repository=self.read_repo(), committed_result_files=self.tasks.committed_result_files)


    def merge_shared_run(self, state: RunState, request_id: str, *, review_id: str = "") -> RunState:
        remote_configured = self.read_git().remote_configured(self.project_settings().remote)
        current_main_head = SharedMainApplyPreflight(
            git=self.read_git(), repo=self.read_repo(), shared_boundary=self.workspace.shared_workspace_boundary,
            invalidate=self.verification.invalidate_integration_verification,
        ).validate(state, remote_configured=remote_configured)
        operation = self.claim_git_operation(state, "merge", request_id, "applying_main", review_id=review_id)
        try:
            with self.steps.step(state, RunStep.MERGE):
                return self.apply_shared_run_to_main(state, current_main_head, operation, remote_configured=remote_configured)
        except Exception as exc:
            self.fail_git_operation(operation, exc)
            raise


    def apply_shared_run_to_main(
        self, state: RunState, current_main_head: str, operation: OperationRecord, *, remote_configured: bool
    ) -> RunState:
        if current_main_head == state.verified_main_head:
            self.read_git().guarded_fast_forward_main(
                state.verified_main_head,
                state.verified_integration_head,
                ignored_untracked_roots=(self.state_root(),),
                preserve_nonoverlapping_changes=True,
                non_interactive=True,
                timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
            )
        if self.read_git().head(self.read_repo(), non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS) != state.verified_integration_head:
            raise PipelineError("main HEAD does not match the verified shared work commit")
        operation.update("main_applied")
        operation.result_commit = state.verified_integration_head
        self.records.save_operation(operation)
        if remote_configured and operation.payload.get("review_id"):
            for task in state.tasks:
                task.status = TaskStatus.MERGED
            state.refresh_task_readiness()
            state.transition(Stage.MERGED, "verified shared work commit applied to local main; remote Push awaits approval")
            self.records.save(state)
            operation.update("main_applied", status="succeeded")
            self.records.save_operation(operation)
            return state
        if remote_configured:
            operation.update("pushing")
            self.records.save_operation(operation)
            self.read_git().push(self.project_settings().remote)
            self.confirm_push(
                state,
                operation,
                scope="main",
                branch=self.read_git().main_branch,
                local_commit=state.verified_integration_head,
            )
        return self.finish_shared_main_apply(state, operation, remote_configured=remote_configured)


    def finish_shared_main_apply(self, state: RunState, operation: OperationRecord, *, remote_configured: bool) -> RunState:
        for task in state.tasks:
            task.status = TaskStatus.MERGED
        state.refresh_task_readiness()
        if remote_configured:
            state.transition(Stage.PUSHED, "verified shared work commit applied and main branch pushed")
        else:
            state.transition(Stage.MERGED, "verified shared work commit applied to local main without a configured remote")
        self.records.save(state)
        operation.update("cleaning_workspaces")
        self.records.save_operation(operation)
        try:
            self.workspaces.cleanup_shared_workspace(state)
        except (GitError, OSError, PipelineError) as exc:
            state.add_event("workspace", f"shared run workspace cleanup deferred: {exc}")
            self.records.save(state)
            operation.update("cleanup_deferred", status="succeeded", error=str(exc), error_code="cleanup_deferred")
        else:
            operation.update("cleanup_completed", status="succeeded")
        self.records.save_operation(operation)
        return state


    def merge_isolated(self, state: RunState, operation: OperationRecord) -> RunState:
        try:
            self.read_git().guarded_fast_forward_main(
                state.verified_main_head,
                state.verified_integration_head,
                ignored_untracked_roots=(self.state_root(),),
                non_interactive=True,
                timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
            )
        except GitError as exc:
            state.fail_step(RunStep.MERGE, f"verified integration commit apply failed: {exc}")
            self.records.save(state)
            raise PipelineError(str(exc)) from exc
        if self.read_git().head(self.read_repo(), non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS) != state.verified_integration_head:
            raise PipelineError("main HEAD does not match the verified integration commit")
        return self.finish_isolated_main_apply(state, operation)


    def finish_isolated_main_apply(self, state: RunState, operation: OperationRecord) -> RunState:
        operation.update("main_applied")
        self.records.save_operation(operation)
        for task in state.tasks:
            task.status = TaskStatus.MERGED
        state.refresh_task_readiness()
        state.transition(Stage.MERGED, "verified integration commit applied to main")
        self.records.save(state)
        operation.update("main_applied", status="succeeded")
        self.records.save_operation(operation)
        integration_branch = integration_branch_name(state.id)
        if self.read_git().branch_exists(integration_branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS):
            try:
                self.read_git().delete_branch(integration_branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            except GitError as exc:
                state.add_event("workspace", f"integration branch cleanup failed: {exc}")
                self.records.save(state)
        return state


    def push_main(self, state: RunState, operation: OperationRecord) -> RunState:
        local_commit = self.read_git().head(self.read_repo(), non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        self.read_git().push(self.project_settings().remote)
        self.confirm_push(
            state,
            operation,
            scope="main",
            branch=self.read_git().main_branch,
            local_commit=local_commit,
        )
        state.transition(Stage.PUSHED, "main branch pushed")
        self.records.save(state)
        operation.update("pushed", status="succeeded")
        self.records.save_operation(operation)
        return state


    def push_preflight(self) -> PushPreflight:
        return PushPreflight(
            git=self.read_git(), shared_boundary=self.workspace.shared_workspace_boundary, ensure_clean=self.workspace.ensure_worktree_clean,
            invalidate=self.verification.invalidate_integration_verification, ensure_main_ready=self.workspaces.ensure_main_worktree_ready,
        )


    def confirm_push(
        self,
        state: RunState,
        operation: OperationRecord,
        *,
        scope: str,
        branch: str,
        local_commit: str,
    ) -> None:
        return PushConfirmation(
            git=self.read_git(), save_operation=self.records.save_operation, remote=lambda: self.project_settings().remote,
        ).confirm(state, operation, scope=scope, branch=branch, local_commit=local_commit)


    def git_operation_recorder(self) -> GitOperationRecorder:
        return GitOperationRecorder(self.records.load_operation, self.records.claim_operation, self.records.save_operation)


    def completed_operation_replay(self, state: RunState, action: str, request_id: str, *, review_id: str = "") -> bool:
        return self.git_operation_recorder().completed_replay(state, action, request_id, review_id=review_id)


    def claim_git_operation(self, state: RunState, action: str, request_id: str, phase: str, *, review_id: str = "") -> OperationRecord:
        return self.git_operation_recorder().claim(state, action, request_id, phase, review_id=review_id)


    def fail_git_operation(self, operation: OperationRecord, error: Exception) -> None:
        return self.git_operation_recorder().fail(operation, error)


    def deploy_command(self, state: RunState) -> RunState:
        command = self.execution_settings().deploy_command
        result = run_command(command, self.read_repo(), check=False)
        log_dir = self.records.run_dir(state.id) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "deploy.log").write_text(result.stdout, encoding="utf-8")
        if result.returncode != 0:
            state.fail_step(RunStep.DEPLOY, "deployment failed")
            self.records.save(state)
            raise PipelineError(f"deployment command failed: {' '.join(command)}")
        state.transition(Stage.DEPLOYED, "deployment completed")
        self.records.save(state)
        return state
