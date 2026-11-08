from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path
from dataclasses import replace
from threading import Event
from unittest.mock import Mock, patch

import pytest

from ai_orchestrator import mcp_bundle, result_artifacts
from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, ProjectConfig
from ai_orchestrator.desktop_rpc import DesktopApplication, RpcService
from ai_orchestrator.mcp_operations import McpOperations
from ai_orchestrator.models import RunState, Stage, UserCheck
from ai_orchestrator.pipeline import Pipeline, PipelineError
from ai_orchestrator.registry import ProjectRegistry
from ai_orchestrator.result_artifacts import ResultArtifact, artifact_digest, artifact_path, inspect_result, launch_result
from test_pipeline import git


@pytest.fixture
def pipeline(tmp_path: Path) -> Pipeline:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / ".gitignore").write_text("build/\n", encoding="utf-8")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-m", "Initial")
    return Pipeline(Config(path=tmp_path / "orchestrator.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(),
                           agents=(AgentConfig("general", ("general",), (sys.executable, "-c", "pass"), 1),)))


def draft() -> dict[str, object]:
    return {"id": "app", "title": "앱 만들기", "description": "작은 앱을 만든다.", "capabilities": ["general"],
            "depends_on": [], "acceptance_criteria": ["앱이 시작된다."], "expected_paths": ["src/"], "forbidden_paths": [],
            "verify_commands": [[sys.executable, "-c", "pass"]], "risk_level": "low"}


def test_empty_project_accepts_external_plan_without_planning_ai_and_rejects_stale_control(pipeline: Pipeline) -> None:
    with patch.object(pipeline, "_build_plan", side_effect=AssertionError("no planning AI")):
        state = pipeline.submit_external_plan(f"mcp-plan-{uuid.uuid4().hex}", expected_base_commit=pipeline.git.head(pipeline.config.project.repo),
                                              summary="새 앱", requirements="처음부터 만든다.", task_drafts=[draft()])
    assert state.stage == Stage.PLANNED and state.repository_intent == "external_plan"
    assert not state.plan_is_approved
    saved = pipeline.store.load(state.id)
    assert saved.tasks[0].agent_id
    assert sum(event.summary_code == "plan_confirmation_required" for event in saved.notification_events) == 1
    with pytest.raises(PipelineError, match="계획이 변경"):
        pipeline.update_plan(state.id, [draft()], expected_revision=0)
    pipeline.confirm_plan(state.id, expected_revision=1)
    with pytest.raises(PipelineError, match="계획이 변경"):
        pipeline.execute(state.id, expected_revision=0)
    assert not pipeline.store.load(state.id).execution_worktree


def test_external_plan_runs_local_worker_and_verifies_without_planning_ai(pipeline: Pipeline) -> None:
    worker = ("from pathlib import Path; Path('src').mkdir(exist_ok=True); Path('src/app.py').write_text('value = 1\\n'); "
              "Path('src/index.html').write_text('<h1>Fixture</h1>')")
    pipeline = Pipeline(replace(pipeline.config, agents=(AgentConfig("general", ("general",), (sys.executable, "-c", worker), 1),)))
    with patch.object(pipeline, "_build_plan", side_effect=AssertionError("no planning AI")):
        state = pipeline.submit_external_plan(f"mcp-plan-{uuid.uuid4().hex}", expected_base_commit=pipeline.git.head(pipeline.config.project.repo),
                                              summary="새 앱", requirements="처음부터 만든다.", task_drafts=[draft()],
                                              user_checks=(UserCheck("preview", "직접 실행", "결과를 확인한다.", ("화면이 보인다.",), "app",
                                                                     required_for_integration=True),))
        pipeline.confirm_plan(state.id, expected_revision=1)
        result = pipeline.execute(state.id, expected_revision=1)
        assert all(task.status == "completed" for task in result.tasks), result.failure_message
        context = pipeline.result_artifact_info(state.id)
        assert context["verification_scope"] == "task"
        preview = pipeline.register_result_artifact(state.id, kind="web", relative_path="src/index.html", expected_commit=context["reference_commit"])
        assert preview["can_launch"] and preview["verification_scope"] == "task"
        with pytest.raises(PipelineError):
            pipeline.verify(state.id)
        assert pipeline.store.load(state.id).integration_user_checks_pending()
        pipeline.record_user_check(state.id, "preview", expected_revision=1, expected_commit=context["reference_commit"],
                                   outcome="passed", note="격리된 결과를 확인함")
        verified = pipeline.verify(state.id)
        assert verified.stage == Stage.VERIFIED and verified.verified_integration_head
        assert (Path(verified.execution_worktree) / "src" / "app.py").read_text() == "value = 1\n"


def test_control_roles_confirmation_receipt_and_interrupted_execution(tmp_path: Path) -> None:
    (tmp_path / "projects").mkdir()
    application = DesktopApplication(ProjectRegistry(tmp_path / "registry.json"))
    operations = McpOperations(application, allow_control=True, projects_root=tmp_path / "projects")
    state = RunState("run", "", "", str(tmp_path), "main", Stage.PLANNED, summary="작은 앱", plan_revision=2)
    view = {"id": state.id, "summary": state.summary, "stage": state.stage, "plan_revision": 2, "tasks": []}
    try:
        with patch.object(application, "status", return_value=view), patch.object(application, "confirm_plan", return_value=state) as confirm:
            review = operations.review_plan("project", "run")
            request = str(uuid.uuid4())
            assert operations.confirm_plan("project", "run", request, review["review_id"])["status"] == "confirmation_required"
            confirm.assert_not_called()
            with patch.object(operations, "_run_result", return_value={"status": "confirmed"}):
                first = operations.confirm_plan("project", "run", request, review["review_id"], approved=True)
                assert operations.confirm_plan("project", "run", request, review["review_id"]) == first
            confirm.assert_called_once_with("project", "run", expected_revision=2)
            with pytest.raises(ValueError, match="계획"):
                operations.confirm_plan("project", "run", str(uuid.uuid4()), "old-review", approved=True)
        request = str(uuid.uuid4())
        with patch.object(application, "status", return_value=view), \
             patch.object(application, "execute", side_effect=RuntimeError("interrupted")) as execute:
            with pytest.raises(RuntimeError, match="interrupted"):
                operations.control_run("project", "run", request, "execute", 2)
            with patch.object(operations, "run", return_value={"stage": "executing"}):
                assert operations.control_run("project", "run", request, "execute", 2)["request_status"] == "observed_after_interruption"
            execute.assert_called_once()
        for revision in (True, 0):
            with pytest.raises(ValueError):
                operations.control_run("project", "run", str(uuid.uuid4()), "execute", revision)
        with pytest.raises(PermissionError):
            McpOperations(application).control_run("project", "run", str(uuid.uuid4()), "execute", 2)
    finally:
        application.close()


def test_control_server_exposes_external_planning_and_result_registration_only(tmp_path: Path) -> None:
    (tmp_path / "projects").mkdir()
    pytest.importorskip("mcp")
    from anyio import run
    from mcp.shared.memory import create_connected_server_and_client_session
    from ai_orchestrator.mcp_server import build_server

    application = DesktopApplication(ProjectRegistry(tmp_path / "registry.json"))

    async def scenario() -> None:
        for options in ({}, {"allow_planning": True}, {"allow_control": True, "projects_root": tmp_path / "projects"}):
            async with create_connected_server_and_client_session(build_server(McpOperations(application, **options))) as client:
                names = {tool.name for tool in (await client.list_tools()).tools}
                assert "draft_tasks" not in names
                assert ("submit_plan" in names) == bool(options)
                assert ("control_run" in names) == bool(options.get("allow_control"))
                assert ("register_result_artifact" in names) == bool(options.get("allow_control"))
    try:
        run(scenario)
    finally:
        application.close()


def test_background_control_returns_promptly_and_preserves_failures_and_retries(tmp_path: Path) -> None:
    (tmp_path / "projects").mkdir()
    application = DesktopApplication(ProjectRegistry(tmp_path / "registry.json"))
    operations = McpOperations(application, allow_control=True, projects_root=tmp_path / "projects")
    started, finish = Event(), Event()

    def execute(*args, **kwargs):
        started.set()
        assert finish.wait(5)
        raise RuntimeError("worker failed before execution")

    request = str(uuid.uuid4())
    try:
        with patch.object(application, "status", return_value={"plan_revision": 1}), \
             patch.object(application, "execute", side_effect=execute) as execute_mock, \
             patch.object(operations, "run", return_value={"stage": "planned"}):
            assert operations.start_control_run("project", "run", request, "execute", 1)["status"] == "queued"
            assert started.wait(5)
            assert operations.start_control_run("project", "run", request, "execute", 1)["status"] == "started"
            finish.set()
            operations.close()
            outcome = operations.control_request("project", "run", request)
            assert outcome["status"] == "failed" and "worker failed" in outcome["error"]
            assert operations.start_control_run("project", "run", request, "execute", 1)["status"] == "failed"
            execute_mock.assert_called_once()
            with pytest.raises(ValueError, match="프로젝트"):
                operations.control_request("other-project", "run", request)
    finally:
        finish.set()
        operations.close()
        application.close()


def test_result_registration_pins_verified_worktree_and_file_content(pipeline: Pipeline, tmp_path: Path) -> None:
    state = RunState("result", "", "", str(pipeline.config.project.repo), "main", Stage.VERIFIED)
    worktree = pipeline._shared_run_worktree_path(state)
    git(pipeline.config.project.repo, "worktree", "add", "-b", "ai/result", str(worktree))
    output = worktree / "build" / "index.html"
    output.parent.mkdir()
    output.write_text("<h1>Fixture</h1>", encoding="utf-8")
    state.execution_branch, state.execution_worktree = "ai/result", str(worktree)
    state.verified_integration_head = pipeline.git.head(worktree)
    pipeline.store.save(state)
    result = pipeline.register_result_artifact(state.id, kind="web", relative_path="build/index.html",
                                               expected_commit=state.verified_integration_head)
    assert result["can_launch"] and result["reference_commit"] == state.verified_integration_head
    with patch.object(result_artifacts.webbrowser, "open", return_value=True) as opened:
        assert pipeline.launch_result_artifact(state.id, expected_digest=result["digest"])["status"] == "launch_requested"
        opened.assert_called_once_with(output.as_uri())
    output.write_text("changed", encoding="utf-8")
    assert pipeline.result_artifact_info(state.id)["status"] == "changed"
    with pytest.raises(ValueError, match="바뀌었"):
        pipeline.launch_result_artifact(state.id, expected_digest=result["digest"])
    with pytest.raises(PipelineError, match="버전"):
        pipeline.register_result_artifact(state.id, kind="web", relative_path="build/index.html", expected_commit="stale")
    state.stage = Stage.EXECUTING
    pipeline.store.save(state)
    assert not pipeline.result_artifact_info(state.id)["can_launch"]


def test_background_call_returning_a_failed_run_is_reported_as_failure(tmp_path: Path) -> None:
    (tmp_path / "projects").mkdir()
    application = DesktopApplication(ProjectRegistry(tmp_path / "registry.json"))
    operations = McpOperations(application, allow_control=True, projects_root=tmp_path / "projects")
    failed = RunState("run", "", "", str(tmp_path), "main", Stage.FAILED, failure_message="provider failed")
    request = str(uuid.uuid4())
    try:
        with patch.object(application, "status", return_value={"plan_revision": 1}), \
             patch.object(application, "execute", return_value=failed), patch.object(operations, "run", return_value={"stage": "failed"}):
            operations.start_control_run("project", "run", request, "execute", 1)
            operations.close()
            result = operations.control_request("project", "run", request)
            assert result["status"] == "failed" and result["error"] == "provider failed"
    finally:
        operations.close()
        application.close()


@pytest.mark.parametrize("path", ["../app.exe", "/app.exe", "C:/app.exe", "build\\app.exe", ".git/app.exe", "build/app.txt"])
def test_result_paths_cannot_escape_or_use_other_file_types(tmp_path: Path, path: str) -> None:
    with pytest.raises((ValueError, OSError)):
        artifact_path(tmp_path, "windows", path)


def test_macos_result_requires_mac_and_changed_bundle_is_rejected(tmp_path: Path, monkeypatch) -> None:
    app = tmp_path / "Example.app"
    (app / "Contents").mkdir(parents=True)
    payload = app / "Contents" / "Info.plist"
    payload.write_text("fixture", encoding="utf-8")
    artifact = ResultArtifact("macos", app.name, "commit", artifact_digest(app))
    monkeypatch.setattr(result_artifacts.sys, "platform", "win32")
    assert inspect_result(tmp_path, artifact)["status"] == "needs_environment"
    payload.write_text("changed", encoding="utf-8")
    assert inspect_result(tmp_path, artifact)["status"] == "changed"


def test_windows_result_starts_only_the_registered_executable(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "fixture.exe"
    executable.write_bytes(b"fixture")
    artifact = ResultArtifact("windows", executable.name, "commit", artifact_digest(executable))
    monkeypatch.setattr(result_artifacts.sys, "platform", "win32")
    with patch.object(result_artifacts.subprocess, "Popen", return_value=Mock(pid=42)) as start:
        with pytest.raises(ValueError, match="변경"):
            launch_result(tmp_path, artifact, expected_digest="old")
        start.assert_not_called()
        assert launch_result(tmp_path, artifact, expected_digest=artifact.digest) == {
            "status": "started", "pid": 42, "kind": "windows", "reference_commit": "commit",
        }
        assert start.call_args.args[0] == [str(executable)]
        assert start.call_args.kwargs["cwd"] == executable.parent
        assert "shell" not in start.call_args.kwargs


def test_control_cli_accepts_the_registry_after_the_mcp_command(tmp_path: Path) -> None:
    from ai_orchestrator.cli import main

    with patch("ai_orchestrator.mcp_server.serve") as serve:
        assert main(["mcp", "--registry", str(tmp_path / "registry.json"), "--allow-control"]) == 0
        assert serve.call_args.args[0] == str(tmp_path / "registry.json")
        assert serve.call_args.kwargs["allow_control"] is True


def test_android_launch_selects_device_and_surfaces_start_failure(tmp_path: Path, monkeypatch) -> None:
    apk = tmp_path / "fixture.apk"
    apk.write_bytes(b"apk fixture")
    artifact = ResultArtifact("android", apk.name, "commit", artifact_digest(apk))
    monkeypatch.setattr(result_artifacts.shutil, "which", lambda name: name)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if command == ["adb", "devices"]:
            return subprocess.CompletedProcess(command, 0, "List of devices attached\nemulator-5554\tdevice\nphone\tdevice\n", "")
        if command[0] == "aapt":
            return subprocess.CompletedProcess(command, 0, "package: name='test.fixture'\nlaunchable-activity: name='test.fixture.Main'", "")
        return subprocess.CompletedProcess(command, 0, "Error: Activity class does not exist" if "start" in command else "Success", "")

    monkeypatch.setattr(result_artifacts.subprocess, "run", run)
    with pytest.raises(ValueError, match="선택"):
        launch_result(tmp_path, artifact, expected_digest=artifact.digest)
    with pytest.raises(ValueError, match="실행하지 못"):
        launch_result(tmp_path, artifact, expected_digest=artifact.digest, device_id="phone")
    assert ["adb", "-s", "phone", "install", "-r", str(apk)] in calls
    assert not any(command[:3] == ["adb", "-s", "emulator-5554"] for command in calls)


def test_external_claude_config_preserves_other_servers_and_codex_uses_control(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(mcp_bundle.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(mcp_bundle, "_windows_claude_package_families", lambda: ())
    registry = tmp_path / "registry.json"
    target = tmp_path / "Claude" / "claude_desktop_config.json"
    target.parent.mkdir()
    target.write_text(json.dumps({"mcpServers": {"other": {"command": "fixture"}}, "theme": "light"}), encoding="utf-8")
    assert mcp_bundle.register_external_connection("claude", registry)["status"] == "registered"
    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["theme"] == "light" and saved["mcpServers"]["other"] == {"command": "fixture"}
    assert saved["mcpServers"]["ai_work_orchestrator"]["args"][-3:] == ["--registry", str(registry), "--allow-control"]
    with patch("ai_orchestrator.codex_sdk.installed_codex_executable", return_value="codex"), \
         patch.object(mcp_bundle.subprocess, "run", return_value=Mock(returncode=0)) as run:
        assert mcp_bundle.register_external_connection("codex", registry)["status"] == "registered"
        command = run.call_args.args[0]
        assert command[:5] == ["codex", "mcp", "add", "ai_work_orchestrator", "--"]
        assert "--allow-control" in command


def test_new_rpc_paths_use_project_boundary_and_explicit_launch_version(tmp_path: Path) -> None:
    application = Mock()
    application.registry = ProjectRegistry(tmp_path / "registry.json")
    service = RpcService(application)
    service.dispatch("runs.launchResult", {"projectName": "fixture", "runId": "run", "expectedDigest": "digest", "deviceId": "phone"})
    application.launch_result.assert_called_once_with("fixture", "run", expected_digest="digest", device_id="phone")
    service.dispatch("runs.get", {"projectName": "fixture", "runId": "run", "includeUserChecks": True})
    application.status.assert_called_once_with("fixture", "run", include_user_checks=True)
