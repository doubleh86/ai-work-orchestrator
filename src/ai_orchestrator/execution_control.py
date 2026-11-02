from __future__ import annotations

from typing import Protocol


class CancellationSignal(Protocol):
    def is_set(self) -> bool: ...


class ExecutionStopped(RuntimeError):
    """Raised after an owned execution has received a user stop request."""

    def __init__(self, message: str, *, request_id: str = "") -> None:
        super().__init__(message)
        self.request_id = request_id


class DispatchPaused(ExecutionStopped):
    """Raised before a queued Task starts after dispatch was paused."""
