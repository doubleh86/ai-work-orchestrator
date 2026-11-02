from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
import uuid

import pytest

from ai_orchestrator.codex_sdk import CodexSdkError, CodexSdkExecutionProfile, CodexSdkProgress, CodexSdkTimeout
from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, PlanningConfig, ProjectConfig
from ai_orchestrator.execution_control import ExecutionStopped
from ai_orchestrator.models import RunState, Stage
from ai_orchestrator.pipeline import Pipeline, PipelineError, ProviderTimeoutError
from ai_orchestrator.usage import TokenCounts, UsageContext, UsageObservation, usage_now


def pipeline(root: Path) -> Pipeline:
    agent = AgentConfig("planner", ("general",), (), provider_id="codex", model="gpt-6.1-sol")
    result = Pipeline(Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=root), execution=ExecutionConfig(),
                             agents=(agent,), planning=PlanningConfig(agent_id=agent.id)), codex_sdk=Mock())
    result.store.save(RunState("group", "plan.md", "digest", str(root), "main", Stage.REVIEWED))
    return result


def invoke(result: Pipeline, root: Path, context: UsageContext) -> str:
    return result._invoke_provider_command(
        agent=result.agents["planner"], command_template=(), replacements={"{run_id}": "group"},
        cwd=root, prompt="plan", prompt_path=str(root / "prompt.md"), log_path=root / "agent.log",
        action="planning", task_id="planning", model="gpt-6.1-sol", usage_context=context,
    )


def test_actual_callbacks_keep_frozen_context_and_effective_model(tmp_path: Path) -> None:
    result = pipeline(tmp_path)
    operation, policy = str(uuid.uuid4()), str(uuid.uuid4())
    context = UsageContext("group", "chat", operation_request_id=operation, policy_id=policy, mode="economy")
    def sdk(request):
        result.store.set_effort_mode("group", "focused", target="planning", expected_revision=0, request_id=str(uuid.uuid4()))
        request.profile_callback(CodexSdkExecutionProfile("gpt-effective", "low", False, False))
        request.usage_callback(UsageObservation(1, TokenCounts(100, 20, 120), source_kind="turn_total",
                                              missing_reason="", observed_at=usage_now(), finalized=True))
        return "answer"
    result._codex_sdk.run_turn.side_effect = sdk
    assert invoke(result, tmp_path, context) == "answer"
    snapshot = result.usage("group")
    row = snapshot["records"][0]
    assert row["mode"] == "economy"
    assert row["policy_id"] == policy and row["operation_request_id"] == operation
    assert row["model_effective"] == "gpt-effective"
    assert row["model_requested"] == "gpt-6.1-sol"
    assert row["outcome"] == "completed"
    assert snapshot["summary"]["total_tokens"] == 120


@pytest.mark.parametrize("error,outcome", [
    (CodexSdkError("failed"), "failed"), (CodexSdkTimeout("timeout"), "interrupted"), (ExecutionStopped("stop"), "cancelled"),
])
def test_failed_and_late_usage_preserve_invocation_outcome(tmp_path: Path, error: Exception, outcome: str) -> None:
    result = pipeline(tmp_path)
    requests = []
    def sdk(request):
        requests.append(request)
        request.usage_callback(UsageObservation(1, TokenCounts(10, 2, 12), source_kind="turn_total",
                                              missing_reason="", observed_at=usage_now()))
        raise error
    result._codex_sdk.run_turn.side_effect = sdk
    with pytest.raises((PipelineError, ProviderTimeoutError, ExecutionStopped)):
        invoke(result, tmp_path, UsageContext("group", "recovery_planning"))
    requests[0].usage_callback(UsageObservation(2, TokenCounts(20, 4, 24), source_kind="turn_total",
                                               missing_reason="", observed_at=usage_now(), finalized=True))
    snapshot = result.usage("group")
    assert snapshot["records"][0]["outcome"] == outcome
    assert snapshot["summary"]["total_tokens"] == 24
    assert snapshot["summary"]["call_count"] == 1


def test_no_structured_usage_and_non_ai_operations_remain_unavailable(tmp_path: Path) -> None:
    result = pipeline(tmp_path)
    assert result.usage("group")["summary"]["call_count"] == 0
    result._codex_sdk.run_turn.return_value = "answer"
    invoke(result, tmp_path, UsageContext("group", "verification_repair"))
    row = result.usage("group")["records"][0]
    assert row["total_tokens"] is None
    assert row["missing_reason"] == "provider_not_reported"
    assert row["mode"] is None


def test_purpose_from_planning_binding_ignores_execution_reservation(tmp_path: Path) -> None:
    result = pipeline(tmp_path)
    state = result.store.load("group")
    state.planning_agent_id = "planner"
    state.planning_model = "gpt-6.1-sol"
    result.store.save(state)
    result.store.set_effort_mode("group", "balanced", target="planning", expected_revision=0, request_id=str(uuid.uuid4()))
    result.store.set_effort_mode("group", "focused", target="next_execution", expected_revision=1, request_id=str(uuid.uuid4()))
    result._codex_sdk.run_turn.return_value = "answer"
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text("Plan", encoding="utf-8")
    with result._planning_effort_scope(state, purpose="recovery_planning"):
        result._invoke_planning_agent(state, result.agents["planner"], "Plan", prompt_path, tmp_path / "agent.log")
    row = result.usage("group")["records"][0]
    assert row["purpose"] == "recovery_planning" and row["mode"] == "balanced"
    assert row["operation_request_id"] and row["policy_id"]
    assert result.store.load_effort_policy("group").pending_execution_mode.value == "focused"
