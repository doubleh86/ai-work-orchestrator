from copy import deepcopy
from pathlib import Path
import subprocess
import uuid
from unittest.mock import Mock

import pytest

from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, ProjectConfig, create_default_config, load_config
from ai_orchestrator.git import GitError
from ai_orchestrator.models import RunState, RunStep, Stage, TaskAction, TaskActionResult, TaskStatus, WorkTask
from ai_orchestrator.pipeline import Pipeline, TaskVerificationFailure, TaskVerificationTimeout


@pytest.fixture
def verification(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    agent = AgentConfig("worker", ("general",), ())
    pipeline = Pipeline(Config(tmp_path / "config.toml", ProjectConfig(repo), ExecutionConfig(), (agent,)))
    task = WorkTask("slow", "전체 테스트", ["general"], worktree=str(work), agent_id="worker",
                    status=TaskStatus.FAILED, failed_action=TaskAction.VERIFY, verify_commands=[["test", "suite"]])
    state = RunState("timeout-test", "", "digest", str(repo), "main", stage=Stage.FAILED,
                     failed_step=RunStep.AGENT_EXECUTION, plan_revision=1, plan_approved_revision=1,
                     tasks=[WorkTask("done", "완료", ["general"], status=TaskStatus.COMPLETED, completed_commit="d" * 40), task])
    state.refresh_task_readiness()
    pipeline.store.save(state)
    (pipeline.store.run_dir(state.id) / "logs").mkdir(exist_ok=True)
    head = ["a" * 40]
    monkeypatch.setattr(pipeline.git, "head", lambda *_args, **_kwargs: head[0])
    monkeypatch.setattr(pipeline.git, "task_changed_paths", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(pipeline.git, "commit_changed_files", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(pipeline, "_ensure_worktree_clean", lambda *_args: None)
    monkeypatch.setattr(pipeline, "_refresh_task_code_style_evidence", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(pipeline, "_prepare_verification_command", lambda command, *_args: command)
    return pipeline, state, task, head


def test_defaults_fallback_and_explicit_timeout_configuration(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    path = create_default_config(tmp_path / "config.toml", repo)
    config = load_config(path)
    assert (config.execution.task_verify_command_timeout_seconds, config.execution.task_verify_total_timeout_seconds) == (900, 1800)
    original = path.read_text(encoding="utf-8")
    path.write_text(original.replace("task_verify_command_timeout_seconds = 900\n", "")
                    .replace("task_verify_total_timeout_seconds = 1800\n", ""), encoding="utf-8")
    config = load_config(path)
    assert (config.execution.task_verify_command_timeout_seconds, config.execution.task_verify_total_timeout_seconds) == (900, 1800)
    path.write_text(original.replace("task_verify_command_timeout_seconds = 900", "task_verify_command_timeout_seconds = 60")
                    .replace("task_verify_total_timeout_seconds = 1800", "task_verify_total_timeout_seconds = 120"), encoding="utf-8")
    config = load_config(path)
    assert (config.execution.task_verify_command_timeout_seconds, config.execution.task_verify_total_timeout_seconds) == (60, 120)


def test_normal_verification_longer_than_five_minutes_can_finish_without_any_agent(verification, monkeypatch):
    pipeline, state, task, _ = verification
    preserved = deepcopy(state.tasks[0])
    clock = [0.0]
    monkeypatch.setattr("ai_orchestrator.pipeline.time.monotonic", lambda: clock[0])
    worker = Mock(side_effect=AssertionError("verification must not invoke an implementation or review agent"))
    monkeypatch.setattr(pipeline, "_invoke_agent", worker)

    def run(command, *_args, **kwargs):
        assert kwargs["timeout_seconds"] == 900
        clock[0] = 400.0
        return subprocess.CompletedProcess(command, 0, "all tests passed")

    monkeypatch.setattr("ai_orchestrator.pipeline.run_command", run)
    pipeline._run_task(state, task, TaskAction.VERIFY)
    assert task.action_results[-1].status == "succeeded"
    assert task.action_results[-1].passed_commands == [["test", "suite"]]
    assert task.completed_commit == "a" * 40
    assert state.tasks[0] == preserved
    worker.assert_not_called()


def timeout(_command, *_args, **_kwargs):
    raise GitError("command timed out after 900s: test suite\npartial progress")


def test_timeout_is_preserved_as_incomplete_and_never_starts_code_repair(verification, monkeypatch):
    pipeline, state, task, _ = verification
    worker = Mock()
    monkeypatch.setattr(pipeline, "_invoke_agent", worker)
    monkeypatch.setattr("ai_orchestrator.pipeline.run_command", timeout)
    with pytest.raises(TaskVerificationTimeout, match="완료 여부 미확인"):
        pipeline._run_task(state, task, TaskAction.VERIFY)
    assert task.status != TaskStatus.COMPLETED
    assert task.failed_action == TaskAction.VERIFY
    result = task.action_results[-1]
    assert result.status == "failed" and result.verification_failure_kind == "timeout"
    assert result.passed_commands == [] and not task.completed_commit
    assert result.verification_context_digest
    archived = pipeline.store.run_dir(state.id) / "logs" / f"slow-verify-{result.attempt_id}.log"
    assert "partial progress" in archived.read_text(encoding="utf-8")
    worker.assert_not_called()


@pytest.mark.parametrize("change", ["none", "head", "command", "command_limit", "total_limit", "environment"])
def test_same_timeout_is_not_reexecuted_until_verification_conditions_change(verification, monkeypatch, change):
    pipeline, state, task, head = verification
    if change == "environment":
        task.verify_commands = [["dotnet", "test", "Suite.sln"]]
    run = Mock(side_effect=timeout)
    monkeypatch.setattr("ai_orchestrator.pipeline.run_command", run)
    with pytest.raises(TaskVerificationTimeout):
        pipeline._run_task_verification(state, task)
    assert run.call_count == 1
    # Exercise persistence, rather than relying only on in-memory exception metadata.
    state = pipeline.store.load(state.id)
    task = state.tasks[1]
    kwargs = {}
    if change == "head":
        head[0] = "b" * 40
    elif change == "command":
        task.verify_commands = [["test", "another-suite"]]
    elif change == "command_limit":
        state.task_verify_command_timeout_seconds = 1200
    elif change == "total_limit":
        state.task_verify_total_timeout_seconds = 2400
    elif change == "environment":
        kwargs["environment_overrides"] = {"MSBUILDUSESERVER": "0"}
    run.side_effect = None
    run.return_value = subprocess.CompletedProcess([], 0, "passed")
    if change == "none":
        with pytest.raises(TaskVerificationTimeout, match="같은 검증 조건"):
            pipeline._run_task_verification(state, task)
        assert run.call_count == 1
        assert task.action_results[-1].status == "failed"
    else:
        pipeline._run_task_verification(state, task, **kwargs)
        assert run.call_count == 2
        assert task.action_results[-1].status == "succeeded"


def test_total_budget_includes_command_preparation_and_does_not_start_an_overdue_command(verification, monkeypatch):
    pipeline, state, task, _ = verification
    state.task_verify_total_timeout_seconds = 30
    clock = [0.0]
    monkeypatch.setattr("ai_orchestrator.pipeline.time.monotonic", lambda: clock[0])

    def prepare(command, *_args):
        clock[0] = 31.0
        return command

    monkeypatch.setattr(pipeline, "_prepare_verification_command", prepare)
    run = Mock()
    monkeypatch.setattr("ai_orchestrator.pipeline.run_command", run)
    with pytest.raises(TaskVerificationTimeout):
        pipeline._run_task_verification(state, task)
    run.assert_not_called()
    assert task.action_results[-1].verification_failure_kind == "timeout"
    clock[0] = 0.0
    with pytest.raises(TaskVerificationTimeout, match="같은 검증 조건"):
        pipeline._run_task_verification(state, task)
    run.assert_not_called()
    state.task_verify_total_timeout_seconds = 60
    run.return_value = subprocess.CompletedProcess([], 0, "passed")
    pipeline._run_task_verification(state, task)
    assert run.call_count == 1
    assert task.action_results[-1].status == "succeeded"


def test_nonzero_test_exit_is_a_real_failure_not_a_timeout(verification, monkeypatch):
    pipeline, state, task, _ = verification
    monkeypatch.setattr("ai_orchestrator.pipeline.run_command", lambda *args, **kwargs: subprocess.CompletedProcess([], 1, "failed test"))
    with pytest.raises(TaskVerificationFailure):
        pipeline._run_task_verification(state, task)
    result = task.action_results[-1]
    assert result.verification_failure_kind == "command_failed"
    assert result.status == "failed" and result.passed_commands == []


def test_task_action_metadata_reads_legacy_records_without_inventing_a_repeated_failure(verification):
    _, state, task, _ = verification
    task.action_results = [TaskActionResult("verify", status="failed", verification_context_digest="context",
                                          verification_failure_kind="timeout")]
    restored = RunState.from_dict(state.to_dict())
    assert restored.tasks[1].action_results[0] == task.action_results[0]
    legacy = state.to_dict()
    result = legacy["tasks"][1]["action_results"][0]
    result.pop("verification_context_digest")
    result.pop("verification_failure_kind")
    old = RunState.from_dict(legacy).tasks[1].action_results[0]
    assert old.verification_context_digest == old.verification_failure_kind == ""


def test_chat_timeout_recovery_extends_saved_limits_and_dispatches_only_verification(verification, monkeypatch):
    pipeline, state, task, _ = verification
    state.task_verify_command_timeout_seconds = 300
    state.task_verify_total_timeout_seconds = 600
    task.error = "command timed out after 300s: dotnet test Suite.sln"
    pipeline.store.save(state)
    preserved = deepcopy(state.tasks[0])

    def execute(current, **_kwargs):
        assert current.tasks[1].failed_action == TaskAction.VERIFY
        assert (current.task_verify_command_timeout_seconds, current.task_verify_total_timeout_seconds) == (900, 1800)
        assert current.tasks[0] == preserved
        assert current.tasks[1].verify_commands == [["test", "suite"]]
        return current

    run = Mock(side_effect=execute)
    monkeypatch.setattr(pipeline, "_execute", run)
    request = dict(request_id=str(uuid.uuid4()), message="고쳐서 계속해줘",
                   fingerprint=pipeline.task_retry_context(state.id, task.id)["fingerprint"], conversation_revision=0)
    pipeline.repair_task_from_chat(state.id, task.id, **request)
    pipeline.repair_task_from_chat(state.id, task.id, **request)
    assert run.call_count == 1


def test_policy_refresh_does_not_silently_change_an_existing_run(verification):
    pipeline, state, _, _ = verification
    state.task_verify_command_timeout_seconds = 300
    state.task_verify_total_timeout_seconds = 600
    pipeline._ensure_verification_policy(state)
    assert (state.task_verify_command_timeout_seconds, state.task_verify_total_timeout_seconds) == (300, 600)
    state.task_verify_command_timeout_seconds = 1200
    state.task_verify_total_timeout_seconds = 2400
    pipeline._extend_task_timeout_for_recovery(state)
    assert (state.task_verify_command_timeout_seconds, state.task_verify_total_timeout_seconds) == (1200, 2400)


def test_explicit_task_retry_also_extends_timeout_without_restarting_implementation(verification, monkeypatch):
    pipeline, state, task, _ = verification
    state.task_verify_command_timeout_seconds = 300
    state.task_verify_total_timeout_seconds = 600
    task.error = "command timed out after 300s: test suite"
    pipeline.store.save(state)

    def execute(current, **kwargs):
        assert kwargs["selected_task_ids"] == {task.id}
        assert current.tasks[1].failed_action == TaskAction.VERIFY
        assert (current.task_verify_command_timeout_seconds, current.task_verify_total_timeout_seconds) == (900, 1800)
        return current

    run = Mock(side_effect=execute)
    monkeypatch.setattr(pipeline, "_execute", run)
    pipeline.retry_task(state.id, task.id)
    run.assert_called_once()


def test_timing_noise_is_the_same_failure_but_changed_error_and_command_are_distinct(tmp_path):
    def error(text, command=("dotnet", "test")):
        return TaskVerificationFailure("task", command, text, tmp_path / "error.log")

    first = error("[xUnit.net 00:00:02.0] Test [FAIL]\nExpected: 1\nActual: 2\nTime Elapsed: 00:00:02")
    second = error("[xUnit.net 00:00:40.2] Test [FAIL]\nExpected: 1\nActual: 2\nTime Elapsed: 00:00:40")
    fingerprint = Pipeline._task_verification_failure_fingerprint
    assert fingerprint(first) == fingerprint(second)
    assert fingerprint(first) != fingerprint(error(second.output.replace("Actual: 2", "Actual: 3")))
    assert fingerprint(first) != fingerprint(error(second.output, ("dotnet", "build")))


@pytest.mark.parametrize("limits,expected_kind", [((300,600), "verify_with_timeout_adjustment"), ((900,1800), "diagnose")])
def test_recovery_capability_reports_real_limits_and_repeat_guard(verification, monkeypatch, limits, expected_kind):
    pipeline, state, task, head = verification
    state.task_verify_command_timeout_seconds, state.task_verify_total_timeout_seconds = limits
    monkeypatch.setattr("ai_orchestrator.pipeline.run_command", timeout)
    with pytest.raises(TaskVerificationTimeout):
        pipeline._run_task_verification(state, task)
    current = pipeline.store.load(state.id)
    current.tasks[1].active_action = None
    current.tasks[1].status = TaskStatus.FAILED
    pipeline.store.save(current)
    context = pipeline.task_retry_context(state.id, task.id)["recovery"]
    assert context["kind"] == expected_kind
    assert context["current_limits"] == list(limits)
    assert context["proposed_limits"] == [900,1800]
    assert context["will_change"] == (limits != (900,1800))
    assert context["can_execute"] == (expected_kind != "diagnose")
    head[0] = "b" * 40
    changed = pipeline.task_retry_context(state.id, task.id)["recovery"]
    assert changed["fingerprint"] != context["fingerprint"]
    assert changed["can_execute"]
    assert "head" in changed["changed_factors"]


def test_changed_recovery_conditions_are_rejected_before_instruction_or_execution(verification, monkeypatch):
    pipeline, state, task, head = verification
    task.error = "command timed out after 300s: test suite"
    state.task_verify_command_timeout_seconds = 300
    pipeline.store.save(state)
    context = pipeline.task_retry_context(state.id, task.id)
    head[0] = "b" * 40
    execute = Mock()
    monkeypatch.setattr(pipeline, "_execute", execute)
    with pytest.raises(Exception, match="조회 후 검증 조건"):
        pipeline.repair_task_from_chat(state.id, task.id, request_id=str(uuid.uuid4()), message="고쳐서 계속해줘",
            fingerprint=context["fingerprint"], conversation_revision=state.planning_conversation_revision,
            recovery_fingerprint=context["recovery"]["fingerprint"])
    execute.assert_not_called()
    assert pipeline.store.load_revision_requests(state.id) == []
