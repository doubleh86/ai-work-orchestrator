import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_orchestrator import provider_executable
from ai_orchestrator.config import AgentConfig
from ai_orchestrator.pipeline import Pipeline


def test_missing_cli_status_never_launches_authentication() -> None:
    with patch.object(Pipeline, "_resolve_executable", return_value=None), patch.object(Pipeline, "_claude_auth_status") as auth, patch(
        "ai_orchestrator.pipeline.selected_claude_executable", return_value=""
    ):
        status = Pipeline.claude_connection_status()
    assert status == {"installed": False, "authenticated": False, "auth_method": "none", "message": "Claude CLI 설치 필요",
                      "account_email": "", "plan_type": "", "selected_executable": ""}
    auth.assert_not_called()


@pytest.mark.skipif(os.name == "nt", reason="Claude user install fallback is POSIX only")
def test_user_installed_cli_is_reported_when_desktop_path_omits_it(tmp_path: Path) -> None:
    with patch.object(provider_executable, "_claude_settings_path", return_value=tmp_path / "selection.json"):
        launcher = tmp_path / ".local" / "bin" / "claude"
        launcher.parent.mkdir(parents=True)
        launcher.write_text("fixture", encoding="utf-8")
        launcher.chmod(0o755)
        result = subprocess.CompletedProcess([], 0, json.dumps({"loggedIn": True, "authMethod": "claude.ai"}), "")
        with patch("ai_orchestrator.provider_executable.Path.home", return_value=tmp_path), patch(
            "ai_orchestrator.provider_executable.shutil.which", return_value=None
        ), patch("ai_orchestrator.pipeline.subprocess.run", return_value=result) as execute:
            status = Pipeline.claude_connection_status()
        assert status["installed"] is True
        assert status["authenticated"] is True
        assert status["selected_executable"] == ""
        assert execute.call_args.args[0] == [str(launcher), "auth", "status", "--json"]


def test_missing_selected_cli_reports_selected_path_without_falling_back(tmp_path: Path) -> None:
    selected = str(tmp_path / "missing" / "claude")
    with patch("ai_orchestrator.pipeline.selected_claude_executable", return_value=selected), patch.object(
        Pipeline, "_resolve_executable", return_value=""
    ):
        status = Pipeline.claude_connection_status()
    assert status["installed"] is False
    assert status["selected_executable"] == selected
    assert "선택한" in status["message"]


@pytest.mark.parametrize("code, payload, expected", [
    (0, {"loggedIn": True, "authMethod": "oauth_token", "subscriptionType": "max"}, (True, "claude_subscription")),
    (1, {"loggedIn": True, "authMethod": "oauth_token"}, (None, "error")),
    (1, {"loggedIn": False}, (False, "none")),
    (0, [], (None, "error")),
])
def test_cli_status_returns_only_sanitized_connection_information(code: int, payload: object, expected: tuple) -> None:
    if isinstance(payload, dict):
        payload = {**payload, "email": "private@example.test", "token": "private-token", "organization": "private-org"}
    result = subprocess.CompletedProcess([], code, json.dumps(payload), "private-stderr")
    with patch.object(Pipeline, "_resolve_executable", return_value="claude"), patch("ai_orchestrator.pipeline.subprocess.run", return_value=result) as execute:
        status = Pipeline.claude_connection_status()
    assert status["installed"] is True
    assert (status["authenticated"], status["auth_method"]) == expected
    assert set(status) == {"installed", "authenticated", "auth_method", "message", "account_email", "plan_type", "selected_executable"}
    assert status["account_email"] == ("private@example.test" if expected[0] is True else "")
    assert status["plan_type"] == ("max" if expected[0] is True else "")
    assert "private-token" not in json.dumps(status)
    assert "private-org" not in json.dumps(status)
    assert execute.call_args.args[0] == ["claude", "auth", "status", "--json"]
    assert execute.call_count == 1


@pytest.mark.parametrize("fields, email, plan", [
    ({"email": " account@example.test ", "subscriptionType": " Pro "}, "account@example.test", "pro"),
    ({}, "", ""),
    ({"email": {"unexpected": "object"}, "subscriptionType": 123}, "", ""),
    ({"email": "line\nbreak@example.test", "subscriptionType": "unrecognized"}, "", ""),
    ({"email": "a" * 321}, "", ""),
])
def test_connection_returns_only_supported_account_details(fields: dict, email: str, plan: str) -> None:
    payload = {"loggedIn": True, "authMethod": "claude.ai", **fields, "accessToken": "secret-access", "refreshToken": "secret-refresh"}
    result = subprocess.CompletedProcess([], 0, json.dumps(payload), "secret-stderr")
    with patch.object(Pipeline, "_resolve_executable", return_value="claude"), patch("ai_orchestrator.pipeline.subprocess.run", return_value=result):
        status = Pipeline.claude_connection_status()
    assert status["authenticated"] is True
    assert status["account_email"] == email
    assert status["plan_type"] == plan
    assert "secret" not in json.dumps(status)


@pytest.mark.parametrize("method", ["api_key", "third_party", "external"])
def test_other_authentication_does_not_display_a_previous_subscription_account(method: str) -> None:
    payload = {"loggedIn": True, "authMethod": method, "email": "old@example.test", "subscriptionType": "pro"}
    result = subprocess.CompletedProcess([], 0, json.dumps(payload), "")
    with patch.object(Pipeline, "_resolve_executable", return_value="claude"), patch("ai_orchestrator.pipeline.subprocess.run", return_value=result):
        status = Pipeline.claude_connection_status()
    assert status["authenticated"] is True
    assert status["account_email"] == ""
    assert status["plan_type"] == ""


def test_status_timeout_is_unknown_and_does_not_retry_or_login() -> None:
    with patch.object(Pipeline, "_resolve_executable", return_value="claude"), patch("ai_orchestrator.pipeline.subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 5)) as execute:
        status = Pipeline.claude_connection_status()
    assert status["authenticated"] is None
    assert status["auth_method"] == "error"
    assert execute.call_count == 1


@pytest.mark.parametrize("output", [
    "Not logged in · Please run /login",
    "NOT LOGGED IN · Please run /login",
    "Error: Not logged in. Please run /login",
    "\n  Not logged in · Please run /login\n",
])
def test_logged_out_cli_errors_point_to_login_without_reproducing_provider_output(output: str) -> None:
    agent = AgentConfig("claude-general", ("planning",), ("claude", "-p"), provider_id="claude")
    message = Pipeline._provider_command_failure_message(agent, 1, output, Path("planning-chat.log"))
    assert "Claude 로그인이 필요합니다." in message
    assert "AI 연결" in message
    assert "연결을 다시 확인" in message
    assert "see planning-chat.log" in message
    assert "exited with" not in message
    assert "Please run /login" not in message


@pytest.mark.parametrize("provider, output", [
    ("custom", "Not logged in · Please run /login"),
    ("claude", "Test failure: expected Not logged in but got ready"),
    ("claude", "Unknown model selected"),
])
def test_other_exit_errors_do_not_claim_claude_is_logged_out(provider: str, output: str) -> None:
    agent = AgentConfig("example", ("planning",), ("example",), provider_id=provider)
    message = Pipeline._provider_command_failure_message(agent, 1, output, Path("provider.log"))
    assert message == "agent example exited with 1; see provider.log"
