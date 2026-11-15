"""Scope consent receipts inside the caller's request-control lock."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable

from ..errors import PipelineError
from ..models import OperationRecord, RunState
from ..scope_consent import ScopeConsent


@dataclass(frozen=True, slots=True)
class ScopeConsentRecorder:
    load_operation: Callable[[str, str], OperationRecord | None]
    load_run: Callable[[str], RunState]
    save_operation: Callable[[OperationRecord], None]
    validate_target: Callable[[RunState, OperationRecord], None]
    scope_proposal: Callable[[RunState, str], dict[str, object] | None]
    scope_question: Callable[[dict[str, object]], str]

    def record_locked(
        self, run_id: str, record: OperationRecord, proposal: dict[str, object], consent: ScopeConsent,
    ) -> tuple[OperationRecord, str]:
        # Only decline/unclear produce a reply after the lock is released.
        response = ""
        latest = self.load_operation(run_id, record.request_id)
        if latest is None or latest.status != "running" or latest.phase != "deciding":
            raise PipelineError("승인 판단 중 요청이 취소됐습니다.")
        current = self.load_run(run_id)
        self.validate_target(current, latest)
        if self.scope_proposal(current, str(proposal["task_id"])) != proposal:
            raise PipelineError("승인 판단 중 작업 범위가 변경됐습니다.")
        latest.payload["scope_consent"] = asdict(consent)
        if consent.intent in {"approve", "approve_only"}:
            latest.payload["scope_approval"] = {"proposal": proposal, "resume": consent.intent == "approve"}
        elif consent.intent in {"decline", "unclear"}:
            response = ("경로 추가와 재시도는 보류했습니다. 기존 작업은 유지합니다." if consent.intent == "decline"
                        else self.scope_question(proposal))
            latest.payload["decision"] = {"action": "reply" if consent.intent == "decline" else "ask", "authorized": False,
                                          "task_id": proposal["task_id"], "message": response, "instruction": ""}
            if consent.intent == "unclear":
                latest.payload["scope_proposal"] = proposal
            latest.update("completed" if consent.intent == "decline" else "needs_input", status="succeeded")
        self.save_operation(latest)
        return latest, response
