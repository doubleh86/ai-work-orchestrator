"""LifecycleCommands with explicit phase and persistence dependencies."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from ..codex_sdk import CodexSdkManager
from ..errors import ApprovalRequired as ApprovalRequired, PipelineError
from ..git import GitError, GitWorkspace, LOCAL_GIT_TIMEOUT_SECONDS
from ..integration import integration_branch_name, uses_shared_workspace
from ..integration.archive_flow import ArchiveFlow
from ..integration.archive_views import archive_fingerprint, archive_request_id, archive_target_payload
from ..integration.deletion import RunWorkspaceDeletion, RUN_DELETION_TIMEOUT_SECONDS
from ..integration.workspace_access import WorkspaceAccess
from ..integration.workspace_flows import WorkspaceFlows
from ..integration.workspaces import WorkspaceStatusQueries
from ..models import RunDeletion, RunLockState, RunState, WorkspaceStatus
from ..persistence.integration_records import LifecycleCommandsRecords
from ..persistence.run_lookup import RunLookup, find_task
from ..planning.conversation import planning_conversation_id


@dataclass
class LifecycleCommands:
    records: LifecycleCommandsRecords
    archive: ArchiveFlow
    workspaces: WorkspaceFlows
    read_git: Callable[[], GitWorkspace]
    sdk: Callable[[], CodexSdkManager | None]
    lookup: RunLookup
    workspace: WorkspaceAccess

    def archive_plan(self, run_id: str) -> dict[str, object]:
        self.read_git().ensure_repository(non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        state = self.records.load(run_id)
        if state.archive is not None:
            return self.archive.archived_run_plan(state)
        registered = {
            worktree.path: worktree
            for worktree in self.read_git().list_worktrees(non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        }
        targets = self.workspaces.archive_cleanup_targets(state, registered)
        reasons = self.archive.archive_block_reasons(state)
        lock = self.records.inspect_lock(run_id)
        if lock.state != RunLockState.UNLOCKED:
            reasons.append(f"실행 잠금 상태가 {lock.state.value}입니다: {lock.reason}")
        fingerprint = archive_fingerprint(state, targets)
        return {
            "run_id": state.id,
            "expected_revision": state.updated_at,
            "fingerprint": fingerprint,
            "can_archive": not reasons,
            "block_reasons": reasons,
            "archived": False,
            "archive": None,
            "cleanup_targets": [archive_target_payload(target) for target in targets],
            "record_path": str(self.records.run_dir(state.id).resolve()),
            "preserved_records": [
                "요청·계획·기획 대화",
                "Task·복구·실행 시도",
                "검증·로그·사용량",
                "결과 commit 참조",
            ],
        }


    def archive_run(
        self,
        run_id: str,
        *,
        expected_revision: str,
        fingerprint: str,
        request_id: str,
        approved: bool,
    ) -> RunState:
        if not approved:
            raise ApprovalRequired("run archive requires explicit approval")
        normalized_request_id = archive_request_id(request_id)
        self.read_git().ensure_repository(non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        with self.records.project_git_lock("run-archive"), self.records.lock(run_id, "run-archive"), self.records.planning_chat_lock(run_id):
            return self.archive.archiver().archive_locked(
                run_id,
                expected_revision=expected_revision,
                fingerprint=fingerprint,
                normalized_request_id=normalized_request_id,
            )


    def retry_archive_cleanup(
        self, run_id: str, *, fingerprint: str, request_id: str, approved: bool
    ) -> RunState:
        if not approved:
            raise ApprovalRequired("archive cleanup retry requires explicit approval")
        normalized_request_id = archive_request_id(request_id)
        with self.records.project_git_lock("archive-cleanup"), self.records.lock(run_id, "archive-cleanup"):
            return self.archive.cleanup().retry_locked(
                run_id, fingerprint=fingerprint, normalized_request_id=normalized_request_id,
            )


    def delete_run(self, run_id: str, *, approved: bool) -> RunDeletion:
        if not approved:
            raise ApprovalRequired("run deletion requires explicit approval")
        deadline = time.monotonic() + RUN_DELETION_TIMEOUT_SECONDS

        def remaining_timeout() -> float:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PipelineError(f"작업 그룹 삭제가 제한시간을 초과했습니다: {RUN_DELETION_TIMEOUT_SECONDS}초")
            return remaining

        self.read_git().ensure_repository(non_interactive=True, timeout_seconds=remaining_timeout())
        self.lookup.require_known(run_id)
        lock = self.records.inspect_lock(run_id)
        if lock.state == RunLockState.STALE:
            self.records.clear_stale_lock(run_id)
            lock = self.records.inspect_lock(run_id)
        if lock.state != RunLockState.UNLOCKED:
            raise PipelineError(f"작업 그룹을 삭제할 수 없습니다. 실행 잠금 상태가 {lock.state.value}입니다: {lock.reason}")
        with self.records.lock(run_id, "run-delete"):
            state = self.records.load(run_id)
            if self.sdk() is not None:
                self.sdk().discard_idle_clients()
            result = RunWorkspaceDeletion(
                git=self.read_git(), verification_worktree=self.workspaces.run_deletion_verification_worktree,
                conflict_worktree=self.workspaces.run_deletion_conflict_worktree, run_root=self.workspace.run_worktree_root,
                targets=self.workspaces.run_deletion_targets, integration_branch=integration_branch_name, save_state=self.records.save,
            ).remove(state, remaining_timeout=remaining_timeout)
            self.records.delete(state.id)
            if self.sdk() is not None:
                self.sdk().close_conversation(planning_conversation_id(state))
            return result


    def workspace_statuses(self, run_id: str = "") -> list[WorkspaceStatus]:
        return WorkspaceStatusQueries(
            ensure_repository=lambda timeout: self.read_git().ensure_repository(non_interactive=True, timeout_seconds=timeout),
            load_run=self.records.load, list_runs=self.records.list_runs,
            registered_worktrees=lambda timeout: self.read_git().list_worktrees(non_interactive=True, timeout_seconds=timeout),
            uses_shared=uses_shared_workspace, task_status=self.workspaces.workspace_status,
        ).statuses(run_id)


    def cleanup_workspace(self, run_id: str, task_id: str, *, approved: bool) -> WorkspaceStatus:
        if not approved:
            raise ApprovalRequired("workspace clear requires --approve")
        self.lookup.require_known(run_id)
        with self.records.lock(run_id, "workspace-clear"):
            state = self.records.load(run_id)
            if state.archive is not None:
                raise PipelineError("보관된 작업 그룹은 보관 정리 다시 시도에서만 작업공간을 정리할 수 있습니다.")
            task = find_task(state, task_id)
            registered = {worktree.path: worktree for worktree in self.read_git().list_worktrees()}
            status = self.workspaces.workspace_status(state, task, registered, require_unlocked=False)
            if not status.cleanup_safe:
                raise PipelineError(f"workspace is not safe to clear: {status.state.value} ({status.reason})")
            try:
                if status.worktree_registered:
                    worktree = Path(status.worktree)
                    managed_state_exists = any(path.exists() for path in self.workspace.worktree_managed_state_roots(worktree))
                    self.read_git().remove_worktree(worktree, force=managed_state_exists)
                if status.branch_exists:
                    self.read_git().delete_branch(status.branch)
            except GitError as exc:
                state.add_event("workspace", f"{task.id} cleanup failed: {exc}")
                self.records.save(state)
                raise PipelineError(f"workspace cleanup failed: {exc}") from exc
            state.add_event(
                "workspace",
                ("shared run worktree and local branch cleaned" if uses_shared_workspace(state) else f"{task.id} worktree and branch cleaned"),
            )
            self.records.save(state)
            refreshed = {worktree.path: worktree for worktree in self.read_git().list_worktrees()}
            return self.workspaces.workspace_status(state, task, refreshed, require_unlocked=False)
