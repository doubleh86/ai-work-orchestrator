"""Exercise public query lifetimes and failure boundaries after migration."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_orchestrator import pipeline_bootstrap
from ai_orchestrator.codex_sdk import CodexSdkAccountStatus
from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, ProjectConfig
from ai_orchestrator.execution import provider_connection
from ai_orchestrator.models import RunExecutionSituation, RunLockState, RunLockStatus, RunState, Stage
from ai_orchestrator.pipeline import Pipeline
from ai_orchestrator.store import StateStore


@pytest.fixture
def pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Pipeline:
    monkeypatch.setattr(pipeline_bootstrap, "current_nvidia_api_key", lambda: None)
    monkeypatch.setattr(pipeline_bootstrap, "current_claude_api_key", lambda: None)
    monkeypatch.setattr(pipeline_bootstrap, "current_nvidia_model_keys", lambda: {})
    agent = AgentConfig("worker", ("general",), (), provider_id="codex")
    return Pipeline(Config(tmp_path / "config.toml", ProjectConfig(tmp_path), ExecutionConfig(), (agent,)))


def test_queries_read_replaced_store_config_and_borrowed_sdk(pipeline: Pipeline, tmp_path: Path) -> None:
    assert not pipeline.provider_statuses("codex")[0].available
    sdk = Mock()
    sdk.account_status.return_value = CodexSdkAccountStatus(True, "chatgpt", "fixture")
    pipeline._codex_sdk = sdk
    pipeline.config = replace(pipeline.config, agents=(replace(pipeline.config.agents[0], id="new-worker"),))
    status = pipeline.provider_statuses("codex")[0]
    assert status.available and status.agent_ids == ("new-worker",)
    pipeline.store = StateStore(tmp_path / "replacement")
    state = RunState("new-run", "", "", str(tmp_path), "main", Stage.PLANNED)
    pipeline.store.save(state)
    assert [item.id for item in pipeline.list_statuses()] == [state.id]
    assert pipeline.status(state.id).id == state.id
    sdk.close.assert_not_called()


def test_status_lock_changes_and_control_read_errors_keep_distinct_meanings(pipeline: Pipeline, tmp_path: Path) -> None:
    state = RunState("query-run", "", "", str(tmp_path), "main", Stage.PLANNED)
    pipeline.store.save(state)
    pipeline.git = Mock()
    unlocked = RunLockStatus(state.id, RunLockState.UNLOCKED)
    active = RunLockStatus(state.id, RunLockState.ACTIVE, operation="execute")
    pipeline.store.inspect_lock = Mock(side_effect=[unlocked, active])
    assert pipeline.status_with_controls(state.id)[1].situation == RunExecutionSituation.STATUS_UNKNOWN
    pipeline.store.inspect_lock = Mock(return_value=unlocked)
    pipeline.store.load_execution_control = Mock(side_effect=ValueError("malformed control"))
    assert pipeline.status_with_controls(state.id)[0].id == state.id
    pipeline.store.load_execution_control.side_effect = OSError("control unreadable")
    with pytest.raises(OSError, match="control unreadable"):
        pipeline.status_with_controls(state.id)
    assert pipeline._common_runtime.runs.controls.summary_control(state).situation == RunExecutionSituation.STATUS_UNKNOWN


def test_static_queries_do_not_construct_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    build = Mock(side_effect=AssertionError("static queries must not construct a Pipeline"))
    monkeypatch.setattr("ai_orchestrator.pipeline.build_pipeline_runtime", build)
    monkeypatch.setattr(provider_connection, "resolve_provider_executable", lambda value: "")
    monkeypatch.setattr(provider_connection, "selected_claude_executable", lambda: "")
    assert Pipeline.account_usage("unsupported").status == "unavailable"
    assert Pipeline.claude_connection_status()["installed"] is False
    build.assert_not_called()
