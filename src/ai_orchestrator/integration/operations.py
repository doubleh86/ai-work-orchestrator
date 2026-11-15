"""Main operation receipts without Git or Run stage authority."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Callable

from ..errors import PipelineError
from ..models import OperationRecord, RunState


@dataclass(frozen=True, slots=True)
class GitOperationRecorder:
    load_operation: Callable[[str, str], OperationRecord | None]
    claim_operation: Callable[[OperationRecord], tuple[OperationRecord, bool]]
    save_operation: Callable[[OperationRecord], None]

    def completed_replay(self, state: RunState, action: str, request_id: str, *, review_id: str = "") -> bool:
        if not request_id:
            return False
        try:
            normalized = str(uuid.UUID(request_id.strip()))
        except ValueError as exc:
            raise PipelineError("requestId는 UUID 형식이어야 합니다.") from exc
        existing = self.load_operation(state.id, normalized)
        if existing is None:
            return False
        if existing.action != action:
            raise PipelineError(f"requestId가 다른 작업에 사용되었습니다: {existing.action}")
        if existing.payload.get("review_id", "") != review_id:
            raise PipelineError("같은 요청 ID를 다른 Main 반영 검토에 사용할 수 없습니다.")
        if existing.status == "succeeded":
            return True
        raise PipelineError(f"이전 {action} 요청 상태를 확인해 주세요: {existing.phase} ({existing.status})")

    def claim(self, state: RunState, action: str, request_id: str, phase: str, *, review_id: str = "") -> OperationRecord:
        try:
            normalized = str(uuid.UUID(request_id.strip())) if request_id else str(uuid.uuid4())
        except ValueError as exc:
            raise PipelineError("requestId는 UUID 형식이어야 합니다.") from exc
        payload = {
            "action": action,
            "workspace_mode": state.workspace_mode.value,
            "expected_main_head": state.verified_main_head,
            "target_head": state.verified_integration_head,
        }
        if review_id:
            payload["review_id"] = review_id
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        record = OperationRecord(
            request_id=normalized,
            run_id=state.id,
            action=action,
            digest=digest,
            phase=phase,
            expected_main_head=state.verified_main_head,
            target_head=state.verified_integration_head,
            payload={"review_id": review_id} if review_id else {},
        )
        existing, created = self.claim_operation(record)
        if not created:
            if existing.action != action or existing.digest != digest:
                raise PipelineError("requestId가 다른 Main 작업 대상에 사용되었습니다.")
            if existing.status == "succeeded":
                return existing
            raise PipelineError(f"이전 {action} 요청 상태를 확인해 주세요: {existing.phase} ({existing.status})")
        return record

    def fail(self, operation: OperationRecord, error: Exception) -> None:
        if operation.status == "succeeded":
            return
        operation.update(operation.phase, status="failed", error=str(error))
        self.save_operation(operation)
