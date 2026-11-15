"""Data records for project-chat decisions and actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, ContextManager

from ..models import OperationRecord, RunExecutionControl, RunState


@dataclass(frozen=True, slots=True)
class ProjectChatRecords:
    load_run: Callable[[str], RunState]
    load_operation: Callable[[str, str], OperationRecord | None]
    save_operation: Callable[[OperationRecord], None]
    control_lock: Callable[[str], ContextManager[None]]


@dataclass(frozen=True, slots=True)
class ProjectChatDecisionResult:
    payload: dict[str, object]
    handled: bool = False


@dataclass(frozen=True, slots=True)
class ProjectChatAction:
    run_id: str
    request_id: str
    step_id: str
    state: RunState
    control: RunExecutionControl
    record: OperationRecord
    decision: dict[str, object]
    kind: str
