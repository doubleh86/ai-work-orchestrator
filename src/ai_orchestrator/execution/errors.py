"""Shared task verification failures, also exported at legacy entry points."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from ..errors import PipelineError
from .task_verification import TaskVerificationFailed, TaskVerificationTimedOut


class TaskVerificationFailure(PipelineError):
    def __init__(self, task_id: str, command: Sequence[str], output: str, log_path: Path):
        super().__init__(str(TaskVerificationFailed(task_id, command, output, log_path)))
        self.command = tuple(command)
        self.output = output
        self.log_path = log_path


class TaskVerificationTimeout(PipelineError):
    def __init__(self, task_id: str, command: Sequence[str], timeout_seconds: float, *, repeated: bool = False):
        super().__init__(str(TaskVerificationTimedOut(task_id, command, timeout_seconds, repeated=repeated)))
