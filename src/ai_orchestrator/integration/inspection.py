from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .layout import integration_branch_name, uses_shared_workspace
from ..git import GitError, GitWorkspace, LOCAL_GIT_TIMEOUT_SECONDS
from ..models import (
    ConflictResolutionStatus,
    IntegrationControl,
    IntegrationStatus,
    OperationRecord,
    RunLockState,
    RunLockStatus,
    RunState,
    RunStep,
    Stage,
    TaskStatus,
)


@dataclass(frozen=True, slots=True)
class IntegrationInspector:
    git: GitWorkspace
    remote: str
    managed_roots: tuple[Path, ...]
    latest_operation: Callable[[str, str], OperationRecord | None]
    inspect_project_lock: Callable[[], RunLockStatus]

    def control(self, state: RunState, lock: RunLockStatus) -> IntegrationControl:
        try:
            remote_configured = self.git.remote_configured(self.remote)
        except (GitError, OSError):
            remote_configured = True
        common = {
            "verified_main_head": state.verified_main_head,
            "verified_integration_head": state.verified_integration_head,
            "remote_configured": remote_configured,
        }
        if lock.state == RunLockState.ACTIVE and lock.operation in {"verify", "verify-and-repair"}:
            return IntegrationControl(IntegrationStatus.VERIFYING, "최신 Main과 작업 결과를 통합·검증하고 있습니다.", "lock_active", False, False, **common)
        if lock.state == RunLockState.ACTIVE:
            return IntegrationControl(IntegrationStatus.UNKNOWN, "그룹 작업이 진행 중입니다. 종료 후 병합 상태를 다시 확인하세요.", "lock_active", False, False, **common)
        if lock.state in {RunLockState.UNVERIFIABLE, RunLockState.MALFORMED}:
            return IntegrationControl(IntegrationStatus.UNKNOWN, "Main 상태를 확인하지 못했습니다. 상태를 다시 확인해 주세요.", "query_failed", False, False, **common)
        if not state.tasks or not all(task.status in {TaskStatus.COMPLETED, TaskStatus.MERGED} for task in state.tasks):
            return IntegrationControl(IntegrationStatus.NOT_READY, "Task 실행이 아직 완료되지 않았습니다.", "tasks_incomplete", False, False, **common)
        if state.integration_user_checks_pending():
            return IntegrationControl(
                IntegrationStatus.NOT_READY, "통합에 필요한 사용자 확인이 남았습니다.", "user_checks_pending", False, False, **common,
            )
        pending_main_push = self.main_push_recovery_source(state) if remote_configured else None
        if state.stage in {Stage.MERGED, Stage.PUSHED, Stage.DEPLOYED} and pending_main_push is None:
            reason = "검증한 작업 결과를 Main에 반영했습니다."
            if state.stage == Stage.MERGED and not remote_configured:
                reason = "로컬 Main 반영을 완료했습니다. 원격 저장소는 연결되지 않았습니다."
            return IntegrationControl(IntegrationStatus.APPLIED, reason, "applied", False, False, **common)
        try:
            self.git.ensure_repository(non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            current_main = self.git.branch_head(state.main_branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            main_checked_out = self.git.current_branch(non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS) == state.main_branch
            main_dirty = self.git.has_uncommitted_changes(
                ignored_untracked_roots=self.managed_roots, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
            ) if main_checked_out else None
            current_integration = ""
            if state.verified_integration_head:
                branch = state.execution_branch if uses_shared_workspace(state) else integration_branch_name(state.id)
                if branch and self.git.branch_exists(branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS):
                    current_integration = self.git.branch_head(branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            changed_task_heads: list[str] = []
            if state.verified_task_heads and not uses_shared_workspace(state):
                changed_task_heads = [
                    task.id
                    for task in state.tasks
                    if state.verified_task_heads.get(task.id)
                    != self.git.branch_head(task.branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
                ]
        except (GitError, OSError) as exc:
            return IntegrationControl(IntegrationStatus.UNKNOWN, f"Main 상태를 확인하지 못했습니다: {exc}", "query_failed", False, False, **common)
        details = {**common, "main_dirty": main_dirty, "current_main_head": current_main, "current_integration_head": current_integration}
        merge_operation = self.latest_operation(state.id, "merge")
        if (
            merge_operation is not None
            and merge_operation.phase == "applying_main"
            and merge_operation.status == "running"
            and (lock.state != RunLockState.ACTIVE or lock.operation != "merge")
        ):
            try:
                recoverable = self.recovery_ready(state, merge_operation, lock, remote_configured)
            except (GitError, OSError):
                recoverable = False
            reason = (
                "이전 Main 반영이 중단됐지만 Main ref·index·작업 폴더가 검증 commit과 일치합니다. 원본을 확인한 뒤 별도 승인으로 결과를 확정할 수 있습니다."
                if recoverable else
                "이전 Main 반영이 중단되었습니다. Main ref 또는 작업 폴더가 검증 commit과 일치하지 않을 수 있으므로 원본을 확인해 주세요."
            )
            return IntegrationControl(
                IntegrationStatus.UNKNOWN, reason, "main_apply_recoverable" if recoverable else "main_apply_interrupted",
                False, False, can_recover_main_apply=recoverable, **details,
            )
        if lock.state == RunLockState.STALE:
            return IntegrationControl(
                IntegrationStatus.UNKNOWN, "중단된 실행 잠금이 있습니다. 잠금 상태를 확인한 뒤 병합 상태를 다시 확인하세요.",
                "lock_stale", False, False, **details,
            )
        if state.integration_conflict and state.integration_conflict.resolution_status not in {
            ConflictResolutionStatus.APPLIED, ConflictResolutionStatus.STALE,
        }:
            return IntegrationControl(IntegrationStatus.CONFLICT, "Main 변경과 작업 결과가 충돌해 통합을 멈췄습니다.", "integration_conflict", False, False, **details)
        main_matches_verification = current_main == state.verified_main_head or (
            uses_shared_workspace(state)
            and state.stage == Stage.WORK_BRANCH_PUSHED
            and current_main == state.verified_integration_head
        )
        work_changed = (
            not current_integration
            or current_integration != state.verified_integration_head
            or bool(changed_task_heads)
            or (
                state.stage == Stage.WORK_BRANCH_PUSHED
                and state.pushed_work_branch_head != state.verified_integration_head
            )
        )
        if (
            pending_main_push is not None
            and current_main == state.verified_integration_head
            and not work_changed
            and remote_configured
        ):
            if not main_checked_out:
                return IntegrationControl(
                    IntegrationStatus.MAIN_PUSH_PENDING,
                    "로컬 Main 반영은 완료됐습니다. 현재 체크아웃된 branch가 Main이 아니므로 Main으로 돌아온 뒤 Push를 재시도하세요.",
                    "branch_mismatch", False, False, **details,
                )
            return IntegrationControl(
                IntegrationStatus.MAIN_PUSH_PENDING,
                "검증된 commit의 로컬 Main 반영은 완료됐습니다. 원격 상태 확인 후 Main Push를 진행할 수 있습니다.",
                "main_push_retry", False, False, **details,
            )
        if state.verified_main_head and (not main_matches_verification or work_changed):
            if not main_matches_verification and work_changed:
                reason = "Main과 작업 결과가 모두 변경되어 재검증이 필요합니다. 완료한 Task는 보존됩니다."
            elif not main_matches_verification:
                reason = "Main이 검증 이후 변경되어 재검증이 필요합니다. 완료한 Task는 보존됩니다."
            else:
                reason = "검증한 작업 결과가 변경되어 재검증이 필요합니다. 완료한 Task는 보존됩니다."
            reason_code = "main_changed" if not main_matches_verification else "work_changed"
            if not main_checked_out:
                reason += " 현재 체크아웃된 branch가 Main이 아니므로 Main으로 돌아온 뒤 재검증하세요."
            return IntegrationControl(IntegrationStatus.STALE, reason, reason_code, main_checked_out, False, **details)
        if state.stage in {Stage.VERIFIED, Stage.WORK_BRANCH_PUSHED} and state.verified_main_head:
            if not main_checked_out:
                return IntegrationControl(
                    IntegrationStatus.APPLY_BLOCKED, "검증은 완료됐지만 현재 체크아웃된 branch가 Main이 아닙니다.",
                    "branch_mismatch", False, False, **details,
                )
            expected_stage = Stage.WORK_BRANCH_PUSHED if uses_shared_workspace(state) and remote_configured else Stage.VERIFIED
            can_apply = state.stage == expected_stage
            if main_dirty:
                if not uses_shared_workspace(state):
                    return IntegrationControl(
                        IntegrationStatus.APPLY_BLOCKED, "검증은 완료됐습니다. Main의 미커밋 변경을 정리한 뒤 반영할 수 있습니다.",
                        "main_dirty", False, False, **details,
                    )
                try:
                    overlap = () if current_main == state.verified_integration_head else self.git.main_apply_overlap_paths(
                        state.verified_main_head, state.verified_integration_head,
                        ignored_untracked_roots=self.managed_roots, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
                    )
                except (GitError, OSError) as exc:
                    return IntegrationControl(IntegrationStatus.UNKNOWN, f"Main 변경의 겹침을 확인하지 못했습니다: {exc}", "query_failed", False, False, **details)
                if overlap:
                    sample = ", ".join(overlap[:3])
                    return IntegrationControl(
                        IntegrationStatus.APPLY_BLOCKED,
                        f"Main의 미커밋 변경과 검증 결과가 {len(overlap)}개 경로에서 겹칩니다: {sample}",
                        "main_overlap", False, False, **details,
                    )
                return IntegrationControl(
                    IntegrationStatus.VERIFIED,
                    "Main의 미커밋 변경과 검증 결과가 겹치지 않습니다. 반영 중에도 변경 보존을 다시 확인합니다.",
                    "main_dirty_disjoint", False, can_apply, **details,
                )
            return IntegrationControl(IntegrationStatus.VERIFIED, "최신 Main 기준 통합 검증이 완료됐습니다.", "verified", False, can_apply, **details)
        can_verify = state.stage == Stage.READY_TO_MERGE or (state.stage == Stage.FAILED and state.failed_step == RunStep.VERIFY)
        if can_verify and not main_checked_out:
            return IntegrationControl(
                IntegrationStatus.NEEDS_VERIFICATION,
                "현재 체크아웃된 branch가 Main이 아닙니다. Main으로 돌아온 뒤 통합·검증하세요.",
                "branch_mismatch", False, False, **details,
            )
        return IntegrationControl(
            IntegrationStatus.NEEDS_VERIFICATION, "최신 Main 기준 통합·검증이 필요합니다.",
            "verification_required", can_verify, False, **details,
        )

    def recovery_ready(
        self, state: RunState, operation: OperationRecord, lock: RunLockStatus, remote_configured: bool,
        *, require_stale_locks: bool = True,
    ) -> bool:
        expected_stage = Stage.WORK_BRANCH_PUSHED if uses_shared_workspace(state) and remote_configured else Stage.VERIFIED
        if (
            state.stage != expected_stage or state.active_step != RunStep.MERGE
            or operation.phase != "applying_main" or operation.status != "running"
            or operation.expected_main_head != state.verified_main_head
            or operation.target_head != state.verified_integration_head
            or not operation.expected_main_head or not operation.target_head
            or not state.tasks or not all(task.status == TaskStatus.COMPLETED for task in state.tasks)
        ):
            return False
        if require_stale_locks:
            if lock.state not in {RunLockState.STALE, RunLockState.UNLOCKED}:
                return False
            if lock.state == RunLockState.STALE and lock.operation != "merge":
                return False
            project_lock = self.inspect_project_lock()
            if project_lock.state not in {RunLockState.STALE, RunLockState.UNLOCKED}:
                return False
            if project_lock.state == RunLockState.STALE and project_lock.operation != "merge":
                return False
        branch = state.execution_branch if uses_shared_workspace(state) else integration_branch_name(state.id)
        if not branch or not self.git.branch_exists(branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS):
            return False
        if self.git.branch_head(branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS) != operation.target_head:
            return False
        if uses_shared_workspace(state) and remote_configured and state.pushed_work_branch_head != operation.target_head:
            return False
        return self.git.main_checkout_matches_commit(
            operation.target_head, ignored_untracked_roots=self.managed_roots,
            non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
        )

    def main_push_recovery_source(self, state: RunState) -> OperationRecord | None:
        if not uses_shared_workspace(state):
            return None
        failed = state.stage == Stage.FAILED and state.failed_step in {RunStep.MERGE, RunStep.PUSH}
        interrupted = state.stage == Stage.WORK_BRANCH_PUSHED and state.active_step == RunStep.MERGE
        previous_retry = self.latest_operation(state.id, "retry_main_push")
        interrupted_retry = (
            state.stage == Stage.FAILED and state.active_step == RunStep.PUSH
            and previous_retry is not None and previous_retry.status == "running"
            and previous_retry.phase in {"checking_remote", "pushing", "confirming_remote"}
            and previous_retry.target_head == state.verified_integration_head
        )
        local_only = state.stage == Stage.MERGED
        if not (failed or interrupted or interrupted_retry or local_only):
            return None
        operation = self.latest_operation(state.id, "merge")
        if operation is None:
            return None
        reviewed_apply = operation.phase == "main_applied" and bool(operation.payload.get("review_id"))
        if local_only and not reviewed_apply:
            return None
        if operation.status not in {"failed", "running", "interrupted"} and not (reviewed_apply and operation.status == "succeeded"):
            return None
        if operation.phase not in {"main_applied", "pushing", "confirming_remote"}:
            return None
        if not state.verified_main_head or not state.verified_integration_head:
            return None
        if operation.expected_main_head != state.verified_main_head or operation.target_head != state.verified_integration_head:
            return None
        if operation.result_commit and operation.result_commit != operation.target_head:
            return None
        if state.pushed_work_branch_head != operation.target_head:
            return None
        if not state.tasks or not all(task.status in {TaskStatus.COMPLETED, TaskStatus.MERGED} for task in state.tasks):
            return None
        return operation
