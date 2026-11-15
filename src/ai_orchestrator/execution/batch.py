"""Owned task pool lifetime and isolated completion/stop/failure recording."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, ContextManager

from ..execution_control import DispatchPaused, ExecutionStopped
from ..models import ReviewStatus, RunState, TaskAction, TaskStatus, WorkTask


@dataclass(frozen=True, slots=True)
class TaskBatchExecutor:
    max_parallel: int
    shared_workspace: Callable[[RunState], bool]
    run_task: Callable[[RunState, WorkTask, TaskAction], None]
    state_lock: ContextManager[object]
    confirm_stopped: Callable[[str, str], None]
    infer_action: Callable[[WorkTask], TaskAction]
    save_state: Callable[[RunState], None]

    def run(self, state: RunState, tasks: list[WorkTask], resume_actions: dict[str, TaskAction]) -> None:
        with ThreadPoolExecutor(max_workers=(1 if self.shared_workspace(state) else self.max_parallel)) as pool:
            futures = {pool.submit(self.run_task, state, task, resume_actions[task.id]): task for task in tasks}
            for future in as_completed(futures):
                task = futures[future]
                with self.state_lock:
                    try:
                        future.result()
                        task.status = TaskStatus.COMPLETED
                        task.error = ""
                        message = f"{task.id} completed by {task.agent_id}/{task.provider_id}"
                        if task.reviewer_agent_id:
                            message += f", reviewed by {task.reviewer_agent_id}/{task.reviewer_provider_id}"
                        state.add_event("task", message)
                    except DispatchPaused:
                        task.status = TaskStatus.PENDING
                        task.clear_progress()
                        state.add_event("task", f"{task.id} dispatch paused by stop request")
                    except ExecutionStopped as exc:
                        task.status = TaskStatus.STOPPED
                        task.error = ""
                        request_id = exc.request_id or task.stop_request_id
                        if request_id:
                            task.stop_request_id = request_id
                            self.confirm_stopped(state.id, request_id)
                        state.add_event("task", f"{task.id} stopped by user; work preserved")
                    # keep independent agents running
                    except Exception as exc:
                        failure_action = task.failed_action or self.infer_action(task)
                        task.status = TaskStatus.FAILED
                        task.failed_action = failure_action
                        if task.review_status == ReviewStatus.RUNNING:
                            task.review_status = ReviewStatus.FAILED
                        task.error = str(exc)
                        state.add_event("task", f"{task.id} failed: {exc}")
                    state.refresh_task_readiness()
                    self.save_state(state)
