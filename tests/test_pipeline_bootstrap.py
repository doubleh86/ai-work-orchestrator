"""Resource replacement and scope lifetime at the Pipeline boundary."""

from __future__ import annotations

import os
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_orchestrator import pipeline_bootstrap as bootstrap
from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, PlanningConfig, ProjectConfig
from ai_orchestrator.models import ExecutionControlRecord, ProfileSource, RunState, RunStep, Stage
from ai_orchestrator.pipeline import Pipeline
from ai_orchestrator.store import StateStore


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setattr(bootstrap, "current_nvidia_api_key", lambda: None)
    monkeypatch.setattr(bootstrap, "current_claude_api_key", lambda: None)
    monkeypatch.setattr(bootstrap, "current_nvidia_model_keys", lambda: {})
    agent = AgentConfig("planner", ("general",), (), provider_id="codex", model="gpt-6.1-sol")
    return Config(
        tmp_path / "config.toml", ProjectConfig(tmp_path), ExecutionConfig(), (agent,), planning=PlanningConfig(agent_id=agent.id),
    )


def state_at(config: Config) -> RunState:
    return RunState(
        "run-scope", "plan.md", "digest", str(config.project.repo), "main", stage=Stage.REVIEWED,
        planning_agent_id="planner", planning_provider_id="codex", planning_model="gpt-6.1-sol",
        planning_reasoning_effort="medium", planning_profile_source=ProfileSource.ROUTING,
    )


def test_construction_is_lazy_borrows_sdk_and_isolates_instance_scopes(config: Config, monkeypatch: pytest.MonkeyPatch) -> None:
    notifications = Mock()
    monkeypatch.setattr(bootstrap, "synchronize_notification_events", notifications)
    monkeypatch.setattr(bootstrap, "current_nvidia_api_key", lambda: "fixture-nvidia-key")
    monkeypatch.setattr(bootstrap, "current_claude_api_key", lambda: "fixture-claude-key")
    monkeypatch.setattr(bootstrap, "current_nvidia_model_keys", lambda: {"fixture-model": "fixture-model-key"})
    sdk = Mock()
    first = Pipeline(config, codex_sdk=sdk)
    second = Pipeline(config)
    assert not list((first.store.root / "runs").glob("*/state.json"))
    assert not sdk.mock_calls
    assert first._resources is not second._resources
    assert first._common_runtime.resources.state_lock is not second._common_runtime.resources.state_lock
    assert first._common_runtime.planning_policy.context is not second._common_runtime.planning_policy.context
    assert first._common_runtime.planning_policy.context is first._common_runtime.planning_policy.context
    assert first._common_runtime.resources.codex_sdk is sdk
    assert all(key not in repr(first._common_runtime) for key in ("fixture-nvidia-key", "fixture-claude-key", "fixture-model-key"))
    initial_agents, initial_git, initial_store = first.agents, first.git, first.store
    first.config = replace(config, project=replace(config.project, repo=config.project.repo / "later"), agents=())
    assert (first.agents, first.git, first.store) == (initial_agents, initial_git, initial_store)
    initial_store.notification_sync(state_at(config))
    assert notifications.call_args.kwargs == {
        "project_key": str(config.project.repo.resolve()), "deployment_configured": False,
    }


def test_live_store_config_and_git_ports_drive_step_and_control(config: Config) -> None:
    pipeline = Pipeline(config)
    old_store = pipeline.store
    pipeline.store = StateStore(config.project.repo / "replacement")
    pipeline.config = replace(config, execution=replace(
        config.execution, integration_verify_command_timeout_seconds=47, integration_verify_total_timeout_seconds=83,
    ))
    pipeline.git = Mock()
    pipeline.git.commit_changed_files.return_value = [("result.txt", "modified")]
    state = state_at(config)
    state.verified_main_head, state.verified_integration_head = "base", "result"
    with pipeline._common_runtime.execution_control.owned_session(state.id, "verification"):
        assert pipeline.store.load_execution_control(state.id).phase == "running"
        assert old_store.load_execution_control(state.id) is None
        with pipeline._common_runtime.steps.step(state, RunStep.VERIFY):
            assert state.verification_attempts[-1].command_timeout_seconds == 47
            assert state.verification_attempts[-1].total_timeout_seconds == 83
    assert pipeline.store.load_execution_control(state.id).phase == "finished"
    assert pipeline.store.load(state.id).group_result_history[-1].files[0].path == "result.txt"
    pipeline.git.commit_changed_files.assert_called_once()


def test_policy_scope_reuses_nested_request_resets_on_failure_and_reads_replaced_resources(config: Config) -> None:
    pipeline = Pipeline(replace(config, agents=()))
    pipeline.store = StateStore(config.project.repo / "policy-replacement")
    pipeline.agents = {agent.id: agent for agent in config.agents}
    pipeline._codex_sdk = Mock()
    state = state_at(config)
    pipeline.store.save(state)
    pipeline.store.set_effort_mode(state.id, "economy", target="planning", expected_revision=0, request_id=str(uuid.uuid4()))
    with pytest.raises(RuntimeError, match="scope failure"):
        with pipeline._common_runtime.planning_policy.scope(state, purpose="chat") as policy:
            assert policy is not None
            with pipeline._common_runtime.planning_policy.scope(state, purpose="chat") as nested:
                assert nested is policy
            assert len(pipeline.store.load_effort_policy(state.id).planning_bindings) == 1
            raise RuntimeError("scope failure")
    assert pipeline._common_runtime.planning_policy.context.get() is None
    with pipeline._common_runtime.planning_policy.scope(state, purpose="chat"):
        pass
    assert pipeline._common_runtime.planning_policy.context.get() is None
    assert [item.status for item in pipeline.store.load_effort_policy(state.id).planning_bindings] == ["failed", "finished"]


def test_stop_signal_keeps_originating_store_when_public_store_is_replaced(config: Config) -> None:
    pipeline = Pipeline(config)
    state = state_at(config)
    original = pipeline.store
    control = ExecutionControlRecord(state.id, str(uuid.uuid4()), "verification", os.getpid())
    original.save_execution_control(control)
    signal = pipeline._common_runtime.execution.tasks.stop_signal(state, scope="verification")
    assert signal is not None
    pipeline.store = StateStore(config.project.repo / "different")
    assert not signal.is_set()
    control.phase, control.stop_request_id = "stopping", str(uuid.uuid4())
    original.save_execution_control(control)
    assert signal.is_set() and signal.request_id == control.stop_request_id
    assert pipeline._common_runtime.execution.tasks.stop_signal(state, scope="verification") is None
