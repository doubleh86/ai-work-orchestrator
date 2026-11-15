"""Planning request ownership and receipts under caller-owned locks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..errors import PipelineError
from ..models import OperationRecord, RunState


@dataclass(frozen=True, slots=True)
class PlanningRequestRecords:
    load_run: Callable[[str], RunState]
    claim_operation: Callable[[OperationRecord], tuple[OperationRecord, bool]]
    load_operation: Callable[[str, str], OperationRecord | None]
    save_operation: Callable[[OperationRecord], None]
    requests_apply: Callable[[str], bool]

    def begin_locked(self, run_id: str, request_id: str, kind: str, message: str) -> dict[str, object]:
        state = self.load_run(run_id)
        if state.archive is not None:
            if kind != "chat":
                raise PipelineError("보관된 그룹에서는 대화만 할 수 있습니다.")
            kind = "archived_chat"
        elif kind == "chat" and self.requests_apply(message):
            kind = "replan"
        record = OperationRecord(request_id=request_id, run_id=run_id, action="planning_request", digest=kind,
                                 phase="running", reason=kind)
        existing, created = self.claim_operation(record)
        if not created and (existing.action != record.action or existing.digest != kind or existing.status != "running"):
            raise PipelineError("Planning request ID was already used")
        return {"request_id": request_id, "kind": kind}

    def owner_locked(self, run_id: str, request_id: str) -> OperationRecord:
        record = self.load_operation(run_id, request_id)
        if record is None or record.action != "planning_request":
            raise PipelineError("Planning request owner not found")
        return record

    def finish_locked(self, run_id: str, request_id: str, phase: str, error: str) -> dict[str, object]:
        record = self.load_operation(run_id, request_id)
        if record is None:
            raise PipelineError("Planning request owner disappeared")
        record.update(phase, status=phase, error=error)
        self.save_operation(record)
        return record.to_dict()
