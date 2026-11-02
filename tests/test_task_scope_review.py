import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from ai_orchestrator.config import Config, ExecutionConfig, ProjectConfig
from ai_orchestrator.desktop_rpc import DesktopApplication
from ai_orchestrator.models import RunLockState, RunState, RunStep, Stage, TaskAction, TaskActionResult, TaskStatus, WorkTask
from ai_orchestrator.pipeline import Pipeline, PipelineError
from ai_orchestrator.task_scope_review import ERROR_MARKER, REPORT_MARKER, TaskScopeReview, stored_scope_review, task_scope_report

REPORTED_REPLY = (
    "실제 검증 로그에서 Runner 테스트 2건 실패를 확인했습니다. 수정안은 src/SampleRunner/SampleMcpAdapter.cs의 승인·임대 메타데이터 전달과 "
    "tests/SampleRunner.Tests/RunnerRuntimeTests.cs의 유효한 작업 임대 구성입니다. 현재 plan.json에는 두 파일이 허용 경로로 등록되어 있지 않습니다. "
    "repair는 작업 계약을 변경할 수 없으므로, 기존 계획 검토 절차에서 두 경로 추가를 승인해 주시겠습니까?"
)


def report(**changes) -> str:
    return REPORT_MARKER + " " + json.dumps({"reason": "요청에 승인 정보를 연결하려면 추가 파일 수정이 필요합니다.",
                                           "paths": ["src/Adapter.cs", "tests/RunnerTests.cs"], **changes}, ensure_ascii=False)


def test_structured_scope_report_roundtrips_with_contract_and_normalizes_paths() -> None:
    value = task_scope_report("현재 구현은 보존했습니다.\n" + report(paths=["src\\Adapter.cs", "src/Adapter.cs"]))
    assert value == TaskScopeReview("요청에 승인 정보를 연결하려면 추가 파일 수정이 필요합니다.", ("src/Adapter.cs",))
    assert stored_scope_review(value.error("digest")) == TaskScopeReview(value.reason, value.paths, "digest")
    assert task_scope_report(report() + "\n위 예시는 보고 형식입니다.") is None


@pytest.mark.parametrize("path", ["../Other.cs", "C:/project/Other.cs", "/tmp/Other.cs", "src/**", "src/", "src/./File.cs", "\\\\host\\file"])
def test_scope_proposal_rejects_external_or_unbounded_paths(path: str) -> None:
    with pytest.raises(ValueError):
        task_scope_report(report(paths=[path]))


@pytest.mark.parametrize("value", [report(paths=[]), report(reason=""), REPORT_MARKER + " {}", REPORT_MARKER + " invalid"])
def test_invalid_scope_report_does_not_become_no_commit(value: str) -> None:
    with pytest.raises(ValueError):
        task_scope_report(value)


def test_legacy_scope_question_is_explicit_and_never_inferred_from_a_normal_summary() -> None:
    response = "`src/Adapter.cs`가 허용 경로에 빠져 있습니다. 경로에 추가해도 될까요?"
    assert task_scope_report(response) is None
    assert task_scope_report(response, legacy=True).paths == ("src/Adapter.cs",)
    for summary in ["허용 경로 안에서 수정했습니다. 추가 승인은 필요 없습니다.", "파일이 없습니다. 추가할까요?", "검증 실패: permission denied"]:
        assert task_scope_report(summary, legacy=True) is None


def test_exact_reported_approval_request_preserves_both_required_paths() -> None:
    review = task_scope_report(REPORTED_REPLY, legacy=True)
    assert review is not None
    assert review.paths == ("src/SampleRunner/SampleMcpAdapter.cs", "tests/SampleRunner.Tests/RunnerRuntimeTests.cs")
    assert review.reason == REPORTED_REPLY


@pytest.fixture
def blocked(tmp_path: Path):
    pipeline = Pipeline(Config(path=tmp_path / "config.toml", project=ProjectConfig(repo=tmp_path),
                               execution=ExecutionConfig(), agents=()))
    task = WorkTask("adapter", "MCP 연결", ["general"], status=TaskStatus.FAILED, failed_action=TaskAction.EXECUTE,
                    expected_paths=["src/Contracts.cs"], last_attempt_id="current")
    task.error = task_scope_report(report()).error(pipeline._task_scope_contract_digest(task))
    task.action_results = [TaskActionResult("execute", attempt_id="current", status="failed", error=task.error, worker_response=report())]
    state = RunState("scope", "plan", "digest", str(tmp_path), "main", Stage.FAILED, tasks=[task], failed_step=RunStep.AGENT_EXECUTION)
    pipeline.store.save(state)
    return pipeline, state, task


def test_scope_review_context_survives_reload_without_mutating_contract_or_history(blocked) -> None:
    pipeline, state, task = blocked
    before = pipeline.store.state_path(state.id).read_bytes()
    context = pipeline.task_retry_context(state.id, task.id)
    assert context["error"].startswith(ERROR_MARKER)
    assert context["response"] == report()
    assert context["can_save"]
    assert not context["recovery"]["can_execute"]
    assert context["recovery"]["reason_code"] == "task_scope_review_required"
    assert pipeline.store.state_path(state.id).read_bytes() == before


def test_status_rpc_projects_the_reported_legacy_error_without_changing_raw_history(blocked) -> None:
    pipeline, state, task = blocked
    task.error = "agent codex-general produced no commit for runner-scoped-mcp-gate"
    task.action_results[-1].error = task.error
    task.action_results[-1].worker_response = REPORTED_REPLY
    pipeline.store.save(state)
    original = pipeline.store.state_path(state.id).read_bytes()
    application = DesktopApplication(Mock(), codex_sdk=Mock())
    with patch.object(application, "_pipeline", return_value=pipeline), \
            patch.object(pipeline, "status_with_controls", return_value=(state, None, None)), \
            patch.object(pipeline, "latest_main_operations", return_value={}), \
            patch.object(pipeline, "effort_control", return_value={}), \
            patch.object(pipeline, "waiting_prompt", return_value=None):
        result = application.status("sample", state.id)
    visible = result["tasks"][0]
    assert visible["error"].startswith(ERROR_MARKER)
    assert stored_scope_review(visible["error"]).paths == (
        "src/SampleRunner/SampleMcpAdapter.cs", "tests/SampleRunner.Tests/RunnerRuntimeTests.cs",
    )
    assert visible["action_results"][-1]["error"] == task.error
    assert visible["action_results"][-1]["worker_response"] == REPORTED_REPLY
    assert task.error == "agent codex-general produced no commit for runner-scoped-mcp-gate"
    assert pipeline.store.state_path(state.id).read_bytes() == original


def test_status_projection_does_not_guess_unknown_or_previous_responses(blocked) -> None:
    pipeline, state, task = blocked
    task.error = "agent worker produced no commit for adapter"
    task.action_results[-1].worker_response = "검증 기록을 확인해 주세요."
    assert pipeline.task_failure_message(task) == task.error
    task.action_results[-1].worker_response = REPORTED_REPLY
    task.action_results[-1].attempt_id = "previous"
    assert pipeline.task_failure_message(task) == task.error


def test_same_contract_cannot_repeat_through_executor_or_chat_repair(blocked) -> None:
    pipeline, state, task = blocked
    with patch.object(pipeline, "_run_task_attempt") as attempt:
        with pytest.raises(PipelineError, match=ERROR_MARKER):
            pipeline._run_task(state, task)
    attempt.assert_not_called()
    with patch.object(pipeline, "_execute") as execute:
        with pytest.raises(PipelineError, match=ERROR_MARKER):
            pipeline.repair_task_from_chat(state.id, task.id, request_id=str(uuid4()), message="고쳐서 계속해",
                fingerprint=pipeline.task_retry_context(state.id, task.id)["fingerprint"], conversation_revision=0)
    execute.assert_not_called()
    assert pipeline.store.load_revision_requests(state.id) == []


def test_project_chat_keeps_scope_review_as_a_user_decision_instead_of_repeated_repair(blocked) -> None:
    pipeline, state, task = blocked
    control = SimpleNamespace(can_stop=False, lock_state=RunLockState.UNLOCKED)
    integration = SimpleNamespace(can_verify=False)
    assert pipeline._project_chat_actions(state, control, integration, 0) == ["reply", "ask"]
    with patch.object(pipeline, "_begin_effort_execution") as binding:
        with pytest.raises(PipelineError, match=ERROR_MARKER):
            pipeline._execute(state, manual=False)
    binding.assert_not_called()


def test_only_scope_update_covering_requested_paths_releases_wait(blocked) -> None:
    pipeline, state, task = blocked
    task.model = "new-model"
    task.expected_paths.append("unrelated.cs")
    assert pipeline._task_scope_review(task) is not None
    task.expected_paths.extend(["src/Adapter.cs", "tests/RunnerTests.cs"])
    task.forbidden_paths = ["tests/**"]
    assert pipeline._task_scope_review(task) is not None
    task.forbidden_paths = []
    assert pipeline._task_scope_review(task) is None
    assert pipeline._task_recovery_capability(state, task, can_execute=True)["can_execute"]


def test_legacy_no_commit_uses_only_the_current_failed_implementation_response(blocked) -> None:
    pipeline, state, task = blocked
    task.error = "agent worker produced no commit for adapter"
    task.action_results[-1].worker_response = "src/Adapter.cs가 허용 경로에 빠져 있습니다. 추가해도 될까요?"
    assert pipeline._task_scope_review(task) is not None
    task.action_results[-1].attempt_id = "old"
    assert pipeline._task_scope_review(task) is None
    task.action_results[-1].attempt_id = "current"
    task.failed_action = TaskAction.VERIFY
    assert pipeline._task_scope_review(task) is None
