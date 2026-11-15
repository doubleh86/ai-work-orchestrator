"""Record Task actions and activity with caller-owned state and locks."""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, ContextManager, Iterator, Protocol

from ..codex_sdk import CodexSdkExecutionProfile, CodexSdkProgress
from ..execution_control import CancellationSignal, DispatchPaused, ExecutionStopped
from ..models import ReviewStatus, RunState, TaskAction, TaskActionResult, TaskStatus, WorkTask, utc_now
from ..progress import advance_progress_observation


class OwnedStopSignal(CancellationSignal, Protocol):
    request_id: str


class CheckpointRecorder(Protocol):
    def __call__(self, state: RunState, request_id: str, *, task: WorkTask | None = None) -> None: ...


@dataclass(frozen=True, slots=True)
class TaskActivityRecorder:
    state_lock: ContextManager[object]
    save_state: Callable[[RunState], None]
    set_active: Callable[[RunState, WorkTask, TaskAction, str, str], None]
    clear_active: Callable[[str, str, str], None]
    stop_signal: Callable[[RunState, WorkTask], OwnedStopSignal | None]
    record_checkpoint: CheckpointRecorder

    @contextmanager
    def action(self, state: RunState, task: WorkTask, action: TaskAction, *, count_attempt: bool = True) -> Iterator[None]:
        with self.state_lock:
            if task.action_results and task.action_results[-1].status == "running":
                previous = task.action_results[-1]
                previous.status = "interrupted"
                previous.finished_at = utc_now()
                previous.error = "previous action did not finish; retry started"
            attempt_id = str(uuid.uuid4())
            invocation_id = str(uuid.uuid4())
            action_result = TaskActionResult(action=action.value, attempt_id=attempt_id, invocation_id=invocation_id)
            task.action_results.append(action_result)
            task.begin_action(action, count_attempt=count_attempt, attempt_id=attempt_id, invocation_id=invocation_id)
            try:
                self.set_active(state, task, action, attempt_id, invocation_id)
            except DispatchPaused:
                task.action_results.pop()
                task.active_action = None
                task.active_invocation_id = ""
                task.status = TaskStatus.PENDING
                raise
            state.add_event("task_action", f"{task.id} {action.value} started")
            state.refresh_task_readiness()
            self.save_state(state)
        try:
            yield
        except ExecutionStopped as exc:
            with self.state_lock:
                request_id = exc.request_id
                if not request_id:
                    signal = self.stop_signal(state, task)
                    if signal is not None and signal.is_set():
                        request_id = signal.request_id
                action_result.status = "interrupted"
                action_result.finished_at = utc_now()
                action_result.error = "사용자가 실행을 중지했습니다."
                task.stop_action(action, request_id)
                state.add_event("task_action", f"{task.id} {action.value} stopped by user")
                state.refresh_task_readiness()
                self.save_state(state)
                self.record_checkpoint(state, request_id, task=task)
            raise ExecutionStopped(str(exc), request_id=request_id) from exc
        # agent action isolation and recovery boundary
        except Exception as exc:
            with self.state_lock:
                action_result.status = "failed"
                action_result.finished_at = utc_now()
                action_result.error = str(exc)
                task.fail_action(action, str(exc))
                state.add_event("task_action", f"{task.id} {action.value} failed: {exc}")
                state.refresh_task_readiness()
                self.save_state(state)
            raise
        else:
            with self.state_lock:
                action_result.status = "succeeded"
                action_result.finished_at = utc_now()
                task.complete_action(action)
                state.add_event("task_action", f"{task.id} {action.value} completed")
                state.refresh_task_readiness()
                self.save_state(state)
        finally:
            self.clear_active(state.id, task.id, attempt_id)

    def save_progress(self, state: RunState) -> None:
        with self.state_lock:
            state.refresh_task_readiness()
            self.save_state(state)

    def record_progress(self, state: RunState, task: WorkTask, progress: CodexSdkProgress) -> None:
        with self.state_lock:
            if task.active_action is None:
                return
            received_at = progress.received_at or utc_now()
            previous_received_at = task.progress_observation.last_event_received_at if task.progress_observation else ""
            task.progress_observation = advance_progress_observation(
                task.progress_observation,
                attempt_id=progress.attempt_id or task.last_attempt_id or f"{task.id}:{task.attempt_count}:{task.active_action.value}",
                invocation_id=progress.invocation_id or f"local:{task.id}:{task.attempt_count}:{task.active_action.value}",
                turn_id=progress.turn_id,
                phase=progress.phase,
                detail=progress.detail,
                received_at=received_at,
                event_seq=progress.event_seq,
                activity_changed=progress.activity_changed,
                evidence_kind=progress.evidence_kind if progress.invocation_id else "local_phase",
            )
            task.progress_phase = progress.phase
            task.progress_detail = progress.detail
            task.progress_updated_at = received_at
            if task.progress_observation.evidence_kind != "provider_event" or previous_received_at != received_at:
                self.save_state(state)

    def record_execution_profile(self, state: RunState, task: WorkTask, profile: CodexSdkExecutionProfile) -> None:
        with self.state_lock:
            if task.active_action not in {TaskAction.EXECUTE, TaskAction.REVISE}:
                return
            if task.effective_model == profile.model and task.effective_reasoning_effort == profile.reasoning_effort:
                return
            task.set_effective_profile(profile.model, profile.reasoning_effort)
            self.save_state(state)


def infer_task_action(task: WorkTask) -> TaskAction:
    if task.active_action:
        return task.active_action
    if task.status == TaskStatus.REVIEWING:
        return TaskAction.REVIEW
    if task.status == TaskStatus.REVISING:
        return TaskAction.REVISE
    if task.review_status == ReviewStatus.CHANGES_REQUESTED:
        return TaskAction.REVISE
    if task.review_status == ReviewStatus.FAILED:
        return TaskAction.REVIEW
    return TaskAction.EXECUTE


def mark_task_interrupted(task: WorkTask) -> None:
    action = task.active_action or infer_task_action(task)
    message = f"{action.value} was interrupted before completion"
    task.fail_action(action, message)
    task.status = TaskStatus.FAILED
    if task.review_status == ReviewStatus.RUNNING:
        task.review_status = ReviewStatus.FAILED


def collect_interrupted_tasks(state: RunState) -> list[WorkTask]:
    interrupted: list[WorkTask] = []
    for task in state.tasks:
        if task.active_action or task.status in {TaskStatus.RUNNING, TaskStatus.REVIEWING, TaskStatus.REVISING}:
            mark_task_interrupted(task)
            state.add_event("task", f"{task.id} interrupted action collected")
            interrupted.append(task)
    return interrupted
