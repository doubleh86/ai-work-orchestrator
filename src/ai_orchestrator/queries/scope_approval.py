"""Read scope approval receipts and offered-proposal evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..models import OperationRecord, PlanningMessageRole, RunState
from ..scope_consent import scope_proposal_id
from ..task_scope_review import scope_approval_reply


@dataclass(frozen=True, slots=True)
class ScopeApprovalQueries:
    load_run: Callable[[str], RunState]
    load_operation: Callable[[str, str], OperationRecord | None]
    recent_operations: Callable[[str, str], list[OperationRecord]]

    def result(self, record: OperationRecord) -> dict[str, object]:
        child = self.load_operation(record.run_id, str(record.payload["step_id"]))
        state = self.load_run(record.run_id)
        status = child.status if child else record.status
        scope_applied = bool(record.payload.get("scope_approval_consumed"))
        error = (child.error if child else "") or record.error
        return {"run_id": state.id, "stage": state.stage.value, "scope_applied": scope_applied,
                "retry_status": status, "error": error}

    def was_offered(self, state: RunState, proposal: dict[str, object]) -> bool:
        for record in self.recent_operations(state.id, "chat_control"):
            if (record.status != "succeeded" or record.payload.get("intent") != "project"
                    or record.payload.get("fingerprint") != proposal["fingerprint"]):
                return False
            if record.phase == "needs_input" and record.payload.get("scope_proposal") == proposal:
                question = record.payload.get("decision", {}).get("message")
                return any(item.role == PlanningMessageRole.ASSISTANT and item.text == question for item in state.planning_messages)
            # A shown proposal is context, never permission for the next
            # message. Legacy records bridge only unexecuted human
            # approvals of this exact failure.
            if record.payload.get("history") or record.payload.get("scope_approval_consumed"):
                return False
            consent = record.payload.get("scope_consent")
            if consent is not None:
                if consent.get("proposal_id") != scope_proposal_id(proposal):
                    return False
            elif scope_approval_reply(str(record.payload.get("message", "")), tuple(proposal["paths"]), offered=True) is None:
                return False
        return False
