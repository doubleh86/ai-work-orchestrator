from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .common import (
    ArchiveCleanupStatus,
    ConflictResolutionStatus,
    IntegrationStatus,
    WorkspaceLocationSource,
    WorkspaceState,
    utc_now,
)


@dataclass(frozen=True, slots=True)
class WorkspaceLocation:
    root: str
    source: WorkspaceLocationSource
    layout_version: int = 2
    notice_code: str = ""


@dataclass(frozen=True, slots=True)
class IntegrationConflictFile:
    path: str
    kind: str
    base_blob: str = ""
    work_blob: str = ""
    main_blob: str = ""
    base_mode: str = ""
    work_mode: str = ""
    main_mode: str = ""
    binary: bool = False
    supported: bool = True


@dataclass(slots=True)
class ConflictResolutionCandidate:
    id: str
    request_id: str
    revision: int = 1
    status: str = "generating"
    worktree: str = ""
    commit: str = ""
    changed_paths: list[str] = field(default_factory=list)
    content_digest: str = ""
    summary: str = ""
    error: str = ""
    created_at: str = field(default_factory=utc_now)
    applied_at: str = ""
    apply_request_id: str = ""


@dataclass(slots=True)
class IntegrationConflict:
    id: str
    verification_attempt_id: str
    main_head: str
    work_head: str
    merge_base_heads: list[str]
    files: list[IntegrationConflictFile]
    fingerprint: str
    detected_at: str = field(default_factory=utc_now)
    abort_status: str = "pending"
    abort_error: str = ""
    resolution_status: ConflictResolutionStatus = ConflictResolutionStatus.UNRESOLVED
    candidate: ConflictResolutionCandidate | None = None
    error: str = ""


@dataclass(slots=True)
class RecoveryTask:
    id: str
    kind: str
    source_key: str
    conflict: IntegrationConflict
    title: str = "최신 Main 통합 충돌 해결"
    operation_request_ids: list[str] = field(default_factory=list)
    verification_attempt_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    superseded_by: str = ""


@dataclass(slots=True)
class ArchiveCleanupTarget:
    id: str
    recorded_path: str
    expected_head: str
    status: str = "pending"
    error: str = ""
    archive_ref: str = ""


@dataclass(slots=True)
class RunArchive:
    archived_at: str
    source_revision: str
    snapshot_path: str
    manifest_path: str
    summary_path: str
    fingerprint: str
    cleanup_status: ArchiveCleanupStatus = ArchiveCleanupStatus.PENDING
    cleanup_request_id: str = ""
    cleanup_targets: list[ArchiveCleanupTarget] = field(default_factory=list)


@dataclass(slots=True)
class VerificationAttempt:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "running"
    started_at: str = field(default_factory=utc_now)
    finished_at: str = ""
    main_head: str = ""
    task_heads: dict[str, str] = field(default_factory=dict)
    integration_head: str = ""
    phase: str = "preparing"
    current_command: list[str] = field(default_factory=list)
    passed_commands: list[list[str]] = field(default_factory=list)
    commit_queue_task_ids: list[str] = field(default_factory=list)
    last_integrated_task_id: str = ""
    failed_task_id: str = ""
    failure_phase: str = ""
    failed_command: list[str] = field(default_factory=list)
    candidate_task_ids: list[str] = field(default_factory=list)
    attribution_reason: str = ""
    log_path: str = ""
    error: str = ""
    stop_reason: str = ""
    command_timeout_seconds: int = 0
    total_timeout_seconds: int = 0
    repair_count: int = 0


@dataclass(frozen=True, slots=True)
class PushReceipt:
    scope: str
    remote: str
    branch: str
    local_commit: str
    remote_commit: str
    operation_request_id: str = ""
    pushed_at: str = field(default_factory=utc_now)


def conflict_source_key(conflict: IntegrationConflict) -> str:
    return f"{conflict.work_head}:{conflict.main_head}:{conflict.fingerprint}"


@dataclass(frozen=True, slots=True)
class RepositoryUpdate:
    repo_path: str
    branch: str
    remote: str
    before_commit: str
    after_commit: str
    remaining_change_count: int = 0
    sync: MainSyncStatus | None = None

    @property
    def changed(self) -> bool:
        return self.before_commit != self.after_commit


@dataclass(frozen=True, slots=True)
class MainChangeItem:
    path: str
    status: str
    staged: bool
    unstaged: bool
    staged_status: str = ""
    unstaged_status: str = ""
    original_path: str = ""


@dataclass(frozen=True, slots=True)
class MainSyncStatus:
    local_head: str
    remote_head: str
    remote: str
    target_branch: str
    relation: str
    ahead: int | None
    behind: int | None
    checked_at: str = ""
    error: str = ""


@dataclass(frozen=True, slots=True)
class MainChangeSnapshot:
    snapshot_id: str
    repo_path: str
    branch: str
    expected_branch: str
    changes: tuple[MainChangeItem, ...]
    excluded_count: int
    sync: MainSyncStatus
    blocked_reason: str = ""


@dataclass(frozen=True, slots=True)
class MainChangeDiff:
    snapshot_id: str
    path: str
    mode: str
    content: str
    binary: bool = False
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class MainMutationResult:
    phase: str
    commit: str
    commit_created: bool
    pushed: bool
    remaining_change_count: int
    snapshot: MainChangeSnapshot
    error: str = ""


@dataclass(frozen=True, slots=True)
class RunDeletion:
    run_id: str
    summary: str
    task_count: int
    worktree_count: int
    branch_count: int


@dataclass(frozen=True, slots=True)
class IntegrationControl:
    status: IntegrationStatus
    reason: str
    reason_code: str
    can_verify: bool
    can_apply_main: bool
    main_dirty: bool | None = None
    verified_main_head: str = ""
    current_main_head: str = ""
    verified_integration_head: str = ""
    current_integration_head: str = ""
    remote_configured: bool = False
    can_recover_main_apply: bool = False
    checked_at: str = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class WorkspaceStatus:
    run_id: str
    task_id: str
    state: WorkspaceState
    run_stage: str
    task_status: str
    branch: str
    worktree: str
    worktree_exists: bool
    worktree_registered: bool
    worktree_clean: bool | None
    branch_exists: bool
    branch_merged: bool | None
    cleanup_safe: bool
    reason: str
