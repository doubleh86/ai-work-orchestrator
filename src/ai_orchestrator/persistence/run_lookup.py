"""Resolve Run/Task identities with the original failure contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..errors import PipelineError
from ..models import RunState, Stage, WorkTask


def find_task(state: RunState, task_id: str) -> WorkTask:
    for task in state.tasks:
        if task.id == task_id:
            return task
    raise PipelineError(f"unknown task: {task_id}")


@dataclass(frozen=True, slots=True)
class RunLookup:
    load_state: Callable[[str], RunState]
    state_path: Callable[[str], Path]

    def at(self, run_id: str, allowed: set[Stage]) -> RunState:
        state = self.load_state(run_id)
        if state.archive is not None:
            raise PipelineError("보관된 작업 그룹은 읽기 전용입니다.")
        if state.stage not in allowed:
            expected = ", ".join(sorted(value.value for value in allowed))
            raise PipelineError(f"run {run_id} is at '{state.stage.value}', expected one of: {expected}")
        return state


    def require_known(self, run_id: str) -> None:
        if not self.state_path(run_id).exists():
            raise ValueError(f"unknown run: {run_id}")
