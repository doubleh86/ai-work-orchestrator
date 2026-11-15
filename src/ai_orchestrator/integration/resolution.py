"""Conflict resolution records and effects inside the caller's run lock."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..errors import PipelineError
from ..git import GitError, GitWorkspace, LOCAL_GIT_TIMEOUT_SECONDS
from ..models import ConflictResolutionCandidate, ConflictResolutionStatus, IntegrationConflict, OperationRecord, RunState, utc_now
from .candidates import ConflictCandidateBuilder, ConflictResolutionProfile, candidate_content_digest
from .layout import uses_shared_workspace


@dataclass(frozen=True, slots=True)
class ConflictResolutionRecords:
    save_state: Callable[[RunState], None]
    claim_operation: Callable[[OperationRecord], tuple[OperationRecord, bool]]
    save_operation: Callable[[OperationRecord], None]


@dataclass(frozen=True, slots=True)
class ConflictResolutionService:
    git: GitWorkspace
    repo: Path
    records: ConflictResolutionRecords
    shared_boundary: Callable[[RunState], tuple[str, Path]]
    ensure_clean: Callable[[Path], None]
    worktree_root: Callable[[RunState], Path]
    discard_candidate: Callable[[RunState, ConflictResolutionCandidate], None]
    select_profile: Callable[[RunState, str, str, str], ConflictResolutionProfile]
    builder: ConflictCandidateBuilder
    view: Callable[[str, str], dict[str, object]]

    def prepare(
        self, state: RunState, conflict: IntegrationConflict, *, run_id: str, normalized_request_id: str,
        agent_id: str = "", model: str = "", reasoning_effort: str = "",
    ) -> dict[str, object]:
        if not uses_shared_workspace(state):
            raise PipelineError("AI 충돌 해결안은 공유 작업 그룹에서만 만들 수 있습니다.")
        if conflict.abort_status != "verified":
            raise PipelineError("충돌 뒤 작업공간 복구가 확인되지 않아 해결안을 만들 수 없습니다.")
        unsupported = [item.path for item in conflict.files if not item.supported]
        if unsupported:
            raise PipelineError("자동 텍스트 해결을 지원하지 않는 충돌 파일이 있습니다: " + ", ".join(unsupported))
        if conflict.candidate and conflict.candidate.request_id == normalized_request_id:
            return self.view(run_id, conflict.id)
        if conflict.resolution_status in {ConflictResolutionStatus.GENERATING, ConflictResolutionStatus.APPLYING}:
            raise PipelineError("다른 충돌 해결 요청이 이미 진행 중입니다.")
        _, source_worktree = self.shared_boundary(state)
        self.ensure_clean(source_worktree)
        current_main = self.git.head(self.repo, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        current_work = self.git.head(source_worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        if current_main != conflict.main_head or current_work != conflict.work_head:
            conflict.resolution_status = ConflictResolutionStatus.STALE
            self.records.save_state(state)
            raise PipelineError("Main 또는 그룹 작업 commit이 바뀌어 기존 충돌 snapshot이 stale 상태입니다.")
        profile = self.select_profile(state, agent_id, model, reasoning_effort)
        agent, selected_model, selected_effort = profile.agent, profile.model, profile.reasoning_effort
        operation_digest = hashlib.sha256(json.dumps({
            "conflict_id": conflict.id,
            "fingerprint": conflict.fingerprint,
            "agent_id": agent.id,
            "model": selected_model,
            "reasoning_effort": selected_effort,
        }, sort_keys=True).encode("utf-8")).hexdigest()
        operation = OperationRecord(
            request_id=normalized_request_id,
            run_id=state.id,
            action="conflict_resolution_prepare",
            digest=operation_digest,
            phase="preparing_workspace",
            expected_main_head=conflict.main_head,
            target_head=conflict.work_head,
            task_id=(state.recovery_task_for_conflict(conflict.id).id if state.recovery_task_for_conflict(conflict.id) else ""),
            scope=conflict.id,
        )
        existing_operation, created = self.records.claim_operation(operation)
        if not created:
            if existing_operation.action != operation.action or existing_operation.digest != operation.digest:
                raise PipelineError("requestId가 다른 충돌 해결 요청에 사용되었습니다.")
            return self.view(run_id, conflict.id)
        state.link_recovery_operation(conflict.id, normalized_request_id)
        self.records.save_state(state)
        if conflict.candidate and conflict.candidate.worktree:
            try:
                self.discard_candidate(state, conflict.candidate)
            except Exception as exc:
                operation.update(
                    "failed",
                    status="failed",
                    error=str(exc),
                    error_code="candidate_cleanup_failed",
                )
                self.records.save_operation(operation)
                raise
        candidate_root = (self.worktree_root(state) / ".conflict-resolution").resolve()
        candidate_worktree = (candidate_root / normalized_request_id).resolve()
        if candidate_worktree.parent != candidate_root:
            raise PipelineError("충돌 해결 후보 경로가 작업 그룹 경계를 벗어났습니다.")
        candidate = ConflictResolutionCandidate(
            id=f"candidate-{normalized_request_id}",
            request_id=normalized_request_id,
            status=ConflictResolutionStatus.GENERATING.value,
            worktree=str(candidate_worktree),
        )
        conflict.candidate = candidate
        conflict.resolution_status = ConflictResolutionStatus.GENERATING
        conflict.error = ""
        state.add_event("integration_conflict", f"conflict resolution generation started: {candidate.id}")
        self.records.save_state(state)

        try:
            evidence = self.builder.build(
                state, conflict, operation, candidate_worktree=candidate_worktree,
                normalized_request_id=normalized_request_id, agent=agent,
                selected_model=selected_model, selected_effort=selected_effort,
            )
            commit, digest, allowed_paths, output = evidence.commit, evidence.content_digest, evidence.allowed_paths, evidence.output
            candidate.commit = commit
            candidate.changed_paths = sorted(allowed_paths)
            candidate.content_digest = digest
            candidate.summary = output.strip()[-4000:]
            candidate.status = ConflictResolutionStatus.CANDIDATE_READY.value
            conflict.resolution_status = ConflictResolutionStatus.CANDIDATE_READY
            state.add_event("integration_conflict", f"conflict resolution candidate ready: {candidate.id}")
            self.records.save_state(state)
            operation.result_commit = commit
            operation.update("candidate_ready", status="succeeded")
            self.records.save_operation(operation)
            return self.view(run_id, conflict.id)
        except Exception as exc:
            candidate.status = ConflictResolutionStatus.FAILED.value
            candidate.error = str(exc)
            conflict.resolution_status = ConflictResolutionStatus.FAILED
            conflict.error = str(exc)
            state.add_event("integration_conflict", f"conflict resolution generation failed: {exc}")
            self.records.save_state(state)
            operation.update("failed", status="failed", error=str(exc), error_code="conflict_candidate_failed")
            self.records.save_operation(operation)
            try:
                self.discard_candidate(state, candidate)
                candidate.worktree = ""
                self.records.save_state(state)
            except (GitError, PipelineError):
                pass
            raise

    def apply_candidate(
        self, state: RunState, conflict: IntegrationConflict, *, candidate_id: str,
        candidate_revision: int, normalized_request_id: str,
    ) -> tuple[OperationRecord, Path] | None:
        """Apply under the caller's lock; None means an already handled request."""
        candidate = conflict.candidate
        if candidate is None or candidate.id != candidate_id or candidate.revision != candidate_revision:
            raise PipelineError("검토한 해결안 revision과 현재 후보가 일치하지 않습니다.")
        if candidate.apply_request_id == normalized_request_id and candidate.status == ConflictResolutionStatus.APPLIED.value:
            return None
        if candidate.status != ConflictResolutionStatus.CANDIDATE_READY.value:
            raise PipelineError("적용할 수 있는 해결안 후보가 없습니다.")
        branch, worktree = self.shared_boundary(state)
        if self.git.head(self.repo, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS) != conflict.main_head:
            conflict.resolution_status = ConflictResolutionStatus.STALE
            self.records.save_state(state)
            raise PipelineError("Main commit이 바뀌어 해결안을 적용하지 않았습니다. 새 해결안을 만들어 주세요.")
        self.ensure_clean(worktree)
        if self.git.head(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS) != conflict.work_head:
            conflict.resolution_status = ConflictResolutionStatus.STALE
            self.records.save_state(state)
            raise PipelineError("그룹 작업 commit이 바뀌어 해결안을 적용하지 않았습니다. 새 해결안을 만들어 주세요.")
        candidate_worktree = Path(candidate.worktree).resolve()
        self.ensure_clean(candidate_worktree)
        if candidate_content_digest(self.git, candidate_worktree, candidate.commit, conflict.files) != candidate.content_digest:
            conflict.resolution_status = ConflictResolutionStatus.STALE
            self.records.save_state(state)
            raise PipelineError("검토 후 해결안 내용이 바뀌어 적용하지 않았습니다.")
        if self.git.commit_parents(
            candidate_worktree, candidate.commit, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
        ) != [conflict.work_head, conflict.main_head]:
            raise PipelineError("해결안 commit 부모가 승인한 기준과 일치하지 않습니다.")
        operation_digest = hashlib.sha256(json.dumps({
            "conflict_id": conflict.id,
            "fingerprint": conflict.fingerprint,
            "candidate_id": candidate.id,
            "candidate_revision": candidate.revision,
            "candidate_digest": candidate.content_digest,
        }, sort_keys=True).encode("utf-8")).hexdigest()
        recovery_task = state.recovery_task_for_conflict(conflict.id)
        operation = OperationRecord(
            request_id=normalized_request_id,
            run_id=state.id,
            action="conflict_resolution_apply",
            digest=operation_digest,
            phase="validating_candidate",
            expected_main_head=conflict.main_head,
            target_head=candidate.commit,
            task_id=recovery_task.id if recovery_task else "",
            scope=conflict.id,
        )
        existing_operation, created = self.records.claim_operation(operation)
        if not created:
            if existing_operation.action != operation.action or existing_operation.digest != operation.digest:
                raise PipelineError("requestId가 다른 충돌 해결 적용 요청에 사용되었습니다.")
            if existing_operation.status == "succeeded":
                return None
            raise PipelineError("같은 충돌 해결 적용 요청이 이미 처리되었습니다. 현재 상태와 시도 기록을 확인해 주세요.")
        state.link_recovery_operation(conflict.id, normalized_request_id)
        conflict.resolution_status = ConflictResolutionStatus.APPLYING
        candidate.status = ConflictResolutionStatus.APPLYING.value
        candidate.apply_request_id = normalized_request_id
        self.records.save_state(state)
        operation.update("applying")
        self.records.save_operation(operation)
        try:
            self.git.fast_forward_worktree(
                worktree, candidate.commit, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
            )
        except Exception as exc:
            candidate.status = ConflictResolutionStatus.FAILED.value
            candidate.error = str(exc)
            conflict.resolution_status = ConflictResolutionStatus.FAILED
            conflict.error = str(exc)
            state.add_event("integration_conflict", f"conflict resolution apply failed: {exc}")
            self.records.save_state(state)
            operation.update("apply_failed", status="failed", error=str(exc), error_code="candidate_apply_failed")
            self.records.save_operation(operation)
            raise
        candidate.status = ConflictResolutionStatus.APPLIED.value
        candidate.applied_at = utc_now()
        conflict.resolution_status = ConflictResolutionStatus.APPLIED
        state.add_event("integration_conflict", f"conflict resolution candidate applied: {candidate.id}")
        self.records.save_state(state)
        operation.result_commit = candidate.commit
        operation.update("verifying")
        self.records.save_operation(operation)
        return operation, candidate_worktree
