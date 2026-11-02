import json
import sys
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from ai_orchestrator.codex_sdk import CodexSdkAccountStatus, CodexSdkError
from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, PlanningConfig, ProjectConfig, RoutingConfig
from ai_orchestrator.desktop_rpc import DesktopApplication, RpcError, _expanded_provider_choices
from ai_orchestrator.models import PlanningMode, RunState, Stage, TaskAction, TaskStatus, WorkTask
from ai_orchestrator.pipeline import Pipeline
from ai_orchestrator.planner import PLAN_MARKER, Plan, PlanningError, assign_plan_agents


@pytest.fixture
def connection_pipeline(tmp_path, monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    sdk = Mock()
    sdk.account_status.return_value = CodexSdkAccountStatus(False, "none", "로그인 필요")
    pipeline = Pipeline(Config(
        path=tmp_path / "config.toml", project=ProjectConfig(tmp_path), execution=ExecutionConfig(),
        planning=PlanningConfig(agent_id="codex-planner"), agents=(
            AgentConfig("codex-planner", ("planning",), (), provider_id="codex"),
            AgentConfig("codex-worker", ("general",), (), provider_id="codex"),
            AgentConfig("claude-general", ("general",), (sys.executable, "-c", "pass"), provider_id="claude"),
            AgentConfig("local", ("general",), (sys.executable, "-c", "pass"), provider_id="local"),
        ),
    ), codex_sdk=sdk)
    monkeypatch.setattr(pipeline, "_resolve_executable", lambda _command: "fixture.exe")
    monkeypatch.setattr(pipeline, "_claude_auth_status", Mock(return_value=(False, "none", "로그인 필요")))
    return pipeline, sdk


@pytest.mark.parametrize("codex", [True, False, None])
@pytest.mark.parametrize("claude", [True, False, None])
def test_planning_and_execution_hide_disconnected_and_unknown_authentication(connection_pipeline, codex, claude):
    pipeline, sdk = connection_pipeline
    original = pipeline.config
    if codex is None:
        sdk.account_status.side_effect = CodexSdkError("fixture authentication lookup failed")
    else:
        sdk.account_status.return_value = CodexSdkAccountStatus(codex, "chatgpt" if codex else "none", "fixture")
    pipeline._claude_auth_status.return_value = (claude, "claude_subscription" if claude else "none", "fixture")
    expected = {"local"}
    if codex is True:
        expected.add("codex")
    if claude is True:
        expected.add("claude")
    planning = pipeline.planning_provider_choices()
    execution = pipeline.execution_provider_choices(["backend"])
    assert {choice.provider_id for choice in planning} == expected
    assert {choice.provider_id for choice in execution} == expected
    assert {profile["provider_id"] for profile in _expanded_provider_choices(planning)} == expected
    assert sdk.account_status.call_count == 2
    assert pipeline._claude_auth_status.call_count == 2
    sdk.run_turn.assert_not_called()
    assert pipeline.config is original
    assert not original.path.exists()


def test_reconnection_and_key_removal_change_choices_without_reassigning_configuration(connection_pipeline, monkeypatch):
    pipeline, sdk = connection_pipeline
    assert {choice.provider_id for choice in pipeline.execution_provider_choices(["general"])} == {"local"}
    sdk.account_status.return_value = CodexSdkAccountStatus(True, "chatgpt", "로그인됨")
    pipeline._claude_auth_status.return_value = (True, "claude_subscription", "로그인됨")
    monkeypatch.setenv("NVIDIA_API_KEY", "fixture-key-not-real")
    assert {choice.provider_id for choice in pipeline.execution_provider_choices(["general"])} == {"codex", "claude", "nvidia", "local"}
    assert {choice.provider_id for choice in pipeline.planning_provider_choices()} == {"codex", "claude", "local"}
    monkeypatch.delenv("NVIDIA_API_KEY")
    assert "nvidia" not in {choice.provider_id for choice in pipeline.execution_provider_choices(["general"])}
    assert pipeline.config.planning.agent_id == "codex-planner"
    assert pipeline.agents["claude-general"].provider_id == "claude"
    sdk.run_turn.assert_not_called()


def test_unconnected_choices_can_be_empty_while_connection_management_retains_providers(connection_pipeline):
    pipeline, sdk = connection_pipeline
    pipeline.config = replace(pipeline.config, agents=tuple(agent for agent in pipeline.config.agents if agent.provider_id != "local"))
    assert pipeline.planning_provider_choices() == []
    assert pipeline.execution_provider_choices(["general"]) == []
    assert {status.id for status in pipeline.provider_statuses()} == {"codex", "claude", "nvidia"}
    sdk.run_turn.assert_not_called()


def test_missing_nvidia_cli_hides_key_configured_profiles(connection_pipeline, monkeypatch):
    pipeline, _sdk = connection_pipeline
    monkeypatch.setenv("NVIDIA_API_KEY", "fixture-key-not-real")
    monkeypatch.setattr(pipeline, "_resolve_executable", lambda command: "" if command == "opencode" else "fixture.exe")
    assert "nvidia" not in {choice.provider_id for choice in pipeline.execution_provider_choices(["general"])}


def test_custom_provider_keeps_eligible_agents_when_another_custom_agent_is_missing(connection_pipeline, monkeypatch):
    pipeline, _sdk = connection_pipeline
    missing = AgentConfig("missing-local", ("general",), ("missing-local-cli",), provider_id="local")
    pipeline.config = replace(pipeline.config, agents=(*pipeline.config.agents, missing))
    monkeypatch.setattr(pipeline, "_resolve_executable", lambda command: "" if command == "missing-local-cli" else "fixture.exe")
    assert [choice.agent_id for choice in pipeline.execution_provider_choices(["general"])] == ["local"]
    assert [choice.agent_id for choice in pipeline.planning_provider_choices()] == ["local"]


def test_stale_desktop_selections_are_rechecked_without_reassigning_saved_tasks(connection_pipeline):
    pipeline, _sdk = connection_pipeline
    task = WorkTask("task", "Saved task", ["general"], agent_id="claude-general", provider_id="claude", model="sonnet")
    with pytest.raises(RpcError):
        DesktopApplication._desktop_planning_agent_id(pipeline, "claude-general")
    with patch.object(pipeline, "status", return_value=SimpleNamespace(tasks=[task])):
        with pytest.raises(RpcError):
            DesktopApplication._ensure_desktop_execution_profiles(pipeline, "run", {})
    assert (task.agent_id, task.model) == ("claude-general", "sonnet")
    pipeline._claude_auth_status.return_value = (True, "claude_subscription", "로그인됨")
    assert DesktopApplication._desktop_planning_agent_id(pipeline, "claude-general") == "claude-general"
    with patch.object(pipeline, "status", return_value=SimpleNamespace(tasks=[task])):
        DesktopApplication._ensure_desktop_execution_profiles(pipeline, "run", {})
        pipeline._claude_auth_status.return_value = (False, "none", "로그인 필요")
        task.status = TaskStatus.COMPLETED
        DesktopApplication._ensure_desktop_execution_profiles(pipeline, "run", {})
    assert (task.agent_id, task.model) == ("claude-general", "sonnet")


@pytest.mark.parametrize("codex,claude,expected", [
    (True, True, ["codex", "claude"] * 2),
    (True, False, ["codex"] * 4),
    (False, True, ["claude"] * 4),
    (None, True, ["claude"] * 4),
    (True, None, ["codex"] * 4),
    (False, False, []),
])
def test_planning_assignment_balances_only_connected_providers(connection_pipeline, codex, claude, expected):
    pipeline, sdk = connection_pipeline
    pipeline.config = replace(pipeline.config, routing=RoutingConfig(default_provider="codex"),
                              agents=tuple(agent for agent in pipeline.config.agents if agent.provider_id != "local"))
    if codex is None:
        sdk.account_status.side_effect = CodexSdkError("fixture authentication lookup failed")
    else:
        sdk.account_status.return_value = CodexSdkAccountStatus(codex, "fixture", "fixture")
    pipeline._claude_auth_status.return_value = (claude, "fixture", "fixture")
    agents = pipeline._planning_execution_agents()
    payload = {"summary": "구현", "server_work": False, "source_paths": [], "instruction_paths": [], "questions": [], "tasks": [
        {"id": f"task-{index}", "title": "구현", "description": "설명", "capabilities": ["backend"], "depends_on": [],
         "acceptance_criteria": ["검증 통과"], "expected_paths": [f"src/{index}.py"], "forbidden_paths": [],
         "verify_commands": [["python", "-m", "unittest"]], "risk_level": "low"} for index in range(4)
    ]}

    def validate():
        return pipeline._validated_planning_plan(
            f"{PLAN_MARKER} " + json.dumps(payload), source_root=None, source_index=None, required_instruction_paths=set(),
            execution_agents=agents, planning_mode=PlanningMode.DIRECTED, require_directory_task_draft=False, sequential=True,
        )

    if expected:
        assert [task.provider_id for task in validate().tasks] == expected
    else:
        with pytest.raises(PlanningError, match="no available execution agent"):
            validate()
    assert sdk.account_status.call_count == 1
    assert pipeline._claude_auth_status.call_count == 1
    sdk.run_turn.assert_not_called()
    assert not pipeline.config.path.exists()


def test_automatically_assigned_tasks_dispatch_to_both_connected_ais(connection_pipeline):
    pipeline, sdk = connection_pipeline
    pipeline.config = replace(pipeline.config, agents=tuple(agent for agent in pipeline.config.agents if agent.provider_id != "local"))
    sdk.account_status.return_value = CodexSdkAccountStatus(True, "chatgpt", "로그인됨")
    pipeline._claude_auth_status.return_value = (True, "claude_subscription", "로그인됨")
    plan = Plan("실행", False, [WorkTask(str(index), "구현", ["backend"]) for index in range(4)])
    assign_plan_agents(plan, pipeline.config.agents, RoutingConfig(default_provider="codex"),
                       execution_agent_ids={agent.id for agent in pipeline._planning_execution_agents()}, sequential=True)
    root = pipeline.config.project.repo
    state = RunState("dispatch", "", "", str(root), "main", stage=Stage.PLANNED, tasks=plan.tasks)
    with patch.object(pipeline, "_invoke_provider_command", return_value="모의 실행 완료") as invoke:
        for task in plan.tasks:
            task.worktree = str(root)
            assert pipeline._invoke_agent(state, task, pipeline.agents[task.agent_id], "구현", root / "test.log", TaskAction.EXECUTE)
    assert [call.kwargs["agent"].provider_id for call in invoke.call_args_list] == ["codex", "claude"] * 2
    assert all(call.kwargs["action"] == "execute" for call in invoke.call_args_list)
    sdk.run_turn.assert_not_called()
    assert not (root / "test.log").exists()
