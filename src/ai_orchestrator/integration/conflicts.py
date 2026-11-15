from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from .layout import uses_shared_workspace
from ..errors import PipelineError
from ..git import GitError, GitWorkspace, LOCAL_GIT_TIMEOUT_SECONDS
from ..models import (
    ConflictResolutionStatus,
    IntegrationConflict,
    IntegrationConflictFile,
    OperationRecord,
    RunState,
)


def conflict_request_id(request_id: str) -> str:
    try:
        normalized = str(uuid.UUID(request_id.strip()))
    except (AttributeError, ValueError) as exc:
        raise PipelineError("requestId는 UUID 형식이어야 합니다.") from exc
    return normalized


def conflict_prepare_block_reason(state: RunState, conflict: IntegrationConflict) -> str:
    if not uses_shared_workspace(state):
        return "공유 작업 그룹에서만 해결안을 만들 수 있습니다."
    if conflict.abort_status != "verified":
        return "충돌 뒤 원래 작업공간 복구를 먼저 확인해야 합니다."
    unsupported = [item.path for item in conflict.files if not item.supported]
    if unsupported:
        return "자동 해결을 지원하지 않는 파일이 있습니다: " + ", ".join(unsupported)
    if conflict.resolution_status == ConflictResolutionStatus.GENERATING:
        return "해결안 생성 요청이 진행 중입니다."
    if conflict.resolution_status == ConflictResolutionStatus.APPLYING:
        return "해결안 적용과 전체 검증이 진행 중입니다."
    if conflict.resolution_status == ConflictResolutionStatus.APPLIED:
        return "해결안을 이미 적용했습니다. 검증 결과를 확인해 주세요."
    return "현재 충돌 상태에서는 새 해결안을 만들 수 없습니다."


def conflict_apply_block_reason(conflict: IntegrationConflict) -> str:
    if conflict.resolution_status == ConflictResolutionStatus.GENERATING:
        return "해결안 생성이 끝난 뒤 적용할 수 있습니다."
    if conflict.resolution_status == ConflictResolutionStatus.APPLYING:
        return "해결안 적용과 전체 검증이 진행 중입니다."
    if conflict.resolution_status == ConflictResolutionStatus.APPLIED:
        return "해결안을 이미 적용했습니다. 검증 결과를 확인해 주세요."
    if conflict.candidate is None:
        return "먼저 해결안을 만들어 검토해 주세요."
    if conflict.candidate.status != ConflictResolutionStatus.CANDIDATE_READY.value:
        return "적용 가능한 해결안 후보가 준비되지 않았습니다."
    return "현재 후보를 적용할 수 없습니다. 상태를 다시 확인해 주세요."


def require_integration_conflict(
    state: RunState, *, conflict_id: str = "", fingerprint: str = ""
) -> IntegrationConflict:
    conflict = state.integration_conflict
    if conflict is None:
        raise PipelineError("이 작업 그룹에 보존된 Main 통합 충돌이 없습니다.")
    if conflict_id and conflict.id != conflict_id:
        raise PipelineError("충돌 ID가 현재 snapshot과 일치하지 않습니다.")
    if fingerprint and conflict.fingerprint != fingerprint:
        raise PipelineError("충돌 fingerprint가 현재 snapshot과 일치하지 않습니다.")
    return conflict


def conflict_resolution_prompt(state: RunState, conflict: IntegrationConflict) -> str:
    paths = "\n".join(f"- {item.path} ({item.kind})" for item in conflict.files)
    return (
        f"# Latest Main conflict resolution\n\nRun: {state.id}\nWork commit: {conflict.work_head}\nMain commit: {conflict.main_head}\n\n"
        "Resolve the existing Git conflict in this isolated candidate worktree.\n\nAllowed files:\n"
        f"{paths}\n\n"
        "Preserve the intent from both the completed work and the latest Main change. Inspect nearby code only when needed.\n"
        "Edit only the listed conflict files. Do not run git add, git commit, git merge, git reset, or change refs.\n"
        "Remove all conflict markers. If the two sides require a product decision that cannot be inferred safely, "
        "leave the conflict markers and explain the decision needed.\n"
        "At the end, briefly summarize how both sides were preserved.\n"
    )


def integration_conflict_fingerprint(main_head: str, work_head: str, files: list[IntegrationConflictFile]) -> str:
    payload = {
        "main_head": main_head,
        "work_head": work_head,
        "files": [
            {
                "path": item.path,
                "kind": item.kind,
                "blobs": [item.base_blob, item.work_blob, item.main_blob],
                "modes": [item.base_mode, item.work_mode, item.main_mode],
            }
            for item in files
        ],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ConflictInspector:
    git: GitWorkspace
    repo: Path
    run_directory: Callable[[str], Path]
    load_operation: Callable[[str, str], OperationRecord | None]
    read_log_tail: Callable[[Path], str]

    def view(
        self, state: RunState, run_id: str, *, conflict_id: str = "", file_path: str = "", recovery_task_id: str = ""
    ) -> dict[str, object]:
        recovery_task = None
        if recovery_task_id:
            recovery_task = next((task for task in state.recovery_tasks if task.id == recovery_task_id), None)
            if recovery_task is None:
                raise PipelineError("선택한 복구 Task가 이 작업 그룹에 없습니다.")
            conflict = recovery_task.conflict
            if conflict_id and conflict.id != conflict_id:
                raise PipelineError("충돌 ID가 선택한 복구 Task와 일치하지 않습니다.")
        else:
            conflict = require_integration_conflict(state, conflict_id=conflict_id)
            recovery_task = state.recovery_task_for_conflict(conflict.id)
        serialized = state.to_dict()
        payload = serialized["integration_conflict"]
        if state.integration_conflict is None or state.integration_conflict.id != conflict.id:
            payload = next(
                item["conflict"] for item in serialized.get("recovery_tasks", []) if item.get("id") == recovery_task_id
            )
        recovery_payload = next(
            (item for item in serialized.get("recovery_tasks", []) if item.get("id") == recovery_task.id), None
        ) if recovery_task is not None else None
        attempts = []
        if recovery_task is not None:
            for request_id in recovery_task.operation_request_ids:
                operation = self.load_operation(run_id, request_id)
                if operation is None:
                    attempts.append({"request_id": request_id, "status": "unknown", "phase": "unknown", "action": "unknown", "error": "", "log": ""})
                    continue
                log = ""
                if operation.action == "conflict_resolution_prepare":
                    log_path = self.run_directory(run_id) / "logs" / f"conflict-{request_id}.log"
                    if log_path.is_file():
                        log = self.read_log_tail(log_path)
                attempts.append({
                    "request_id": operation.request_id,
                    "action": operation.action,
                    "status": operation.status,
                    "phase": operation.phase,
                    "error": operation.error,
                    "created_at": operation.created_at,
                    "updated_at": operation.updated_at,
                    "result_commit": operation.result_commit,
                    "progress_observation": asdict(operation.progress_observation) if operation.progress_observation else None,
                    "log": log,
                })
        selected: dict[str, object] | None = None
        if file_path:
            conflict_file = next((item for item in conflict.files if item.path == file_path), None)
            if conflict_file is None:
                raise PipelineError("선택한 파일은 이 충돌 snapshot에 없습니다.")
            selected = {
                "path": conflict_file.path,
                "kind": conflict_file.kind,
                "base": self.git.read_blob(self.repo, conflict_file.base_blob, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS),
                "work": self.git.read_blob(self.repo, conflict_file.work_blob, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS),
                "main": self.git.read_blob(self.repo, conflict_file.main_blob, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS),
                "candidate": "",
                "candidate_state": (
                    "generating" if conflict.resolution_status == ConflictResolutionStatus.GENERATING else "not_generated"
                ),
                "candidate_error": "",
            }
            if conflict.candidate and conflict.candidate.commit:
                try:
                    candidate_blob = self.git.blob_at(
                        self.repo,
                        conflict.candidate.commit,
                        conflict_file.path,
                        non_interactive=True,
                        timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
                    )
                    if candidate_blob:
                        selected["candidate"] = self.git.read_blob(
                            self.repo, candidate_blob, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
                        )
                        selected["candidate_state"] = "ready"
                    else:
                        selected["candidate_state"] = "missing"
                except (GitError, OSError) as exc:
                    selected["candidate_state"] = "read_failed"
                    selected["candidate_error"] = str(exc)
        active_conflict = bool(
            recovery_task is not None
            and state.integration_conflict is not None
            and state.integration_conflict.id == conflict.id
            and not recovery_task.superseded_by
        )
        can_prepare = (
            active_conflict
            and uses_shared_workspace(state)
            and conflict.abort_status == "verified"
            and all(item.supported for item in conflict.files)
            and conflict.resolution_status
            not in {ConflictResolutionStatus.GENERATING, ConflictResolutionStatus.APPLYING, ConflictResolutionStatus.APPLIED}
        )
        can_apply = bool(
            active_conflict
            and conflict.candidate
            and conflict.candidate.status == ConflictResolutionStatus.CANDIDATE_READY.value
            and conflict.resolution_status == ConflictResolutionStatus.CANDIDATE_READY
        )
        return {
            "conflict": payload,
            "recovery_task": recovery_payload,
            "attempts": attempts,
            "selected_file": selected,
            "can_prepare": can_prepare,
            "can_apply": can_apply,
            "prepare_block_reason": "" if can_prepare else (
                "새 기준의 복구 Task로 대체된 기록입니다." if not active_conflict else conflict_prepare_block_reason(state, conflict)
            ),
            "apply_block_reason": "" if can_apply else (
                "새 기준의 복구 Task로 대체된 기록입니다." if not active_conflict else conflict_apply_block_reason(conflict)
            ),
        }
