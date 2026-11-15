from threading import RLock
from unittest.mock import Mock

from ai_orchestrator.execution import TaskBatchExecutor
from ai_orchestrator.execution_control import DispatchPaused, ExecutionStopped
from ai_orchestrator.models import ReviewStatus, RunState, Stage, TaskAction, TaskStatus, WorkTask


def test_independent_batch_results_preserve_failure_pause_stop_and_success() -> None:
    tasks = [WorkTask(name, name, ["general"], status=TaskStatus.RUNNING) for name in ["failed", "paused", "stopped", "done"]]
    tasks[0].review_status = ReviewStatus.RUNNING
    tasks[1].update_progress("preparing_task", "queued")
    state = RunState("run", "plan.md", "digest", "repo", "main", Stage.EXECUTING, tasks=tasks)
    completed = []
    stop_id = "f7aa0d92-996d-4d9f-a136-05c80c689dc9"

    def run_task(_state: RunState, task: WorkTask, action: TaskAction) -> None:
        assert action == TaskAction.EXECUTE
        if task.id == "failed":
            raise RuntimeError("review failed")
        if task.id == "paused":
            raise DispatchPaused("stop queued dispatch")
        if task.id == "stopped":
            raise ExecutionStopped("owned work stopped", request_id=stop_id)
        completed.append(task.id)

    confirm = Mock()
    save = Mock()
    TaskBatchExecutor(2, lambda _state: False, run_task, RLock(), confirm, lambda _task: TaskAction.REVIEW, save).run(
        state, tasks, {task.id: TaskAction.EXECUTE for task in tasks},
    )

    assert completed == ["done"]
    assert [task.status for task in tasks] == [TaskStatus.FAILED, TaskStatus.PENDING, TaskStatus.STOPPED, TaskStatus.COMPLETED]
    assert tasks[0].error == "review failed"
    assert tasks[0].failed_action == TaskAction.REVIEW
    assert tasks[0].review_status == ReviewStatus.FAILED
    assert tasks[1].progress_phase == ""
    assert tasks[2].error == "" and tasks[2].stop_request_id == stop_id
    confirm.assert_called_once_with(state.id, stop_id)
    assert save.call_count == len(tasks)
