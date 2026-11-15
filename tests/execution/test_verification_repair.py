from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai_orchestrator.codex_sdk import CodexSdkProgress
from ai_orchestrator.config import AgentConfig, Config, ProjectConfig, ExecutionConfig
from ai_orchestrator.execution_control import ExecutionStopped
from ai_orchestrator.model_selection import CODEX_SOL_MODEL
from ai_orchestrator.models import RunState, RunStep, Stage, VerificationAttempt, WorkTask
from ai_orchestrator.pipeline import Pipeline, PipelineError


@pytest.fixture
def repair(tmp_path: Path, monkeypatch):
    planner = AgentConfig("planner", ("planning",), ("codex", "{prompt}"), provider_id="codex", model="saved-model")
    worker = AgentConfig("worker", ("general",), ("claude", "{prompt}"), provider_id="claude", model="sonnet")
    pipeline = Pipeline(Config(tmp_path / "config.toml", ProjectConfig(tmp_path), ExecutionConfig(), (planner, worker)))
    saved = []
    pipeline.store = SimpleNamespace(run_dir=lambda _run_id: tmp_path / "records", save=lambda state: saved.append(state.to_dict()))
    pipeline.git = Mock()
    pipeline.git.branch_exists.return_value = True
    pipeline.git.head.side_effect = ["candidate", "repaired"]
    worktree = tmp_path / "worktrees" / ".verification-repair"
    signal = SimpleNamespace(is_set=lambda: False, request_id="stop-repair")
    monkeypatch.setattr(type(pipeline._common_runtime.availability), 'is_available', lambda self, _agent, _purpose: True)
    monkeypatch.setattr("ai_orchestrator.integration.verification_flow.uses_shared_workspace", lambda _state: False)
    monkeypatch.setattr(pipeline._common_runtime.execution.workspace, 'run_worktree_root', lambda _state: worktree.parent)
    monkeypatch.setattr(pipeline._common_runtime.execution.workspace, 'shared_workspace_boundary', lambda _state: ("group", worktree))
    monkeypatch.setattr(pipeline._common_runtime.execution.workspace, 'ensure_worktree_clean', Mock())
    monkeypatch.setattr(
        pipeline._common_runtime.execution.verification,
        'stop_signal',
        lambda _state, *, scope: signal if scope == 'verification' else None,
    )
    monkeypatch.setattr("ai_orchestrator.integration.verification_flow.agent_command", lambda agent, _purpose: agent.command)
    monkeypatch.setattr(pipeline._common_runtime.execution.tasks, 'validate_task_change_scope', Mock())

    def invoke(**options):
        options["progress_callback"](CodexSdkProgress("running", "수정 중"))
        return "worker response"

    monkeypatch.setattr(pipeline._common_runtime.provider, 'invoke', Mock(side_effect=invoke))
    log = tmp_path / "failed.log"
    log.write_text("old prefix" + "x" * 16000, encoding="utf-8")
    attempt = VerificationAttempt(status="failed", main_head="main-before", task_heads={"done": "done-head"}, log_path=str(log))
    state = RunState(
        "repair", "plan.md", "digest", str(tmp_path), "main", Stage.FAILED, failed_step=RunStep.VERIFY,
        planning_agent_id=planner.id, verification_repair_head="candidate", verification_repair_limit=2,
        verification_attempts=[attempt],
        tasks=[WorkTask("done", "완료 결과", ["general"], expected_paths=["src/**"], forbidden_paths=["private/**"])],
    )
    return pipeline, state, worktree, signal, saved


@pytest.mark.parametrize("shared", [False, True])
def test_repair_preserves_worker_contract_and_requires_scope_before_git_publication(repair, monkeypatch, shared):
    pipeline, state, worktree, signal, saved = repair
    monkeypatch.setattr("ai_orchestrator.integration.verification_flow.uses_shared_workspace", lambda _state: shared)
    if shared:
        monkeypatch.setattr(type(pipeline._common_runtime.availability), 'is_available', lambda self, agent, _purpose: agent.id != "planner")
    original_tasks = deepcopy(state.to_dict()["tasks"])
    actions = Mock()
    actions.attach_mock(pipeline._common_runtime.execution.tasks.validate_task_change_scope, "scope")
    actions.attach_mock(pipeline.git.commit_all, "commit")
    actions.attach_mock(pipeline.git.update_branch, "publish")

    pipeline._common_runtime.execution.verification.repair_verification_failure(state, PipelineError("test assertion failed"), 1)

    options = pipeline._common_runtime.provider.invoke.call_args.kwargs
    assert options["agent"].id == ("worker" if shared else "planner")
    assert options["model"] == ("sonnet" if shared else CODEX_SOL_MODEL)
    assert options["cancel_signal"] is signal
    assert options["usage_context"].run_id == state.id
    assert options["attempt_id"] == "verification-repair-1" and options["invocation_id"]
    assert options["cwd"] == worktree
    assert options["prompt"] == Path(options["prompt_path"]).read_text(encoding="utf-8")
    assert "old prefix" not in options["prompt"] and "x" * 16000 in options["prompt"]
    assert "src/**" in options["prompt"] and "test assertion failed" in options["prompt"]
    scoped = pipeline._common_runtime.execution.tasks.validate_task_change_scope.call_args.args[0]
    assert scoped.started_commit == "candidate" and scoped.expected_paths == ["src/**"] and scoped.forbidden_paths == ["private/**"]
    assert [call[0] for call in actions.mock_calls] == (["scope", "commit"] if shared else ["scope", "commit", "publish"])
    assert state.verification_repair_head == "repaired" and saved[-1]["verification_repair_head"] == "repaired"
    assert state.verification_repair_main_head == "main-before" and state.verification_repair_task_heads == {"done": "done-head"}
    assert state.to_dict()["tasks"] == original_tasks
    assert saved[0]["verification_progress_phase"] == "repairing" and len(saved) == 3
    assert pipeline.git.discard_detached_worktree.call_count == (0 if shared else 1)


@pytest.mark.parametrize("failure", ["provider", "stop", "scope", "no_commit"])
def test_failed_or_cancelled_repair_never_publishes_a_candidate_and_cleans_owned_worktree(repair, failure):
    pipeline, state, worktree, signal, saved = repair
    expected = PipelineError
    if failure == "provider":
        pipeline._common_runtime.provider.invoke.side_effect = PipelineError("provider failed")
    elif failure == "stop":
        signal.is_set = lambda: True
        expected = ExecutionStopped
    elif failure == "scope":
        pipeline._common_runtime.execution.tasks.validate_task_change_scope.side_effect = PipelineError("scope rejected")
    else:
        pipeline.git.head.side_effect = ["candidate", "candidate"]

    with pytest.raises(expected) as caught:
        pipeline._common_runtime.execution.verification.repair_verification_failure(state, PipelineError("test failed"), 1)

    assert str(caught.value)
    assert state.verification_repair_head == "candidate" and not state.verification_repair_main_head
    assert all(item["verification_repair_head"] == "candidate" for item in saved)
    pipeline.git.update_branch.assert_not_called()
    assert pipeline.git.commit_all.call_count == (1 if failure == "no_commit" else 0)
    assert pipeline.git.discard_detached_worktree.call_args.args[0] == worktree
    if failure == "stop":
        assert caught.value.request_id == "stop-repair"


def test_missing_repair_agent_fails_before_workspace_or_provider_access(repair, monkeypatch):
    pipeline, state, _worktree, _signal, saved = repair
    monkeypatch.setattr(type(pipeline._common_runtime.availability), 'is_available', lambda self, _agent, _purpose: False)
    with pytest.raises(PipelineError, match="실행 Agent가 없습니다"):
        pipeline._common_runtime.execution.verification.repair_verification_failure(state, PipelineError("test failed"), 1)
    assert not saved
    pipeline.git.prepare_detached_worktree.assert_not_called()
    pipeline._common_runtime.provider.invoke.assert_not_called()
