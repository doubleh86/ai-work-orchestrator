"""Exercise external plan replay without a transport or an AI session."""

from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

from ai_orchestrator import pipeline_bootstrap
from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, PlanningConfig, ProjectConfig, RoutingConfig
from ai_orchestrator.models import ProfileSource, RunState, RunStep, Stage, WorkTask
from ai_orchestrator.pipeline import Pipeline, PipelineError
from ai_orchestrator.planning import source_indexes
from ai_orchestrator.planning.conversation import task_plan_draft
from ai_orchestrator.planning.contracts import Plan


def test_external_plan_replay_preserves_saved_plan_without_ai_or_connection_queries(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(pipeline_bootstrap, "current_nvidia_api_key", lambda: None)
    monkeypatch.setattr(pipeline_bootstrap, "current_claude_api_key", lambda: None)
    monkeypatch.setattr(pipeline_bootstrap, "current_nvidia_model_keys", lambda: {})
    monkeypatch.setattr(source_indexes, "ensure_planning_git_ready", lambda repository: None)
    (tmp_path / "app.py").write_text("print('fixture')\n", encoding="utf-8")
    agent = AgentConfig("worker", ("general",), (), provider_id="codex", model="gpt-6.1-sol")
    sdk = Mock()
    pipeline = Pipeline(Config(tmp_path / "config.toml", ProjectConfig(tmp_path), ExecutionConfig(), (agent,),
                               routing=RoutingConfig(review_required=False)), codex_sdk=sdk)
    pipeline.git = Mock()
    pipeline.git.head.return_value = "a" * 40
    monkeypatch.setattr(pipeline._common_runtime.provider, "invoke", Mock(side_effect=AssertionError("no AI call")))
    task = WorkTask("task", "문구 수정", ["general"], description="화면의 안내 문구를 수정한다.", expected_paths=["app.py"],
                    acceptance_criteria=["수정한 안내 문구가 표시된다."], verify_commands=[["git", "diff", "--check"]])
    request = dict(expected_base_commit="a" * 40, summary="문구 수정", requirements="화면의 안내 문구를 수정한다.",
                   task_drafts=[task_plan_draft(task)])
    run_id = "mcp-plan-" + uuid4().hex
    saved = pipeline.submit_external_plan(run_id, **request)
    assert saved.stage == Stage.PLANNED and not saved.plan_is_approved
    snapshot = pipeline.store.state_path(run_id).read_bytes()
    assert pipeline.submit_external_plan(run_id, **request).external_plan_digest == saved.external_plan_digest
    assert pipeline.store.state_path(run_id).read_bytes() == snapshot
    with pytest.raises(PipelineError, match="다른 계획"):
        pipeline.submit_external_plan(run_id, **{**request, "summary": "변경된 계획"})
    assert pipeline.store.state_path(run_id).read_bytes() == snapshot
    sdk.account_status.assert_not_called()
    sdk.close.assert_not_called()


def test_run_planning_uses_replaced_agent_mapping_when_pinning_profile(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(pipeline_bootstrap, "current_nvidia_api_key", lambda: None)
    monkeypatch.setattr(pipeline_bootstrap, "current_claude_api_key", lambda: None)
    monkeypatch.setattr(pipeline_bootstrap, "current_nvidia_model_keys", lambda: {})
    old = AgentConfig("old", ("general",), (), provider_id="codex", model="gpt-6.1-sol")
    pipeline = Pipeline(Config(tmp_path / "config.toml", ProjectConfig(tmp_path), ExecutionConfig(), (old,)))
    current = replace(old, id="current")
    pipeline.config = replace(pipeline.config, agents=(current,), planning=PlanningConfig(agent_id=current.id))
    pipeline.agents = {current.id: current}
    document = tmp_path / "planning.md"
    document.write_text("문구를 수정한다.", encoding="utf-8")
    state = RunState("reassigned", "", "", str(tmp_path), "main", Stage.REVIEWED, active_step=RunStep.PLANNING,
                     spec_snapshot_path=str(document), planning_agent_id=current.id, planning_provider_id="codex",
                     planning_model=current.model, planning_reasoning_effort="medium", planning_profile_source=ProfileSource.ROUTING)
    pipeline.store.save(state)
    task = WorkTask("task", "문구 수정", ["general"])
    monkeypatch.setattr(pipeline._common_runtime.planning.ai, "build_plan", Mock(return_value=Plan("문구 수정", False, [task])))
    result = pipeline.run_planning(state.id)
    assert result.stage == Stage.PLANNED
    assert result.planning_profile_source == ProfileSource.MODE
    assert pipeline.store.load(state.id).planning_profile_source == ProfileSource.MODE
