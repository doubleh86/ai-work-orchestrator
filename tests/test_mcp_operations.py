from __future__ import annotations

import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from ai_orchestrator.config import load_config
from ai_orchestrator.desktop_rpc import DesktopApplication
from ai_orchestrator.mcp_operations import McpOperations
from ai_orchestrator.models import RunState, RunStep, Stage, TaskActionResult, TaskStatus, VerificationAttempt, WorkTask
from ai_orchestrator.pipeline import Pipeline
from ai_orchestrator.registry import ProjectRegistry
from ai_orchestrator.task_scope_review import TaskScopeReview


def test_stdio_creates_and_connects_document_then_handles_current_failure(tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    from anyio import fail_after, run
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.types import ElicitResult

    registry = ProjectRegistry(tmp_path / "registry.json")
    projects = tmp_path / "projects"
    projects.mkdir()
    env = {key: os.environ[key] for key in ("PYTHONPATH", "SYSTEMROOT", "PATH") if key in os.environ}
    env.update(GIT_CEILING_DIRECTORIES=str(projects), GIT_CONFIG_COUNT="2", GIT_CONFIG_KEY_0="user.name",
               GIT_CONFIG_VALUE_0="MCP Fixture", GIT_CONFIG_KEY_1="user.email", GIT_CONFIG_VALUE_1="mcp@example.invalid",
               TEMP=str(tmp_path), TMP=str(tmp_path))
    args = ["-m", "ai_orchestrator.cli", "--registry", str(registry.path), "mcp"]

    async def scenario() -> None:
        from test_pipeline import git

        async with stdio_client(StdioServerParameters(command=sys.executable, args=args, env=env)) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                names = {tool.name for tool in (await client.list_tools()).tools}
                assert {"report_progress", "preview_main_apply"} <= names
                assert not {"create_project_with_document", "repair_and_continue", "approve_scope_and_retry", "apply_local_main"} & names
                response = await client.call_tool("attach_planning_document", {})
                assert response.isError and not registry.path.exists()

        prompts = []
        decision = "default"
        on_confirmation = None

        async def confirm(_context, params):
            prompts.append(params.message)
            if on_confirmation:
                on_confirmation()
            approved = decision != "decline" and len(prompts) != 1
            return ElicitResult(action="accept", content={"approve": True}) if approved else ElicitResult(action="decline")

        parameters = StdioServerParameters(command=sys.executable, args=[*args, "--allow-write", "--projects-root", str(projects)], env=env)
        async with stdio_client(parameters) as (reader, writer):
            async with ClientSession(reader, writer, elicitation_callback=confirm) as client:
                await client.initialize()

                async def call(name, **arguments):
                    response = await client.call_tool(name, arguments)
                    assert not response.isError, response.content
                    return response.structuredContent

                request = {"project_name": "예제", "document_name": "요구사항.md", "body": "# 기획서\n원격 연결 확인\n",
                           "request_id": str(uuid.uuid4())}
                assert (await call("create_project_with_document", **request))["status"] == "cancelled"
                assert not (projects / "예제").exists()
                result = await call("create_project_with_document", **request)
                assert result["index"]["document_count"] == 1
                assert (await call("create_project_with_document", **request))["document"] == result["document"]
                assert len(prompts) == 2 and str(projects / "예제") in prompts[-1]
                project = registry.get("예제")
                assert Path(result["document"]).read_text(encoding="utf-8") == request["body"]
                assert project.planning_source_dir == Path(result["document"]).parent
                assert len((await call("list_projects"))["projects"]) == 1

                for update in ({"body": "다른 본문"}, {"project_name": "../escape", "request_id": str(uuid.uuid4())}):
                    rejected = await client.call_tool("create_project_with_document", {**request, **update})
                    assert rejected.isError

                attach = {**request, "document_name": "추가.md", "request_id": str(uuid.uuid4())}
                extra = await call("attach_planning_document", **attach)
                assert extra["index"]["document_count"] == 2
                assert (await call("attach_planning_document", **attach))["document"] == extra["document"]
                assert (await client.call_tool("attach_planning_document", {**attach, "body": "변경", "request_id": str(uuid.uuid4())})).isError
                assert Path(extra["document"]).read_text(encoding="utf-8") == request["body"]

                pipeline = Pipeline(load_config(project.config_path))
                task = WorkTask("task", "실패한 작업", ["general"], status=TaskStatus.FAILED, error="sample failure",
                                last_attempt_id="attempt-1", expected_paths=["src/"])
                state = RunState("run", result["document"], "digest", str(project.repo), "main", Stage.FAILED,
                                 failed_step=RunStep.AGENT_EXECUTION, tasks=[task])
                state.add_event("task_repair_handoff", "task:attempt-1")
                pipeline.store.save(state)

                attention = (await call("list_attention"))["items"]
                pending = next(item for item in attention if item["task_id"] == "task")
                assert pending["automatic_recovery_stopped"] and pending["attempt_id"] == "attempt-1"
                assert (await call("list_attention"))["items"][0]["review_id"] == pending["review_id"]
                target = {"project_name": "예제", "run_id": "run", "task_id": "task"}
                failure = await call("inspect_task_failure", **target)
                assert failure["expected_paths"] == ["src/"] and failure["error"] == "sample failure"
                assert failure["next_action"]["kind"] == "repair_and_continue"
                report = {**target, "fingerprint": failure["fingerprint"], "diagnosis": "테스트의 실패 조건을 확인했습니다."}
                await call("record_task_diagnosis", **report)
                await call("record_task_diagnosis", **report)
                current = pipeline.store.load("run")
                assert len([event for event in current.events if event.kind == "task_diagnosis"]) == 1
                assert (await call("get_run", project_name="예제", run_id="run"))["stage"] == "failed"
                current.tasks[0].last_attempt_id = "attempt-2"
                pipeline.store.save(current)
                assert (await client.call_tool("record_task_diagnosis", report)).isError
                assert (await client.call_tool("get_run", {"project_name": "예제", "run_id": "../run"})).isError

                current.tasks[0].error = TaskScopeReview("자동 종료 뒤 참가 마침 저장이 필요합니다.", ("service/Topic.cs",)).error(
                    pipeline._task_scope_contract_digest(current.tasks[0]))
                current.tasks[0].action_results = [TaskActionResult("execute", attempt_id="attempt-2", status="failed",
                                                                   error=current.tasks[0].error)]
                pipeline.store.save(current)
                failure = await call("inspect_task_failure", **target)
                assert failure["next_action"]["kind"] == "approve_scope_and_retry"
                scope = failure["scope_review"]
                assert scope["paths"] == ["service/Topic.cs"] and "참가 마침" in scope["reason"]
                approval = {**target, "request_id": str(uuid.uuid4()), "review_id": scope["review_id"]}
                decision = "decline"
                assert (await call("approve_scope_and_retry", **approval))["status"] == "cancelled"
                assert "service/Topic.cs" in prompts[-1]

                def change_attempt():
                    current.tasks[0].last_attempt_id = "attempt-3"
                    pipeline.store.save(current)

                decision = "accept"
                on_confirmation = change_attempt
                assert (await client.call_tool("approve_scope_and_retry", approval)).isError
                assert pipeline.store.load("run").tasks[0].expected_paths == ["src/"]
                on_confirmation = None

                main_target = {"project_name": "예제", "run_id": "apply"}
                branch = "ai-integration/apply"
                worktree = tmp_path / "apply-worktree"
                base = pipeline.git.head(project.repo)
                pipeline.git.create_worktree(worktree, branch)
                (worktree / "result.txt").write_text("verified\n", encoding="utf-8")
                git(worktree, "add", "result.txt")
                git(worktree, "-c", "user.name=MCP Fixture", "-c", "user.email=mcp@example.invalid", "commit", "-m", "Result")
                head = pipeline.git.head(worktree)
                git(project.repo, "worktree", "remove", str(worktree))
                candidate = WorkTask("candidate", "검증된 작업", ["general"], status=TaskStatus.COMPLETED, branch=branch)
                run = RunState("apply", result["document"], "digest", str(project.repo), "main", Stage.VERIFIED, tasks=[candidate],
                               verified_main_head=base, verified_integration_head=head, verified_task_heads={candidate.id: head},
                               verification_attempts=[VerificationAttempt(status="succeeded", main_head=base, integration_head=head)])
                pipeline.store.save(run)
                review = await call("preview_main_apply", **main_target)
                assert review["can_apply"] and review["target_commit"] == head
                assert review["files"][0]["path"] == "result.txt" and review["verification"]["status"] == "succeeded"
                apply = {**main_target, "review_id": review["review_id"], "request_id": str(uuid.uuid4())}
                decision = "decline"
                assert (await call("apply_local_main", **apply))["status"] == "cancelled"
                assert pipeline.git.head(project.repo) == base
                decision = "accept"
                applied = await call("apply_local_main", **apply)
                assert applied["stage"] == "merged" and applied["main_commit"] == head and not applied["remote_push_performed"]
                assert pipeline.git.head(project.repo) == head
                count = len(prompts)
                assert await call("apply_local_main", **apply) == applied
                assert len(prompts) == count

    async def bounded_scenario() -> None:
        with fail_after(60):
            await scenario()

    run(bounded_scenario)


def test_registry_writers_share_the_same_lock(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    repos = [tmp_path / f"repo-{index}" for index in range(12)]
    for repo in repos:
        repo.mkdir()
        (repo / "orchestrator.toml").touch()
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda repo: ProjectRegistry(path).add(repo.name, repo), repos))
    assert {item.repo for item in ProjectRegistry(path).list()} == set(repos)


def test_task_draft_reuses_the_reserved_run_and_keeps_existing_plan_gate(tmp_path: Path) -> None:
    registry = ProjectRegistry(tmp_path / "registry.json")
    (tmp_path / "orchestrator.toml").touch()
    registry.add("project", tmp_path, planning_source_dir=tmp_path)
    application = DesktopApplication(registry)
    operations = McpOperations(application, allow_write=True)
    request_id = str(uuid.uuid4())
    run_id = "mcp-" + uuid.UUID(request_id).hex
    planned = RunState(run_id, "plan.md", "digest", str(tmp_path), "main", Stage.PLANNED)
    try:
        with patch.object(application, "runs", side_effect=[[], [Mock(id=run_id, stage=Stage.PLANNED)]]), \
             patch.object(application, "prepare_planning") as prepare, \
             patch.object(application, "run_planning", return_value=planned) as planning, \
             patch.object(operations, "run", return_value={"run_id": run_id}) as status:
            assert operations.draft_tasks("project", request_id, "existing_structure")["run_id"] == run_id
            assert operations.draft_tasks("project", request_id, "existing_structure")["run_id"] == run_id
            prepare.assert_called_once_with("project", tmp_path, repository_intent="existing_structure", reserved_run_id=run_id)
            planning.assert_called_once_with("project", run_id)
            status.assert_called_once_with("project", run_id)
            with pytest.raises(ValueError, match="같은 요청 ID"):
                operations.draft_tasks("project", request_id, "new_project")
    finally:
        application.close()
