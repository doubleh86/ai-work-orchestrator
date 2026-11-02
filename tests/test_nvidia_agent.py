import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock

import pytest

from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, NVIDIA_MODEL_PRESETS, ProjectConfig, RoutingConfig
from ai_orchestrator.codex_sdk import CodexSdkAccountStatus
from ai_orchestrator.desktop_rpc import _expanded_provider_choices, handle_request
from ai_orchestrator.execution_control import ExecutionStopped
from ai_orchestrator.models import RunState, Stage, WorkTask
from ai_orchestrator.nvidia_agent import (
    NVIDIA_AGENT_ID, NvidiaAgentError, NvidiaCompletionError, nvidia_command, nvidia_environment, parse_nvidia_output,
    redact_nvidia_output, with_nvidia_agent,
    current_nvidia_api_key, current_nvidia_model_keys, nvidia_credential_scope,
)
from ai_orchestrator.pipeline import Pipeline, PipelineError, ProviderCapacityError, ProviderRequestLimitError, ProviderTimeoutError
from ai_orchestrator.planner import assign_task_agent_overrides, execution_profile_guidance, select_agent_for_provider


def configured_pipeline(tmp_path):
    sdk = Mock()
    sdk.account_status.return_value = CodexSdkAccountStatus(True, "chatgpt", "로그인됨")
    return Pipeline(Config(
        path=tmp_path / "config.toml", project=ProjectConfig(tmp_path), execution=ExecutionConfig(),
        agents=(AgentConfig("worker", ("general",), (), provider_id="codex"),), routing=RoutingConfig(default_provider="codex"),
    ), codex_sdk=sdk)


def stream(*events):
    return "\n".join(json.dumps(event, ensure_ascii=False) for event in events)


def text(value):
    return {"type": "text", "part": {"text": value}}


def finish(reason="stop", **tokens):
    return {"type": "step_finish", "part": {"reason": reason, "tokens": tokens}}


def invoke(pipeline, tmp_path, **options):
    agent = pipeline.agents[NVIDIA_AGENT_ID]
    return pipeline._run_provider_command(
        agent=agent, command_template=pipeline._agent_command(agent, "execute"), replacements={"{run_id}": "run"},
        cwd=tmp_path, prompt="공개 예제 수정", prompt_path="prompt.md", log_path=tmp_path / "agent.log",
        action="execute", task_id="task", **options,
    )


def test_trial_profile_is_available_only_after_setup_and_never_changes_default(tmp_path, monkeypatch):
    pipeline = configured_pipeline(tmp_path)
    original = pipeline.config
    assert with_nvidia_agent(original) is original
    assert not original.path.exists()
    assert original.routing.default_provider == "codex"
    assert pipeline.agents[NVIDIA_AGENT_ID].manual_only
    monkeypatch.setattr(pipeline, "_resolve_executable", lambda _value: "opencode.exe")
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    assert [choice.provider_id for choice in pipeline.execution_provider_choices(["general"])] == ["codex"]
    status = pipeline.provider_statuses("nvidia")[0]
    assert not status.available and "API 키" in status.auth_label
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key-not-real")
    choices = pipeline.execution_provider_choices(["general"])
    assert [choice.provider_id for choice in choices] == ["codex", "nvidia"]
    assert [choice.provider_id for choice in pipeline.planning_provider_choices()] == ["codex"]
    status = pipeline.provider_statuses("nvidia")[0]
    assert status.available and status.authenticated is None and "미검증" in status.auth_label
    assert any(profile["provider_id"] == "nvidia" and profile["model"] == NVIDIA_MODEL_PRESETS[0]
               for profile in _expanded_provider_choices(choices))
    monkeypatch.setattr(pipeline, "_resolve_executable", lambda _value: "")
    assert "OpenCode" in pipeline.provider_statuses("nvidia")[0].auth_label


def test_trial_profile_does_not_become_automatic_worker_or_reviewer(tmp_path):
    pipeline = configured_pipeline(tmp_path)
    task = WorkTask(id="test", title="example", capabilities=["general"])
    agents = pipeline.config.agents
    assert select_agent_for_provider(task, agents, "", purpose="execution").provider_id == "codex"
    assert select_agent_for_provider(task, agents, "nvidia", purpose="execution").id == NVIDIA_AGENT_ID
    with pytest.raises(ValueError, match="no review agent"):
        select_agent_for_provider(task, (agents[-1],), "", purpose="review")
    assert "nvidia" not in execution_profile_guidance(agents)


def test_command_uses_explicit_provider_model_and_disables_plugins(tmp_path):
    pipeline = configured_pipeline(tmp_path)
    agent = pipeline.agents[NVIDIA_AGENT_ID]
    command = pipeline._command_with_model(agent, (), "nvidia/example-model")
    assert command == nvidia_command("nvidia/example-model")
    assert command[-1] == "nvidia/nvidia/example-model"
    assert "--pure" in command and "--attach" not in command
    with pytest.raises(NvidiaAgentError):
        nvidia_command("bad\nmodel")


def test_manual_task_override_persists_nvidia_without_adding_a_reviewer(tmp_path):
    pipeline = configured_pipeline(tmp_path)
    task = WorkTask(id="test", title="example", capabilities=["general"], agent_id="worker", provider_id="codex")
    assign_task_agent_overrides([task], pipeline.config.agents, pipeline.config.routing, {task.id: NVIDIA_AGENT_ID}, sequential=True)
    assert task.agent_id == NVIDIA_AGENT_ID and task.provider_id == "nvidia" and task.model == NVIDIA_MODEL_PRESETS[0]
    assert task.reviewer_agent_id == ""
    state = RunState(id="test", spec_path="", spec_digest="", repo_path=str(tmp_path), main_branch="main", stage=Stage.PLANNED, tasks=[task])
    restored = RunState.from_dict(state.to_dict()).tasks[0]
    assert restored.provider_id == "nvidia" and restored.model == NVIDIA_MODEL_PRESETS[0]


def test_execution_and_review_have_explicit_tools_without_secret_config():
    for action in ("execute", "review"):
        environment = nvidia_environment({"NVIDIA_API_KEY": "test-key-not-real"}, model="nvidia/example", action=action)
        config = json.loads(environment["OPENCODE_CONFIG_CONTENT"])
        assert "test-key-not-real" not in environment["OPENCODE_CONFIG_CONTENT"]
        assert config["provider"]["nvidia"]["options"]["apiKey"] == "{env:NVIDIA_API_KEY}"
        assert config["enabled_providers"] == ["nvidia"] and config["snapshot"] is False
        permission = config["agent"]["orchestrator"]["permission"]
        assert permission["*"] == "deny" and permission["external_directory"] == "deny"
        assert permission["question"] == "deny" and permission["task"] == "deny"
        assert permission["read"]["**/.env.*"] == "deny"
        assert permission["bash"]["*"] == "deny"
        assert permission["bash"]["git diff*"] == "allow"
        if action == "review":
            assert permission["edit"] == "deny" and "python -m pytest*" not in permission["bash"]
        else:
            assert permission["edit"]["*"] == "allow" and permission["bash"]["python -m pytest*"] == "allow"


@pytest.mark.parametrize("model", ["nvidia/nemotron-3-super-120b-a12b", "nvidia/nemotron-3-ultra-550b-a55b"])
@pytest.mark.parametrize("action", ["execute", "review"])
def test_documented_nemotron_models_request_nonempty_content_without_relaxing_permissions(model, action):
    environment = nvidia_environment({}, model=model, action=action, api_key="fixture-key")
    config = json.loads(environment["OPENCODE_CONFIG_CONTENT"])
    settings = config["provider"]["nvidia"]["models"][model]
    assert settings["options"] == {"chat_template_kwargs": {"force_nonempty_content": True}}
    assert settings["tool_call"] is True
    assert "fixture-key" not in environment["OPENCODE_CONFIG_CONTENT"]
    assert config["permission"]["external_directory"] == "deny"
    if action == "review":
        assert config["permission"]["edit"] == "deny"


@pytest.mark.parametrize("model", ["nvidia/nemotron-3-nano-30b-a3b", "vendor/other-model"])
def test_other_registered_models_do_not_receive_undocumented_template_parameters(model):
    environment = nvidia_environment({}, model=model, action="execute", api_key="fixture-key")
    config = json.loads(environment["OPENCODE_CONFIG_CONTENT"])
    assert "options" not in config["provider"]["nvidia"]["models"][model]


def test_parser_returns_final_answer_and_sums_reported_steps_only():
    output = stream({"type": "step_start"}, text("읽는 중"), finish("tool-calls", input=7, output=2),
                    {"type": "step_start"}, text("AI_REVIEW_RESULT {\"verdict\":\"approved\"}"), finish(input=11, output=3))
    answer, usage = parse_nvidia_output(output)
    assert answer.startswith("AI_REVIEW_RESULT") and "읽는 중" not in answer
    assert usage is not None and usage.counts.input_tokens == 18 and usage.counts.output_tokens == 5
    assert usage.counts.cached_input_tokens is None and usage.counts.total_tokens is None
    assert parse_nvidia_output(stream(text("done"), finish()))[1] is None
    assert parse_nvidia_output(stream(text("done"), finish(input=0, output=0, reasoning=0)))[1] is None


@pytest.mark.parametrize("output", [
    "", "ordinary stdout", stream(text("not complete")), stream(text("truncated"), finish("length")),
    stream(text("previous"), finish(), {"type": "step_start"}),
    stream(text("previous"), finish(), finish("tool-calls")),
    stream({"type": "error", "error": {"data": {"message": "503 Service Unavailable"}}}),
])
def test_parser_does_not_hide_incomplete_or_failed_turns(output):
    with pytest.raises(NvidiaAgentError):
        parse_nvidia_output(output)


@pytest.mark.parametrize("final_text", [None, "", " \n\t"])
def test_stop_after_file_tools_without_a_final_answer_stays_an_explicit_failure(final_text):
    events = [text("이전 단계의 중간 보고"), finish("tool-calls"), {"type": "step_start"},
              {"type": "tool_use", "part": {"tool": "edit", "state": {"status": "completed"}}},
              finish("tool-calls"), {"type": "step_start"}]
    if final_text is not None:
        events.append(text(final_text))
    events.append(finish("stop", input=2150, output=0, reasoning=565))
    with pytest.raises(NvidiaCompletionError, match="최종 답변을 보내지 않았습니다"):
        parse_nvidia_output(stream(*events))


@pytest.mark.parametrize(("output", "message"), [
    (stream({"type": "tool_use", "part": {"tool": "edit", "state": {"status": "completed"}}},
            finish("stop", input=2150, output=0, reasoning=565)), "최종 답변을 보내지 않았습니다"),
    (stream(text("중간 보고만 있음")), "완료 응답을 확인하지 못했습니다"),
    (stream(text("잘린 답변"), finish("length")), "응답이 완료되지 않았습니다: length"),
])
def test_runtime_preserves_the_completion_failure_reason_without_replaying_tools(tmp_path, monkeypatch, output, message):
    pipeline = configured_pipeline(tmp_path)
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setattr(pipeline, "_resolve_executable", lambda _value: "opencode.exe")
    process = Mock(returncode=0)
    process.communicate.return_value = (output, None)
    popen = Mock(return_value=process)
    monkeypatch.setattr("ai_orchestrator.pipeline.subprocess.Popen", popen)
    with pytest.raises(PipelineError, match=message) as caught:
        invoke(pipeline, tmp_path)
    assert type(caught.value) is PipelineError
    assert "agent.log" in str(caught.value)
    saved = (tmp_path / "agent.log").read_text(encoding="utf-8")
    assert output in saved and message in saved
    assert popen.call_count == 1


def test_runtime_feeds_prompt_via_stdin_records_usage_and_redacts_output(tmp_path, monkeypatch):
    pipeline = configured_pipeline(tmp_path)
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setattr(pipeline, "_resolve_executable", lambda _value: "opencode.exe")
    process = Mock(returncode=0)
    process.communicate.return_value = (stream(text("완료 test-key-not-real"), finish(input=6, output=3)), None)
    popen = Mock(return_value=process)
    monkeypatch.setattr("ai_orchestrator.pipeline.subprocess.Popen", popen)
    observations = []
    assert invoke(pipeline, tmp_path, usage_callback=observations.append) == "완료 [REDACTED]"
    process.communicate.assert_called_once_with(input="공개 예제 수정", timeout=1800)
    assert observations[0].counts.input_tokens == 6
    assert popen.call_args.kwargs["cwd"] == tmp_path
    assert popen.call_args.args[0][-2:] == ["--dir", str(tmp_path.resolve())]
    assert "test-key-not-real" not in (tmp_path / "agent.log").read_text(encoding="utf-8")
    assert redact_nvidia_output("nvapi-another-key", {}) == "[REDACTED]"


@pytest.mark.parametrize(("message", "expected"), [("429 Too Many Requests", ProviderRequestLimitError),
    ("503 Service Unavailable", ProviderCapacityError), ("invalid API key", PipelineError)])
def test_zero_exit_error_events_are_failures(tmp_path, monkeypatch, message, expected):
    pipeline = configured_pipeline(tmp_path)
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setattr(pipeline, "_resolve_executable", lambda _value: "opencode.exe")
    process = Mock(returncode=0)
    process.communicate.return_value = (stream({"type": "error", "error": {"data": {"message": message}}}), None)
    monkeypatch.setattr("ai_orchestrator.pipeline.subprocess.Popen", Mock(return_value=process))
    with pytest.raises(expected):
        invoke(pipeline, tmp_path)
    assert message in (tmp_path / "agent.log").read_text(encoding="utf-8")


def test_runtime_keeps_stop_and_timeout_boundaries(tmp_path, monkeypatch):
    pipeline = configured_pipeline(tmp_path)
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key-not-real")
    monkeypatch.setattr(pipeline, "_resolve_executable", lambda _value: "opencode.exe")
    process = Mock(returncode=0)
    process.communicate.return_value = ("test-key-not-real", None)
    monkeypatch.setattr("ai_orchestrator.pipeline.subprocess.Popen", Mock(return_value=process))
    terminate = Mock()
    monkeypatch.setattr(pipeline, "_terminate_agent_process", terminate)
    signal = Mock(request_id="request")
    signal.is_set.return_value = True
    with pytest.raises(ExecutionStopped):
        invoke(pipeline, tmp_path, cancel_signal=signal)
    terminate.assert_called_once_with(process)
    assert "test-key-not-real" not in (tmp_path / "agent.log").read_text()
    process.communicate.side_effect = [subprocess.TimeoutExpired("opencode", 1), ("test-key-not-real", None)]
    with pytest.raises(ProviderTimeoutError):
        invoke(pipeline, tmp_path, timeout_seconds=1)
    assert "test-key-not-real" not in (tmp_path / "agent.log").read_text()


def test_structured_http_status_is_not_lost_when_message_has_no_status_number(tmp_path):
    output = stream({"type": "error", "error": {"data": {"message": "Request failed", "statusCode": 429}}})
    with pytest.raises(NvidiaAgentError, match="HTTP 429") as caught:
        parse_nvidia_output(output)
    assert isinstance(Pipeline._nvidia_command_failure(str(caught.value), tmp_path / "agent.log"), ProviderRequestLimitError)


def test_request_credentials_are_isolated_and_pipelines_keep_their_snapshot(tmp_path, monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    barrier = Barrier(2)
    pipelines = {}

    def dispatch(method, params):
        pipeline = configured_pipeline(tmp_path / params["name"])
        pipelines[params["name"]] = pipeline
        barrier.wait(timeout=5)
        monkeypatch.setattr(pipeline, "_resolve_executable", lambda _value: "opencode.exe")
        return pipeline.provider_statuses("nvidia")

    service = Mock(dispatch=dispatch)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(handle_request, service, {
            "id": name, "method": "providers.status", "params": {"name": name}, "nvidia_api_key": key,
        }) for name, key in (("app", "fixture-app-key"), ("none", None))]
        app, none = [future.result() for future in futures]
    assert app["result"][0]["available"] and app["result"][0]["auth_method"] == "app_key"
    assert not none["result"][0]["available"]
    assert "fixture-app-key" not in json.dumps(app)
    assert current_nvidia_api_key() is None
    with nvidia_credential_scope("replacement-key"):
        assert pipelines["app"]._nvidia_api_key == "fixture-app-key"
        assert pipelines["none"]._nvidia_api_key is None
    assert current_nvidia_api_key() is None


@pytest.mark.parametrize("credential", ["", "line\nbreak", 10, {"key": "fake"}, "x" * 4097])
def test_invalid_private_credential_cannot_reach_dispatch_or_echo_secret(credential):
    service = Mock()
    response = handle_request(service, {"id": 1, "method": "system.hello", "nvidia_api_key": credential})
    service.dispatch.assert_not_called()
    assert response["error"]["message"] == "Invalid NVIDIA credential"
    assert current_nvidia_api_key() is None


def test_rpc_error_redacts_key_and_resets_scope():
    service = Mock()
    service.dispatch.side_effect = RuntimeError("server rejected fixture-secret-key")
    response = handle_request(service, {"id": 1, "method": "system.hello", "nvidia_api_key": "fixture-secret-key"})
    assert "fixture-secret-key" not in json.dumps(response)
    assert "[REDACTED]" in response["error"]["message"]
    assert current_nvidia_api_key() is None


def test_app_key_is_injected_only_into_nvidia_process_and_redacted(tmp_path, monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    with nvidia_credential_scope("app-fixture-key"):
        pipeline = configured_pipeline(tmp_path)
    monkeypatch.setattr(pipeline, "_resolve_executable", lambda _value: "mock.exe")
    process = Mock(returncode=0)
    process.communicate.return_value = (stream(text("done app-fixture-key"), finish()), None)
    popen = Mock(return_value=process)
    monkeypatch.setattr("ai_orchestrator.pipeline.subprocess.Popen", popen)
    with ThreadPoolExecutor(max_workers=1) as executor:
        assert executor.submit(invoke, pipeline, tmp_path).result() == "done [REDACTED]"
    assert popen.call_args.kwargs["env"]["NVIDIA_API_KEY"] == "app-fixture-key"
    assert "app-fixture-key" not in (tmp_path / "agent.log").read_text(encoding="utf-8")
    process.communicate.return_value = ("other output", None)
    pipeline._run_provider_command(
        agent=AgentConfig("other", ("general",), ("other",), provider_id="custom"), command_template=("other",),
        replacements={"{run_id}": "run"}, cwd=tmp_path, prompt="example", prompt_path="prompt.md", log_path=tmp_path / "other.log",
        action="execute", task_id="other",
    )
    assert "NVIDIA_API_KEY" not in popen.call_args.kwargs["env"]
    assert current_nvidia_api_key() is None
    monkeypatch.setenv("NVIDIA_API_KEY", "environment-fixture-key")
    assert nvidia_environment({}, model="", action="execute", api_key="app-fixture-key")["NVIDIA_API_KEY"] == "app-fixture-key"
    assert configured_pipeline(tmp_path).provider_statuses("nvidia")[0].auth_method == "environment"


def test_model_keys_override_default_and_remain_fixed_across_worker_threads(tmp_path, monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "environment-fixture")
    bindings = {"vendor/model-a": "model-a-fixture", "vendor/model-b": "model-b-fixture"}
    with nvidia_credential_scope("default-fixture", bindings):
        pipeline = configured_pipeline(tmp_path)
        monkeypatch.setattr(pipeline, "_resolve_executable", lambda _value: "mock.exe")
        choices = _expanded_provider_choices(pipeline.execution_provider_choices(["general"]))
        assert {item["model"] for item in choices if item["provider_id"] == "nvidia"} >= set(bindings)
    monkeypatch.setattr(pipeline, "_resolve_executable", lambda _value: "mock.exe")
    observed = []

    def start(*args, **kwargs):
        selected = kwargs["env"]["NVIDIA_API_KEY"]
        observed.append(selected)
        process = Mock(returncode=0)
        process.communicate.return_value = (stream(text(f"done {selected}"), finish()), None)
        return process

    monkeypatch.setattr("ai_orchestrator.pipeline.subprocess.Popen", start)
    with nvidia_credential_scope("new-default", {"vendor/model-a": "new-model-key"}):
        with ThreadPoolExecutor(max_workers=1) as executor:
            for model in ("vendor/model-a", "vendor/model-b", "vendor/unbound", ""):
                assert executor.submit(invoke, pipeline, tmp_path, model=model).result() == "done [REDACTED]"
    assert observed == ["model-a-fixture", "model-b-fixture", "default-fixture", "default-fixture"]
    assert current_nvidia_model_keys() == {}
    assert not pipeline.config.path.exists()
    assert "fixture" not in (tmp_path / "agent.log").read_text(encoding="utf-8")


def test_model_mapping_is_copied_and_environment_fallback_stays_available(tmp_path, monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "environment-fixture")
    bindings = {"vendor/model": "model-fixture"}
    with nvidia_credential_scope(None, bindings):
        pipeline = configured_pipeline(tmp_path)
        bindings["vendor/model"] = "mutated-caller-value"
        assert current_nvidia_model_keys()["vendor/model"] == "model-fixture"
    assert pipeline._nvidia_model_api_keys["vendor/model"] == "model-fixture"
    assert pipeline._nvidia_api_key is None
    environment = nvidia_environment({"NVIDIA_API_KEY": "environment-fixture"}, model="vendor/unbound", action="execute")
    assert environment["NVIDIA_API_KEY"] == "environment-fixture"


@pytest.mark.parametrize("bindings", [[], {"bad model": "secret-fixture"}, {"vendor/model": ""}, {"vendor/model": "key\nvalue"}])
def test_invalid_model_credentials_are_rejected_before_dispatch(bindings):
    service = Mock()
    response = handle_request(service, {"id": 1, "method": "system.hello", "nvidia_model_api_keys": bindings})
    assert response["error"]["message"] == "Invalid NVIDIA model credentials"
    service.dispatch.assert_not_called()
    assert current_nvidia_model_keys() == {}


def test_rpc_error_redacts_every_model_key():
    service = Mock()
    service.dispatch.side_effect = RuntimeError("rejected default-fixture model-a-fixture model-b-fixture")
    response = handle_request(service, {"id": 1, "method": "system.hello", "nvidia_api_key": "default-fixture",
        "nvidia_model_api_keys": {"vendor/a": "model-a-fixture", "vendor/b": "model-b-fixture"}})
    assert "fixture" not in json.dumps(response)
    assert response["error"]["message"].count("[REDACTED]") == 3


def test_registered_model_is_valid_for_manual_override_but_unregistered_models_are_rejected(tmp_path):
    with nvidia_credential_scope("default-fixture", {"vendor/registered": "model-fixture"}):
        pipeline = configured_pipeline(tmp_path)
    task = WorkTask(id="task", title="example", capabilities=["general"], agent_id=NVIDIA_AGENT_ID, provider_id="nvidia")
    state = RunState(id="run", spec_path="", spec_digest="", repo_path=str(tmp_path), main_branch="main", stage=Stage.PLANNED, tasks=[task])
    pipeline._validate_task_model_overrides(state, {"task": "vendor/registered"}, {})
    with pytest.raises(PipelineError, match="unsupported execution model"):
        pipeline._validate_task_model_overrides(state, {"task": "vendor/unregistered"}, {})
