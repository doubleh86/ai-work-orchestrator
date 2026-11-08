from __future__ import annotations

import io
import json
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock, Thread
from unittest.mock import Mock, patch

import pytest

from ai_orchestrator.desktop_rpc import DesktopApplication, RpcError, RpcService, handle_request, serve
from ai_orchestrator.models import (
    IntegrationControl,
    IntegrationStatus,
    ProviderChoice,
    RunExecutionAction,
    RunExecutionControl,
    RunExecutionSituation,
    RunLockState,
    RunState,
    RunSummary,
    Stage,
)
from ai_orchestrator.registry import ProjectRegistry
from ai_orchestrator.config import create_default_config, load_config
from ai_orchestrator.code_style import ProjectCodeStylePreference
from ai_orchestrator.git import DotnetDiagnostic, run_command
from ai_orchestrator.pipeline import PipelineError


@dataclass
class SampleProject:
    name: str


class FakeApplication:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def projects(self) -> list[SampleProject]:
        return [SampleProject(name="sample")]

    def __getattr__(self, name: str):  # type: ignore[no-untyped-def]
        def call(*args: object, **kwargs: object) -> object:
            self.calls.append((name, *args, kwargs))
            if name == "task_log":
                return "작업 로그"
            if name.endswith("statuses"):
                return []
            return {"id": args[1] if len(args) > 1 else "result"}

        return call


def service() -> tuple[RpcService, FakeApplication]:
    application = FakeApplication()
    return RpcService(application), application  # type: ignore[arg-type]


def test_notifications_rpc_forwards_cursor_and_limit() -> None:
    rpc, application = service()

    rpc.dispatch(
        "notifications.list",
        {"projectName": "sample", "afterCursor": "cursor-1", "limit": 25},
    )

    assert application.calls == [
        ("notifications", "sample", {"after_cursor": "cursor-1", "limit": 25})
    ]


def test_notifications_rpc_rejects_non_integer_limit() -> None:
    rpc, _ = service()

    with pytest.raises(Exception, match="limit must be an integer"):
        rpc.dispatch("notifications.list", {"projectName": "sample", "limit": "25"})


def test_usage_rpc_is_read_only_and_forwards_scope_and_pagination() -> None:
    rpc, application = service()
    rpc.dispatch("runs.usage", {"projectName": "sample", "runId": "group", "executionRequestId": "execution", "cursor": "cursor", "limit": 25})
    rpc.dispatch("runs.usage", {"projectName": "sample", "runId": "group"})
    assert application.calls == [
        ("usage", "sample", "group", {"execution_request_id": "execution", "cursor": "cursor", "limit": 25}),
        ("usage", "sample", "group", {"execution_request_id": "", "cursor": "", "limit": 50}),
    ]
    for limit in (True, "25"):
        with pytest.raises(Exception, match="limit must be a non-negative integer"):
            rpc.dispatch("runs.usage", {"projectName": "sample", "runId": "group", "limit": limit})


def test_result_revision_rpc_routes_read_and_draft_creation_separately() -> None:
    rpc, application = service()

    rpc.dispatch("runs.resultRevisions", {"projectName": "sample", "runId": "source"})
    rpc.dispatch("runs.proposeResultRevision", {
        "projectName": "sample", "runId": "source", "proposalId": "proposal-1",
        "text": "문구를 수정해 주세요", "focusTaskId": "task-1",
    })
    rpc.dispatch("runs.createResultRevision", {
        "projectName": "sample", "runId": "source", "requestId": "request-1",
        "text": "문구를 수정해 주세요", "taskIds": ["task-1"], "paths": ["README.md"], "proposalId": "proposal-1",
    })

    assert application.calls == [
        ("result_revisions", "sample", "source", {}),
        ("propose_result_revision", "sample", "source", {
            "proposal_id": "proposal-1", "text": "문구를 수정해 주세요", "focus_task_id": "task-1",
        }),
        ("create_result_revision", "sample", "source", {
            "request_id": "request-1", "text": "문구를 수정해 주세요",
            "task_ids": ["task-1"], "paths": ["README.md"], "proposal_id": "proposal-1",
        }),
    ]


def test_codex_auth_rpc_is_available_without_project() -> None:
    rpc, application = service()

    rpc.dispatch("auth.codex.status", {})
    rpc.dispatch("auth.codex.start", {"method": "browser", "requestId": "request-1"})
    rpc.dispatch("auth.codex.get", {"attemptId": "attempt-1"})
    rpc.dispatch("auth.codex.cancel", {"attemptId": "attempt-1"})

    assert application.calls == [
        ("codex_auth_status", {}),
        ("start_codex_auth", "browser", "request-1", {}),
        ("codex_auth_attempt", "attempt-1", {}),
        ("cancel_codex_auth", "attempt-1", {}),
    ]


def test_codex_auth_rpc_rejects_unknown_login_method() -> None:
    rpc, _ = service()

    with pytest.raises(Exception, match="browser or device_code"):
        rpc.dispatch("auth.codex.start", {"method": "password", "requestId": "request-1"})


def test_codex_api_key_rpc_uses_official_adapter_without_project() -> None:
    rpc, application = service()
    rpc.dispatch("auth.codex.apiKey", {"apiKey": "sk-fixture-only", "requestId": "key-request"})
    assert application.calls == [("connect_codex_api_key", "sk-fixture-only", "key-request", {})]


@pytest.mark.parametrize("value", [None, "", "sk private", "private\n", "\x00private", "s" * 4097])
def test_codex_api_key_rpc_rejects_bad_keys_without_dispatch(value: object) -> None:
    rpc, application = service()
    with pytest.raises(RpcError):
        rpc.dispatch("auth.codex.apiKey", {"apiKey": value, "requestId": "key-request"})
    assert application.calls == []


def test_codex_api_key_rpc_redacts_credential_in_unexpected_errors() -> None:
    rpc, application = service()
    application.connect_codex_api_key = Mock(side_effect=RuntimeError("unexpected sk-fixture-only payload"))
    response = handle_request(rpc, {"id": 1, "method": "auth.codex.apiKey", "params": {"apiKey": "sk-fixture-only", "requestId": "key-request"}})
    assert response["error"]["code"] == "application_error"
    assert "sk-fixture-only" not in json.dumps(response)


def test_codex_auth_serializes_only_display_fields_without_project_or_persistence() -> None:
    from ai_orchestrator.codex_sdk import CodexSdkLoginState

    application = Mock()
    application.codex_auth_status.return_value = CodexSdkLoginState(
        status="connected", auth_method="chatgpt", auth_label="ChatGPT 구독 로그인",
        account_email="rpc-fixture@example.invalid", plan_type="pro",
    )
    response = handle_request(RpcService(application), {"id": 1, "method": "auth.codex.status", "params": {}})
    assert response["result"]["account_email"] == "rpc-fixture@example.invalid"
    assert response["result"]["plan_type"] == "pro"
    assert set(response["result"]) == {
        "status", "attempt_id", "method", "started_at", "auth_method", "auth_label", "auth_url", "user_code",
        "error_code", "message", "account_email", "plan_type",
    }
    assert application.mock_calls == [(("codex_auth_status"), (), {})]


def test_git_preparation_rpc_keeps_read_and_approved_actions_separate() -> None:
    rpc, application = service()

    rpc.dispatch("projects.inspectGitReadiness", {"repo": "C:/project"})
    rpc.dispatch("projects.previewGitInitialization", {"repo": "C:/project"})
    rpc.dispatch("projects.initializeGit", {"repo": "C:/project", "expectedKind": "not_initialized", "approved": True})
    rpc.dispatch("projects.previewInitialCommit", {"repo": "C:/project"})
    rpc.dispatch(
        "projects.createInitialCommit",
        {
            "repo": "C:/project",
            "snapshotId": "snapshot",
            "selectedPaths": ["README.md"],
            "message": "Initial commit",
            "authorName": "Test",
            "authorEmail": "test@example.com",
            "saveAuthor": True,
            "allowEmpty": False,
            "approved": True,
        },
    )

    assert application.calls == [
        ("inspect_git_readiness", "C:/project", {}),
        ("preview_git_initialization", "C:/project", {}),
        ("initialize_git", "C:/project", "not_initialized", {"approved": True}),
        ("preview_initial_commit", "C:/project", {}),
        (
            "create_initial_commit",
            "C:/project",
            "snapshot",
            ["README.md"],
            "Initial commit",
            {
                "author_name": "Test",
                "author_email": "test@example.com",
                "save_author": True,
                "allow_empty": False,
                "approved": True,
            },
        ),
    ]


def test_git_preparation_mutations_require_native_approval() -> None:
    rpc, _ = service()

    with pytest.raises(Exception, match="explicit native approval"):
        rpc.dispatch("projects.initializeGit", {"repo": "C:/project", "expectedKind": "not_initialized"})
    with pytest.raises(Exception, match="explicit native approval"):
        rpc.dispatch(
            "projects.createInitialCommit",
            {"repo": "C:/project", "snapshotId": "snapshot", "selectedPaths": [], "message": "Initial commit"},
        )


def test_planning_apply_rpc_forwards_request_and_revisions() -> None:
    rpc, application = service()

    rpc.dispatch(
        "runs.applyPlanningConversation",
        {
            "projectName": "sample",
            "runId": "run-1",
            "requestId": "apply-1",
            "expectedRevision": 3,
            "conversationRevision": 7,
        },
    )

    assert application.calls == [
        (
            "apply_planning_conversation",
            "sample",
            "run-1",
            {"request_id": "apply-1", "expected_revision": 3, "conversation_revision": 7},
        )
    ]


def test_greenfield_answer_rpc_preserves_revisions_retry_and_profile() -> None:
    rpc, application = service()
    rpc.dispatch("runs.applyPlanningConversation", {
        "projectName": "sample", "runId": "run-1", "requestId": "answer-1", "expectedRevision": 3,
        "conversationRevision": 7, "expectedTechStackRevision": 2, "answer": "개인 메모 앱", "retryFailed": True,
        "planningAgentId": "codex", "planningModel": "test-model", "planningReasoningEffort": "high",
    })
    assert application.calls == [("apply_planning_conversation", "sample", "run-1", {
        "request_id": "answer-1", "expected_revision": 3, "conversation_revision": 7,
        "answer_message": "개인 메모 앱", "expected_tech_stack_revision": 2, "retry_failed": True,
        "planning_agent_id": "codex", "planning_model": "test-model", "planning_reasoning_effort": "high",
    })]
    for invalid in [True, -1, "2"]:
        with pytest.raises(Exception, match="expectedTechStackRevision"):
            rpc.dispatch("runs.applyPlanningConversation", {
                "projectName": "sample", "runId": "run-1", "requestId": "answer-2", "expectedRevision": 3,
                "conversationRevision": 7, "expectedTechStackRevision": invalid, "answer": "답변",
            })


def test_greenfield_confirm_plan_rpc_forwards_reviewed_revision_and_digest() -> None:
    rpc, application = service()
    rpc.dispatch("runs.confirmPlan", {
        "projectName": "sample", "runId": "run-1", "expectedRevision": 4, "bootstrapDigest": "reviewed-digest",
    })
    assert application.calls == [("confirm_plan", "sample", "run-1", {
        "expected_revision": 4, "expected_bootstrap_digest": "reviewed-digest",
    })]


def test_planning_preview_rpc_separates_generation_read_and_application() -> None:
    rpc, application = service()
    rpc.dispatch("runs.previewPlanningApply", {"projectName": "sample", "runId": "run-1", "requestId": "preview-1"})
    rpc.dispatch("runs.getPlanningPreview", {"projectName": "sample", "runId": "run-1"})
    rpc.dispatch("runs.applyPlanningPreview", {
        "projectName": "sample", "runId": "run-1", "previewId": "preview-1",
        "fingerprint": "before", "candidateDigest": "candidate",
    })
    assert application.calls == [
        ("preview_planning_apply", "sample", "run-1", {"request_id": "preview-1"}),
        ("planning_apply_preview", "sample", "run-1", {}),
        ("apply_planning_preview", "sample", "run-1", {
            "preview_id": "preview-1", "fingerprint": "before", "candidate_digest": "candidate",
        }),
    ]


def test_direction_change_rpc_requires_explicit_request_and_routes_to_control_backend() -> None:
    rpc, application = service()
    rpc.dispatch("runs.requestDirectionChange", {
        "projectName": "sample", "runId": "run-1", "requestId": "direction-1",
        "text": "다음 Task의 범위를 줄여 주세요",
    })
    assert application.calls == [
        ("request_direction_change", "sample", "run-1", {
            "request_id": "direction-1", "text": "다음 Task의 범위를 줄여 주세요",
        }),
    ]
    with pytest.raises(Exception, match="text"):
        rpc.dispatch("runs.requestDirectionChange", {
            "projectName": "sample", "runId": "run-1", "requestId": "direction-2",
        })


def test_manual_handoff_rpc_requires_selected_task_and_observed_version() -> None:
    rpc, application = service()
    params = {"projectName": "sample", "runId": "run-1", "taskId": "one", "expectedCommit": "observed-head", "expectedRevision": 2}
    rpc.dispatch("tasks.handoffToAi", params)
    for invalid in ({"taskId": ""}, {"expectedCommit": ""}, {"expectedRevision": True}):
        with pytest.raises(RpcError, match=next(iter(invalid))):
            rpc.dispatch("tasks.handoffToAi", params | invalid)
    assert application.calls == [
        ("handoff_manual_task_to_ai", "sample", "run-1", "one", {"expected_commit": "observed-head", "expected_revision": 2}),
    ]


def test_manual_verification_rpc_binds_note_to_task_revision_and_commit() -> None:
    rpc, application = service()
    method = "tasks.completeManualVerification"
    params = {"projectName": "sample", "runId": "run-1", "taskId": "https", "note": "브라우저 확인",
              "expectedCommit": "observed-head", "expectedRevision": 2}
    rpc.dispatch(method, params)
    for invalid in ({"note": " "}, {"expectedCommit": ""}, {"expectedRevision": True}):
        with pytest.raises(RpcError, match=next(iter(invalid))):
            rpc.dispatch(method, params | invalid)
    assert application.calls == [
        ("complete_manual_verification", "sample", "run-1", "https", {
            "note": "브라우저 확인", "expected_commit": "observed-head", "expected_revision": 2,
        }),
    ]


def test_record_user_check_rpc_binds_outcome_to_revision_and_commit() -> None:
    rpc, application = service()
    method = "runs.recordUserCheck"
    params = {"projectName": "sample", "runId": "run-1", "checkId": "browser", "outcome": "deferred", "note": "환경 대기",
              "expectedCommit": "observed-head", "expectedRevision": 2}
    rpc.dispatch(method, params)
    for invalid in ({"checkId": ""}, {"outcome": ""}, {"expectedCommit": ""}, {"expectedRevision": True}):
        with pytest.raises(RpcError, match=next(iter(invalid))):
            rpc.dispatch(method, params | invalid)
    assert application.calls == [
        ("record_user_check", "sample", "run-1", "browser", {
            "outcome": "deferred", "note": "환경 대기", "expected_commit": "observed-head", "expected_revision": 2,
        }),
    ]


def test_manual_deferral_and_resume_require_a_task_and_route_separately_from_completion() -> None:
    rpc, application = service()
    params = {"projectName": "sample", "runId": "run-1"}
    for method in ("tasks.deferManual", "tasks.resumeManual"):
        with pytest.raises(RpcError, match="taskId"):
            rpc.dispatch(method, params)
        rpc.dispatch(method, {**params, "taskId": "https"})
    assert application.calls == [
        ("set_manual_task_deferred", "sample", "run-1", "https", {"deferred": True}),
        ("set_manual_task_deferred", "sample", "run-1", "https", {"deferred": False}),
    ]


def test_retry_instruction_and_preview_status_have_separate_rpc_contracts() -> None:
    rpc, application = service()
    params = {"projectName": "sample", "runId": "run-1"}
    rpc.dispatch("runs.planningPreviewStatus", params)
    rpc.dispatch("tasks.retryContext", {**params, "taskId": "task"})
    rpc.dispatch("tasks.saveRetryInstruction", {
        **params, "taskId": "task", "requestId": "request", "text": "fix assertion", "fingerprint": "failure",
    })
    assert application.calls == [
        ("planning_preview_status", "sample", "run-1", {}),
        ("task_retry_context", "sample", "run-1", "task", {}),
        ("save_task_retry_instruction", "sample", "run-1", "task", {
            "request_id": "request", "text": "fix assertion", "fingerprint": "failure",
        }),
    ]
    with pytest.raises(Exception, match="fingerprint"):
        rpc.dispatch("tasks.saveRetryInstruction", {**params, "taskId": "task", "requestId": "request", "text": "fix"})


def test_chat_recovery_requires_current_failure_and_conversation_and_uses_execution_profiles() -> None:
    rpc, application = service()
    params = {"projectName": "sample", "runId": "run-1", "taskId": "broken", "requestId": "request",
              "message": "고쳐서 계속해줘", "fingerprint": "failed-attempt", "conversationRevision": 2}
    rpc.dispatch("tasks.repairFromChat", params)
    assert application.calls == [("repair_task_from_chat", "sample", "run-1", "broken", {
        "request_id": "request", "message": "고쳐서 계속해줘", "fingerprint": "failed-attempt", "conversation_revision": 2,
    })]
    for missing in ("taskId", "requestId", "message", "fingerprint", "conversationRevision"):
        with pytest.raises(Exception, match=missing):
            rpc.dispatch("tasks.repairFromChat", {key: value for key, value in params.items() if key != missing})
    desktop = DesktopApplication(Mock())
    pipeline = Mock()
    with patch.object(desktop, "_pipeline", return_value=pipeline), patch.object(desktop, "_ensure_desktop_execution_profiles") as check:
        desktop.repair_task_from_chat("sample", "run-1", "broken", request_id="id", message="고쳐줘",
                                      fingerprint="failure", conversation_revision=2)
    check.assert_called_once_with(pipeline, "run-1", {})
    pipeline.repair_task_from_chat.assert_called_once_with(
        "run-1", "broken", request_id="id", message="고쳐줘", fingerprint="failure", conversation_revision=2,
    )


def test_chat_stop_and_verification_repair_preserve_the_explicit_message_in_rpc() -> None:
    rpc, application = service()
    params = {"projectName": "sample", "runId": "run-1", "requestId": "request", "chatMessage": "진행 멈추고 복구해줘"}
    rpc.dispatch("runs.requestStop", {**params, "executionId": "execution", "scope": "task", "taskId": "task"})
    rpc.dispatch("runs.verifyAndRepair", params)
    assert application.calls == [
        ("request_stop", "sample", "run-1", {"request_id": "request", "execution_id": "execution", "scope": "task",
          "task_id": "task", "attempt_id": "", "invocation_id": "", "chat_message": params["chatMessage"]}),
        ("verify_and_repair", "sample", "run-1", "request", {"chat_message": params["chatMessage"]}),
    ]


def test_desktop_direct_planning_apply_cannot_bypass_preview() -> None:
    application = DesktopApplication(Mock())
    pipeline = Mock()
    pipeline.status.return_value.repository_intent = "existing_structure"
    with patch.object(application, "_pipeline", return_value=pipeline):
        with pytest.raises(PipelineError, match="미리보기"):
            application.apply_planning_conversation(
                "sample", "run-1", request_id="old", expected_revision=1, conversation_revision=2
            )
    pipeline.request_planning_conversation_apply.assert_not_called()


def test_planning_apply_rpc_rejects_boolean_revision() -> None:
    rpc, _ = service()

    with pytest.raises(Exception, match="expectedRevision must be a non-negative integer"):
        rpc.dispatch(
            "runs.applyPlanningConversation",
            {
                "projectName": "sample",
                "runId": "run-1",
                "requestId": "apply-1",
                "expectedRevision": True,
                "conversationRevision": 7,
            },
        )


def test_technology_stack_confirmation_forwards_option_and_expected_revision() -> None:
    rpc, application = service()

    rpc.dispatch(
        "runs.confirmTechStack",
        {
            "projectName": "sample",
            "runId": "run-1",
            "optionId": "electron-typescript",
            "expectedRevision": 2,
        },
    )

    assert application.calls == [
        (
            "confirm_tech_stack",
            "sample",
            "run-1",
            {"option_id": "electron-typescript", "expected_revision": 2},
        )
    ]


def test_bootstrap_instruction_choice_forwards_revision_and_digest() -> None:
    rpc, application = service()

    rpc.dispatch(
        "runs.configureBootstrapInstructions",
        {
            "projectName": "sample",
            "runId": "run-1",
            "create": False,
            "expectedRevision": 2,
            "expectedDigest": "digest-2",
        },
    )

    assert application.calls == [
        (
            "configure_bootstrap_agent_instructions",
            "sample",
            "run-1",
            {"create": False, "expected_revision": 2, "expected_digest": "digest-2"},
        )
    ]


def test_bootstrap_preview_forwards_project_and_run() -> None:
    rpc, application = service()

    rpc.dispatch("planning.previewBootstrap", {"projectName": "sample", "runId": "run-1"})

    assert application.calls == [("preview_bootstrap", "sample", "run-1", {})]


def test_feature_plan_generation_forwards_project_and_run() -> None:
    rpc, application = service()

    rpc.dispatch("planning.generateFeaturePlan", {"projectName": "sample", "runId": "run-1"})

    assert application.calls == [("generate_feature_plan", "sample", "run-1", {})]


def test_code_style_rpc_separates_read_preview_and_approved_save() -> None:
    rpc, application = service()
    preference = {
        "mode": "repository_only",
        "fallback_by_language": {},
        "custom_instruction_paths": [],
    }

    rpc.dispatch("projects.codeStyleProfile", {"projectName": "sample"})
    rpc.dispatch("projects.previewCodeStylePreference", {"projectName": "sample", "preference": preference})
    rpc.dispatch(
        "projects.updateCodeStylePreference",
        {
            "projectName": "sample",
            "preference": preference,
            "expectedRevision": 2,
            "approved": True,
        },
    )

    assert application.calls == [
        ("code_style_profile", "sample", {}),
        ("preview_code_style_preference", "sample", ProjectCodeStylePreference.from_dict(preference), {}),
        (
            "update_code_style_preference",
            "sample",
            ProjectCodeStylePreference.from_dict(preference),
            2,
            {"approved": True},
        ),
    ]


def test_code_style_rpc_rejects_unapproved_save() -> None:
    rpc, _ = service()
    with pytest.raises(Exception, match="explicit native approval"):
        rpc.dispatch(
            "projects.updateCodeStylePreference",
            {
                "projectName": "sample",
                "preference": {"mode": "repository_only", "fallback_by_language": {}, "custom_instruction_paths": []},
                "expectedRevision": 0,
            },
        )


def test_project_dotnet_rpc_saves_and_diagnoses_with_fresh_settings(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config_path = tmp_path / "orchestrator.toml"
    create_default_config(config_path, repo)
    registry = ProjectRegistry(tmp_path / "projects.json")
    registry.add("Example", repo, config_path)
    application = DesktopApplication(registry, codex_sdk=Mock())
    rpc = RpcService(application)
    executable = tmp_path / "dotnet.exe"
    executable.touch()
    rpc.dispatch("projects.updateDotnet", {"projectName": "Example", "executable": str(executable)})
    diagnostic = DotnetDiagnostic(str(executable), "SDK selected")
    with patch("ai_orchestrator.pipeline.diagnose_dotnet", return_value=diagnostic) as diagnose:
        assert rpc.dispatch("projects.checkDotnet", {"projectName": "Example"}) == diagnostic
    diagnose.assert_called_once_with(str(executable.resolve()), repo)
    rpc.dispatch("projects.updateDotnet", {"projectName": "Example", "executable": ""})
    assert application._pipeline("Example").dotnet_executable == ""


def test_project_workspace_location_rpc_reports_resolved_path_without_creating_it(tmp_path: Path) -> None:
    repo = tmp_path / "프로젝트"
    repo.mkdir()
    config_path = tmp_path / "orchestrator.toml"
    create_default_config(config_path, repo)
    registry = ProjectRegistry(tmp_path / "projects.json")
    registry.add("Example", repo, config_path)
    rpc = RpcService(DesktopApplication(registry, codex_sdk=Mock()))

    result = rpc.dispatch("projects.workspaceLocation", {"projectName": "Example"})

    assert result["repo"] == str(repo.resolve())
    assert result["root"] == str((repo / ".ai_auto_work" / "worktree").resolve())
    assert result["source"] == "project_default"
    assert result["layout_version"] == 2
    assert result["created"] is False
    assert not (repo / ".ai_auto_work").exists()


def test_project_capabilities_report_deployment_and_repository_maturity(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config_path = tmp_path / "orchestrator.toml"
    create_default_config(config_path, repo)
    registry = ProjectRegistry(tmp_path / "projects.json")
    registry.add("Example", repo, config_path)
    rpc = RpcService(DesktopApplication(registry, codex_sdk=Mock()))

    initial = rpc.dispatch("projects.capabilities", {"projectName": "Example"})
    assert initial["deployment_configured"] is False
    assert initial["repository_maturity"]["kind"] == "docs_only"
    assert rpc.dispatch("planning.inspectRepositoryMaturity", {"projectName": "Example"})["kind"] == "docs_only"

    configured = config_path.read_text(encoding="utf-8").replace(
        "deploy_command = []", 'deploy_command = ["python", "deploy.py"]'
    )
    config_path.write_text(configured, encoding="utf-8")

    assert rpc.dispatch("projects.capabilities", {"projectName": "Example"})["deployment_configured"] is True


def test_project_code_style_profile_preview_and_save_are_repository_safe(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("pass\n", encoding="utf-8")
    config_path = tmp_path / "orchestrator.toml"
    create_default_config(config_path, repo)
    registry = ProjectRegistry(tmp_path / "projects.json")
    registry.add("Example", repo, config_path)
    rpc = RpcService(DesktopApplication(registry, codex_sdk=Mock()))

    initial = rpc.dispatch("projects.codeStyleProfile", {"projectName": "Example"})
    preview = rpc.dispatch(
        "projects.previewCodeStylePreference",
        {
            "projectName": "Example",
            "preference": {"mode": "repository_only", "fallback_by_language": {}, "custom_instruction_paths": []},
        },
    )
    saved = rpc.dispatch(
        "projects.updateCodeStylePreference",
        {
            "projectName": "Example",
            "preference": {"mode": "repository_only", "fallback_by_language": {}, "custom_instruction_paths": []},
            "expectedRevision": 0,
            "approved": True,
        },
    )

    assert initial["status"] == "detected"
    assert any(rule["standard_id"] == "pep8" for rule in initial["rules"])
    assert preview["status"] == "unspecified"
    assert saved["preference_revision"] == 1
    assert saved["status"] == "unspecified"
    assert (repo / "pyproject.toml").exists() is False


def test_main_change_rpc_separates_preview_refresh_and_approved_mutations() -> None:
    rpc, application = service()
    selections = [{"path": "src/app.py", "mode": "whole"}]

    rpc.dispatch("projects.mainChanges", {"projectName": "sample"})
    rpc.dispatch("projects.refreshMainRemote", {"projectName": "sample"})
    rpc.dispatch(
        "projects.mainChangeDiff",
        {"projectName": "sample", "snapshotId": "snapshot", "path": "src/app.py", "mode": "whole"},
    )
    rpc.dispatch(
        "projects.commitMainChanges",
        {
            "projectName": "sample",
            "snapshotId": "snapshot",
            "selections": selections,
            "message": "selected change",
            "approved": True,
        },
    )

    assert application.calls == [
        ("main_changes", "sample", {}),
        ("main_changes", "sample", {"refresh_remote": True}),
        ("main_change_diff", "sample", "snapshot", "src/app.py", "whole", {}),
        ("commit_main_changes", "sample", "snapshot", [("src/app.py", "whole")], "selected change", {"approved": True}),
    ]


def test_main_change_rpc_rejects_invalid_selection_mode() -> None:
    rpc, _ = service()

    with pytest.raises(Exception, match="staged/whole"):
        rpc.dispatch(
            "projects.commitMainChanges",
            {
                "projectName": "sample",
                "snapshotId": "snapshot",
                "selections": [{"path": "src/app.py", "mode": "everything"}],
                "message": "selected change",
                "approved": True,
            },
        )

def test_desktop_application_reuses_and_closes_codex_sdk_manager(tmp_path: Path) -> None:
    registry = Mock()
    project = Mock(repo=tmp_path, config_path=tmp_path / "orchestrator.toml")
    registry.get.return_value = project
    config = Mock()
    config.project.repo = tmp_path
    codex_sdk = Mock()
    application = DesktopApplication(registry, codex_sdk=codex_sdk)

    with patch("ai_orchestrator.desktop_rpc.load_config", return_value=config), patch("ai_orchestrator.desktop_rpc.Pipeline") as pipeline:
        application._pipeline("sample")
        application._pipeline("sample")

    assert pipeline.call_count == 2
    assert all(call.kwargs["codex_sdk"] is codex_sdk for call in pipeline.call_args_list)
    application.close()
    codex_sdk.close.assert_called_once_with()


def test_desktop_application_consumes_prepared_index_token_once(tmp_path: Path) -> None:
    source = tmp_path / "Planning"
    source.mkdir()
    pipeline = Mock()
    index = Mock(
        source_root=str(source),
        generated_at="2026-09-01T00:00:00+00:00",
        document_count=3,
        reused_count=2,
        updated_count=1,
        added_count=0,
        modified_count=1,
        deleted_count=0,
    )
    pipeline.refresh_planning_index.return_value = index
    pipeline.prepare_planning.return_value = {"id": "run-1"}
    pipeline.planning_provider_choices.return_value = [ProviderChoice("codex", "codex-general", is_default=True)]
    application = DesktopApplication(Mock(), codex_sdk=Mock())

    with patch.object(application, "_pipeline", return_value=pipeline):
        refreshed = application.refresh_planning_index("sample", source)
        application.prepare_planning("sample", source, prepared_index_generated_at="2026-09-01T00:00:00+00:00")
        application.prepare_planning("sample", source, prepared_index_generated_at="2026-09-01T00:00:00+00:00")

    prepare_calls = pipeline.prepare_planning.call_args_list
    assert refreshed["modified_count"] == 1
    assert refreshed["added_count"] == refreshed["deleted_count"] == 0
    assert prepare_calls[0].kwargs["prepared_source_index"] is index
    assert prepare_calls[1].kwargs["prepared_source_index"] is None


def test_desktop_application_prepares_directed_run_without_source() -> None:
    pipeline = Mock()
    pipeline.prepare_planning.return_value = {"id": "run-1"}
    pipeline.planning_provider_choices.return_value = [ProviderChoice("codex", "codex-general", is_default=True)]
    application = DesktopApplication(Mock(), codex_sdk=Mock())

    with patch.object(application, "_pipeline", return_value=pipeline):
        application.prepare_planning("sample", "", planning_mode="directed", planning_request="README 표시 오류만 수정해 주세요.")

    pipeline.prepare_planning.assert_called_once_with(
        "",
        planning_agent_id="codex-general",
        planning_model="",
        planning_reasoning_effort="",
        planning_mode="directed",
        planning_request="README 표시 오류만 수정해 주세요.",
        prepared_source_index=None,
        repository_intent="",
        effort_mode="balanced",
        planning_profile_source=None,
    )


def test_run_status_includes_backend_execution_control() -> None:
    application = DesktopApplication(Mock(), codex_sdk=Mock())
    pipeline = Mock()
    state = RunState(
        id="run-1",
        spec_path="plan.md",
        spec_digest="digest",
        repo_path="repo",
        main_branch="main",
        stage=Stage.PLANNED,
    )
    control = RunExecutionControl(
        situation=RunExecutionSituation.READY,
        action=RunExecutionAction.EXECUTE,
        reason="준비된 Task를 실행할 수 있습니다.",
        lock_state=RunLockState.UNLOCKED,
    )
    integration_control = IntegrationControl(
        status=IntegrationStatus.NOT_READY,
        reason="Task 실행이 아직 완료되지 않았습니다.",
        reason_code="tasks_incomplete",
        can_verify=False,
        can_apply_main=False,
    )
    pipeline.status_with_controls.return_value = (state, control, integration_control)
    pipeline.execution_profile_view.return_value = state
    pipeline.latest_main_operations.return_value = {"merge": None, "push": None, "retry_main_push": None}

    with patch.object(application, "_pipeline", return_value=pipeline):
        result = application.status("sample", state.id)

    assert isinstance(result, dict)
    assert result["id"] == state.id
    assert result["execution_control"] is control
    assert result["integration_control"] is integration_control
    assert result["main_operations"] == {"merge": None, "push": None, "retry_main_push": None}
    pipeline.status_with_controls.assert_called_once_with(state.id)
    pipeline.execution_profile_view.assert_called_once_with(state)
    pipeline.latest_main_operations.assert_called_once_with(state.id)


def test_desktop_application_reuses_single_codex_sdk_manager(tmp_path: Path) -> None:
    registry = Mock()
    project = Mock(repo=tmp_path, config_path=tmp_path / "orchestrator.toml")
    registry.get.return_value = project
    config = Mock()
    config.project.repo = tmp_path
    codex_sdk = Mock()

    with patch("ai_orchestrator.desktop_rpc.CodexSdkManager", return_value=codex_sdk) as manager_factory:
        application = DesktopApplication(registry)
        with patch("ai_orchestrator.desktop_rpc.load_config", return_value=config), patch("ai_orchestrator.desktop_rpc.Pipeline") as pipeline:
            application._pipeline("first")
            application._pipeline("second")
        application.close()

    manager_factory.assert_called_once_with()
    assert pipeline.call_args_list[0].kwargs["codex_sdk"] is codex_sdk
    assert pipeline.call_args_list[1].kwargs["codex_sdk"] is codex_sdk
    codex_sdk.close.assert_called_once_with()


def test_projects_are_serialized_from_dataclasses() -> None:
    rpc, _ = service()
    response = handle_request(rpc, {"id": 1, "method": "projects.list", "params": {}})
    assert response == {"id": 1, "result": [{"name": "sample"}]}


def test_run_lookup_requires_project_name() -> None:
    rpc, _ = service()
    response = handle_request(rpc, {"id": "a", "method": "runs.list", "params": {}})
    assert response == {"id": "a", "error": {"code": "invalid_params", "message": "projectName must be a non-empty string"}}


def test_active_groups_rpc_needs_no_selected_project() -> None:
    rpc, application = service()

    response = handle_request(rpc, {"id": "active", "method": "runs.activeGroups", "params": {}})

    assert response["result"] == {"id": "result"}
    assert application.calls == [("active_groups", {})]


def test_attention_items_rpc_needs_no_project_or_approval() -> None:
    rpc, application = service()
    response = handle_request(rpc, {"id": "attention", "method": "runs.attentionItems", "params": {}})
    assert response["result"] == {"id": "result"}
    assert application.calls == [("attention_items", {})]


def test_attention_items_isolate_project_errors_and_keep_same_run_id_distinct() -> None:
    registry = Mock()
    registry.list.return_value = [SampleProject("first"), SampleProject("second"), SampleProject("broken")]
    application = DesktopApplication(registry, codex_sdk=Mock())

    def project_items(project_name: str) -> list[dict[str, object]]:
        if project_name == "broken":
            raise OSError("read denied")
        return [{"run_id": "same", "kind": "planning_questions", "updated_at": "now"}]

    try:
        with patch.object(application, "_attention_items_for_project", side_effect=project_items):
            result = application.attention_items()
    finally:
        application.close()
    assert {(item["project_name"], item["run_id"]) for item in result["items"]} == {("first", "same"), ("second", "same")}
    assert [(item["project_name"], item["error"]) for item in result["errors"]] == [("broken", "read denied")]


def test_attention_items_reuse_stalled_project_future() -> None:
    from concurrent.futures import wait

    registry = Mock()
    registry.list.return_value = [SampleProject("fast"), SampleProject("slow")]
    application = DesktopApplication(registry, codex_sdk=Mock())
    release = Event()
    calls: list[str] = []

    def project_items(project_name: str) -> list[dict[str, object]]:
        calls.append(project_name)
        if project_name == "slow":
            release.wait(15)
        return [{"run_id": project_name, "updated_at": "now"}]

    try:
        with patch.object(application, "_attention_items_for_project", side_effect=project_items):
            with patch("ai_orchestrator.desktop_rpc.wait", side_effect=lambda futures, timeout: wait(futures, timeout=0.1)):
                first = application.attention_items()
                second = application.attention_items()
    finally:
        release.set()
        application.close()
    assert [item["project_name"] for item in first["items"]] == ["fast"]
    assert [item["project_name"] for item in second["errors"]] == ["slow"]
    assert calls.count("slow") == 1


def test_active_groups_keep_same_run_id_distinct_and_isolate_project_errors() -> None:
    registry = Mock()
    registry.list.return_value = [SampleProject("first"), SampleProject("second"), SampleProject("broken")]
    application = DesktopApplication(registry, codex_sdk=Mock())

    def project_groups(project_name: str) -> list[dict[str, object]]:
        if project_name == "broken":
            raise ValueError("invalid project state")
        return [{
            "run_id": "shared-id", "title": project_name, "stage": "executing", "status": "active",
            "completed_task_count": 1, "task_count": 2, "activity_kinds": ["task"],
            "last_activity_at": "2026-09-29T00:00:00+00:00", "checked_at": "2026-09-29T00:00:00+00:00",
        }]

    try:
        with patch.object(application, "_active_groups_for_project", side_effect=project_groups):
            result = application.active_groups()
    finally:
        application.close()

    assert {(item["project_name"], item["run_id"]) for item in result["items"]} == {
        ("first", "shared-id"), ("second", "shared-id"),
    }
    assert [(item["project_name"], item["error"]) for item in result["errors"]] == [("broken", "invalid project state")]


def test_active_groups_bounded_wait_keeps_fast_project_when_other_project_stalls() -> None:
    registry = Mock()
    registry.list.return_value = [SampleProject("fast"), SampleProject("slow")]
    application = DesktopApplication(registry, codex_sdk=Mock())
    release = Event()

    def project_groups(project_name: str) -> list[dict[str, object]]:
        if project_name == "slow":
            release.wait(15)
            return []
        return [{
            "run_id": "fast-run", "title": "Fast", "stage": "executing", "status": "active",
            "completed_task_count": 0, "task_count": 1, "activity_kinds": ["task"],
            "last_activity_at": "2026-09-29T00:00:00+00:00", "checked_at": "2026-09-29T00:00:00+00:00",
        }]

    try:
        with patch.object(application, "_active_groups_for_project", side_effect=project_groups):
            result = application.active_groups()
    finally:
        release.set()
        application.close()

    assert [item["project_name"] for item in result["items"]] == ["fast"]
    assert [item["project_name"] for item in result["errors"]] == ["slow"]
    assert "시간이 초과" in result["errors"][0]["error"]


def test_plan_update_and_confirmation_are_routed() -> None:
    rpc, application = service()
    draft = {
        "id": "task-1",
        "title": "Task",
        "description": "설명",
        "is_prerequisite": True,
        "expected_paths": ["src/models.py"],
    }

    updated = handle_request(
        rpc, {"id": "update", "method": "runs.updatePlan", "params": {"projectName": "sample", "runId": "run-1", "tasks": [draft]}}
    )
    confirmed = handle_request(rpc, {"id": "confirm", "method": "runs.confirmPlan", "params": {"projectName": "sample", "runId": "run-1"}})

    assert "error" not in updated
    assert "error" not in confirmed
    assert application.calls == [
        ("update_plan", "sample", "run-1", [draft], {}),
        ("confirm_plan", "sample", "run-1", {}),
    ]


def test_plan_update_forwards_optional_revision_and_rejects_invalid_revision() -> None:
    rpc, application = service()
    draft = {"id": "task-1", "title": "Task"}
    params = {"projectName": "sample", "runId": "run-1", "tasks": [draft], "expectedRevision": 3}
    rpc.dispatch("runs.updatePlan", params)
    assert application.calls == [("update_plan", "sample", "run-1", [draft], {"expected_revision": 3})]
    for invalid in (True, -1, "3", None):
        with pytest.raises(RpcError):
            rpc.dispatch("runs.updatePlan", {**params, "expectedRevision": invalid})
    assert len(application.calls) == 1


def test_next_execution_profile_rpc_requires_a_complete_current_snapshot() -> None:
    rpc, application = service()
    expected = {"agent_id": "old", "model": "old-model", "reasoning_effort": "high", "last_attempt_id": "attempt", "status": "failed"}
    params = {"projectName": "sample", "runId": "run-1", "taskId": "task-1", "agentId": "nvidia-experimental",
              "model": "registered-model", "reasoningEffort": "", "expectedProfile": expected}
    rpc.dispatch("tasks.updateExecutionProfile", params)
    assert application.calls == [("update_task_execution_profile", "sample", "run-1", "task-1", {
        "agent_id": "nvidia-experimental", "model": "registered-model", "reasoning_effort": "", "expected_profile": expected,
    })]
    for changes in ({"expectedProfile": None}, {"expectedProfile": {}}, {"expectedProfile": {**expected, "status": 1}},
                    {"agentId": ""}, {"model": 1}, {"reasoningEffort": False}):
        with pytest.raises(RpcError):
            rpc.dispatch("tasks.updateExecutionProfile", {**params, **changes})
    assert len(application.calls) == 1


def test_plan_update_requires_nonempty_object_array() -> None:
    rpc, _ = service()

    response = handle_request(rpc, {"id": "update", "method": "runs.updatePlan", "params": {"projectName": "sample", "runId": "run-1", "tasks": []}})

    assert response["error"] == {"code": "invalid_params", "message": "tasks must not be empty"}


def test_run_list_returns_card_summaries_without_full_run_payload() -> None:
    class SummaryApplication(FakeApplication):
        def runs(self, _project_name: str) -> list[RunSummary]:
            return [
                RunSummary(
                    id="run-1",
                    summary="요약",
                    stage=Stage.PLANNED,
                    updated_at="2026-08-28T00:00:00+00:00",
                    created_at="2026-08-28T00:00:00+00:00",
                    task_count=5,
                    completed_task_count=2,
                )
            ]

    response = handle_request(
        RpcService(SummaryApplication()), {"id": "summary", "method": "runs.list", "params": {"projectName": "sample"}}  # type: ignore[arg-type]
    )

    assert response["result"] == [
        {
            "id": "run-1",
            "summary": "요약",
            "stage": "planned",
            "updated_at": "2026-08-28T00:00:00+00:00",
            "created_at": "2026-08-28T00:00:00+00:00",
            "task_count": 5,
            "completed_task_count": 2,
            "archived": False,
            "archived_at": "",
            "cleanup_status": "",
            "failed_task_count": 0,
            "waiting_task_count": 0,
            "plan_is_approved": True,
            "attention_reasons": [],
            "execution_situation": "unavailable",
            "pipeline_complete": False,
            "checked_at": "",
        }
    ]


def test_run_archive_rpcs_forward_preview_and_approved_requests() -> None:
    rpc, application = service()

    rpc.dispatch("runs.archivePlan", {"projectName": "sample", "runId": "run-1"})
    rpc.dispatch(
        "runs.archive",
        {
            "projectName": "sample",
            "runId": "run-1",
            "expectedRevision": "revision-1",
            "fingerprint": "fingerprint-1",
            "requestId": "request-1",
            "approved": True,
        },
    )
    rpc.dispatch(
        "runs.retryArchiveCleanup",
        {
            "projectName": "sample",
            "runId": "run-1",
            "fingerprint": "fingerprint-1",
            "requestId": "request-2",
            "approved": True,
        },
    )

    assert application.calls == [
        ("archive_plan", "sample", "run-1", {}),
        (
            "archive_run",
            "sample",
            "run-1",
            {
                "expected_revision": "revision-1",
                "fingerprint": "fingerprint-1",
                "request_id": "request-1",
                "approved": True,
            },
        ),
        (
            "retry_archive_cleanup",
            "sample",
            "run-1",
            {"fingerprint": "fingerprint-1", "request_id": "request-2", "approved": True},
        ),
    ]


def test_task_execute_uses_validated_profile_overrides() -> None:
    rpc, application = service()
    response = handle_request(
        rpc,
        {
            "id": 2,
            "method": "tasks.execute",
            "params": {
                "projectName": "sample",
                "runId": "run-1",
                "taskId": "task-1",
                "agentOverrides": {"task-1": "codex-ai"},
                "modelOverrides": {"task-1": "gpt-5.6-sol"},
                "reasoningEffortOverrides": {"task-1": "high"},
                "command": "ignored",
            },
        },
    )
    assert "error" not in response
    assert application.calls == [
        (
            "execute_task",
            "sample",
            "run-1",
            "task-1",
            {
                "agent_overrides": {"task-1": "codex-ai"},
                "model_overrides": {"task-1": "gpt-5.6-sol"},
                "reasoning_effort_overrides": {"task-1": "high"},
            },
        )
    ]


def test_approved_method_rejects_renderer_only_flag_omission() -> None:
    rpc, application = service()
    response = handle_request(rpc, {"id": 3, "method": "runs.merge", "params": {"projectName": "sample", "runId": "run-1"}})
    assert response["error"] == {"code": "approval_required", "message": "this operation requires explicit native approval"}
    assert application.calls == []


def test_main_push_retry_requires_native_approval_and_routes_only_explicit_true() -> None:
    rpc, application = service()
    params = {"projectName": "sample", "runId": "run-1", "requestId": "a665df73-f287-43e2-a5f1-c057e9812e89"}

    denied = handle_request(rpc, {"id": 31, "method": "runs.retryMainPush", "params": params})
    assert denied["error"]["code"] == "approval_required"
    assert application.calls == []

    allowed = handle_request(rpc, {"id": 32, "method": "runs.retryMainPush", "params": {**params, "approved": True}})
    assert "error" not in allowed
    assert application.calls == [
        ("approved_run_action", "sample", "run-1", "retryMainPush", {"approved": True, "request_id": params["requestId"]})
    ]


def test_interrupted_main_apply_recovery_requires_native_approval() -> None:
    rpc, application = service()
    params = {
        "projectName": "sample", "runId": "run-1", "requestId": "c4aa2583-2780-43f3-b8be-75b957013f9c",
        "repoPath": "/tmp/example", "targetCommit": "a" * 40,
    }
    denied = handle_request(rpc, {"id": 33, "method": "runs.recoverMainApply", "params": params})
    assert denied["error"]["code"] == "approval_required"
    assert application.calls == []
    missing_target = handle_request(
        rpc, {"id": 35, "method": "runs.recoverMainApply", "params": {"projectName": "sample", "runId": "run-1", "approved": True}}
    )
    assert missing_target["error"]["code"] == "invalid_params"
    assert application.calls == []
    allowed = handle_request(rpc, {"id": 34, "method": "runs.recoverMainApply", "params": {**params, "approved": True}})
    assert "error" not in allowed
    assert application.calls == [
        (
            "approved_run_action", "sample", "run-1", "recoverMainApply",
            {"approved": True, "request_id": params["requestId"], "expected_repo": params["repoPath"], "expected_commit": params["targetCommit"]},
        )
    ]


def test_approved_method_routes_only_explicit_true() -> None:
    rpc, application = service()
    response = handle_request(
        rpc, {"id": 4, "method": "workspaces.cleanup", "params": {"projectName": "sample", "runId": "run-1", "taskId": "task-1", "approved": True}}
    )
    assert "error" not in response
    assert application.calls == [
        ("cleanup_workspace", "sample", "run-1", "task-1", {"approved": True})
    ]


def test_planning_interrupt_requires_native_approval() -> None:
    rpc, application = service()

    response = handle_request(
        rpc, {"id": "interrupt-rejected", "method": "runs.interruptPlanning", "params": {"projectName": "sample", "runId": "run-1"}}
    )

    assert response["error"] == {"code": "approval_required", "message": "this operation requires explicit native approval"}
    assert application.calls == []


def test_planning_interrupt_routes_explicit_native_approval() -> None:
    rpc, application = service()

    response = handle_request(
        rpc, {"id": "interrupt-approved", "method": "runs.interruptPlanning", "params": {"projectName": "sample", "runId": "run-1", "approved": True}}
    )

    assert "error" not in response
    assert application.calls == [("interrupt_planning", "sample", "run-1", {"approved": True})]


def test_planning_prepare_and_run_are_separate_rpc_calls() -> None:
    rpc, application = service()

    prepared = handle_request(
        rpc,
        {
            "id": "prepare-planning",
            "method": "runs.preparePlanning",
            "params": {
                "projectName": "sample",
                "specPath": "Planning",
                "planningAgentId": "planner",
                "planningModel": "gpt-test",
                "planningReasoningEffort": "medium",
                "planningMode": "directed",
                "planningRequest": "작업 그룹 삭제 오류만 계획해 주세요.",
                "preparedIndexGeneratedAt": "2026-09-01T00:00:00+00:00",
                "repositoryIntent": "new_project",
            },
        },
    )
    started = handle_request(rpc, {"id": "run-planning", "method": "runs.runPlanning", "params": {"projectName": "sample", "runId": "run-1"}})

    assert "error" not in prepared
    assert "error" not in started
    assert application.calls == [
        (
            "prepare_planning",
            "sample",
            "Planning",
            {
                "planning_agent_id": "planner",
                "planning_model": "gpt-test",
                "planning_reasoning_effort": "medium",
                "planning_mode": "directed",
                "planning_request": "작업 그룹 삭제 오류만 계획해 주세요.",
                "prepared_index_generated_at": "2026-09-01T00:00:00+00:00",
                "repository_intent": "new_project",
                "effort_mode": "balanced",
                "planning_profile_source": None,
            },
        ),
        ("run_planning", "sample", "run-1", {}),
    ]


def test_directed_planning_rpc_allows_missing_spec_path() -> None:
    rpc, application = service()

    response = handle_request(
        rpc,
        {
            "id": "prepare-without-documents",
            "method": "runs.preparePlanning",
            "params": {
                "projectName": "sample",
                "planningMode": "directed",
                "planningRequest": "README 표시 오류만 수정해 주세요.",
            },
        },
    )

    assert "error" not in response
    assert application.calls == [
        (
            "prepare_planning",
            "sample",
            "",
            {
                "planning_agent_id": "",
                "planning_model": "",
                "planning_reasoning_effort": "",
                "planning_mode": "directed",
                "planning_request": "README 표시 오류만 수정해 주세요.",
                "prepared_index_generated_at": "",
                "repository_intent": "",
                "effort_mode": "balanced",
                "planning_profile_source": None,
            },
        )
    ]


def test_new_planning_mode_and_profile_source_are_forwarded_for_prepare_and_start() -> None:
    for method in ("runs.preparePlanning", "runs.start"):
        rpc, application = service()
        response = handle_request(rpc, {
            "id": "new-planning-policy", "method": method,
            "params": {"projectName": "sample", "specPath": "plan", "effortMode": "economy", "planningProfileSource": "routing"},
        })
        assert "error" not in response
        assert application.calls[-1][-1]["effort_mode"] == "economy"
        assert application.calls[-1][-1]["planning_profile_source"] == "routing"


def test_unknown_method_does_not_invoke_application() -> None:
    rpc, application = service()
    response = handle_request(rpc, {"id": 5, "method": "shell.execute", "params": {}})
    assert response["error"] == {"code": "method_not_found", "message": "unsupported RPC method: shell.execute"}
    assert application.calls == []


def test_server_returns_parse_error_and_continues() -> None:
    rpc, _ = service()
    input_stream = io.StringIO("not-json\n" + json.dumps({"id": 6, "method": "system.hello", "params": {}}) + "\n")
    output_stream = io.StringIO()
    serve(rpc, input_stream, output_stream)
    responses = [json.loads(line) for line in output_stream.getvalue().splitlines()]
    assert responses[0]["error"]["code"] == "parse_error"
    assert responses[1]["result"]["rpcVersion"] == 1


def test_server_response_is_safe_for_cp949_output_stream() -> None:
    class UnicodeApplication(FakeApplication):
        def status(self, _project_name: str, _run_id: str) -> dict[str, str]:
            return {"summary": "기획—응답"}

    rpc = RpcService(UnicodeApplication())  # type: ignore[arg-type]
    input_stream = io.StringIO(json.dumps({"id": "unicode", "method": "runs.get", "params": {"projectName": "sample", "runId": "run-1"}}) + "\n")
    output_bytes = io.BytesIO()
    output_stream = io.TextIOWrapper(output_bytes, encoding="cp949")

    serve(rpc, input_stream, output_stream)

    output_stream.flush()
    output_bytes.seek(0)
    response = json.loads(output_bytes.read().decode("cp949"))
    assert response["result"] == {"summary": "기획—응답"}


def test_status_queries_are_not_blocked_by_work_or_control_requests() -> None:
    class BlockingApplication(FakeApplication):
        def __init__(self) -> None:
            super().__init__()
            self.release = Event()
            self.all_started = Event()
            self.list_returned = Event()
            self.started_count = 0
            self.started_lock = Lock()

        def _block(self) -> dict[str, str]:
            with self.started_lock:
                self.started_count += 1
                if self.started_count == 8:
                    self.all_started.set()
            self.release.wait(timeout=2)
            return {"id": "run"}

        def start(self, *_args: object, **_kwargs: object) -> dict[str, str]:
            return self._block()

        def execution_provider_choices(self, _project_name: str, _capabilities: list[str]) -> dict[str, str]:
            return self._block()

        def runs(self, _project_name: str) -> list[object]:
            self.list_returned.set()
            return []

    application = BlockingApplication()
    rpc = RpcService(application)  # type: ignore[arg-type]
    requests = [{"id": request_id, "method": "runs.start", "params": {"projectName": "sample", "specPath": "plan"}} for request_id in range(1, 5)]
    requests.extend(
        {
            "id": request_id,
            "method": "providers.execution",
            "params": {"projectName": "sample", "capabilities": ["backend"]},
        }
        for request_id in range(5, 9)
    )
    requests.append({"id": 9, "method": "runs.list", "params": {"projectName": "sample"}})
    input_stream = io.StringIO("".join(json.dumps(request) + "\n" for request in requests))
    output_stream = io.StringIO()
    server = Thread(target=serve, args=(rpc, input_stream, output_stream))

    server.start()
    try:
        assert application.all_started.wait(timeout=1)
        assert application.list_returned.wait(timeout=1)
    finally:
        application.release.set()
        server.join(timeout=2)

    assert not server.is_alive()
    responses = [json.loads(line) for line in output_stream.getvalue().splitlines()]
    assert next(response for response in responses if response["id"] == 9) == {"id": 9, "result": []}


def test_pending_model_save_is_processed_while_all_work_threads_are_busy() -> None:
    class BlockingApplication(FakeApplication):
        def __init__(self) -> None:
            super().__init__()
            self.release = Event()
            self.started = Event()
            self.saved = Event()
            self.count = 0
            self.guard = Lock()

        def start(self, *_args: object, **_kwargs: object) -> dict[str, str]:
            with self.guard:
                self.count += 1
                if self.count == 4:
                    self.started.set()
            self.release.wait(timeout=3)
            return {"id": "run"}

        def update_task_execution_profile(self, *_args: object, **_kwargs: object) -> dict[str, str]:
            self.saved.set()
            return {"id": "run", "model": "selected-model"}

    application = BlockingApplication()
    requests = [{"id": index, "method": "runs.start", "params": {"projectName": "sample", "specPath": "plan"}} for index in range(4)]
    requests.append({"id": 4, "method": "tasks.updateExecutionProfile", "params": {
        "projectName": "sample", "runId": "run", "taskId": "pending-task", "agentId": "codex", "model": "selected-model",
        "expectedProfile": {"agent_id": "codex", "model": "old-model", "reasoning_effort": "", "last_attempt_id": "", "status": "pending"},
    }})
    output = io.StringIO()
    server = Thread(target=serve, args=(RpcService(application), io.StringIO("".join(json.dumps(item) + "\n" for item in requests)), output))
    server.start()
    try:
        assert application.started.wait(timeout=1)
        assert application.saved.wait(timeout=1)
    finally:
        application.release.set()
        server.join(timeout=3)
    assert not server.is_alive()
    responses = [json.loads(line) for line in output.getvalue().splitlines()]
    assert next(item for item in responses if item["id"] == 4)["result"]["model"] == "selected-model"


def test_register_project_creates_managed_config_and_remembers_source(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    planning = tmp_path / "planning"
    repo.mkdir()
    run_command(["git", "init", "-b", "trunk"], repo)
    run_command(["git", "config", "user.name", "Test"], repo)
    run_command(["git", "config", "user.email", "test@example.com"], repo)
    (repo / "README.md").write_text("ready", encoding="utf-8")
    run_command(["git", "add", "README.md"], repo)
    run_command(["git", "commit", "-m", "initial"], repo)
    planning.mkdir()
    registry = ProjectRegistry(tmp_path / "app-data" / "projects.json")
    application = DesktopApplication(registry)

    project = application.register_project("Example", repo, planning_source_dir=planning)

    assert project.config_path == registry.managed_config_path(repo)  # type: ignore[attr-defined]
    assert project.config_path.is_file()  # type: ignore[attr-defined]
    assert not (repo / "orchestrator.toml").exists()
    assert project.planning_source_dir == planning.resolve()  # type: ignore[attr-defined]
    assert load_config(project.config_path).project.main_branch == "trunk"  # type: ignore[attr-defined]


def test_register_project_rejects_repository_without_first_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    registry = ProjectRegistry(tmp_path / "app-data" / "projects.json")
    application = DesktopApplication(registry)

    with pytest.raises(Exception, match="not ready: not_initialized"):
        application.register_project("Example", repo)


def test_application_preserves_pipeline_approval_boundaries(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config_path = _write_config(repo)
    registry = ProjectRegistry(tmp_path / "projects.json")
    registry.add("Example", repo, config_path)
    application = DesktopApplication(registry)
    expected = RunState(id="run-1", spec_path="plan.md", spec_digest="abc", repo_path=str(repo), main_branch="main", stage=Stage.MERGED)

    with patch("ai_orchestrator.desktop_rpc.Pipeline") as pipeline_class:
        pipeline = pipeline_class.return_value
        pipeline.merge.return_value = expected
        pipeline.cleanup_workspace.return_value = {"state": "cleaned"}

        assert application.approved_run_action("Example", "run-1", "merge", approved=True, request_id="request") is expected
        application.cleanup_workspace("Example", "run-1", "task-1", approved=True)

    pipeline.merge.assert_called_once_with("run-1", approved=True, request_id="request")
    pipeline.cleanup_workspace.assert_called_once_with("run-1", "task-1", approved=True)


@pytest.mark.parametrize("role", ["planning", "execution"])
def test_provider_profiles_expand_models_and_reasoning(tmp_path: Path, role: str) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config_path = _write_config(repo)
    registry = ProjectRegistry(tmp_path / "projects.json")
    registry.add("Example", repo, config_path)
    application = DesktopApplication(registry)

    with patch("ai_orchestrator.desktop_rpc.Pipeline") as pipeline_class:
        choices = [ProviderChoice("codex", "planner", is_default=True)]
        if role == "planning":
            pipeline_class.return_value.planning_provider_choices.return_value = choices
            profiles = application.planning_provider_choices("Example")
        else:
            pipeline_class.return_value.execution_provider_choices.return_value = choices
            profiles = application.execution_provider_choices("Example", ["general"])
            pipeline_class.return_value.execution_provider_choices.assert_called_once_with(["general"])

    models = {profile["model"] for profile in profiles}  # type: ignore[index]
    assert models == {"", "gpt-6.1-sol", "gpt-6.1-terra", "gpt-6-luna"}
    updated_sol = next(profile for profile in profiles if profile["model"] == "gpt-6.1-sol")  # type: ignore[index]
    assert "medium" in updated_sol["reasoning_efforts"]  # type: ignore[operator]
    assert "max" in updated_sol["reasoning_efforts"]  # type: ignore[operator]
    assert "ultra" not in updated_sol["reasoning_efforts"]  # type: ignore[operator]
    terra = next(profile for profile in profiles if profile["model"] == "gpt-6.1-terra")  # type: ignore[index]
    assert terra["reasoning_efforts"] == ["low", "medium", "high", "xhigh", "max", "ultra"]
    assert terra["agent_id"] == "planner"


def test_configured_astra_model_remains_selectable_with_automatic_option() -> None:
    from ai_orchestrator.desktop_rpc import _expanded_provider_choices

    profiles = _expanded_provider_choices([ProviderChoice("codex", "planner", model="gpt-6-astra", is_default=True)])
    models = {profile["model"] for profile in profiles}
    assert "gpt-6-astra" in models
    assert "" in models
    assert "gpt-6.1-sol" in models


def test_claude_provider_profiles_are_available_for_new_selection() -> None:
    from ai_orchestrator.desktop_rpc import _expanded_provider_choices

    profiles = _expanded_provider_choices(
        [
            ProviderChoice("claude", "claude-ai", model="sonnet", is_default=True),
            ProviderChoice("codex", "codex-general", model="gpt-6-sol"),
        ]
    )

    assert {profile["provider_id"] for profile in profiles} == {"claude", "codex"}
    assert any(profile["agent_id"] == "claude-ai" and profile["model"] == "sonnet" for profile in profiles)
    assert any(profile["agent_id"] == "claude-ai" and profile["model"] == "claude-opus-5-5" for profile in profiles)
    assert next(profile for profile in profiles if profile["is_default"])["provider_id"] == "claude"


def test_claude_status_is_global_read_only_rpc() -> None:
    rpc, application = service()
    rpc.dispatch("auth.claude.status", {})
    assert application.calls == [("claude_auth_status", {})]


def test_application_rejects_registry_when_config_repository_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    other = tmp_path / "other"
    repo.mkdir()
    other.mkdir()
    config_path = _write_config(repo)
    registry = ProjectRegistry(tmp_path / "projects.json")
    registry.add("Example", repo, config_path)
    config_path.write_text(
        f"""
[project]
repo = {str(other)!r}

[[agents]]
id = "manual"
capabilities = ["general"]
command = []
""",
        encoding="utf-8",
    )
    application = DesktopApplication(registry)

    with pytest.raises(ValueError, match="changed repository"):
        application.runs("Example")


def _write_config(repo: Path) -> Path:
    config_path = repo / "orchestrator.toml"
    config_path.write_text(
        """
[project]
repo = "."

[[agents]]
id = "manual"
capabilities = ["general"]
command = []
""",
        encoding="utf-8",
    )
    return config_path


def test_recovery_rpc_requires_approval_and_forwards_reviewed_selection() -> None:
    rpc, application = service()
    params = {
        "projectName": "sample",
        "runId": "failed",
        "fingerprint": "reviewed",
        "sourceIds": ["source"],
    }
    with pytest.raises(Exception, match="approval"):
        rpc.dispatch("runs.applyRecovery", params)
    assert not application.calls
    rpc.dispatch("runs.recoveryPlan", params)
    assert application.calls[-1][0] == "recovery_plan"
    rpc.dispatch("runs.applyRecovery", {**params, "approved": True})
    assert application.calls[-1] == (
        "apply_recovery",
        "sample",
        "failed",
        "reviewed",
        ["source"],
        {"approved": True},
    )


def test_recovery_tracking_rpc_forwards_request_identity_and_status_reads() -> None:
    rpc, application = service()
    request_id = "43aa358f-e93d-44fe-a98f-e53fcb926992"
    resume_id = "fdb2e403-6141-4cec-868f-723be1c33d5e"
    common = {"projectName": "sample", "runId": "failed", "requestId": request_id}

    rpc.dispatch("runs.recoveryPlan", common)
    assert application.calls[-1] == ("recovery_plan", "sample", "failed", {"request_id": request_id})
    rpc.dispatch("operations.get", common)
    assert application.calls[-1] == ("recovery_operation", "sample", "failed", request_id, {})
    rpc.dispatch("operations.latest", {"projectName": "sample", "runId": "failed", "kind": "recovery_preview"})
    assert application.calls[-1] == ("latest_recovery_operation", "sample", "failed", "recovery_preview", {})
    rpc.dispatch("runs.applyRecovery", {
        **common,
        "fingerprint": "reviewed",
        "sourceIds": ["source"],
        "resumeRequestId": resume_id,
        "approved": True,
    })
    assert application.calls[-1] == (
        "apply_recovery",
        "sample",
        "failed",
        "reviewed",
        ["source"],
        {"approved": True, "request_id": request_id, "resume_request_id": resume_id},
    )


def test_execution_stop_and_verification_repair_rpc_preserve_request_identity() -> None:
    rpc, application = service()
    stop_request = "43aa358f-e93d-44fe-a98f-e53fcb926992"
    execution_id = "fdb2e403-6141-4cec-868f-723be1c33d5e"
    rpc.dispatch(
        "runs.requestStop",
        {
            "projectName": "sample",
            "runId": "running",
            "requestId": stop_request,
            "executionId": execution_id,
            "scope": "task",
            "taskId": "task-1",
            "attemptId": "attempt-1",
            "invocationId": "invocation-1",
        },
    )
    assert application.calls[-1] == (
        "request_stop",
        "sample",
        "running",
        {
            "request_id": stop_request,
            "execution_id": execution_id,
            "scope": "task",
            "task_id": "task-1",
            "attempt_id": "attempt-1",
            "invocation_id": "invocation-1",
        },
    )

    rpc.dispatch(
        "runs.verifyAndRepair",
        {"projectName": "sample", "runId": "running", "requestId": stop_request},
    )
    assert application.calls[-1] == ("verify_and_repair", "sample", "running", stop_request, {})


def test_conflict_resolution_rpc_separates_preview_generation_and_approved_apply() -> None:
    rpc, application = service()
    common = {
        "projectName": "sample",
        "runId": "failed",
        "conflictId": "conflict-1",
        "fingerprint": "fingerprint",
        "requestId": "da49bb4c-c543-4d6a-bcff-f92bf512ec48",
    }

    rpc.dispatch("runs.integrationConflict", {**common, "filePath": "docs/계획.md", "recoveryTaskId": "recovery-1"})
    assert application.calls[-1] == (
        "integration_conflict", "sample", "failed", "conflict-1", "docs/계획.md", "recovery-1", {}
    )
    rpc.dispatch("runs.prepareConflictResolution", {**common, "agentId": "worker", "model": "model", "reasoningEffort": "high"})
    assert application.calls[-1][0] == "prepare_conflict_resolution"
    with pytest.raises(Exception, match="approval"):
        rpc.dispatch(
            "runs.applyConflictResolution",
            {**common, "candidateId": "candidate-1", "candidateRevision": 1},
        )
    rpc.dispatch(
        "runs.applyConflictResolution",
        {**common, "candidateId": "candidate-1", "candidateRevision": 1, "approved": True},
    )
    assert application.calls[-1][0] == "apply_conflict_resolution"
