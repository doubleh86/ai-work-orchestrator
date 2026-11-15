"""Preserve run archive records before caller-owned workspace cleanup."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from ..errors import PipelineError
from ..git import GitError, GitWorkspace, GitWorktree, LOCAL_GIT_TIMEOUT_SECONDS
from ..models import ArchiveCleanupStatus, ArchiveCleanupTarget, OperationRecord, RunArchive, RunState, utc_now


class ArchivePreservedFiles(Protocol):
    def __call__(self, run_id: str, *, excluded_operation_request_ids: tuple[str, ...] = ()) -> list[dict[str, object]]: ...


@dataclass(frozen=True, slots=True)
class ArchiveRecords:
    load_run: Callable[[str], RunState]
    run_directory: Callable[[str], Path]
    claim_operation: Callable[[OperationRecord], tuple[OperationRecord, bool]]
    save_snapshot: Callable[[RunState], tuple[Path, str]]
    save_operation: Callable[[OperationRecord], None]
    save_summary: Callable[[str, str], Path]
    preserved_files: ArchivePreservedFiles
    save_manifest: Callable[[str, dict[str, object]], tuple[Path, str]]
    save_state: Callable[[RunState], None]


@dataclass(frozen=True, slots=True)
class RunArchiver:
    git: GitWorkspace
    records: ArchiveRecords
    cleanup_targets: Callable[[RunState, dict[Path, GitWorktree]], list[ArchiveCleanupTarget]]
    fingerprint: Callable[[RunState, list[ArchiveCleanupTarget]], str]
    block_reasons: Callable[[RunState], list[str]]
    protect_commits: Callable[[RunState], list[dict[str, str]]]
    summary: Callable[[RunState, str, list[ArchiveCleanupTarget]], str]
    target_payload: Callable[[ArchiveCleanupTarget], dict[str, str]]
    cleanup: Callable[[RunState, OperationRecord], RunState]

    def archive_locked(self, run_id: str, *, expected_revision: str, fingerprint: str, normalized_request_id: str) -> RunState:
        state = self.records.load_run(run_id)
        if state.archive is not None:
            if state.archive.cleanup_request_id == normalized_request_id:
                return state
            raise PipelineError("이미 보관된 작업 그룹입니다. 남은 작업공간은 정리 다시 시도를 사용해 주세요.")
        registered = {
            worktree.path: worktree
            for worktree in self.git.list_worktrees(non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        }
        targets = self.cleanup_targets(state, registered)
        current_fingerprint = self.fingerprint(state, targets)
        if state.updated_at != expected_revision or current_fingerprint != fingerprint:
            raise PipelineError("작업 그룹 상태나 정리 대상이 변경됐습니다. 보관 내용을 다시 확인해 주세요.")
        reasons = self.block_reasons(state)
        if reasons:
            raise PipelineError("작업 그룹을 보관할 수 없습니다: " + " ".join(reasons))
        operation = OperationRecord(
            request_id=normalized_request_id,
            run_id=state.id,
            action="run_archive",
            digest=current_fingerprint,
            phase="saving_snapshot",
            scope=state.id,
        )
        existing, created = self.records.claim_operation(operation)
        if not created:
            if existing.action != operation.action or existing.digest != operation.digest:
                raise PipelineError("requestId가 다른 보관 요청에 사용되었습니다.")
            if existing.status in {"succeeded", "partial"}:
                return self.records.load_run(run_id)
            raise PipelineError("같은 보관 요청이 이미 처리되었습니다. 새로고침 후 다시 확인해 주세요.")
        try:
            archived_at = utc_now()
            snapshot_path, snapshot_digest = self.records.save_snapshot(state)
            operation.update("protecting_commits")
            self.records.save_operation(operation)
            protected_refs = self.protect_commits(state)
            summary_path = self.records.save_summary(state.id, self.summary(state, archived_at, targets))
            manifest = {
                "schema_version": 1,
                "run_id": state.id,
                "archived_at": archived_at,
                "source_revision": state.updated_at,
                "snapshot": {
                    "path": snapshot_path.relative_to(self.records.run_directory(state.id)).as_posix(),
                    "sha256": snapshot_digest,
                },
                "files": self.records.preserved_files(
                    state.id, excluded_operation_request_ids=(normalized_request_id,)
                ),
                "protected_refs": protected_refs,
                "cleanup_status": ArchiveCleanupStatus.PENDING.value,
                "cleanup_targets": [self.target_payload(target) for target in targets],
            }
            manifest_path, _ = self.records.save_manifest(state.id, manifest)
            state.archive = RunArchive(
                archived_at=archived_at,
                source_revision=state.updated_at,
                snapshot_path=str(snapshot_path.resolve()),
                manifest_path=str(manifest_path.resolve()),
                summary_path=str(summary_path.resolve()),
                fingerprint=current_fingerprint,
                cleanup_status=ArchiveCleanupStatus.RUNNING,
                cleanup_request_id=normalized_request_id,
                cleanup_targets=targets,
            )
            state.add_event("archive", "completed run records archived; workspace cleanup started")
            self.records.save_state(state)
            operation.update("cleaning_worktrees")
            self.records.save_operation(operation)
            return self.cleanup(state, operation)
        except Exception as exc:
            operation.update(operation.phase, status="failed", error=str(exc), error_code=type(exc).__name__)
            self.records.save_operation(operation)
            raise


@dataclass(frozen=True, slots=True)
class ArchiveCleanupWorkflow:
    load_run: Callable[[str], RunState]
    claim_operation: Callable[[OperationRecord], tuple[OperationRecord, bool]]
    save_state: Callable[[RunState], None]
    save_operation: Callable[[OperationRecord], None]
    cleanup_target: Callable[[RunState, ArchiveCleanupTarget], None]
    apply_cleanup: Callable[[RunState, OperationRecord], RunState]

    def retry_locked(self, run_id: str, *, fingerprint: str, normalized_request_id: str) -> RunState:
        state = self.load_run(run_id)
        if state.archive is None:
            raise PipelineError("보관되지 않은 작업 그룹입니다.")
        if state.archive.fingerprint != fingerprint:
            raise PipelineError("보관 기록과 정리 대상 fingerprint가 일치하지 않습니다.")
        if state.archive.cleanup_status == ArchiveCleanupStatus.COMPLETED:
            return state
        operation = OperationRecord(
            request_id=normalized_request_id,
            run_id=state.id,
            action="archive_cleanup",
            digest=fingerprint,
            phase="checking_targets",
            scope=state.id,
        )
        existing, created = self.claim_operation(operation)
        if not created:
            if existing.action != operation.action or existing.digest != operation.digest:
                raise PipelineError("requestId가 다른 정리 요청에 사용되었습니다.")
            if existing.status in {"succeeded", "partial"}:
                return state
            raise PipelineError("같은 정리 요청이 이미 처리되었습니다. 새로고침 후 다시 확인해 주세요.")
        state.archive.cleanup_request_id = normalized_request_id
        state.archive.cleanup_status = ArchiveCleanupStatus.RUNNING
        self.save_state(state)
        operation.update("cleaning_worktrees")
        self.save_operation(operation)
        return self.apply_cleanup(state, operation)

    def complete_targets(self, state: RunState, archive: RunArchive, operation: OperationRecord) -> RunState:
        for target in archive.cleanup_targets:
            if target.status in {"removed", "already_removed"}:
                continue
            try:
                self.cleanup_target(state, target)
            except PipelineError as exc:
                target.status = "blocked"
                target.error = str(exc)
            except (GitError, OSError) as exc:
                target.status = "failed"
                target.error = str(exc)
            self.save_state(state)
        completed = sum(target.status in {"removed", "already_removed"} for target in archive.cleanup_targets)
        total = len(archive.cleanup_targets)
        if completed == total:
            archive.cleanup_status = ArchiveCleanupStatus.COMPLETED
        elif completed == 0:
            archive.cleanup_status = ArchiveCleanupStatus.BLOCKED
        else:
            archive.cleanup_status = ArchiveCleanupStatus.PARTIAL
        state.add_event("archive", f"archive workspace cleanup {archive.cleanup_status.value}: {completed}/{total}")
        self.save_state(state)
        operation.update(
            "completed" if archive.cleanup_status == ArchiveCleanupStatus.COMPLETED else archive.cleanup_status.value,
            status="succeeded" if archive.cleanup_status == ArchiveCleanupStatus.COMPLETED else "partial",
            error="" if archive.cleanup_status == ArchiveCleanupStatus.COMPLETED else "일부 작업공간 정리가 보류됐습니다.",
            error_code="" if archive.cleanup_status == ArchiveCleanupStatus.COMPLETED else "cleanup_incomplete",
        )
        self.save_operation(operation)
        return state
