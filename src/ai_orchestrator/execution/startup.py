"""Prepare execution inputs and retry Tasks without Run stage authority."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from ..errors import PipelineError
from ..models import RunState, RunStep, Stage, TaskStatus, WorkTask


class PrepareExecutionFiles(Protocol):
    def __call__(self, state: RunState, *, task_ids: set[str]) -> None: ...


@dataclass(frozen=True, slots=True)
class ExecutionRetryQueue:
    resume_run: bool
    message: str


@dataclass(frozen=True, slots=True)
class ExecutionStartup:
    save_state: Callable[[RunState], None]
    prepare_tasks: PrepareExecutionFiles
    validate_targets: Callable[[RunState, set[str]], None]
    validate_models: Callable[[RunState, dict[str, str], dict[str, str]], None]
    validate_effort: Callable[[RunState, dict[str, str], dict[str, str], dict[str, str]], None]
    apply_agents: Callable[[RunState, dict[str, str]], None]
    apply_models: Callable[[RunState, dict[str, str]], None]
    apply_effort: Callable[[RunState, dict[str, str]], None]
    restore_legacy: Callable[[RunState, WorkTask], None]

    def prepare_inputs(
        self, state: RunState, *, agent_overrides: dict[str, str] | None, model_overrides: dict[str, str] | None,
        reasoning_effort_overrides: dict[str, str] | None,
    ) -> None:
        incomplete_task_ids = {
            task.id
            for task in state.tasks
            if task.status in {TaskStatus.PENDING, TaskStatus.WAITING, TaskStatus.FAILED, TaskStatus.STOPPED}
            and (
                not task.branch
                or not task.worktree
                or not task.prompt_path
                or not task.log_path
                or not Path(task.prompt_path).is_file()
            )
        }
        if state.stage != Stage.PLANNED and incomplete_task_ids:
            self.prepare_tasks(state, task_ids=incomplete_task_ids)
            state.add_event("workspace", "missing replanned task execution files restored: " + ", ".join(sorted(incomplete_task_ids)))
            self.save_state(state)
        profile_override_ids = set(agent_overrides or ())
        profile_override_ids.update(model_overrides or ())
        profile_override_ids.update(reasoning_effort_overrides or ())
        self.validate_targets(state, profile_override_ids)
        if model_overrides:
            self.validate_models(state, model_overrides, agent_overrides or {})
        if reasoning_effort_overrides:
            self.validate_effort(state, reasoning_effort_overrides, agent_overrides or {}, model_overrides or {})
        if agent_overrides:
            self.apply_agents(state, agent_overrides)
        if model_overrides:
            self.apply_models(state, model_overrides)
        if reasoning_effort_overrides:
            self.apply_effort(state, reasoning_effort_overrides)

    def queue_retry(self, state: RunState, *, selected_task_ids: set[str] | None, retry_selected: bool) -> ExecutionRetryQueue | None:
        if state.stage == Stage.FAILED:
            if state.failed_step != RunStep.AGENT_EXECUTION:
                step = state.failed_step.value if state.failed_step else "unknown"
                raise PipelineError(f"this failure came from {step}, not agent execution")
            failed = [
                task
                for task in state.tasks
                if task.status in {TaskStatus.FAILED, TaskStatus.STOPPED} and (selected_task_ids is None or task.id in selected_task_ids)
            ]
            pending_after_preflight_failure = [
                task
                for task in state.tasks
                if task.status in {TaskStatus.PENDING, TaskStatus.WAITING} and (selected_task_ids is None or task.id in selected_task_ids)
            ]
            if not failed and not pending_after_preflight_failure:
                raise PipelineError("this failure did not come from agent execution")
            for task in failed:
                self.restore_legacy(state, task)
                task.status = TaskStatus.PENDING
                task.error = ""
            state.refresh_task_readiness()
            return ExecutionRetryQueue(
                True, "failed agent tasks queued for retry" if failed else "agent execution preflight failure queued for retry",
            )
        elif retry_selected and selected_task_ids is not None:
            selected = [task for task in state.tasks if task.id in selected_task_ids and task.status in {TaskStatus.FAILED, TaskStatus.STOPPED}]
            if not selected:
                raise PipelineError("selected tasks are not failed or stopped")
            for task in selected:
                self.restore_legacy(state, task)
                task.status = TaskStatus.PENDING
                task.error = ""
            state.refresh_task_readiness()
            return ExecutionRetryQueue(False, 'selected failed tasks queued for retry')
        return None
