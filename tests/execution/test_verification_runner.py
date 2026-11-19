from __future__ import annotations

import subprocess
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest

from ai_orchestrator.config import Config, ExecutionConfig, ProjectConfig
from ai_orchestrator.execution import VerificationRunError, VerificationRunner, VerificationRuntimeOptions
from ai_orchestrator.execution_control import ExecutionStopped
from ai_orchestrator.git import GitError
from ai_orchestrator.models import RunState, Stage, VerificationAttempt
from ai_orchestrator.pipeline import Pipeline, PipelineError


def test_standalone_verification_shares_budget_and_collects_logs_before_recording_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    clock = [0.0]
    monkeypatch.setattr("ai_orchestrator.execution.verification_runner.time.monotonic", lambda: clock[0])
    commands = (("npm", "run", "test"), ("dotnet", "test"), ("git", "diff", "--check"))
    calls = []
    progress = Mock()
    passed = []
    heads = []
    signal = Event()
    log = tmp_path / "verify-attempt-1.log"

    def execute(command, cwd, *, timeout_seconds, cancel_signal, environment_overrides=None):
        assert cwd == tmp_path and cancel_signal is signal
        calls.append((tuple(command), timeout_seconds, environment_overrides))
        clock[0] += 20
        return subprocess.CompletedProcess(command, 0, "완료", "진단")

    def prepare(command, _cwd, diagnostic):
        if command[0] == "dotnet":
            clock[0] += 5
            diagnostic("SDK 준비")
        return command

    def record_passed(command):
        assert heads[-1] == len(calls)
        assert "완료" in log.read_text(encoding="utf-8")
        passed.append(command)

    options = VerificationRuntimeOptions(tmp_path, log, 100, 120, 15, elapsed_preparation_seconds=10)
    runner = VerificationRunner(
        options, execute_command=execute, prepare_command=prepare, check_stopped=Mock(),
        ensure_head=lambda: heads.append(len(calls)), progress_callback=progress, passed_callback=record_passed,
    )
    runner.run(commands, cancel_signal=signal)
    assert [call[0] for call in calls] == [("npm", "ci"), *commands]
    assert [call[1] for call in calls] == [90, 70, 50, 15]
    assert [call[2] for call in calls] == [None, None, {
        "DOTNET_CLI_USE_MSBUILD_SERVER": "0", "MSBUILDUSESERVER": "0", "MSBUILDDISABLENODEREUSE": "1",
    }, None]
    assert passed == list(commands) and heads == [1, 2, 3, 4]
    assert progress.call_args_list[0].args == ("preparing_dependencies", ("npm", "ci"), 0, 3)
    assert progress.call_args_list[-1].args == ("running_command", commands[-1], 3, 3)
    assert log.read_bytes() == (tmp_path / "verify.log").read_bytes()
    assert "SDK 준비" in log.read_text(encoding="utf-8") and "진단" in log.read_text(encoding="utf-8")


def test_standalone_verification_stops_before_next_command_when_total_budget_is_spent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    clock = [0.0]
    monkeypatch.setattr("ai_orchestrator.execution.verification_runner.time.monotonic", lambda: clock[0])

    def execute(command, *_args, **_kwargs):
        clock[0] = 11
        return subprocess.CompletedProcess(command, 0, "passed")

    execute_command = Mock(side_effect=execute)
    passed = Mock()
    runner = VerificationRunner(
        VerificationRuntimeOptions(tmp_path, tmp_path / "verify.log", 10, 10, 5), execute_command=execute_command,
        prepare_command=lambda command, *_: command, check_stopped=Mock(), ensure_head=None,
        progress_callback=Mock(), passed_callback=passed,
    )
    with pytest.raises(VerificationRunError, match="전체 제한시간") as caught:
        runner.run((("first",), ("second",)))
    assert execute_command.call_count == 1 and not caught.value.phase
    passed.assert_called_once_with(("first",))


@pytest.mark.parametrize("boundary", ["stop", "head"])
def test_standalone_verification_propagates_stop_and_head_failure_without_recording_a_pass(tmp_path: Path, boundary: str):
    error = ExecutionStopped("중지", request_id="stop-id") if boundary == "stop" else RuntimeError("HEAD changed")
    signal = Event()
    passed = Mock()

    def execute(command, *_args, **_kwargs):
        signal.set()
        return subprocess.CompletedProcess(command, 0, "passed")

    def check():
        if signal.is_set():
            raise error

    runner = VerificationRunner(
        VerificationRuntimeOptions(tmp_path, tmp_path / "verify.log", 10, 10, 5), execute_command=execute,
        prepare_command=lambda command, *_: command, check_stopped=check if boundary == "stop" else Mock(),
        ensure_head=check, progress_callback=Mock(), passed_callback=passed,
    )
    with pytest.raises(type(error)) as caught:
        runner.run((("first",), ("second",)), cancel_signal=signal)
    assert caught.value is error
    passed.assert_not_called()


@pytest.mark.parametrize(("failure", "phase"), [
    ("command_error", "command_execution"), ("prepare_error", "command_environment"),
    ("command_exit", "verification_command"), ("restore_error", "dependency_restore"), ("restore_exit", "dependency_restore"),
])
def test_facade_preserves_failure_evidence_and_original_adapter_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str, phase: str):
    monkeypatch.setattr("ai_orchestrator.pipeline_bootstrap.current_claude_api_key", lambda: "")
    monkeypatch.setattr("ai_orchestrator.pipeline_bootstrap.current_nvidia_api_key", lambda: "")
    monkeypatch.setattr("ai_orchestrator.pipeline_bootstrap.current_nvidia_model_keys", lambda: {})
    pipeline = Pipeline(Config(tmp_path / "config.toml", ProjectConfig(tmp_path), ExecutionConfig(), ()))
    state = RunState("failure", "", "", str(tmp_path), "main", stage=Stage.READY_TO_MERGE,
                     verification_attempts=[VerificationAttempt()])
    command = ("npm", "run", "test") if failure.startswith("restore") else ("python", "check.py")
    if failure.startswith("restore"):
        (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    source_error = PipelineError("SDK 환경 오류") if failure == "prepare_error" else GitError("command timed out after 600 seconds")
    if failure == "prepare_error":
        monkeypatch.setattr(pipeline._common_runtime.execution.verification_commands, 'prepare_verification_command', Mock(side_effect=source_error))
    execute = Mock(side_effect=source_error) if failure.endswith("error") else Mock(return_value=subprocess.CompletedProcess([], 1, "실패"))
    monkeypatch.setattr("ai_orchestrator.execution.verification_sandbox.VerificationSandbox.execute", execute)
    with pytest.raises(PipelineError) as caught:
        pipeline._common_runtime.execution.verification.run_verification_commands(state, tmp_path, (command,))
    if failure == "prepare_error":
        assert caught.value is source_error
        execute.assert_not_called()
    elif failure.endswith("error"):
        assert caught.value.__cause__ is source_error
    saved = pipeline.store.load(state.id).verification_attempts[-1]
    expected_command = ["npm", "ci"] if failure.startswith("restore") else list(command)
    assert saved.failure_phase == phase and saved.failed_command == expected_command
    assert saved.passed_commands == [] and saved.current_command == expected_command
    if failure != "prepare_error":
        expected_output = "command timed out" if failure.endswith("error") else "실패"
        assert expected_output in Path(saved.log_path).read_text(encoding="utf-8")
