from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai_orchestrator.codex_sdk import CodexSdkError, CodexSdkTimeout
from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, ProjectConfig
from ai_orchestrator.execution import (
    ProviderRequestLimited, ProviderRunError, ProviderRunner, ProviderRuntimeOptions, ProviderTimedOut, ProviderUnavailable,
)
from ai_orchestrator.pipeline import Pipeline, PipelineError, ProviderCapacityError, ProviderRequestLimitError, ProviderTimeoutError


@pytest.fixture
def invocation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("ai_orchestrator.pipeline_bootstrap.current_claude_api_key", lambda: "")
    monkeypatch.setattr("ai_orchestrator.pipeline_bootstrap.current_nvidia_api_key", lambda: "")
    monkeypatch.setattr("ai_orchestrator.pipeline_bootstrap.current_nvidia_model_keys", lambda: {})
    agent = AgentConfig(
        "worker", ("general",), (), provider_id="codex", sandbox_mode="workspace-write", approval_mode="on-request",
        review_sandbox_mode="read-only", review_approval_mode="never",
    )
    config = Config(tmp_path / "config.toml", ProjectConfig(tmp_path), ExecutionConfig(), (agent,))
    params = dict(agent=agent, command_template=(), replacements={"{run_id}": "run"}, cwd=tmp_path,
                  prompt="구현 확인", prompt_path="prompt.md", log_path=tmp_path / "worker.log", action="execute", task_id="task")
    return config, ProviderRuntimeOptions(tmp_path, config.execution.agent_timeout_seconds), params


@pytest.mark.parametrize(("failure", "runtime_type", "facade_type"), [
    (CodexSdkTimeout("fixture timeout"), ProviderTimedOut, ProviderTimeoutError),
    (CodexSdkError("usage_limit_exceeded"), ProviderRequestLimited, ProviderRequestLimitError),
    (CodexSdkError("HTTP 503 Service Unavailable"), ProviderUnavailable, ProviderCapacityError),
    (CodexSdkError("fixture failure"), ProviderRunError, PipelineError),
])
def test_standalone_failure_is_translated_by_facade_with_the_same_message_and_sdk_cause(invocation, failure, runtime_type, facade_type):
    config, options, params = invocation
    sdk = Mock()
    sdk.run_turn.side_effect = failure
    with pytest.raises(runtime_type) as direct:
        ProviderRunner(options, codex_sdk=sdk).run(**params)
    with pytest.raises(facade_type) as adapted:
        Pipeline(config, codex_sdk=sdk)._common_runtime.provider.run(**params)
    assert type(adapted.value) is facade_type
    assert str(direct.value) == str(adapted.value)
    assert direct.value.__cause__ is failure and adapted.value.__cause__ is failure
    sdk.close.assert_not_called()


@pytest.mark.parametrize(("action", "sandbox", "approval"), [("execute", "workspace-write", "on-request"), ("review", "read-only", "never")])
def test_standalone_and_facade_preserve_request_identity_callbacks_and_sdk_ownership(invocation, action, sandbox, approval):
    config, options, params = invocation
    sdk = Mock()
    sdk.run_turn.return_value = "completed"
    callbacks = {name: Mock() for name in ("progress_callback", "profile_callback", "usage_callback", "retry_callback")}
    signal = SimpleNamespace(request_id="stop", is_set=lambda: False)
    params.update(action=action, model="gpt-6.1-sol", reasoning_effort="high", timeout_seconds=2.5,
                  sdk_conversation_id="conversation", attempt_id="attempt", invocation_id="invocation", cancel_signal=signal, **callbacks)
    for invoke in (ProviderRunner(options, codex_sdk=sdk).run, Pipeline(config, codex_sdk=sdk)._common_runtime.provider.run):
        assert invoke(**params) == "completed"
        request = sdk.run_turn.call_args.args[0]
        assert (request.sandbox_mode, request.approval_mode) == (sandbox, approval)
        assert request.model == "gpt-6.1-sol" and request.reasoning_effort == "high" and request.timeout_seconds == 2.5
        assert (request.attempt_id, request.invocation_id, request.conversation_id) == ("attempt", "invocation", "conversation")
        assert request.cancel_signal is signal
        assert all(getattr(request, name) is callback for name, callback in callbacks.items())
    sdk.close.assert_not_called()


def test_public_execution_import_does_not_load_workflow_or_storage(tmp_path: Path):
    source = Path(__file__).resolve().parents[2] / "src"
    environment = {**os.environ, "PYTHONPATH": str(source)}
    subprocess.run([
        sys.executable, "-c", "import sys; from ai_orchestrator.execution import ProviderRunner; "
        "assert not {'ai_orchestrator.pipeline','ai_orchestrator.store','ai_orchestrator.registry','ai_orchestrator.git'} & set(sys.modules)",
    ], cwd=tmp_path, env=environment, check=True, timeout=15, capture_output=True)
