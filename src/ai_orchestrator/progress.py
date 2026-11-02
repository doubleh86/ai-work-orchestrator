from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProgressObservation:
    attempt_id: str
    invocation_id: str
    phase: str
    detail: str = ""
    turn_id: str = ""
    phase_started_at: str = ""
    last_event_received_at: str = ""
    last_activity_changed_at: str = ""
    event_seq: int = 0
    activity_seq: int = 0
    evidence_kind: str = "provider_event"


def advance_progress_observation(
    current: ProgressObservation | None,
    *,
    attempt_id: str,
    invocation_id: str,
    turn_id: str,
    phase: str,
    detail: str,
    received_at: str,
    event_seq: int,
    activity_changed: bool,
    evidence_kind: str,
) -> ProgressObservation:
    same_invocation = current is not None and current.attempt_id == attempt_id and current.invocation_id == invocation_id
    changed = not same_invocation or activity_changed or current.phase != phase or current.detail != detail
    waiting = evidence_kind == "retry_wait"
    return ProgressObservation(
        attempt_id=attempt_id,
        invocation_id=invocation_id,
        turn_id=turn_id or (current.turn_id if same_invocation else ""),
        phase=phase,
        detail=detail,
        phase_started_at=received_at if changed else current.phase_started_at,
        last_event_received_at=received_at,
        last_activity_changed_at=(current.last_activity_changed_at if same_invocation else "") if waiting
        else received_at if changed else current.last_activity_changed_at,
        event_seq=max(event_seq, (current.event_seq + 1) if same_invocation else 1),
        activity_seq=(current.activity_seq if same_invocation else 0) if waiting
        else (current.activity_seq + 1) if same_invocation and changed else (current.activity_seq if same_invocation else 1),
        evidence_kind=("retry_wait" if waiting else "local_phase" if evidence_kind == "local_phase"
                       else "activity_change" if changed else evidence_kind),
    )
