"""Cancellation factory contract shared by task and verification phases."""

from __future__ import annotations

from typing import Protocol
from .lifecycle import StoredStopSignal
from ..models import RunState, WorkTask


class StopSignalFactory(Protocol):
    def __call__(self, state: RunState, task: WorkTask | None = None, *, scope: str = "task") -> StoredStopSignal | None: ...
