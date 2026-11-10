import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock

import pytest

from ai_orchestrator.claude_credentials import claude_credential_scope, claude_environment, current_claude_api_key
from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, ProjectConfig, RoutingConfig
from ai_orchestrator.desktop_rpc import handle_request
from ai_orchestrator.execution_control import ExecutionStopped
from ai_orchestrator.pipeline import Pipeline, PipelineError, ProviderTimeoutError


def configured_pipeline(path):
    return Pipeline(Config(path=path / "config.toml", project=ProjectConfig(path), execution=ExecutionConfig(),
                           agents=(AgentConfig("worker", ("general", "planning"), ("claude", "-p"), provider_id="claude"),),
                           routing=RoutingConfig(default_provider="claude")))


def test_claude_keys_are_request_local_and_pipeline_snapshot_survives_worker_handoff(tmp_path):
    barrier = Barrier(2)
    pipelines = {}

    def dispatch(method, params):
        pipelines[params["name"]] = configured_pipeline(tmp_path / params["name"])
        barrier.wait(timeout=5)
        return {"has_key": current_claude_api_key() is not None}

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(handle_request, Mock(dispatch=dispatch), {
            "id": name, "method": "providers.status", "params": {"name": name}, "claude_api_key": key,
        }) for name, key in [("app", "fixture-app-key"), ("none", None)]]
        app, none = [future.result() for future in futures]
        assert app["result"] == {"has_key": True}
        assert none["result"] == {"has_key": False}
        with claude_credential_scope("new-key"):
            assert executor.submit(lambda: pipelines["app"]._claude_api_key).result() == "fixture-app-key"
            assert executor.submit(lambda: pipelines["none"]._claude_api_key).result() is None
    assert current_claude_api_key() is None
    assert "fixture-app-key" not in json.dumps(app)


@pytest.mark.parametrize("credential", ["", "line\nbreak", "key with space", 42, "x" * 4097])
def test_invalid_claude_credential_never_reaches_dispatch(credential):
    service = Mock()
    response = handle_request(service, {"id": 1, "method": "system.hello", "claude_api_key": credential})
    service.dispatch.assert_not_called()
    assert response["error"]["message"] == "Invalid Claude credential"
    assert current_claude_api_key() is None


def test_claude_private_key_is_redacted_from_rpc_errors():
    service = Mock(dispatch=Mock(side_effect=RuntimeError("failure with fixture-private-key")))
    response = handle_request(service, {"id": 1, "method": "system.hello", "claude_api_key": "fixture-private-key"})
    assert "fixture-private-key" not in json.dumps(response)
    assert "[REDACTED]" in response["error"]["message"]
    assert current_claude_api_key() is None


def test_explicit_app_key_overrides_conflicting_auth_only_in_child_environment():
    original = {"ANTHROPIC_API_KEY": "old-key", "ANTHROPIC_BASE_URL": "https://gateway.invalid",
                "ANTHROPIC_AUTH_TOKEN": "other-token", "CLAUDE_CODE_OAUTH_TOKEN": "oauth",
                "ANTHROPIC_CUSTOM_HEADERS": "example", "CLAUDE_CODE_USE_BEDROCK": "1", "KEEP": "value"}
    environment = claude_environment("fixture-key", original)
    assert environment == {"ANTHROPIC_API_KEY": "fixture-key", "KEEP": "value"}
    assert original["ANTHROPIC_API_KEY"] == "old-key"
    assert claude_environment(None, original) == original


def test_auth_query_and_provider_selection_use_app_key_without_exposing_it(tmp_path, monkeypatch):
    monkeypatch.setattr(Pipeline, "_resolve_executable", staticmethod(lambda _: "claude"))
    monkeypatch.setattr("ai_orchestrator.pipeline.selected_claude_executable", lambda: "")
    result = subprocess.CompletedProcess([], 0, json.dumps({"loggedIn": True, "authMethod": "api_key", "email": "old@example.test"}), "")
    execute = Mock(return_value=result)
    monkeypatch.setattr("ai_orchestrator.pipeline.subprocess.run", execute)
    with claude_credential_scope("fixture-key"):
        pipeline = configured_pipeline(tmp_path)
        status = Pipeline.claude_connection_status()
    assert status["auth_method"] == "api_key" and status["account_email"] == ""
    assert "fixture-key" not in json.dumps(status)
    assert execute.call_args.kwargs["env"]["ANTHROPIC_API_KEY"] == "fixture-key"
    assert execute.call_args.args[0] == ["claude", "auth", "status", "--json"]
    assert pipeline.provider_statuses("claude")[0].available
    assert execute.call_args.kwargs["env"]["ANTHROPIC_API_KEY"] == "fixture-key"
    execute.return_value = subprocess.CompletedProcess([], 1, json.dumps({"loggedIn": False}), "")
    with pytest.raises(PipelineError, match="Claude API 키 인증 상태"):
        pipeline._ensure_planning_provider_ready(pipeline.agents["worker"])
    execute.return_value = subprocess.CompletedProcess([], 0, json.dumps({
        "loggedIn": True, "authMethod": "claude.ai", "email": "fixture-key", "subscriptionType": "pro",
    }), "")
    with claude_credential_scope("fixture-key"):
        mismatched = Pipeline.claude_connection_status()
    assert mismatched["authenticated"] is None and mismatched["account_email"] == ""
    assert "fixture-key" not in json.dumps(mismatched)


@pytest.mark.parametrize("outcome", ["success", "failure", "timeout", "stop", "other-provider"])
def test_only_claude_process_receives_app_key_and_all_exit_paths_redact_logs(tmp_path, monkeypatch, outcome):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with claude_credential_scope("fixture-private-key"):
        pipeline = configured_pipeline(tmp_path)
    monkeypatch.setattr(pipeline, "_resolve_executable", lambda _: "claude")
    process = Mock(returncode=1 if outcome == "failure" else 0)
    process.communicate.return_value = ("done fixture-private-key", None)
    if outcome == "failure":
        process.communicate.return_value = ("invalid x-api-key fixture-private-key", None)
    if outcome == "timeout":
        process.communicate.side_effect = [subprocess.TimeoutExpired(["claude"], 1, output="fixture-private-key"), ("fixture-private-key", None)]
    spawn = Mock(return_value=process)
    monkeypatch.setattr("ai_orchestrator.pipeline.subprocess.Popen", spawn)
    monkeypatch.setattr(pipeline, "_terminate_agent_process", Mock())
    agent = pipeline.agents["worker"] if outcome != "other-provider" else AgentConfig("other", ("general",), ("example",), provider_id="custom")
    signal = Mock(request_id="stop-request") if outcome == "stop" else None
    if signal is not None:
        signal.is_set.return_value = True
    options = dict(agent=agent, command_template=agent.command, replacements={"{run_id}": "run"}, cwd=tmp_path,
                   prompt="fixture task", prompt_path="prompt.md", log_path=tmp_path / "agent.log",
                   action="execute", task_id="task", cancel_signal=signal)
    error = {"failure": PipelineError, "timeout": ProviderTimeoutError, "stop": ExecutionStopped}.get(outcome)
    if error:
        with pytest.raises(error) as failed:
            pipeline._run_provider_command(**options)
        if outcome == "failure":
            assert "Claude API 인증에 실패" in str(failed.value)
            assert "claude auth login" not in str(failed.value)
    else:
        answer = pipeline._run_provider_command(**options)
        if outcome == "success":
            assert "fixture-private-key" not in answer
    sent = spawn.call_args
    assert "fixture-private-key" not in json.dumps(sent.args[0])
    assert "fixture-private-key" not in sent.kwargs.get("cwd", tmp_path).as_posix()
    if outcome == "other-provider":
        assert "ANTHROPIC_API_KEY" not in sent.kwargs["env"]
    else:
        assert sent.kwargs["env"]["ANTHROPIC_API_KEY"] == "fixture-private-key"
        assert "fixture-private-key" not in (tmp_path / "agent.log").read_text(encoding="utf-8")
