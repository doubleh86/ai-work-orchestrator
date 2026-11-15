import subprocess
from pathlib import Path
from threading import RLock
from unittest.mock import Mock

from ai_orchestrator.execution import TaskCancellation, TaskVerificationService
from ai_orchestrator.execution_control import CancellationSignal
from ai_orchestrator.models import RunState, Stage, TaskActionResult, WorkTask


def test_one_owned_cancellation_is_reused_for_all_verification_commands(tmp_path: Path) -> None:
    (tmp_path / "logs").mkdir()
    task = WorkTask("task", "verify", ["general"], worktree=str(tmp_path), verify_commands=[["first"], ["second"]])
    task.action_results.append(TaskActionResult("verify", baseline_commit="reviewed-head"))
    state = RunState("run", "plan.md", "digest", str(tmp_path), "main", Stage.EXECUTING, tasks=[task])
    signal = Mock(spec=CancellationSignal)
    signal.is_set.return_value = False
    check = Mock()
    cancellation = Mock(return_value=TaskCancellation(signal, check))
    received = []

    def execute(command, _cwd, *, timeout_seconds, cancel_signal, environment_overrides):
        assert timeout_seconds <= 30
        assert cancel_signal is signal
        received.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, "passed")

    TaskVerificationService(
        default_total_timeout=lambda: 60, default_command_timeout=lambda: 30, dotnet_executable=lambda: "",
        state_lock=RLock(), save_state=Mock(), save_progress=Mock(), run_directory=lambda _run_id: tmp_path,
        cancellation=cancellation, ensure_clean=Mock(), ensure_head=Mock(), validate_scope=Mock(return_value=[]),
        record_progress=Mock(), refresh_style=Mock(), prepare_command=lambda command, _cwd, _diagnostic: command,
        execute_command=execute,
    ).run(state, task)

    cancellation.assert_called_once_with(state, task)
    assert check.call_count > 1
    assert received == [("first",), ("second",)]
    assert task.action_results[-1].passed_commands == [["first"], ["second"]]
