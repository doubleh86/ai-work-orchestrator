import json
import os
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, ProjectConfig, create_default_config, load_config
from ai_orchestrator.codex_sdk import CodexSdkError, CodexSdkManager
from ai_orchestrator.desktop_rpc import DesktopApplication, RpcService, handle_request
from ai_orchestrator.execution_control import ExecutionStopped
from ai_orchestrator.pipeline import Pipeline, PipelineError
from ai_orchestrator.registry import ProjectRegistry, RegistryError
from ai_orchestrator.worker_mcp import (
    WorkerMcpError, WorkerMcpServer, check_mcp_connection, claude_mcp_options, codex_mcp_config,
    configure_claude_mcp, parse_mcp_servers, worker_mcp_lease,
)
from test_codex_sdk import FakeClientFactory, FakeCodex, FakeTurnHandle, request


def server(**kwargs):
    return WorkerMcpServer.from_dict({"id": "tool", "url": "http://localhost:8080/mcp", **kwargs})


@pytest.fixture(autouse=True)
def isolated_mcp_user(tmp_path, monkeypatch):
    monkeypatch.setattr("ai_orchestrator.worker_mcp.application_config_root", lambda: tmp_path / "mcp-user")


@pytest.mark.parametrize("raw", [
    {"mcpServers": {"unity": {"url": "http://localhost:8080/mcp"}}},
    {"mcp_servers": {"unity": {"url": "http://localhost:8080/mcp", "type": "streamable-http"}}},
    {"mcpServers": {"unity": {"url": "https://example.com/mcp?project_ref=example&read_only=true"}}},
    [{"id": "unity", "transport": "http", "url": "http://localhost:8080/mcp"}],
])
def test_standard_and_saved_mcp_formats_round_trip_without_vendor_special_cases(raw):
    parsed = parse_mcp_servers(raw)
    assert parsed[0].id == "unity" and parsed[0].transport == "http"
    assert parse_mcp_servers([item.to_dict() for item in parsed]) == parsed


@pytest.mark.parametrize("raw", [
    {"id": "bad name", "url": "https://example.com/mcp"},
    {"id": "tool", "url": "https://user:password@example.com/mcp"},
    {"id": "tool", "url": "https://example.com/mcp?token=private-value"},
    {"id": "tool", "url": "https://example.com/mcp", "headers": {"Authorization": "Bearer private-value"}},
    {"id": "tool", "command": "fixture", "env": {"TOKEN": "private-value"}},
    {"id": "tool", "url": "https://example.com/mcp", "type": "sse"},
    {"id": "tool", "command": "fixture", "args": ["--api-key", "private-value"]},
    {"id": "tool", "url": "http://[invalid-ipv6/mcp"},
    {"id": "tool", "url": "https://example.com/mcp", "bearer_token_env_var": "ANTHROPIC_API_KEY"},
    {"id": "tool", "url": "https://example.com/mcp", "env_http_headers": {"Authorization": 1}},
    {"id": "tool", "url": "https://example.com/mcp", "transport": []},
    {"id": "tool", "url": "https://example.com/mcp", "env_http_headers": {"X-Token": "ONE", "x-token": "TWO"}},
])
def test_invalid_connections_and_literal_credentials_are_rejected_without_echoing_values(raw):
    with pytest.raises(WorkerMcpError) as error:
        WorkerMcpServer.from_dict(raw)
    assert "private-value" not in str(error.value) and "password" not in str(error.value)


def test_environment_references_are_adapted_without_changing_the_source_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("FIXTURE_MCP_TOKEN", "fixture-token-value")
    selected = server(headers={"Authorization": "Bearer ${FIXTURE_MCP_TOKEN}"})
    assert "fixture-token-value" not in json.dumps(selected.to_dict())
    native = codex_mcp_config((selected,), tmp_path, tmp_path)["mcp_servers"]["tool"]
    assert native["required"] and native["http_headers"] == {"Authorization": "Bearer fixture-token-value"}
    command = ["claude", "-p", "--allowedTools", "Read,Write", "--disallowedTools", "Bash(git push:*)"]
    injected = configure_claude_mcp(command, (selected,), tmp_path, tmp_path)
    assert command[command.index("--allowedTools") + 1] == "Read,Write,mcp__tool__*"
    assert "Bash(git push:*)" in command and "--strict-mcp-config" in command
    assert "fixture-token-value" not in json.dumps(command) and "fixture-token-value" in injected.values()
    monkeypatch.delenv("FIXTURE_MCP_TOKEN")
    with pytest.raises(WorkerMcpError, match="FIXTURE_MCP_TOKEN"):
        codex_mcp_config((selected,), tmp_path, tmp_path)


def test_workspace_substitution_and_provider_permission_limits_are_explicit(tmp_path):
    selected = WorkerMcpServer.from_dict({"id": "local", "command": "fixture", "args": ["{worktree}", "{project_root}"]})
    config = codex_mcp_config((selected,), tmp_path / "work", tmp_path)["mcp_servers"]["local"]
    assert config["cwd"] == str(tmp_path / "work") and config["args"] == [str(tmp_path / "work"), str(tmp_path)]
    with pytest.raises(WorkerMcpError, match="이미"):
        configure_claude_mcp(["claude", "--mcp-config", "existing.json"], (selected,), tmp_path, tmp_path)
    with pytest.raises(WorkerMcpError, match="허용 목록"):
        claude_mcp_options((server(enabled_tools=["read"]),), tmp_path, tmp_path)


@pytest.fixture
def application(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    config = create_default_config(repo / "orchestrator.toml", repo)
    registry = ProjectRegistry(tmp_path / "registry.json")
    registry.add("project", repo, config)
    app = DesktopApplication(registry)
    yield app
    app.close()


@pytest.mark.parametrize("version", [1, 2, 3])
def test_old_registry_defaults_and_revisioned_settings_preserve_other_project_data(application, version):
    registry = application.registry
    original = registry.get("project")
    path = registry.path
    raw = json.loads(path.read_text())
    raw["schema_version"] = version
    for key in ("worker_mcp_servers", "worker_mcp_revision"):
        raw["projects"][0].pop(key)
    path.write_text(json.dumps(raw))
    assert registry.get("project").worker_mcp_servers is None
    updated = registry.update_worker_mcp_servers("project", (server(),), expected_revision=0)
    assert updated.worker_mcp_revision == 1 and updated.repo == original.repo
    assert updated.config_path == original.config_path and updated.created_at == original.created_at
    assert json.loads(path.read_text())["schema_version"] == 4
    with pytest.raises(RegistryError, match="변경"):
        registry.update_worker_mcp_servers("project", (), expected_revision=0)
    registry.update_worker_mcp_servers("project", (), expected_revision=1)
    assert registry.get("project").worker_mcp_servers == ()


def test_rpc_requires_approval_and_fresh_revision_and_append_preserves_existing_connections(application, monkeypatch):
    rpc = RpcService(application)
    params = {"projectName": "project", "servers": [server().to_dict()], "expectedRevision": 0}
    reply = handle_request(rpc, {"id": 1, "method": "projects.updateWorkerMcp", "params": params})
    assert "error" in reply and application.registry.get("project").worker_mcp_revision == 0
    reply = handle_request(rpc, {"id": 2, "method": "projects.updateWorkerMcp", "params": {**params, "approved": True}})
    assert reply["result"]["revision"] == 1
    application.update_worker_mcp_connections("project", [server(id="other").to_dict()], expected_revision=1, approved=True, append=True)
    assert {item["id"] for item in application.worker_mcp_connections("project")["servers"]} == {"tool", "other"}
    monkeypatch.setattr("ai_orchestrator.desktop_rpc.check_mcp_connection", Mock(return_value={"status": "connected"}))
    with pytest.raises(Exception, match="변경"):
        application.check_worker_mcp_connection("project", "tool", expected_revision=1)
    pipeline = application._pipeline("project")
    application.update_worker_mcp_connections("project", [], expected_revision=2, approved=True)
    assert len(pipeline.config.worker_mcp_servers) == 2
    assert application._pipeline("project").config.worker_mcp_servers == ()


def test_toml_tool_settings_are_used_until_registry_explicitly_overrides_them(application):
    project = application.registry.get("project")
    with project.config_path.open("a") as stream:
        stream.write('\n[mcp_servers.docs]\nurl = "https://example.com/mcp"\n')
    assert load_config(project.config_path).worker_mcp_servers[0].id == "docs"
    assert application.worker_mcp_connections("project")["servers"][0]["id"] == "docs"
    application.update_worker_mcp_connections("project", [], expected_revision=0, approved=True)
    assert application.worker_mcp_connections("project")["servers"] == []


def test_cli_uses_project_tool_overrides_only_with_an_explicit_registry(application, monkeypatch):
    from ai_orchestrator.cli import main

    selected = server()
    application.registry.update_worker_mcp_servers("project", (selected,), expected_revision=0)
    constructor = Mock()
    constructor.return_value.list_statuses.return_value = []
    monkeypatch.setattr("ai_orchestrator.cli.Pipeline", constructor)
    monkeypatch.setattr("ai_orchestrator.cli.CodexSdkManager", Mock())
    monkeypatch.setattr("ai_orchestrator.cli.current_claude_api_key", lambda: "")
    args = ["--config", str(application.registry.get("project").config_path), "status"]
    assert main(args) == 0
    assert constructor.call_args.args[0].worker_mcp_servers == ()
    assert main(["--registry", str(application.registry.path), *args]) == 0
    assert constructor.call_args.args[0].worker_mcp_servers == (selected,)


def test_manual_probe_does_not_interrupt_a_tool_in_use_or_report_a_changed_configuration_as_connected(application, monkeypatch):
    selected = server()
    application.update_worker_mcp_connections("project", [selected.to_dict()], expected_revision=0, approved=True)
    probe = Mock(return_value={"status": "connected"})
    monkeypatch.setattr("ai_orchestrator.desktop_rpc.check_mcp_connection", probe)
    with worker_mcp_lease((selected,)):
        result = application.check_worker_mcp_connection("project", selected.id, expected_revision=1)
    assert result["status"] == "error" and "사용 중" in result["message"]
    probe.assert_not_called()

    def changed(*args):
        application.registry.update_worker_mcp_servers("project", (), expected_revision=1)
        return {"status": "connected"}

    probe.side_effect = changed
    with pytest.raises(Exception, match="변경"):
        application.check_worker_mcp_connection("project", selected.id, expected_revision=1)


def test_codex_scopes_tools_to_one_thread_and_closes_the_client_before_reuse(tmp_path):
    first, second = FakeCodex(), FakeCodex()
    manager = CodexSdkManager(client_factory=FakeClientFactory([first, second]))
    selected = server()
    try:
        assert manager.run_turn(replace(request(tmp_path), mcp_servers=(selected,))) == "structured plan"
        assert first.close_count == 1
        assert first.thread_start_calls[0]["config"]["mcp_servers"]["tool"]["required"]
        assert manager.run_turn(request(tmp_path)) == "structured plan"
        assert "config" not in second.thread_start_calls[0]
        with pytest.raises(CodexSdkError, match="새 작업"):
            manager.run_turn(replace(request(tmp_path, conversation_id="chat"), mcp_servers=(selected,)))
    finally:
        manager.close()


def test_codex_mcp_error_and_logs_do_not_leak_environment_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("FIXTURE_MCP_TOKEN", "fixture-sensitive-token")
    client = FakeCodex()
    failed = RuntimeError("connection refused for fixture-sensitive-token")
    failed.data = {"fixture-sensitive-token": "failed"}
    client.thread_start = Mock(side_effect=failed)
    success = FakeCodex(FakeTurnHandle(response="done fixture-sensitive-token"))
    manager = CodexSdkManager(client_factory=FakeClientFactory([client, success]))
    try:
        with pytest.raises(CodexSdkError) as error:
            manager.run_turn(replace(request(tmp_path), mcp_servers=(server(bearer_token_env_var="FIXTURE_MCP_TOKEN"),)))
        assert "fixture-sensitive-token" not in str(error.value)
        assert "fixture-sensitive-token" not in (tmp_path / "planning.log").read_text()
        assert client.close_count == 1
        response = manager.run_turn(replace(request(tmp_path), mcp_servers=(server(bearer_token_env_var="FIXTURE_MCP_TOKEN"),)))
        assert response == "done [REDACTED]"
        assert "fixture-sensitive-token" not in (tmp_path / "planning.log").read_text()
    finally:
        manager.close()


def test_pipeline_propagates_tools_only_to_worker_calls_and_redacts_claude_output(tmp_path, monkeypatch):
    monkeypatch.setattr("ai_orchestrator.worker_mcp.application_config_root", lambda: tmp_path / "user")
    monkeypatch.setenv("FIXTURE_MCP_TOKEN", "fixture-sensitive-token")
    selected = server(bearer_token_env_var="FIXTURE_MCP_TOKEN")
    agent = AgentConfig("worker", ("general",), ("claude", "-p", "--allowedTools", "Read,Write"), provider_id="claude", model="sonnet")
    pipeline = Pipeline(Config(tmp_path / "cfg.toml", ProjectConfig(tmp_path), ExecutionConfig(), (agent,), worker_mcp_servers=(selected,)))
    monkeypatch.setattr(pipeline, "_resolve_executable", lambda command: command)
    monkeypatch.setattr("ai_orchestrator.pipeline.check_mcp_connection", lambda *args: {"status": "connected"})
    process = Mock(returncode=0)
    process.communicate.return_value = ("done fixture-sensitive-token", None)
    spawn = Mock(return_value=process)
    monkeypatch.setattr("ai_orchestrator.pipeline.subprocess.Popen", spawn)
    values = dict(agent=agent, command_template=agent.command, replacements={"{run_id}": "run"}, cwd=tmp_path,
                  prompt="implement", prompt_path="prompt", log_path=tmp_path / "worker.log", action="execute", task_id="task")
    assert pipeline._invoke_provider_command(**values) == "done [REDACTED]"
    assert "--strict-mcp-config" in spawn.call_args.args[0]
    assert "fixture-sensitive-token" not in json.dumps(spawn.call_args.args[0])
    assert "fixture-sensitive-token" not in values["log_path"].read_text()
    sdk = Mock()
    sdk.run_turn.return_value = "done"
    codex = replace(agent, command=(), provider_id="codex")
    pipeline._codex_sdk = sdk
    pipeline._invoke_provider_command(**{**values, "agent": codex})
    assert sdk.run_turn.call_args.args[0].mcp_servers == (selected,)
    pipeline._invoke_provider_command(**{**values, "agent": codex, "action": "review"})
    assert sdk.run_turn.call_args.args[0].mcp_servers == ()
    monkeypatch.setattr("ai_orchestrator.pipeline.check_mcp_connection", lambda *args: {"status": "error", "message": "도구 연결 실패"})
    with pytest.raises(PipelineError, match="도구 연결 실패"):
        pipeline._invoke_provider_command(**values)
    queued, updates, results, failures = threading.Event(), [], [], []
    sdk.run_turn.reset_mock()

    def report(progress):
        updates.append(progress)
        if progress.phase == "waiting_for_tool":
            queued.set()

    def execute_when_ready():
        try:
            results.append(pipeline._invoke_provider_command(
                **{**values, "agent": codex}, progress_callback=report, invocation_id="invocation",
            ))
        except Exception as exc:
            failures.append(exc)

    with worker_mcp_lease((selected,)):
        worker = threading.Thread(target=execute_when_ready)
        worker.start()
        assert queued.wait(2)
        sdk.run_turn.assert_not_called()
    worker.join(3)
    assert not worker.is_alive() and not failures and results == ["done"]
    assert [progress.phase for progress in updates] == ["waiting_for_tool", "preparing_task"]
    assert not updates[0].activity_changed and updates[0].evidence_kind == "resource_wait"


@pytest.fixture
def fixture_mcp(tmp_path):
    script = tmp_path / "fixture_mcp.py"
    marker = tmp_path / "tools-listed.txt"
    script.write_text('''import sys
from pathlib import Path
import anyio
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool
server=Server("fixture")
@server.list_tools()
async def tools():
    Path(sys.argv[1]).write_text("listed")
    return [Tool(name="echo",description="Fixture",inputSchema={"type":"object"})]
@server.call_tool()
async def call(name,arguments):
    raise RuntimeError("No tool call is allowed in a connection check")
async def main():
    async with stdio_server() as (read,write):
        await server.run(read,write,server.create_initialization_options())
anyio.run(main)
''')
    return WorkerMcpServer.from_dict({"id": "fixture", "command": sys.executable, "args": [str(script), str(marker)]}), marker


def test_connection_check_initializes_real_stdio_mcp_and_lists_tools_without_calling_them(fixture_mcp, tmp_path):
    selected, marker = fixture_mcp
    result = check_mcp_connection(selected, tmp_path, tmp_path)
    assert result["status"] == "connected" and result["tool_count"] == 1 and marker.read_text() == "listed"
    failed = check_mcp_connection(replace(selected, command=str(tmp_path / "missing.exe")), tmp_path, tmp_path)
    assert failed["status"] == "error" and str(tmp_path) not in failed["message"]


def test_http_connection_check_uses_streamable_protocol_and_environment_auth_without_invoking_tools(tmp_path, monkeypatch):
    import httpx

    monkeypatch.setenv("FIXTURE_MCP_TOKEN", "fixture-sensitive-token")
    requests = []

    def respond(request):
        message = json.loads(request.content)
        requests.append((message["method"], request.headers.get("Authorization")))
        if "id" not in message:
            return httpx.Response(202)
        if message["method"] == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "fixture", "version": "1"}}
        elif message["method"] == "tools/list":
            result = {"tools": [{"name": "echo", "description": "Fixture", "inputSchema": {"type": "object"}}]}
        else:
            raise AssertionError("Connection checks must never call a tool")
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": message["id"], "result": result})

    class FixtureClient(httpx.AsyncClient):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(respond), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", FixtureClient)
    result = check_mcp_connection(server(bearer_token_env_var="FIXTURE_MCP_TOKEN"), tmp_path, tmp_path)
    assert result["status"] == "connected" and result["tool_count"] == 1, result
    assert {method for method, _ in requests} == {"initialize", "notifications/initialized", "tools/list"}
    assert all(auth == "Bearer fixture-sensitive-token" for _, auth in requests)
    assert "fixture-sensitive-token" not in json.dumps(result)


@pytest.mark.skipif(os.environ.get("AI_ORCHESTRATOR_NATIVE_MCP_SMOKE") != "1", reason="Opt-in local Codex runtime smoke check")
def test_native_codex_thread_loads_project_mcp_without_starting_a_model_turn(fixture_mcp, tmp_path):
    from openai_codex import Codex, CodexConfig
    selected, marker = fixture_mcp
    home = tmp_path / "native-user"
    home.mkdir()
    environment = {key: str(home) for key in ("APPDATA", "LOCALAPPDATA", "HOME", "USERPROFILE", "TEMP", "TMP", "CODEX_HOME", "CODEX_SQLITE_HOME")}
    environment.update(OPENAI_API_KEY="", CODEX_API_KEY="", CODEX_ACCESS_TOKEN="")
    client = Codex(CodexConfig(cwd=str(tmp_path), env=environment, config_overrides=('cli_auth_credentials_store="file"',)))
    deadline = threading.Timer(25, client.close)
    deadline.start()
    try:
        thread = client.thread_start(cwd=str(tmp_path), ephemeral=True, model="gpt-6.1-sol",
                                     config=codex_mcp_config((selected,), tmp_path, tmp_path))
        assert thread.id
        until = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < until:
            time.sleep(0.05)
        assert marker.read_text() == "listed"
        missing = replace(selected, command=str(tmp_path / "missing-mcp.exe"))
        with pytest.raises(Exception) as error:
            client.thread_start(cwd=str(tmp_path), ephemeral=True, model="gpt-6.1-sol",
                                config=codex_mcp_config((missing,), tmp_path, tmp_path))
        assert "mcp" in str(error.value).lower()
        # No turn_start call: this checks MCP discovery without an AI request.
    finally:
        client.close()
        deadline.cancel()
        deadline.join()


def test_tool_lease_honors_cancellation_and_does_not_create_locks_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr("ai_orchestrator.worker_mcp.application_config_root", lambda: tmp_path)
    selected = server()
    with worker_mcp_lease((replace(selected, exclusive=False),)):
        assert not (tmp_path / "mcp-locks").exists()
    with worker_mcp_lease((selected,)):
        with pytest.raises(ExecutionStopped):
            with worker_mcp_lease((selected,), cancel_signal=SimpleNamespace(is_set=lambda: True)):
                raise AssertionError("cancelled request acquired a tool")
        started, entered, stop = threading.Event(), threading.Event(), threading.Event()
        errors = []

        def wait_for_tool():
            started.set()
            try:
                with worker_mcp_lease((selected,), cancel_signal=SimpleNamespace(is_set=stop.is_set)):
                    entered.set()
            except ExecutionStopped as exc:
                errors.append(exc)

        waiting = threading.Thread(target=wait_for_tool)
        waiting.start()
        try:
            assert started.wait(1)
            time.sleep(0.15)
            assert not entered.is_set()
        finally:
            stop.set()
            waiting.join(2)
        assert errors and not waiting.is_alive()
