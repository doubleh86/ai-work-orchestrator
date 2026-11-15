from pathlib import Path
import subprocess
from threading import Event
from unittest.mock import Mock

import pytest

from ai_orchestrator.execution import TaskVerificationRunner, TaskVerificationRuntimeOptions


def test_standalone_task_verification_keeps_preparation_budget_and_dotnet_environment_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    clock = [0.0]
    monkeypatch.setattr("ai_orchestrator.execution.task_verification.time.monotonic", lambda: clock[0])
    commands = (("dotnet", "test"), ("npm", "test"))
    signal = Event()
    calls = []
    progress = Mock()
    prepared = Mock(return_value=False)
    failure = Mock()
    passed = []
    log = tmp_path / "task-verify.log"
    attempt_log = tmp_path / "task-verify-attempt.log"

    def prepare(command, _cwd, diagnostic):
        if command[0] == "dotnet":
            clock[0] += 5
            diagnostic("SDK ready")
            return ("/runtime/dotnet", *command[1:])
        return command

    def execute(command, cwd, *, timeout_seconds, cancel_signal, environment_overrides=None):
        assert cwd == tmp_path and cancel_signal is signal
        calls.append((tuple(command), timeout_seconds, environment_overrides))
        clock[0] += 5
        return subprocess.CompletedProcess(command, 0, "verified")

    def record_passed(command):
        assert "exit code: 0" in log.read_text(encoding="utf-8")
        passed.append(command)

    runner = TaskVerificationRunner(
        TaskVerificationRuntimeOptions("task", tmp_path, log, attempt_log, 100, 30, 30, (("MSBUILDUSESERVER", "0"),)),
        execute_command=execute, prepare_command=prepare, check_stopped=Mock(), timestamp=lambda: "timestamp",
        progress_callback=progress, prepared_callback=prepared, failure_callback=failure, passed_callback=record_passed,
    )
    runner.run(commands, cancel_signal=signal)
    assert calls == [(("/runtime/dotnet", "test"), 25, {"MSBUILDUSESERVER": "0"}), (commands[1], 20, None)]
    assert passed == list(commands)
    assert prepared.call_args_list[0].args == (commands[0], ("/runtime/dotnet", "test"), {"MSBUILDUSESERVER": "0"})
    assert [call.args[0] for call in progress.call_args_list] == [
        "preparing_verification", "verifying_command", "checking_verification_result",
        "preparing_verification", "verifying_command", "checking_verification_result",
    ]
    assert "SDK ready" in log.read_text(encoding="utf-8") and not attempt_log.exists()
    failure.assert_not_called()
