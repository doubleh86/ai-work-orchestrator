from __future__ import annotations

import subprocess
import tempfile
import tomllib
from unittest.mock import Mock

import pytest

from ai_orchestrator.execution.verification_sandbox import VerificationSandbox
from ai_orchestrator.git import GitError


def test_verification_launches_in_an_app_owned_profile(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = repo / "task"
    worktree.mkdir()
    state = repo / ".ai-orchestrator"
    cli = tmp_path / "codex.exe"
    cli.touch()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr("ai_orchestrator.execution.verification_sandbox.installed_codex_executable", lambda: str(cli))
    monkeypatch.setenv("GITHUB_TOKEN", "fixture-value")
    result = subprocess.CompletedProcess([], 0, "Python fixture", "")
    launch = Mock(return_value=result)
    monkeypatch.setattr("ai_orchestrator.execution.verification_sandbox.run_command", launch)

    assert VerificationSandbox(repo, state).execute(
        ["python", "--version"], worktree, timeout_seconds=5, cancel_signal=None,
        environment_overrides={"UNRELATED_VAR": "fixture", "MSBUILDUSESERVER": "0"},
    ) is result
    command, launcher_cwd = launch.call_args.args
    assert command[:3] == [str(cli), "sandbox", "-P"]
    assert command[command.index("--") + 1:] == ["python", "--version"]
    assert not launcher_cwd.is_relative_to(repo)
    profile = command[3]
    policy = tomllib.loads(command[5])["permissions"][profile]
    assert policy["network"] == {"enabled": False}
    assert policy["filesystem"][str(worktree)] == "write"
    assert policy["filesystem"][str(state)] == "deny"
    assert policy["filesystem"][":root"] == "deny"
    environment = launch.call_args.kwargs["base_environment"]
    assert environment["MSBUILDUSESERVER"] == "0"
    assert {"GITHUB_TOKEN", "UNRELATED_VAR"}.isdisjoint(environment)
    assert not launcher_cwd.exists()


def test_repository_owned_launcher_is_rejected_before_escaping_the_sandbox(tmp_path, monkeypatch):
    cli = tmp_path / "codex.exe"
    cli.touch()
    monkeypatch.setattr("ai_orchestrator.execution.verification_sandbox.installed_codex_executable", lambda: str(cli))
    launch = Mock()
    monkeypatch.setattr("ai_orchestrator.execution.verification_sandbox.run_command", launch)

    with pytest.raises(GitError, match="검증 격리 실행 파일"):
        VerificationSandbox(tmp_path, tmp_path / "state").execute(
            ["python", "--version"], tmp_path, timeout_seconds=5, cancel_signal=None,
        )
    launch.assert_not_called()
