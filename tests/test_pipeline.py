import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, call, patch

from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, PlanningConfig, ProjectConfig, RoutingConfig
from ai_orchestrator.code_style import CodeStyleSnapshot, ProjectCodeStylePreference, inspect_project_code_style, inspect_task_code_style
from ai_orchestrator.codex_sdk import CodexSdkAccountStatus, CodexSdkError, CodexSdkExecutionProfile, CodexSdkProgress
from ai_orchestrator.git import LOCAL_GIT_TIMEOUT_SECONDS, REMOTE_GIT_TIMEOUT_SECONDS, GitError, DotnetDiagnostic, run_command
from ai_orchestrator.models import (
    BootstrapSpec,
    ConflictResolutionCandidate,
    ConflictResolutionStatus,
    DirectionChangeStatus,
    ExecutionWorkspaceMode,
    GroupResultRecord,
    IntegrationConflict,
    IntegrationStatus,
    PlanningMode,
    ProfileSource,
    PlanningApplyStatus,
    PlanningMessageRole,
    OperationRecord,
    ReviewStatus,
    RunArchive,
    ResultFileChange,
    RiskLevel,
    RunExecutionAction,
    RunExecutionControl,
    RunExecutionSituation,
    RunLockState,
    RunLockStatus,
    RunState,
    RunStep,
    Stage,
    TaskAction,
    TaskActionResult,
    TaskResultRecord,
    TaskReadiness,
    TaskStatus,
    TechStackComponents,
    TechStackDecision,
    TechStackDecisionStatus,
    TechStackOption,
    WorkTask,
    VerificationAttempt,
    WorkspaceLocation,
    WorkspaceLocationSource,
    WorkspaceState,
)
from ai_orchestrator.pipeline import (
    AGENT_OUTPUT_DRAIN_TIMEOUT_SECONDS,
    AGENT_TERMINATION_TIMEOUT_SECONDS,
    BOOTSTRAP_AGENTS_ACCEPTANCE,
    CODEX_INPUT_LIMIT_CHARACTERS,
    INTEGRATION_VERIFICATION_COMMAND_TIMEOUT_SECONDS,
    RUN_DELETION_TIMEOUT_SECONDS,
    TASK_LOG_DISPLAY_LIMIT_BYTES,
    ApprovalRequired,
    Pipeline,
    PipelineError,
    ProviderCapacityError,
    ProviderRequestLimitError,
    ProviderTimeoutError,
)
from ai_orchestrator.document_index import PLANNING_INDEX_TIMEOUT_SECONDS, load_planning_source_index
from ai_orchestrator.execution_control import ExecutionStopped
from ai_orchestrator.planner import Plan, PlanningError
from ai_orchestrator.store import StateStore


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, stdout=subprocess.PIPE, text=True)


def connected_codex_sdk() -> Mock:
    sdk = Mock()
    sdk.account_status.return_value = CodexSdkAccountStatus(True, "chatgpt", "로그인됨")
    return sdk


class PipelineTest(unittest.TestCase):
    def test_result_revision_ai_proposal_is_cached_and_retry_instruction_waits_for_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            agent = AgentConfig("codex-general", ("general",), (), provider_id="codex", model="gpt-6-sol")
            config = Config(
                path=root / "orchestrator.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(),
                planning=PlanningConfig(agent_id=agent.id), agents=(agent,),
            )
            sdk = connected_codex_sdk()
            pipeline = Pipeline(config, codex_sdk=sdk)
            task = WorkTask(
                "broken", "설정 저장", ["general"], status=TaskStatus.FAILED, error="저장 오류",
                action_results=[TaskActionResult("execute", status="failed", error="저장 오류", changed_paths=["settings.py"])],
            )
            source = RunState(
                id="proposal-source", spec_path="", spec_digest="digest", repo_path=str(repo), main_branch="main",
                stage=Stage.FAILED, failed_step=RunStep.AGENT_EXECUTION, tasks=[task],
            )
            pipeline.store.save(source)
            output = 'AI_RESULT_REVISION_PROPOSAL: {"summary":"설정 저장 오류 수정","reason":"broken Task의 실패 기록","task_ids":["broken"],"paths":["settings.py"],"question":""}'
            with patch.object(pipeline, "_invoke_provider_command", return_value=output) as provider:
                proposal = pipeline.propose_result_revision(source.id, proposal_id=str(uuid.uuid4()), text="", focus_task_id="broken")
                reused = pipeline.propose_result_revision(source.id, proposal_id=str(uuid.uuid4()), text="", focus_task_id="broken")
            self.assertEqual(proposal["status"], "ready")
            self.assertEqual(proposal["next_action"], "retry_task")
            self.assertEqual(reused["proposal_id"], proposal["proposal_id"])
            self.assertEqual(provider.call_count, 1)
            self.assertEqual(provider.call_args.kwargs["agent"].review_sandbox_mode, "read-only")
            self.assertEqual(provider.call_args.kwargs["agent"].review_approval_mode, "deny-all")
            self.assertEqual(pipeline._result_revision_retry_instruction(source.id, "broken"), "")
            saved = pipeline.create_result_revision_request(
                source.id, request_id=str(uuid.uuid4()), text="", task_ids=["broken"], paths=["settings.py"],
                proposal_id=str(proposal["proposal_id"]),
            )
            self.assertEqual(saved["target_run_id"], source.id)
            self.assertEqual(saved["handling"], "same_task_retry")
            context = pipeline.task_retry_context(source.id, "broken")
            self.assertTrue(context["instruction_current"])
            self.assertEqual(saved["retry_fingerprint"], context["fingerprint"])
            self.assertTrue(saved["task_contract_digest"])
            restored = pipeline.store.load(source.id)
            prompt = pipeline.waiting_prompt(restored, pipeline._summary_execution_control(restored))
            self.assertEqual((prompt["action"], prompt["task_id"]), ("retry", "broken"))
            self.assertIn(saved["request_id"], pipeline._result_revision_retry_instruction(source.id, "broken"))
            self.assertEqual(len(pipeline.store.list_runs()), 1)
            self.assertEqual(pipeline.store.load(source.id).tasks[0].status, TaskStatus.FAILED)
            self.assertEqual(pipeline.create_result_revision_request(
                source.id, request_id=saved["request_id"], text="", task_ids=["broken"], paths=["settings.py"],
                proposal_id=str(proposal["proposal_id"]),
            ), saved)
            task.prompt_path = str(root / "original-task.md")
            Path(task.prompt_path).write_text("원래 작업 지시", encoding="utf-8")
            with (patch.object(pipeline, "_run_executor") as execute,
                  patch.object(pipeline, "_run_task_verification"),
                  patch.object(pipeline, "_record_task_result"),
                  patch.object(pipeline.git, "head", return_value="c" * 40)):
                pipeline._run_task(source, task)
            self.assertIn(saved["request_id"], execute.call_args.args[2])
            self.assertIn("원래 작업 지시", execute.call_args.args[2])
            source.stage = Stage.PUSHED
            source.tasks[0].status = TaskStatus.COMPLETED
            pipeline.store.save(source)
            self.assertEqual(pipeline.create_result_revision_request(
                source.id, request_id=saved["request_id"], text="", task_ids=["broken"], paths=["settings.py"],
                proposal_id=str(proposal["proposal_id"]),
            ), saved)

    def test_result_revision_ai_proposal_rejects_unsupported_evidence_and_stale_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            agent = AgentConfig("codex-general", ("general",), (), provider_id="codex", model="gpt-6-sol")
            pipeline = Pipeline(
                Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(),
                       planning=PlanningConfig(agent_id=agent.id), agents=(agent,)), codex_sdk=connected_codex_sdk(),
            )
            source = RunState(
                id="stale-proposal", spec_path="", spec_digest="digest", repo_path=str(repo), main_branch="main",
                stage=Stage.PUSHED, tasks=[WorkTask("done", "완료", ["general"], status=TaskStatus.COMPLETED)],
            )
            pipeline.store.save(source)
            question = pipeline._parse_result_revision_proposal(
                source,
                'AI_RESULT_REVISION_PROPOSAL: {"summary":"","reason":"","task_ids":[],"paths":[],"question":"어느 문구를 바꿀까요?"}',
            )
            self.assertEqual(question["status"], "needs_clarification")
            self.assertEqual(question["task_ids"], [])
            invalid = 'AI_RESULT_REVISION_PROPOSAL: {"summary":"수정","reason":"근거","task_ids":["missing"],"paths":[],"question":""}'
            valid = 'AI_RESULT_REVISION_PROPOSAL: {"summary":"완료 수정","reason":"done Task","task_ids":["done"],"paths":[],"question":""}'
            with patch.object(pipeline, "_invoke_provider_command", side_effect=[invalid, valid]):
                rejected = pipeline.propose_result_revision(source.id, proposal_id=str(uuid.uuid4()), text="문구 수정")
                proposal = pipeline.propose_result_revision(source.id, proposal_id=str(uuid.uuid4()), text="문구 수정")
            self.assertEqual(rejected["status"], "failed")
            self.assertIn("없는 Task", rejected["error"])
            self.assertEqual(proposal["status"], "ready")
            accepted = pipeline.create_result_revision_request(
                source.id, request_id=str(uuid.uuid4()), text="문구 수정", task_ids=["done"], paths=[],
                proposal_id=str(proposal["proposal_id"]),
            )
            self.assertNotEqual(accepted["target_run_id"], source.id)
            self.assertEqual(pipeline.store.load(str(accepted["target_run_id"])).stage, Stage.REVIEWED)
            source.tasks[0].error = "결과 변경"
            pipeline.store.save(source)
            self.assertTrue(pipeline.result_revision_requests(source.id)["proposals"][-1]["stale"])
            with self.assertRaisesRegex(PipelineError, "원본 결과가 변경"):
                pipeline.create_result_revision_request(
                    source.id, request_id=str(uuid.uuid4()), text="문구 수정", task_ids=["done"], paths=[],
                    proposal_id=str(proposal["proposal_id"]),
                )

    def test_result_revision_same_group_is_draft_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline = Pipeline(Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=()))
            source = RunState(
                id="revision-source", spec_path="", spec_digest="digest", repo_path=str(repo), main_branch="main",
                stage=Stage.EXECUTING, summary="원본", tasks=[WorkTask(
                    "finished", "완료 Task", ["general"], status=TaskStatus.COMPLETED,
                    action_results=[TaskActionResult("execute", status="succeeded", changed_paths=["README.md", "transient.txt"])],
                    completed_commit="b" * 40,
                    result_history=[TaskResultRecord(
                        "a" * 40, "b" * 40, "2026-09-29T00:00:00+00:00",
                        files_state="confirmed", files=[ResultFileChange("README.md", "M")],
                    )],
                )],
            )
            pipeline.store.save(source)
            request_id = str(uuid.uuid4())
            first = pipeline.create_result_revision_request(
                source.id, request_id=request_id, text="문구를 수정해 주세요", task_ids=["finished"], paths=["README.md"]
            )
            second = pipeline.create_result_revision_request(
                source.id, request_id=request_id, text="문구를 수정해 주세요", task_ids=["finished"], paths=["README.md"]
            )

            self.assertEqual(first, second)
            self.assertEqual(first["target_run_id"], source.id)
            self.assertEqual(len(pipeline.store.list_runs()), 1)
            self.assertEqual(pipeline.store.load(source.id).tasks[0].status, TaskStatus.COMPLETED)
            self.assertEqual(len(pipeline.result_revision_requests(source.id)["requests"]), 1)
            with self.assertRaisesRegex(PipelineError, "다른 내용"):
                pipeline.create_result_revision_request(
                    source.id, request_id=request_id, text="다른 요청", task_ids=["finished"], paths=["README.md"]
                )
            with self.assertRaisesRegex(PipelineError, "기록되지 않은"):
                pipeline.create_result_revision_request(
                    source.id, request_id=str(uuid.uuid4()), text="수정", task_ids=["finished"], paths=["outside.py"]
                )
            with self.assertRaisesRegex(PipelineError, "기록되지 않은"):
                pipeline.create_result_revision_request(
                    source.id, request_id=str(uuid.uuid4()), text="수정", task_ids=["finished"], paths=["transient.txt"]
                )
            source.stage = Stage.PUSHED
            pipeline.store.save(source)
            moved = pipeline.create_result_revision_request(
                source.id, request_id=request_id, text="문구를 수정해 주세요", task_ids=["finished"], paths=["README.md"]
            )
            self.assertNotEqual(moved["target_run_id"], source.id)
            self.assertEqual(moved["created_at"], first["created_at"])
            self.assertEqual(len(pipeline.store.list_runs()), 2)

    def test_result_revision_archived_source_creates_linked_prepared_group_without_running_ai(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline = Pipeline(Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=()))
            source = RunState(
                id="archived-source", spec_path="", spec_digest="digest", repo_path=str(repo), main_branch="main",
                stage=Stage.PUSHED, summary="보관 원본", tasks=[WorkTask("finished", "완료 Task", ["general"], status=TaskStatus.COMPLETED)],
                archive=RunArchive("now", "revision", "snapshot", "manifest", "summary", "fingerprint"),
            )
            pipeline.store.save(source)
            original = pipeline.store.state_path(source.id).read_bytes()
            request_id = str(uuid.uuid4())
            first = pipeline.create_result_revision_request(
                source.id, request_id=request_id, text="작은 창에서 다시 확인", task_ids=["finished"], paths=[]
            )
            child = pipeline.store.load(str(first["target_run_id"]))
            self.assertEqual(child.stage, Stage.REVIEWED)
            self.assertEqual(child.revision_source_run_id, source.id)
            self.assertEqual(child.revision_request_id, request_id)
            self.assertIn("작은 창에서 다시 확인", child.planning_request)
            self.assertEqual(pipeline.store.state_path(source.id).read_bytes(), original)
            self.assertTrue(pipeline.store.revision_requests_path(source.id).is_file())
            self.assertFalse((pipeline.store.run_dir(source.id) / "revision-requests.json").exists())
            self.assertEqual(pipeline.create_result_revision_request(
                source.id, request_id=request_id, text="작은 창에서 다시 확인", task_ids=["finished"], paths=[]
            ), first)
            self.assertEqual(len(pipeline.store.list_runs()), 2)
            links = pipeline.result_revision_requests(child.id)
            self.assertEqual(links["origin"].id, source.id)
            self.assertEqual(links["children"], [])
            self.assertEqual([item.id for item in pipeline.result_revision_requests(source.id)["children"]], [child.id])
            child.stage = Stage.PUSHED
            child.tasks = [WorkTask("follow-up", "후속 Task", ["general"], status=TaskStatus.COMPLETED)]
            pipeline.store.save(child)
            repeated = pipeline.create_result_revision_request(
                child.id, request_id=str(uuid.uuid4()), text="다시 다듬어 주세요", task_ids=["follow-up"], paths=[]
            )
            grandchild = pipeline.store.load(str(repeated["target_run_id"]))
            self.assertEqual(grandchild.revision_source_run_id, child.id)
            self.assertEqual(pipeline.result_revision_requests(grandchild.id)["origin"].id, child.id)
            self.assertEqual([item.id for item in pipeline.result_revision_requests(child.id)["children"]], [grandchild.id])

    def test_result_revision_retries_after_receipt_write_failure_without_duplicate_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline = Pipeline(Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=()))
            source = RunState(
                id="retry-source", spec_path="", spec_digest="digest", repo_path=str(repo), main_branch="main",
                stage=Stage.PUSHED, tasks=[WorkTask("finished", "완료 Task", ["general"], status=TaskStatus.COMPLETED)],
            )
            pipeline.store.save(source)
            request_id = str(uuid.uuid4())
            with patch.object(pipeline.store, "save_revision_requests", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    pipeline.create_result_revision_request(
                        source.id, request_id=request_id, text="확인 문구 수정", task_ids=["finished"], paths=[]
                    )
            self.assertEqual(len(pipeline.store.list_runs()), 2)
            retry = pipeline.create_result_revision_request(
                source.id, request_id=request_id, text="확인 문구 수정", task_ids=["finished"], paths=[]
            )
            self.assertEqual(len(pipeline.store.list_runs()), 2)
            self.assertEqual(pipeline.store.load(str(retry["target_run_id"])).revision_request_id, request_id)

    def test_final_result_records_only_committed_files_and_survives_archive_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline = Pipeline(Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=()))
            baseline = pipeline.git.head(repo)
            (repo / "final.txt").write_text("done\n", encoding="utf-8")
            git(repo, "add", "final.txt")
            git(repo, "commit", "-m", "final result")
            committed = pipeline.git.head(repo)
            task = WorkTask(
                "finished", "완료 Task", ["general"], status=TaskStatus.COMPLETED,
                started_commit=baseline, completed_commit=committed,
                action_results=[
                    TaskActionResult("execute", status="succeeded", worker_response="실제 작업 설명\n두 번째 줄", changed_paths=["transient.txt"]),
                    TaskActionResult("verify", status="succeeded", passed_commands=[["python", "-m", "pytest"]]),
                ],
            )
            pipeline._record_task_result(task)
            pipeline._record_task_result(task)
            state = RunState(
                id="final-record", spec_path="", spec_digest="digest", repo_path=str(repo), main_branch="main",
                stage=Stage.VERIFIED, tasks=[task], verified_main_head=baseline,
                verified_integration_head=committed,
                verification_attempts=[VerificationAttempt(id="verify-one", status="succeeded")],
            )
            pipeline._record_group_result(state)
            pipeline.store.save(state)
            restored = pipeline.store.load(state.id)
            self.assertEqual(len(restored.tasks[0].result_history), 1)
            self.assertEqual([(item.change, item.path) for item in restored.tasks[0].result_history[0].files], [("A", "final.txt")])
            self.assertNotIn("transient.txt", [item.path for item in restored.tasks[0].result_history[0].files])
            self.assertEqual(restored.tasks[0].result_history[0].self_report, "실제 작업 설명\n두 번째 줄")
            self.assertEqual(restored.tasks[0].result_history[0].passed_commands, [["python", "-m", "pytest"]])
            self.assertEqual(restored.group_result_history[0].files_state, "confirmed")
            summary = pipeline._archive_summary(restored, "2026-09-29T02:00:00+00:00", [])
            self.assertIn("A final.txt", summary)
            self.assertIn("AI 자체 보고: 실제 작업 설명 / 두 번째 줄", summary)
            self.assertNotIn("transient.txt", summary)

    def test_missing_result_commit_is_unknown_not_file_change_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline = Pipeline(Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=()))
            task = WorkTask(
                "finished", "완료", ["general"], status=TaskStatus.COMPLETED,
                action_results=[TaskActionResult("verify", status="succeeded", passed_commands=[])],
            )
            pipeline._record_task_result(task)
            self.assertEqual(task.result_history[0].files_state, "unavailable")
            self.assertIn("commit", task.result_history[0].error)
            self.assertEqual(task.result_history[0].verification_status, "unverified")

    def test_group_result_is_saved_only_after_verification_step_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline = Pipeline(Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=()))
            baseline = pipeline.git.head(repo)
            (repo / "final.txt").write_text("done\n", encoding="utf-8")
            git(repo, "add", "final.txt")
            git(repo, "commit", "-m", "integrated result")
            committed = pipeline.git.head(repo)
            failed = RunState("failed-finalization", "", "digest", str(repo), "main", Stage.READY_TO_MERGE)
            with self.assertRaisesRegex(PipelineError, "finalization failed"):
                with pipeline._step(failed, RunStep.VERIFY):
                    failed.verified_main_head = baseline
                    failed.verified_integration_head = committed
                    raise PipelineError("finalization failed")
            self.assertEqual(failed.verification_attempts[-1].status, "failed")
            self.assertEqual(failed.group_result_history, [])
            failed.group_result_history.append(GroupResultRecord(
                failed.verification_attempts[-1].id, baseline, committed, "2026-09-29T00:00:00+00:00",
                files_state="confirmed", files=[ResultFileChange("final.txt", "A")],
            ))
            self.assertIn("통합 검증 실패 · 최종 변경 파일 확인 불가", pipeline._archive_summary(failed, "2026-09-29T01:00:00+00:00", []))

            succeeded = RunState("successful-finalization", "", "digest", str(repo), "main", Stage.READY_TO_MERGE)
            with pipeline._step(succeeded, RunStep.VERIFY):
                succeeded.verified_main_head = baseline
                succeeded.verified_integration_head = committed
                succeeded.transition(Stage.VERIFIED, "verification passed")
            self.assertEqual(succeeded.verification_attempts[-1].status, "succeeded")
            self.assertEqual(len(succeeded.group_result_history), 1)
            self.assertEqual(succeeded.group_result_history[0].verification_attempt_id, succeeded.verification_attempts[-1].id)
            self.assertEqual([(item.change, item.path) for item in succeeded.group_result_history[0].files], [("A", "final.txt")])
            succeeded.group_result_history.clear()
            self.assertIn("통합 검증 완료 · 최종 변경 파일 확인 불가", pipeline._archive_summary(
                succeeded, "2026-09-29T02:00:00+00:00", []
            ))

    def test_commit_queue_order_respects_dependencies_before_risk(self) -> None:
        state = RunState(
            id="queue-order",
            spec_path="plan.md",
            spec_digest="digest",
            repo_path="repo",
            main_branch="main",
            stage=Stage.PLANNED,
            tasks=[
                WorkTask("base", "base", ["general"], risk_level=RiskLevel.LOW),
                WorkTask("dependent", "dependent", ["general"], dependencies=["base"], risk_level=RiskLevel.HIGH),
                WorkTask("independent", "independent", ["general"], risk_level=RiskLevel.MEDIUM),
            ],
        )

        self.assertEqual(
            [task.id for task in Pipeline._commit_queue_tasks(state)],
            ["independent", "base", "dependent"],
        )

    def test_verification_failure_records_command_owner_as_candidate_not_direct_cause(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = [sys.executable, "-c", "raise SystemExit(2)"]
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=root),
                    execution=ExecutionConfig(),
                    agents=(),
                )
            )
            state = RunState(
                id="command-owner",
                spec_path="plan.md",
                spec_digest="digest",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.READY_TO_MERGE,
                tasks=[
                    WorkTask("owner", "owner", ["general"], verify_commands=[command], status=TaskStatus.COMPLETED),
                    WorkTask("other", "other", ["general"], status=TaskStatus.COMPLETED),
                ],
                verification_attempts=[VerificationAttempt()],
            )
            pipeline.store.save(state)

            pipeline._record_verification_failure(
                state,
                tuple(command),
                "verification_command",
                command_failed=True,
            )

            attempt = pipeline.store.load(state.id).verification_attempts[-1]
            self.assertEqual(attempt.candidate_task_ids, ["owner"])
            self.assertEqual(attempt.failed_task_id, "")
            self.assertIn("단일 원인으로 확정하지 않았습니다", attempt.attribution_reason)

    def test_planning_reports_git_readiness_before_git_command_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            spec = root / "plan.md"
            spec.write_text("## 작업\n", encoding="utf-8")
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=repo),
                    execution=ExecutionConfig(),
                    agents=(),
                )
            )

            with self.assertRaisesRegex(PipelineError, r"Git 준비가 필요합니다 \(not_initialized\)"):
                pipeline.prepare_planning(spec)

    def test_run_summary_attention_classifies_resume_integration_and_completion(self) -> None:
        resumable = RunState("resume", "plan.md", "digest", "repo", "main", Stage.EXECUTING)
        resume_control = RunExecutionControl(
            situation=RunExecutionSituation.RESUMABLE,
            action=RunExecutionAction.RESUME,
            reason="resume",
            lock_state=RunLockState.UNLOCKED,
        )
        self.assertEqual(
            Pipeline._summary_attention_reasons(resumable, resume_control, deployment_configured=False, remote_configured=True),
            ("resume",),
        )

        integration = replace(resumable, stage=Stage.VERIFIED)
        complete_control = replace(
            resume_control,
            situation=RunExecutionSituation.TASKS_COMPLETE,
            action=RunExecutionAction.NONE,
        )
        self.assertEqual(
            Pipeline._summary_attention_reasons(integration, complete_control, deployment_configured=False, remote_configured=True),
            ("integration",),
        )

        pushed = replace(resumable, stage=Stage.PUSHED)
        self.assertEqual(
            Pipeline._summary_attention_reasons(pushed, complete_control, deployment_configured=True, remote_configured=True),
            ("deployment",),
        )
        self.assertEqual(
            Pipeline._summary_attention_reasons(pushed, complete_control, deployment_configured=False, remote_configured=True),
            (),
        )

    def test_active_group_summary_uses_live_run_and_planning_locks_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state.stage = Stage.EXECUTING
            pipeline.store.save(state)
            self.assertEqual(pipeline.active_group_summaries(), [])

            with pipeline.store.planning_chat_lock(state.id):
                planning = pipeline.active_group_summaries()
                self.assertEqual([(item["run_id"], item["status"], item["activity_kinds"]) for item in planning], [
                    (state.id, "active", ["planning"]),
                ])
                with pipeline.store.lock(state.id, "execute"):
                    combined = pipeline.active_group_summaries()
                    self.assertEqual(combined[0]["activity_kinds"], ["task", "planning"])

            with pipeline.store.lock(state.id, "verify"):
                self.assertEqual(pipeline.active_group_summaries()[0]["activity_kinds"], ["verification"])
            self.assertEqual(pipeline.active_group_summaries(), [])

            with patch.object(pipeline.store, "inspect_lock", return_value=RunLockStatus(
                run_id=state.id, state=RunLockState.STALE, operation="execute",
            )):
                uncertain = pipeline.active_group_summaries()
            self.assertEqual(uncertain[0]["status"], "check_required")
            self.assertEqual(uncertain[0]["activity_kinds"], [])

    def test_completed_run_archive_preserves_records_and_removes_clean_owned_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline, state = self._scope_test_run(root)
            state = pipeline.execute(state.id, manual=True)
            worktree = Path(state.execution_worktree)
            completed_head = pipeline.git.head(worktree)
            state.stage = Stage.PUSHED
            state.active_step = None
            state.tasks[0].status = TaskStatus.COMPLETED
            state.tasks[0].active_action = None
            state.tasks[0].completed_commit = completed_head
            pipeline.store.save(state)

            plan = pipeline.archive_plan(state.id)
            archived = pipeline.archive_run(
                state.id,
                expected_revision=str(plan["expected_revision"]),
                fingerprint=str(plan["fingerprint"]),
                request_id=str(uuid.uuid4()),
                approved=True,
            )

            self.assertIsNotNone(archived.archive)
            assert archived.archive is not None
            self.assertEqual(archived.archive.cleanup_status.value, "completed")
            self.assertFalse(worktree.exists())
            self.assertTrue(Path(archived.archive.snapshot_path).is_file())
            self.assertTrue(Path(archived.archive.manifest_path).is_file())
            self.assertTrue(Path(archived.archive.summary_path).is_file())
            self.assertTrue(pipeline.git.branch_exists(state.execution_branch))
            protected = f"refs/ai-orchestrator/archive/{state.id}/task-1"
            self.assertEqual(pipeline.git.branch_head(protected), completed_head)
            self.assertEqual([item.id for item in pipeline.list_summaries("active")], [])
            self.assertEqual([item.id for item in pipeline.list_summaries("archived")], [state.id])

    def test_archive_plan_allows_stale_conflict_only_after_group_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline = Pipeline(Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=()))
            head = pipeline.git.head(repo)
            state = RunState(
                id="stale-conflict-archive",
                spec_path="plan.md",
                spec_digest="digest",
                repo_path=str(repo),
                main_branch="main",
                stage=Stage.PUSHED,
                integration_conflict=IntegrationConflict(
                    id="conflict-1",
                    verification_attempt_id="verify-1",
                    main_head=head,
                    work_head=head,
                    merge_base_heads=[],
                    files=[],
                    fingerprint="fingerprint",
                    resolution_status=ConflictResolutionStatus.STALE,
                ),
            )
            pipeline.store.save(state)

            self.assertTrue(pipeline.archive_plan(state.id)["can_archive"])

            assert state.integration_conflict is not None
            state.integration_conflict.resolution_status = ConflictResolutionStatus.UNRESOLVED
            pipeline.store.save(state)
            self.assertIn("완료되지 않은 Main 통합 충돌 복구가 있습니다.", pipeline.archive_plan(state.id)["block_reasons"])

            state.integration_conflict.resolution_status = ConflictResolutionStatus.STALE
            state.stage = Stage.VERIFIED
            pipeline.store.save(state)
            self.assertFalse(pipeline.archive_plan(state.id)["can_archive"])

    def test_archive_snapshot_failure_does_not_start_workspace_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=repo),
                    execution=ExecutionConfig(),
                    agents=(),
                )
            )
            state = RunState(
                "archive-failure",
                "plan.md",
                "digest",
                str(repo),
                "main",
                summary="archive failure",
                stage=Stage.PUSHED,
            )
            pipeline.store.save(state)
            plan = pipeline.archive_plan(state.id)

            with (
                patch.object(pipeline.store, "save_archive_snapshot", side_effect=OSError("disk full")),
                patch.object(pipeline.git, "remove_worktree") as remove_worktree,
                self.assertRaisesRegex(OSError, "disk full"),
            ):
                pipeline.archive_run(
                    state.id,
                    expected_revision=str(plan["expected_revision"]),
                    fingerprint=str(plan["fingerprint"]),
                    request_id=str(uuid.uuid4()),
                    approved=True,
                )

            self.assertIsNone(pipeline.status(state.id).archive)
            remove_worktree.assert_not_called()

    def test_archive_cleanup_can_retry_after_dirty_worktree_is_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline, state = self._scope_test_run(root)
            state = pipeline.execute(state.id, manual=True)
            worktree = Path(state.execution_worktree)
            completed_head = pipeline.git.head(worktree)
            state.stage = Stage.PUSHED
            state.active_step = None
            state.tasks[0].status = TaskStatus.COMPLETED
            state.tasks[0].active_action = None
            state.tasks[0].completed_commit = completed_head
            pipeline.store.save(state)
            dirty_file = worktree / "unfinished.txt"
            dirty_file.write_text("unfinished\n", encoding="utf-8")
            plan = pipeline.archive_plan(state.id)

            archived = pipeline.archive_run(
                state.id,
                expected_revision=str(plan["expected_revision"]),
                fingerprint=str(plan["fingerprint"]),
                request_id=str(uuid.uuid4()),
                approved=True,
            )

            assert archived.archive is not None
            self.assertEqual(archived.archive.cleanup_status.value, "blocked")
            self.assertTrue(worktree.is_dir())
            dirty_file.unlink()
            retried = pipeline.retry_archive_cleanup(
                state.id,
                fingerprint=archived.archive.fingerprint,
                request_id=str(uuid.uuid4()),
                approved=True,
            )
            assert retried.archive is not None
            self.assertEqual(retried.archive.cleanup_status.value, "completed")
            self.assertFalse(worktree.exists())

    def test_archive_cleanup_preserves_ignored_files_on_repeated_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state = pipeline.execute(state.id, manual=True)
            worktree = Path(state.execution_worktree)
            state.stage = Stage.PUSHED
            state.active_step = None
            state.tasks[0].status = TaskStatus.COMPLETED
            state.tasks[0].active_action = None
            state.tasks[0].completed_commit = pipeline.git.head(worktree)
            pipeline.store.save(state)
            with (pipeline.repo / ".git" / "info" / "exclude").open("a", encoding="utf-8") as exclude:
                exclude.write("\n/retained-cache/\n")
            retained = worktree / "retained-cache" / "data.txt"
            retained.parent.mkdir()
            retained.write_text("preserve ignored data", encoding="utf-8")
            plan = pipeline.archive_plan(state.id)
            with patch.object(pipeline.git, "remove_worktree") as remove:
                archived = pipeline.archive_run(
                    state.id, expected_revision=str(plan["expected_revision"]), fingerprint=str(plan["fingerprint"]),
                    request_id=str(uuid.uuid4()), approved=True,
                )
                assert archived.archive is not None
                snapshot = Path(archived.archive.snapshot_path).read_bytes()
                retried = pipeline.retry_archive_cleanup(
                    state.id, fingerprint=archived.archive.fingerprint, request_id=str(uuid.uuid4()), approved=True,
                )
                remove.assert_not_called()
            assert retried.archive is not None
            self.assertEqual(retried.archive.cleanup_status.value, "blocked")
            self.assertIn("ignored 파일", retried.archive.cleanup_targets[0].error)
            self.assertEqual(retained.read_text(encoding="utf-8"), "preserve ignored data")
            self.assertEqual(Path(retried.archive.snapshot_path).read_bytes(), snapshot)

    def test_archive_partial_cleanup_records_blocked_candidate_without_losing_completed_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline, state = self._scope_test_run(root)
            state = pipeline.execute(state.id, manual=True)
            worktree = Path(state.execution_worktree)
            completed_head = pipeline.git.head(worktree)
            candidate_path = pipeline._run_worktree_root(state) / ".conflict-resolution" / str(uuid.uuid4())
            candidate_path.mkdir(parents=True)
            (candidate_path / "unowned.txt").write_text("preserve\n", encoding="utf-8")
            state.stage = Stage.PUSHED
            state.active_step = None
            state.tasks[0].status = TaskStatus.COMPLETED
            state.tasks[0].active_action = None
            state.tasks[0].completed_commit = completed_head
            state.integration_conflict = IntegrationConflict(
                id="conflict-1",
                verification_attempt_id="verify-1",
                main_head=pipeline.git.head(pipeline.repo),
                work_head=completed_head,
                merge_base_heads=[],
                files=[],
                fingerprint="fingerprint",
                resolution_status=ConflictResolutionStatus.STALE,
                candidate=ConflictResolutionCandidate(
                    id="candidate-1",
                    request_id=str(uuid.uuid4()),
                    status="failed",
                    worktree=str(candidate_path),
                ),
            )
            pipeline.store.save(state)
            plan = pipeline.archive_plan(state.id)
            self.assertTrue(plan["can_archive"])

            archived = pipeline.archive_run(
                state.id,
                expected_revision=str(plan["expected_revision"]),
                fingerprint=str(plan["fingerprint"]),
                request_id=str(uuid.uuid4()),
                approved=True,
            )

            assert archived.archive is not None
            self.assertEqual(archived.archive.cleanup_status.value, "partial")
            self.assertEqual([target.status for target in archived.archive.cleanup_targets], ["removed", "blocked"])
            self.assertFalse(worktree.exists())
            self.assertTrue((candidate_path / "unowned.txt").is_file())

    def test_archive_cleanup_retries_residue_after_git_registration_was_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline, state = self._scope_test_run(root)
            state = pipeline.execute(state.id, manual=True)
            worktree = Path(state.execution_worktree)
            completed_head = pipeline.git.head(worktree)
            state.stage = Stage.PUSHED
            state.active_step = None
            state.tasks[0].status = TaskStatus.COMPLETED
            state.tasks[0].active_action = None
            state.tasks[0].completed_commit = completed_head
            pipeline.store.save(state)
            plan = pipeline.archive_plan(state.id)
            remove_worktree = pipeline.git.remove_worktree

            def leave_residue(path: Path, **kwargs: object) -> None:
                remove_worktree(path, **kwargs)
                worktree.mkdir(parents=True)
                residue = worktree / "src" / "locked.txt"
                residue.parent.mkdir()
                residue.write_text("left after Git unregister\n", encoding="utf-8")
                raise GitError(f"could not remove worktree residue at {worktree.resolve()}: sharing violation")

            with patch.object(pipeline.git, "remove_worktree", side_effect=leave_residue):
                archived = pipeline.archive_run(
                    state.id,
                    expected_revision=str(plan["expected_revision"]),
                    fingerprint=str(plan["fingerprint"]),
                    request_id=str(uuid.uuid4()),
                    approved=True,
                )

            assert archived.archive is not None
            self.assertEqual(archived.archive.cleanup_status.value, "blocked")
            self.assertEqual(archived.archive.cleanup_targets[0].status, "failed")
            self.assertTrue(worktree.is_dir())
            retried = pipeline.retry_archive_cleanup(
                state.id,
                fingerprint=archived.archive.fingerprint,
                request_id=str(uuid.uuid4()),
                approved=True,
            )

            assert retried.archive is not None
            self.assertEqual(retried.archive.cleanup_status.value, "completed")
            self.assertEqual(retried.archive.cleanup_targets[0].status, "removed")
            self.assertFalse(worktree.exists())

    def test_archive_cleanup_accepts_prior_workspace_removal_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline, state = self._scope_test_run(root)
            state = pipeline.execute(state.id, manual=True)
            worktree = Path(state.execution_worktree)
            completed_head = pipeline.git.head(worktree)
            pipeline.git.remove_worktree(worktree)
            residue = worktree / "src" / "locked.txt"
            residue.parent.mkdir(parents=True)
            residue.write_text("left after Git unregister\n", encoding="utf-8")
            state.stage = Stage.PUSHED
            state.active_step = None
            state.tasks[0].status = TaskStatus.COMPLETED
            state.tasks[0].active_action = None
            state.tasks[0].completed_commit = completed_head
            state.add_event(
                "workspace",
                "shared run workspace cleanup deferred: command failed (255): "
                f"git -c core.longpaths=true worktree remove {worktree.resolve()}\n"
                "error: failed to delete worktree: Permission denied",
            )
            pipeline.store.save(state)
            plan = pipeline.archive_plan(state.id)

            archived = pipeline.archive_run(
                state.id,
                expected_revision=str(plan["expected_revision"]),
                fingerprint=str(plan["fingerprint"]),
                request_id=str(uuid.uuid4()),
                approved=True,
            )

            assert archived.archive is not None
            self.assertEqual(archived.archive.cleanup_status.value, "completed")
            self.assertEqual(archived.archive.cleanup_targets[0].status, "removed")
            self.assertFalse(worktree.exists())

    def test_shared_main_conflict_can_generate_review_and_apply_isolated_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            (repo / "result.txt").write_text("base\n", encoding="utf-8")
            git(repo, "add", "result.txt")
            git(repo, "commit", "-m", "base result")
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] 결과 수정\n", encoding="utf-8")
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=repo),
                    execution=ExecutionConfig(
                        auto_commit=True,
                        verify_commands=((sys.executable, "-c", "from pathlib import Path; value=Path('result.txt').read_text(); assert 'work' in value and 'main' in value"),),
                    ),
                    agents=(AgentConfig("worker", ("general",), (sys.executable, "-c", "pass"), 1, provider_id="local"),),
                )
            )
            state = pipeline.confirm_plan(pipeline.start(spec).id)
            state = pipeline.execute(state.id, manual=True)
            worktree = Path(state.tasks[0].worktree)
            (worktree / "result.txt").write_text("work\n", encoding="utf-8")
            state = pipeline.complete_task(state.id, state.tasks[0].id)
            work_head = pipeline.git.head(worktree)
            (repo / "result.txt").write_text("main\n", encoding="utf-8")
            git(repo, "add", "result.txt")
            git(repo, "commit", "-m", "latest main")
            main_head = pipeline.git.head(repo)

            with self.assertRaisesRegex(PipelineError, "Operations"):
                pipeline.verify(state.id)

            failed = pipeline.status(state.id)
            conflict = failed.integration_conflict
            self.assertIsNotNone(conflict)
            assert conflict is not None
            self.assertEqual(conflict.work_head, work_head)
            self.assertEqual(conflict.main_head, main_head)
            self.assertEqual(conflict.abort_status, "verified")
            self.assertEqual([item.path for item in conflict.files], ["result.txt"])
            self.assertEqual(len(failed.recovery_tasks), 1)
            self.assertEqual(failed.recovery_tasks[0].conflict.id, conflict.id)
            self.assertEqual([task.id for task in failed.tasks], [state.tasks[0].id])
            self.assertEqual(pipeline.git.head(worktree), work_head)
            pipeline.git.ensure_worktree_clean(worktree)

            def resolve_candidate(**kwargs: object) -> str:
                callback = kwargs["progress_callback"]
                assert callable(callback)
                callback(CodexSdkProgress(
                    "reading_documents", attempt_id=str(kwargs["attempt_id"]), invocation_id=str(kwargs["invocation_id"]),
                    received_at="2026-09-25T00:00:00+00:00", event_seq=1,
                ))
                running = pipeline.integration_conflict(failed.id, conflict_id=conflict.id)
                self.assertEqual(running["attempts"][-1]["status"], "running")
                self.assertEqual(running["attempts"][-1]["progress_observation"]["phase"], "reading_documents")
                callback(CodexSdkProgress(
                    "reading_documents", attempt_id=str(kwargs["attempt_id"]), invocation_id=str(kwargs["invocation_id"]),
                    received_at="2026-09-25T00:00:05+00:00", event_seq=2, activity_changed=False, evidence_kind="provider_event",
                ))
                candidate_worktree = Path(str(kwargs["cwd"]))
                (candidate_worktree / "result.txt").write_text("work\nmain\n", encoding="utf-8")
                return "작업 결과와 Main 변경을 함께 보존했습니다."

            def change_outside_conflict(**kwargs: object) -> str:
                candidate_worktree = Path(str(kwargs["cwd"]))
                (candidate_worktree / "result.txt").write_text("work\nmain\n", encoding="utf-8")
                (candidate_worktree / "outside.txt").write_text("not allowed\n", encoding="utf-8")
                return "허용 범위 밖 파일도 변경했습니다."

            with (
                patch.object(pipeline, "_invoke_provider_command", side_effect=change_outside_conflict),
                self.assertRaisesRegex(PipelineError, "허용된 충돌 파일 밖"),
            ):
                pipeline.prepare_conflict_resolution(
                    failed.id,
                    conflict_id=conflict.id,
                    fingerprint=conflict.fingerprint,
                    request_id="e99be4e1-a900-45cb-84fc-c9a0f03f0455",
                    agent_id="worker",
                )

            first_request = "e99be4e1-a900-45cb-84fc-c9a0f03f0455"
            residue = (pipeline._run_worktree_root(failed) / ".conflict-resolution" / first_request).resolve()
            residue.mkdir(parents=True, exist_ok=True)
            failed_state = pipeline.store.load(failed.id)
            assert failed_state.integration_conflict is not None and failed_state.integration_conflict.candidate is not None
            failed_state.integration_conflict.candidate.worktree = str(residue)
            pipeline.store.save(failed_state)

            generation_request = "914772ee-2868-4b09-9241-ea0eb733effc"
            pipeline.agents["codex_worker"] = AgentConfig("codex_worker", ("general",), (), 1, provider_id="codex")
            pipeline._codex_sdk = connected_codex_sdk()
            with patch.object(pipeline, "_invoke_provider_command", side_effect=resolve_candidate) as invoke:
                prepared = pipeline.prepare_conflict_resolution(
                    failed.id,
                    conflict_id=conflict.id,
                    fingerprint=conflict.fingerprint,
                    request_id=generation_request,
                    agent_id="codex_worker",
                )
                repeated = pipeline.prepare_conflict_resolution(
                    failed.id,
                    conflict_id=conflict.id,
                    fingerprint=conflict.fingerprint,
                    request_id=generation_request,
                    agent_id="codex_worker",
                )
            self.assertEqual(invoke.call_count, 1)
            self.assertFalse(residue.exists())
            candidate = prepared["conflict"]["candidate"]
            self.assertEqual(candidate["status"], "candidate_ready")
            self.assertEqual(repeated["conflict"]["candidate"]["commit"], candidate["commit"])
            self.assertEqual([attempt["status"] for attempt in prepared["attempts"]], ["failed", "succeeded"])
            self.assertIsNone(prepared["attempts"][0]["progress_observation"])
            observed = prepared["attempts"][1]["progress_observation"]
            self.assertEqual(observed["attempt_id"], generation_request)
            self.assertEqual(observed["phase"], "reading_documents")
            self.assertEqual(observed["last_event_received_at"], "2026-09-25T00:00:05+00:00")
            self.assertEqual(observed["last_activity_changed_at"], "2026-09-25T00:00:00+00:00")
            self.assertEqual(repeated["attempts"][1]["progress_observation"], observed)
            self.assertEqual(prepared["recovery_task"]["operation_request_ids"], [
                "e99be4e1-a900-45cb-84fc-c9a0f03f0455",
                generation_request,
            ])
            comparison = pipeline.integration_conflict(failed.id, conflict_id=conflict.id, file_path="result.txt")
            self.assertEqual(comparison["selected_file"]["candidate"], "work\nmain\n")
            self.assertEqual(comparison["selected_file"]["candidate_state"], "ready")

            with self.assertRaises(ApprovalRequired):
                pipeline.apply_conflict_resolution(
                    failed.id,
                    conflict_id=conflict.id,
                    candidate_id=candidate["id"],
                    candidate_revision=candidate["revision"],
                    fingerprint=conflict.fingerprint,
                    request_id="879be29a-1be4-4f5f-8adb-8ff10617a314",
                    approved=False,
                )

            verified = pipeline.apply_conflict_resolution(
                failed.id,
                conflict_id=conflict.id,
                candidate_id=candidate["id"],
                candidate_revision=candidate["revision"],
                fingerprint=conflict.fingerprint,
                request_id="4f54e564-d8e7-4931-8da2-b9374999792d",
                approved=True,
            )

            self.assertEqual(verified.stage, Stage.VERIFIED)
            self.assertEqual(verified.integration_conflict.resolution_status, "applied")
            self.assertEqual(verified.recovery_tasks[0].operation_request_ids[-1], "4f54e564-d8e7-4931-8da2-b9374999792d")
            self.assertEqual(verified.recovery_tasks[0].verification_attempt_ids[-1], verified.verification_attempts[-1].id)
            applied_detail = pipeline.integration_conflict(verified.id, recovery_task_id=verified.recovery_tasks[0].id)
            self.assertEqual(applied_detail["attempts"][-1]["status"], "succeeded")
            self.assertEqual((worktree / "result.txt").read_text(encoding="utf-8"), "work\nmain\n")
            self.assertEqual(pipeline.git.head(repo), main_head)
            linked_attempts = list(verified.recovery_tasks[0].verification_attempt_ids)

            reverified = pipeline.verify(verified.id)

            self.assertEqual(len(reverified.recovery_tasks[0].verification_attempt_ids), len(linked_attempts) + 1)
            self.assertEqual(reverified.recovery_tasks[0].verification_attempt_ids[-1], reverified.verification_attempts[-1].id)
            pipeline.delete_run(reverified.id, approved=True)

    def test_conflict_candidate_retry_preserves_nonempty_unregistered_residue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline = Pipeline(Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=()))
            state = RunState(id="nonempty-candidate", spec_path="", spec_digest="digest", repo_path=str(repo), main_branch="main", stage=Stage.FAILED)
            request_id = "4a5be6f5-777d-422d-b310-e5ca09b3f423"
            candidate_path = pipeline._run_worktree_root(state) / ".conflict-resolution" / request_id
            candidate_path.mkdir(parents=True)
            (candidate_path / "keep.txt").write_text("user data\n", encoding="utf-8")
            candidate = ConflictResolutionCandidate(id=f"candidate-{request_id}", request_id=request_id, worktree=str(candidate_path))

            with self.assertRaisesRegex(PipelineError, "비어 있지 않거나 사용 중"):
                pipeline._discard_conflict_candidate_worktree(state, candidate)
            self.assertEqual((candidate_path / "keep.txt").read_text(encoding="utf-8"), "user data\n")

    def test_execution_control_uses_lock_and_state_as_one_backend_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))

            _, ready = pipeline.status_with_execution_control(state.id)
            self.assertEqual(ready.situation, RunExecutionSituation.READY)
            self.assertEqual(ready.action, RunExecutionAction.EXECUTE)

            state.stage = Stage.EXECUTING
            state.begin_step(RunStep.AGENT_EXECUTION)
            state.tasks[0].status = TaskStatus.RUNNING
            state.tasks[0].active_action = TaskAction.EXECUTE
            pipeline.store.save(state)
            active_lock = RunLockStatus(
                run_id=state.id,
                state=RunLockState.ACTIVE,
                operation="execute",
                pid=123,
                host="test",
            )
            with patch.object(pipeline.store, "inspect_lock", return_value=active_lock):
                _, running = pipeline.status_with_execution_control(state.id)
            self.assertEqual(running.situation, RunExecutionSituation.RUNNING)
            self.assertEqual(running.action, RunExecutionAction.NONE)
            self.assertEqual(running.active_task_id, state.tasks[0].id)

            state.tasks[0].status = TaskStatus.PENDING
            state.tasks[0].active_action = None
            pipeline.store.save(state)
            with patch.object(pipeline.store, "inspect_lock", return_value=active_lock):
                _, preparing = pipeline.status_with_execution_control(state.id)
            self.assertEqual(preparing.situation, RunExecutionSituation.PREPARING)
            self.assertEqual(preparing.action, RunExecutionAction.NONE)

            state.tasks[0].status = TaskStatus.RUNNING
            state.tasks[0].active_action = TaskAction.EXECUTE
            pipeline.store.save(state)
            _, resumable = pipeline.status_with_execution_control(state.id)
            self.assertEqual(resumable.situation, RunExecutionSituation.RESUMABLE)
            self.assertEqual(resumable.action, RunExecutionAction.RESUME)
            self.assertEqual(resumable.active_task_id, state.tasks[0].id)

    def test_execution_control_blocks_uncertain_and_non_resumable_states(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            unlocked = RunLockStatus(run_id=state.id, state=RunLockState.UNLOCKED)
            active = RunLockStatus(run_id=state.id, state=RunLockState.ACTIVE, operation="execute", pid=123, host="test")
            with patch.object(pipeline.store, "inspect_lock", side_effect=[unlocked, active]):
                _, changed = pipeline.status_with_execution_control(state.id)
            self.assertEqual(changed.situation, RunExecutionSituation.STATUS_UNKNOWN)
            self.assertEqual(changed.action, RunExecutionAction.NONE)

            stale = RunLockStatus(run_id=state.id, state=RunLockState.STALE, operation="execute", pid=123, host="test")
            with patch.object(pipeline.store, "inspect_lock", return_value=stale):
                _, interrupted = pipeline.status_with_execution_control(state.id)
            self.assertEqual(interrupted.situation, RunExecutionSituation.ATTENTION_REQUIRED)
            self.assertEqual(interrupted.action, RunExecutionAction.NONE)

            state.fail_step(RunStep.PLANNING, "planner failed")
            pipeline.store.save(state)
            _, planning_failure = pipeline.status_with_execution_control(state.id)
            self.assertEqual(planning_failure.situation, RunExecutionSituation.ATTENTION_REQUIRED)
            self.assertEqual(planning_failure.action, RunExecutionAction.NONE)

            state.resume_to(Stage.READY_TO_MERGE, "tasks completed")
            pipeline.store.save(state)
            _, complete = pipeline.status_with_execution_control(state.id)
            self.assertEqual(complete.situation, RunExecutionSituation.TASKS_COMPLETE)
            self.assertEqual(complete.action, RunExecutionAction.NONE)

    def test_recovery_preview_deadline_releases_lock_without_applying_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state = pipeline.execute(state.id, manual=True)
            state.tasks[0].status = TaskStatus.FAILED
            state.fail_step(RunStep.AGENT_EXECUTION, "produced no commit")
            pipeline.store.save(state)
            original = pipeline.store.load(state.id).to_dict()
            with (
                patch("ai_orchestrator.pipeline.time") as clock,
                patch.object(pipeline.git, "ensure_worktree_clean", wraps=pipeline.git.ensure_worktree_clean) as clean,
                patch.object(pipeline.git, "head") as head,
            ):
                clock.monotonic.side_effect = [0, 1, 2, 46]
                request_id = "89223d34-cdfa-44d0-b83c-84826829c7e1"
                with self.assertRaisesRegex(PipelineError, "45초"):
                    pipeline.recovery_plan(state.id, request_id=request_id)
                self.assertTrue(clean.call_args.kwargs["non_interactive"])
                self.assertLessEqual(clean.call_args.kwargs["timeout_seconds"], LOCAL_GIT_TIMEOUT_SECONDS)
                head.assert_not_called()
                failed_operation = pipeline.recovery_operation(state.id, request_id)
                self.assertEqual(failed_operation["status"], "failed")
                self.assertEqual(failed_operation["phase"], "collecting_sources")
            self.assertEqual(pipeline.store.load(state.id).to_dict(), original)
            with pipeline.store.lock(state.id, "test-released"):
                pass
            with patch.object(pipeline.git, "head", side_effect=GitError("head timed out")) as head:
                with self.assertRaisesRegex(GitError, "head timed out"):
                    pipeline.recovery_plan(state.id)
                self.assertTrue(head.call_args.kwargs["non_interactive"])
                self.assertLessEqual(head.call_args.kwargs["timeout_seconds"], LOCAL_GIT_TIMEOUT_SECONDS)
            self.assertEqual(pipeline.store.load(state.id).to_dict(), original)

    def test_reviewed_recovery_preserves_group_and_rejects_stale_or_unapproved_plan(self) -> None:
        from copy import deepcopy

        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state = pipeline.execute(state.id, manual=True)
            state.planning_agent_id = "worker"
            state.tasks[0].status = TaskStatus.FAILED
            state.tasks[0].error = "produced no commit"
            state.fail_step(RunStep.AGENT_EXECUTION, "produced no commit")
            pipeline.store.save(state)
            source = deepcopy(state)
            source.id = "source-group"
            source.tasks[0].status = TaskStatus.COMPLETED
            repo = pipeline.repo
            git(repo, "checkout", "-b", "source-result")
            (repo / "prerequisite.txt").write_text("implemented", encoding="utf-8")
            pipeline.git.commit_all(repo, "prerequisite")
            source.tasks[0].completed_commit = pipeline.git.head(repo)
            git(repo, "checkout", "main")
            pipeline.store.save(source)
            plan = pipeline.recovery_plan(state.id)
            self.assertEqual([item["run_id"] for item in plan["sources"]], [source.id])
            self.assertEqual(pipeline.git.head(Path(state.tasks[0].worktree)), plan["baseline"])
            with self.assertRaises(PipelineError):
                pipeline.apply_recovery(state.id, plan["fingerprint"], [source.id], approved=False)
            with self.assertRaises(PipelineError):
                pipeline.apply_recovery(state.id, "stale", [source.id], approved=True)
            proposals = deepcopy(state.tasks)
            proposals[0].description = "recover missing integration"
            new_task = WorkTask(
                id="recovered-prerequisite",
                title="복구된 선행 Task",
                capabilities=["general"],
                agent_id="worker",
                expected_paths=["recovered.txt"],
            )
            proposals.append(new_task)
            with patch.object(pipeline, "_build_plan", return_value=Plan(summary="recovered", server_work=False, tasks=proposals)):
                updated = pipeline.apply_recovery(state.id, plan["fingerprint"], [source.id], approved=True)
            self.assertEqual(updated.id, state.id)
            self.assertEqual(updated.stage, Stage.FAILED)
            self.assertEqual(updated.tasks[0].error, "produced no commit")
            self.assertEqual(updated.tasks[0].description, "recover missing integration")
            self.assertEqual(updated.tasks[0].started_commit, pipeline.git.head(Path(updated.tasks[0].worktree)))
            self.assertTrue((Path(updated.tasks[0].worktree) / "prerequisite.txt").exists())
            prepared = updated.tasks[-1]
            self.assertEqual(prepared.worktree, updated.execution_worktree)
            self.assertEqual(prepared.branch, updated.execution_branch)
            self.assertTrue(Path(prepared.prompt_path).is_file())
            self.assertEqual(Path(prepared.log_path).parent, pipeline.store.run_dir(state.id) / "logs")
            self.assertEqual(pipeline.recovery_plan(state.id)["sources"], [])
            plan = pipeline.recovery_plan(state.id)
            partial_request_id = "987879ed-9b8b-468e-b0fb-bd77a6479a80"
            with patch.object(pipeline, "_build_plan", side_effect=PlanningError("planner unavailable")):
                with self.assertRaisesRegex(PipelineError, "Task 재계획에 실패"):
                    pipeline.apply_recovery(
                        state.id,
                        plan["fingerprint"],
                        [],
                        approved=True,
                        request_id=partial_request_id,
                    )
            self.assertTrue(pipeline.store.load(state.id).planning_follow_up_requests)
            partial = pipeline.recovery_operation(state.id, partial_request_id)
            self.assertEqual(partial["status"], "partial")
            self.assertEqual(partial["phase"], "replanning")
            integrated = partial["result_commit"]
            retry_proposals = deepcopy(pipeline.store.load(state.id).tasks)
            retry_request_id = "5b42fcb7-41eb-4b6f-bf75-14caab17e30c"
            with patch.object(pipeline, "_build_plan", return_value=Plan(summary="recovered again", server_work=False, tasks=retry_proposals)):
                resumed = pipeline.apply_recovery(
                    state.id,
                    plan["fingerprint"],
                    [],
                    approved=True,
                    request_id=retry_request_id,
                    resume_request_id=partial_request_id,
                )
            retried = pipeline.recovery_operation(state.id, retry_request_id)
            self.assertEqual(retried["status"], "succeeded")
            self.assertEqual(retried["result_commit"], integrated)
            self.assertEqual(resumed.plan_revision, retried["result_revision"])

    def test_capacity_after_recovery_integration_preserves_completed_tasks_and_resumes_only_replanning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state = pipeline.execute(state.id, manual=True)
            state.planning_agent_id = "worker"
            state.tasks[0].status = TaskStatus.FAILED
            state.tasks[0].error = "Selected model is at capacity. Please try a different model."
            completed = deepcopy(state.tasks[0])
            completed.id = "completed-contract"
            completed.status = TaskStatus.COMPLETED
            completed.readiness = TaskReadiness.DONE
            completed.error = ""
            completed.completed_commit = pipeline.git.head(Path(state.tasks[0].worktree))
            completed.attempt_count = 1
            state.tasks.append(completed)
            saved_completed = deepcopy(completed)
            state.fail_step(RunStep.AGENT_EXECUTION, state.tasks[0].error)
            pipeline.store.save(state)
            plan = pipeline.recovery_plan(state.id)
            request_id = str(uuid.uuid4())
            with patch.object(pipeline, "_build_plan", side_effect=PlanningError("선택한 AI 모델이 혼잡합니다. upstream overloaded")):
                with self.assertRaisesRegex(PipelineError, "Task 재계획에 실패"):
                    pipeline.apply_recovery(state.id, plan["fingerprint"], [], approved=True, request_id=request_id)
            partial = pipeline.recovery_operation(state.id, request_id)
            self.assertEqual(partial["status"], "partial")
            self.assertEqual(partial["error_code"], "replanning_failed")
            self.assertTrue(partial["result_commit"])
            self.assertIn("혼잡", partial["error"])
            self.assertEqual(pipeline.store.load(state.id).tasks[1], saved_completed)
            pending = deepcopy(pipeline.store.load(state.id).tasks)
            pending[0].description = "same failed task; keep completion contract"
            resumed_id = str(uuid.uuid4())
            with (
                patch.object(pipeline.git, "recover_commits", side_effect=AssertionError("must not reintegrate")),
                patch.object(pipeline, "_build_plan", return_value=Plan(summary="recovered", server_work=False, tasks=pending)),
                patch.object(pipeline, "_run_task", side_effect=AssertionError("must not execute any task")),
            ):
                resumed = pipeline.apply_recovery(state.id, plan["fingerprint"], [], approved=True,
                                                  request_id=resumed_id, resume_request_id=request_id)
            operation = pipeline.recovery_operation(state.id, resumed_id)
            self.assertEqual(operation["status"], "succeeded")
            self.assertEqual(operation["result_commit"], partial["result_commit"])
            self.assertEqual(operation["resume_request_id"], request_id)
            self.assertEqual(next(task for task in resumed.tasks if task.id == completed.id), saved_completed)
            self.assertEqual(resumed.tasks[0].status, TaskStatus.FAILED)
            self.assertEqual(resumed.tasks[0].attempt_count, state.tasks[0].attempt_count)

    def test_recovery_preview_is_replayable_and_discoverable_by_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state = pipeline.execute(state.id, manual=True)
            state.tasks[0].status = TaskStatus.FAILED
            state.tasks[0].error = "produced no commit"
            state.fail_step(RunStep.AGENT_EXECUTION, "produced no commit")
            pipeline.store.save(state)
            request_id = "43aa358f-e93d-44fe-a98f-e53fcb926992"

            plan = pipeline.recovery_plan(state.id, request_id=request_id)
            replayed = pipeline.recovery_plan(state.id, request_id=request_id)
            operation = pipeline.recovery_operation(state.id, request_id)
            latest = pipeline.latest_recovery_operation(state.id, "recovery_preview")

            self.assertEqual(replayed, plan)
            self.assertEqual(operation["status"], "succeeded")
            self.assertEqual(operation["phase"], "preview_ready")
            self.assertEqual(operation["result"]["fingerprint"], plan["fingerprint"])
            self.assertEqual(latest, operation)

            changed = pipeline.store.load(state.id)
            changed.failure_message = "updated failure evidence"
            changed.add_event("test", "recovery inputs changed")
            pipeline.store.save(changed)
            self.assertIsNone(pipeline.latest_recovery_operation(state.id, "recovery_preview"))
            with self.assertRaisesRegex(PipelineError, "다른 복구 요청이나 입력"):
                pipeline.recovery_plan(state.id, request_id=request_id)

    def test_running_recovery_operation_without_live_lock_is_marked_interrupted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            request_id = "2f4ca21a-7393-48fb-82ee-809dac8bfa21"
            operation = OperationRecord(
                request_id=request_id,
                run_id=state.id,
                action="recovery_preview",
                digest="digest",
                phase="collecting_sources",
            )
            pipeline.store.claim_operation(operation)

            recovered = pipeline.recovery_operation(state.id, request_id)

            self.assertEqual(recovered["status"], "interrupted")
            self.assertEqual(recovered["error_code"], "operation_interrupted")
            self.assertEqual(recovered["lock_state"], "unlocked")

    def test_interrupted_replanning_preserves_integrated_commit_as_partial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            request_id = "ec3ae58b-e70d-4126-98ad-42be72189939"
            operation = OperationRecord(
                request_id=request_id,
                run_id=state.id,
                action="recovery_apply",
                digest="digest",
                phase="replanning",
                result_commit=pipeline.git.head(pipeline.repo),
            )
            operation.result_ref = pipeline.store.save_operation_result(
                state.id,
                request_id,
                {"fingerprint": "reviewed", "source_ids": [], "result_commit": operation.result_commit},
            )
            pipeline.store.claim_operation(operation)

            recovered = pipeline.recovery_operation(state.id, request_id)

            self.assertEqual(recovered["status"], "partial")
            self.assertEqual(recovered["error_code"], "replanning_interrupted")
            self.assertEqual(recovered["result_commit"], operation.result_commit)

    def test_same_group_apply_preserves_completed_and_failed_execution_evidence(self) -> None:
        from copy import deepcopy

        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state = pipeline.execute(state.id, manual=True)
            state.planning_agent_id = "worker"
            failed = state.tasks[0]
            failed.status = TaskStatus.FAILED
            failed.error = "verification failed"
            failed.failed_action = TaskAction.VERIFY
            failed.started_commit = "original-baseline"
            preserved_worktree = failed.worktree
            done = deepcopy(failed)
            done.id = "done"
            done.status = TaskStatus.COMPLETED
            done.error = ""
            done.failed_action = None
            done.completed_commit = "completed-commit"
            state.tasks.insert(0, done)
            state.fail_step(RunStep.AGENT_EXECUTION, "verification failed")
            state.refresh_task_readiness()
            pipeline._append_planning_user_message(state, "실패한 Task 요구사항을 수정해 주세요.")
            pipeline.store.save(state)
            original_done = deepcopy(state.to_dict()["tasks"][0])
            proposals = deepcopy(state.tasks)
            proposals[0].description = "must not overwrite completed task"
            proposals[1].description = "수정된 요구사항"
            proposals[1].status = TaskStatus.PENDING
            with patch.object(pipeline, "_build_plan", return_value=Plan(summary="updated", server_work=False, tasks=proposals)):
                updated = pipeline.send_planning_message(state.id, "지금까지 내용을 Task에 적용해줘")
            self.assertEqual(updated.id, state.id)
            self.assertEqual(updated.stage, Stage.FAILED)
            self.assertEqual(updated.failure_message, "verification failed")
            self.assertEqual(updated.to_dict()["tasks"][0], original_done)
            blocked = pipeline.planning_apply_preview(state.id)
            self.assertFalse(blocked["can_apply"])
            self.assertEqual(blocked["changes"][0]["kind"], "review_required")
            proposals[0].description = state.tasks[0].description
            proposals[0].status = TaskStatus.PENDING
            with patch.object(pipeline, "_build_plan", return_value=Plan(summary="updated", server_work=False, tasks=proposals)):
                preview = pipeline.preview_planning_apply(state.id, request_id=str(uuid.uuid4()))
            self.assertTrue(preview["can_apply"])
            applied = pipeline.apply_planning_preview(
                state.id, preview_id=preview["preview_id"], fingerprint=preview["fingerprint"],
                candidate_digest=preview["candidate_digest"],
            )["run"]
            self.assertEqual(applied.to_dict()["tasks"][0], original_done)
            changed = applied.tasks[1]
            self.assertEqual(changed.description, "수정된 요구사항")
            self.assertEqual(changed.status, TaskStatus.FAILED)
            self.assertEqual(changed.error, "verification failed")
            self.assertEqual(changed.failed_action, TaskAction.EXECUTE)
            self.assertEqual(changed.started_commit, "original-baseline")
            self.assertEqual(changed.worktree, preserved_worktree)
            self.assertEqual(pipeline.status(state.id).planning_follow_up_requests, [])
            self.assertEqual(len(pipeline.list_statuses()), 1)

    def test_same_group_invalid_plan_preserves_tasks_and_pending_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state.planning_agent_id = "worker"
            state.stage = Stage.EXECUTING
            pipeline._append_planning_user_message(state, "현재 Task 계획을 다시 정리해 주세요.")
            pipeline.store.save(state)
            original = state.to_dict()["tasks"]
            with patch.object(pipeline, "_build_plan", return_value=Plan(summary="bad", server_work=False, tasks=[])):
                with self.assertRaisesRegex(PlanningError, "task plan must not be empty"):
                    pipeline.send_planning_message(state.id, "지금까지 내용을 Task에 적용해줘")
            restored = pipeline.status(state.id)
            self.assertEqual(restored.to_dict()["tasks"], original)
            self.assertFalse(restored.planning_follow_up_requests)
            self.assertIsNone(pipeline.planning_apply_preview(state.id))

    def test_busy_planning_chat_preserves_failed_batch_and_queued_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state.planning_agent_id = "worker"
            pipeline._append_planning_user_message(state, "실패 뒤 적용할 요구사항을 보존해 주세요.")
            pipeline.store.save(state)

            def fail(current, *_args):
                pipeline.send_planning_message(current.id, "지금까지 내용을 Task에 적용해줘")
                raise PipelineError("worker failed")

            apply_after_batch = pipeline._apply_queued_changes_after_batch

            def busy(current):
                with pipeline.store.planning_chat_lock(current.id):
                    return apply_after_batch(current)

            with (
                patch.object(pipeline, "_invoke_agent", side_effect=fail),
                patch.object(pipeline, "_apply_queued_changes_after_batch", side_effect=busy),
                patch.object(pipeline, "_build_plan", return_value=Plan(summary=state.summary, server_work=False, tasks=deepcopy(state.tasks))),
            ):
                failed = pipeline.execute(state.id)
            self.assertEqual(failed.stage, Stage.FAILED)
            self.assertIn("worker failed", failed.failure_message)
            self.assertFalse(failed.planning_follow_up_requests)
            self.assertIsNotNone(pipeline.planning_apply_preview(state.id))
            self.assertEqual(failed.tasks[0].status, TaskStatus.FAILED)

    def test_same_group_update_keeps_completed_group_ready_and_routes_new_work_to_execution(self) -> None:
        from copy import deepcopy

        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state.planning_agent_id = "worker"
            state.stage = Stage.EXECUTING
            state.tasks[0].status = TaskStatus.COMPLETED
            pipeline._append_planning_user_message(state, "완료 결과 뒤에 후속 작업을 추가해 주세요.")
            pipeline.store.save(state)
            proposal = deepcopy(state.tasks)
            proposal[0].status = TaskStatus.PENDING
            with patch.object(pipeline, "_build_plan", return_value=Plan(summary=state.summary, server_work=False, tasks=proposal)):
                previewed = pipeline.send_planning_message(state.id, "지금까지 내용을 Task에 적용해줘")
            self.assertEqual(previewed.stage, Stage.EXECUTING)
            self.assertFalse(previewed.planning_follow_up_requests)
            candidate = pipeline.planning_apply_preview(state.id)
            self.assertIsNotNone(candidate)
            completed = pipeline.apply_planning_preview(
                state.id, preview_id=candidate["preview_id"], fingerprint=candidate["fingerprint"],
                candidate_digest=candidate["candidate_digest"],
            )["run"]
            self.assertEqual(completed.stage, Stage.READY_TO_MERGE)
            completed.fail_step(RunStep.VERIFY, "integration failed")
            pipeline.store.save(completed)
            extra = WorkTask(id="extra", title="추가 작업", capabilities=["general"], agent_id="worker", expected_paths=["extra.txt"])
            with patch.object(
                pipeline, "_build_plan", return_value=Plan(summary=state.summary, server_work=False, tasks=[*deepcopy(completed.tasks), extra])
            ):
                updated = pipeline.apply_planning_conversation(state.id)
            self.assertEqual(updated.stage, Stage.FAILED)
            self.assertEqual(updated.failure_message, "integration failed")
            self.assertEqual(updated.failed_step, RunStep.AGENT_EXECUTION)
            self.assertEqual(updated.tasks[-1].status, TaskStatus.PENDING)
            self.assertEqual(updated.tasks[-1].worktree, updated.execution_worktree)
            self.assertTrue(Path(updated.tasks[-1].prompt_path).is_file())

    def test_resume_repairs_execution_files_missing_from_a_replanned_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state = pipeline.execute(state.id, manual=True)
            task = state.tasks[0]
            task.status = TaskStatus.FAILED
            task.error = "[Errno 13] Permission denied: '.'"
            task.failed_action = TaskAction.EXECUTE
            task.branch = ""
            task.worktree = ""
            task.prompt_path = ""
            task.log_path = ""
            state.fail_step(RunStep.AGENT_EXECUTION, task.error)
            pipeline.store.save(state)

            repaired = pipeline.resume(state.id, manual=True)

            task = repaired.tasks[0]
            self.assertEqual(task.status, TaskStatus.WAITING)
            self.assertEqual(task.worktree, repaired.execution_worktree)
            self.assertEqual(task.branch, repaired.execution_branch)
            self.assertTrue(Path(task.prompt_path).is_file())
            self.assertNotEqual(Path(task.prompt_path), Path("."))
            self.assertEqual(Path(task.log_path).parent, pipeline.store.run_dir(state.id) / "logs")
            self.assertTrue(any("execution files restored" in event.message for event in repaired.events))

    def test_apply_during_execution_is_consumed_after_batch_in_same_group(self) -> None:
        from copy import deepcopy

        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state.planning_agent_id = "worker"
            pipeline._append_planning_user_message(state, "현재 결과에 후속 Task를 추가해 주세요.")
            pipeline.store.save(state)

            def implement(current, task, *_args):
                queued = pipeline.send_planning_message(current.id, "지금까지 내용을 Task에 적용해줘")
                self.assertFalse(queued.planning_follow_up_requests)
                self.assertFalse(pipeline.planning_apply_preview(current.id)["can_apply"])
                (Path(task.worktree) / "result.txt").write_text("done", encoding="utf-8")
                return "done"

            def replan(current, *_args, **_kwargs):
                extra = WorkTask(id="extra", title="추가 작업", capabilities=["general"], agent_id="worker", expected_paths=["extra.txt"])
                proposal = deepcopy(current.tasks[0])
                proposal.status = TaskStatus.PENDING
                proposal.active_action = None
                proposal.action_results = []
                return Plan(summary=current.summary, server_work=False, tasks=[proposal, extra])

            with patch.object(pipeline, "_invoke_agent", side_effect=implement) as worker, patch.object(pipeline, "_build_plan", side_effect=replan):
                updated = pipeline.execute(state.id)
            self.assertEqual(worker.call_count, 1)
            self.assertEqual(updated.id, state.id)
            self.assertEqual([task.status for task in updated.tasks], [TaskStatus.COMPLETED])
            self.assertTrue(updated.tasks[0].completed_commit)
            self.assertFalse(updated.planning_follow_up_requests)
            self.assertIsNone(updated.active_step)
            self.assertTrue(pipeline.planning_apply_preview(state.id)["stale"])
            with patch.object(pipeline, "_build_plan", side_effect=replan):
                preview = pipeline.preview_planning_apply(state.id, request_id=str(uuid.uuid4()))
            self.assertTrue(preview["can_apply"])
            applied = pipeline.apply_planning_preview(
                state.id, preview_id=preview["preview_id"], fingerprint=preview["fingerprint"],
                candidate_digest=preview["candidate_digest"],
            )["run"]
            self.assertEqual([task.status for task in applied.tasks], [TaskStatus.COMPLETED, TaskStatus.PENDING])

    def test_task_log_includes_final_failure_after_successful_provider_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            task = state.tasks[0]
            log_path = pipeline.store.run_dir(state.id) / "provider.log"
            log_path.write_text("provider turn completed\n", encoding="utf-8")
            task.log_path = str(log_path)
            task.status = TaskStatus.FAILED
            task.failed_action = TaskAction.EXECUTE
            task.error = "change scope validation failed"
            pipeline.store.save(state)
            displayed = pipeline.task_log(state.id, task.id)
            self.assertIn("provider turn completed", displayed)
            self.assertIn("실패 단계: execute", displayed)
            self.assertTrue(displayed.endswith("원인: change scope validation failed"))
            self.assertEqual(log_path.read_text(encoding="utf-8"), "provider turn completed\n")

    def test_task_verification_reports_current_command_and_passed_count(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state = pipeline.execute(state.id, manual=True)
            task = state.tasks[0]
            (Path(task.worktree) / "result.txt").write_text("done", encoding="utf-8")
            task.verify_commands = [
                [sys.executable, "-c", "pass"],
                [sys.executable, "-c", "raise SystemExit(1)"],
            ]
            pipeline.store.save(state)
            observations = []

            def run_verification(command, *_args, **_kwargs):
                current = pipeline.store.load(state.id).tasks[0]
                observations.append((current.progress_phase, current.progress_detail, len(current.action_results[-1].passed_commands)))
                self.assertTrue(current.progress_updated_at)
                return subprocess.CompletedProcess(command, 0 if len(observations) == 1 else 1, "test output")

            with patch("ai_orchestrator.pipeline.run_command", side_effect=run_verification):
                with self.assertRaisesRegex(PipelineError, "verification command failed"):
                    pipeline.complete_task(state.id, task.id)
            self.assertEqual([item[0] for item in observations], ["verifying_command", "verifying_command"])
            self.assertTrue(observations[0][1].startswith("1/2 · "))
            self.assertTrue(observations[1][1].startswith("2/2 · "))
            self.assertEqual([item[2] for item in observations], [0, 1])
            final = pipeline.store.load(state.id).tasks[0]
            self.assertEqual(final.action_results[-1].status, "failed")
            self.assertEqual(len(final.action_results[-1].passed_commands), 1)
            log = pipeline.task_log(state.id, task.id)
            self.assertIn("exit code: 0", log)
            self.assertIn("exit code: 1", log)

    def test_repeated_sdk_activity_updates_last_report_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            task = state.tasks[0]
            task.begin_action(TaskAction.EXECUTE)
            task.update_progress("running_command", "dotnet test")
            task.progress_updated_at = "2000-01-01T00:00:00+00:00"
            pipeline.store.save(state)
            pipeline._record_task_progress(state, task, CodexSdkProgress("running_command", "dotnet test"))
            restored = pipeline.store.load(state.id).tasks[0]
            self.assertNotEqual(restored.progress_updated_at, "2000-01-01T00:00:00+00:00")
            self.assertEqual(restored.progress_detail, "dotnet test")
            self.assertIsNotNone(restored.progress_observation)
            first_activity = restored.progress_observation.last_activity_changed_at
            pipeline._record_task_progress(
                state,
                task,
                CodexSdkProgress(
                    "running_command",
                    "dotnet test",
                    invocation_id=restored.progress_observation.invocation_id,
                    received_at="2099-01-01T00:00:05+00:00",
                    event_seq=2,
                    activity_changed=False,
                    evidence_kind="provider_event",
                ),
            )
            repeated = pipeline.store.load(state.id).tasks[0].progress_observation
            self.assertEqual(repeated.last_event_received_at, "2099-01-01T00:00:05+00:00")
            self.assertEqual(repeated.last_activity_changed_at, first_activity)

    def test_dotnet_preflight_blocks_worker_and_preserves_retry_action(self) -> None:
        for resume_action in (TaskAction.EXECUTE, TaskAction.VERIFY):
            with self.subTest(action=resume_action), tempfile.TemporaryDirectory() as directory:
                pipeline, state = self._scope_test_run(Path(directory))
                state = pipeline.execute(state.id, manual=True)
                task = state.tasks[0]
                task.verify_commands = [["dotnet", "--info"], ["dotnet", "test"]]
                task.status = TaskStatus.FAILED
                task.failed_action = resume_action
                state.fail_step(RunStep.AGENT_EXECUTION, "previous failure")
                pipeline.store.save(state)
                pipeline.dotnet_executable = "C:/SDK/dotnet.exe"
                diagnostic = DotnetDiagnostic(pipeline.dotnet_executable, "No compatible SDK", "SDK 환경 오류")
                with (
                    patch("ai_orchestrator.pipeline.diagnose_dotnet", return_value=diagnostic) as diagnose,
                    patch.object(pipeline, "_run_task") as worker,
                ):
                    failed = pipeline.retry_task(state.id, task.id)
                worker.assert_not_called()
                diagnose.assert_called_once_with(pipeline.dotnet_executable, Path(task.worktree))
                self.assertEqual(failed.stage, Stage.FAILED)
                self.assertEqual(failed.tasks[0].failed_action, resume_action)
                self.assertIn("No compatible SDK", pipeline.task_log(state.id, task.id))

    def test_dotnet_retry_after_environment_fix_runs_verification_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            task = state.tasks[0]
            task.verify_commands = [["dotnet", "test"]]
            pipeline.store.save(state)

            def implement(_state, selected_task, *_args):
                (Path(selected_task.worktree) / "result.txt").write_text("done", encoding="utf-8")
                return "done"

            with (
                patch(
                    "ai_orchestrator.pipeline.diagnose_dotnet",
                    side_effect=[
                        DotnetDiagnostic("dotnet", "SDK selected"),
                        DotnetDiagnostic("dotnet", "missing SDK", "SDK error"),
                    ],
                ),
                patch.object(pipeline, "_invoke_agent", side_effect=implement),
            ):
                failed = pipeline.execute(state.id)
            task = failed.tasks[0]
            self.assertEqual(failed.tasks[0].failed_action, TaskAction.VERIFY)
            pipeline.dotnet_executable = "C:/SDK/dotnet.exe"
            with (
                patch("ai_orchestrator.pipeline.diagnose_dotnet", return_value=DotnetDiagnostic(pipeline.dotnet_executable, "SDK selected")),
                patch("ai_orchestrator.pipeline.run_command", return_value=subprocess.CompletedProcess([], 0, "tests passed")) as run,
                patch.object(pipeline, "_run_executor") as worker,
            ):
                retried = pipeline.retry_task(state.id, task.id)
            worker.assert_not_called()
            self.assertEqual(retried.tasks[0].status, TaskStatus.COMPLETED)
            self.assertEqual(run.call_args.args[0], (pipeline.dotnet_executable, "test"))
            self.assertEqual((Path(task.worktree) / "result.txt").read_text(encoding="utf-8"), "done")

    def test_dotnet_build_server_verification_uses_configured_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            task = state.tasks[0]
            command = ("dotnet", "build-server", "shutdown")
            pipeline.dotnet_executable = "C:/SDK/dotnet.exe"
            diagnostic = DotnetDiagnostic(pipeline.dotnet_executable, "SDK selected")
            diagnostics: list[str] = []

            with patch("ai_orchestrator.pipeline.diagnose_dotnet", return_value=diagnostic) as diagnose:
                selected = pipeline._prepare_verification_command(command, Path(task.worktree), diagnostics.append)

            diagnose.assert_called_once_with(pipeline.dotnet_executable, Path(task.worktree))
            self.assertEqual(selected, (pipeline.dotnet_executable, "build-server", "shutdown"))
            self.assertEqual(diagnostics, ["SDK selected"])

    def test_failed_planning_chat_preserves_task_results_and_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state = pipeline.execute(state.id, manual=True)
            state.planning_agent_id = "worker"
            task = state.tasks[0]
            task.status = TaskStatus.FAILED
            task.failed_action = TaskAction.VERIFY
            task.error = "SDK not found"
            state.fail_step(RunStep.AGENT_EXECUTION, task.error)
            state.refresh_task_readiness()
            pipeline.store.save(state)
            original = pipeline.store.state_path(state.id).read_text(encoding="utf-8")
            with (
                patch.object(pipeline, "_invoke_planning_agent", return_value="SDK 경로를 확인하세요."),
                patch.object(pipeline, "_build_plan", return_value=Plan(summary=state.summary, server_work=False, tasks=state.tasks)),
            ):
                chatted = pipeline.send_planning_message(state.id, "실패 원인을 알려줘", planning_agent_id="worker")
                followed = pipeline.send_planning_message(state.id, "후속 Task에 적용해줘", planning_agent_id="worker")
            self.assertEqual(chatted.planning_messages[-1].text, "SDK 경로를 확인하세요.")
            self.assertEqual(pipeline.store.state_path(state.id).read_text(encoding="utf-8"), original)
            restored = pipeline.status(state.id)
            self.assertEqual(restored.stage, Stage.FAILED)
            self.assertEqual(restored.failure_message, "SDK not found")
            self.assertEqual(len(restored.planning_follow_up_requests), 0)
            self.assertEqual(restored.id, state.id)

    def test_dotnet_sdk_error_is_logged_before_task_or_integration_verification(self) -> None:
        for integration in (False, True):
            with self.subTest(integration=integration), tempfile.TemporaryDirectory() as directory:
                pipeline, state = self._scope_test_run(Path(directory))
                state = pipeline.execute(state.id, manual=True)
                (Path(state.tasks[0].worktree) / "result.txt").write_text("done", encoding="utf-8")
                if integration:
                    state = pipeline.complete_task(state.id, state.tasks[0].id)
                state.tasks[0].verify_commands = [["dotnet", "test", "tests.csproj"]]
                pipeline.store.save(state)
                diagnostic = DotnetDiagnostic(
                    "C:/runtime/dotnet.exe", "Requested SDK version: 10.0.301\nNo .NET SDKs were found.", ".NET SDK 환경 오류: SDK를 찾지 못했습니다."
                )
                with patch("ai_orchestrator.pipeline.diagnose_dotnet", return_value=diagnostic), patch("ai_orchestrator.pipeline.run_command") as run:
                    with self.assertRaisesRegex(PipelineError, ".NET SDK 환경 오류"):
                        if integration:
                            pipeline.verify(state.id)
                        else:
                            pipeline.complete_task(state.id, state.tasks[0].id)
                run.assert_not_called()
                failed = pipeline.store.load(state.id)
                if integration:
                    log_path = Path(failed.verification_attempts[-1].log_path)
                    self.assertEqual(failed.verification_attempts[-1].passed_commands, [])
                else:
                    log_path = pipeline.store.run_dir(state.id) / "logs" / f"{state.tasks[0].id}-verify.log"
                    self.assertEqual(failed.tasks[0].failed_action, TaskAction.VERIFY)
                self.assertIn(diagnostic.log, log_path.read_text(encoding="utf-8"))

    def test_dotnet_success_pins_executable_without_hiding_test_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            diagnostic = DotnetDiagnostic("C:/sdk/dotnet.exe", "SDK selected: 10.0.301")
            with (
                patch("ai_orchestrator.pipeline.diagnose_dotnet", return_value=diagnostic),
                patch("ai_orchestrator.pipeline.run_command", return_value=subprocess.CompletedProcess([], 1, "test assertion failed")) as run,
            ):
                with self.assertRaisesRegex(PipelineError, "통합 검증 명령이 실패"):
                    pipeline._run_verification_commands(state, pipeline.repo, (("dotnet", "test"),))
            self.assertEqual(run.call_args.args[0], (diagnostic.executable, "test"))
            log = (pipeline.store.run_dir(state.id) / "logs" / "verify.log").read_text(encoding="utf-8")
            self.assertIn(diagnostic.log, log)
            self.assertIn("test assertion failed", log)

    def test_integration_dotnet_build_commands_use_private_build_processes_only(self) -> None:
        commands = (
            ("dotnet", "restore", "Example.sln"), ("dotnet", "build", "Example.sln"),
            ("dotnet", "test", "Example.sln"), ("dotnet", "--version"), (sys.executable, "check.py"),
        )
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            diagnostic = DotnetDiagnostic("C:/sdk/dotnet.exe", "SDK selected: 10.0.301")
            with (
                patch("ai_orchestrator.pipeline.diagnose_dotnet", return_value=diagnostic),
                patch("ai_orchestrator.pipeline.run_command", return_value=subprocess.CompletedProcess([], 0, "passed")) as run,
            ):
                pipeline._run_verification_commands(state, pipeline.repo, commands)
            self.assertEqual(run.call_count, len(commands))
            for command, call in zip(commands, run.call_args_list, strict=True):
                expected = (diagnostic.executable, *command[1:]) if command[0] == "dotnet" else command
                self.assertEqual(call.args[0], expected)
                environment = call.kwargs.get("environment_overrides")
                if command[0] == "dotnet" and command[1] in {"restore", "build", "test"}:
                    self.assertEqual(environment, {
                        "DOTNET_CLI_USE_MSBUILD_SERVER": "0", "MSBUILDUSESERVER": "0", "MSBUILDDISABLENODEREUSE": "1",
                    })
                else:
                    self.assertIsNone(environment)
                self.assertTrue(call.kwargs["non_interactive"])
                self.assertGreater(call.kwargs["timeout_seconds"], 0)

    def test_sdk_planning_assigns_more_tasks_than_agent_max_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            codex = AgentConfig("sdk", ("general", "planning"), (), 1, provider_id="codex")
            sdk = connected_codex_sdk()
            sdk.account_status.return_value = CodexSdkAccountStatus(True, "chatgpt", "로그인됨")
            tasks = []
            for index in range(6):
                task = pipeline._task_plan_draft(state.tasks[0])
                task.update(id=f"task-{index}", provider_id="codex", verify_commands=[[sys.executable, "-c", "pass"]])
                tasks.append(task)
            sdk.run_turn.return_value = "AI_PLAN_RESULT: " + json.dumps(
                {
                    "summary": "six tasks",
                    "server_work": False,
                    "tasks": tasks,
                    "source_paths": [],
                    "instruction_paths": [],
                    "questions": [],
                }
            )
            pipeline = Pipeline(replace(pipeline.config, agents=(codex,), planning=PlanningConfig(agent_id=codex.id)), codex_sdk=sdk)
            planned = pipeline.start(state.spec_path)
            self.assertEqual(len(planned.tasks), 6)
            self.assertTrue(all(task.agent_id == codex.id for task in planned.tasks))
            self.assertEqual(sdk.run_turn.call_count, 1)
            self.assertIn("Provider `codex`", sdk.run_turn.call_args.args[0].prompt)

    def test_shared_plan_edit_and_provider_switch_reuse_one_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            drafts = []
            for index in range(6):
                draft = pipeline._task_plan_draft(state.tasks[0])
                draft.update(id=f"task-{index}", verify_commands=[[sys.executable, "-c", "pass"]])
                drafts.append(draft)
            updated = pipeline.update_plan(state.id, drafts)
            self.assertEqual(len(updated.tasks), 6)
            self.assertTrue(all(task.agent_id == "worker" for task in updated.tasks))
            pipeline.confirm_plan(state.id)
            codex = AgentConfig("sdk-worker", ("general",), (), 1, provider_id="codex")
            pipeline = Pipeline(replace(pipeline.config, agents=(*pipeline.config.agents, codex)), codex_sdk=connected_codex_sdk())
            for draft in drafts:
                draft.update(provider_id="codex", model="", reasoning_effort="")
            switched = pipeline.update_plan(state.id, drafts)
            self.assertFalse(switched.plan_is_approved)
            confirmed = pipeline.confirm_plan(state.id)
            self.assertTrue(all(task.agent_id == codex.id for task in confirmed.tasks))
            self.assertEqual(len(confirmed.tasks), 6)

    def test_manual_nvidia_profile_runs_through_existing_task_commit_and_verification(self) -> None:
        from ai_orchestrator.nvidia_agent import nvidia_credential_scope

        for model in ("nvidia/nemotron-3-super-120b-a12b", "vendor/registered-model"):
            with (
                self.subTest(model=model), tempfile.TemporaryDirectory() as directory,
                nvidia_credential_scope("default-fixture", {"vendor/registered-model": "model-fixture"}),
            ):
                pipeline, state = self._scope_test_run(Path(directory))
                draft = pipeline._task_plan_draft(state.tasks[0])
                draft.update(provider_id="nvidia", model=model, reasoning_effort="",
                             verify_commands=[[sys.executable, "-c", "from pathlib import Path; assert Path('result.txt').read_text() == 'done'"]])
                resolve = pipeline._resolve_executable
                calls = []

                def invoke(**request):
                    calls.append((request["agent"].provider_id, request["action"], request["model"]))
                    (request["cwd"] / "result.txt").write_text("done", encoding="utf-8")
                    return "공개 예제 수정 완료"

                with (
                    patch.object(pipeline, "_resolve_executable", side_effect=lambda value: "opencode.exe" if value == "opencode" else resolve(value)),
                    patch.object(pipeline, "_run_provider_command", side_effect=invoke),
                ):
                    pipeline.update_plan(state.id, [draft])
                    pipeline.confirm_plan(state.id)
                    completed = pipeline.execute(state.id)
                self.assertEqual(calls, [("nvidia", "execute", draft["model"])])
                self.assertEqual(completed.tasks[0].provider_id, "nvidia")
                self.assertTrue(completed.tasks[0].completed_commit)
                self.assertEqual(completed.tasks[0].reviewer_agent_id, "")
                self.assertIn(completed.tasks[0].status, {TaskStatus.COMPLETED, TaskStatus.MERGED})

    def test_planning_preview_and_cached_replanning_preserve_manual_nvidia_execution(self) -> None:
        from ai_orchestrator.nvidia_agent import nvidia_credential_scope

        for failed in (False, True):
            for model in ("nvidia/nemotron-3-ultra-550b-a55b", "vendor/registered-model"):
                with (
                    self.subTest(failed=failed, model=model), tempfile.TemporaryDirectory() as directory,
                    nvidia_credential_scope("default-fixture", {model: "model-fixture"}),
                ):
                    pipeline, state = self._scope_test_run(Path(directory))
                    codex = AgentConfig("codex-worker", ("general",), (), 2, provider_id="codex", model="gpt-6.1-sol")
                    pipeline = Pipeline(replace(pipeline.config, agents=(*pipeline.config.agents, codex),
                                                planning=PlanningConfig(agent_id="worker", max_attempts=1)), codex_sdk=connected_codex_sdk())
                    resolve = pipeline._resolve_executable
                    with patch.object(
                        pipeline, "_resolve_executable", side_effect=lambda value: "opencode.exe" if value == "opencode" else resolve(value)
                    ):
                        draft = pipeline._task_plan_draft(state.tasks[0])
                        verify = [sys.executable, "-c", "from pathlib import Path; assert Path('result.txt').read_text() == 'done'"]
                        draft.update(provider_id="nvidia", model=model, reasoning_effort="",
                                     verify_commands=[verify])
                        pipeline.update_plan(state.id, [draft])
                        state = pipeline.confirm_plan(state.id)
                        if failed:
                            state = pipeline.execute(state.id, manual=True)
                            state.tasks[0].status = TaskStatus.FAILED
                            state.tasks[0].failed_action = TaskAction.EXECUTE
                            state.fail_step(RunStep.AGENT_EXECUTION, "previous execution failed")
                        state.planning_agent_id = "worker"
                        pipeline._append_planning_user_message(state, "설명을 보강하고 기존 실행 AI 선택은 유지해 주세요.")
                        pipeline.store.save(state)
                        original = deepcopy(state.tasks[0])
                        proposal = pipeline._task_plan_draft(original)
                        proposal.update(description="보강한 작업 설명", provider_id="codex", model="gpt-6.1-sol", reasoning_effort="medium")
                        output = "AI_PLAN_RESULT: " + json.dumps({"summary": state.summary, "server_work": False,
                                                                 "tasks": [proposal], "questions": []}, ensure_ascii=False)
                        with (
                            patch.object(pipeline.git, "has_uncommitted_changes", return_value=False),
                            patch.object(pipeline.store, "load_planning_result", return_value=output),
                            patch.object(pipeline, "_invoke_planning_agent") as invoke,
                        ):
                            cached = pipeline._build_plan(deepcopy(state), "요구사항")
                        invoke.assert_not_called()
                        self.assertEqual(cached.tasks[0].provider_id, "nvidia")
                        self.assertEqual(cached.tasks[0].model, model)
                        with patch.object(pipeline, "_invoke_planning_agent", return_value=output):
                            preview = pipeline.preview_planning_apply(state.id, request_id=str(uuid.uuid4()))
                        self.assertTrue(preview["can_apply"])
                        self.assertEqual(preview["changes"][0]["fields"], ["description"])
                        updated = pipeline.apply_planning_preview(
                            state.id, preview_id=preview["preview_id"], fingerprint=preview["fingerprint"],
                            candidate_digest=preview["candidate_digest"],
                        )["run"]
                        task = updated.tasks[0]
                        self.assertEqual((task.agent_id, task.provider_id, task.model, task.reasoning_effort, task.profile_source),
                                         (original.agent_id, "nvidia", model, "", ProfileSource.MANUAL))
                        self.assertEqual(task.description, "보강한 작업 설명")
                        if not failed:
                            pipeline.confirm_plan(state.id)
                        calls = []

                        def execute(**request):
                            calls.append((request["agent"].provider_id, request["model"]))
                            (request["cwd"] / "result.txt").write_text("done", encoding="utf-8")
                            return "모의 NVIDIA 수정 완료"

                        with patch.object(pipeline, "_run_provider_command", side_effect=execute):
                            completed = pipeline.retry_task(state.id, task.id) if failed else pipeline.execute(state.id)
                        self.assertEqual(calls, [("nvidia", model)])
                        self.assertIn(completed.tasks[0].status, {TaskStatus.COMPLETED, TaskStatus.MERGED})

    def test_saved_next_execution_profile_retries_failed_verification_with_selected_ai(self) -> None:
        from ai_orchestrator.nvidia_agent import nvidia_credential_scope

        with tempfile.TemporaryDirectory() as directory, nvidia_credential_scope("fixture-key"):
            pipeline, state = self._scope_test_run(Path(directory))
            state = pipeline.execute(state.id, manual=True)
            task = state.tasks[0]
            task.status, task.failed_action = TaskStatus.FAILED, TaskAction.VERIFY
            task.error = "original verification failure"
            task.verify_commands = [[sys.executable, "-c", "from pathlib import Path; assert Path('result.txt').read_text() == 'fixed'"]]
            task.last_attempt_id = "old-attempt"
            state.fail_step(RunStep.AGENT_EXECUTION, task.error)
            pipeline.store.save(state)
            selected = next(agent for agent in pipeline.config.agents if agent.provider_id == "nvidia")
            resolve = pipeline._resolve_executable
            calls = []

            def implement(**request):
                calls.append((request["agent"].provider_id, request["action"], request["model"]))
                (request["cwd"] / "result.txt").write_text("fixed", encoding="utf-8")
                return "모의 NVIDIA 수정 완료"

            with (
                patch.object(pipeline, "_resolve_executable", side_effect=lambda value: sys.executable if value == "opencode" else resolve(value)),
                patch.object(pipeline, "_run_provider_command", side_effect=implement),
            ):
                saved = pipeline.update_task_execution_profile(
                    state.id, task.id, agent_id=selected.id, model=selected.model, reasoning_effort="",
                    expected_profile={"agent_id": task.agent_id, "model": task.model, "reasoning_effort": task.reasoning_effort,
                                      "last_attempt_id": task.last_attempt_id, "status": "failed"},
                )
                self.assertEqual(calls, [])
                self.assertEqual(saved.stage, Stage.FAILED)
                self.assertEqual(saved.tasks[0].error, "original verification failure")
                self.assertEqual(saved.tasks[0].failed_action, TaskAction.EXECUTE)
                completed = pipeline.retry_task(state.id, task.id)
            self.assertEqual(calls, [("nvidia", "execute", selected.model)])
            self.assertEqual(completed.tasks[0].status, TaskStatus.COMPLETED)

    def test_pending_profile_saved_by_another_instance_is_used_by_the_next_dispatch(self) -> None:
        from ai_orchestrator.nvidia_agent import nvidia_credential_scope

        for mode in (ExecutionWorkspaceMode.SHARED, ExecutionWorkspaceMode.ISOLATED):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory, nvidia_credential_scope("fixture-key"):
                pipeline, state = self._scope_test_run(Path(directory), mode=mode, max_tasks=2)
                first = state.tasks[0]
                second = deepcopy(first)
                second.id, second.title, second.dependencies = "next-task", "다음 작업", [first.id]
                state.tasks.append(second)
                state.revise_plan()
                pipeline.store.save(state)
                state = pipeline.confirm_plan(state.id)
                remote = Pipeline(pipeline.config)
                resolve = pipeline._resolve_executable
                calls = []

                def implement(current, task, agent, *_args):
                    calls.append((task.id, agent.provider_id, task.model))
                    if task.id == first.id:
                        before = remote.store.load(current.id)
                        target = before.tasks[-1]
                        selected = next(item for item in remote.config.agents if item.provider_id == "nvidia")
                        saved = remote.update_task_execution_profile(
                            current.id, target.id, agent_id=selected.id, model=selected.model, reasoning_effort="",
                            expected_profile=remote._task_execution_profile_snapshot(target),
                        )
                        self.assertEqual(saved.tasks[-1].provider_id, "nvidia")
                        self.assertEqual(remote.store.load(current.id).tasks[-1].agent_id, "worker")
                        self.assertEqual(current.tasks[0].agent_id, "worker")
                    (Path(task.worktree) / "result.txt").write_text(task.id, encoding="utf-8")
                    return "모의 구현 완료"

                with (
                    patch.object(pipeline, "_resolve_executable",
                                 side_effect=lambda value: sys.executable if value == "opencode" else resolve(value)),
                    patch.object(remote, "_resolve_executable", return_value=sys.executable),
                    patch.object(pipeline, "_invoke_agent", side_effect=implement),
                ):
                    completed = pipeline.execute(state.id)
                self.assertEqual(completed.stage, Stage.READY_TO_MERGE)
                self.assertEqual([item[0] for item in calls], [first.id, second.id])
                self.assertEqual(calls[-1][1], "nvidia")
                self.assertEqual(completed.tasks[-1].profile_source, ProfileSource.MANUAL)
                self.assertTrue(all(item.completed_commit for item in completed.tasks))

    def test_verification_finalization_marks_changed_inputs_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state = pipeline.execute(state.id, manual=True)
            worktree = Path(state.tasks[0].worktree)
            (worktree / "result.txt").write_text("done", encoding="utf-8")
            state = pipeline.complete_task(state.id, state.tasks[0].id)
            tested_commit = state.tasks[0].completed_commit
            state.tasks[0].verify_commands = [[sys.executable, "-c", "pass"]]
            pipeline.store.save(state)
            save = pipeline.store.save
            changed = False

            def change_after_checks(saved):
                nonlocal changed
                if saved.verification_progress_phase == "finalizing" and not changed:
                    changed = True
                    git(worktree, "commit", "--allow-empty", "-m", "concurrent change")
                save(saved)

            with patch.object(pipeline.store, "save", side_effect=change_after_checks):
                with self.assertRaisesRegex(PipelineError, "재검증이 필요"):
                    pipeline.verify(state.id)
            self.assertTrue(changed)
            stale = pipeline.store.load(state.id)
            self.assertEqual(stale.stage, Stage.READY_TO_MERGE)
            self.assertEqual(stale.verified_integration_head, "")
            self.assertEqual(stale.verification_attempts[-1].integration_head, tested_commit)
            self.assertEqual(stale.verification_attempts[-1].status, "stale")

    def test_interrupted_evidence_is_preserved_when_a_new_attempt_starts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            task = state.tasks[0]
            task.action_results.append(TaskActionResult("execute", worker_response="partial"))
            state.verification_attempts.append(VerificationAttempt(integration_head="old-head"))
            with self.assertRaisesRegex(PipelineError, "new failure"):
                with pipeline._task_action(state, task, TaskAction.EXECUTE):
                    raise PipelineError("new failure")
            with self.assertRaisesRegex(PipelineError, "verification failure"):
                with pipeline._step(state, RunStep.VERIFY):
                    raise PipelineError("verification failure")
            restored = pipeline.store.load(state.id)
            self.assertEqual([item.status for item in restored.tasks[0].action_results], ["interrupted", "failed"])
            self.assertEqual(restored.tasks[0].action_results[0].worker_response, "partial")
            self.assertEqual([item.status for item in restored.verification_attempts], ["interrupted", "failed"])
            self.assertEqual(restored.verification_attempts[0].integration_head, "old-head")

    def test_isolated_integration_rejects_uncommitted_verification_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory), mode=ExecutionWorkspaceMode.ISOLATED)
            state = pipeline.execute(state.id, manual=True)
            (Path(state.tasks[0].worktree) / "result.txt").write_text("done", encoding="utf-8")
            state = pipeline.complete_task(state.id, state.tasks[0].id)
            state.tasks[0].verify_commands = [
                [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; Path('result.txt').write_text('changed')",
                ]
            ]
            pipeline.store.save(state)
            with self.assertRaises(GitError):
                pipeline.verify(state.id)
            failed = pipeline.store.load(state.id)
            self.assertEqual(failed.stage, Stage.FAILED)
            self.assertEqual(failed.verified_integration_head, "")
            self.assertEqual(failed.verification_attempts[-1].status, "failed")

    def test_action_evidence_preserves_failed_execution_and_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            responses = iter(["first attempt", "fixed result"])

            def implement(_state, task, *_args):
                response = next(responses)
                (Path(task.worktree) / "result.txt").write_text(response, encoding="utf-8")
                return response

            with patch.object(pipeline, "_invoke_agent", side_effect=implement):
                with patch.object(pipeline.git, "commit_all", side_effect=GitError("commit failed")):
                    failed = pipeline.execute(state.id)
                first = failed.tasks[0].action_results[0]
                self.assertEqual(first.status, "failed")
                self.assertEqual(first.worker_response, "first attempt")
                self.assertEqual(first.changed_paths, ["result.txt"])
                completed = pipeline.execute(state.id)
            results = completed.tasks[0].action_results
            self.assertEqual([item.status for item in results], ["failed", "succeeded", "succeeded"])
            self.assertEqual(results[0].error, "commit failed")
            self.assertEqual(results[1].worker_response, "fixed result")
            self.assertEqual(results[1].result_commit, completed.tasks[0].completed_commit)
            self.assertEqual(results[2].passed_commands, [])
            self.assertTrue(all(item.finished_at for item in results))
            self.assertEqual(len({item.attempt_id for item in results}), len(results))
            self.assertTrue(all(item.attempt_id for item in results))
            self.assertEqual(completed.tasks[0].last_attempt_id, results[-1].attempt_id)

    def test_task_verification_rejects_new_commit_even_in_allowed_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state.tasks[0].verify_commands = [
                ["git", "commit", "--allow-empty", "-m", "unexpected"]
            ]
            pipeline.store.save(state)

            def implement(_state, task, *_args):
                (Path(task.worktree) / "result.txt").write_text("done", encoding="utf-8")
                return "implemented"

            with patch.object(pipeline, "_invoke_agent", side_effect=implement):
                failed = pipeline.execute(state.id)
            self.assertEqual(failed.stage, Stage.FAILED)
            self.assertEqual(failed.tasks[0].failed_action, TaskAction.VERIFY)
            self.assertIn("HEAD changed during verification", failed.tasks[0].error)
            self.assertEqual(failed.tasks[0].action_results[-1].passed_commands, [])
            self.assertEqual(failed.tasks[0].completed_commit, "")

    def test_integration_attempts_preserve_failure_and_successful_retry(self) -> None:
        for mode in ExecutionWorkspaceMode:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                pipeline, state = self._scope_test_run(root, mode=mode)
                state = pipeline.execute(state.id, manual=True)
                (Path(state.tasks[0].worktree) / "result.txt").write_text("done", encoding="utf-8")
                state = pipeline.complete_task(state.id, state.tasks[0].id)
                task_commit = state.tasks[0].completed_commit
                marker = root / "fail-check"
                marker.write_text("fail", encoding="utf-8")
                commands = [
                    [sys.executable, "-c", "print('first passed')"],
                    [
                        sys.executable,
                        "-c",
                        f"from pathlib import Path; import sys; print('second'); sys.exit(7 if Path({str(marker)!r}).exists() else 0)",
                    ],
                ]
                state.tasks[0].verify_commands = commands
                pipeline.store.save(state)
                with self.assertRaisesRegex(PipelineError, "통합 검증 명령이 실패"):
                    pipeline.verify(state.id)
                failed = pipeline.store.load(state.id)
                attempt = failed.verification_attempts[0]
                self.assertEqual(attempt.status, "failed")
                self.assertEqual(attempt.passed_commands, commands[:1])
                self.assertEqual(attempt.current_command, commands[1])
                self.assertEqual(attempt.task_heads, {state.tasks[0].id: task_commit})
                self.assertEqual(attempt.failed_task_id, "")
                self.assertTrue(attempt.integration_head)
                old_log = Path(attempt.log_path).read_text(encoding="utf-8")
                marker.unlink()
                verified = pipeline.verify(state.id)
                self.assertEqual(verified.stage, Stage.VERIFIED)
                self.assertEqual([item.status for item in verified.verification_attempts], ["failed", "succeeded"])
                self.assertEqual(verified.verification_attempts[-1].passed_commands, commands)
                self.assertEqual(Path(attempt.log_path).read_text(encoding="utf-8"), old_log)
                self.assertEqual(verified.tasks[0].completed_commit, task_commit)
                self.assertEqual(verified.verification_attempts[-1].integration_head, verified.verified_integration_head)

    def test_integration_verification_rejects_head_mutation(self) -> None:
        for mode in ExecutionWorkspaceMode:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                pipeline, state = self._scope_test_run(Path(directory), mode=mode)
                state = pipeline.execute(state.id, manual=True)
                (Path(state.tasks[0].worktree) / "result.txt").write_text("done", encoding="utf-8")
                state = pipeline.complete_task(state.id, state.tasks[0].id)
                state.tasks[0].verify_commands = [
                    ["git", "commit", "--allow-empty", "-m", "unexpected"]
                ]
                pipeline.store.save(state)
                with self.assertRaisesRegex(PipelineError, "HEAD changed during verification"):
                    pipeline.verify(state.id)
                failed = pipeline.store.load(state.id)
                self.assertEqual(failed.stage, Stage.FAILED)
                self.assertEqual(failed.verified_integration_head, "")
                self.assertEqual(failed.verification_attempts[-1].passed_commands, [])
                self.assertEqual(failed.verification_attempts[-1].status, "failed")

    def test_conflict_schedule_drives_dependency_handoff_and_execution(self) -> None:
        for mode in ExecutionWorkspaceMode:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                pipeline, state = self._scope_test_run(Path(directory), mode=mode)
                foundation = state.tasks[0]
                foundation.is_prerequisite = True
                consumer = WorkTask(
                    "consumer",
                    "Consumer",
                    ["general"],
                    expected_paths=["result.txt"],
                    agent_id=foundation.agent_id,
                    provider_id=foundation.provider_id,
                )
                state.tasks = [consumer, foundation]
                state.revise_plan()
                pipeline.store.save(state)
                planned = pipeline.confirm_plan(state.id)
                self.assertEqual([task.id for task in planned.tasks], [foundation.id, "consumer"])
                self.assertEqual(planned.tasks[1].dependencies, [])
                self.assertEqual(planned.tasks[1].conflict_dependencies, [foundation.id])
                self.assertEqual(planned.tasks[1].readiness, TaskReadiness.BLOCKED)
                observed: list[str] = []

                def implement(_state, task, *_args):
                    path = Path(task.worktree) / "result.txt"
                    observed.append(task.id)
                    if task.id == "consumer":
                        self.assertEqual(path.read_text(encoding="utf-8"), "schema")
                    path.write_text(task.id if task.id == "consumer" else "schema", encoding="utf-8")
                    return "done"

                with patch.object(pipeline, "_invoke_agent", side_effect=implement):
                    completed = pipeline.execute(state.id)
                self.assertEqual(completed.stage, Stage.READY_TO_MERGE)
                self.assertEqual(observed, [foundation.id, "consumer"])

    def test_conflict_confirmation_failure_preserves_unapproved_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            foundation = state.tasks[0]
            foundation.is_prerequisite = True
            foundation.dependencies = ["consumer"]
            consumer = WorkTask(
                "consumer", "Consumer", ["general"], expected_paths=["result.txt"], agent_id=foundation.agent_id, provider_id=foundation.provider_id
            )
            state.tasks.append(consumer)
            state.revise_plan()
            pipeline.store.save(state)
            before = pipeline.store.state_path(state.id).read_bytes()
            with self.assertRaisesRegex(PipelineError, "conflict prerequisite contradicts"):
                pipeline.confirm_plan(state.id)
            self.assertEqual(pipeline.store.state_path(state.id).read_bytes(), before)
            self.assertFalse(pipeline.status(state.id).plan_is_approved)

    def test_conflict_update_and_exclusion_recompute_derived_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory), max_tasks=2)

            def draft(task_id: str, prerequisite: bool = False) -> dict[str, object]:
                return {
                    "id": task_id,
                    "title": task_id,
                    "description": "작업 설명",
                    "capabilities": ["general"],
                    "depends_on": [],
                    "is_prerequisite": prerequisite,
                    "acceptance_criteria": ["결과 생성"],
                    "expected_paths": ["result.txt"],
                    "forbidden_paths": [],
                    "verify_commands": [[sys.executable, "-c", "pass"]],
                    "risk_level": "low",
                    "provider_id": "",
                    "model": "",
                    "reasoning_effort": "",
                }

            first = draft("first", True)
            second = draft("second")
            updated = pipeline.update_plan(state.id, [second, first])
            self.assertEqual(updated.tasks[1].conflict_dependencies, ["first"])
            bad_first = {**first, "depends_on": ["second"]}
            before = pipeline.store.state_path(state.id).read_bytes()
            with self.assertRaisesRegex(PipelineError, "conflict prerequisite contradicts"):
                pipeline.update_plan(state.id, [second, bad_first])
            self.assertEqual(pipeline.store.state_path(state.id).read_bytes(), before)
            swapped = pipeline.update_plan(state.id, [draft("first"), draft("second", True)])
            self.assertEqual([task.id for task in swapped.tasks], ["second", "first"])
            self.assertEqual(swapped.tasks[1].dependencies, [])
            self.assertEqual(swapped.tasks[1].conflict_dependencies, ["second"])
            excluded = pipeline.exclude_tasks(state.id, ["second"])
            self.assertEqual(excluded.tasks[0].conflict_dependencies, [])
            self.assertEqual(excluded.tasks[0].conflict_group, [])
            self.assertEqual(excluded.tasks[0].readiness, TaskReadiness.READY)
            stored_plan = json.loads(Path(excluded.structured_plan_path).read_text(encoding="utf-8"))
            self.assertEqual(stored_plan["tasks"][0]["conflict_dependencies"], [])
            self.assertFalse(excluded.plan_is_approved)

    def test_scope_globs_are_root_anchored_and_segment_aware(self) -> None:
        for path, rule, expected in (
            ("src/a.py", "src", True),
            ("src2/a.py", "src", False),
            ("src/a.py", "./src/", True),
            ("src/a.py", "src/*.py", True),
            ("src/nested/a.py", "src/*.py", False),
            ("other/src/a.py", "src/*.py", False),
            ("src/a.py", "src/**/*.py", True),
            ("src/nested/a.py", "src/**/*.py", True),
            ("a.py", "**/*.py", True),
            ("src/file1.py", "src/file[12].?y", True),
            ("src/file3.py", "src/file[12].?y", False),
            ("Src/a.py", "src/**", False),
        ):
            with self.subTest(path=path, rule=rule):
                self.assertEqual(Pipeline._task_path_matches(path, rule), expected)

    def test_scope_violation_blocks_auto_commit_and_can_retry_pending_fix(self) -> None:
        for mode in ExecutionWorkspaceMode:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                pipeline, state = self._scope_test_run(root, mode=mode)

                def violate(_state, task, _agent, _prompt, _log, _action):
                    worktree = Path(task.worktree)
                    (worktree / "result.txt").write_text("allowed", encoding="utf-8")
                    (worktree / "outside.txt").write_text("outside", encoding="utf-8")
                    return "done"

                with patch.object(pipeline, "_invoke_agent", side_effect=violate):
                    failed = pipeline.execute(state.id)
                task = failed.tasks[0]
                worktree = Path(task.worktree)
                baseline = task.started_commit
                self.assertEqual(failed.stage, Stage.FAILED)
                self.assertEqual(task.failed_action, TaskAction.EXECUTE)
                self.assertIn("outside expected_paths: 'outside.txt'", task.error)
                self.assertEqual(pipeline.git.head(worktree), baseline)
                self.assertTrue((worktree / "outside.txt").exists())

                def repair(*_args):
                    (worktree / "outside.txt").unlink()
                    return "fixed"

                with patch.object(pipeline, "_invoke_agent", side_effect=repair):
                    completed = pipeline.retry_task(state.id, task.id)
                self.assertEqual(completed.stage, Stage.READY_TO_MERGE)
                self.assertEqual(completed.tasks[0].started_commit, baseline)
                self.assertNotEqual(pipeline.git.head(worktree), baseline)

    def test_scope_checks_agent_commits_and_preserves_retry_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory), auto_commit=False)
            state.tasks[0].expected_paths = ["**"]
            state.tasks[0].forbidden_paths = ["forbidden.txt"]
            pipeline.store.save(state)

            def commit_violation(_state, task, *_args):
                worktree = Path(task.worktree)
                (worktree / "forbidden.txt").write_text("bad", encoding="utf-8")
                git(worktree, "add", ".")
                git(worktree, "commit", "-m", "agent commit")
                return "done"

            with patch.object(pipeline, "_invoke_agent", side_effect=commit_violation):
                failed = pipeline.execute(state.id)
            task = failed.tasks[0]
            baseline = task.started_commit
            worktree = Path(task.worktree)
            committed_head = pipeline.git.head(worktree)
            self.assertNotEqual(committed_head, baseline)
            self.assertIn("forbidden path", task.error)
            with patch.object(pipeline, "_invoke_agent", return_value="done"):
                retried = pipeline.retry_task(state.id, task.id)
            self.assertEqual(retried.stage, Stage.FAILED)
            self.assertEqual(retried.tasks[0].started_commit, baseline)
            self.assertEqual(pipeline.git.head(worktree), committed_head)
            self.assertIn("forbidden path", retried.tasks[0].error)

    def test_scope_retry_excludes_later_completed_task_commit_but_checks_pending_test_edit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state = pipeline.execute(state.id, manual=True)
            task = state.tasks[0]
            worktree = Path(task.worktree)
            initial_head = task.started_commit
            test_path = "tests/ExistingTests.cs"
            test_file = worktree / test_path
            test_file.parent.mkdir(parents=True)
            test_file.write_text("Assert.True(true);\n", encoding="utf-8")
            git(worktree, "add", test_path)
            git(worktree, "commit", "-m", "earlier task result")
            earlier_result = pipeline.git.head(worktree)

            task.started_commit = earlier_result
            task.status = TaskStatus.FAILED
            task.failed_action = TaskAction.EXECUTE
            task.action_results.append(TaskActionResult(
                action=TaskAction.EXECUTE.value, status="succeeded",
                baseline_commit=initial_head, result_commit=earlier_result,
            ))
            other_path = "src/Other.cs"
            other_file = worktree / other_path
            other_file.parent.mkdir(parents=True)
            other_file.write_text("class Other {}\n", encoding="utf-8")
            git(worktree, "add", other_path)
            git(worktree, "commit", "-m", "completed other task")
            completed_head = pipeline.git.head(worktree)
            state.tasks.append(WorkTask(
                id="other", title="Other", capabilities=["general"], status=TaskStatus.COMPLETED,
                agent_id="worker", provider_id=pipeline.agents["worker"].provider_id,
                worktree=str(worktree), started_commit=earlier_result, completed_commit=completed_head,
                expected_paths=[other_path],
            ))
            test_file.write_text("Assert.True(false);\n", encoding="utf-8")
            state.fail_step(RunStep.AGENT_EXECUTION, "previous task failure")

            task.expected_paths = ["result.txt"]
            pipeline._record_task_start_commit(task)
            self.assertEqual(task.started_commit, completed_head)
            with self.assertRaisesRegex(PipelineError, "scope violation") as caught:
                pipeline._validate_task_change_scope(task)
            self.assertIn(f"baseline={completed_head}", str(caught.exception))
            self.assertIn(f"checked_paths=['{test_path}']", str(caught.exception))
            self.assertNotIn(other_path, str(caught.exception))

            task.expected_paths = [test_path]
            pipeline.store.save(state)
            with patch.object(pipeline, "_invoke_agent", return_value="done"):
                completed = pipeline.retry_task(state.id, task.id)
            self.assertEqual(completed.stage, Stage.READY_TO_MERGE)
            self.assertEqual(completed.tasks[0].started_commit, completed_head)
            self.assertEqual(completed.tasks[0].action_results[-2].changed_paths, [test_path])
            self.assertEqual(pipeline.git.task_changed_paths(worktree, completed_head), [test_path])

    def _scope_with_later_completed_task(self, root: Path, *, own_path: str = "") -> tuple[Pipeline, RunState, str]:
        pipeline, state = self._scope_test_run(root)
        state = pipeline.execute(state.id, manual=True)
        task = state.tasks[0]
        worktree = Path(task.worktree)
        baseline = task.started_commit
        task.status = TaskStatus.FAILED
        task.failed_action = TaskAction.EXECUTE
        task.action_results.append(TaskActionResult(action="execute", status="failed", baseline_commit=baseline))
        foreign_paths = ["src/Contracts.cs", "src/Service.cs", "src/Store.cs", "src/SqliteStore.cs",
                         "tests/Infrastructure/ContractsTests.cs", "tests/Infrastructure/SnapshotTests.cs"]
        if own_path:
            file = worktree / own_path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("own prior change\n", encoding="utf-8")
            git(worktree, "add", own_path)
            git(worktree, "commit", "-m", "current task prior commit")
            task.action_results.append(TaskActionResult(
                action="execute", status="failed", baseline_commit=baseline, result_commit=pipeline.git.head(worktree)
            ))
        foreign_baseline = pipeline.git.head(worktree)
        for name in foreign_paths:
            file = worktree / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("completed prerequisite\n", encoding="utf-8")
        git(worktree, "add", *foreign_paths)
        git(worktree, "commit", "-m", "completed prerequisite contract")
        completed = pipeline.git.head(worktree)
        state.tasks.append(WorkTask(
            id="completed-prerequisite", title="Completed prerequisite", capabilities=["general"],
            agent_id="worker", provider_id=task.provider_id, status=TaskStatus.COMPLETED, readiness=TaskReadiness.DONE,
            branch=task.branch, worktree=task.worktree, started_commit=foreign_baseline, completed_commit=completed,
            expected_paths=foreign_paths, action_results=[TaskActionResult(
                action="execute", status="succeeded", baseline_commit=foreign_baseline, result_commit=completed,
                changed_paths=foreign_paths,
            )],
        ))
        state.fail_step(RunStep.AGENT_EXECUTION, "previous incomplete attempt")
        pipeline.store.save(state)
        return pipeline, state, completed

    def test_scope_missing_result_then_completed_prerequisite_does_not_block_ui_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state, prerequisite_commit = self._scope_with_later_completed_task(Path(directory))
            task = state.tasks[0]
            baseline = task.started_commit
            preserved = deepcopy(state.tasks[1])
            (Path(task.worktree) / "result.txt").write_text("UI change\n", encoding="utf-8")
            with patch.object(pipeline, "_invoke_agent", return_value="done"):
                completed = pipeline.retry_task(state.id, task.id)
            self.assertEqual(completed.stage, Stage.READY_TO_MERGE)
            self.assertEqual(completed.tasks[0].started_commit, baseline)
            self.assertEqual(completed.tasks[1], preserved)
            self.assertEqual(completed.tasks[0].action_results[-1].changed_paths, ["result.txt"])
            records = [json.loads(line) for line in (pipeline.store.run_dir(state.id) / "logs" / f"{task.id}-scope.jsonl").read_text().splitlines()]
            self.assertTrue(records)
            for record in records:
                self.assertEqual(record["status"], "passed")
                self.assertEqual(record["baseline"], baseline)
                self.assertEqual(record["expected_paths"], ["result.txt"])
                self.assertEqual(record["checked_paths"], ["result.txt"])
                self.assertEqual(record["excluded_completed_commits"], {prerequisite_commit: ["completed-prerequisite"]})

    def test_scope_completed_commit_exclusion_cannot_hide_owned_violation_on_the_same_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state, prerequisite_commit = self._scope_with_later_completed_task(Path(directory), own_path="src/Contracts.cs")
            task = state.tasks[0]
            baseline = task.started_commit
            with self.assertRaisesRegex(PipelineError, "change scope violation") as caught:
                pipeline._validate_task_change_scope(task, state)
            self.assertIn("outside expected_paths: 'src/Contracts.cs'", str(caught.exception))
            self.assertIn(f"excluded_completed_commits=['{prerequisite_commit}']", str(caught.exception))
            self.assertIn("expected_paths=['result.txt']", str(caught.exception))
            self.assertEqual(task.started_commit, baseline)
            task.expected_paths.append("src/Contracts.cs")
            self.assertEqual(pipeline._validate_task_change_scope(task, state), ["src/Contracts.cs"])

    def test_scope_unproven_or_failed_or_foreign_completion_never_exempts_paths(self) -> None:
        for mode in ("failed_task", "failed_action", "missing_baseline", "foreign_worktree", "owned_overlap", "unknown_commit"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                pipeline, state, prerequisite_commit = self._scope_with_later_completed_task(Path(directory))
                task, other = state.tasks
                if mode == "failed_task":
                    other.status = TaskStatus.FAILED
                elif mode == "failed_action":
                    other.action_results[0].status = "failed"
                elif mode == "missing_baseline":
                    other.action_results[0].baseline_commit = ""
                elif mode == "foreign_worktree":
                    other.worktree = str(Path(directory) / "unrelated")
                elif mode == "owned_overlap":
                    task.action_results.append(TaskActionResult(
                        action="execute", status="failed", baseline_commit=task.started_commit, result_commit=prerequisite_commit
                    ))
                else:
                    file = Path(task.worktree) / "unknown.txt"
                    file.write_text("unattributed commit\n", encoding="utf-8")
                    git(Path(task.worktree), "add", file.name)
                    git(Path(task.worktree), "commit", "-m", "unrecorded change")
                with self.assertRaisesRegex(PipelineError, "change scope violation") as caught:
                    pipeline._validate_task_change_scope(task, state)
                self.assertIn("unknown.txt" if mode == "unknown_commit" else "outside expected_paths: 'src/Contracts.cs'", str(caught.exception))

    def test_replanned_scope_matches_saved_paths_prepared_prompt_and_checker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state, _ = self._scope_with_later_completed_task(Path(directory))
            task = state.tasks[0]
            browser_file = Path(task.worktree) / "tests/browser/visible.cjs"
            browser_file.parent.mkdir(parents=True)
            browser_file.write_text("mock browser regression\n", encoding="utf-8")
            with self.assertRaisesRegex(PipelineError, "outside expected_paths"):
                pipeline._validate_task_change_scope(task, state)
            proposals = deepcopy(state.tasks)
            proposals[0].expected_paths.append("tests/browser/**")
            with patch.object(pipeline, "_build_plan", return_value=Plan(summary="updated", server_work=False, tasks=proposals)):
                pipeline._apply_pending_task_changes(state)
            saved = pipeline.store.load(state.id)
            self.assertEqual(saved.tasks[0].expected_paths, ["result.txt", "tests/browser/**"])
            self.assertIn("- tests/browser/**", Path(saved.tasks[0].prompt_path).read_text(encoding="utf-8"))
            observed = []

            def invoke(_state: RunState, current: WorkTask, _agent: AgentConfig, prompt: str, *_args: object) -> str:
                observed.append((list(current.expected_paths), prompt))
                return "done"

            with patch.object(pipeline, "_invoke_agent", side_effect=invoke):
                completed = pipeline.retry_task(state.id, task.id)
            self.assertEqual(completed.stage, Stage.READY_TO_MERGE)
            self.assertEqual(observed[0][0], saved.tasks[0].expected_paths)
            self.assertIn("- tests/browser/**", observed[0][1])
            records = [json.loads(line) for line in (pipeline.store.run_dir(state.id) / "logs" / f"{task.id}-scope.jsonl").read_text().splitlines()]
            self.assertEqual(records[-1]["expected_paths"], saved.tasks[0].expected_paths)
            self.assertEqual(records[-1]["plan_revision"], saved.plan_revision)
            self.assertEqual(records[-1]["checked_paths"], ["tests/browser/visible.cjs"])

    def test_scope_completed_action_range_keeps_later_own_change_and_lookup_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state, prerequisite_commit = self._scope_with_later_completed_task(Path(directory))
            task, other = state.tasks
            worktree = Path(task.worktree)
            (worktree / "src/Second.cs").write_text("second prerequisite commit\n", encoding="utf-8")
            git(worktree, "add", "src/Second.cs")
            git(worktree, "commit", "-m", "complete prerequisite range")
            other.completed_commit = pipeline.git.head(worktree)
            other.action_results[0].result_commit = other.completed_commit
            self.assertEqual(pipeline._validate_task_change_scope(task, state), [])
            own_baseline = other.completed_commit
            (worktree / "src/Contracts.cs").write_text("current task later change\n", encoding="utf-8")
            git(worktree, "add", "src/Contracts.cs")
            git(worktree, "commit", "-m", "later owned change")
            task.action_results.append(TaskActionResult(
                action="revise", status="failed", baseline_commit=own_baseline, result_commit=pipeline.git.head(worktree)
            ))
            with self.assertRaisesRegex(PipelineError, "outside expected_paths: 'src/Contracts.cs'"):
                pipeline._validate_task_change_scope(task, state)
            log = pipeline.store.run_dir(state.id) / "logs" / f"{task.id}-scope.jsonl"
            failed = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(failed["checked_paths"], ["src/Contracts.cs"])
            self.assertEqual(set(failed["excluded_completed_commits"]), {prerequisite_commit, other.completed_commit})
            with patch.object(pipeline.git, "commit_ids_between", side_effect=GitError("cannot inspect history")):
                with self.assertRaisesRegex(GitError, "cannot inspect history"):
                    pipeline._validate_task_change_scope(task, state)
            unavailable = json.loads(log.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(unavailable["status"], "lookup_failed")
            self.assertEqual(unavailable["expected_paths"], task.expected_paths)
            self.assertNotIn("checked_paths", unavailable)

    def test_scope_manual_violation_preserves_waiting_and_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            waiting = pipeline.execute(state.id, manual=True)
            task = waiting.tasks[0]
            worktree = Path(task.worktree)
            (worktree / "outside.txt").write_text("outside", encoding="utf-8")
            (worktree / "result.txt").write_text("allowed", encoding="utf-8")
            with self.assertRaisesRegex(PipelineError, "scope violation"):
                pipeline.complete_task(state.id, task.id)
            blocked = pipeline.status(state.id)
            self.assertEqual(blocked.stage, Stage.EXECUTING)
            self.assertEqual(blocked.tasks[0].status, TaskStatus.WAITING)
            self.assertIn("outside.txt", blocked.tasks[0].error)
            self.assertEqual(pipeline.git.head(worktree), task.started_commit)
            (worktree / "outside.txt").unlink()
            complete = pipeline.complete_task(state.id, task.id)
            self.assertEqual(complete.stage, Stage.READY_TO_MERGE)
            self.assertEqual(complete.tasks[0].error, "")

    def test_scope_missing_legacy_baseline_blocks_manual_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            waiting = pipeline.execute(state.id, manual=True)
            task = waiting.tasks[0]
            baseline = task.started_commit
            task.started_commit = ""
            pipeline.store.save(waiting)
            (Path(task.worktree) / "result.txt").write_text("allowed", encoding="utf-8")
            with self.assertRaisesRegex(PipelineError, "no original scope baseline"):
                pipeline.complete_task(state.id, task.id)
            self.assertEqual(pipeline.git.head(Path(task.worktree)), baseline)

    def test_scope_verify_retry_rejects_changes_without_rerunning_worker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline, state = self._scope_test_run(root)
            verify_script = root / "verify.py"
            verify_script.write_text("raise SystemExit(1)\n", encoding="utf-8")
            state.tasks[0].verify_commands = [[sys.executable, str(verify_script)]]
            pipeline.store.save(state)

            def implement(_state, task, *_args):
                result = Path(task.worktree) / "result.txt"
                result.write_text((result.read_text(encoding="utf-8") if result.exists() else "") + "allowed", encoding="utf-8")
                return "done"

            with patch.object(pipeline, "_invoke_agent", side_effect=implement) as worker:
                failed = pipeline.execute(state.id)
                task = failed.tasks[0]
                baseline = task.started_commit
                self.assertEqual(task.failed_action, TaskAction.VERIFY)
                self.assertEqual(worker.call_count, 4)
                verify_script.write_text("from pathlib import Path\nPath('outside.txt').write_text('outside')\n", encoding="utf-8")
                rejected = pipeline.retry_task(state.id, task.id)
                self.assertEqual(rejected.stage, Stage.FAILED)
                self.assertEqual(rejected.tasks[0].failed_action, TaskAction.VERIFY)
                self.assertIn("outside.txt", rejected.tasks[0].error)
                self.assertEqual(worker.call_count, 4)
                (Path(task.worktree) / "outside.txt").unlink()
                verify_script.write_text("pass\n", encoding="utf-8")
                complete = pipeline.retry_task(state.id, task.id)
                self.assertEqual(complete.stage, Stage.READY_TO_MERGE)
                self.assertEqual(complete.tasks[0].started_commit, baseline)
                self.assertEqual(worker.call_count, 4)

    def test_scope_revision_cannot_commit_forbidden_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            pipeline.agents["reviewer"] = replace(pipeline.agents["reviewer"], provider_id="local-review")
            task = state.tasks[0]
            task.reviewer_agent_id = "reviewer"
            task.reviewer_provider_id = "local-review"
            pipeline.store.save(state)

            def agent(_state, task, _agent, _prompt, _log, action):
                if action == TaskAction.REVIEW:
                    return 'AI_REVIEW_RESULT: {"verdict":"changes_requested","summary":"revise","findings":["fix implementation"]}'
                name = "result.txt" if action == TaskAction.EXECUTE else "outside.txt"
                (Path(task.worktree) / name).write_text("content", encoding="utf-8")
                return "done"

            with patch.object(pipeline, "_invoke_agent", side_effect=agent):
                failed = pipeline.execute(state.id)
            task = failed.tasks[0]
            self.assertEqual(task.failed_action, TaskAction.REVISE)
            self.assertIn("outside.txt", task.error)
            self.assertEqual(len(pipeline.git.commit_subjects_since(Path(task.worktree), task.started_commit)), 1)

    def test_scope_excludes_dependency_commits_in_both_workspace_modes(self) -> None:
        for mode in ExecutionWorkspaceMode:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                pipeline, state = self._scope_test_run(Path(directory), mode=mode)
                first = state.tasks[0]
                first.expected_paths = ["first.txt"]
                second = WorkTask(
                    id="second",
                    title="Second",
                    capabilities=["general"],
                    dependencies=[first.id],
                    expected_paths=["second.txt"],
                    forbidden_paths=["first.txt"],
                    agent_id=first.agent_id,
                    provider_id=first.provider_id,
                )
                second.started_commit = pipeline.git.head(pipeline.config.project.repo)
                state.tasks.append(second)
                pipeline.store.save(state)

                def implement(_state, task, *_args):
                    worktree = Path(task.worktree)
                    if task.id == "second":
                        self.assertTrue((worktree / "first.txt").exists())
                    name = "second.txt" if task.id == "second" else "first.txt"
                    (worktree / name).write_text("done", encoding="utf-8")
                    return "done"

                with patch.object(pipeline, "_invoke_agent", side_effect=implement):
                    complete = pipeline.execute(state.id)
                self.assertEqual(complete.stage, Stage.READY_TO_MERGE, [(task.id, task.error) for task in complete.tasks])
                self.assertTrue(all(task.status == TaskStatus.COMPLETED for task in complete.tasks))
                self.assertNotEqual(complete.tasks[0].started_commit, complete.tasks[1].started_commit)

    def _scope_test_run(
        self, root: Path, *, mode: ExecutionWorkspaceMode = ExecutionWorkspaceMode.SHARED, auto_commit: bool = True, max_tasks: int = 1
    ) -> tuple[Pipeline, RunState]:
        repo = self._repository(root)
        spec = root / "plan.md"
        spec.write_text("## 작업\n\n- [general] 결과 생성\n", encoding="utf-8")
        pipeline = Pipeline(
            Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(auto_commit=auto_commit),
                agents=(
                    AgentConfig("worker", ("general",), (sys.executable, "-c", "pass"), max_tasks),
                    AgentConfig("reviewer", ("review",), (sys.executable, "-c", "pass"), 1),
                ),
            )
        )
        state = pipeline.start(spec)
        state.workspace_mode = mode
        state.tasks[0].expected_paths = ["result.txt"]
        pipeline.store.save(state)
        return pipeline, pipeline.confirm_plan(state.id)

    @staticmethod
    def _automatic_repair_check() -> list[str]:
        return [sys.executable, "-c", "from pathlib import Path; import sys; v=Path('result.txt').read_text(); print(v); sys.exit(v!='fixed')"]

    def test_automatic_task_repair_preserves_contract_and_failed_evidence_in_both_workspaces(self) -> None:
        for mode in (ExecutionWorkspaceMode.SHARED, ExecutionWorkspaceMode.ISOLATED):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                pipeline, state = self._scope_test_run(Path(directory), mode=mode)
                task = state.tasks[0]
                task.verify_commands = [self._automatic_repair_check()]
                contract = deepcopy(pipeline._planning_preview_task_fields(task))
                pipeline.store.save(state)
                prompts = []
                baselines = []

                def implement(_state, current, _agent, prompt, *_args):
                    prompts.append(prompt)
                    baselines.append(current.started_commit)
                    value = "broken" if len(prompts) == 1 else "fixed"
                    (Path(current.worktree) / "result.txt").write_text(value, encoding="utf-8")
                    return value

                with patch.object(pipeline, "_invoke_agent", side_effect=implement):
                    completed = pipeline.execute(state.id)
                task = completed.tasks[0]
                self.assertEqual(completed.stage, Stage.READY_TO_MERGE)
                self.assertEqual(len(prompts), 2)
                self.assertIn("Automatic correction of this Task (1/3)", prompts[1])
                self.assertIn("broken", prompts[1])
                self.assertIn("untrusted diagnostic data", prompts[1])
                self.assertEqual(baselines[0], baselines[1])
                self.assertEqual(pipeline._planning_preview_task_fields(task), contract)
                self.assertEqual([item.status for item in task.action_results], ["succeeded", "failed", "succeeded", "succeeded"])
                failed = task.action_results[1]
                log = pipeline.store.run_dir(state.id) / "logs" / f"{task.id}-verify-{failed.attempt_id}.log"
                self.assertIn("broken", log.read_text(encoding="utf-8"))
                self.assertIn("exit code: 1", log.read_text(encoding="utf-8"))
                self.assertTrue(Path(task.log_path).name.startswith(f"{task.id}-auto-repair-1-"))
                self.assertTrue(any(event.kind == "task_repair" for event in completed.events))

    def test_automatic_task_repair_reviews_the_changed_commit_again(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            reviewer = replace(pipeline.agents["reviewer"], provider_id="review-local")
            pipeline.agents[reviewer.id] = reviewer
            pipeline.config = replace(pipeline.config, agents=tuple(
                reviewer if agent.id == reviewer.id else agent for agent in pipeline.config.agents
            ))
            task = state.tasks[0]
            task.verify_commands = [self._automatic_repair_check()]
            task.reviewer_agent_id = "reviewer"
            task.reviewer_provider_id = pipeline.agents["reviewer"].provider_id
            pipeline.store.save(state)
            actions = []

            def invoke(_state, current, _agent, _prompt, _log, action):
                actions.append(action)
                if action == TaskAction.REVIEW:
                    return "AI_REVIEW_RESULT: " + json.dumps({"verdict": "approved", "summary": "checked", "findings": []})
                value = "broken" if actions.count(TaskAction.EXECUTE) == 1 else "fixed"
                (Path(current.worktree) / "result.txt").write_text(value, encoding="utf-8")
                return value

            with patch.object(pipeline, "_invoke_agent", side_effect=invoke):
                completed = pipeline.execute(state.id)
            self.assertEqual(completed.stage, Stage.READY_TO_MERGE, completed.tasks[0].error)
            self.assertEqual(actions, [TaskAction.EXECUTE, TaskAction.REVIEW, TaskAction.EXECUTE, TaskAction.REVIEW])
            task = completed.tasks[0]
            self.assertEqual(task.last_review_commit, task.completed_commit)
            reviews = [item for item in task.action_results if item.action == "review"]
            self.assertEqual(len(reviews), 2)
            self.assertNotEqual(reviews[0].baseline_commit, reviews[1].baseline_commit)
            archived = list((pipeline.store.run_dir(state.id) / "logs").glob(f"{task.id}-auto-repair-1-*-previous-review-1.json"))
            self.assertEqual(len(archived), 1)
            self.assertEqual(json.loads(archived[0].read_text(encoding="utf-8"))["verdict"], "approved")

    def test_chat_repair_reaches_worker_after_verify_failure_or_stop_and_continues_only_after_success(self) -> None:
        for fail, stopped in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(fail=fail, stopped=stopped), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                repo = self._repository(root)
                spec = root / "plan.md"
                spec.write_text("## 작업\n\n- [general] 첫 결과\n- [general] 후속 결과\n", encoding="utf-8")
                pipeline = Pipeline(Config(
                    path=root / "config.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(auto_commit=True),
                    agents=(AgentConfig("worker", ("general",), (sys.executable, "-c", "pass"), 1),),
                ))
                state = pipeline.start(spec)
                state.workspace_mode = ExecutionWorkspaceMode.SHARED
                first, second = state.tasks
                first.expected_paths = ["result.txt"]
                first.verify_commands = [self._automatic_repair_check()]
                second.dependencies = [first.id]
                second.expected_paths = ["next.txt"]
                second.verify_commands = [[sys.executable, "-c", "from pathlib import Path; assert Path('next.txt').read_text()=='done'"]]
                pipeline.store.save(state)
                pipeline.confirm_plan(state.id)
                if stopped:
                    def interrupt(current, task, *_args):
                        (Path(task.worktree) / "result.txt").write_text("preserved partial work", encoding="utf-8")
                        control = pipeline.store.load_execution_control(current.id)
                        receipt = pipeline.request_stop(
                            current.id, request_id=str(uuid.uuid4()), execution_id=control.execution_id, scope="task",
                            task_id=task.id, attempt_id=task.last_attempt_id, invocation_id=task.active_invocation_id,
                        )
                        self.assertEqual(receipt.phase, "stopping")
                        raise ExecutionStopped("user stopped", request_id=receipt.request_id)

                    with patch.object(pipeline, "_invoke_agent", side_effect=interrupt):
                        state = pipeline.execute(state.id)
                    first, second = state.tasks
                    self.assertEqual(first.status, TaskStatus.STOPPED)
                    self.assertEqual(pipeline.store.load_execution_control(state.id).phase, "stopped")
                    self.assertEqual(first.action_results[-1].status, "interrupted")
                else:
                    state = pipeline.execute(state.id, manual=True)
                    first, second = state.tasks
                    first.status = TaskStatus.FAILED
                    first.failed_action = TaskAction.VERIFY
                    first.error = "test timed out"
                    first.active_action = None
                    state.fail_step(RunStep.AGENT_EXECUTION, "test timed out")
                pipeline._append_planning_assistant_message(state, "멈춘 테스트의 원인을 찾아 수정하고 전체 검증을 유지합니다.")
                pipeline.store.save(state)
                calls = []

                def invoke(_state, task, _agent, prompt, *_args):
                    calls.append(task.id)
                    if task.id == first.id:
                        self.assertIn("User-confirmed revision", prompt)
                        self.assertIn("멈춘 테스트", prompt)
                        if stopped:
                            self.assertEqual((Path(task.worktree) / "result.txt").read_text(encoding="utf-8"), "preserved partial work")
                        if fail:
                            raise PipelineError("repair blocked")
                        (Path(task.worktree) / "result.txt").write_text("fixed", encoding="utf-8")
                    else:
                        self.assertEqual(_state.tasks[0].status, TaskStatus.COMPLETED)
                        (Path(task.worktree) / "next.txt").write_text("done", encoding="utf-8")
                    return "implemented"

                context = pipeline.task_retry_context(state.id, first.id)
                with patch.object(pipeline, "_invoke_agent", side_effect=invoke):
                    result = pipeline.repair_task_from_chat(
                        state.id, first.id, request_id=str(uuid.uuid4()), message="고쳐서 계속해줘",
                        fingerprint=context["fingerprint"], conversation_revision=state.planning_conversation_revision,
                    )
                self.assertEqual(calls, [first.id] if fail else [first.id, second.id])
                self.assertEqual(result.stage, Stage.FAILED if fail else Stage.READY_TO_MERGE)
                self.assertEqual(result.tasks[1].status, TaskStatus.PENDING if fail else TaskStatus.COMPLETED)

    def test_third_automatic_task_repair_verifies_and_continues_the_dependent_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] 첫 결과\n- [general] 후속 결과\n", encoding="utf-8")
            pipeline = Pipeline(Config(
                path=root / "orchestrator.toml", project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(auto_commit=True),
                agents=(AgentConfig("worker", ("general",), (sys.executable, "-c", "pass"), 1),),
            ))
            state = pipeline.start(spec)
            state.workspace_mode = ExecutionWorkspaceMode.SHARED
            first, second = state.tasks
            first.expected_paths = ["result.txt"]
            first.verify_commands = [self._automatic_repair_check()]
            second.dependencies = [first.id]
            second.expected_paths = ["next.txt"]
            second.verify_commands = [[sys.executable, "-c", "from pathlib import Path; assert Path('next.txt').read_text()=='done'"]]
            pipeline.store.save(state)
            state = pipeline.confirm_plan(state.id)
            calls = []
            prompts = []

            def invoke(_state, current, _agent, prompt, *_args):
                calls.append(current.id)
                if current.id == first.id:
                    prompts.append(prompt)
                    value = f"broken-{len(prompts)}" if len(prompts) < 4 else "fixed"
                    (Path(current.worktree) / "result.txt").write_text(value, encoding="utf-8")
                else:
                    self.assertEqual(_state.tasks[0].status, TaskStatus.COMPLETED)
                    self.assertEqual(_state.tasks[0].action_results[-1].status, "succeeded")
                    self.assertEqual((Path(current.worktree) / "result.txt").read_text(encoding="utf-8"), "fixed")
                    (Path(current.worktree) / "next.txt").write_text("done", encoding="utf-8")
                return "implemented"

            with patch.object(pipeline, "_invoke_agent", side_effect=invoke):
                completed = pipeline.execute(state.id)
            self.assertEqual(completed.stage, Stage.READY_TO_MERGE, [task.error for task in completed.tasks])
            self.assertEqual(calls, [first.id] * 4 + [second.id])
            self.assertIn("Automatic correction of this Task (3/3)", prompts[-1])
            self.assertTrue(all(task.status == TaskStatus.COMPLETED for task in completed.tasks))

    def test_automatic_task_repair_is_bounded_and_preserves_repeated_failure(self) -> None:
        for repeated in (False, True):
            with self.subTest(repeated=repeated), tempfile.TemporaryDirectory() as directory:
                pipeline, state = self._scope_test_run(Path(directory))
                state.tasks[0].verify_commands = [[sys.executable, "-c", "print('same failure'); raise SystemExit(1)"]
                                                  if repeated else self._automatic_repair_check()]
                pipeline.store.save(state)
                calls = []

                def invoke(_state, current, _agent, prompt, *_args):
                    calls.append(prompt)
                    (Path(current.worktree) / "result.txt").write_text(f"broken-{len(calls)}", encoding="utf-8")
                    return "attempted correction"

                with patch.object(pipeline, "_invoke_agent", side_effect=invoke):
                    failed = pipeline.execute(state.id)
                self.assertEqual(failed.stage, Stage.FAILED)
                self.assertEqual(len(calls), 4)
                self.assertEqual(failed.tasks[0].failed_action, TaskAction.VERIFY)
                self.assertIn("자동 복구 3회", failed.tasks[0].error)
                self.assertIn("verification command failed", failed.tasks[0].error)
                self.assertEqual(failed.tasks[0].completed_commit, "")
                self.assertEqual(sum(item.status == "failed" for item in failed.tasks[0].action_results), len(calls))
                self.assertEqual(calls[-1].count("Automatic correction of this Task"), 1)
                if repeated:
                    self.assertIn("test a different cause or corrective approach", calls[-1])

    def test_automatic_task_repair_preserves_completed_prerequisite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state, _ = self._scope_with_later_completed_task(Path(directory))
            preserved = deepcopy(state.tasks[1])
            state.tasks[0].verify_commands = [self._automatic_repair_check()]
            pipeline.store.save(state)
            calls = []

            def invoke(_state, current, *_args):
                calls.append(current.id)
                (Path(current.worktree) / "result.txt").write_text("broken" if len(calls) == 1 else "fixed", encoding="utf-8")
                return "corrected"

            with patch.object(pipeline, "_invoke_agent", side_effect=invoke):
                completed = pipeline.retry_task(state.id, state.tasks[0].id)
            self.assertEqual(completed.stage, Stage.READY_TO_MERGE)
            self.assertEqual(completed.tasks[1], preserved)
            self.assertEqual(calls, [state.tasks[0].id] * 2)

    def test_automatic_task_repair_cannot_expand_scope_or_invent_a_commit(self) -> None:
        for correction in ("forbidden", "no_change"):
            with self.subTest(correction=correction), tempfile.TemporaryDirectory() as directory:
                pipeline, state = self._scope_test_run(Path(directory))
                state.tasks[0].verify_commands = [self._automatic_repair_check()]
                pipeline.store.save(state)
                calls = []

                def invoke(_state, current, *_args):
                    calls.append(current.id)
                    if len(calls) == 1:
                        (Path(current.worktree) / "result.txt").write_text("broken", encoding="utf-8")
                    elif correction == "forbidden":
                        (Path(current.worktree) / "outside.txt").write_text("not approved", encoding="utf-8")
                    return "scope change or human decision is required"

                with patch.object(pipeline, "_invoke_agent", side_effect=invoke):
                    failed = pipeline.execute(state.id)
                self.assertEqual(failed.stage, Stage.FAILED)
                self.assertEqual(len(calls), 2)
                self.assertEqual(failed.tasks[0].expected_paths, ["result.txt"])
                self.assertEqual(failed.tasks[0].failed_action, TaskAction.EXECUTE if correction == "forbidden" else TaskAction.VERIFY)
                self.assertIn("scope violation" if correction == "forbidden" else "같은 검증 실패", failed.tasks[0].error)
                self.assertEqual(failed.tasks[0].action_results[1].status, "failed")
                self.assertEqual(failed.tasks[0].completed_commit, "")
                if correction == "no_change":
                    worktree = Path(failed.tasks[0].worktree)
                    self.assertEqual(len(pipeline.git.commit_subjects_since(worktree, failed.tasks[0].started_commit)), 1)

    def test_automatic_task_repair_stops_when_only_failure_timing_changes_without_a_new_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state.tasks[0].verify_commands = [[sys.executable, "-c", "raise SystemExit(1)"]]
            pipeline.store.save(state)
            calls = []

            def invoke(_state, current, *_args):
                calls.append(current.id)
                if len(calls) == 1:
                    (Path(current.worktree) / "result.txt").write_text("implemented", encoding="utf-8")
                return "existing implementation needs no new commit"

            def check(command, *_args, **_kwargs):
                elapsed = len(calls)
                output = f"[xUnit.net 00:00:0{elapsed}.0] Test [FAIL]\nExpected: 1\nActual: 2\nTime Elapsed: 00:00:0{elapsed}"
                return subprocess.CompletedProcess(command, 1, output)

            with (patch.object(pipeline, "_invoke_agent", side_effect=invoke),
                  patch("ai_orchestrator.pipeline.run_command", side_effect=check)):
                failed = pipeline.execute(state.id)
            self.assertEqual(calls, [state.tasks[0].id] * 2)
            self.assertEqual(failed.stage, Stage.FAILED)
            self.assertIn("같은 검증 실패", failed.tasks[0].error)
            self.assertEqual(failed.tasks[0].completed_commit, "")

    def test_automatic_task_repair_does_not_rewrite_code_for_locked_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state.tasks[0].verify_commands = [["dotnet", "build", "Example.sln"]]
            pipeline.store.save(state)

            def invoke(_state, current, *_args):
                (Path(current.worktree) / "result.txt").write_text("implemented", encoding="utf-8")
                return "implemented"

            diagnostic = "error MSB3027: Could not copy output. The file is locked by: Example (1234)"
            diagnostic += "\n" + "additional build output\n" * 1000
            with patch.object(pipeline, "_invoke_agent", side_effect=invoke) as agent:
                with patch.object(pipeline, "_prepare_verification_command", side_effect=lambda command, *_args: command):
                    with patch("ai_orchestrator.pipeline.run_command", return_value=subprocess.CompletedProcess([], 1, diagnostic)):
                        failed = pipeline.execute(state.id)
            self.assertEqual(agent.call_count, 1)
            self.assertEqual(failed.stage, Stage.FAILED)
            self.assertIn("출력 파일이 사용 중", failed.tasks[0].error)

    def test_msbuild_output_access_detection_requires_build_diagnostic_and_generated_path(self) -> None:
        cases = (
            ("dotnet", "error MSB4018: System.UnauthorizedAccessException: Access to the path 'C:/work/obj/Manifest.json' is denied.", True),
            ("dotnet.exe", "warning MSB3101: Cannot write 'obj/Debug/cache': Access to the path 'obj/Debug/cache' is denied.", True),
            ("dotnet", "오류 MSB4018: 'bin\\Debug\\result.json' 경로에 대한 액세스가 거부되었습니다.", True),
            ("dotnet", "error MSB4018: System.NullReferenceException in C:/work/obj/Task.cs", False),
            ("dotnet", "Assert: UnauthorizedAccessException for C:/work/obj/data.json", False),
            ("dotnet", "error MSB4018: Access to the path 'src/source.cs' is denied.", False),
            ("python", "error MSB4018: Access to the path 'obj/Debug/cache' is denied.", False),
        )
        for executable, output, expected in cases:
            with self.subTest(executable=executable, output=output):
                self.assertEqual(Pipeline._verification_build_output_access_denied((executable, "build"), output), expected)

    def test_msbuild_output_access_failure_preserves_commit_and_retries_verification_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            task = state.tasks[0]
            task.verify_commands = [["dotnet", "build", "Example.sln"], ["dotnet", "test", "Example.sln"]]
            contract = deepcopy(pipeline._planning_preview_task_fields(task))
            pipeline.store.save(state)
            diagnostic = "error MSB4018: System.UnauthorizedAccessException: Access to the path 'C:/work/obj/Manifest.json' is denied."
            diagnostic += "\n" + "additional build output\n" * 1000

            def invoke(_state, current, *_args):
                (Path(current.worktree) / "result.txt").write_text("implemented", encoding="utf-8")
                return "existing implementation"

            with (
                patch("ai_orchestrator.pipeline.diagnose_dotnet", return_value=DotnetDiagnostic("dotnet", "SDK selected")),
                patch("ai_orchestrator.pipeline.run_command", return_value=subprocess.CompletedProcess([], 1, diagnostic)),
                patch.object(pipeline, "_invoke_agent", side_effect=invoke) as worker,
            ):
                failed = pipeline.execute(state.id)
            task = failed.tasks[0]
            implementation = task.action_results[0].result_commit
            self.assertEqual(worker.call_count, 1)
            self.assertEqual(failed.stage, Stage.FAILED)
            self.assertEqual(task.failed_action, TaskAction.VERIFY)
            self.assertIn("산출물 쓰기 접근이 거부", task.error)
            self.assertNotIn("produced no commit", task.error)
            self.assertEqual([item.action for item in task.action_results], ["execute", "verify", "verify"])
            self.assertIn("동일 환경의 검증을 반복하지 않고", task.error)
            self.assertEqual(pipeline.git.head(Path(task.worktree)), implementation)
            self.assertEqual(pipeline._planning_preview_task_fields(task), contract)
            archive = pipeline.store.run_dir(state.id) / "logs" / f"{task.id}-verify-{task.last_attempt_id}.log"
            self.assertIn("MSB4018", archive.read_text(encoding="utf-8"))

            with (
                patch("ai_orchestrator.pipeline.diagnose_dotnet", return_value=DotnetDiagnostic("dotnet", "SDK selected")),
                patch("ai_orchestrator.pipeline.run_command", return_value=subprocess.CompletedProcess([], 0, "verified")) as verification,
                patch.object(pipeline, "_invoke_agent") as worker,
            ):
                complete = pipeline.retry_task(state.id, task.id)
            worker.assert_not_called()
            self.assertEqual(verification.call_count, 2)
            self.assertEqual(complete.stage, Stage.READY_TO_MERGE)
            self.assertEqual(complete.tasks[0].completed_commit, implementation)
            self.assertEqual(complete.tasks[0].started_commit, task.started_commit)
            self.assertEqual(pipeline._planning_preview_task_fields(complete.tasks[0]), contract)

    def test_task_environment_recovery_automatically_verifies_without_another_worker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            task = state.tasks[0]
            task.verify_commands = [
                ["dotnet", "build", "Example.sln"],
                [sys.executable, "-c", "import os; assert os.environ['MSBUILDUSESERVER']=='1'; print('checked')"],
            ]
            contract = deepcopy(pipeline._planning_preview_task_fields(task))
            pipeline.store.save(state)
            diagnostic = "error MSB4018: Access to the path 'obj/Debug/Manifest.json' is denied."
            parent_environment = {"DOTNET_CLI_USE_MSBUILD_SERVER": "1", "MSBUILDUSESERVER": "1", "MSBUILDDISABLENODEREUSE": "0"}
            child_calls = Path(directory) / "child-calls.jsonl"
            fake_dotnet = Path(directory) / "fake_dotnet.py"
            fake_dotnet.write_text(
                "import os,sys,json\nfrom pathlib import Path\n"
                f"values={{key:os.environ.get(key) for key in {tuple(parent_environment)!r}}}\n"
                f"with Path({str(child_calls)!r}).open('a',encoding='utf-8') as log:\n"
                " log.write(json.dumps({'argv':sys.argv[1:],'env':values})+'\\n')\n"
                "ok=values['MSBUILDUSESERVER']=='0' and values['DOTNET_CLI_USE_MSBUILD_SERVER']=='0' "
                "and values['MSBUILDDISABLENODEREUSE']=='1'\n"
                f"print('verified' if ok else {diagnostic!r})\nsys.exit(0 if ok else 1)\n",
                encoding="utf-8",
            )

            def invoke(_state, current, *_args):
                (Path(current.worktree) / "result.txt").write_text("implemented", encoding="utf-8")
                return "implemented"

            def prepare(command, *_args):
                return (sys.executable, str(fake_dotnet), *command[1:]) if pipeline._is_dotnet_command(command) else command

            with (
                patch.dict(os.environ, parent_environment),
                patch.object(pipeline, "_prepare_verification_command", side_effect=prepare),
                patch("ai_orchestrator.pipeline.run_command", wraps=run_command) as verification,
                patch.object(pipeline, "_invoke_agent", side_effect=invoke) as worker,
            ):
                completed = pipeline.execute(state.id)
                self.assertEqual({key: os.environ[key] for key in parent_environment}, parent_environment)
            self.assertEqual(completed.stage, Stage.READY_TO_MERGE, completed.tasks[0].error)
            self.assertEqual(worker.call_count, 1)
            calls = [(tuple(item.args[0]), item.kwargs) for item in verification.call_args_list]
            self.assertEqual(len(calls), 3)
            child_records = [json.loads(line) for line in child_calls.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([record["argv"] for record in child_records], [task.verify_commands[0][1:]] * 2)
            self.assertEqual(child_records[0]["env"], parent_environment)
            self.assertIsNone(calls[0][1].get("environment_overrides"))
            self.assertEqual(calls[1][1]["environment_overrides"], {
                "DOTNET_CLI_USE_MSBUILD_SERVER": "0", "MSBUILDUSESERVER": "0", "MSBUILDDISABLENODEREUSE": "1",
            })
            self.assertEqual(child_records[1]["env"], calls[1][1]["environment_overrides"])
            self.assertIsNone(calls[2][1].get("environment_overrides"))
            task = completed.tasks[0]
            self.assertEqual(pipeline._planning_preview_task_fields(task), contract)
            self.assertEqual([item.status for item in task.action_results], ["succeeded", "failed", "succeeded"])
            self.assertEqual(task.completed_commit, task.action_results[0].result_commit)
            archive = pipeline.store.run_dir(state.id) / "logs" / f"{task.id}-verify-{task.action_results[1].attempt_id}.log"
            self.assertIn("MSB4018", archive.read_text(encoding="utf-8"))
            current_log = pipeline.store.run_dir(state.id) / "logs" / f"{task.id}-verify.log"
            self.assertIn("MSBUILDDISABLENODEREUSE", current_log.read_text(encoding="utf-8"))

    def test_task_environment_recovery_preserves_stop_and_rejects_mutation(self) -> None:
        for outcome in ("stop", "scope", "head"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                pipeline, state = self._scope_test_run(Path(directory))
                state.tasks[0].verify_commands = [["dotnet", "build", "Example.sln"]]
                pipeline.store.save(state)
                diagnostic = "error MSB4018: Access to the path 'obj/Debug/Manifest.json' is denied."
                calls = []

                def invoke(_state, current, *_args):
                    (Path(current.worktree) / "result.txt").write_text("implemented", encoding="utf-8")
                    return "implemented"

                def verify(command, cwd, **_options):
                    calls.append(tuple(command))
                    if len(calls) > 1:
                        raise ExecutionStopped("user stopped recovery")
                    if outcome == "scope":
                        (cwd / "outside.txt").write_text("preserve", encoding="utf-8")
                    elif outcome == "head":
                        git(cwd, "commit", "--allow-empty", "-m", "verification mutation")
                    return subprocess.CompletedProcess(command, 1, diagnostic)

                with (
                    patch("ai_orchestrator.pipeline.diagnose_dotnet", return_value=DotnetDiagnostic("dotnet", "SDK selected")),
                    patch("ai_orchestrator.pipeline.run_command", side_effect=verify),
                    patch.object(pipeline, "_invoke_agent", side_effect=invoke) as worker,
                ):
                    result = pipeline.execute(state.id)
                self.assertEqual(worker.call_count, 1)
                self.assertEqual(len(calls), 2 if outcome == "stop" else 1)
                task = result.tasks[0]
                self.assertEqual(task.completed_commit, "")
                self.assertEqual((Path(task.worktree) / "result.txt").read_text(encoding="utf-8"), "implemented")
                if outcome == "stop":
                    self.assertEqual(task.status, TaskStatus.STOPPED)
                    self.assertEqual(task.action_results[-1].status, "interrupted")
                else:
                    self.assertEqual(task.status, TaskStatus.FAILED)
                    self.assertIn("outside.txt" if outcome == "scope" else "HEAD", task.error)

    def test_scope_review_report_preserves_partial_work_and_blocks_commit_review_and_repeated_execution(self) -> None:
        from ai_orchestrator.task_scope_review import ERROR_MARKER, REPORT_MARKER, stored_scope_review

        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            response = REPORT_MARKER + ' {"reason":"추가 파일에 승인 정보를 연결해야 합니다.","paths":["adapter.txt"]}'

            def invoke(_state, task, _agent, prompt, _log, action):
                self.assertIn(REPORT_MARKER, prompt)
                self.assertEqual(action, TaskAction.EXECUTE)
                (Path(task.worktree) / "result.txt").write_text("partial", encoding="utf-8")
                return response

            with patch.object(pipeline, "_invoke_agent", side_effect=invoke) as worker, \
                    patch.object(pipeline.git, "commit_all") as commit, patch.object(pipeline, "_run_task_verification") as verify:
                failed = pipeline.execute(state.id)
            task = failed.tasks[0]
            self.assertEqual(failed.stage, Stage.FAILED)
            self.assertTrue(task.error.startswith(ERROR_MARKER), task.error)
            self.assertEqual(stored_scope_review(task.error).paths, ("adapter.txt",))
            self.assertEqual(task.action_results[-1].worker_response, response)
            self.assertEqual(task.action_results[-1].baseline_commit, task.action_results[-1].result_commit)
            self.assertEqual((Path(task.worktree) / "result.txt").read_text(), "partial")
            worker.assert_called_once()
            commit.assert_not_called()
            verify.assert_not_called()
            with patch.object(pipeline, "_invoke_agent") as repeated:
                with self.assertRaisesRegex(PipelineError, ERROR_MARKER):
                    pipeline.retry_task(state.id, task.id)
            repeated.assert_not_called()
            self.assertEqual(len(pipeline.store.load(state.id).tasks[0].action_results), 1)

            # The approved plan edit, not the report, grants the added path.
            failed.tasks[0].expected_paths.append("adapter.txt")
            pipeline.store.save(failed)

            def fixed(_state, current, _agent, _prompt, _log, action):
                if action == TaskAction.REVIEW:
                    return 'AI_REVIEW_RESULT: {"verdict":"approved","summary":"checked","findings":[]}'
                (Path(current.worktree) / "adapter.txt").write_text("fixed", encoding="utf-8")
                return "수정 완료"

            with patch.object(pipeline, "_invoke_agent", side_effect=fixed), patch.object(pipeline, "_run_task_verification") as verify:
                recovered = pipeline.retry_task(state.id, task.id)
            self.assertEqual(recovered.stage, Stage.READY_TO_MERGE, recovered.tasks[0].error)
            verify.assert_called_once()
            self.assertEqual(recovered.tasks[0].action_results[0].worker_response, response)

    def test_scope_review_during_auto_repair_preserves_the_existing_implementation_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            task = state.tasks[0]
            task.verify_commands = [self._automatic_repair_check()]
            pipeline.store.save(state)
            calls = []

            def invoke(_state, current, *_args):
                calls.append(current.id)
                if len(calls) == 1:
                    (Path(current.worktree) / "result.txt").write_text("implemented", encoding="utf-8")
                    return "구현 완료"
                return 'AI_TASK_SCOPE_REVIEW: {"reason":"추가 경로가 필요합니다.","paths":["adapter.txt"]}'

            with patch.object(pipeline, "_invoke_agent", side_effect=invoke), \
                    patch.object(pipeline.git, "commit_all", wraps=pipeline.git.commit_all) as commit:
                failed = pipeline.execute(state.id)
            task = failed.tasks[0]
            self.assertEqual(calls, [task.id, task.id])
            self.assertIn("task_scope_review_required:", task.error)
            self.assertNotIn("produced no commit", task.error)
            self.assertEqual([item.status for item in task.action_results], ["succeeded", "failed", "failed"])
            self.assertEqual(task.action_results[0].result_commit, pipeline.git.head(Path(task.worktree)))
            self.assertEqual(task.action_results[-1].baseline_commit, task.action_results[0].result_commit)
            self.assertEqual((Path(task.worktree) / "result.txt").read_text(), "implemented")
            commit.assert_called_once()

    def test_scope_question_without_changes_has_its_own_reason_but_scope_violations_still_win(self) -> None:
        for outcome in ("question", "violation"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                pipeline, state = self._scope_test_run(Path(directory))

                def invoke(_state, task, *_args):
                    if outcome == "violation":
                        (Path(task.worktree) / "outside.txt").write_text("forbidden", encoding="utf-8")
                    return "src/Adapter.cs가 허용 경로에 빠져 있습니다. 추가해도 될까요?"

                with patch.object(pipeline, "_invoke_agent", side_effect=invoke), patch.object(pipeline.git, "commit_all") as commit:
                    failed = pipeline.execute(state.id)
                expected = "task_scope_review_required:" if outcome == "question" else "change scope violation"
                self.assertIn(expected, failed.tasks[0].error)
                self.assertNotIn("produced no commit", failed.tasks[0].error)
                commit.assert_not_called()

    def test_task_recorded_implementation_reuses_commit_and_reviews_without_empty_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline, state = self._scope_test_run(root)
            reviewer = replace(pipeline.agents["reviewer"], provider_id="review-local")
            pipeline.agents[reviewer.id] = reviewer
            pipeline.config = replace(pipeline.config, agents=tuple(
                reviewer if agent.id == reviewer.id else agent for agent in pipeline.config.agents
            ))
            task = state.tasks[0]
            checker = root / "verify.py"
            checker.write_text(
                "from pathlib import Path\nimport sys\nassert Path('result.txt').read_text()=='implemented'\n"
                "marker=Path(sys.argv[1])\nfirst=not marker.exists()\nmarker.write_text('checked')\nsys.exit(1 if first else 0)\n",
                encoding="utf-8",
            )
            task.verify_commands = [[sys.executable, str(checker), str(root / "checked")]]
            task.reviewer_agent_id = reviewer.id
            task.reviewer_provider_id = reviewer.provider_id
            pipeline.store.save(state)
            actions = []

            def invoke(_state, current, _agent, _prompt, _log, action):
                actions.append(action)
                if action == TaskAction.REVIEW:
                    return 'AI_REVIEW_RESULT: {"verdict":"approved","summary":"checked","findings":[]}'
                if actions.count(TaskAction.EXECUTE) == 1:
                    (Path(current.worktree) / "result.txt").write_text("implemented", encoding="utf-8")
                return "existing implementation is unchanged"

            with patch.object(pipeline, "_invoke_agent", side_effect=invoke):
                completed = pipeline.execute(state.id)
            self.assertEqual(completed.stage, Stage.READY_TO_MERGE, completed.tasks[0].error)
            self.assertEqual(actions, [TaskAction.EXECUTE, TaskAction.REVIEW, TaskAction.EXECUTE, TaskAction.REVIEW])
            task = completed.tasks[0]
            implementations = [item for item in task.action_results if item.action == TaskAction.EXECUTE.value]
            self.assertEqual(implementations[1].baseline_commit, implementations[1].result_commit)
            self.assertEqual(task.completed_commit, implementations[0].result_commit)
            self.assertEqual(task.last_review_commit, task.completed_commit)
            self.assertEqual(task.action_results[-1].status, "succeeded")
            self.assertEqual(len(pipeline.git.commit_subjects_since(Path(task.worktree), task.started_commit)), 1)

    def test_task_recorded_implementation_requires_successful_ancestor_and_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline, state = self._scope_test_run(root)
            repo = pipeline.repo
            baseline = pipeline.git.head(repo)
            git(repo, "checkout", "-b", "recorded")
            (repo / "result.txt").write_text("implemented", encoding="utf-8")
            git(repo, "add", "result.txt")
            git(repo, "commit", "-m", "recorded implementation")
            implementation = pipeline.git.head(repo)
            task = state.tasks[0]
            task.worktree = str(repo)
            task.verify_commands = [[sys.executable, "-c", "pass"]]
            record = TaskActionResult("execute", status="succeeded", baseline_commit=baseline, result_commit=implementation)
            task.action_results = [record]
            self.assertTrue(pipeline._task_has_recorded_implementation(task, implementation))
            self.assertFalse(pipeline._task_has_recorded_implementation(task, implementation, action_start=1))
            self.assertFalse(pipeline._task_has_recorded_implementation(task, baseline))
            (repo / "later.txt").write_text("later task", encoding="utf-8")
            git(repo, "add", "later.txt")
            git(repo, "commit", "-m", "later task")
            self.assertTrue(pipeline._task_has_recorded_implementation(task, pipeline.git.head(repo)))
            task.verify_commands = []
            self.assertFalse(pipeline._task_has_recorded_implementation(task, implementation))
            task.verify_commands = [[sys.executable, "-c", "pass"]]
            record.status = "failed"
            self.assertFalse(pipeline._task_has_recorded_implementation(task, implementation))
            record.status = "succeeded"
            record.baseline_commit = implementation
            self.assertFalse(pipeline._task_has_recorded_implementation(task, implementation))

    def test_task_unproven_no_commit_does_not_skip_to_successful_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state.tasks[0].verify_commands = [[sys.executable, "-c", "pass"]]
            pipeline.store.save(state)
            with patch.object(pipeline, "_invoke_agent", return_value="already complete"), patch.object(pipeline, "_run_task_verification") as verify:
                result = pipeline.execute(state.id)
            self.assertEqual(result.stage, Stage.FAILED)
            self.assertEqual(result.tasks[0].failed_action, TaskAction.EXECUTE)
            self.assertIn("produced no commit", result.tasks[0].error)
            verify.assert_not_called()

    def test_msbuild_output_access_integration_failure_does_not_start_code_repair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))

            def invoke(_state, current, *_args):
                (Path(current.worktree) / "result.txt").write_text("implemented", encoding="utf-8")
                return "implemented"

            with patch.object(pipeline, "_invoke_agent", side_effect=invoke):
                completed = pipeline.execute(state.id)
            pipeline.config = replace(pipeline.config, execution=replace(
                pipeline.config.execution, verify_commands=(("dotnet", "build", "Example.sln"),),
            ))
            diagnostic = "error MSB4018: System.UnauthorizedAccessException: Access to the path 'obj/Debug/Manifest.json' is denied."
            with (
                patch("ai_orchestrator.pipeline.diagnose_dotnet", return_value=DotnetDiagnostic("dotnet", "SDK selected")),
                patch("ai_orchestrator.pipeline.run_command", return_value=subprocess.CompletedProcess([], 1, diagnostic)),
                patch.object(pipeline, "_repair_verification_failure") as repair,
            ):
                with self.assertRaisesRegex(PipelineError, "산출물 쓰기 접근이 거부") as caught:
                    pipeline.verify_and_repair(state.id, request_id=str(uuid.uuid4()))
            repair.assert_not_called()
            self.assertFalse(pipeline._verification_failure_is_repairable(caught.exception))
            failed = pipeline.store.load(state.id)
            self.assertEqual(failed.stage, Stage.FAILED)
            self.assertEqual(failed.verification_repair_count, 0)
            self.assertEqual(failed.tasks[0].completed_commit, completed.tasks[0].completed_commit)
            attempt = failed.verification_attempts[-1]
            self.assertEqual(attempt.failure_phase, "command_environment")
            self.assertEqual(attempt.failed_command, ["dotnet", "build", "Example.sln"])
            self.assertEqual(attempt.candidate_task_ids, [])

    def test_automatic_task_repair_does_not_retry_provider_failures(self) -> None:
        for error in (ProviderCapacityError("model overloaded"), ProviderRequestLimitError("usage limit"), ProviderTimeoutError("timeout")):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as directory:
                pipeline, state = self._scope_test_run(Path(directory))
                with patch.object(pipeline, "_invoke_agent", side_effect=error) as agent:
                    failed = pipeline.execute(state.id)
                self.assertEqual(failed.stage, Stage.FAILED)
                self.assertEqual(agent.call_count, 1)
                self.assertFalse(any(event.kind == "task_repair" for event in failed.events))

    def test_automatic_task_repair_preserves_user_stop(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))

            def invoke(_state, current, *_args):
                (Path(current.worktree) / "result.txt").write_text("preserved work", encoding="utf-8")
                return "implemented"

            with patch.object(pipeline, "_invoke_agent", side_effect=invoke) as agent:
                with patch.object(pipeline, "_perform_task_verification", side_effect=ExecutionStopped("user stopped")):
                    stopped = pipeline.execute(state.id)
            self.assertEqual(agent.call_count, 1)
            self.assertEqual(stopped.tasks[0].status, TaskStatus.STOPPED)
            self.assertEqual((Path(stopped.tasks[0].worktree) / "result.txt").read_text(encoding="utf-8"), "preserved work")
            self.assertFalse(any(event.kind == "task_repair" for event in stopped.events))

    def test_automatic_task_repair_rejects_head_mutation_even_when_verification_failed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state.tasks[0].verify_commands = [[sys.executable, "-c",
                "import subprocess; subprocess.run(['git','commit','--allow-empty','-m','not allowed'],check=True); raise SystemExit(1)"]]
            pipeline.store.save(state)

            def invoke(_state, current, *_args):
                (Path(current.worktree) / "result.txt").write_text("implemented", encoding="utf-8")
                return "implemented"

            with patch.object(pipeline, "_invoke_agent", side_effect=invoke) as agent:
                failed = pipeline.execute(state.id)
            self.assertEqual(agent.call_count, 1)
            self.assertEqual(failed.tasks[0].failed_action, TaskAction.VERIFY)
            self.assertIn("HEAD changed during verification", failed.tasks[0].error)
            self.assertEqual(failed.tasks[0].completed_commit, "")

    def test_interrupt_planning_marks_active_run_failed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
            codex_sdk = connected_codex_sdk()
            pipeline = Pipeline(config, codex_sdk=codex_sdk)
            state = RunState(
                id="planning-run",
                spec_path=str(root / "requirements.md"),
                spec_digest="digest",
                repo_path=str(repo),
                main_branch="main",
                stage=Stage.REVIEWED,
            )
            state.begin_step(RunStep.PLANNING)
            pipeline.store.save(state)

            interrupted = pipeline.interrupt_planning(state.id, approved=True)

            self.assertEqual(interrupted.stage, Stage.FAILED)
            self.assertIsNone(interrupted.active_step)
            self.assertEqual(interrupted.failed_step, RunStep.PLANNING)
            self.assertEqual(interrupted.failure_message, "사용자가 Planning 작업을 중단했습니다.")
            codex_sdk.close_conversation.assert_called_once_with(f"planning:{state.id}")
            self.assertEqual(pipeline.store.inspect_lock(state.id).state, RunLockState.UNLOCKED)

    def test_interrupt_planning_clears_only_confirmed_stale_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
            pipeline = Pipeline(config)
            state = RunState(
                id="orphaned-planning-run",
                spec_path=str(root / "requirements.md"),
                spec_digest="digest",
                repo_path=str(repo),
                main_branch="main",
                stage=Stage.REVIEWED,
            )
            state.begin_step(RunStep.PLANNING)
            pipeline.store.save(state)
            lock_path = pipeline.store.lock_path(state.id)
            lock_path.write_text(
                json.dumps(
                    {
                        "token": "stale-token",
                        "pid": 999_999_999,
                        "host": socket.gethostname(),
                        "operation": "planning",
                        "acquired_at": state.updated_at,
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(StateStore, "_pid_is_alive", return_value=False):
                interrupted = pipeline.interrupt_planning(state.id, approved=True)

            self.assertEqual(interrupted.stage, Stage.FAILED)
            self.assertFalse(lock_path.exists())

    def test_interrupt_planning_requires_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
            pipeline = Pipeline(config)

            with self.assertRaisesRegex(ApprovalRequired, "planning interruption requires approval"):
                pipeline.interrupt_planning("planning-run", approved=False)

    def test_planning_prepare_persists_run_before_provider_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "requirements.md"
            spec.write_text("분리 Planning 실행을 검증한다.", encoding="utf-8")
            pipeline, counter = self._counting_planning_pipeline(root, repo)

            prepared = pipeline.prepare_planning(spec)

            self.assertEqual(prepared.stage, Stage.REVIEWED)
            self.assertEqual(prepared.active_step, RunStep.PLANNING)
            self.assertEqual(prepared.planning_profile_source, ProfileSource.ROUTING)
            self.assertEqual(pipeline.status(prepared.id).stage, Stage.REVIEWED)
            self.assertFalse(counter.exists())

            planned = pipeline.run_planning(prepared.id)

            self.assertEqual(planned.stage, Stage.PLANNED)
            self.assertIsNone(planned.active_step)
            self.assertEqual(counter.read_text(encoding="utf-8"), "1\n")

    def test_directed_planning_requires_and_persists_specific_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            source = repo / "Planning"
            source.mkdir()
            (source / "work-groups.md").write_text("작업 그룹 삭제 기능과 worktree 정리 규칙", encoding="utf-8")
            git(repo, "add", "Planning/work-groups.md")
            git(repo, "commit", "-m", "planning source")
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=repo),
                    execution=ExecutionConfig(),
                    agents=(AgentConfig("manual", ("general",), (), 1),),
                )
            )

            with self.assertRaisesRegex(PipelineError, "requires a specific user request"):
                pipeline.prepare_planning(source, planning_mode=PlanningMode.DIRECTED)

            prepared = pipeline.prepare_planning(source, planning_mode=PlanningMode.DIRECTED, planning_request="작업 그룹 삭제 오류만 수정해 주세요.")

            self.assertEqual(prepared.planning_mode, PlanningMode.DIRECTED)
            self.assertEqual(prepared.planning_request, "작업 그룹 삭제 오류만 수정해 주세요.")
            self.assertEqual(len(prepared.planning_messages), 1)
            self.assertEqual(prepared.planning_messages[0].role, PlanningMessageRole.USER)
            self.assertEqual(prepared.planning_messages[0].text, prepared.planning_request)

    def test_incremental_document_changes_keep_stable_snapshot_per_base_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            source = repo / "Planning"
            source.mkdir()
            document = source / "ranking.md"
            document.write_text("# Ranking\n초기 규칙\n", encoding="utf-8")
            git(repo, "add", "Planning/ranking.md")
            git(repo, "commit", "-m", "planning baseline")
            pipeline, _ = self._counting_planning_pipeline(root, repo)
            pipeline.refresh_planning_index(source)
            document.write_text("# Ranking\n변경된 동점 규칙\n", encoding="utf-8")
            git(repo, "add", "Planning/ranking.md")
            git(repo, "commit", "-m", "change planning rule")

            first = pipeline.prepare_planning(source)
            second = pipeline.prepare_planning(source)

            first_document = Path(first.spec_snapshot_path).read_text(encoding="utf-8")
            second_document = Path(second.spec_snapshot_path).read_text(encoding="utf-8")
            self.assertIn("Changes: 1 (added 0, modified 1, deleted 0).", first_document)
            self.assertIn("변경된 동점 규칙", first_document)
            self.assertEqual(first_document, second_document)
            second_snapshot = load_planning_source_index(
                pipeline.store.run_dir(second.id) / "planning-source-index.json"
            )
            self.assertEqual((second_snapshot.added_count, second_snapshot.modified_count, second_snapshot.deleted_count), (0, 1, 0))

    def test_directed_document_context_is_saved_and_reused_with_cached_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            source = repo / "Planning"
            source.mkdir()
            (source / "ranking.md").write_text("# Ranking\n\n동점일 때 먼저 달성한 사용자를 우선한다.", encoding="utf-8")
            (source / "payment.md").write_text("# Payment\n\n무관한 결제 상세 원문.", encoding="utf-8")
            git(repo, "add", "Planning")
            git(repo, "commit", "-m", "planning documents")
            pipeline, _ = self._counting_planning_pipeline(root, repo)
            output = "AI_PLAN_RESULT: " + json.dumps(
                {
                    "summary": "Ranking 구현",
                    "server_work": False,
                    "source_paths": ["ranking.md"],
                    "instruction_paths": [],
                    "tasks": [
                        {
                            "id": "ranking",
                            "title": "Ranking 구현",
                            "description": "동점 순위를 처리한다.",
                            "capabilities": ["general"],
                            "depends_on": [],
                            "acceptance_criteria": ["먼저 달성한 사용자가 우선한다."],
                            "expected_paths": ["README.md"],
                            "forbidden_paths": [],
                            "verify_commands": [[sys.executable, "-c", "pass"]],
                            "risk_level": "low",
                        }
                    ],
                    "questions": [],
                }
            )
            with patch.object(pipeline, "_invoke_planning_agent", return_value=output) as provider:
                first = pipeline.start(source, planning_mode=PlanningMode.DIRECTED, planning_request="Ranking 구현")
                second = pipeline.start(source, planning_mode=PlanningMode.DIRECTED, planning_request="Ranking 구현")
            self.assertEqual(provider.call_count, 1)
            self.assertEqual(first.stage, Stage.PLANNED)
            self.assertEqual(second.stage, Stage.PLANNED)
            prompt = (pipeline.store.run_dir(first.id) / "prompts" / "planning-1.md").read_text(encoding="utf-8")
            self.assertIn("Request-related document context", prompt)
            self.assertIn("동점일 때 먼저 달성한 사용자를 우선한다.", prompt)
            self.assertNotIn("무관한 결제 상세 원문", prompt)
            cache_prompt = (pipeline.store.run_dir(second.id) / "prompts" / "planning-cache-0.md").read_text(encoding="utf-8")
            self.assertEqual(prompt, cache_prompt)
            with (
                patch.object(pipeline, "_invoke_planning_agent", return_value=output),
                patch(
                    "ai_orchestrator.pipeline.render_planning_request_context",
                    side_effect=AssertionError("clarification must reuse conversation context"),
                ),
            ):
                revised = pipeline.clarify_text(second.id, "동점 처리 요구사항을 유지해 주세요.")
            self.assertEqual(revised.stage, Stage.PLANNED)

    def test_changed_directed_context_fails_before_provider_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            source = repo / "Planning"
            source.mkdir()
            document = source / "ranking.md"
            document.write_text("# Ranking\noriginal", encoding="utf-8")
            pipeline, _ = self._counting_planning_pipeline(root, repo)
            prepared = pipeline.prepare_planning(source, planning_mode=PlanningMode.DIRECTED, planning_request="Ranking 구현")
            document.write_text("# Ranking\nchanged", encoding="utf-8")
            with patch.object(pipeline, "_invoke_planning_agent") as provider:
                with self.assertRaisesRegex(PlanningError, "changed since indexing"):
                    pipeline.run_planning(prepared.id)
            provider.assert_not_called()
            failed = pipeline.status(prepared.id)
            self.assertEqual(failed.stage, Stage.FAILED)
            self.assertEqual(failed.failed_step, RunStep.PLANNING)
            self.assertEqual(failed.planning_attempts, 0)

    def test_directed_planning_runs_without_planning_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline, counter = self._counting_planning_pipeline(root, repo)

            state = pipeline.start("", planning_mode=PlanningMode.DIRECTED, planning_request="README 표시 오류만 수정해 주세요.")

            self.assertEqual(state.stage, Stage.PLANNED)
            self.assertEqual(state.spec_path, "")
            self.assertEqual(counter.read_text(encoding="utf-8"), "1\n")
            self.assertIn("No planning document directory was provided.", Path(state.spec_snapshot_path).read_text(encoding="utf-8"))
            self.assertFalse((pipeline.store.run_dir(state.id) / "planning-source-index.json").exists())

    def test_full_auto_planning_rejects_missing_planning_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline = Pipeline(Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=()))

            with self.assertRaisesRegex(PipelineError, "full auto planning requires a planning document or directory"):
                pipeline.prepare_planning("")

    def test_planning_reuses_valid_result_for_identical_clean_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "requirements.md"
            spec.write_text("캐시 가능한 계획을 작성한다.", encoding="utf-8")
            pipeline, counter = self._counting_planning_pipeline(root, repo)

            first = pipeline.start(spec)
            second = pipeline.start(spec)

            self.assertEqual(first.stage, Stage.PLANNED)
            self.assertEqual(first.planning_attempts, 1)
            self.assertEqual(second.stage, Stage.PLANNED)
            self.assertEqual(second.planning_attempts, 0)
            self.assertEqual(counter.read_text(encoding="utf-8"), "1\n")
            self.assertTrue(any(event.message.startswith("planning result cache hit:") for event in second.events))

    def test_planning_cache_is_bypassed_for_dirty_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "requirements.md"
            spec.write_text("변경 감지 계획을 작성한다.", encoding="utf-8")
            pipeline, counter = self._counting_planning_pipeline(root, repo)
            pipeline.start(spec)
            (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")

            state = pipeline.start(spec)

            self.assertEqual(state.stage, Stage.PLANNED)
            self.assertEqual(state.planning_attempts, 1)
            self.assertEqual(counter.read_text(encoding="utf-8"), "1\n1\n")
            self.assertTrue(any(event.message == "planning result cache bypassed: repository has uncommitted changes" for event in state.events))

    def test_planning_ignores_corrupt_cached_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "requirements.md"
            spec.write_text("손상 캐시 계획을 작성한다.", encoding="utf-8")
            pipeline, counter = self._counting_planning_pipeline(root, repo)
            pipeline.start(spec)
            cache_paths = list((repo / ".ai-orchestrator" / "planning-cache").glob("*.json"))
            self.assertEqual(len(cache_paths), 1)
            cache_paths[0].write_text("not-json", encoding="utf-8")

            state = pipeline.start(spec)

            self.assertEqual(state.stage, Stage.PLANNED)
            self.assertEqual(state.planning_attempts, 1)
            self.assertEqual(counter.read_text(encoding="utf-8"), "1\n1\n")
            self.assertTrue(any(event.message.startswith("planning result cache ignored: invalid planning result cache:") for event in state.events))

    def test_planning_cache_key_changes_with_base_commit_and_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline, _ = self._counting_planning_pipeline(root, repo)
            agent = pipeline.agents["planner"]
            state = RunState(
                id="run-1",
                spec_path=str(root / "requirements.md"),
                spec_digest="digest",
                repo_path=str(repo),
                main_branch="main",
                stage=Stage.PLANNED,
                base_commit="commit-a",
                planning_model="model-a",
                planning_reasoning_effort="high",
            )

            original = pipeline._planning_cache_key(state, agent, "prompt")
            state.base_commit = "commit-b"
            changed_commit = pipeline._planning_cache_key(state, agent, "prompt")
            state.base_commit = "commit-a"
            state.planning_model = "model-b"
            changed_model = pipeline._planning_cache_key(state, agent, "prompt")
            changed_prompt = pipeline._planning_cache_key(state, agent, "updated prompt")

            self.assertNotEqual(original, changed_commit)
            self.assertNotEqual(original, changed_model)
            self.assertNotEqual(changed_model, changed_prompt)

    def test_delete_run_requires_approval_and_removes_planned_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] 결과 생성\n", encoding="utf-8")
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
            codex_sdk = connected_codex_sdk()
            pipeline = Pipeline(config, codex_sdk=codex_sdk)
            state = pipeline.start(spec)

            with self.assertRaisesRegex(ApprovalRequired, "approval"):
                pipeline.delete_run(state.id, approved=False)

            result = pipeline.delete_run(state.id, approved=True)

            self.assertEqual(result.run_id, state.id)
            self.assertEqual(result.task_count, 1)
            self.assertEqual(result.worktree_count, 0)
            self.assertEqual(result.branch_count, 0)
            self.assertFalse(pipeline.store.run_dir(state.id).exists())
            self.assertEqual(pipeline.list_statuses(), [])
            codex_sdk.discard_idle_clients.assert_called_once_with()
            codex_sdk.close_conversation.assert_called_once_with(f"planning:{state.id}")

    def test_delete_run_discards_owned_dirty_unmerged_workspaces(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] 폐기할 결과 생성\n", encoding="utf-8")
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
            pipeline = Pipeline(config)
            state = pipeline.execute(pipeline.confirm_plan(pipeline.start(spec).id).id, manual=True)
            task = state.tasks[0]
            worktree = Path(task.worktree)
            (worktree / "uncommitted.txt").write_text("discard me\n", encoding="utf-8")
            main_head = pipeline.git.head(repo)

            result = pipeline.delete_run(state.id, approved=True)

            self.assertEqual(result.worktree_count, 1)
            self.assertEqual(result.branch_count, 1)
            self.assertFalse(worktree.exists())
            self.assertFalse(pipeline.git.branch_exists(task.branch))
            self.assertFalse(pipeline.store.run_dir(state.id).exists())
            self.assertEqual(pipeline.git.head(repo), main_head)

    def test_delete_run_clears_confirmed_stale_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] 결과 생성\n", encoding="utf-8")
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
            pipeline = Pipeline(config)
            state = pipeline.start(spec)
            pipeline.store.lock_path(state.id).write_text(
                json.dumps(
                    {
                        "token": "stale-token",
                        "pid": 999_999_999,
                        "host": socket.gethostname(),
                        "operation": "planning",
                        "acquired_at": state.updated_at,
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(StateStore, "_pid_is_alive", return_value=False):
                result = pipeline.delete_run(state.id, approved=True)

            self.assertEqual(result.run_id, state.id)
            self.assertFalse(pipeline.store.run_dir(state.id).exists())

    def test_delete_run_shares_one_git_timeout_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] 결과 생성\n", encoding="utf-8")
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
            pipeline = Pipeline(config)
            state = pipeline.start(spec)

            with (
                patch("ai_orchestrator.pipeline.time.monotonic", side_effect=[100, 100, 101, 102, 103, 104, 105]),
                patch.object(pipeline.git, "ensure_repository") as ensure_repo,
                patch.object(pipeline.git, "list_worktrees", return_value=[]) as list_worktrees,
                patch.object(pipeline.git, "branch_exists", return_value=False) as branch_exists,
            ):
                pipeline.delete_run(state.id, approved=True)

            ensure_repo.assert_called_once_with(non_interactive=True, timeout_seconds=RUN_DELETION_TIMEOUT_SECONDS)
            list_worktrees.assert_called_once_with(non_interactive=True, timeout_seconds=RUN_DELETION_TIMEOUT_SECONDS - 1)
            self.assertEqual([call.kwargs["timeout_seconds"] for call in branch_exists.call_args_list], [58, 57, 56, 55])
            self.assertTrue(all(call.kwargs["non_interactive"] for call in branch_exists.call_args_list))

    def test_delete_verified_run_removes_preserved_integration_branch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline, state = self._ready_manual_run(root, repo)
            verified = pipeline.verify(state.id)
            integration_branch = pipeline._integration_branch_name(state.id)
            self.assertTrue(pipeline.git.branch_exists(integration_branch))
            main_head = pipeline.git.head(repo)

            result = pipeline.delete_run(verified.id, approved=True)

            self.assertEqual(result.worktree_count, 1)
            self.assertEqual(result.branch_count, 2)
            self.assertFalse(pipeline.git.branch_exists(integration_branch))
            self.assertFalse(pipeline.store.run_dir(verified.id).exists())
            self.assertEqual(pipeline.git.head(repo), main_head)

    def test_delete_run_removes_interrupted_verification_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline, state = self._ready_manual_run(root, repo)
            verification_worktree = pipeline._verification_worktree_path(state.id)
            pipeline.git.prepare_detached_worktree(verification_worktree, pipeline.git.head(repo))

            result = pipeline.delete_run(state.id, approved=True)

            self.assertEqual(result.worktree_count, 2)
            self.assertFalse(verification_worktree.exists())
            self.assertFalse(pipeline.store.run_dir(state.id).exists())

    def test_delete_run_removes_recorded_unregistered_conflict_candidate_residue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=repo),
                    execution=ExecutionConfig(),
                    agents=(AgentConfig("manual", ("general",), (), 1),),
                )
            )
            run_id = "conflict-candidate-residue"
            request_id = "a268b134-5cc9-41a9-a78e-0d119ba065f4"
            workspace_root = root / "worktrees"
            candidate_worktree = workspace_root / run_id / ".conflict-resolution" / request_id
            candidate_worktree.mkdir(parents=True)
            (candidate_worktree / "leftover.txt").write_text("discard\n", encoding="utf-8")
            state = RunState(
                id=run_id,
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(repo),
                main_branch="main",
                stage=Stage.FAILED,
                workspace_location=WorkspaceLocation(root=str(workspace_root), source=WorkspaceLocationSource.PROJECT_DEFAULT),
                integration_conflict=IntegrationConflict(
                    id="conflict-1",
                    verification_attempt_id="verify-1",
                    main_head=pipeline.git.head(repo),
                    work_head=pipeline.git.head(repo),
                    merge_base_heads=[],
                    files=[],
                    fingerprint="fingerprint",
                    candidate=ConflictResolutionCandidate(
                        id=f"candidate-{request_id}",
                        request_id=request_id,
                        status="failed",
                        worktree=str(candidate_worktree),
                    ),
                ),
            )
            pipeline.store.save(state)

            result = pipeline.delete_run(run_id, approved=True)

            self.assertEqual(result.worktree_count, 1)
            self.assertFalse(candidate_worktree.exists())
            self.assertFalse(pipeline.store.run_dir(run_id).exists())

    def test_delete_run_preserves_unregistered_conflict_candidate_with_git_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=repo),
                    execution=ExecutionConfig(),
                    agents=(AgentConfig("manual", ("general",), (), 1),),
                )
            )
            run_id = "conflict-candidate-with-marker"
            request_id = "b268b134-5cc9-41a9-a78e-0d119ba065f4"
            workspace_root = root / "worktrees"
            candidate_worktree = workspace_root / run_id / ".conflict-resolution" / request_id
            candidate_worktree.mkdir(parents=True)
            marker = candidate_worktree / ".git"
            marker.write_text("gitdir: unknown\n", encoding="utf-8")
            state = RunState(
                id=run_id,
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(repo),
                main_branch="main",
                stage=Stage.FAILED,
                workspace_location=WorkspaceLocation(root=str(workspace_root), source=WorkspaceLocationSource.PROJECT_DEFAULT),
                integration_conflict=IntegrationConflict(
                    id="conflict-1",
                    verification_attempt_id="verify-1",
                    main_head=pipeline.git.head(repo),
                    work_head=pipeline.git.head(repo),
                    merge_base_heads=[],
                    files=[],
                    fingerprint="fingerprint",
                    candidate=ConflictResolutionCandidate(
                        id=f"candidate-{request_id}",
                        request_id=request_id,
                        status="failed",
                        worktree=str(candidate_worktree),
                    ),
                ),
            )
            pipeline.store.save(state)

            with self.assertRaisesRegex(PipelineError, "Git marker"):
                pipeline.delete_run(run_id, approved=True)

            self.assertTrue(marker.is_file())
            self.assertTrue(pipeline.store.run_dir(run_id).is_dir())

    def test_delete_run_refuses_unregistered_verification_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline, state = self._ready_manual_run(root, repo)
            verification_worktree = pipeline._verification_worktree_path(state.id)
            verification_worktree.mkdir(parents=True)
            marker = verification_worktree / "keep.txt"
            marker.write_text("keep\n", encoding="utf-8")

            with self.assertRaisesRegex(PipelineError, "검증용 경로를 Git이 소유하지 않습니다"):
                pipeline.delete_run(state.id, approved=True)

            self.assertTrue(marker.is_file())

    def test_delete_run_removes_recorded_long_path_residue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=repo),
                    execution=ExecutionConfig(),
                    agents=(AgentConfig("manual", ("general",), (), 1),),
                )
            )
            run_id = "partial-long-path-delete"
            task_id = "task"
            worktree = repo / ".ai_auto_work" / "worktree" / run_id / task_id
            worktree.mkdir(parents=True)
            marker = worktree / "leftover.txt"
            marker.write_text("leftover", encoding="utf-8")
            state = RunState(
                id=run_id,
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(repo),
                main_branch="main",
                stage=Stage.PUSHED,
                tasks=[
                    WorkTask(
                        id=task_id,
                        title="부분 삭제 작업",
                        capabilities=["general"],
                        branch=f"ai/{run_id}/{task_id}",
                        worktree=str(worktree),
                        status=TaskStatus.MERGED,
                    )
                ],
            )
            state.add_event(
                "workspace",
                "run deletion failed: command failed (255): "
                f"git worktree remove --force {worktree.resolve()}\n"
                "error: failed to delete worktree: Filename too long",
            )
            pipeline.store.save(state)

            result = pipeline.delete_run(run_id, approved=True)

            self.assertEqual(result.worktree_count, 1)
            self.assertFalse(worktree.exists())
            self.assertFalse(pipeline.store.run_dir(run_id).exists())

    def test_delete_run_removes_recorded_windows_permission_residue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=repo),
                    execution=ExecutionConfig(),
                    agents=(AgentConfig("manual", ("general",), (), 1),),
                )
            )
            run_id = "partial-windows-permission-delete"
            workspace_root = repo / ".ai_auto_work" / "worktree"
            worktree = workspace_root / run_id / "work"
            (worktree / "src").mkdir(parents=True)
            (worktree / "src" / "locked.dll").write_text("leftover", encoding="utf-8")
            branch = f"ai/{run_id}"
            git(repo, "branch", branch)
            state = RunState(
                id=run_id,
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(repo),
                main_branch="main",
                stage=Stage.PUSHED,
                workspace_mode=ExecutionWorkspaceMode.SHARED,
                workspace_location=WorkspaceLocation(root=str(workspace_root), source=WorkspaceLocationSource.PROJECT_DEFAULT),
                execution_branch=branch,
                execution_worktree=str(worktree),
                tasks=[
                    WorkTask(
                        id="task",
                        title="Windows 부분 삭제 잔여물 정리",
                        capabilities=["general"],
                        branch=branch,
                        worktree=str(worktree),
                        status=TaskStatus.MERGED,
                    )
                ],
            )
            state.add_event(
                "workspace",
                "shared run workspace cleanup deferred: command failed (255): "
                f"git -c core.longpaths=true worktree remove {worktree.resolve()}\n"
                f"error: failed to delete '{worktree.resolve()}': Permission denied",
            )
            pipeline.store.save(state)

            result = pipeline.delete_run(run_id, approved=True)

            self.assertEqual(result.worktree_count, 1)
            self.assertFalse(worktree.exists())
            self.assertFalse(pipeline.git.branch_exists(branch))
            self.assertFalse(pipeline.store.run_dir(run_id).exists())

    def test_delete_run_preserves_unrecorded_worktree_residue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=repo),
                    execution=ExecutionConfig(),
                    agents=(AgentConfig("manual", ("general",), (), 1),),
                )
            )
            run_id = "unrecorded-residue"
            task_id = "task"
            worktree = repo / ".ai_auto_work" / "worktree" / run_id / task_id
            worktree.mkdir(parents=True)
            marker = worktree / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            state = RunState(
                id=run_id,
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(repo),
                main_branch="main",
                stage=Stage.PUSHED,
                tasks=[
                    WorkTask(
                        id=task_id,
                        title="미확인 경로",
                        capabilities=["general"],
                        branch=f"ai/{run_id}/{task_id}",
                        worktree=str(worktree),
                        status=TaskStatus.MERGED,
                    )
                ],
            )
            pipeline.store.save(state)

            with self.assertRaisesRegex(PipelineError, "작업공간 경로를 Git이 소유하지 않습니다"):
                pipeline.delete_run(run_id, approved=True)

            self.assertTrue(marker.is_file())

    def test_delete_run_removes_shared_worktree_with_orphaned_repository_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=repo),
                    execution=ExecutionConfig(),
                    agents=(AgentConfig("manual", ("general",), (), 1),),
                )
            )
            run_id = "orphaned-shared-worktree"
            workspace_root = repo / ".ai_auto_work" / "worktree"
            worktree = workspace_root / run_id / "work"
            branch = f"ai/{run_id}"
            pipeline.git.prepare_worktree(worktree, branch, pipeline.git.head(repo))
            marker_text = (worktree / ".git").read_text(encoding="utf-8")
            pipeline.git.remove_worktree(worktree, force=True)
            worktree.mkdir(parents=True)
            (worktree / ".git").write_text(marker_text, encoding="utf-8")
            (worktree / "leftover.txt").write_text("discard\n", encoding="utf-8")
            state = RunState(
                id=run_id,
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(repo),
                main_branch="main",
                stage=Stage.PUSHED,
                workspace_mode=ExecutionWorkspaceMode.SHARED,
                workspace_location=WorkspaceLocation(root=str(workspace_root), source=WorkspaceLocationSource.PROJECT_DEFAULT),
                execution_branch=branch,
                execution_worktree=str(worktree),
                tasks=[
                    WorkTask(
                        id="task",
                        title="고아 작업공간 정리",
                        capabilities=["general"],
                        branch=branch,
                        worktree=str(worktree),
                        status=TaskStatus.MERGED,
                    )
                ],
            )
            pipeline.store.save(state)

            result = pipeline.delete_run(run_id, approved=True)

            self.assertEqual(result.worktree_count, 1)
            self.assertEqual(result.branch_count, 1)
            self.assertFalse(worktree.exists())
            self.assertFalse(pipeline.git.branch_exists(branch))
            self.assertFalse(pipeline.store.run_dir(run_id).exists())

    def test_delete_run_removes_shared_worktree_with_only_managed_state_residue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=repo),
                    execution=ExecutionConfig(),
                    agents=(AgentConfig("manual", ("general",), (), 1),),
                )
            )
            run_id = "managed-state-only-residue"
            workspace_root = repo / ".ai_auto_work" / "worktree"
            worktree = workspace_root / run_id / "work"
            managed_state = worktree / ".ai-orchestrator"
            managed_state.mkdir(parents=True)
            (managed_state / "local-state.json").write_text("{}\n", encoding="utf-8")
            branch = f"ai/{run_id}"
            git(repo, "branch", branch)
            state = RunState(
                id=run_id,
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(repo),
                main_branch="main",
                stage=Stage.PUSHED,
                workspace_mode=ExecutionWorkspaceMode.SHARED,
                workspace_location=WorkspaceLocation(root=str(workspace_root), source=WorkspaceLocationSource.PROJECT_DEFAULT),
                execution_branch=branch,
                execution_worktree=str(worktree),
                tasks=[
                    WorkTask(
                        id="task",
                        title="관리 상태 잔여물 정리",
                        capabilities=["general"],
                        branch=branch,
                        worktree=str(worktree),
                        status=TaskStatus.MERGED,
                    )
                ],
            )
            pipeline.store.save(state)

            result = pipeline.delete_run(run_id, approved=True)

            self.assertEqual(result.worktree_count, 1)
            self.assertFalse(worktree.exists())
            self.assertFalse(pipeline.git.branch_exists(branch))
            self.assertFalse(pipeline.store.run_dir(run_id).exists())

    def test_delete_run_refuses_active_lock_and_foreign_workspace_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] 결과 생성\n", encoding="utf-8")
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
            pipeline = Pipeline(config)
            state = pipeline.start(spec)

            with pipeline.store.lock(state.id, "execute"):
                with self.assertRaisesRegex(PipelineError, "잠금 상태가 active"):
                    pipeline.delete_run(state.id, approved=True)

            foreign = repo / "foreign-worktree"
            foreign.mkdir()
            (foreign / "keep.txt").write_text("keep", encoding="utf-8")
            state.tasks[0].worktree = str(foreign)
            pipeline.store.save(state)

            with self.assertRaisesRegex(PipelineError, "허용된 경계 밖"):
                pipeline.delete_run(state.id, approved=True)

            self.assertTrue((foreign / "keep.txt").is_file())
            self.assertTrue(pipeline.store.run_dir(state.id).is_dir())

    def test_refresh_planning_index_uses_git_visible_documents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            docs = repo / "Docs"
            ignored = docs / "ignored"
            ignored.mkdir(parents=True)
            (docs / "tracked.md").write_text("# 추적 기획\n", encoding="utf-8")
            (repo / ".gitignore").write_text(".ai-orchestrator/\nDocs/ignored/\n", encoding="utf-8")
            git(repo, "add", ".gitignore", "Docs/tracked.md")
            git(repo, "commit", "-m", "add planning docs")
            (docs / "untracked.txt").write_text("비추적 기획\n", encoding="utf-8")
            (ignored / "hidden.md").write_text("# 무시된 문서\n", encoding="utf-8")
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )

            index = Pipeline(config).refresh_planning_index(docs)

            self.assertEqual([document.relative_path for document in index.documents], ["tracked.md", "untracked.txt"])
            self.assertTrue(Path(index.cache_path).is_file())

    def test_planning_start_reuses_matching_clean_source_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            docs = repo / "Docs"
            docs.mkdir()
            (docs / "plan.md").write_text("# 구현 계획\n", encoding="utf-8")
            git(repo, "add", "Docs/plan.md")
            git(repo, "commit", "-m", "add planning document")
            config = Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=())
            pipeline = Pipeline(config)
            base_commit = pipeline.git.head(repo)
            original = pipeline.refresh_planning_index(docs, base_commit=base_commit)

            with (
                patch.object(pipeline.git, "ensure_repository") as ensure_repo,
                patch.object(pipeline.git, "head") as head,
                patch.object(pipeline.git, "path_has_changes") as path_has_changes,
            ):
                prepared = pipeline.prepare_planning(docs, prepared_source_index=original)

            self.assertEqual(prepared.stage, Stage.REVIEWED)
            self.assertEqual(prepared.base_commit, original.base_commit)
            ensure_repo.assert_not_called()
            head.assert_not_called()
            path_has_changes.assert_not_called()

            with (
                patch.object(pipeline.git, "path_has_changes", return_value=False) as path_has_changes,
                patch.object(pipeline, "refresh_planning_index") as refresh_index,
            ):
                reused, was_reused = pipeline._planning_index_for_start(docs, base_commit=base_commit)

            self.assertTrue(was_reused)
            self.assertEqual(reused.content_digest, original.content_digest)
            self.assertEqual(reused.reused_count, original.document_count)
            path_has_changes.assert_called_once_with(docs.resolve(), non_interactive=True, timeout_seconds=PLANNING_INDEX_TIMEOUT_SECONDS)
            refresh_index.assert_not_called()

            refreshed = Mock()
            with (
                patch.object(pipeline.git, "path_has_changes", return_value=True),
                patch.object(pipeline, "refresh_planning_index", return_value=refreshed) as refresh_index,
            ):
                selected, was_reused = pipeline._planning_index_for_start(docs, base_commit=base_commit)

            self.assertFalse(was_reused)
            self.assertIs(selected, refreshed)
            refresh_index.assert_called_once_with(docs.resolve(), base_commit=base_commit)

    @patch("ai_orchestrator.pipeline.time.monotonic", return_value=100)
    def test_refresh_planning_index_bounds_git_preflight(self, _monotonic) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            docs = repo / "Docs"
            docs.mkdir(parents=True)
            document = docs / "plan.md"
            document.write_text("# 구현 계획\n", encoding="utf-8")
            pipeline = Pipeline(Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=()))
            expected = Mock()

            with (
                patch.object(pipeline.git, "ensure_repository") as ensure_repository,
                patch.object(pipeline.git, "list_project_files", return_value=[document]) as list_project_files,
                patch.object(pipeline.git, "head", return_value="a" * 40) as head,
                patch("ai_orchestrator.pipeline.inspect_git_readiness", return_value=Mock(kind="ready")),
                patch("ai_orchestrator.pipeline.refresh_planning_source_index", return_value=expected) as refresh_index,
            ):
                result = pipeline.refresh_planning_index(docs)

            timeout = PLANNING_INDEX_TIMEOUT_SECONDS
            ensure_repository.assert_called_once_with(non_interactive=True, timeout_seconds=timeout)
            list_project_files.assert_called_once_with(docs.resolve(), non_interactive=True, timeout_seconds=timeout)
            head.assert_called_once_with(repo.resolve(), non_interactive=True, timeout_seconds=timeout)
            refresh_index.assert_called_once_with(
                docs.resolve(),
                pipeline.store.root,
                repo.resolve(),
                "a" * 40,
                candidate_paths=[document],
                excluded_roots=((repo / ".ai_auto_work" / "worktree").resolve(),),
                timeout_seconds=timeout,
            )
            self.assertIs(result, expected)

    def test_excludes_selected_tasks_from_planned_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline = Pipeline(Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=root), execution=ExecutionConfig(), agents=()))
            state = RunState(
                id="run-1",
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.PLANNED,
                tasks=[
                    WorkTask("skip", "제외", ["general"]),
                    WorkTask("keep", "유지", ["general"]),
                ],
            )
            pipeline.store.save(state)

            updated = pipeline.exclude_tasks(state.id, ["skip", "skip"])

            self.assertEqual([task.id for task in updated.tasks], ["keep"])
            self.assertEqual([task.id for task in pipeline.status(state.id).tasks], ["keep"])
            self.assertEqual(updated.stage, Stage.PLANNED)
            self.assertEqual(updated.plan_revision, 1)
            self.assertFalse(updated.plan_is_approved)
            self.assertIn("tasks excluded from execution plan: skip", updated.events[-1].message)

    def test_updates_and_confirms_task_plan_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=root),
                    execution=ExecutionConfig(),
                    agents=(
                        AgentConfig("worker", ("general", "backend"), (sys.executable, "-c", "pass"), 2, provider_id="local"),
                    ),
                    routing=RoutingConfig(default_provider="local"),
                )
            )
            state = RunState(
                id="run-review",
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.PLANNED,
                plan_revision=1,
                tasks=[
                    WorkTask(
                        "old-task",
                        "기존 Task",
                        ["general"],
                        description="기존 작업을 수행한다.",
                        acceptance_criteria=["기존 작업이 검증된다."],
                        expected_paths=["src/**"],
                        verify_commands=[["python", "-m", "unittest"]],
                    )
                ],
            )
            pipeline.store.save(state)

            with self.assertRaisesRegex(PipelineError, "reviewed and confirmed"):
                pipeline.execute(state.id)

            updated = pipeline.update_plan(
                state.id,
                [
                    {
                        "id": "backend-task",
                        "title": "Backend Task 수정",
                        "description": "수정한 Backend 작업을 수행한다.",
                        "capabilities": ["backend"],
                        "depends_on": [],
                        "acceptance_criteria": ["수정 결과가 검증된다."],
                        "expected_paths": ["src/backend/**"],
                        "forbidden_paths": ["vendor/**"],
                        "verify_commands": [["python", "-m", "unittest"]],
                        "risk_level": "high",
                        "provider_id": "local",
                        "model": "",
                        "reasoning_effort": "",
                    }
                ],
            )

            self.assertEqual(updated.plan_revision, 2)
            self.assertFalse(updated.plan_is_approved)
            self.assertEqual(updated.tasks[0].id, "backend-task")
            self.assertEqual(updated.tasks[0].agent_id, "worker")

            confirmed = pipeline.confirm_plan(state.id)

            self.assertEqual(confirmed.plan_approved_revision, 2)
            self.assertTrue(confirmed.plan_is_approved)

    def test_update_plan_rejects_invalid_dependency_graph(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=root),
                    execution=ExecutionConfig(),
                    agents=(
                        AgentConfig("worker", ("general",), (sys.executable, "-c", "pass"), 2, provider_id="local"),
                    ),
                    routing=RoutingConfig(default_provider="local"),
                )
            )
            state = RunState(
                id="invalid-plan",
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.PLANNED,
                tasks=[WorkTask("old", "기존", ["general"])],
            )
            pipeline.store.save(state)
            draft = {
                "title": "Task",
                "description": "Task 설명",
                "capabilities": ["general"],
                "acceptance_criteria": ["검증된다."],
                "expected_paths": ["src/**"],
                "forbidden_paths": [],
                "verify_commands": [["python", "-m", "unittest"]],
                "risk_level": "medium",
                "provider_id": "local",
                "model": "",
                "reasoning_effort": "",
            }

            with self.assertRaisesRegex(PipelineError, "cyclic task dependency"):
                pipeline.update_plan(
                    state.id, [{**draft, "id": "first", "depends_on": ["second"]}, {**draft, "id": "second", "depends_on": ["first"]}]
                )

    def test_excluding_tasks_preserves_dependency_and_nonempty_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline = Pipeline(Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=root), execution=ExecutionConfig(), agents=()))
            state = RunState(
                id="run-1",
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.PLANNED,
                tasks=[
                    WorkTask("base", "기반", ["general"]),
                    WorkTask("dependent", "후속", ["general"], dependencies=["base"]),
                ],
            )
            pipeline.store.save(state)

            with self.assertRaisesRegex(PipelineError, "remaining tasks depend on excluded tasks"):
                pipeline.exclude_tasks(state.id, ["base"])
            with self.assertRaisesRegex(PipelineError, "cannot exclude every task"):
                pipeline.exclude_tasks(state.id, ["base", "dependent"])

            self.assertEqual([task.id for task in pipeline.status(state.id).tasks], ["base", "dependent"])

    def test_lists_only_available_capability_compatible_provider_choices(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=root),
                execution=ExecutionConfig(),
                agents=(
                    AgentConfig("codex-backend", ("backend",), (sys.executable, "-c", "pass"), max_tasks=4, provider_id="codex"),
                    AgentConfig("codex-general", ("general",), (sys.executable, "-c", "pass"), max_tasks=6, provider_id="codex"),
                    AgentConfig("claude-ai", ("general", "planning"), (sys.executable, "-c", "pass"), provider_id="claude", model="sonnet"),
                    AgentConfig("missing-ai", ("general", "planning"), ("missing-provider-executable",), provider_id="missing"),
                ),
                planning=PlanningConfig(agent_id="codex-general"),
            )
            sdk = connected_codex_sdk()
            sdk.account_status.return_value = CodexSdkAccountStatus(True, "chatgpt", "ChatGPT 구독 로그인")
            pipeline = Pipeline(config, codex_sdk=sdk)

            with patch.object(pipeline, "_claude_auth_status", return_value=(True, "claude_subscription", "로그인됨")):
                planning = pipeline.planning_provider_choices()
                execution = pipeline.execution_provider_choices(["backend"])

        self.assertEqual([(choice.provider_id, choice.agent_id) for choice in planning], [("codex", "codex-general"), ("claude", "claude-ai")])
        self.assertTrue(planning[0].is_default)
        self.assertEqual(
            [(choice.provider_id, choice.agent_id) for choice in execution],
            [("claude", "claude-ai"), ("codex", "codex-backend"), ("codex", "codex-general")],
        )
        self.assertEqual({choice.agent_id: choice.max_tasks for choice in execution}, {"codex-backend": 4, "codex-general": 6, "claude-ai": 1})

    def test_update_main_requires_approval_and_fast_forward_pull(self) -> None:
        root = Path.cwd()
        config = Config(
            path=root / "orchestrator.toml",
            project=ProjectConfig(repo=root, main_branch="main", remote="upstream"),
            execution=ExecutionConfig(),
            agents=(),
        )
        pipeline = Pipeline(config)

        snapshot = Mock(changes=(), sync=Mock())
        with (
            patch.object(pipeline.git, "update_main_ff_only", return_value=("a" * 40, "b" * 40)) as update_main,
            patch.object(pipeline, "_main_changes_locked", return_value=snapshot),
        ):
            with self.assertRaisesRegex(ApprovalRequired, "explicit approval"):
                pipeline.update_main()
            update_main.assert_not_called()

            result = pipeline.update_main(approved=True)

        update_main.assert_called_once_with("upstream", ignored_untracked_roots=(pipeline.store.root,))
        self.assertEqual(result.before_commit, "a" * 40)
        self.assertEqual(result.after_commit, "b" * 40)
        self.assertTrue(result.changed)

        with patch("ai_orchestrator.git.run_command") as run:
            pipeline.git.pull_ff_only("upstream")
        run.assert_called_once_with(
            ["git", "pull", "--ff-only", "upstream", "main"], root, non_interactive=True, timeout_seconds=REMOTE_GIT_TIMEOUT_SECONDS
        )

    def test_main_change_snapshot_rejects_content_changed_after_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=repo),
                    execution=ExecutionConfig(),
                    agents=(),
                )
            )
            target = repo / "value.txt"
            target.write_text("reviewed\n", encoding="utf-8")
            snapshot = pipeline.main_changes()
            remote_failure = pipeline.main_changes(refresh_remote=True)
            self.assertEqual(remote_failure.sync.relation, "unknown")
            self.assertTrue(remote_failure.sync.error)
            self.assertEqual([item.path for item in remote_failure.changes], ["value.txt"])
            target.write_text("changed after review\n", encoding="utf-8")

            with self.assertRaisesRegex(PipelineError, "검토 후 Main"):
                pipeline.commit_main_changes(snapshot.snapshot_id, [("value.txt", "whole")], "reviewed change", approved=True)

            refreshed = pipeline.main_changes()
            result = pipeline.commit_main_changes(
                refreshed.snapshot_id, [("value.txt", "whole")], "reviewed change", approved=True
            )

            self.assertTrue(result.commit_created)
            self.assertEqual(result.remaining_change_count, 0)
            self.assertEqual(run_command(["git", "show", f"{result.commit}:value.txt"], repo).stdout, "changed after review\n")

    def test_selected_planning_provider_is_used_for_clarification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "requirements.md"
            spec.write_text("알림 기능을 계획한다.", encoding="utf-8")
            agents = (
                AgentConfig("codex-planner", ("general", "planning"), (sys.executable, "-c", "pass"), provider_id="codex"),
                AgentConfig("claude-planner", ("general", "planning"), (sys.executable, "-c", "pass"), provider_id="claude", model="sonnet"),
            )
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=agents,
                planning=PlanningConfig(agent_id="codex-planner", max_attempts=1),
            )
            pipeline = Pipeline(config, codex_sdk=connected_codex_sdk())
            response = (
                'AI_PLAN_RESULT: {"summary":"확인 필요","server_work":false,"source_paths":[],"tasks":[],"questions":["범위를 알려주세요."]}'
            )

            with (
                patch.object(pipeline, "_invoke_planning_agent", return_value=response) as invoke,
                patch.object(pipeline, "_claude_auth_status", return_value=(True, "claude_subscription", "Claude 구독 로그인")),
            ):
                state = pipeline.start(spec, planning_agent_id="claude-planner", planning_reasoning_effort="max")
                first_agent = invoke.call_args.args[1]
                first_effort = state.planning_reasoning_effort
                state = pipeline.clarify_text(state.id, "API만 구현합니다.", planning_agent_id="codex-planner", planning_reasoning_effort="xhigh")
                second_agent = invoke.call_args.args[1]

        self.assertEqual(first_agent.id, "claude-planner")
        self.assertEqual(first_effort, "max")
        self.assertEqual(second_agent.id, "codex-planner")
        self.assertEqual(state.planning_agent_id, "codex-planner")
        self.assertEqual(state.planning_provider_id, "codex")
        self.assertEqual(state.planning_reasoning_effort, "xhigh")

    def test_applies_task_agent_override_and_reassigns_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agents = (
                AgentConfig("codex-ai", ("general", "backend", "review"), (sys.executable, "-c", "pass"), provider_id="codex"),
                AgentConfig("claude-ai", ("general", "backend", "review"), (sys.executable, "-c", "pass"), provider_id="claude", model="sonnet"),
            )
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=root),
                execution=ExecutionConfig(),
                agents=agents,
                routing=RoutingConfig(default_provider="codex", review_required=True),
            )
            pipeline = Pipeline(config, codex_sdk=connected_codex_sdk())
            state = RunState(
                id="run-1",
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.PLANNED,
                tasks=[
                    WorkTask(
                        id="backend",
                        title="API 구현",
                        capabilities=["backend"],
                        agent_id="codex-ai",
                        provider_id="codex",
                        reviewer_agent_id="claude-ai",
                        reviewer_provider_id="claude",
                        review_status=ReviewStatus.PENDING,
                    )
                ],
            )
            pipeline.store.save(state)

            pipeline._apply_task_agent_overrides(state, {"backend": "claude-ai"})
            pipeline._validate_task_model_overrides(state, {"backend": "claude-opus-5"}, {})
            pipeline._validate_task_reasoning_overrides(state, {"backend": "max"}, {}, {"backend": "claude-opus-5"})
            pipeline._apply_task_model_overrides(state, {"backend": "claude-opus-5"})
            pipeline._apply_task_reasoning_overrides(state, {"backend": "max"})

        task = state.tasks[0]
        self.assertEqual(task.agent_id, "claude-ai")
        self.assertEqual(task.provider_id, "claude")
        self.assertEqual(task.model, "claude-opus-5")
        self.assertEqual(task.reasoning_effort, "max")
        self.assertEqual(task.reviewer_agent_id, "codex-ai")
        self.assertEqual(task.reviewer_provider_id, "codex")
        self.assertTrue(any("claude/claude-ai" in event.message for event in state.events))
        self.assertIn("reasoning selected: max", state.events[-1].message)

    def test_start_snapshots_planning_document_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "planning"
            nested = spec / "context"
            nested.mkdir(parents=True)
            (spec / "01-plan.md").write_text("## 작업\n\n- [general] 결과 생성\n", encoding="utf-8")
            (nested / "02-background.txt").write_text("배경 문서\n\n추가 배경 원문", encoding="utf-8")
            (spec / "ignored.md").write_text("# 무관 문서\n\n무관한 상세 원문", encoding="utf-8")
            prompt_record = root / "planning-prompt.md"
            plan_payload = {
                "summary": "planning cwd",
                "server_work": False,
                "source_paths": ["01-plan.md", "context/02-background.txt"],
                "tasks": [
                    {
                        "id": "result",
                        "title": "결과 생성",
                        "description": "선택한 문서를 기준으로 결과를 생성한다.",
                        "capabilities": ["general"],
                        "depends_on": [],
                        "acceptance_criteria": ["결과가 생성된다"],
                        "expected_paths": ["result.txt"],
                        "forbidden_paths": [],
                        "verify_commands": [["python", "-m", "compileall", "-q", "src"]],
                        "risk_level": "low",
                    }
                ],
                "questions": [],
            }
            planner_script = (
                "import json, sys; from pathlib import Path; "
                "prompt=sys.stdin.read(); "
                f"Path({str(prompt_record)!r}).write_text(prompt, encoding='utf-8'); "
                f"payload={plan_payload!r}; "
                "payload['summary']=str(Path.cwd()); "
                "print('AI_PLAN_RESULT: '+json.dumps(payload))"
            )
            planner = AgentConfig(
                "planner",
                ("planning",),
                (sys.executable, "-c", planner_script),
                1,
                provider_id="local",
                review_command=(sys.executable, "-c", planner_script),
            )
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(planner, AgentConfig("worker", ("general",), (), 1)),
                planning=PlanningConfig(agent_id="planner", max_attempts=1),
            )

            state = Pipeline(config).start(spec)

            self.assertEqual(state.stage, Stage.PLANNED)
            self.assertEqual(state.spec_path, str(spec.resolve()))
            self.assertEqual(Path(state.summary).resolve(), repo.resolve())
            prompt = prompt_record.read_text(encoding="utf-8")
            self.assertIn("No active root `AGENTS.md`", prompt)
            self.assertIn("Return `instruction_paths` as an empty array", prompt)
            self.assertIn(spec.resolve().as_posix(), prompt)
            self.assertIn("Full index JSON:", prompt)
            self.assertIn("`rg -n -i -C 3`", prompt)
            self.assertIn("Never print or load the complete index", prompt)
            self.assertIn('"path":"context/02-background.txt"', prompt)
            self.assertIn('"title":"배경 문서"', prompt)
            self.assertIn('"path":"ignored.md"', prompt)
            self.assertNotIn("추가 배경 원문", prompt)
            self.assertNotIn("무관한 상세 원문", prompt)
            self.assertNotIn("Request-related document context", prompt)
            snapshot = Path(state.spec_snapshot_path).read_text(encoding="utf-8")
            self.assertIn("Source: `01-plan.md`", snapshot)
            self.assertIn("Source: `context/02-background.txt`", snapshot)
            self.assertNotIn("Source: `ignored.md`", snapshot)
            selection = repo / ".ai-orchestrator" / "runs" / state.id / "planning-sources" / "selection-1"
            manifest = json.loads((selection / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual([item["source_path"] for item in manifest["documents"]], ["01-plan.md", "context/02-background.txt"])
            selection_digest = hashlib.sha256()
            for item in manifest["documents"]:
                copied = Path(item["snapshot_path"])
                source = spec.joinpath(*item["source_path"].split("/"))
                self.assertEqual(copied.read_bytes(), source.read_bytes())
                digest = hashlib.sha256(source.read_bytes()).hexdigest()
                self.assertEqual(item["source_sha256"], digest)
                selection_digest.update(item["source_path"].encode("utf-8"))
                selection_digest.update(b"\0")
                selection_digest.update(digest.encode("ascii"))
                selection_digest.update(b"\0")
            self.assertEqual(state.spec_digest, selection_digest.hexdigest())
            plan = json.loads(Path(state.structured_plan_path).read_text(encoding="utf-8"))
            self.assertEqual(plan["source_paths"], plan_payload["source_paths"])
            index_snapshot = json.loads((repo / ".ai-orchestrator" / "runs" / state.id / "planning-source-index.json").read_text(encoding="utf-8"))
            self.assertEqual(
                [item["relative_path"] for item in index_snapshot["documents"]], ["01-plan.md", "context/02-background.txt", "ignored.md"]
            )

    def test_workspace_cleanup_requires_merged_clean_task_and_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "requirements.md"
            spec.write_text("## 작업\n\n- [general] 결과 생성\n", encoding="utf-8")
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(auto_commit=True, verify_commands=((sys.executable, "-c", "raise SystemExit(0)"),)),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
            pipeline = Pipeline(config)
            state = pipeline.start(spec)
            state.workspace_mode = ExecutionWorkspaceMode.ISOLATED
            pipeline.store.save(state)
            state = pipeline.confirm_plan(state.id)
            state = pipeline.execute(state.id, manual=True)
            task = state.tasks[0]
            Path(task.worktree, "result.txt").write_text("done\n", encoding="utf-8")
            state = pipeline.complete_task(state.id, task.id)

            active = pipeline.workspace_statuses(state.id)[0]

            self.assertEqual(active.state, WorkspaceState.ACTIVE)
            self.assertFalse(active.cleanup_safe)
            state = pipeline.verify(state.id)
            state = pipeline.merge(state.id, approved=True)

            status = pipeline.workspace_statuses(state.id)[0]

            self.assertEqual(status.state, WorkspaceState.STALE)
            self.assertTrue(status.cleanup_safe)
            self.assertTrue(status.worktree_registered)
            self.assertTrue(status.branch_merged)
            with pipeline.store.lock(state.id, "test"):
                locked = pipeline.workspace_statuses(state.id)[0]
                self.assertEqual(locked.state, WorkspaceState.ACTIVE)
                self.assertFalse(locked.cleanup_safe)
            with self.assertRaises(ApprovalRequired):
                pipeline.cleanup_workspace(state.id, task.id, approved=False)

            cleaned = pipeline.cleanup_workspace(state.id, task.id, approved=True)

            self.assertEqual(cleaned.state, WorkspaceState.CLEANED)
            self.assertFalse(cleaned.cleanup_safe)
            self.assertFalse(Path(task.worktree).exists())
            self.assertFalse(pipeline.git.branch_exists(task.branch))
            saved = pipeline.status(state.id)
            self.assertIn("worktree and branch cleaned", saved.events[-1].message)

    def test_workspace_statuses_are_bounded_parallel_and_keep_task_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=root),
                    execution=ExecutionConfig(),
                    agents=(AgentConfig("manual", ("general",), (), 1),),
                )
            )
            state = RunState(
                id="workspace-status",
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.EXECUTING,
                tasks=[
                    WorkTask("first", "첫 Task", ["general"]),
                    WorkTask("second", "둘째 Task", ["general"]),
                ],
            )
            pipeline.store.save(state)
            barrier = threading.Barrier(2)

            def status_result(_state: RunState, task: WorkTask, _registered: object, **_kwargs: object) -> str:
                barrier.wait(timeout=2)
                return task.id

            with (
                patch.object(pipeline.git, "ensure_repository") as ensure,
                patch.object(pipeline.git, "list_worktrees", return_value=[]) as list_worktrees,
                patch.object(pipeline, "_workspace_status", side_effect=status_result) as workspace_status,
            ):
                statuses = pipeline.workspace_statuses(state.id)

            self.assertEqual(statuses, ["first", "second"])
            self.assertTrue(ensure.call_args.kwargs["non_interactive"])
            self.assertGreater(ensure.call_args.kwargs["timeout_seconds"], 0)
            self.assertTrue(list_worktrees.call_args.kwargs["non_interactive"])
            self.assertGreater(list_worktrees.call_args.kwargs["timeout_seconds"], 0)
            self.assertEqual(workspace_status.call_count, 2)
            self.assertTrue(all(call.kwargs["non_interactive"] for call in workspace_status.call_args_list))
            self.assertTrue(all(isinstance(call.kwargs["deadline"], float) for call in workspace_status.call_args_list))

    def test_workspace_cleanup_refuses_dirty_merged_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline, state = self._merged_manual_run(root, repo)
            task = state.tasks[0]
            Path(task.worktree, "uncommitted.txt").write_text("keep\n", encoding="utf-8")

            status = pipeline.workspace_statuses(state.id)[0]

            self.assertEqual(status.state, WorkspaceState.UNSAFE)
            self.assertFalse(status.cleanup_safe)
            self.assertIn("uncommitted", status.reason)
            with self.assertRaisesRegex(PipelineError, "not safe"):
                pipeline.cleanup_workspace(state.id, task.id, approved=True)
            self.assertTrue(Path(task.worktree).exists())
            self.assertTrue(pipeline.git.branch_exists(task.branch))

    def test_task_preparation_reuses_interrupted_clean_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "requirements.md"
            spec.write_text("## 작업\n\n- [general] 결과 생성\n", encoding="utf-8")
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
            pipeline = Pipeline(config)
            state = pipeline.start(spec)
            state.workspace_mode = ExecutionWorkspaceMode.ISOLATED
            pipeline.store.save(state)
            state = pipeline.confirm_plan(state.id)
            task = state.tasks[0]
            branch = f"ai/{state.id}/{task.id}"
            worktree = pipeline._run_worktree_root(state) / task.id
            pipeline.git.ensure_managed_workspace_excluded(worktree.parent.parent)
            pipeline.git.create_worktree(worktree, branch)

            resumed = pipeline.execute(state.id, manual=True)

            self.assertEqual(resumed.stage, Stage.EXECUTING)
            self.assertEqual(resumed.tasks[0].status, TaskStatus.WAITING)
            self.assertEqual(resumed.tasks[0].branch, branch)
            self.assertEqual(Path(resumed.tasks[0].worktree).resolve(), worktree.resolve())
            self.assertEqual([entry.path for entry in pipeline.git.list_worktrees()].count(worktree.resolve()), 1)

    def test_task_execution_ignores_only_untracked_state_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            git(repo, "init", "-b", "main")
            git(repo, "config", "user.email", "test@example.com")
            git(repo, "config", "user.name", "Test")
            (repo / "README.md").write_text("initial\n", encoding="utf-8")
            git(repo, "add", "README.md")
            git(repo, "commit", "-m", "initial")
            spec = root / "requirements.md"
            spec.write_text("## 작업\n\n- [general] 결과 생성\n", encoding="utf-8")
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
            pipeline = Pipeline(config)
            state = pipeline.confirm_plan(pipeline.start(spec).id)

            self.assertEqual(run_command(["git", "status", "--porcelain"], repo).stdout.strip(), "?? .ai-orchestrator/")
            executed = pipeline.execute(state.id, manual=True)

            self.assertEqual(executed.stage, Stage.EXECUTING)
            self.assertEqual(executed.tasks[0].status, TaskStatus.WAITING)
            self.assertTrue(Path(executed.tasks[0].worktree).is_dir())

    def test_task_execution_git_preflight_is_bounded_and_noninteractive(self) -> None:
        root = Path.cwd()
        config = Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=root), execution=ExecutionConfig(), agents=())
        pipeline = Pipeline(config)

        with patch.object(pipeline.git, "ensure_clean") as ensure_clean, patch.object(pipeline.git, "ensure_main_branch") as ensure_main:
            pipeline._ensure_main_worktree_ready()

        ensure_clean.assert_called_once_with(
            ignored_untracked_roots=(pipeline.store.root,), non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
        )
        ensure_main.assert_called_once_with(non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)

    def test_task_executor_bounds_git_calls_before_and_after_agent(self) -> None:
        root = Path.cwd()
        agent = AgentConfig("worker", ("general",), (sys.executable, "-c", "print('unused')"), provider_id="local")
        pipeline = Pipeline(
            Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=root), execution=ExecutionConfig(auto_commit=True), agents=(agent,))
        )
        task = WorkTask(
            id="bounded-git",
            title="Bound Git calls",
            capabilities=["general"],
            agent_id=agent.id,
            worktree=str(root),
            status=TaskStatus.RUNNING,
            verify_commands=[["dotnet", "test", "tests/Example.Tests.csproj"]],
        )
        state = RunState(
            id="bounded-git-run", spec_path="", spec_digest="digest", repo_path=str(root), main_branch="main", stage=Stage.EXECUTING, tasks=[task]
        )
        pipeline.dotnet_executable = "C:/SDK/dotnet.exe"
        legacy_prompt = pipeline._with_task_worktree_contract("Implement the task.")

        with (
            patch.object(pipeline.store, "save"),
            patch.object(pipeline.git, "head", side_effect=["before", "before", "after"]) as head,
            patch.object(pipeline, "_invoke_agent", return_value="implemented") as invoke_agent,
            patch.object(pipeline.git, "task_changed_paths", return_value=["result.txt"]) as changed_paths,
            patch.object(pipeline.git, "commit_all") as commit_all,
        ):
            pipeline._run_executor(state, task, legacy_prompt, root / "task.log", "feat(bounded-git): result", TaskAction.EXECUTE)

        self.assertEqual(head.call_count, 3)
        for call in head.call_args_list:
            self.assertTrue(call.kwargs["non_interactive"])
            self.assertEqual(call.kwargs["timeout_seconds"], LOCAL_GIT_TIMEOUT_SECONDS)
        commit_all.assert_called_once_with(root, "feat(bounded-git): result", non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        invoke_agent.assert_called_once()
        changed_paths.assert_called_once_with(root, "before", non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        execution_prompt = invoke_agent.call_args.args[3]
        self.assertIn("## Orchestrator worktree contract", execution_prompt)
        self.assertIn("## Execution efficiency", execution_prompt)
        self.assertIn("Start with the expected change paths and\n  their direct references", execution_prompt)
        self.assertEqual(execution_prompt.count("Do not repeat a successful check"), 1)
        self.assertIn("## Project-configured .NET executable", execution_prompt)
        self.assertIn('"C:/SDK/dotnet.exe"', execution_prompt)
        self.assertIn('"tests/Example.Tests.csproj"', execution_prompt)
        self.assertIn("supersedes bare `dotnet`", execution_prompt)
        self.assertTrue(execution_prompt.rstrip().endswith("The orchestrator owns those lifecycle\n  operations."))

    def test_task_prompt_ends_with_orchestrator_worktree_contract(self) -> None:
        root = Path.cwd()
        pipeline = Pipeline(Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=root), execution=ExecutionConfig(), agents=()))
        task = WorkTask(
            id="worktree-and-plan",
            title="별도 worktree와 구현 계획 준비",
            description=("feature/example 브랜치와 C:/Repo-example worktree를 만든다."),
            capabilities=["planning"],
            expected_paths=["docs/plans/example.md"],
            worktree=str(root),
        )
        state = RunState(
            id="worktree-contract-run",
            spec_path="",
            spec_digest="digest",
            repo_path=str(root),
            main_branch="main",
            stage=Stage.EXECUTING,
            tasks=[task],
        )

        prompt = pipeline._prompt(state, task, "중요: C:/Repo-example worktree를 먼저 생성한다.")

        contract_position = prompt.rfind("## Orchestrator worktree contract")
        self.assertGreater(contract_position, prompt.index("## Full planning document"))
        final_contract = prompt[contract_position:]
        self.assertIn("worktree already prepared and assigned by the orchestrator", final_contract)
        self.assertIn("treat that setup instruction as\n  already satisfied", final_contract)
        self.assertIn("Do not modify the main checkout", final_contract)
        self.assertIn("Do not commit, merge, push, or deploy", final_contract)
        self.assertIn("Start with the expected change paths and\n  their direct references", prompt)
        self.assertIn("Do not repeat a successful check unless affected code changed", prompt)
        self.assertIn("Stop once the acceptance criteria are met", prompt)
        self.assertEqual(prompt.count("Do not repeat a successful check"), 1)

    def test_codex_sdk_task_does_not_require_external_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "requirements.md"
            spec.write_text("## 작업\n\n- [general] 결과 생성\n", encoding="utf-8")
            agent = AgentConfig("codex-general", ("general",), (), provider_id="codex")
            pipeline = Pipeline(
                Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=(agent,)),
                codex_sdk=connected_codex_sdk(),
            )
            state = pipeline.confirm_plan(pipeline.start(spec).id)

            def complete_batch(_state: RunState, tasks: list[WorkTask], _resume_actions: dict[str, TaskAction]) -> None:
                for task in tasks:
                    task.status = TaskStatus.COMPLETED

            with patch.object(pipeline, "_run_task_batch", side_effect=complete_batch) as run_batch:
                executed = pipeline.execute(state.id)

            self.assertEqual(executed.stage, Stage.READY_TO_MERGE)
            self.assertEqual(executed.tasks[0].status, TaskStatus.COMPLETED)
            run_batch.assert_called_once()

    def test_next_dependent_task_is_visible_while_preflight_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "requirements.md"
            spec.write_text("## 작업\n\n- [general] 첫 작업\n", encoding="utf-8")
            agent = AgentConfig("codex-general", ("general",), (), provider_id="codex")
            pipeline = Pipeline(
                Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=(agent,)),
                codex_sdk=connected_codex_sdk(),
            )
            state = pipeline.start(spec)
            first = state.tasks[0]
            second = replace(
                first,
                id="next-dependent-task",
                title="다음 작업",
                dependencies=[first.id],
                conflict_dependencies=[],
                branch="",
                worktree="",
                started_commit="",
                completed_commit="",
                prompt_path="",
                log_path="",
                action_results=[],
            )
            state.tasks = [first, second]
            state.refresh_task_readiness()
            pipeline.store.save(state)
            state = pipeline.confirm_plan(state.id)
            observed: list[tuple[str, TaskStatus, str, RunExecutionSituation, str]] = []

            def inspect_preflight(_state: RunState, task: WorkTask) -> None:
                current, control = pipeline.status_with_execution_control(state.id)
                saved_task = next(item for item in current.tasks if item.id == task.id)
                observed.append((task.id, saved_task.status, saved_task.progress_phase, control.situation, control.active_task_id))

            def complete_batch(current: RunState, tasks: list[WorkTask], _resume_actions: dict[str, TaskAction]) -> None:
                for task in tasks:
                    task.status = TaskStatus.COMPLETED
                    task.clear_progress()
                current.refresh_task_readiness()
                pipeline.store.save(current)

            with (
                patch.object(pipeline, "_preflight_task_environment", side_effect=inspect_preflight),
                patch.object(pipeline, "_run_task_batch", side_effect=complete_batch),
            ):
                executed = pipeline.execute(state.id)

            self.assertEqual([item[0] for item in observed], [first.id, second.id])
            for task_id, status, progress_phase, situation, active_task_id in observed:
                self.assertEqual(status, TaskStatus.RUNNING)
                self.assertEqual(progress_phase, "preparing_task")
                self.assertEqual(situation, RunExecutionSituation.RUNNING)
                self.assertEqual(active_task_id, task_id)
            self.assertEqual(executed.stage, Stage.READY_TO_MERGE)

    def test_resume_retries_agent_preflight_failure_with_pending_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "requirements.md"
            spec.write_text("## 작업\n\n- [general] 결과 생성\n", encoding="utf-8")
            agent = AgentConfig("codex-general", ("general",), (), provider_id="codex")
            pipeline = Pipeline(
                Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=(agent,)),
                codex_sdk=connected_codex_sdk(),
            )
            state = pipeline.confirm_plan(pipeline.start(spec).id)
            pipeline._prepare_tasks(state)
            state.fail_step(RunStep.AGENT_EXECUTION, "agents unavailable for execution: codex-general")
            pipeline.store.save(state)

            def complete_batch(_state: RunState, tasks: list[WorkTask], _resume_actions: dict[str, TaskAction]) -> None:
                for task in tasks:
                    task.status = TaskStatus.COMPLETED

            with patch.object(pipeline, "_run_task_batch", side_effect=complete_batch):
                resumed = pipeline.resume(state.id)

            self.assertEqual(resumed.stage, Stage.READY_TO_MERGE)
            self.assertEqual(resumed.tasks[0].status, TaskStatus.COMPLETED)
            self.assertIsNone(resumed.failed_step)
            self.assertEqual(resumed.failure_message, "")

    def test_task_preparation_refuses_workspace_with_commits_beyond_base(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "requirements.md"
            spec.write_text("## 작업\n\n- [general] 결과 생성\n", encoding="utf-8")
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
            pipeline = Pipeline(config)
            state = pipeline.start(spec)
            state.workspace_mode = ExecutionWorkspaceMode.ISOLATED
            pipeline.store.save(state)
            state = pipeline.confirm_plan(state.id)
            task = state.tasks[0]
            branch = f"ai/{state.id}/{task.id}"
            worktree = pipeline._run_worktree_root(state) / task.id
            pipeline.git.ensure_managed_workspace_excluded(worktree.parent.parent)
            pipeline.git.create_worktree(worktree, branch)
            Path(worktree, "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
            git(worktree, "add", "unexpected.txt")
            git(worktree, "commit", "-m", "unexpected")

            with self.assertRaisesRegex(GitError, "commits beyond base"):
                pipeline.execute(state.id, manual=True)

            failed = pipeline.status(state.id)
            self.assertEqual(failed.stage, Stage.FAILED)
            self.assertEqual(failed.failed_step, RunStep.TASK_PREPARATION)

    def test_task_log_reads_only_registered_task_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log_path = root / "task.log"
            log_path.write_text("agent output\n", encoding="utf-8")
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=root),
                execution=ExecutionConfig(),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
            pipeline = Pipeline(config)
            state = RunState(
                id="run-log",
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.EXECUTING,
                tasks=[
                    WorkTask(id="task-1", title="task", capabilities=["general"], log_path=str(log_path))
                ],
            )
            pipeline.store.save(state)

            self.assertEqual(pipeline.task_log(state.id, "task-1"), "agent output\n")
            with self.assertRaisesRegex(PipelineError, "unknown task"):
                pipeline.task_log(state.id, "missing")

    def test_task_log_returns_bounded_tail_for_large_existing_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log_path = root / "large-task.log"
            log_path.write_text("old entry\n" + ("x" * (TASK_LOG_DISPLAY_LIMIT_BYTES + 100)) + "\nlatest entry\n", encoding="utf-8")
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=root),
                    execution=ExecutionConfig(),
                    agents=(AgentConfig("manual", ("general",), (), 1),),
                )
            )
            state = RunState(
                id="large-run-log",
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.EXECUTING,
                tasks=[
                    WorkTask(id="task-1", title="task", capabilities=["general"], log_path=str(log_path))
                ],
            )
            pipeline.store.save(state)

            displayed = pipeline.task_log(state.id, "task-1")

            self.assertIn("최근 64 KiB만 표시합니다", displayed)
            self.assertIn(str(log_path), displayed)
            self.assertTrue(displayed.endswith("latest entry\n"))
            self.assertNotIn("old entry", displayed)
            self.assertLess(len(displayed.encode("utf-8")), TASK_LOG_DISPLAY_LIMIT_BYTES + 1024)

    def test_structured_planning_clarification_replans_same_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "requirements.txt"
            spec.write_text("사용자에게 알림 기능이 필요하다.", encoding="utf-8")
            planner_script = (
                "import json, sys; prompt=sys.stdin.read(); "
                "answered=('비동기 조회' in prompt or "
                "'### Previous structured plan' in prompt); "
                "payload=({'summary':'알림 기능','server_work':True,'tasks':["
                "{'id':'notification-api','title':'알림 API 구현',"
                "'description':'사용자별 알림 조회 API를 구현한다.',"
                "'capabilities':['backend','api'],'depends_on':[],"
                "'acceptance_criteria':['사용자는 자신의 알림만 조회한다'],"
                "'expected_paths':['src/api/**'],'forbidden_paths':[],"
                "'verify_commands':[['python','-m','unittest']],"
                "'risk_level':'medium'}],"
                "'questions':[]} if answered else "
                "{'summary':'알림 기능','server_work':True,'tasks':[],"
                "'questions':['실시간 알림인가요, 비동기 조회인가요?']}); "
                "print('AI_PLAN_RESULT: '+json.dumps(payload, ensure_ascii=False))"
            )
            planner = AgentConfig(
                "planner",
                ("planning",),
                (sys.executable, "-c", planner_script),
                2,
                provider_id="local",
                review_command=(sys.executable, "-c", planner_script),
            )
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(
                    planner,
                    AgentConfig("worker", ("general", "backend", "api"), (sys.executable, "-c", "print('worker')"), 2, provider_id="local"),
                ),
                planning=PlanningConfig(agent_id="planner", max_attempts=2),
            )
            pipeline = Pipeline(config)

            state = pipeline.start(spec)

            self.assertEqual(state.stage, Stage.NEEDS_CLARIFICATION)
            self.assertEqual(state.planning_questions, ["실시간 알림인가요, 비동기 조회인가요?"])
            self.assertEqual(state.tasks, [])
            with self.assertRaisesRegex(PipelineError, "must not be empty"):
                pipeline.clarify_text(state.id, "  \n")
            answers = root / "answers.md"
            answers.write_text("비동기 조회 방식으로 구현한다.", encoding="utf-8")

            state = pipeline.clarify(state.id, answers)

            self.assertEqual(state.stage, Stage.PLANNED)
            self.assertEqual(state.planning_questions, [])
            self.assertEqual(state.tasks[0].id, "notification-api")
            self.assertEqual(state.tasks[0].agent_id, "worker")
            self.assertEqual(state.planning_attempts, 2)
            self.assertEqual(len(state.clarification_paths), 1)
            self.assertEqual(Path(state.clarification_paths[0]).read_text(encoding="utf-8"), "비동기 조회 방식으로 구현한다.")
            self.assertTrue(Path(state.structured_plan_path).exists())
            self.assertEqual(
                [message.role for message in state.planning_messages],
                [PlanningMessageRole.ASSISTANT, PlanningMessageRole.USER, PlanningMessageRole.ASSISTANT],
            )
            self.assertIn("실시간 알림인가요", state.planning_messages[0].text)

            state = pipeline.confirm_plan(state.id)

            self.assertTrue(state.plan_is_approved)

            state = pipeline.apply_planning_conversation(state.id, message="권한 검증을 완료 조건에서 특히 강조해 주세요.")

            self.assertEqual(state.stage, Stage.PLANNED)
            self.assertFalse(state.plan_is_approved)
            self.assertEqual(len(state.clarification_paths), 2)
            self.assertEqual(len(state.planning_messages), 5)
            self.assertEqual(state.planning_messages[-2].text, "권한 검증을 완료 조건에서 특히 강조해 주세요.")
            conversation_context = pipeline._clarification_context(state)
            self.assertIn("### Previous structured plan", conversation_context)
            self.assertIn("### Saved Planning conversation", conversation_context)
            self.assertIn('"notification-api"', conversation_context)
            self.assertIn("권한 검증을 완료 조건", conversation_context)
            self.assertIn("실시간 알림인가요", conversation_context)
            self.assertIn("비동기 조회 방식으로", conversation_context)
            state.stage = Stage.EXECUTING
            pipeline.store.save(state)
            with pipeline.store.lock(state.id, "execute"):
                pipeline.send_planning_message(state.id, "후속 Task에는 감사 로그도 포함해 주세요.")
                with patch.object(pipeline, "_build_plan", return_value=Plan(summary=state.summary, server_work=False, tasks=deepcopy(state.tasks))):
                    executing = pipeline.send_planning_message(state.id, "지금까지 내용을 Task에 적용해줘.")
            self.assertEqual(executing.stage, Stage.EXECUTING)
            self.assertEqual(executing.planning_follow_up_requests, [])
            self.assertEqual(executing.planning_messages[-1].text, "지금까지 내용을 Task에 적용해줘.")
            self.assertIsNotNone(pipeline.planning_apply_preview(state.id))

    def test_completed_result_discussion_preserves_results_and_rejects_direct_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "requirements.md"
            spec.write_text("저장된 결과를 논의한다.", encoding="utf-8")
            planner = AgentConfig("planner", ("planning", "docs"), (sys.executable, "-c", "print('unused')"), 2,
                                  provider_id="local", review_command=(sys.executable, "-c", "print('unused')"))
            pipeline = Pipeline(Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=repo),
                                       execution=ExecutionConfig(), agents=(planner,), planning=PlanningConfig(agent_id="planner")))
            for stage in (Stage.VERIFIED, Stage.WORK_BRANCH_PUSHED, Stage.MERGED, Stage.PUSHED, Stage.DEPLOYED):
                with self.subTest(stage=stage):
                    state = RunState(id=f"result-chat-{stage.value}", spec_path=str(spec), spec_digest="digest", repo_path=str(repo),
                                     main_branch="main", stage=stage, spec_snapshot_path=str(spec), planning_agent_id="planner",
                                     planning_provider_id="local", plan_revision=2, plan_approved_revision=2,
                                     tasks=[WorkTask(id="done", title="완료된 기능", capabilities=["docs"], status=TaskStatus.COMPLETED)])
                    state.refresh_task_readiness()
                    pipeline.store.save(state)
                    original = state.to_dict()
                    with patch.object(pipeline, "_invoke_planning_agent", return_value="결과를 보존하며 개선 방법을 논의합니다.") as invoked:
                        chatted = pipeline.send_planning_message(state.id, "버튼이 작아 보이는데 어떻게 하면 좋을까?")
                    invoked.assert_called_once()
                    for name in ("stage", "tasks", "plan_revision", "plan_approved_revision", "base_commit"):
                        self.assertEqual(chatted.to_dict()[name], original[name], name)
                    self.assertEqual(chatted.planning_messages[-1].text, "결과를 보존하며 개선 방법을 논의합니다.")
                    prompt = next((pipeline.store.run_dir(state.id) / "prompts").glob("planning-chat-*.md")).read_text(encoding="utf-8")
                    self.assertIn("Saved result evidence", prompt)
                    self.assertIn("Do not edit files", prompt)
                    saved = pipeline.store.load(state.id).to_dict()
                    with self.assertRaisesRegex(PipelineError, "결과 화면"):
                        pipeline.send_planning_message(state.id, "지금까지 내용을 Task에 적용해줘")
                    self.assertEqual(pipeline.store.load(state.id).to_dict(), saved)

    def test_archived_chat_continues_after_cleanup_without_mutating_preserved_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state = pipeline.execute(state.id, manual=True)
            worktree = Path(state.execution_worktree)
            state.stage = Stage.PUSHED
            state.active_step = None
            state.tasks[0].status = TaskStatus.COMPLETED
            state.tasks[0].active_action = None
            state.tasks[0].completed_commit = pipeline.git.head(worktree)
            state.planning_agent_id = "worker"
            pipeline._append_planning_user_message(state, "처음 요청")
            pipeline._append_planning_assistant_message(state, "완료했습니다.")
            pipeline.store.save_planning_chat(state)
            pipeline.store.save(state)
            policy = pipeline.store.load_effort_policy(state.id)
            pipeline.store.set_effort_mode(
                state.id, "balanced", target="planning", expected_revision=policy.revision, request_id=str(uuid.uuid4()),
            )
            plan = pipeline.archive_plan(state.id)
            archived = pipeline.archive_run(
                state.id, expected_revision=str(plan["expected_revision"]), fingerprint=str(plan["fingerprint"]),
                request_id=str(uuid.uuid4()), approved=True,
            )
            self.assertFalse(worktree.exists())
            run_dir = pipeline.store.run_dir(state.id)
            preserved = {path: path.read_bytes() for path in run_dir.rglob("*") if path.is_file()}
            original = archived.to_dict()
            head = pipeline.git.head(pipeline.repo)
            for message in ("완료한 내용을 설명해줘", "지금까지 내용을 Task에 적용해줘"):
                with patch.object(pipeline, "_invoke_provider_command", return_value="기록을 보존하며 다음 작업을 논의합니다.") as invoked:
                    chatted = pipeline.send_planning_message(state.id, message)
                invoked.assert_called_once()
                agent = invoked.call_args.kwargs["agent"]
                self.assertEqual((agent.review_sandbox_mode, agent.review_approval_mode), ("read-only", "deny-all"))
                self.assertEqual(chatted.planning_messages[-2].text, message)
                self.assertEqual(chatted.planning_messages[-1].text, "기록을 보존하며 다음 작업을 논의합니다.")
                for name in ("stage", "tasks", "archive", "plan_revision", "plan_approved_revision", "base_commit"):
                    self.assertEqual(chatted.to_dict()[name], original[name], name)
                self.assertEqual(pipeline.store.load(state.id).planning_messages[-1].text, chatted.planning_messages[-1].text)
            with patch.object(pipeline, "_invoke_provider_command", side_effect=PipelineError("mock provider unavailable")):
                with self.assertRaisesRegex(PipelineError, "mock provider unavailable"):
                    pipeline.send_planning_message(state.id, "실패도 숨기지 마세요")
            self.assertEqual(pipeline.store.load(state.id).planning_messages[-1].text, "실패도 숨기지 마세요")
            for path, content in preserved.items():
                self.assertEqual(path.read_bytes(), content, str(path.relative_to(run_dir)))
            self.assertTrue(pipeline.store.archived_planning_chat_path(state.id).is_file())
            self.assertFalse(worktree.exists())
            self.assertEqual(pipeline.git.head(pipeline.repo), head)
            self.assertEqual(pipeline.list_summaries("active"), [])
            self.assertEqual([item.id for item in pipeline.list_summaries("archived")], [state.id])

    def test_execution_planning_chat_uses_sidecar_without_mutating_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "requirements.md"
            spec.write_text("문서를 수정한다.", encoding="utf-8")
            planner = AgentConfig(
                "planner",
                ("planning", "docs"),
                (sys.executable, "-c", "print('unused')"),
                2,
                provider_id="local",
                review_command=(sys.executable, "-c", "print('unused')"),
            )
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(planner,),
                planning=PlanningConfig(agent_id="planner", max_attempts=2),
            )
            pipeline = Pipeline(config)
            state = RunState(
                id="executing-chat",
                spec_path=str(spec),
                spec_digest="digest",
                repo_path=str(repo),
                main_branch="main",
                stage=Stage.EXECUTING,
                spec_snapshot_path=str(spec),
                planning_agent_id="planner",
                planning_provider_id="local",
                tasks=[
                    WorkTask(id="docs", title="문서 수정", capabilities=["docs"], status=TaskStatus.RUNNING,
                             progress_phase="provider_retry_wait",
                             progress_detail='{"retry_index":1,"max_retries":4,"retry_at":"2099-01-01T00:00:00Z"}')
                ],
                plan_revision=2,
                plan_approved_revision=2,
            )
            state.begin_step(RunStep.AGENT_EXECUTION)
            state.refresh_task_readiness()
            pipeline.store.save(state)
            original_tasks = state.to_dict()["tasks"]

            with (
                pipeline.store.lock(state.id, "execute"),
                patch.object(pipeline, "_invoke_planning_agent", return_value="현재 문서 Task를 실행하고 있습니다."),
                patch.object(pipeline, "_build_plan", return_value=Plan(summary="문서 수정", server_work=False, tasks=deepcopy(state.tasks))),
            ):
                chatted = pipeline.send_planning_message(state.id, "지금 어떤 작업을 하고 있어?")
                follow_up = pipeline.send_planning_message(state.id, "지금까지 이야기한 내용을 후속 Task에 적용해줘.")

            self.assertEqual(chatted.planning_messages[-1].text, "현재 문서 Task를 실행하고 있습니다.")
            self.assertEqual(follow_up.to_dict()["tasks"], original_tasks)
            self.assertEqual(follow_up.plan_revision, 2)
            self.assertEqual(follow_up.plan_approved_revision, 2)
            self.assertEqual(follow_up.planning_follow_up_requests, [])
            self.assertIsNotNone(pipeline.planning_apply_preview(state.id))
            self.assertTrue(pipeline.store.planning_chat_path(state.id).is_file())
            persisted_main = json.loads(pipeline.store.state_path(state.id).read_text(encoding="utf-8"))
            self.assertEqual(persisted_main["planning_messages"], [])
            restored = pipeline.status(state.id)
            self.assertEqual(restored.planning_messages, follow_up.planning_messages)

    def test_execution_planning_chat_uses_sidecar_during_startup_race(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "requirements.md"
            spec.write_text("문서를 수정한다.", encoding="utf-8")
            planner = AgentConfig(
                "planner",
                ("planning", "docs"),
                (sys.executable, "-c", "print('unused')"),
                2,
                provider_id="local",
                review_command=(sys.executable, "-c", "print('unused')"),
            )
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(planner,),
                planning=PlanningConfig(agent_id="planner", max_attempts=2),
            )
            pipeline = Pipeline(config)
            state = RunState(
                id="starting-chat",
                spec_path=str(spec),
                spec_digest="digest",
                repo_path=str(repo),
                main_branch="main",
                stage=Stage.PLANNED,
                spec_snapshot_path=str(spec),
                planning_agent_id="planner",
                planning_provider_id="local",
                tasks=[
                    WorkTask(id="docs", title="문서 수정", capabilities=["docs"], status=TaskStatus.PENDING)
                ],
                plan_revision=1,
                plan_approved_revision=1,
            )
            state.refresh_task_readiness()
            pipeline.store.save(state)

            with (
                pipeline.store.lock(state.id, "execute"),
                patch.object(pipeline, "_invoke_planning_agent", return_value="Task 실행을 시작하고 있습니다."),
            ):
                chatted = pipeline.send_planning_message(state.id, "지금 시작된 거야?")

            self.assertEqual(chatted.stage, Stage.PLANNED)
            self.assertEqual(chatted.planning_messages[-1].text, "Task 실행을 시작하고 있습니다.")
            self.assertTrue(pipeline.store.planning_chat_path(state.id).is_file())
            persisted_main = json.loads(pipeline.store.state_path(state.id).read_text(encoding="utf-8"))
            self.assertEqual(persisted_main["planning_messages"], [])

    def test_clarification_updates_saved_planning_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            spec = root / "requirements.md"
            snapshot = root / "planning-document.md"
            spec.write_text("알림 기능", encoding="utf-8")
            snapshot.write_text("알림 기능", encoding="utf-8")
            planner = AgentConfig("planner", ("planning",), (), provider_id="codex")
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=root),
                execution=ExecutionConfig(),
                agents=(planner,),
                planning=PlanningConfig(agent_id="planner", max_attempts=1),
            )
            pipeline = Pipeline(config, codex_sdk=connected_codex_sdk())
            state = RunState(
                id="run-1",
                spec_path=str(spec),
                spec_digest="abc",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.NEEDS_CLARIFICATION,
                spec_snapshot_path=str(snapshot),
                planning_questions=["어떤 알림인가요?"],
            )
            pipeline.store.save(state)
            follow_up = Plan(summary="추가 확인 필요", server_work=False, tasks=[], questions=["푸시 알림도 포함할까요?"])

            with patch.object(pipeline, "_build_plan", return_value=follow_up):
                updated = pipeline.clarify_text(state.id, "인앱 알림입니다.", planning_model="gpt-5.6-terra", planning_reasoning_effort="ultra")
                preserved = pipeline.clarify_text(state.id, "푸시 알림은 제외합니다.")
                preserved.stage = Stage.FAILED
                preserved.failed_step = RunStep.PLANNING
                pipeline.store.save(preserved)
                recovered = pipeline.apply_planning_conversation(state.id, message="방금 요청을 반영해 계획을 다시 만들어 주세요.")

            self.assertEqual(updated.planning_model, "gpt-5.6-terra")
            self.assertEqual(updated.planning_reasoning_effort, "ultra")
            self.assertEqual(updated.planning_profile_source, ProfileSource.MANUAL)
            self.assertEqual(preserved.planning_model, "gpt-5.6-terra")
            self.assertEqual(preserved.planning_reasoning_effort, "ultra")
            self.assertEqual(pipeline.store.load(state.id).planning_model, "gpt-5.6-terra")
            self.assertEqual(pipeline.store.load(state.id).planning_reasoning_effort, "ultra")
            self.assertEqual(recovered.stage, Stage.NEEDS_CLARIFICATION)
            self.assertEqual(len(recovered.clarification_paths), 3)

    def test_planning_model_override_normalizes_provider_commands(self) -> None:
        codex = AgentConfig("planner", ("planning",), (), provider_id="codex")
        self.assertEqual(Pipeline._planning_command_with_model(codex, codex.command, "gpt-5.6-terra"), ())

        claude = AgentConfig("planner", ("planning",), ("claude", "-p", "prompt", "--model", "sonnet"), provider_id="claude")
        for model in ("opus", "claude-opus-5", "claude-opus-5-5", "fable", "claude-fable-5"):
            with self.subTest(model=model):
                self.assertEqual(Pipeline._planning_command_with_model(claude, claude.command, model), ("claude", "--model", model, "-p", "prompt"))

    def test_reasoning_override_normalizes_provider_commands(self) -> None:
        codex = AgentConfig("planner", ("planning",), (), provider_id="codex")
        self.assertEqual(Pipeline._command_with_reasoning_effort(codex, codex.command, "ultra", "gpt-5.6-sol"), ())

        claude = AgentConfig("planner", ("planning",), ("claude", "--effort=low", "-p", "prompt"), provider_id="claude")
        self.assertEqual(
            Pipeline._command_with_reasoning_effort(claude, claude.command, "max", "sonnet"), ("claude", "--effort", "max", "-p", "prompt")
        )

        with self.assertRaisesRegex(PipelineError, "unsupported reasoning"):
            Pipeline._command_with_reasoning_effort(codex, codex.command, "ultra", "gpt-5.6-luna")

        pipeline = Pipeline(
            Config(path=Path("orchestrator.toml"), project=ProjectConfig(repo=Path.cwd()), execution=ExecutionConfig(), agents=(codex,))
        )
        state = RunState(id="run-1", spec_path="plan.md", spec_digest="abc", repo_path=str(Path.cwd()), main_branch="main", stage=Stage.EXECUTING)
        task = WorkTask(
            id="task-1",
            title="구현",
            capabilities=["general"],
            agent_id=codex.id,
            provider_id=codex.provider_id,
            model="gpt-5.6-sol",
            reasoning_effort="max",
            worktree=str(Path.cwd()),
            prompt_path="prompt.md",
        )
        with patch.object(pipeline, "_invoke_provider_command", return_value="done") as invoke:
            pipeline._invoke_agent(state, task, codex, "prompt", Path("task.log"), TaskAction.EXECUTE)
            execute_call = invoke.call_args
            pipeline._invoke_agent(state, task, codex, "prompt", Path("review.log"), TaskAction.REVIEW)
            review_call = invoke.call_args

        self.assertEqual(execute_call.kwargs["command_template"], ())
        self.assertEqual(execute_call.kwargs["model"], "gpt-5.6-sol")
        self.assertEqual(execute_call.kwargs["reasoning_effort"], "max")
        self.assertEqual(review_call.kwargs["command_template"], ())

    def test_claude_planning_session_flags_are_orchestrator_owned(self) -> None:
        claude = AgentConfig("planner", ("planning",), ("claude", "-p", "prompt"), provider_id="claude")
        session_id = "3b79eb26-4234-48b8-bb8c-f9d0b0c731b1"

        self.assertEqual(
            Pipeline._command_with_claude_session(claude, claude.command, session_id, resume=False),
            ("claude", "--session-id", session_id, "-p", "prompt"),
        )
        self.assertEqual(
            Pipeline._command_with_claude_session(claude, claude.command, session_id, resume=True), ("claude", "--resume", session_id, "-p", "prompt")
        )
        with self.assertRaisesRegex(PipelineError, "must not define session"):
            Pipeline._command_with_claude_session(claude, ("claude", "--continue", "-p", "prompt"), session_id, resume=True)
        with self.assertRaisesRegex(PipelineError, "valid UUID"):
            Pipeline._command_with_claude_session(claude, claude.command, "not-a-session", resume=False)

        pipeline = Pipeline(
            Config(
                path=Path("orchestrator.toml"),
                project=ProjectConfig(repo=Path.cwd()),
                execution=ExecutionConfig(),
                agents=(claude,),
                planning=PlanningConfig(agent_id=claude.id),
            )
        )
        state = RunState(
            id="claude-session-command",
            spec_path="plan.md",
            spec_digest="abc",
            repo_path=str(Path.cwd()),
            main_branch="main",
            stage=Stage.PLANNED,
            planning_agent_id=claude.id,
            planning_provider_id=claude.provider_id,
        )
        with patch.object(pipeline, "_invoke_provider_command", return_value="답변") as invoke:
            result = pipeline._invoke_planning_agent(
                state, claude, "질문", Path("planning-chat.md"), Path("planning-chat.log"), claude_session_id=session_id, resume_claude_session=True
            )

        self.assertEqual(result, "답변")
        self.assertEqual(invoke.call_args.kwargs["command_template"], ("claude", "--resume", session_id, "-p", "prompt"))

    def test_claude_oauth_expiry_has_actionable_provider_error(self) -> None:
        claude = AgentConfig("claude-ai", ("planning",), ("claude", "-p", "prompt"), provider_id="claude")
        custom = AgentConfig("custom-ai", ("planning",), ("custom",), provider_id="custom")
        log_path = Path("planning-chat.log")
        output = "Failed to authenticate. API Error: 401 OAuth access token has expired. Re-authenticate to continue."

        claude_message = Pipeline._provider_command_failure_message(claude, 1, output, log_path)
        custom_message = Pipeline._provider_command_failure_message(custom, 1, output, log_path)

        self.assertIn("Claude 로그인이 만료", claude_message)
        self.assertIn("claude auth login", claude_message)
        self.assertNotIn("OAuth access token", claude_message)
        self.assertEqual(custom_message, "agent custom-ai exited with 1; see planning-chat.log")

    def test_structured_planner_retries_invalid_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "requirements.md"
            spec.write_text("문서를 수정한다.", encoding="utf-8")
            flag = root / "planner-attempted"
            planner_script = (
                "import json, sys; from pathlib import Path; sys.stdin.read(); "
                f"flag=Path({str(flag)!r}); first=not flag.exists(); "
                "flag.write_text('done', encoding='utf-8'); "
                "payload={'summary':'문서 수정','server_work':False,'tasks':["
                "{'id':'docs','title':'문서 수정','description':'README를 수정한다.',"
                "'capabilities':['docs'],'depends_on':[],"
                "'acceptance_criteria':['사용법이 설명된다'],"
                "'expected_paths':['README.md'],'forbidden_paths':[],"
                "'verify_commands':[['python','-m','compileall','-q','src']],"
                "'risk_level':'low'}],'questions':[]}; "
                "print('invalid' if first else "
                "'AI_PLAN_RESULT: '+json.dumps(payload, ensure_ascii=False))"
            )
            planner = AgentConfig(
                "planner",
                ("planning", "docs"),
                (sys.executable, "-c", planner_script),
                2,
                provider_id="local",
                review_command=(sys.executable, "-c", planner_script),
            )
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(planner,),
                planning=PlanningConfig(agent_id="planner", max_attempts=2),
            )

            state = Pipeline(config).start(spec)

            self.assertEqual(state.stage, Stage.PLANNED)
            self.assertEqual(state.planning_attempts, 2)
            self.assertEqual(state.tasks[0].id, "docs")

    def test_sdk_unavailable_stops_planning_without_schema_retry_and_preserves_cause(self) -> None:
        for info in (None, "serverOverloaded", {"httpConnectionFailed": {"httpStatusCode": 503}}):
            with self.subTest(info=info), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                repo = self._repository(root)
                spec = root / "requirements.md"
                spec.write_text("문서를 수정한다.", encoding="utf-8")
                planner = AgentConfig("planner", ("planning", "docs"), (), 2, provider_id="codex", review_command=())
                config = Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(),
                                agents=(planner,), planning=PlanningConfig(agent_id="planner", max_attempts=3))
                message = "Selected model is at capacity. Please try a different model." if info is None else "upstream overloaded"
                failure = CodexSdkError(message, error_info=info, additional_details="provider detail")
                sdk = connected_codex_sdk()
                sdk.run_turn.side_effect = failure
                pipeline = Pipeline(config, codex_sdk=sdk)
                expected = "AI 서버가 일시적으로 응답하지 않습니다" if isinstance(info, dict) else "선택한 AI 모델이 혼잡합니다"
                with self.assertRaisesRegex(PlanningError, expected) as caught:
                    pipeline.start(spec)
                sdk.run_turn.assert_called_once()
                self.assertIsInstance(caught.exception.__cause__, ProviderCapacityError)
                self.assertIs(caught.exception.__cause__.__cause__, failure)
                failed = pipeline.store.list_runs()[0]
                self.assertEqual(failed.stage, Stage.FAILED)
                self.assertEqual(failed.planning_attempts, 1)
                self.assertIn(message, failed.failure_message)
                self.assertEqual(pipeline.store.inspect_lock(failed.id).state, RunLockState.UNLOCKED)

    def test_sdk_request_limit_stops_planning_without_schema_retry(self) -> None:
        for message, info, details, expected in (
            ("exceeded retry limit, last status: 429 Too Many Requests", None, None, "AI 요청이 제한되었습니다"),
            ("upstream failed", "rateLimitExceeded", None, "AI 요청이 제한되었습니다"),
            ("upstream failed", {"httpConnectionFailed": {"httpStatusCode": 429}}, None, "AI 요청이 제한되었습니다"),
            ("HTTP 429", "usageLimitExceeded", None, "AI 사용 한도에 도달했습니다"),
            ("HTTP 429", None, '{"error":{"code":"insufficient_quota"}}', "AI 사용 한도에 도달했습니다"),
        ):
            with self.subTest(message=message, info=info), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                repo = self._repository(root)
                spec = root / "requirements.md"
                spec.write_text("문서를 수정한다.", encoding="utf-8")
                planner = AgentConfig("planner", ("planning", "docs"), (), 2, provider_id="codex", review_command=())
                config = Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(),
                                agents=(planner,), planning=PlanningConfig(agent_id="planner", max_attempts=3))
                failure = CodexSdkError(message, error_info=info, additional_details=details)
                sdk = connected_codex_sdk()
                sdk.run_turn.side_effect = failure
                pipeline = Pipeline(config, codex_sdk=sdk)
                with self.assertRaisesRegex(PlanningError, expected) as caught:
                    pipeline.start(spec)
                sdk.run_turn.assert_called_once()
                self.assertIsInstance(caught.exception.__cause__, ProviderRequestLimitError)
                self.assertIs(caught.exception.__cause__.__cause__, failure)
                failed = pipeline.store.list_runs()[0]
                self.assertEqual(failed.stage, Stage.FAILED)
                self.assertEqual(failed.planning_attempts, 1)
                self.assertIn(message, failed.failure_message)
                self.assertIn(expected, failed.failure_message)
                self.assertEqual(pipeline.store.inspect_lock(failed.id).state, RunLockState.UNLOCKED)

    def test_sdk_planning_retry_continues_same_thread_with_correction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "requirements.md"
            spec.write_text("문서를 수정한다.", encoding="utf-8")
            planner = AgentConfig("planner", ("planning", "docs"), (), 2, provider_id="codex", review_command=())
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(planner,),
                planning=PlanningConfig(agent_id="planner", max_attempts=2),
            )
            valid = (
                'AI_PLAN_RESULT: {"summary":"문서 수정",'
                '"server_work":false,"source_paths":[],"instruction_paths":[],'
                '"tasks":[{"id":"docs","title":"문서 수정",'
                '"description":"README를 수정한다.","capabilities":["docs"],'
                '"depends_on":[],"acceptance_criteria":["사용법이 설명된다"],'
                '"expected_paths":["README.md"],"forbidden_paths":[],'
                '"verify_commands":[["python","-m","compileall","-q","src"]],'
                '"risk_level":"low"}],"questions":[]}'
            )
            codex_sdk = connected_codex_sdk()
            codex_sdk.run_turn.side_effect = ["invalid", valid]
            codex_sdk.account_status.return_value = CodexSdkAccountStatus(True, "chatgpt", "로그인됨")
            pipeline = Pipeline(config, codex_sdk=codex_sdk)

            state = pipeline.start(spec)

            self.assertEqual(state.stage, Stage.PLANNED)
            self.assertEqual(state.planning_attempts, 2)
            requests = [call.args[0] for call in codex_sdk.run_turn.call_args_list]
            self.assertEqual([request.conversation_id for request in requests], [f"planning:{state.id}", f"planning:{state.id}"])
            self.assertIn("Structured implementation planning", requests[0].prompt)
            self.assertIn("Continue the same Planning conversation", requests[1].prompt)
            self.assertNotIn("Structured implementation planning", requests[1].prompt)
            self.assertLess(len(requests[1].prompt), len(requests[0].prompt))
            codex_sdk.close_conversation.assert_not_called()

    def test_sdk_technology_option_retry_supplies_a_valid_shape_and_preserves_failure_if_not_corrected(self) -> None:
        valid_payload = {
            "summary": "로컬 메모 앱 기술 구성",
            "server_work": False,
            "tasks": [],
            "questions": [],
            "source_paths": [],
            "instruction_paths": [],
            "tech_stack_options": [{
                "option_id": "python-desktop", "label": "Python desktop", "recommendation_rank": 1,
                "components": {"languages": ["Python"], "runtimes": ["Python"]},
                "version_policy": ["지원되는 버전을 고정"], "requirement_fit": ["로컬 메모를 오프라인에서 보관"],
                "tradeoffs": ["배포 패키징 검증 필요"], "unresolved_constraints": [], "required_external_dependencies": [],
            }],
        }
        valid_output = "AI_PLAN_RESULT: " + json.dumps(valid_payload, ensure_ascii=False)
        invalid_payload = json.loads(json.dumps(valid_payload))
        invalid_payload["tech_stack_options"][0]["requirement_fit"] = {"reason": "로컬 실행"}
        invalid_output = "AI_PLAN_RESULT: " + json.dumps(invalid_payload, ensure_ascii=False)
        for corrected in (True, False):
            with self.subTest(corrected=corrected), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                repo = self._repository(root)
                planner = AgentConfig("planner", ("planning", "general"), (), 2, provider_id="codex", review_command=())
                config = Config(
                    path=root / "orchestrator.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(),
                    agents=(planner,), planning=PlanningConfig(agent_id="planner", max_attempts=2),
                )
                sdk = connected_codex_sdk()
                sdk.run_turn.side_effect = [invalid_output, valid_output if corrected else invalid_output]
                pipeline = Pipeline(config, codex_sdk=sdk)
                prepared = pipeline.prepare_planning(
                    "", planning_mode="directed", planning_request="로컬 메모 앱을 계획해 주세요.", repository_intent="new_project",
                )
                if corrected:
                    state = pipeline.run_planning(prepared.id)
                    self.assertEqual(state.greenfield_phase, "options_ready")
                    self.assertEqual(state.current_tech_stack_decision().options[0].requirement_fit, ["로컬 메모를 오프라인에서 보관"])
                else:
                    with self.assertRaisesRegex(PlanningError, "failed after 2 attempts: .*requirement_fit"):
                        pipeline.run_planning(prepared.id)
                    state = pipeline.store.load(prepared.id)
                    self.assertEqual(state.stage, Stage.FAILED)
                    self.assertIn("requirement_fit", state.failure_message)
                    self.assertIsNone(state.current_tech_stack_decision())
                self.assertEqual(state.tasks, [])
                self.assertEqual(state.planning_attempts, 2)
                requests = [item.args[0] for item in sdk.run_turn.call_args_list]
                self.assertEqual(requests[0].conversation_id, requests[1].conversation_id)
                self.assertIn("requirement_fit must be an array", requests[1].prompt)
                self.assertNotIn("Structured implementation planning", requests[1].prompt)
                for request in requests:
                    example = next(line for line in request.prompt.splitlines() if line.startswith("AI_PLAN_RESULT:"))
                    payload = json.loads(example.removeprefix("AI_PLAN_RESULT:"))
                    self.assertIsInstance(payload["tech_stack_options"][0]["requirement_fit"], list)

    def test_sdk_planning_chat_and_apply_continue_existing_thread(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "requirements.md"
            spec.write_text("문서를 수정한다.", encoding="utf-8")
            command = ()
            planner = AgentConfig("planner", ("planning", "docs"), command, 2, provider_id="codex", model="gpt-test", review_command=command)
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(planner,),
                planning=PlanningConfig(agent_id="planner", max_attempts=2),
            )
            first = (
                'AI_PLAN_RESULT: {"summary":"문서 수정",'
                '"server_work":false,"source_paths":[],"instruction_paths":[],'
                '"tasks":[{"id":"docs","title":"문서 수정",'
                '"description":"README를 수정한다.","capabilities":["docs"],'
                '"depends_on":[],"acceptance_criteria":["사용법이 설명된다"],'
                '"expected_paths":["README.md"],"forbidden_paths":[],'
                '"verify_commands":[["python","-m","compileall","-q","src"]],'
                '"risk_level":"low"}],"questions":[]}'
            )
            second = first.replace("문서 수정", "문서 수정 제외", 1)
            codex_sdk = connected_codex_sdk()
            codex_sdk.run_turn.side_effect = [first, "제외할 경우 README Task가 사라집니다.", second]
            codex_sdk.has_conversation.return_value = True
            pipeline = Pipeline(config, codex_sdk=codex_sdk)
            planned = pipeline.start(spec)

            chatted = pipeline.send_planning_message(planned.id, "README 작업은 제외하면 어떻게 되나요?")
            updated = pipeline.send_planning_message(planned.id, "지금까지 대화한 내용을 Task에 적용해줘.")

            self.assertEqual(chatted.stage, Stage.PLANNED)
            self.assertEqual(chatted.tasks[0].title, "문서 수정")
            self.assertEqual(chatted.planning_messages[-1].text, "제외할 경우 README Task가 사라집니다.")
            self.assertEqual(updated.stage, Stage.PLANNED)
            self.assertEqual(updated.summary, "문서 수정")
            candidate = pipeline.planning_apply_preview(planned.id)
            self.assertIsNotNone(candidate)
            applied = pipeline.apply_planning_preview(
                planned.id, preview_id=candidate["preview_id"], fingerprint=candidate["fingerprint"],
                candidate_digest=candidate["candidate_digest"],
            )["run"]
            self.assertEqual(applied.summary, "문서 수정 제외")
            requests = [call.args[0] for call in codex_sdk.run_turn.call_args_list]
            self.assertEqual(len(requests), 3)
            for request in requests:
                self.assertIn("Provider `codex`", request.prompt)
                self.assertIn("agents can be reused without a total Task limit", request.prompt)

            self.assertEqual(requests[0].conversation_id, requests[1].conversation_id)
            self.assertNotEqual(requests[1].conversation_id, requests[2].conversation_id)
            self.assertTrue(requests[2].conversation_id.startswith("planning-preview:"))
            self.assertIn("Structured implementation planning", requests[0].prompt)
            self.assertIn("README 작업은 제외하면 어떻게 되나요?", requests[1].prompt)
            self.assertIn("Continue the existing Planning conversation", requests[1].prompt)
            self.assertNotIn("Structured implementation planning", requests[1].prompt)
            self.assertIn("Materialize the decisions", requests[2].prompt)
            self.assertIn("README 작업은 제외하면 어떻게 되나요?", requests[2].prompt)
            self.assertNotIn("Task에 적용해줘", requests[2].prompt)
            self.assertNotIn("Structured implementation planning", requests[2].prompt)
            codex_sdk.close_conversation.assert_not_called()

    def test_claude_planning_chat_restores_then_resumes_same_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "planning-document.md"
            snapshot.write_text("알림 기능 기획", encoding="utf-8")
            planner_command = (sys.executable, "-c", "pass")
            planner = AgentConfig(
                "claude-planner", ("planning", "docs"), planner_command, provider_id="claude", model="sonnet", review_command=planner_command
            )
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=root),
                execution=ExecutionConfig(),
                agents=(planner,),
                planning=PlanningConfig(agent_id=planner.id, max_attempts=2),
            )
            pipeline = Pipeline(config)
            state = RunState(
                id="claude-chat",
                spec_path=str(snapshot),
                spec_digest="abc",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.PLANNED,
                spec_snapshot_path=str(snapshot),
                planning_agent_id=planner.id,
                planning_provider_id=planner.provider_id,
                planning_model="sonnet",
            )
            pipeline.store.save(state)

            with patch.object(pipeline, "_invoke_planning_agent", side_effect=["첫 답변", "두 번째 답변", "모델 변경 답변"]) as invoke:
                first = pipeline.send_planning_message(state.id, "검증 조건을 같이 정리해줘.")
                second = pipeline.send_planning_message(state.id, "그중 첫 번째 조건을 자세히 설명해줘.")
                changed = pipeline.send_planning_message(state.id, "opus 관점에서 다시 검토해줘.", planning_model="opus")

            first_call, second_call, changed_call = invoke.call_args_list
            session_id = first.planning_claude_session_id
            self.assertEqual(str(uuid.UUID(session_id)), session_id)
            self.assertEqual(first_call.kwargs["claude_session_id"], session_id)
            self.assertFalse(first_call.kwargs["resume_claude_session"])
            self.assertIn("Restore a saved Planning conversation", first_call.args[2])
            self.assertEqual(second_call.kwargs["claude_session_id"], session_id)
            self.assertTrue(second_call.kwargs["resume_claude_session"])
            self.assertIn("Continue the existing Planning conversation", second_call.args[2])
            self.assertNotIn("Planning source snapshot", second_call.args[2])
            self.assertNotEqual(changed.planning_claude_session_id, session_id)
            self.assertFalse(changed_call.kwargs["resume_claude_session"])
            self.assertIn("Restore a saved Planning conversation", changed_call.args[2])

    def test_failed_first_claude_chat_does_not_persist_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / "planning-document.md"
            snapshot.write_text("알림 기능 기획", encoding="utf-8")
            planner_command = (sys.executable, "-c", "pass")
            planner = AgentConfig("claude-planner", ("planning",), planner_command, provider_id="claude", review_command=planner_command)
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=root),
                execution=ExecutionConfig(),
                agents=(planner,),
                planning=PlanningConfig(agent_id=planner.id),
            )
            pipeline = Pipeline(config)
            state = RunState(
                id="failed-claude-chat",
                spec_path=str(snapshot),
                spec_digest="abc",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.PLANNED,
                spec_snapshot_path=str(snapshot),
                planning_agent_id=planner.id,
                planning_provider_id=planner.provider_id,
            )
            pipeline.store.save(state)

            with patch.object(pipeline, "_invoke_planning_agent", side_effect=PipelineError("Claude failed")):
                with self.assertRaisesRegex(PipelineError, "Claude failed"):
                    pipeline.send_planning_message(state.id, "답변해줘.")

            failed = pipeline.store.load(state.id)
            self.assertEqual(failed.planning_claude_session_id, "")

    def test_claude_initial_planning_session_is_resumed_by_first_chat(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "requirements.md"
            spec.write_text("README를 수정한다.", encoding="utf-8")
            planner_command = (sys.executable, "-c", "pass")
            planner = AgentConfig(
                "claude-planner", ("planning", "docs"), planner_command, provider_id="claude", model="sonnet", review_command=planner_command
            )
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(planner,),
                planning=PlanningConfig(agent_id=planner.id, max_attempts=2, reuse_results=False),
            )
            result = (
                'AI_PLAN_RESULT: {"summary":"README 수정",'
                '"server_work":false,"source_paths":[],'
                '"instruction_paths":[],"tasks":[{"id":"docs",'
                '"title":"README 수정","description":"문서를 수정한다.",'
                '"capabilities":["docs"],"depends_on":[],'
                '"acceptance_criteria":["설명이 반영된다"],'
                '"expected_paths":["README.md"],"forbidden_paths":[],'
                '"verify_commands":[["python","-m","compileall",'
                '"-q","src"]],"risk_level":"low"}],'
                '"questions":[]}'
            )
            pipeline = Pipeline(config)

            with (
                patch.object(pipeline, "_invoke_planning_agent", side_effect=["invalid", result, "첫 채팅 답변"]) as invoke,
                patch.object(pipeline, "_claude_auth_status", return_value=(True, "claude_subscription", "Claude 구독 로그인")),
            ):
                planned = pipeline.start(spec)
                chatted = pipeline.send_planning_message(planned.id, "완료 조건을 설명해줘.")

            first_planning_call, correction_call, chat_call = invoke.call_args_list
            session_id = planned.planning_claude_session_id
            self.assertEqual(str(uuid.UUID(session_id)), session_id)
            self.assertEqual(first_planning_call.kwargs["claude_session_id"], session_id)
            self.assertFalse(first_planning_call.kwargs["resume_claude_session"])
            self.assertEqual(correction_call.kwargs["claude_session_id"], session_id)
            self.assertTrue(correction_call.kwargs["resume_claude_session"])
            self.assertIn("Continue the same Planning conversation", correction_call.args[2])
            self.assertEqual(chat_call.kwargs["claude_session_id"], session_id)
            self.assertTrue(chat_call.kwargs["resume_claude_session"])
            self.assertIn("Continue the existing Planning conversation", chat_call.args[2])
            self.assertNotIn("Planning source snapshot", chat_call.args[2])
            self.assertEqual(planned.planning_attempts, 2)
            self.assertEqual(chatted.planning_messages[-1].text, "첫 채팅 답변")

    def test_planning_apply_intent_requires_an_explicit_command(self) -> None:
        apply_messages = (
            "반영",
            "  반영해줘!!  ",
            "반영해 주세요~~~",
            "지금까지 내용을 Task에 적용해줘.",
            "이 방향으로 계획을 갱신해 주세요.",
            "논의한 내용으로 태스크 만들어줘",
            "Update the plan with this decision.",
        )
        chat_messages = (
            "반영하지 마",
            "‘반영’이라고 쓰면 돼?",
            "문서에만 반영해줘",
            "```\n반영\n```",
            "Task에 적용해줘 라고 하면 돼?",
            "계획에 반영하는 방법을 알려줘.",
            "계획을 바꾸면 어떤 영향이 있어?",
            "지금 방향이 괜찮은지 이야기해보자.",
        )

        for message in apply_messages:
            with self.subTest(message=message):
                self.assertTrue(Pipeline._planning_message_requests_apply(message))
        for message in chat_messages:
            with self.subTest(message=message):
                self.assertFalse(Pipeline._planning_message_requests_apply(message))

    def test_planning_apply_controls_are_distinct_from_inline_change_instructions(self) -> None:
        for message in (
            "반영", "반영해 주세요", "지금까지 내용을 Task에 적용해줘", "이 방향으로 계획을 갱신해 주세요.",
            "논의한 내용으로 태스크 만들어줘", "계획을 수정해줘", "Update the plan with this decision.",
            "정리한 검증 조건을 계획에 반영해 주세요.", "논의한 요구사항을 Task에 반영해줘",
        ):
            with self.subTest(control=message):
                self.assertTrue(Pipeline._planning_message_is_apply_control(message))
        for message in (
            "코덱스만 쓰는 걸로 태스크를 변경 해줘", "코덱스만 쓰는 걸로 테스크를 변경 해줘",
            "Claude만 쓰도록 Task를 변경해줘", "검증 조건을 추가해서 계획을 수정해줘",
            "Update the tasks to use Codex only.", "태스크를 변경하지 마", "태스크 변경하는 방법 알려줘", "‘계획을 수정해줘’라고 하면 돼?",
        ):
            with self.subTest(instruction=message):
                self.assertFalse(Pipeline._planning_message_is_apply_control(message))

    def test_inline_codex_request_reaches_preview_and_changes_profiles_only_after_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            codex = AgentConfig("codex-worker", ("general",), (), 2, provider_id="codex", model="gpt-6.1-sol")
            pipeline = Pipeline(replace(pipeline.config, agents=(*pipeline.config.agents, codex),
                                        planning=PlanningConfig(agent_id="worker", max_attempts=1)), codex_sdk=connected_codex_sdk())
            state.planning_agent_id = "worker"
            state.tasks[0].profile_source = ProfileSource.ROUTING
            state.planning_applied_conversation_revision = state.planning_conversation_revision
            pipeline.store.save(state)
            original = deepcopy(state.tasks)
            instruction = "코덱스만 쓰는 걸로 테스크를 변경 해줘"
            proposal = pipeline._task_plan_draft(state.tasks[0])
            proposal.update(provider_id="codex", model="gpt-6.1-sol", reasoning_effort="medium",
                            verify_commands=[[sys.executable, "-c", "pass"]])
            output = "AI_PLAN_RESULT: " + json.dumps({"summary": state.summary, "server_work": False,
                                                       "tasks": [proposal], "questions": []}, ensure_ascii=False)
            with patch.object(pipeline, "_invoke_planning_agent", return_value=output) as invoke:
                updated = pipeline.send_planning_message(state.id, instruction)
            self.assertIn(instruction, str(invoke.call_args))
            self.assertGreater(updated.planning_conversation_revision, state.planning_conversation_revision)
            self.assertEqual(updated.tasks, original)
            self.assertEqual(updated.stage, state.stage)
            self.assertEqual(sum(message.text == instruction for message in updated.planning_messages), 1)
            preview = pipeline.planning_apply_preview(state.id)
            self.assertIsNotNone(preview)
            self.assertTrue(preview["can_apply"])
            self.assertEqual(preview["changes"][0]["kind"], "modified")
            applied = pipeline.apply_planning_preview(
                state.id, preview_id=preview["preview_id"], fingerprint=preview["fingerprint"],
                candidate_digest=preview["candidate_digest"],
            )["run"]
            self.assertEqual((applied.tasks[0].agent_id, applied.tasks[0].provider_id), (codex.id, "codex"))
            self.assertEqual(applied.tasks[0].model, "gpt-6.1-sol")
            self.assertEqual(applied.tasks[0].status, TaskStatus.PENDING)
            self.assertEqual(applied.stage, Stage.PLANNED)

    def test_apply_without_new_discussion_stays_guarded_and_does_not_invent_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state.planning_applied_conversation_revision = state.planning_conversation_revision
            pipeline.store.save(state)
            before_revision = state.planning_conversation_revision
            with patch.object(pipeline, "_build_plan") as build:
                with self.assertRaisesRegex(PipelineError, "반영할 새 Planning 대화"):
                    pipeline.send_planning_message(state.id, "지금까지 내용을 Task에 적용해줘")
            build.assert_not_called()
            updated = pipeline.store.load(state.id)
            self.assertEqual(updated.planning_conversation_revision, before_revision)
            self.assertEqual(updated.tasks, state.tasks)

    def test_inline_change_survives_preview_failure_and_reaches_both_planning_contexts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state.planning_applied_conversation_revision = state.planning_conversation_revision
            pipeline.store.save(state)
            instruction = "검증 조건을 추가해서 계획을 수정해줘"
            with patch.object(pipeline, "_build_plan", side_effect=PipelineError("모의 제공자 오류")):
                with self.assertRaisesRegex(PipelineError, "모의 제공자 오류"):
                    pipeline.send_planning_message(state.id, instruction)
            saved = pipeline.store.load(state.id)
            self.assertIn(instruction, pipeline._clarification_context(saved))
            self.assertIn(instruction, pipeline._execution_follow_up_request(saved))
            self.assertEqual(saved.tasks, state.tasks)
            candidate = Plan(summary=state.summary, server_work=False, tasks=deepcopy(state.tasks))
            with patch.object(pipeline, "_build_plan", return_value=candidate) as build:
                replayed = pipeline.send_planning_message(state.id, "지금까지 내용을 Task에 적용해줘")
            self.assertIn(instruction, build.call_args.kwargs["clarification_context"])
            self.assertEqual(replayed.planning_conversation_revision, saved.planning_conversation_revision)
            self.assertEqual(sum(message.text == instruction for message in replayed.planning_messages), 1)
            self.assertIsNotNone(pipeline.planning_apply_preview(state.id))

    def test_inline_change_during_execution_preserves_completed_tasks_and_the_current_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state.stage = Stage.EXECUTING
            state.planning_applied_conversation_revision = state.planning_conversation_revision
            state.tasks[0].status = TaskStatus.COMPLETED
            state.tasks.append(WorkTask(id="next", title="남은 작업", capabilities=["general"], agent_id="worker", expected_paths=["next.txt"]))
            pipeline.store.save(state)
            state = pipeline.store.load(state.id)
            proposal = deepcopy(state.tasks)
            proposal[1].description = "새 검증 조건"
            instruction = "남은 태스크에 검증 조건을 추가해줘"
            with patch.object(pipeline, "_build_plan", return_value=Plan(summary=state.summary, server_work=False, tasks=proposal)) as build:
                updated = pipeline.send_planning_message(state.id, instruction)
            self.assertIn(instruction, build.call_args.kwargs["clarification_context"])
            self.assertIn(instruction, build.call_args.args[0].planning_follow_up_requests[-1])
            self.assertEqual(updated.tasks, state.tasks)
            self.assertEqual(updated.plan_revision, state.plan_revision)
            preview = pipeline.planning_apply_preview(state.id)
            self.assertFalse(preview["completed_task_rerun"])
            self.assertTrue(preview["can_apply"])

    def test_new_project_inline_change_uses_the_saved_revision_without_duplicate_control_text(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state.repository_intent = "new_project"
            state.planning_applied_conversation_revision = state.planning_conversation_revision
            pipeline.store.save(state)
            instruction = "코덱스만 쓰는 걸로 태스크를 변경 해줘"
            with patch.object(
                pipeline, "request_planning_conversation_apply", side_effect=lambda *_args, **_kwargs: pipeline.store.load(state.id)
            ) as apply:
                updated = pipeline.send_planning_message(state.id, instruction)
            self.assertEqual(apply.call_args.kwargs["conversation_revision"], updated.planning_conversation_revision)
            self.assertGreater(updated.planning_conversation_revision, state.planning_conversation_revision)
            self.assertEqual(apply.call_args.kwargs["control_message"], "")
            self.assertEqual(sum(message.text == instruction for message in updated.planning_messages), 1)

    def test_planning_apply_request_is_revision_safe_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state.planning_agent_id = "worker"
            pipeline._append_planning_user_message(state, "검증 조건을 한 개 추가해 주세요.")
            pipeline.store.save(state)
            expected_revision = state.plan_revision
            conversation_revision = state.planning_conversation_revision
            proposal = deepcopy(state.tasks)
            proposal[0].description = "검증 조건을 반영했다."
            with self.assertRaisesRegex(PipelineError, "대화가 변경"):
                pipeline.request_planning_conversation_apply(
                    state.id,
                    request_id="planning-apply-stale",
                    expected_revision=expected_revision,
                    conversation_revision=conversation_revision - 1,
                )
            with patch.object(
                pipeline,
                "_build_plan",
                return_value=Plan(summary=state.summary, server_work=False, tasks=proposal),
            ) as build:
                updated = pipeline.request_planning_conversation_apply(
                    state.id,
                    request_id="planning-apply-1",
                    expected_revision=expected_revision,
                    conversation_revision=conversation_revision,
                )
                replayed = pipeline.request_planning_conversation_apply(
                    state.id,
                    request_id="planning-apply-1",
                    expected_revision=expected_revision,
                    conversation_revision=conversation_revision,
                )

            self.assertEqual(build.call_count, 1)
            self.assertEqual(replayed.plan_revision, updated.plan_revision)
            result = updated.planning_apply_requests[-1]
            self.assertEqual(result.status, PlanningApplyStatus.SUCCEEDED)
            self.assertEqual(result.updated_tasks, 1)
            self.assertEqual(updated.planning_applied_conversation_revision, conversation_revision)
            duplicate_revision = pipeline.request_planning_conversation_apply(
                state.id,
                request_id="planning-apply-2",
                expected_revision=updated.plan_revision,
                conversation_revision=updated.planning_conversation_revision,
            )
            self.assertEqual(len(duplicate_revision.planning_apply_requests), 1)
            self.assertEqual(build.call_count, 1)

    def test_planning_preview_preserves_run_and_applies_saved_candidate_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            pipeline._append_planning_user_message(state, "완료 조건을 보강해 주세요.")
            pipeline.store.save(state)
            before = pipeline.store.load(state.id).to_dict()
            plan_before = Path(state.structured_plan_path).read_bytes()
            proposal = deepcopy(state.tasks)
            proposal[0].description = "완료 조건을 보강했습니다."
            request_id = str(uuid.uuid4())
            with patch.object(pipeline, "_build_plan", return_value=Plan(summary=state.summary, server_work=False, tasks=proposal)) as build:
                preview = pipeline.preview_planning_apply(state.id, request_id=request_id)
                replay = pipeline.preview_planning_apply(state.id, request_id=request_id)
            self.assertEqual(build.call_count, 1)
            self.assertEqual(preview, replay)
            self.assertEqual(preview["changes"][0]["kind"], "modified")
            self.assertEqual(pipeline.store.load(state.id).to_dict(), before)
            self.assertEqual(Path(state.structured_plan_path).read_bytes(), plan_before)
            applied = pipeline.apply_planning_preview(
                state.id, preview_id=preview["preview_id"], fingerprint=preview["fingerprint"],
                candidate_digest=preview["candidate_digest"],
            )
            self.assertEqual(applied["run"].tasks[0].description, "완료 조건을 보강했습니다.")
            self.assertEqual(applied["preview"]["actual"]["modified"], 1)
            again = pipeline.apply_planning_preview(
                state.id, preview_id=preview["preview_id"], fingerprint=preview["fingerprint"],
                candidate_digest=preview["candidate_digest"],
            )
            self.assertEqual(again["run"].plan_revision, applied["run"].plan_revision)

    def test_direction_change_is_idempotent_and_preserves_the_running_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state.stage = Stage.EXECUTING
            state.tasks[0].status = TaskStatus.RUNNING
            state.tasks[0].active_action = TaskAction.EXECUTE
            pipeline.store.save(state)
            before_tasks = deepcopy(pipeline.store.load(state.id).tasks)
            before_messages = len(pipeline.store.load(state.id).planning_messages)
            before_revision = state.plan_revision
            request_id = str(uuid.uuid4())

            accepted = pipeline.request_direction_change(state.id, request_id=request_id, text="다음 Task에서 로그를 추가해 주세요")
            replay = pipeline.request_direction_change(state.id, request_id=request_id, text="다음 Task에서 로그를 추가해 주세요")

            self.assertEqual(len(replay.direction_change_requests), 1)
            self.assertEqual(accepted.direction_change_requests[0].status, DirectionChangeStatus.RECEIVED)
            self.assertEqual(accepted.direction_change_requests[0].task_id, state.tasks[0].id)
            self.assertEqual(pipeline.store.load(state.id).tasks, before_tasks)
            self.assertEqual(pipeline.store.load(state.id).plan_revision, before_revision)
            self.assertEqual(len(pipeline.store.load(state.id).planning_messages), before_messages + 1)
            with self.assertRaisesRegex(PipelineError, "다른 방향 수정"):
                pipeline.request_direction_change(state.id, request_id=request_id, text="다른 지시")

    def test_direction_change_pauses_after_batch_until_preview_is_applied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state.stage = Stage.EXECUTING
            state.tasks[0].status = TaskStatus.RUNNING
            state.tasks[0].active_action = TaskAction.EXECUTE
            state.begin_step(RunStep.AGENT_EXECUTION)
            state.tasks.append(WorkTask(
                id="next", title="다음 Task", capabilities=["general"], agent_id="worker",
                provider_id=pipeline.agents["worker"].provider_id,
                expected_paths=["next.txt"],
            ))
            pipeline.store.save(state)
            pipeline.request_direction_change(state.id, request_id=str(uuid.uuid4()), text="다음 Task 범위를 조정해 주세요")
            finished = pipeline.store.load(state.id)
            finished.tasks[0].status = TaskStatus.COMPLETED
            finished.tasks[0].active_action = None
            pipeline.store.save(finished)

            paused = pipeline._apply_queued_changes_after_batch(finished)

            self.assertIsNotNone(paused)
            self.assertEqual(paused.tasks[1].status, TaskStatus.PENDING)
            self.assertIsNone(paused.active_step)
            self.assertEqual(paused.direction_change_requests[0].status, DirectionChangeStatus.QUEUED)
            with self.assertRaisesRegex(PipelineError, "변경 미리보기"):
                pipeline.resume(state.id, manual=True)
            self.assertEqual(pipeline.store.load(state.id).tasks[1].status, TaskStatus.PENDING)

    def test_direction_change_received_at_dispatch_boundary_prevents_next_batch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state = pipeline.execute(state.id, manual=True)
            request_id = str(uuid.uuid4())

            def receive_while_selecting(_state: RunState, candidates: list[WorkTask]) -> list[WorkTask]:
                pipeline.request_direction_change(state.id, request_id=request_id, text="시작 전에 범위를 변경해 주세요")
                return candidates

            with (
                patch.object(pipeline, "_ready_tasks", side_effect=receive_while_selecting),
                patch.object(pipeline, "_run_task_batch") as batch,
            ):
                paused = pipeline._execute(pipeline.store.load(state.id), manual=False)

            batch.assert_not_called()
            self.assertEqual(paused.stage, Stage.EXECUTING)
            self.assertEqual(paused.direction_change_requests[0].status, DirectionChangeStatus.QUEUED)
            self.assertEqual(paused.tasks[0].status, TaskStatus.WAITING)

    def test_direction_change_pause_keeps_task_failure_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state.stage = Stage.EXECUTING
            state.tasks[0].status = TaskStatus.FAILED
            state.tasks[0].error = "검증 실패"
            state.tasks.append(WorkTask(
                id="next", title="다음 Task", capabilities=["general"], agent_id="worker",
                expected_paths=["next.txt"],
            ))
            state.begin_step(RunStep.AGENT_EXECUTION)
            pipeline.store.save(state)
            pipeline.request_direction_change(state.id, request_id=str(uuid.uuid4()), text="실패 결과를 반영해 조정해 주세요")

            paused = pipeline._apply_queued_changes_after_batch(state)

            self.assertEqual(paused.stage, Stage.FAILED)
            self.assertEqual(paused.failed_step, RunStep.AGENT_EXECUTION)
            self.assertIn("검증 실패", paused.failure_message)
            self.assertEqual(paused.direction_change_requests[0].status, DirectionChangeStatus.QUEUED)

    def test_direction_change_preview_failure_and_confirmation_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state.stage = Stage.EXECUTING
            pipeline.store.save(state)
            direction_id = str(uuid.uuid4())
            pipeline.request_direction_change(state.id, request_id=direction_id, text="완료 조건을 보강해 주세요")
            proposal = deepcopy(state.tasks)
            proposal[0].description = "보강한 완료 조건"

            with patch.object(pipeline, "_build_plan", side_effect=PlanningError("계획 생성 실패")):
                with self.assertRaisesRegex(PlanningError, "계획 생성 실패"):
                    pipeline.preview_planning_apply(state.id, request_id=str(uuid.uuid4()))
            failed = pipeline.store.load(state.id).direction_change_requests[0]
            self.assertEqual(failed.status, DirectionChangeStatus.QUEUED)
            self.assertIn("계획 생성 실패", failed.error)

            with patch.object(pipeline, "_build_plan", return_value=Plan(summary=state.summary, server_work=False, tasks=proposal)):
                preview = pipeline.preview_planning_apply(state.id, request_id=str(uuid.uuid4()))
            self.assertTrue(preview["can_apply"])
            self.assertEqual(preview["direction_request_ids"], [direction_id])
            waiting = pipeline.store.load(state.id).direction_change_requests[0]
            self.assertEqual(waiting.status, DirectionChangeStatus.AWAITING_CONFIRMATION)
            self.assertEqual(waiting.text, "완료 조건을 보강해 주세요")

            applied = pipeline.apply_planning_preview(
                state.id, preview_id=preview["preview_id"], fingerprint=preview["fingerprint"],
                candidate_digest=preview["candidate_digest"],
            )["run"]
            self.assertEqual(applied.direction_change_requests[0].status, DirectionChangeStatus.APPLIED)
            self.assertEqual(applied.tasks[0].description, "보강한 완료 조건")
            self.assertEqual(pipeline.store.load(state.id).direction_change_requests[0].status, DirectionChangeStatus.APPLIED)

    def test_new_direction_change_invalidates_previous_preview(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state.stage = Stage.EXECUTING
            pipeline.store.save(state)
            pipeline.request_direction_change(state.id, request_id=str(uuid.uuid4()), text="첫 요청")
            with patch.object(pipeline, "_build_plan", return_value=Plan(summary=state.summary, server_work=False, tasks=deepcopy(state.tasks))):
                preview = pipeline.preview_planning_apply(state.id, request_id=str(uuid.uuid4()))
            pipeline.request_direction_change(state.id, request_id=str(uuid.uuid4()), text="두 번째 요청")
            self.assertEqual(
                [item.status for item in pipeline.store.load(state.id).direction_change_requests],
                [DirectionChangeStatus.QUEUED, DirectionChangeStatus.QUEUED],
            )
            with self.assertRaisesRegex(PipelineError, "다시 생성"):
                pipeline.apply_planning_preview(
                    state.id, preview_id=preview["preview_id"], fingerprint=preview["fingerprint"],
                    candidate_digest=preview["candidate_digest"],
                )

    def test_planning_preview_rejects_stale_and_protected_task_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            pipeline._append_planning_user_message(state, "설명을 바꿔 주세요.")
            pipeline.store.save(state)
            proposal = deepcopy(state.tasks)
            proposal[0].description = "변경된 설명"
            with patch.object(pipeline, "_build_plan", return_value=Plan(summary=state.summary, server_work=False, tasks=proposal)):
                preview = pipeline.preview_planning_apply(state.id, request_id=str(uuid.uuid4()))
            changed = pipeline.store.load(state.id)
            pipeline._append_planning_user_message(changed, "검증 조건도 보강해 주세요.")
            pipeline.store.save(changed)
            with self.assertRaisesRegex(PipelineError, "다시 생성"):
                pipeline.apply_planning_preview(
                    state.id, preview_id=preview["preview_id"], fingerprint=preview["fingerprint"],
                    candidate_digest=preview["candidate_digest"],
                )
            changed = pipeline.store.load(state.id)
            changed.stage = Stage.EXECUTING
            changed.tasks[0].status = TaskStatus.COMPLETED
            pipeline.store.save(changed)
            with patch.object(pipeline, "_build_plan", return_value=Plan(summary=state.summary, server_work=False, tasks=proposal)):
                protected = pipeline.preview_planning_apply(state.id, request_id=str(uuid.uuid4()))
            self.assertEqual(protected["changes"][0]["kind"], "review_required")
            self.assertFalse(protected["can_apply"])

    def test_planning_preview_waits_for_any_active_step(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state.stage = Stage.EXECUTING
            state.active_step = RunStep.TASK_PREPARATION
            pipeline._append_planning_user_message(state, "후속 Task를 추가해 주세요.")
            pipeline.store.save(state)
            proposal = [*deepcopy(state.tasks), WorkTask(
                id="follow-up", title="후속 Task", capabilities=["general"], agent_id="worker",
                expected_paths=["follow-up.txt"],
            )]
            with patch.object(pipeline, "_build_plan", return_value=Plan(summary=state.summary, server_work=False, tasks=proposal)):
                preview = pipeline.preview_planning_apply(state.id, request_id=str(uuid.uuid4()))
            self.assertFalse(preview["can_apply"])
            self.assertIn("Task 종료 후", preview["apply_after"])
            with self.assertRaisesRegex(PipelineError, "실행 중인 작업"):
                pipeline.apply_planning_preview(
                    state.id, preview_id=preview["preview_id"], fingerprint=preview["fingerprint"],
                    candidate_digest=preview["candidate_digest"],
                )

    def test_planning_preview_blocks_dependent_exclusion_and_allows_unreferenced_exclusion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            dependent = WorkTask(
                id="follow-up", title="후속 작업", capabilities=["general"], agent_id="worker",
                dependencies=[state.tasks[0].id], expected_paths=["follow-up.txt"],
            )
            state.tasks.append(dependent)
            pipeline._append_planning_user_message(state, "필요 없는 Task를 제외해 주세요.")
            pipeline.store.save(state)
            with patch.object(pipeline, "_build_plan", return_value=Plan(summary=state.summary, server_work=False, tasks=[deepcopy(dependent)])):
                blocked = pipeline.preview_planning_apply(state.id, request_id=str(uuid.uuid4()))
            removed = next(item for item in blocked["changes"] if item["task_id"] == state.tasks[0].id)
            self.assertEqual(removed["kind"], "review_required")
            self.assertIn(dependent.id, removed["reason"])
            self.assertFalse(blocked["can_apply"])
            with patch.object(pipeline, "_build_plan", return_value=Plan(summary=state.summary, server_work=False, tasks=[deepcopy(state.tasks[0])])):
                preview = pipeline.preview_planning_apply(state.id, request_id=str(uuid.uuid4()))
            self.assertTrue(preview["can_apply"])
            result = pipeline.apply_planning_preview(
                state.id, preview_id=preview["preview_id"], fingerprint=preview["fingerprint"],
                candidate_digest=preview["candidate_digest"],
            )
            self.assertEqual([task.id for task in result["run"].tasks], [state.tasks[0].id])
            self.assertEqual(result["preview"]["actual"]["excluded"], 1)

    def test_planning_apply_failure_preserves_tasks_and_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state.planning_agent_id = "worker"
            pipeline._append_planning_user_message(state, "완료 조건에 로그 복사를 추가해 주세요.")
            pipeline.store.save(state)
            original_tasks = deepcopy(state.tasks)

            with (
                patch.object(pipeline, "_build_plan", side_effect=PlanningError("invalid updated plan")),
                self.assertRaisesRegex(PlanningError, "invalid updated plan"),
            ):
                pipeline.request_planning_conversation_apply(
                    state.id,
                    request_id="planning-apply-failed",
                    expected_revision=state.plan_revision,
                    conversation_revision=state.planning_conversation_revision,
                )

            failed = pipeline.store.load(state.id)
            self.assertEqual(failed.tasks, original_tasks)
            self.assertEqual(failed.planning_applied_conversation_revision, 0)
            self.assertEqual(failed.planning_apply_requests[-1].status, PlanningApplyStatus.FAILED)
            self.assertEqual(failed.planning_apply_requests[-1].error, "invalid updated plan")

    def test_planning_apply_request_queues_the_conversation_snapshot_during_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state.planning_agent_id = "worker"
            state.stage = Stage.EXECUTING
            state.tasks[0].status = TaskStatus.RUNNING
            state.tasks[0].active_action = TaskAction.EXECUTE
            state.begin_step(RunStep.AGENT_EXECUTION)
            pipeline._append_planning_user_message(state, "현재 결과에 로그 복사 조건을 추가해 주세요.")
            state.refresh_task_readiness()
            pipeline.store.save(state)

            queued = pipeline.request_planning_conversation_apply(
                state.id,
                request_id="planning-apply-queued",
                expected_revision=state.plan_revision,
                conversation_revision=state.planning_conversation_revision,
            )
            replayed = pipeline.request_planning_conversation_apply(
                state.id,
                request_id="planning-apply-queued",
                expected_revision=state.plan_revision,
                conversation_revision=state.planning_conversation_revision,
            )

            self.assertEqual(len(replayed.planning_apply_requests), 1)
            request = queued.planning_apply_requests[0]
            self.assertEqual(request.status, PlanningApplyStatus.QUEUED)
            self.assertIn("로그 복사 조건", request.context_snapshot)
            self.assertEqual(queued.tasks[0].status, TaskStatus.RUNNING)

    def test_sdk_planning_follow_up_restores_context_when_thread_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "requirements.md"
            spec.write_text("문서를 수정한다.", encoding="utf-8")
            command = ("codex", "exec", "--sandbox", "read-only", "--cd", "{worktree}", "-")
            planner = AgentConfig("planner", ("planning", "docs"), command, 2, provider_id="codex", model="gpt-test", review_command=command)
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(planner,),
                planning=PlanningConfig(agent_id="planner", max_attempts=2),
            )
            result = (
                'AI_PLAN_RESULT: {"summary":"문서 수정",'
                '"server_work":false,"source_paths":[],"instruction_paths":[],'
                '"tasks":[{"id":"docs","title":"문서 수정",'
                '"description":"README를 수정한다.","capabilities":["docs"],'
                '"depends_on":[],"acceptance_criteria":["사용법이 설명된다"],'
                '"expected_paths":["README.md"],"forbidden_paths":[],'
                '"verify_commands":[["python","-m","compileall","-q","src"]],'
                '"risk_level":"low"}],"questions":[]}'
            )
            codex_sdk = connected_codex_sdk()
            codex_sdk.run_turn.side_effect = [result, "검증 조건 후보를 정리했습니다.", result]
            codex_sdk.has_conversation.return_value = False
            pipeline = Pipeline(config, codex_sdk=codex_sdk)
            planned = pipeline.start(spec)

            chatted = pipeline.send_planning_message(planned.id, "검증 조건을 먼저 같이 정리해 주세요.")
            pipeline.send_planning_message(planned.id, "정리한 검증 조건을 계획에 반영해 주세요.")

            chat_request = codex_sdk.run_turn.call_args_list[1].args[0]
            apply_request = codex_sdk.run_turn.call_args_list[2].args[0]
            self.assertEqual(chatted.stage, Stage.PLANNED)
            self.assertEqual(chatted.planning_messages[-1].text, "검증 조건 후보를 정리했습니다.")
            self.assertIn("Restore a saved Planning conversation", chat_request.prompt)
            self.assertIn("Previous structured plan", chat_request.prompt)
            self.assertIn("검증 조건을 먼저 같이 정리해 주세요.", chat_request.prompt)
            self.assertIn("Structured implementation planning", apply_request.prompt)
            self.assertIn("Previous structured plan", apply_request.prompt)
            self.assertIn("검증 조건 후보를 정리했습니다.", apply_request.prompt)
            self.assertNotIn("정리한 검증 조건을 계획에 반영해 주세요.", apply_request.prompt)

    def test_planning_timeout_is_not_retried(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "requirements.md"
            spec.write_text("문서를 수정한다.", encoding="utf-8")
            planner_script = "import sys, time; sys.stdin.read(); print('started', flush=True); time.sleep(10)"
            planner = AgentConfig(
                "planner",
                ("planning", "docs"),
                (sys.executable, "-c", planner_script),
                2,
                provider_id="custom",
                review_command=(sys.executable, "-c", planner_script),
            )
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(agent_timeout_seconds=30),
                agents=(planner,),
                planning=PlanningConfig(agent_id="planner", max_attempts=2, timeout_seconds=1),
            )
            pipeline = Pipeline(config)

            with self.assertRaisesRegex(PlanningError, "timed out after 1 seconds"):
                pipeline.start(spec)

            state = pipeline.list_statuses()[0]
            self.assertEqual(state.stage, Stage.FAILED)
            self.assertEqual(state.failed_step, RunStep.PLANNING)
            self.assertEqual(state.planning_attempts, 1)
            self.assertIn("timed out after 1 seconds", state.failure_message)

    def test_planning_retries_share_one_timeout_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "requirements.md"
            spec.write_text("문서를 수정한다.", encoding="utf-8")
            planner = AgentConfig(
                "planner",
                ("planning", "docs"),
                (sys.executable, "-c", "pass"),
                2,
                provider_id="custom",
                review_command=(sys.executable, "-c", "pass"),
            )
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(planner,),
                planning=PlanningConfig(agent_id="planner", max_attempts=2, timeout_seconds=1, reuse_results=False),
            )
            pipeline = Pipeline(config)
            received_timeouts: list[float] = []

            def invoke(*_args: object, **kwargs: object) -> str:
                timeout = kwargs.get("timeout_seconds")
                self.assertIsInstance(timeout, float)
                received_timeouts.append(float(timeout))
                if len(received_timeouts) == 1:
                    return "invalid"
                raise ProviderTimeoutError("provider timed out")

            with (
                patch.object(pipeline, "_invoke_planning_agent", side_effect=invoke),
                patch("ai_orchestrator.pipeline.time.monotonic", side_effect=(0.0, 0.25, 0.75)),
                self.assertRaisesRegex(PlanningError, "planning timed out after 1 seconds"),
            ):
                pipeline.start(spec)

            self.assertEqual(len(received_timeouts), 2)
            self.assertAlmostEqual(received_timeouts[0], 0.75)
            self.assertAlmostEqual(received_timeouts[1], 0.25)

    def test_sdk_planning_retries_use_inactivity_timeout_per_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "requirements.md"
            spec.write_text("문서를 수정한다.", encoding="utf-8")
            command = ("codex", "exec", "--sandbox", "read-only", "-")
            planner = AgentConfig("planner", ("planning", "docs"), command, 2, provider_id="codex", review_command=command)
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(planner,),
                planning=PlanningConfig(agent_id="planner", max_attempts=2, timeout_seconds=1, reuse_results=False),
            )
            pipeline = Pipeline(config, codex_sdk=connected_codex_sdk())
            received_timeouts: list[float] = []

            def invoke(*_args: object, **kwargs: object) -> str:
                timeout = kwargs.get("timeout_seconds")
                self.assertIsInstance(timeout, int)
                received_timeouts.append(float(timeout))
                if len(received_timeouts) == 1:
                    return "invalid"
                raise ProviderTimeoutError("SDK activity timed out")

            with (
                patch.object(pipeline, "_invoke_planning_agent", side_effect=invoke),
                self.assertRaisesRegex(PlanningError, "no Codex SDK activity for 1 seconds"),
            ):
                pipeline.start(spec)

            self.assertEqual(received_timeouts, [1.0, 1.0])

    def test_directory_planning_retries_when_source_paths_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "planning"
            spec.mkdir()
            source_content = "문서를 수정한다."
            (spec / "requirements.md").write_text(source_content, encoding="utf-8")
            flag = root / "planner-attempted"
            planner_script = (
                "import json, sys; from pathlib import Path; sys.stdin.read(); "
                f"flag=Path({str(flag)!r}); first=not flag.exists(); "
                "flag.write_text('done', encoding='utf-8'); "
                "payload={'summary':'문서 수정','server_work':False,"
                "'source_paths':([] if first else ['requirements.md']),'tasks':["
                "{'id':'docs','title':'문서 수정','description':'README를 수정한다.',"
                "'capabilities':['docs'],'depends_on':[],"
                "'acceptance_criteria':['사용법이 설명된다'],"
                "'expected_paths':['README.md'],'forbidden_paths':[],"
                "'verify_commands':[['python','-m','compileall','-q','src']],"
                "'risk_level':'low'}],'questions':[]}; "
                "print('AI_PLAN_RESULT: '+json.dumps(payload))"
            )
            planner = AgentConfig(
                "planner",
                ("planning", "docs"),
                (sys.executable, "-c", planner_script),
                2,
                provider_id="local",
                review_command=(sys.executable, "-c", planner_script),
            )
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(planner,),
                planning=PlanningConfig(agent_id="planner", max_attempts=2),
            )

            state = Pipeline(config).start(spec)

            self.assertEqual(state.stage, Stage.PLANNED)
            self.assertEqual(state.planning_attempts, 2)
            document_digest = hashlib.sha256(source_content.encode("utf-8")).hexdigest()
            expected_digest = hashlib.sha256(b"requirements.md\0" + document_digest.encode("ascii") + b"\0").hexdigest()
            self.assertEqual(state.spec_digest, expected_digest)

    def test_directory_planning_retries_questions_without_task_draft(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "planning"
            spec.mkdir()
            (spec / "requirements.md").write_text("미완료 기능을 구현한다.", encoding="utf-8")
            flag = root / "planner-question-attempted"
            planner_script = (
                "import json, sys; from pathlib import Path; sys.stdin.read(); "
                f"flag=Path({str(flag)!r}); first=not flag.exists(); "
                "flag.write_text('done', encoding='utf-8'); "
                "task={'id':'feature','title':'기능 구현',"
                "'description':'문서에서 확인한 미완료 기능을 구현한다.',"
                "'capabilities':['general'],'depends_on':[],"
                "'acceptance_criteria':['기능 구현과 검증이 완료된다'],"
                "'expected_paths':['src/**'],'forbidden_paths':[],"
                "'verify_commands':[['python','-m','compileall','-q','src']],"
                "'risk_level':'low'}; "
                "payload={'summary':'구현 작업 탐색','server_work':False,"
                "'source_paths':['requirements.md'],"
                "'tasks':([] if first else [task]),"
                "'questions':(['대상 기능이나 기획 영역을 지정해 주세요.'] "
                "if first else [])}; "
                "print('AI_PLAN_RESULT: '+json.dumps(payload, ensure_ascii=False))"
            )
            planner = AgentConfig(
                "planner",
                ("planning", "general"),
                (sys.executable, "-c", planner_script),
                2,
                provider_id="local",
                review_command=(sys.executable, "-c", planner_script),
            )
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(planner,),
                planning=PlanningConfig(agent_id="planner", max_attempts=2),
            )

            state = Pipeline(config).start(spec)

            self.assertEqual(state.stage, Stage.PLANNED)
            self.assertEqual(state.planning_attempts, 2)
            self.assertEqual([task.id for task in state.tasks], ["feature"])
            self.assertTrue(any("clarification requires best-effort tasks" in event.message for event in state.events))

    def test_directed_directory_planning_allows_question_without_unrelated_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = repo / "planning"
            spec.mkdir()
            (spec / "requirements.md").write_text("삭제 정책은 승인 대기 중이다.", encoding="utf-8")
            git(repo, "add", "planning/requirements.md")
            git(repo, "commit", "-m", "planning source")
            planner_script = (
                "import json, sys; sys.stdin.read(); "
                "payload={'summary':'삭제 정책 확인','server_work':False,"
                "'source_paths':[],'instruction_paths':[],'tasks':[],"
                "'questions':['삭제 시 미병합 worktree도 제거할까요?']}; "
                "print('AI_PLAN_RESULT: '+json.dumps(payload, ensure_ascii=False))"
            )
            planner = AgentConfig(
                "planner",
                ("planning", "general"),
                (sys.executable, "-c", planner_script),
                1,
                provider_id="local",
                review_command=(sys.executable, "-c", planner_script),
            )
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=repo),
                    execution=ExecutionConfig(),
                    agents=(planner,),
                    planning=PlanningConfig(agent_id="planner", max_attempts=2),
                )
            )

            state = pipeline.start(spec, planning_mode=PlanningMode.DIRECTED, planning_request="작업 그룹 삭제 정책만 계획해 주세요.")

            self.assertEqual(state.stage, Stage.NEEDS_CLARIFICATION)
            self.assertEqual(state.tasks, [])
            self.assertEqual(state.planning_attempts, 1)
            self.assertEqual(state.planning_questions, ["삭제 시 미병합 worktree도 제거할까요?"])

    def test_directory_planning_follow_up_allows_question_without_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "planning"
            spec.mkdir()
            (spec / "requirements.md").write_text("미완료 기능을 구현한다.", encoding="utf-8")
            call_count = root / "planner-call-count"
            planner_script = (
                "import json, sys; from pathlib import Path; sys.stdin.read(); "
                f"count_path=Path({str(call_count)!r}); "
                "count=int(count_path.read_text()) if count_path.exists() else 0; "
                "count+=1; count_path.write_text(str(count)); "
                "task={'id':'feature','title':'기능 구현',"
                "'description':'문서에서 확인한 미완료 기능을 구현한다.',"
                "'capabilities':['general'],'depends_on':[],"
                "'acceptance_criteria':['기능 구현과 검증이 완료된다'],"
                "'expected_paths':['src/**'],'forbidden_paths':[],"
                "'verify_commands':[['python','-m','compileall','-q','src']],"
                "'risk_level':'low'}; "
                "payload={'summary':'구현 작업 탐색','server_work':False,"
                "'source_paths':['requirements.md'],"
                "'tasks':([task] if count == 1 else []),"
                "'questions':([] if count == 1 else "
                "['이 계획을 중단할까요?'])}; "
                "print('AI_PLAN_RESULT: '+json.dumps(payload, ensure_ascii=False))"
            )
            planner = AgentConfig(
                "planner",
                ("planning", "general"),
                (sys.executable, "-c", planner_script),
                2,
                provider_id="local",
                review_command=(sys.executable, "-c", planner_script),
            )
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(planner,),
                planning=PlanningConfig(agent_id="planner", max_attempts=2),
            )
            pipeline = Pipeline(config)
            planned = pipeline.start(spec)

            clarified = pipeline.apply_planning_conversation(planned.id, message="이 작업은 진행할 필요가 없습니다.")

            self.assertEqual(clarified.stage, Stage.NEEDS_CLARIFICATION)
            self.assertEqual(clarified.tasks, [])
            self.assertEqual(clarified.planning_attempts, 2)
            self.assertEqual(clarified.planning_questions, ["이 계획을 중단할까요?"])
            self.assertFalse(any("clarification requires best-effort tasks" in event.message for event in clarified.events))

    def test_planning_retries_when_active_repository_instruction_is_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            instruction_text = "기능 작업 전에 프로젝트 계획 규약을 확인한다."
            (repo / "AGENTS.md").write_text(instruction_text, encoding="utf-8")
            git(repo, "add", "AGENTS.md")
            git(repo, "commit", "-m", "add instructions")
            spec = root / "requirements.md"
            spec.write_text("README를 수정한다.", encoding="utf-8")
            flag = root / "planner-instruction-attempted"
            planner_script = (
                "import json, sys; from pathlib import Path; sys.stdin.read(); "
                f"flag=Path({str(flag)!r}); first=not flag.exists(); "
                "flag.write_text('done', encoding='utf-8'); "
                "payload={'summary':'문서 수정','server_work':False,"
                "'instruction_paths':([] if first else ['AGENTS.md']),'tasks':["
                "{'id':'docs','title':'문서 수정','description':'README를 수정한다.',"
                "'capabilities':['docs'],'depends_on':[],"
                "'acceptance_criteria':['사용법이 설명된다'],"
                "'expected_paths':['README.md'],'forbidden_paths':[],"
                "'verify_commands':[['python','-m','compileall','-q','src']],"
                "'risk_level':'low'}],'questions':[]}; "
                "print('AI_PLAN_RESULT: '+json.dumps(payload))"
            )
            planner = AgentConfig(
                "planner",
                ("planning", "docs"),
                (sys.executable, "-c", planner_script),
                2,
                provider_id="local",
                review_command=(sys.executable, "-c", planner_script),
            )
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(planner,),
                planning=PlanningConfig(agent_id="planner", max_attempts=2),
            )

            state = Pipeline(config).start(spec)

            self.assertEqual(state.stage, Stage.PLANNED)
            self.assertEqual(state.planning_attempts, 2)
            prompt = (repo / ".ai-orchestrator" / "runs" / state.id / "prompts" / "planning-2.md").read_text(encoding="utf-8")
            self.assertIn(instruction_text, prompt)
            self.assertIn("AGENTS.md", prompt)
            plan = json.loads(Path(state.structured_plan_path).read_text(encoding="utf-8"))
            self.assertEqual(plan["instruction_paths"], ["AGENTS.md"])

    def test_directory_planning_requires_configured_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "planning"
            spec.mkdir()
            (spec / "requirements.md").write_text("문서를 수정한다.", encoding="utf-8")
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
            pipeline = Pipeline(config)

            with self.assertRaisesRegex(PlanningError, "directory requires a configured planning agent"):
                pipeline.start(spec)

            state = pipeline.store.list_runs()[0]
            self.assertEqual(state.stage, Stage.FAILED)
            self.assertEqual(state.failed_step, RunStep.PLANNING)

    def test_provider_process_uses_utf8_and_sdk_rejects_oversized_codex_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=root), execution=ExecutionConfig(), agents=())
            pipeline = Pipeline(config)
            agent = AgentConfig("custom-planner", ("planning",), ("custom-agent",), provider_id="custom")
            process = Mock()
            process.communicate.return_value = ("결과—완료", None)
            process.returncode = 0
            replacements = {
                "{worktree}": str(root),
                "{prompt}": str(root / "prompt.md"),
                "{task_id}": "planning",
                "{run_id}": "run-1",
            }
            with (
                patch.object(pipeline, "_resolve_executable", return_value="custom-agent"),
                patch("ai_orchestrator.pipeline.subprocess.Popen", return_value=process) as popen,
            ):
                output = pipeline._invoke_provider_command(
                    agent=agent,
                    command_template=agent.command,
                    replacements=replacements,
                    cwd=root,
                    prompt="유니코드—입력",
                    prompt_path=str(root / "prompt.md"),
                    log_path=root / "agent.log",
                    action="planning",
                    task_id="planning",
                )

            self.assertEqual(output, "결과—완료")
            self.assertEqual(popen.call_args.kwargs["encoding"], "utf-8")
            self.assertEqual(popen.call_args.kwargs["env"]["PYTHONIOENCODING"], "utf-8")
            process.communicate.assert_called_once_with(input="유니코드—입력", timeout=config.execution.agent_timeout_seconds)

            with (
                patch.object(pipeline, "_resolve_executable") as resolve,
                patch("ai_orchestrator.pipeline.subprocess.Popen") as popen,
                self.assertRaisesRegex(PipelineError, "maximum length"),
            ):
                codex = AgentConfig("codex-planner", ("planning",), (), provider_id="codex")
                pipeline._invoke_provider_command(
                    agent=codex,
                    command_template=codex.command,
                    replacements=replacements,
                    cwd=root,
                    prompt="x" * (CODEX_INPUT_LIMIT_CHARACTERS + 1),
                    prompt_path=str(root / "prompt.md"),
                    log_path=root / "agent.log",
                    action="planning",
                    task_id="planning",
                )
            resolve.assert_not_called()
            popen.assert_not_called()

    def test_codex_planning_uses_sdk_without_external_cli(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=root), execution=ExecutionConfig(), agents=())
            codex_sdk = connected_codex_sdk()
            codex_sdk.run_turn.return_value = "structured plan"
            pipeline = Pipeline(config, codex_sdk=codex_sdk)
            agent = AgentConfig("planner", ("planning",), (), provider_id="codex")
            replacements = {
                "{worktree}": str(root),
                "{prompt}": str(root / "prompt.md"),
                "{task_id}": "planning",
                "{run_id}": "run-1",
            }

            with patch.object(pipeline, "_resolve_executable") as resolve, patch("ai_orchestrator.pipeline.subprocess.Popen") as popen:
                output = pipeline._invoke_provider_command(
                    agent=agent,
                    command_template=agent.command,
                    replacements=replacements,
                    cwd=root,
                    prompt="planning prompt",
                    prompt_path=str(root / "prompt.md"),
                    log_path=root / "planning.log",
                    action="planning",
                    task_id="planning",
                    timeout_seconds=12,
                    model="gpt-test",
                    reasoning_effort="medium",
                )

            self.assertEqual(output, "structured plan")
            resolve.assert_not_called()
            popen.assert_not_called()
            request = codex_sdk.run_turn.call_args.args[0]
            self.assertEqual(request.cwd, root)
            self.assertEqual(request.prompt, "planning prompt")
            self.assertEqual(request.model, "gpt-test")
            self.assertEqual(request.reasoning_effort, "medium")
            self.assertEqual(request.sandbox_mode, "read-only")
            self.assertEqual(request.approval_mode, "deny-all")
            self.assertEqual(request.timeout_seconds, 12)

    def test_sdk_planning_progress_is_saved_for_desktop_polling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agent = AgentConfig("planner", ("planning",), (), provider_id="codex", model="gpt-test")
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=root),
                execution=ExecutionConfig(),
                agents=(agent,),
                planning=PlanningConfig(agent_id=agent.id),
            )
            codex_sdk = connected_codex_sdk()

            def run_turn(request: object) -> str:
                callback = request.progress_callback
                self.assertIsNotNone(callback)
                progress = CodexSdkProgress("plan_step", "관련 기획 규약 확인")
                callback(progress)
                callback(progress)
                return "structured plan"

            codex_sdk.run_turn.side_effect = run_turn
            pipeline = Pipeline(config, codex_sdk=codex_sdk)
            state = RunState(
                id="run-1",
                spec_path=str(root / "requirements.md"),
                spec_digest="digest",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.REVIEWED,
                planning_model="gpt-test",
                planning_reasoning_effort="medium",
            )

            output = pipeline._invoke_planning_agent(state, agent, "planning prompt", root / "prompt.md", root / "planning.log")

            self.assertEqual(output, "structured plan")
            saved = pipeline.store.load(state.id)
            progress_events = [event for event in saved.events if event.kind == "planning_progress"]
            self.assertEqual(len(progress_events), 1)
            self.assertEqual(progress_events[0].message, "codex sdk progress: plan_step | 관련 기획 규약 확인")

    def test_sdk_task_progress_is_saved_for_desktop_polling(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agent = AgentConfig("worker", ("general",), (), provider_id="codex", model="gpt-test")
            config = Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=root), execution=ExecutionConfig(), agents=(agent,))
            codex_sdk = connected_codex_sdk()

            def run_turn(request: object) -> str:
                callback = request.progress_callback
                profile_callback = request.profile_callback
                self.assertIsNotNone(callback)
                self.assertIsNotNone(profile_callback)
                profile_callback(
                    CodexSdkExecutionProfile(
                        model="gpt-runtime-default", reasoning_effort="high", model_automatic=True, reasoning_effort_automatic=True
                    )
                )
                progress = CodexSdkProgress("plan_step", "Terminal 구조 확인")
                callback(progress)
                callback(progress)
                saved = pipeline.store.load(state.id)
                self.assertEqual(saved.tasks[0].progress_phase, "plan_step")
                self.assertEqual(saved.tasks[0].progress_detail, "Terminal 구조 확인")
                self.assertTrue(saved.tasks[0].progress_updated_at)
                self.assertEqual(saved.tasks[0].effective_model, "gpt-runtime-default")
                self.assertEqual(saved.tasks[0].effective_reasoning_effort, "high")
                return "implemented"

            codex_sdk.run_turn.side_effect = run_turn
            pipeline = Pipeline(config, codex_sdk=codex_sdk)
            task = WorkTask(
                id="terminal-tabs",
                title="터미널 탭 구현",
                capabilities=["general"],
                agent_id=agent.id,
                provider_id=agent.provider_id,
                model="gpt-test",
                worktree=str(root),
                prompt_path=str(root / "prompt.md"),
            )
            state = RunState(
                id="run-1",
                spec_path=str(root / "requirements.md"),
                spec_digest="digest",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.EXECUTING,
                tasks=[task],
            )
            task.begin_action(TaskAction.EXECUTE)
            pipeline.store.save(state)

            output = pipeline._invoke_agent(state, task, agent, "implement", root / "worker.log", TaskAction.EXECUTE)

            self.assertEqual(output, "implemented")
            self.assertEqual(task.progress_phase, "plan_step")
            self.assertEqual(task.progress_detail, "Terminal 구조 확인")
            self.assertEqual(task.effective_model, "gpt-runtime-default")
            self.assertEqual(task.effective_reasoning_effort, "high")

    def test_desktop_codex_worker_uses_sdk_workspace_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=root), execution=ExecutionConfig(), agents=())
            codex_sdk = connected_codex_sdk()
            codex_sdk.run_turn.return_value = "implemented"
            pipeline = Pipeline(config, codex_sdk=codex_sdk)
            agent = AgentConfig("worker", ("backend",), (), provider_id="codex")
            replacements = {
                "{worktree}": str(root),
                "{prompt}": str(root / "prompt.md"),
                "{task_id}": "backend",
                "{run_id}": "run-1",
            }

            with patch.object(pipeline, "_resolve_executable") as resolve:
                output = pipeline._invoke_provider_command(
                    agent=agent,
                    command_template=agent.command,
                    replacements=replacements,
                    cwd=root,
                    prompt="implement",
                    prompt_path=str(root / "prompt.md"),
                    log_path=root / "worker.log",
                    action="execute",
                    task_id="backend",
                )

            self.assertEqual(output, "implemented")
            resolve.assert_not_called()
            request = codex_sdk.run_turn.call_args.args[0]
            self.assertEqual(request.sandbox_mode, "workspace-write")
            self.assertEqual(request.approval_mode, "auto-review")

    def test_codex_never_falls_back_to_configured_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agent = AgentConfig("planner", ("planning",), ("codex", "exec", "-"), provider_id="codex")
            pipeline = Pipeline(
                Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=root), execution=ExecutionConfig(), agents=(agent,))
            )

            with patch("ai_orchestrator.pipeline.subprocess.Popen") as popen, self.assertRaisesRegex(PipelineError, "openai-codex SDK"):
                pipeline._invoke_provider_command(
                    agent=agent,
                    command_template=agent.command,
                    replacements={"{run_id}": "run-1", "{task_id}": "planning"},
                    cwd=root,
                    prompt="planning prompt",
                    prompt_path=str(root / "prompt.md"),
                    log_path=root / "planning.log",
                    action="planning",
                    task_id="planning",
                )

            popen.assert_not_called()

    def test_sdk_marks_codex_provider_available_without_external_cli(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agent = AgentConfig("planner", ("planning", "general"), (), provider_id="codex")
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=root),
                execution=ExecutionConfig(),
                agents=(agent,),
                planning=PlanningConfig(agent_id=agent.id),
            )
            codex_sdk = connected_codex_sdk()
            codex_sdk.account_status.return_value = CodexSdkAccountStatus(True, "chatgpt", "ChatGPT 구독 로그인")
            pipeline = Pipeline(config, codex_sdk=codex_sdk)

            with patch.object(pipeline, "_resolve_executable") as resolve:
                choices = pipeline.planning_provider_choices()
                statuses = pipeline.provider_statuses("codex")

            resolve.assert_not_called()
            self.assertEqual([choice.provider_id for choice in choices], ["codex"])
            self.assertEqual(len(statuses), 1)
            self.assertTrue(statuses[0].available)
            self.assertEqual(statuses[0].executable, "openai-codex SDK")
            self.assertTrue(statuses[0].authenticated)
            self.assertEqual(statuses[0].auth_method, "chatgpt")
            self.assertEqual(statuses[0].auth_label, "ChatGPT 구독 로그인")

    def test_codex_provider_requires_an_authenticated_sdk_account(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agent = AgentConfig("planner", ("planning", "general"), (), provider_id="codex")
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=root),
                execution=ExecutionConfig(),
                agents=(agent,),
                planning=PlanningConfig(agent_id=agent.id),
            )
            codex_sdk = connected_codex_sdk()
            codex_sdk.account_status.return_value = CodexSdkAccountStatus(False, "none", "로그인 필요")

            status = Pipeline(config, codex_sdk=codex_sdk).provider_statuses()[0]

            self.assertFalse(status.available)
            self.assertFalse(status.authenticated)
            self.assertEqual(status.auth_method, "none")
            self.assertEqual(status.auth_label, "로그인 필요")

    def test_claude_provider_reports_sanitized_subscription_auth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agent = AgentConfig("claude-planner", ("planning",), (sys.executable, "-c", "pass"), provider_id="claude")
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=root),
                    execution=ExecutionConfig(),
                    agents=(agent,),
                    planning=PlanningConfig(agent_id=agent.id),
                )
            )
            auth_payload = json.dumps(
                {
                    "loggedIn": True,
                    "authMethod": "claude.ai",
                    "apiProvider": "firstParty",
                    "subscriptionType": "max",
                    "email": "private@example.com",
                    "orgId": "private-organization",
                }
            )

            with patch(
                "ai_orchestrator.pipeline.subprocess.run",
                return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=auth_payload, stderr=""),
            ) as run:
                status = pipeline.provider_statuses()[0]

            self.assertTrue(status.available)
            self.assertTrue(status.authenticated)
            self.assertEqual(status.auth_method, "claude_subscription")
            self.assertEqual(status.auth_label, "Claude Max 구독 로그인")
            self.assertNotIn("private", status.auth_label)
            self.assertEqual(run.call_args.args[0], [sys.executable, "auth", "status", "--json"])

    def test_claude_auth_status_maps_api_logout_and_failures(self) -> None:
        cases = (
            ({"loggedIn": True, "authMethod": "apiKey"}, (True, "api_key", "Anthropic API key")),
            ({"loggedIn": False, "email": "private@example.com"}, (False, "none", "로그인 필요")),
            ({"authMethod": "claude.ai"}, (None, "error", "인증 확인 실패")),
        )
        for payload, expected in cases:
            with (
                self.subTest(payload=payload),
                patch(
                    "ai_orchestrator.pipeline.subprocess.run",
                    return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps(payload), stderr=""),
                ),
            ):
                self.assertEqual(Pipeline._claude_auth_status("claude"), expected)

        with patch("ai_orchestrator.pipeline.subprocess.run", side_effect=subprocess.TimeoutExpired("claude", 5)):
            self.assertEqual(Pipeline._claude_auth_status("claude"), (None, "error", "인증 확인 실패"))

    def test_claude_login_is_required_before_planning_preparation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            agent = AgentConfig("claude-planner", ("planning",), (sys.executable, "-c", "pass"), provider_id="claude")
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=repo),
                    execution=ExecutionConfig(),
                    agents=(agent,),
                    planning=PlanningConfig(agent_id=agent.id),
                )
            )

            with (
                patch.object(pipeline, "_claude_auth_status", return_value=(False, "none", "로그인 필요")),
                self.assertRaisesRegex(PipelineError, "claude auth login"),
            ):
                pipeline.prepare_planning(root / "missing-spec.md")

    def test_dependency_tasks_run_sequentially_in_shared_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "requirements.txt"
            spec.write_text("기반 파일 뒤 결과 파일을 만든다.", encoding="utf-8")
            plan_payload = {
                "summary": "의존 작업",
                "server_work": False,
                "tasks": [
                    {
                        "id": "dependent",
                        "title": "결과 파일 생성",
                        "description": "기반 파일을 이용해 결과를 생성한다.",
                        "capabilities": ["general"],
                        "depends_on": ["base"],
                        "acceptance_criteria": ["결과 파일이 생성된다"],
                        "expected_paths": ["dependent.txt"],
                        "forbidden_paths": [],
                        "verify_commands": [["python", "-c", "from pathlib import Path"]],
                        "risk_level": "low",
                    },
                    {
                        "id": "base",
                        "title": "기반 파일 생성",
                        "description": "기반 파일을 생성한다.",
                        "capabilities": ["general"],
                        "depends_on": [],
                        "acceptance_criteria": ["기반 파일이 생성된다"],
                        "expected_paths": ["base.txt"],
                        "forbidden_paths": [],
                        "verify_commands": [["python", "-c", "from pathlib import Path"]],
                        "risk_level": "low",
                    },
                ],
                "questions": [],
            }
            planner_script = f"import json, sys; sys.stdin.read(); print('AI_PLAN_RESULT: '+json.dumps({plan_payload!r}))"
            worker_script = (
                "import os, sys; from pathlib import Path; sys.stdin.read(); "
                "task=os.environ['AI_ORCHESTRATOR_TASK_ID']; "
                "(Path('base.txt').write_text('base\\n', encoding='utf-8') "
                "if task=='base' else "
                "(Path('base.txt').read_text(encoding='utf-8'), "
                "Path('dependent.txt').write_text('done\\n', encoding='utf-8')))"
            )
            planner = AgentConfig(
                "planner",
                ("planning",),
                (sys.executable, "-c", planner_script),
                2,
                provider_id="local",
                review_command=(sys.executable, "-c", planner_script),
            )
            worker = AgentConfig("worker", ("general",), (sys.executable, "-c", worker_script), 2, provider_id="local")
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(auto_commit=True, max_parallel=2),
                agents=(planner, worker),
                planning=PlanningConfig(agent_id="planner", max_attempts=1),
            )
            pipeline = Pipeline(config)

            planned = pipeline.start(spec)
            planned = pipeline.confirm_plan(planned.id)

            self.assertEqual(planned.tasks[0].readiness, TaskReadiness.READY)
            self.assertEqual(planned.tasks[1].readiness, TaskReadiness.BLOCKED)
            self.assertEqual(planned.tasks[1].blocked_by, ["base"])

            state = pipeline.execute(planned.id)

            self.assertEqual(state.stage, Stage.READY_TO_MERGE)
            self.assertEqual([task.id for task in state.tasks], ["base", "dependent"])
            dependent = state.tasks[1]
            self.assertEqual(dependent.readiness, TaskReadiness.DONE)
            self.assertEqual(state.tasks[0].worktree, dependent.worktree)
            self.assertEqual(state.tasks[0].branch, dependent.branch)
            self.assertTrue((Path(dependent.worktree) / "base.txt").exists())
            self.assertTrue((Path(dependent.worktree) / "dependent.txt").exists())
            subjects = subprocess.run(
                ["git", "log", "--format=%s", f"{state.base_commit}..HEAD"],
                cwd=Path(dependent.worktree),
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
            ).stdout.splitlines()
            self.assertEqual(subjects, ["feat(dependent): 결과 파일 생성", "feat(base): 기반 파일 생성"])

    def test_manual_pipeline_through_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            git(repo, "init", "-b", "main")
            git(repo, "config", "user.email", "test@example.com")
            git(repo, "config", "user.name", "Test")
            (repo / ".gitignore").write_text(".ai-orchestrator/\n", encoding="utf-8")
            (repo / "README.md").write_text("initial\n", encoding="utf-8")
            git(repo, "add", ".")
            git(repo, "commit", "-m", "initial")

            spec = root / "plan.md"
            spec.write_text("# 기능\n\n## 작업\n\n- [general] 결과 파일 생성\n", encoding="utf-8")
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(
                    auto_commit=True, verify_commands=((sys.executable, "-c", "from pathlib import Path; assert Path('result.txt').exists()"),)
                ),
                agents=(AgentConfig("general-ai", ("general",), (), 1),),
            )
            pipeline = Pipeline(config)

            state = pipeline.start(spec)
            state = pipeline.confirm_plan(state.id)
            self.assertEqual(state.stage, Stage.PLANNED)
            self.assertTrue(state.base_commit)
            self.assertTrue(Path(state.spec_snapshot_path).exists())
            spec.write_text("changed after planning\n", encoding="utf-8")
            state = pipeline.execute(state.id, manual=True)
            self.assertEqual(state.tasks[0].status, TaskStatus.WAITING)
            prompt = Path(state.tasks[0].prompt_path).read_text(encoding="utf-8")
            self.assertIn("결과 파일 생성", prompt)
            self.assertNotIn("changed after planning", prompt)

            worktree = Path(state.tasks[0].worktree)
            (worktree / "result.txt").write_text("done\n", encoding="utf-8")
            state = pipeline.complete_task(state.id, state.tasks[0].id)
            self.assertEqual(state.stage, Stage.READY_TO_MERGE)

            with self.assertRaises(ApprovalRequired):
                pipeline.merge(state.id, approved=False)
            observed_verification_phases: list[str] = []
            save_state = pipeline.store.save

            def capture_verification_progress(saved_state: RunState) -> None:
                if saved_state.verification_progress_phase:
                    observed_verification_phases.append(saved_state.verification_progress_phase)
                save_state(saved_state)

            with (
                patch.object(pipeline.store, "save", side_effect=capture_verification_progress),
                patch.object(pipeline.git, "branch_head", wraps=pipeline.git.branch_head) as branch_head,
                patch.object(pipeline.git, "head", wraps=pipeline.git.head) as head,
                patch.object(pipeline.git, "prepare_detached_worktree", wraps=pipeline.git.prepare_detached_worktree) as prepare_detached_worktree,
                patch.object(pipeline.git, "merge_into", wraps=pipeline.git.merge_into) as merge_into,
                patch.object(pipeline.git, "update_branch", wraps=pipeline.git.update_branch) as update_branch,
                patch.object(pipeline.git, "discard_detached_worktree", wraps=pipeline.git.discard_detached_worktree) as discard_detached_worktree,
            ):
                state = pipeline.verify(state.id)

            for git_call in (
                *branch_head.call_args_list,
                *head.call_args_list,
                *prepare_detached_worktree.call_args_list,
                *merge_into.call_args_list,
                *update_branch.call_args_list,
                *discard_detached_worktree.call_args_list,
            ):
                self.assertTrue(git_call.kwargs["non_interactive"])
                self.assertEqual(git_call.kwargs["timeout_seconds"], LOCAL_GIT_TIMEOUT_SECONDS)
            self.assertIn("checking_main", observed_verification_phases)
            self.assertIn("running_command", observed_verification_phases)
            self.assertIn("finalizing", observed_verification_phases)
            prepare_detached_worktree.assert_not_called()
            update_branch.assert_not_called()
            discard_detached_worktree.assert_not_called()
            self.assertEqual(state.stage, Stage.VERIFIED)
            self.assertFalse((repo / "result.txt").exists())
            self.assertEqual(set(state.verified_task_heads), {state.tasks[0].id})
            self.assertEqual(state.verified_main_head, state.base_commit)
            self.assertTrue(state.verified_integration_head)
            integration_head = state.verified_integration_head
            integration_branch = pipeline._integration_branch_name(state.id)
            self.assertFalse(pipeline.git.branch_exists(integration_branch))
            self.assertFalse(pipeline._verification_worktree_path(state.id).exists())
            with (
                patch.object(pipeline.git, "remote_configured", return_value=True),
                patch.object(pipeline.git, "push_branch") as push_branch,
                patch.object(pipeline.git, "push") as push_main,
                patch.object(pipeline.git, "remote_branch_head", return_value=integration_head),
            ):
                state = pipeline.push(state.id, approved=True)
                self.assertEqual(state.stage, Stage.WORK_BRANCH_PUSHED)
                push_branch.assert_called_once_with("origin", state.execution_branch)
                state = pipeline.merge(state.id, approved=True)
            self.assertEqual(state.stage, Stage.PUSHED)
            push_main.assert_called_once_with("origin")
            self.assertTrue((repo / "result.txt").exists())
            self.assertEqual(pipeline.git.head(repo), integration_head)
            self.assertFalse(worktree.exists())
            self.assertFalse(pipeline.git.branch_exists(state.execution_branch))
            self.assertEqual(pipeline.latest_main_operations(state.id)["merge"]["phase"], "cleanup_completed")
            self.assertTrue((pipeline.store.run_dir(state.id) / "logs" / "verify.log").exists())
            self.assertEqual(state.verification_progress_phase, "completed")
            self.assertEqual(state.verification_progress_current, 1)
            self.assertEqual(state.verification_progress_total, 1)
            self.assertTrue(state.verification_started_at)

    def test_shared_run_without_remote_applies_locally_and_can_be_archived(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] 로컬 결과 생성\n", encoding="utf-8")
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=repo),
                    execution=ExecutionConfig(auto_commit=True, verify_commands=((sys.executable, "-c", "pass"),)),
                    agents=(AgentConfig("manual", ("general",), (), 1),),
                )
            )
            state = pipeline.execute(pipeline.confirm_plan(pipeline.start(spec).id).id, manual=True)
            worktree = Path(state.execution_worktree)
            (worktree / "local.txt").write_text("done\n", encoding="utf-8")
            completed = pipeline.complete_task(state.id, state.tasks[0].id)
            verified = pipeline.verify(completed.id)
            _, _, control = pipeline.status_with_controls(verified.id)

            with (
                patch.object(pipeline.git, "push_branch") as push_branch,
                patch.object(pipeline.git, "push") as push_main,
            ):
                applied = pipeline.merge(verified.id, approved=True)

            self.assertFalse(control.remote_configured)
            self.assertTrue(control.can_apply_main)
            self.assertEqual(applied.stage, Stage.MERGED)
            push_branch.assert_not_called()
            push_main.assert_not_called()
            self.assertEqual((repo / "local.txt").read_text(encoding="utf-8"), "done\n")
            self.assertFalse(worktree.exists())
            self.assertTrue(pipeline.archive_plan(applied.id)["can_archive"])
            summary = next(item for item in pipeline.list_summaries() if item.id == applied.id)
            self.assertTrue(summary.pipeline_complete)

    def test_interrupted_main_apply_requires_inspection_after_process_restart(self) -> None:
        for crash_point, exit_code in (("after_read_tree", 77), ("after_ref_update", 78), ("after_ref_update_remote", 78)):
            with self.subTest(crash_point=crash_point), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                repo = self._repository(root)
                remote = root / "remote.git"
                if crash_point.endswith("_remote"):
                    remote.mkdir()
                    git(remote, "init", "--bare")
                    git(repo, "remote", "add", "origin", str(remote))
                    git(repo, "push", "origin", "main")
                spec = root / "plan.md"
                spec.write_text("## 작업\n\n- [general] 로컬 결과 생성\n", encoding="utf-8")
                config = Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=repo),
                    execution=ExecutionConfig(auto_commit=True, verify_commands=((sys.executable, "-c", "pass"),)),
                    agents=(AgentConfig("manual", ("general",), (), 1),),
                )
                pipeline = Pipeline(config)
                state = pipeline.execute(pipeline.confirm_plan(pipeline.start(spec).id).id, manual=True)
                Path(state.execution_worktree, "local.txt").write_text("done\n", encoding="utf-8")
                verified = pipeline.verify(pipeline.complete_task(state.id, state.tasks[0].id).id)
                if crash_point.endswith("_remote"):
                    verified = pipeline.push(verified.id, approved=True, request_id=str(uuid.uuid4()))
                request_id = str(uuid.uuid4())
                child = """
import os
import sys
from pathlib import Path
from unittest.mock import patch
import ai_orchestrator.git as git_module
from ai_orchestrator.config import Config, ExecutionConfig, ProjectConfig
from ai_orchestrator.git import GitWorkspace
from ai_orchestrator.pipeline import Pipeline

root, repo, run_id, request_id, crash_point = sys.argv[1:]
real_run_command = git_module.run_command
real_guarded = GitWorkspace.guarded_fast_forward_main

def exit_after_read_tree(command, cwd, **kwargs):
    result = real_run_command(command, cwd, **kwargs)
    if command[1:3] == ["read-tree", "-m"]:
        os._exit(77)
    return result

def exit_after_ref_update(workspace, *args, **kwargs):
    real_guarded(workspace, *args, **kwargs)
    os._exit(78)

config = Config(path=Path(root) / "orchestrator.toml", project=ProjectConfig(repo=Path(repo)), execution=ExecutionConfig(), agents=())
if crash_point == "after_read_tree":
    with patch("ai_orchestrator.git.run_command", side_effect=exit_after_read_tree):
        Pipeline(config).merge(run_id, approved=True, request_id=request_id)
else:
    with patch.object(GitWorkspace, "guarded_fast_forward_main", exit_after_ref_update):
        Pipeline(config).merge(run_id, approved=True, request_id=request_id)
"""
                interrupted = subprocess.run(
                    [sys.executable, "-c", child, str(root), str(repo), verified.id, request_id, crash_point],
                    cwd=repo, check=False, timeout=30,
                )
                self.assertEqual(interrupted.returncode, exit_code)

                restarted = Pipeline(config)
                recorded = restarted.status(verified.id)
                operation = restarted.store.load_operation(verified.id, request_id)
                self.assertIsNotNone(operation)
                assert operation is not None
                expected_stage = Stage.WORK_BRANCH_PUSHED if crash_point.endswith("_remote") else Stage.VERIFIED
                self.assertEqual((recorded.stage, recorded.active_step), (expected_stage, RunStep.MERGE))
                self.assertEqual((operation.phase, operation.status), ("applying_main", "running"))
                self.assertEqual(restarted.run_lock_status(verified.id).state, RunLockState.STALE)
                self.assertTrue(restarted.store.project_git_lock_path().exists())
                self.assertEqual(restarted.git.head(repo), verified.verified_main_head if crash_point == "after_read_tree" else verified.verified_integration_head)
                self.assertEqual((repo / "local.txt").read_text(encoding="utf-8"), "done\n")
                _, _, control = restarted.status_with_controls(verified.id)
                self.assertEqual(control.status, IntegrationStatus.UNKNOWN)
                self.assertEqual(control.reason_code, "main_apply_interrupted" if crash_point == "after_read_tree" else "main_apply_recoverable")
                self.assertFalse(control.can_apply_main)
                self.assertEqual(control.can_recover_main_apply, crash_point != "after_read_tree")
                with self.assertRaises(ApprovalRequired):
                    restarted.recover_main_apply(verified.id, approved=False)
                with self.assertRaises(PipelineError):
                    restarted.clear_run_lock(verified.id, approved=True)
                if crash_point == "after_read_tree":
                    with self.assertRaises(PipelineError):
                        restarted.recover_main_apply(verified.id, approved=True)
                    self.assertEqual(restarted.run_lock_status(verified.id).state, RunLockState.STALE)
                    self.assertTrue(restarted.store.project_git_lock_path().exists())
                    continue
                (repo / "local.txt").write_text("changed after crash\n", encoding="utf-8")
                with self.assertRaises(PipelineError):
                    restarted.recover_main_apply(verified.id, approved=True)
                self.assertEqual(restarted.run_lock_status(verified.id).state, RunLockState.STALE)
                self.assertTrue(restarted.store.project_git_lock_path().exists())
                (repo / "local.txt").write_text("done\n", encoding="utf-8")
                recovery_request = str(uuid.uuid4())
                with self.assertRaises(PipelineError):
                    restarted.recover_main_apply(
                        verified.id, approved=True, expected_repo=str(repo), expected_commit="0" * 40,
                    )
                self.assertEqual(restarted.run_lock_status(verified.id).state, RunLockState.STALE)
                with patch.object(restarted.git, "guarded_fast_forward_main", side_effect=AssertionError("Main reapply forbidden")):
                    recovered = restarted.recover_main_apply(
                        verified.id, approved=True, request_id=recovery_request,
                        expected_repo=str(repo), expected_commit=verified.verified_integration_head,
                    )
                    replayed = restarted.recover_main_apply(
                        verified.id, approved=True, request_id=recovery_request,
                        expected_repo=str(repo), expected_commit=verified.verified_integration_head,
                    )
                self.assertEqual(recovered.stage, Stage.WORK_BRANCH_PUSHED if crash_point.endswith("_remote") else Stage.MERGED)
                self.assertEqual(replayed.stage, recovered.stage)
                self.assertEqual(restarted.run_lock_status(verified.id).state, RunLockState.UNLOCKED)
                self.assertFalse(restarted.store.project_git_lock_path().exists())
                self.assertEqual(restarted.git.head(repo), verified.verified_integration_head)
                self.assertEqual((repo / "local.txt").read_text(encoding="utf-8"), "done\n")
                self.assertEqual(restarted.status_with_controls(verified.id)[2].status, IntegrationStatus.MAIN_PUSH_PENDING if crash_point.endswith("_remote") else IntegrationStatus.APPLIED)
                if crash_point.endswith("_remote"):
                    self.assertNotEqual(restarted.git.remote_branch_head("origin", "main"), verified.verified_integration_head)
                    pushed = restarted.retry_main_push(verified.id, approved=True, request_id=str(uuid.uuid4()))
                    self.assertEqual(pushed.stage, Stage.PUSHED)
                    self.assertEqual(restarted.git.remote_branch_head("origin", "main"), verified.verified_integration_head)

    def test_shared_cleanup_releases_sdk_and_recovers_only_owned_partial_removal(self) -> None:
        for mode in ("clean", "partial", "locked", "registered", "foreign_marker", "unrecorded"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                pipeline, state = self._scope_test_run(Path(directory))
                state = pipeline.execute(state.id, manual=True)
                state.stage = Stage.PUSHED
                state.tasks[0].status = TaskStatus.MERGED
                pipeline.store.save(state)
                worktree = Path(state.execution_worktree)
                main_head = pipeline.git.head(pipeline.repo)
                sdk = connected_codex_sdk()
                pipeline._codex_sdk = sdk
                remove_worktree = pipeline.git.remove_worktree
                remove_residue = pipeline.git.remove_worktree_residue
                residue = worktree / "leftover.txt"

                def leave_residue(path: Path, **kwargs: object) -> None:
                    sdk.discard_idle_clients.assert_called_once_with()
                    if mode == "registered":
                        raise GitError(f"command failed: git worktree remove {path}: Permission denied")
                    remove_worktree(path, **kwargs)
                    if mode == "clean":
                        return
                    worktree.mkdir(parents=True)
                    residue.write_text("preserve until cleanup succeeds\n", encoding="utf-8")
                    if mode == "foreign_marker":
                        (worktree / ".git").write_text("gitdir: other-repository\n", encoding="utf-8")
                    raise GitError(f"command failed: git worktree remove {path}: Permission denied")

                if mode == "unrecorded":
                    remove_worktree(worktree)
                    worktree.mkdir(parents=True)
                    residue.write_text("unknown owner\n", encoding="utf-8")
                with (
                    patch.object(pipeline.git, "remove_worktree", side_effect=leave_residue),
                    patch.object(pipeline.git, "remove_worktree_residue", wraps=remove_residue) as cleanup,
                ):
                    if mode == "locked":
                        cleanup.side_effect = GitError("worktree residue is still locked")
                    if mode in {"clean", "partial"}:
                        pipeline._cleanup_shared_workspace(state)
                        self.assertFalse(worktree.exists())
                        self.assertFalse(pipeline.git.branch_exists(state.execution_branch))
                        self.assertEqual(cleanup.call_count, int(mode == "partial"))
                    else:
                        with self.assertRaises((GitError, PipelineError)):
                            pipeline._cleanup_shared_workspace(state)
                        self.assertTrue(worktree.exists())
                        self.assertTrue(pipeline.git.branch_exists(state.execution_branch))
                        self.assertEqual(cleanup.call_count, int(mode == "locked"))
                sdk.discard_idle_clients.assert_called_once_with()
                self.assertEqual(pipeline.git.head(pipeline.repo), main_head)
                recorded = pipeline.store.load(state.id)
                self.assertEqual(recorded.stage, Stage.PUSHED)
                if mode in {"partial", "locked"}:
                    self.assertTrue(any("git worktree remove" in event.message for event in recorded.events))
                if mode == "locked":
                    self.assertIn("preserve", residue.read_text(encoding="utf-8"))
                    restarted = Pipeline(pipeline.config)
                    restarted._cleanup_shared_workspace(recorded)
                    self.assertFalse(worktree.exists())
                    self.assertFalse(restarted.git.branch_exists(state.execution_branch))
                if mode in {"foreign_marker", "unrecorded"}:
                    self.assertTrue(residue.exists())

    def test_shared_main_apply_keeps_push_result_when_workspace_cleanup_is_deferred(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] 로컬 결과 생성\n", encoding="utf-8")
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=repo),
                    execution=ExecutionConfig(auto_commit=True, verify_commands=((sys.executable, "-c", "pass"),)),
                    agents=(AgentConfig("manual", ("general",), (), 1),),
                )
            )
            state = pipeline.execute(pipeline.confirm_plan(pipeline.start(spec).id).id, manual=True)
            worktree = Path(state.execution_worktree)
            (worktree / "local.txt").write_text("done\n", encoding="utf-8")
            completed = pipeline.complete_task(state.id, state.tasks[0].id)
            verified = pipeline.verify(completed.id)
            request_id = str(uuid.uuid4())

            with patch.object(pipeline, "_cleanup_shared_workspace", side_effect=PipelineError("workspace locked")) as cleanup:
                applied = pipeline.merge(verified.id, approved=True, request_id=request_id)
                replayed = pipeline.merge(verified.id, approved=True, request_id=request_id)

            self.assertEqual(applied.stage, Stage.MERGED)
            self.assertEqual(replayed.stage, Stage.MERGED)
            self.assertEqual((repo / "local.txt").read_text(encoding="utf-8"), "done\n")
            self.assertTrue(worktree.exists())
            cleanup.assert_called_once()
            operation = pipeline.store.load_operation(state.id, request_id)
            self.assertIsNotNone(operation)
            assert operation is not None
            self.assertEqual((operation.phase, operation.status, operation.error_code), ("cleanup_deferred", "succeeded", "cleanup_deferred"))
            self.assertEqual(pipeline.latest_main_operations(state.id)["merge"]["error"], "workspace locked")

    def test_shared_work_branch_and_main_are_pushed_before_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            remote = root / "remote.git"
            remote.mkdir()
            git(remote, "init", "--bare")
            repo = self._repository(root)
            git(repo, "remote", "add", "origin", str(remote))
            git(repo, "push", "-u", "origin", "main")
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] 공유 결과 생성\n", encoding="utf-8")
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=repo),
                    execution=ExecutionConfig(auto_commit=True, verify_commands=((sys.executable, "-c", "pass"),)),
                    agents=(AgentConfig("manual", ("general",), (), 1),),
                )
            )
            state = pipeline.execute(pipeline.confirm_plan(pipeline.start(spec).id).id, manual=True)
            task = state.tasks[0]
            worktree = Path(task.worktree)
            (worktree / "shared.txt").write_text("done\n", encoding="utf-8")
            state = pipeline.complete_task(state.id, task.id)
            worktree_state_root = worktree / ".ai-orchestrator"
            worktree_state_root.mkdir()
            (worktree_state_root / "runtime.json").write_text("{}\n", encoding="utf-8")
            verified = pipeline.verify(state.id)

            work_push_request = str(uuid.uuid4())
            work_pushed = pipeline.push(verified.id, approved=True, request_id=work_push_request)

            (repo / "README.md").write_text("local Main change\n", encoding="utf-8")
            (repo / "local-main.txt").write_text("untracked local change\n", encoding="utf-8")
            _, _, disjoint_control = pipeline.status_with_controls(work_pushed.id)
            self.assertEqual(disjoint_control.status, IntegrationStatus.VERIFIED)
            self.assertEqual(disjoint_control.reason_code, "main_dirty_disjoint")
            self.assertTrue(disjoint_control.can_apply_main)

            self.assertEqual(work_pushed.stage, Stage.WORK_BRANCH_PUSHED)
            remote_work_head = subprocess.run(
                ["git", "rev-parse", f"refs/heads/{work_pushed.execution_branch}"], cwd=remote, check=True, capture_output=True, text=True
            ).stdout.strip()
            self.assertEqual(remote_work_head, work_pushed.verified_integration_head)
            self.assertEqual(len(work_pushed.push_receipts), 1)
            self.assertEqual(work_pushed.push_receipts[0].scope, "work_branch")
            self.assertEqual(work_pushed.push_receipts[0].remote_commit, remote_work_head)
            self.assertEqual(work_pushed.push_receipts[0].operation_request_id, work_push_request)
            work_operation = pipeline.store.load_operation(work_pushed.id, work_push_request)
            self.assertIsNotNone(work_operation)
            self.assertEqual(work_operation.result_commit, remote_work_head)
            replayed = pipeline.push(work_pushed.id, approved=True, request_id=work_push_request)
            self.assertEqual(len(replayed.push_receipts), 1)
            self.assertTrue(worktree.exists())

            with (
                patch.object(pipeline.git, "push", side_effect=GitError("remote unavailable")),
                self.assertRaisesRegex(GitError, "remote unavailable"),
            ):
                pipeline.merge(work_pushed.id, approved=True)

            interrupted = pipeline.status(work_pushed.id)
            self.assertEqual(interrupted.stage, Stage.FAILED)
            self.assertEqual(interrupted.failed_step, RunStep.MERGE)
            self.assertEqual(pipeline.git.head(repo), interrupted.verified_integration_head)
            with self.assertRaisesRegex(PipelineError, "Main Push 재시도"):
                pipeline.resume(interrupted.id)

            main_push_request = str(uuid.uuid4())
            completed = pipeline.retry_main_push(interrupted.id, approved=True, request_id=main_push_request)

            self.assertEqual(completed.stage, Stage.PUSHED)
            remote_main_head = subprocess.run(
                ["git", "rev-parse", "refs/heads/main"], cwd=remote, check=True, capture_output=True, text=True
            ).stdout.strip()
            self.assertEqual(remote_main_head, completed.verified_integration_head)
            self.assertEqual([receipt.scope for receipt in completed.push_receipts], ["work_branch", "main"])
            self.assertEqual(completed.push_receipts[-1].remote_commit, remote_main_head)
            self.assertEqual(completed.push_receipts[-1].operation_request_id, main_push_request)
            main_operation = pipeline.store.load_operation(completed.id, main_push_request)
            self.assertIsNotNone(main_operation)
            self.assertEqual(main_operation.result_commit, remote_main_head)
            self.assertEqual((main_operation.phase, main_operation.status), ("cleanup_completed", "succeeded"))
            self.assertEqual(pipeline.latest_main_operations(completed.id)["merge"]["phase"], "pushing")
            self.assertEqual(pipeline.latest_main_operations(completed.id)["retry_main_push"]["phase"], "cleanup_completed")
            self.assertEqual(pipeline.git.head(repo), remote_main_head)
            self.assertEqual((repo / "README.md").read_text(encoding="utf-8"), "local Main change\n")
            self.assertEqual((repo / "local-main.txt").read_text(encoding="utf-8"), "untracked local change\n")
            self.assertFalse(worktree.exists())
            self.assertFalse(pipeline.git.branch_exists(completed.execution_branch))
            self.assertTrue((repo / "shared.txt").is_file())
            statuses = pipeline.workspace_statuses(completed.id)
            self.assertEqual(len(statuses), 1)
            self.assertEqual(statuses[0].state, WorkspaceState.CLEANED)

    def _failed_shared_main_push(self, root: Path) -> tuple[Pipeline, RunState, Path, Path, Path, str]:
        remote = root / "remote.git"
        remote.mkdir()
        git(remote, "init", "--bare")
        repo = self._repository(root)
        git(repo, "remote", "add", "origin", str(remote))
        git(repo, "push", "origin", "main")
        spec = root / "plan.md"
        spec.write_text("## 작업\n\n- [general] 공유 결과 생성\n", encoding="utf-8")
        pipeline = Pipeline(
            Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(auto_commit=True, verify_commands=((sys.executable, "-c", "pass"),)),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
        )
        state = pipeline.execute(pipeline.confirm_plan(pipeline.start(spec).id).id, manual=True)
        worktree = Path(state.execution_worktree)
        (worktree / "shared.txt").write_text("done\n", encoding="utf-8")
        completed = pipeline.complete_task(state.id, state.tasks[0].id)
        verified = pipeline.verify(completed.id)
        work_pushed = pipeline.push(verified.id, approved=True, request_id=str(uuid.uuid4()))
        merge_request = str(uuid.uuid4())
        with patch.object(pipeline.git, "push", side_effect=GitError("remote unavailable")):
            with self.assertRaisesRegex(GitError, "remote unavailable"):
                pipeline.merge(work_pushed.id, approved=True, request_id=merge_request)
        return pipeline, pipeline.status(state.id), repo, remote, worktree, merge_request

    def test_shared_main_push_retry_sends_only_applied_commit_and_replays_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, failed, repo, remote, worktree, merge_request = self._failed_shared_main_push(Path(directory))
            target = failed.verified_integration_head
            source = pipeline.store.load_operation(failed.id, merge_request)
            self.assertEqual((failed.stage, failed.failed_step), (Stage.FAILED, RunStep.MERGE))
            self.assertEqual((source.phase, source.status, source.result_commit), ("pushing", "failed", target))
            restarted = Pipeline(pipeline.config)
            self.assertEqual(restarted.status_with_controls(failed.id)[2].status, IntegrationStatus.MAIN_PUSH_PENDING)
            _, execution, _ = restarted.status_with_controls(failed.id)
            self.assertEqual(execution.action, RunExecutionAction.NONE)
            self.assertEqual(execution.situation, RunExecutionSituation.UNAVAILABLE)
            with self.assertRaisesRegex(PipelineError, "Main Push 재시도"):
                restarted.resume(failed.id)
            self.assertEqual(pipeline.status(failed.id).stage, Stage.FAILED)
            with self.assertRaises(ApprovalRequired):
                pipeline.retry_main_push(failed.id, approved=False)

            (repo / "README.md").write_text("preserved local change\n", encoding="utf-8")
            (repo / "local-untracked.txt").write_text("preserved\n", encoding="utf-8")
            request_id = str(uuid.uuid4())
            with patch.object(pipeline.git, "guarded_fast_forward_main", side_effect=AssertionError("Main must not be merged again")):
                pushed = pipeline.retry_main_push(failed.id, approved=True, request_id=request_id)

            self.assertEqual(pushed.stage, Stage.PUSHED)
            self.assertTrue(all(task.status == TaskStatus.MERGED for task in pushed.tasks))
            self.assertEqual(pipeline.git.remote_branch_head("origin", "main"), target)
            self.assertEqual(pushed.push_receipts[-1].operation_request_id, request_id)
            self.assertEqual(pipeline.store.load_operation(failed.id, request_id).phase, "cleanup_completed")
            self.assertEqual(pipeline.latest_main_operations(failed.id)["retry_main_push"]["status"], "succeeded")
            self.assertEqual((repo / "README.md").read_text(encoding="utf-8"), "preserved local change\n")
            self.assertEqual((repo / "local-untracked.txt").read_text(encoding="utf-8"), "preserved\n")
            self.assertFalse(worktree.exists())
            with patch.object(pipeline.git, "push", side_effect=AssertionError("same request must not push again")):
                self.assertEqual(pipeline.retry_main_push(failed.id, approved=True, request_id=request_id).stage, Stage.PUSHED)

    def test_shared_main_push_retry_reconciles_already_pushed_remote(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, failed, repo, _, _, _ = self._failed_shared_main_push(Path(directory))
            git(repo, "push", "origin", "main")
            with patch.object(pipeline.git, "push", side_effect=AssertionError("remote is already at target")):
                pushed = pipeline.retry_main_push(failed.id, approved=True, request_id=str(uuid.uuid4()))
            self.assertEqual(pushed.stage, Stage.PUSHED)
            self.assertEqual(pushed.push_receipts[-1].remote_commit, failed.verified_integration_head)

    def test_shared_main_push_retry_reports_branch_mismatch_without_losing_applied_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, failed, repo, _, _, _ = self._failed_shared_main_push(Path(directory))
            git(repo, "checkout", "-b", "feature")

            _, _, blocked = pipeline.status_with_controls(failed.id)
            self.assertEqual(blocked.status, IntegrationStatus.MAIN_PUSH_PENDING)
            self.assertEqual(blocked.reason_code, "branch_mismatch")
            self.assertIsNone(blocked.main_dirty)
            self.assertFalse(blocked.can_apply_main)
            with self.assertRaisesRegex(GitError, "expected branch 'main'"):
                pipeline.retry_main_push(failed.id, approved=True)
            self.assertEqual(pipeline.status(failed.id).stage, Stage.FAILED)

            git(repo, "checkout", "main")
            _, _, ready = pipeline.status_with_controls(failed.id)
            self.assertEqual(ready.status, IntegrationStatus.MAIN_PUSH_PENDING)
            self.assertEqual(ready.reason_code, "main_push_retry")

    def test_shared_main_push_retry_blocks_local_or_remote_drift(self) -> None:
        for changed in ("local", "remote"):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                pipeline, failed, repo, remote, _, _ = self._failed_shared_main_push(root)
                if changed == "local":
                    (repo / "README.md").write_text("new Main commit\n", encoding="utf-8")
                    git(repo, "add", "README.md")
                    git(repo, "commit", "-m", "advance local main")
                else:
                    external = root / "external"
                    git(repo, "worktree", "add", "-b", "external", str(external), failed.verified_main_head)
                    (external / "remote-only.txt").write_text("other change\n", encoding="utf-8")
                    git(external, "add", "remote-only.txt")
                    git(external, "commit", "-m", "advance remote main")
                    git(external, "push", "origin", "HEAD:main")
                with patch.object(pipeline.git, "push", side_effect=AssertionError("changed Main must not be pushed")):
                    with self.assertRaisesRegex(PipelineError, "Main이|원격 Main이"):
                        pipeline.retry_main_push(failed.id, approved=True, request_id=str(uuid.uuid4()))
                self.assertEqual(pipeline.status(failed.id).stage, Stage.FAILED)
                self.assertEqual(pipeline.git.remote_branch_head("origin", "main"),
                                 failed.verified_main_head if changed == "local" else pipeline.git.head(external))

    def test_shared_main_push_retry_failure_can_be_retried_without_merging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, failed, _, _, _, _ = self._failed_shared_main_push(Path(directory))
            first_request = str(uuid.uuid4())
            with patch.object(pipeline.git, "push", side_effect=GitError("retry unavailable")):
                with self.assertRaisesRegex(GitError, "retry unavailable"):
                    pipeline.retry_main_push(failed.id, approved=True, request_id=first_request)
            self.assertEqual(pipeline.status(failed.id).failed_step, RunStep.PUSH)
            self.assertEqual(pipeline.store.load_operation(failed.id, first_request).status, "failed")
            with patch.object(pipeline.git, "guarded_fast_forward_main", side_effect=AssertionError("must not remerge")):
                pushed = pipeline.retry_main_push(failed.id, approved=True, request_id=str(uuid.uuid4()))
            self.assertEqual(pushed.stage, Stage.PUSHED)

    def test_shared_main_push_retry_recovers_interrupted_remote_phase_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, failed, _, _, _, merge_request = self._failed_shared_main_push(Path(directory))
            interrupted = pipeline.store.load(failed.id)
            interrupted.stage = Stage.WORK_BRANCH_PUSHED
            interrupted.failed_step = None
            interrupted.active_step = RunStep.MERGE
            interrupted.failure_message = ""
            pipeline.store.save(interrupted)
            source = pipeline.store.load_operation(failed.id, merge_request)
            source.update("main_applied", status="running")
            pipeline.store.save_operation(source)

            self.assertEqual(pipeline.status_with_controls(failed.id)[2].status, IntegrationStatus.MAIN_PUSH_PENDING)
            pushed = pipeline.retry_main_push(failed.id, approved=True, request_id=str(uuid.uuid4()))
            self.assertEqual(pushed.stage, Stage.PUSHED)
            self.assertEqual(pipeline.store.load_operation(failed.id, merge_request).status, "interrupted")

    def test_shared_main_push_retry_rejects_unproven_main_apply_phase(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, failed, _, _, _, merge_request = self._failed_shared_main_push(Path(directory))
            source = pipeline.store.load_operation(failed.id, merge_request)
            source.update("applying_main", status="failed")
            pipeline.store.save_operation(source)
            with self.assertRaisesRegex(PipelineError, "부분 반영 기록이 없습니다"):
                pipeline.retry_main_push(failed.id, approved=True, request_id=str(uuid.uuid4()))
            self.assertEqual(pipeline.status(failed.id).stage, Stage.FAILED)

    def test_shared_main_push_retry_blocks_changed_work_branch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, failed, _, _, worktree, _ = self._failed_shared_main_push(Path(directory))
            (worktree / "shared.txt").write_text("changed after verification\n", encoding="utf-8")
            git(worktree, "add", "shared.txt")
            git(worktree, "commit", "-m", "advance work branch")
            with self.assertRaisesRegex(PipelineError, "작업 branch가 변경되었습니다"):
                pipeline.retry_main_push(failed.id, approved=True, request_id=str(uuid.uuid4()))
            self.assertEqual(pipeline.status(failed.id).stage, Stage.FAILED)

    def test_interrupted_shared_main_push_retry_can_reconcile_remote_on_next_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, failed, _, _, _, _ = self._failed_shared_main_push(Path(directory))
            interrupted_request = str(uuid.uuid4())
            with patch.object(pipeline.git, "push", side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    pipeline.retry_main_push(failed.id, approved=True, request_id=interrupted_request)
            interrupted = pipeline.status(failed.id)
            self.assertEqual((interrupted.stage, interrupted.active_step, interrupted.failed_step), (Stage.FAILED, RunStep.PUSH, None))
            self.assertEqual(pipeline.store.load_operation(failed.id, interrupted_request).status, "running")
            self.assertEqual(pipeline.status_with_controls(failed.id)[2].status, IntegrationStatus.MAIN_PUSH_PENDING)

            pushed = pipeline.retry_main_push(failed.id, approved=True, request_id=str(uuid.uuid4()))
            self.assertEqual(pushed.stage, Stage.PUSHED)
            self.assertEqual(pipeline.store.load_operation(failed.id, interrupted_request).status, "interrupted")

    def test_pre_merge_verification_falls_back_to_task_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] Task 명령 통합 검증\n", encoding="utf-8")
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(auto_commit=True),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
            pipeline = Pipeline(config)
            state = pipeline.execute(pipeline.confirm_plan(pipeline.start(spec).id).id, manual=True)
            task = state.tasks[0]
            task.verify_commands = [
                [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; "
                    "assert Path('result.txt').read_text() == 'done\\n'",
                ]
            ]
            pipeline.store.save(state)
            Path(task.worktree, "result.txt").write_text("done\n", encoding="utf-8")
            completed = pipeline.complete_task(state.id, task.id)

            verified = pipeline.verify(completed.id)

            self.assertEqual(verified.stage, Stage.VERIFIED)
            self.assertTrue(any("using 1 unique task verification commands" in event.message for event in verified.events))
            verify_log = pipeline.store.run_dir(state.id) / "logs" / "verify.log"
            self.assertIn("result.txt", verify_log.read_text(encoding="utf-8"))

    def test_integration_verification_commands_prefer_config_and_deduplicate_tasks(self) -> None:
        tasks = [
            WorkTask(
                id="first",
                title="첫 작업",
                capabilities=["general"],
                verify_commands=[
                    ["git", "worktree", "list", "--porcelain"],
                    ["python", "-m", "compileall", "src"],
                ],
            ),
            WorkTask(
                id="second",
                title="둘째 작업",
                capabilities=["general"],
                verify_commands=[
                    ["python", "-m", "compileall", "src"],
                    ["python", "-m", "unittest"],
                ],
            ),
        ]
        state = RunState(
            id="run-1", spec_path="plan.md", spec_digest="abc", repo_path="repo", main_branch="main", stage=Stage.READY_TO_MERGE, tasks=tasks
        )
        fallback_pipeline = Pipeline(
            Config(
                path=Path("orchestrator.toml"),
                project=ProjectConfig(repo=Path("repo")),
                execution=ExecutionConfig(),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
        )
        configured_pipeline = Pipeline(
            Config(
                path=Path("orchestrator.toml"),
                project=ProjectConfig(repo=Path("repo")),
                execution=ExecutionConfig(verify_commands=(("python", "-m", "pytest"),)),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
        )

        self.assertEqual(
            fallback_pipeline._integration_verification_commands(state), (("python", "-m", "compileall", "src"), ("python", "-m", "unittest"))
        )
        _, excluded = fallback_pipeline._integration_verification_command_selection(state)
        self.assertEqual(excluded, (("git", "worktree", "list", "--porcelain"),))
        self.assertEqual(configured_pipeline._integration_verification_commands(state), (("python", "-m", "pytest"),))

    def test_integration_verification_persists_each_running_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=root),
                    execution=ExecutionConfig(),
                    agents=(AgentConfig("manual", ("general",), (), 1),),
                )
            )
            state = RunState(
                id="verification-progress",
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.READY_TO_MERGE,
            )
            state.begin_verification(2)
            pipeline.store.save(state)
            observed: list[tuple[str, str, int, int]] = []
            invocations: list[tuple[bool, int]] = []

            def capture_progress(
                command: tuple[str, ...],
                cwd: Path,
                *,
                check: bool,
                non_interactive: bool,
                timeout_seconds: int,
                cancel_signal: object | None = None,
                environment_overrides: dict[str, str] | None = None,
            ) -> subprocess.CompletedProcess[str]:
                del cwd, check, cancel_signal
                self.assertIsNone(environment_overrides)
                invocations.append((non_interactive, timeout_seconds))
                saved = pipeline.store.load(state.id)
                observed.append(
                    (
                        saved.verification_progress_phase,
                        saved.verification_progress_detail,
                        saved.verification_progress_current,
                        saved.verification_progress_total,
                    )
                )
                return subprocess.CompletedProcess([], 0, "passed\n", "")

            commands = (("python", "first.py"), ("git", "status", "--short"))
            with patch("ai_orchestrator.pipeline.run_command", side_effect=capture_progress):
                pipeline._run_verification_commands(state, root, commands)

            self.assertEqual(observed, [("running_command", "python first.py", 1, 2), ("running_command", "git status --short", 2, 2)])
            self.assertEqual(invocations, [(True, INTEGRATION_VERIFICATION_COMMAND_TIMEOUT_SECONDS), (True, LOCAL_GIT_TIMEOUT_SECONDS)])

    def test_integration_verification_restores_missing_npm_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            renderer = root / "renderer"
            renderer.mkdir()
            (renderer / "package-lock.json").write_text("{}\n", encoding="utf-8")
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=root),
                    execution=ExecutionConfig(),
                    agents=(AgentConfig("manual", ("general",), (), 1),),
                )
            )
            state = RunState(
                id="npm-dependency-restore",
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.READY_TO_MERGE,
            )
            state.begin_verification(1)
            pipeline.store.save(state)
            invocations: list[tuple[str, ...]] = []

            def capture_command(
                command: tuple[str, ...],
                cwd: Path,
                *,
                check: bool,
                non_interactive: bool,
                timeout_seconds: int,
                cancel_signal: object | None = None,
                environment_overrides: dict[str, str] | None = None,
            ) -> subprocess.CompletedProcess[str]:
                del cwd, check, cancel_signal
                self.assertIsNone(environment_overrides)
                self.assertTrue(non_interactive)
                self.assertEqual(timeout_seconds, INTEGRATION_VERIFICATION_COMMAND_TIMEOUT_SECONDS)
                invocations.append(tuple(command))
                return subprocess.CompletedProcess(command, 0, "passed\n", "")

            command = ("npm", "--prefix", "renderer", "run", "build")
            with patch("ai_orchestrator.pipeline.run_command", side_effect=capture_command):
                pipeline._run_verification_commands(state, root, (command,))

            self.assertEqual(invocations, [("npm", "--prefix", "renderer", "ci"), command])
            verify_log = pipeline.store.run_dir(state.id) / "logs" / "verify.log"
            self.assertIn("$ npm --prefix renderer ci", verify_log.read_text(encoding="utf-8"))

    def test_integration_verification_skips_unneeded_npm_restore(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installed = root / "installed"
            installed.mkdir()
            (installed / "package-lock.json").write_text("{}\n", encoding="utf-8")
            (installed / "node_modules").mkdir()
            unlocked = root / "unlocked"
            unlocked.mkdir()
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=root),
                    execution=ExecutionConfig(),
                    agents=(AgentConfig("manual", ("general",), (), 1),),
                )
            )
            commands = (
                ("npm", "--prefix", "installed", "run", "build"),
                ("npm", "run", "build", "--prefix", "unlocked"),
                ("npm", "--prefix", "installed", "run", "test"),
            )

            self.assertEqual(pipeline._npm_dependency_restore_commands(root, commands), ())

    def test_integration_verification_respects_explicit_npm_restore(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            renderer = root / "renderer"
            renderer.mkdir()
            (renderer / "package-lock.json").write_text("{}\n", encoding="utf-8")
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=root),
                    execution=ExecutionConfig(),
                    agents=(AgentConfig("manual", ("general",), (), 1),),
                )
            )
            commands = (
                ("npm", "--prefix", "renderer", "ci"),
                ("npm", "--prefix", "renderer", "run", "build"),
            )

            self.assertEqual(pipeline._npm_dependency_restore_commands(root, commands), ())

    def test_integration_verification_excludes_worktree_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=root),
                    execution=ExecutionConfig(),
                    agents=(AgentConfig("manual", ("general",), (), 1),),
                )
            )
            state = RunState(
                id="worktree-command-only",
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.READY_TO_MERGE,
                tasks=[
                    WorkTask(
                        id="task",
                        title="잘못된 검증 명령",
                        capabilities=["general"],
                        status=TaskStatus.COMPLETED,
                        verify_commands=[["git", "worktree", "list", "--porcelain"]],
                    )
                ],
            )
            pipeline.store.save(state)

            with self.assertRaisesRegex(PipelineError, "git worktree 명령은 오케스트레이터가 관리"):
                pipeline.verify(state.id)

            restored = pipeline.status(state.id)
            self.assertEqual(restored.stage, Stage.READY_TO_MERGE)
            self.assertTrue(any("worktree 명령을 통합 검증에서 제외" in event.message for event in restored.events))

    def test_integration_verification_command_timeout_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=root),
                    execution=ExecutionConfig(),
                    agents=(AgentConfig("manual", ("general",), (), 1),),
                )
            )
            state = RunState(
                id="verification-timeout", spec_path="plan.md", spec_digest="abc", repo_path=str(root), main_branch="main", stage=Stage.READY_TO_MERGE
            )
            state.begin_verification(1)
            pipeline.store.save(state)

            with patch("ai_orchestrator.pipeline.run_command", side_effect=GitError("command timed out after 600 seconds: test")) as run:
                with self.assertRaisesRegex(PipelineError, "제한시간을 초과"):
                    pipeline._run_verification_commands(state, root, (("python", "slow.py"),))

            self.assertEqual(run.call_args.kwargs["timeout_seconds"], INTEGRATION_VERIFICATION_COMMAND_TIMEOUT_SECONDS)
            self.assertTrue(run.call_args.kwargs["non_interactive"])
            verify_log = pipeline.store.run_dir(state.id) / "logs" / "verify.log"
            self.assertIn("command timed out", verify_log.read_text(encoding="utf-8"))

    def test_integration_verification_requires_any_available_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=root),
                    execution=ExecutionConfig(),
                    agents=(AgentConfig("manual", ("general",), (), 1),),
                )
            )
            state = RunState(
                id="no-verification-command",
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.READY_TO_MERGE,
                tasks=[
                    WorkTask(id="task", title="검증 없는 작업", capabilities=["general"], status=TaskStatus.COMPLETED)
                ],
            )
            pipeline.store.save(state)

            with self.assertRaisesRegex(PipelineError, "통합 검증 명령이 설정되거나 계획되지 않았습니다"):
                pipeline.verify(state.id)

    def test_pre_merge_verification_failure_does_not_change_main(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] 결과 생성\n", encoding="utf-8")
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(auto_commit=True, verify_commands=((sys.executable, "-c", "raise SystemExit(3)"),)),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
            pipeline = Pipeline(config)
            state = pipeline.execute(pipeline.confirm_plan(pipeline.start(spec).id).id, manual=True)
            task = state.tasks[0]
            Path(task.worktree, "result.txt").write_text("done\n", encoding="utf-8")
            state = pipeline.complete_task(state.id, task.id)
            main_head = pipeline.git.head(repo)

            with self.assertRaisesRegex(PipelineError, "통합 검증 명령이 실패했습니다"):
                pipeline.verify(state.id)

            failed = pipeline.status(state.id)
            self.assertEqual(failed.stage, Stage.FAILED)
            self.assertEqual(failed.failed_step, RunStep.VERIFY)
            attempt = failed.verification_attempts[-1]
            self.assertEqual(attempt.commit_queue_task_ids, [task.id])
            self.assertEqual(attempt.failure_phase, "verification_command")
            self.assertEqual(attempt.failed_command, [sys.executable, "-c", "raise SystemExit(3)"])
            self.assertEqual(attempt.candidate_task_ids, [task.id])
            self.assertIn("프로젝트 공통 검증 명령", attempt.attribution_reason)
            self.assertEqual(pipeline.git.head(repo), main_head)
            self.assertFalse((repo / "result.txt").exists())
            self.assertFalse(pipeline._verification_worktree_path(state.id).exists())

            with patch.object(pipeline, "_run_verification_commands"):
                retried = pipeline.verify(state.id)

            self.assertEqual(retried.stage, Stage.VERIFIED)
            self.assertIsNone(retried.failed_step)
            self.assertEqual(retried.failure_message, "")

    def test_pre_merge_verification_combines_independent_task_branches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            verification_script = "from pathlib import Path; assert Path('first.txt').is_file(); assert Path('second.txt').is_file()"
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(verify_commands=((sys.executable, "-c", verification_script),)),
                agents=(AgentConfig("manual", ("general",), (), 2),),
            )
            pipeline = Pipeline(config)
            base_commit = pipeline.git.head(repo)
            tasks: list[WorkTask] = []
            for task_id, filename, risk in (
                ("first", "first.txt", RiskLevel.LOW),
                ("second", "second.txt", RiskLevel.HIGH),
            ):
                branch = f"ai/multi/{task_id}"
                worktree = root / ".ai-worktrees" / "multi" / task_id
                pipeline.git.prepare_worktree(worktree, branch, base_commit)
                (worktree / filename).write_text(f"{task_id}\n", encoding="utf-8")
                git(worktree, "add", filename)
                git(worktree, "commit", "-m", f"add {filename}")
                tasks.append(
                    WorkTask(
                        id=task_id,
                        title=task_id,
                        capabilities=["general"],
                        risk_level=risk,
                        status=TaskStatus.COMPLETED,
                        branch=branch,
                        worktree=str(worktree),
                    )
                )
            state = RunState(
                id="multi",
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(repo),
                main_branch="main",
                stage=Stage.READY_TO_MERGE,
                base_commit=base_commit,
                tasks=tasks,
            )
            pipeline.store.save(state)

            verified = pipeline.verify(state.id)

            self.assertEqual(verified.stage, Stage.VERIFIED)
            self.assertEqual(set(verified.verified_task_heads), {"first", "second"})
            self.assertEqual(verified.verification_attempts[-1].commit_queue_task_ids, ["second", "first"])
            self.assertEqual(verified.verified_main_head, base_commit)
            self.assertTrue(verified.verified_integration_head)
            self.assertFalse((repo / "first.txt").exists())
            self.assertFalse((repo / "second.txt").exists())
            self.assertFalse(pipeline._verification_worktree_path(state.id).exists())

    def test_integration_verification_uses_latest_main_and_applies_exact_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] Task 결과 생성\n", encoding="utf-8")
            verification_script = "from pathlib import Path; assert Path('task.txt').is_file(); assert Path('latest-main.txt').is_file()"
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(auto_commit=True, verify_commands=((sys.executable, "-c", verification_script),)),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
            pipeline = Pipeline(config)
            state = pipeline.execute(pipeline.confirm_plan(pipeline.start(spec).id).id, manual=True)
            task = state.tasks[0]
            Path(task.worktree, "task.txt").write_text("task\n", encoding="utf-8")
            state = pipeline.complete_task(state.id, task.id)

            Path(repo, "latest-main.txt").write_text("latest\n", encoding="utf-8")
            git(repo, "add", "latest-main.txt")
            git(repo, "commit", "-m", "advance main")
            latest_main_head = pipeline.git.head(repo)

            verified = pipeline.verify(state.id)

            self.assertEqual(verified.verified_main_head, latest_main_head)
            self.assertNotEqual(verified.verified_integration_head, latest_main_head)
            self.assertFalse(Path(repo, "task.txt").exists())
            integration_head = verified.verified_integration_head

            with (
                patch.object(pipeline.git, "remote_configured", return_value=True),
                patch.object(pipeline.git, "push_branch"),
                patch.object(pipeline.git, "push"),
                patch.object(pipeline.git, "remote_branch_head", return_value=integration_head),
            ):
                pushed = pipeline.push(verified.id, approved=True)
                merged = pipeline.merge(pushed.id, approved=True)

            self.assertEqual(merged.stage, Stage.PUSHED)
            self.assertEqual(pipeline.git.head(repo), integration_head)
            self.assertTrue(Path(repo, "task.txt").is_file())
            self.assertTrue(Path(repo, "latest-main.txt").is_file())

    def test_legacy_main_apply_bounds_every_git_call(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=root),
                    execution=ExecutionConfig(),
                    agents=(AgentConfig("manual", ("general",), (), 1),),
                )
            )
            state = RunState(
                id="bounded-main-apply",
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.VERIFIED,
                tasks=[
                    WorkTask(id="task", title="완료 작업", capabilities=["general"], branch="task-branch", status=TaskStatus.COMPLETED)
                ],
                verified_task_heads={"task": "task-head"},
                verified_main_head="main-head",
                verified_integration_head="integration-head",
            )
            pipeline.store.save(state)
            integration_branch = pipeline._integration_branch_name(state.id)
            request_id = "07e2e893-f982-4d9c-bf75-3ec38664811e"

            with (
                patch.object(pipeline, "_ensure_main_worktree_ready"),
                patch.object(pipeline.git, "branch_head", side_effect=("task-head", "integration-head")) as branch_head,
                patch.object(pipeline.git, "head", side_effect=("main-head", "integration-head")) as head,
                patch.object(pipeline.git, "branch_exists", return_value=True) as branch_exists,
                patch.object(pipeline.git, "guarded_fast_forward_main") as fast_forward,
                patch.object(pipeline.git, "delete_branch") as delete_branch,
            ):
                merged = pipeline.merge(state.id, approved=True, request_id=request_id)
                replayed = pipeline.merge(state.id, approved=True, request_id=request_id)

            options = {"non_interactive": True, "timeout_seconds": LOCAL_GIT_TIMEOUT_SECONDS}
            self.assertEqual(merged.stage, Stage.MERGED)
            self.assertEqual(replayed.stage, Stage.MERGED)
            branch_head.assert_has_calls([call("task-branch", **options), call(integration_branch, **options)])
            head.assert_has_calls([call(root, **options), call(root, **options)])
            branch_exists.assert_has_calls([call(integration_branch, **options), call(integration_branch, **options)])
            fast_forward.assert_called_once_with(
                "main-head", "integration-head", ignored_untracked_roots=(pipeline.store.root,), **options
            )
            delete_branch.assert_called_once_with(integration_branch, **options)
            operation = pipeline.store.load_operation(state.id, request_id)
            self.assertIsNotNone(operation)
            assert operation is not None
            self.assertEqual((operation.phase, operation.status), ("main_applied", "succeeded"))

    def test_merge_requires_reverification_when_main_changes_after_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline, state = self._ready_manual_run(root, repo)
            verified = pipeline.verify(state.id)
            Path(repo, "late-main.txt").write_text("late\n", encoding="utf-8")
            git(repo, "add", "late-main.txt")
            git(repo, "commit", "-m", "late main change")
            changed_main_head = pipeline.git.head(repo)

            with self.assertRaisesRegex(PipelineError, "main HEAD changed after integration verification"):
                pipeline.merge(verified.id, approved=True)

            invalidated = pipeline.status(verified.id)
            self.assertEqual(invalidated.stage, Stage.READY_TO_MERGE)
            self.assertEqual(invalidated.verified_task_heads, {})
            self.assertEqual(invalidated.verified_main_head, "")
            self.assertEqual(invalidated.verified_integration_head, "")
            self.assertEqual(pipeline.git.head(repo), changed_main_head)

    def test_manual_task_verification_runs_before_task_completion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline, state = self._waiting_manual_run(root, repo)
            task = state.tasks[0]
            task.verify_commands = [
                [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; "
                    "assert Path('result.txt').read_text() == 'done\\n'",
                ]
            ]
            pipeline.store.save(state)
            Path(task.worktree, "result.txt").write_text("done\n", encoding="utf-8")

            completed = pipeline.complete_task(state.id, task.id)

            self.assertEqual(completed.stage, Stage.READY_TO_MERGE)
            self.assertEqual(completed.tasks[0].status, TaskStatus.COMPLETED)
            verification_log = pipeline.store.run_dir(state.id) / "logs" / f"{task.id}-verify.log"
            self.assertTrue(verification_log.is_file())
            self.assertIn("Task 검증 로그", pipeline.task_log(state.id, task.id))

    def test_automatic_task_verification_repeated_failure_keeps_task_in_failed_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "plan.md"
            spec.write_text("검증 실패 Task", encoding="utf-8")
            worker_script = (
                "import sys; from pathlib import Path; sys.stdin.read(); p=Path('result.txt'); "
                "p.write_text((p.read_text() if p.exists() else '')+'done\\n', encoding='utf-8')"
            )
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(auto_commit=True),
                agents=(
                    AgentConfig("worker", ("general",), (sys.executable, "-c", worker_script), 1, provider_id="custom"),
                ),
            )
            pipeline = Pipeline(config)
            state = RunState(
                id="task-verify-failure",
                spec_path=str(spec),
                spec_digest="abc",
                repo_path=str(repo),
                main_branch="main",
                stage=Stage.PLANNED,
                base_commit=pipeline.git.head(repo),
                tasks=[
                    WorkTask(
                        id="result",
                        title="결과 생성",
                        capabilities=["general"],
                        agent_id="worker",
                        provider_id="custom",
                        verify_commands=[[sys.executable, "-c", "raise SystemExit(7)"]],
                    )
                ],
            )
            pipeline.store.save(state)

            failed = pipeline.execute(state.id)

            self.assertEqual(failed.stage, Stage.FAILED)
            self.assertEqual(failed.tasks[0].status, TaskStatus.FAILED)
            self.assertEqual(failed.tasks[0].failed_action, TaskAction.VERIFY)
            self.assertEqual(failed.tasks[0].attempt_count, 4)
            self.assertIn("자동 복구 3회", failed.tasks[0].error)
            self.assertIn("task verification command failed", failed.tasks[0].error)
            self.assertTrue((pipeline.store.run_dir(state.id) / "logs" / "result-verify.log").is_file())

            failed.tasks[0].verify_commands = [[sys.executable, "-c", "print('verified')"]]
            pipeline.store.save(failed)
            with patch.object(pipeline, "_run_executor") as executor, patch.object(pipeline, "_run_review_cycles") as reviewer:
                retried = pipeline.retry_task(failed.id, failed.tasks[0].id)

            self.assertEqual(retried.stage, Stage.READY_TO_MERGE)
            self.assertEqual(retried.tasks[0].status, TaskStatus.COMPLETED)
            self.assertEqual(retried.tasks[0].attempt_count, 4)
            self.assertIsNone(retried.tasks[0].failed_action)
            executor.assert_not_called()
            reviewer.assert_not_called()

    def test_legacy_no_commit_retry_restores_existing_task_commit_to_verify(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "plan.md"
            spec.write_text("기존 구현 검증", encoding="utf-8")
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(auto_commit=True),
                agents=(
                    AgentConfig("worker", ("general",), (sys.executable, "-c", "raise SystemExit(99)"), 1, provider_id="custom"),
                ),
            )
            pipeline = Pipeline(config)
            state = RunState(
                id="legacy-no-commit",
                spec_path=str(spec),
                spec_digest="abc",
                repo_path=str(repo),
                main_branch="main",
                stage=Stage.PLANNED,
                base_commit=pipeline.git.head(repo),
                tasks=[
                    WorkTask(
                        id="existing-result",
                        title="기존 결과",
                        capabilities=["general"],
                        agent_id="worker",
                        provider_id="custom",
                        verify_commands=[[sys.executable, "-c", "print('verified')"]],
                    )
                ],
            )
            pipeline.store.save(state)
            pipeline._prepare_tasks(state)
            task = state.tasks[0]
            worktree = Path(task.worktree)
            (worktree / "result.txt").write_text("done\n", encoding="utf-8")
            git(worktree, "add", "result.txt")
            git(worktree, "commit", "-m", f"feat({task.id}): existing implementation")
            task.status = TaskStatus.FAILED
            task.failed_action = TaskAction.EXECUTE
            task.attempt_count = 6
            task.error = f"agent {task.agent_id} produced no commit for {task.id}"
            state.fail_step(RunStep.AGENT_EXECUTION, task.error)
            state.refresh_task_readiness()
            pipeline.store.save(state)

            with patch.object(pipeline, "_run_executor") as executor:
                retried = pipeline.retry_task(state.id, task.id)

            self.assertEqual(retried.stage, Stage.READY_TO_MERGE)
            self.assertEqual(retried.tasks[0].status, TaskStatus.COMPLETED)
            self.assertEqual(retried.tasks[0].attempt_count, 6)
            executor.assert_not_called()
            self.assertTrue(any("existing implementation commit restored at verify" in event.message for event in retried.events))

    def test_legacy_no_commit_retry_requires_task_named_commit(self) -> None:
        pipeline = Pipeline(
            Config(
                path=Path("orchestrator.toml"),
                project=ProjectConfig(repo=Path("repo")),
                execution=ExecutionConfig(),
                agents=(AgentConfig("worker", ("general",), (), 1),),
            )
        )
        task = WorkTask(
            id="expected-task",
            title="기대 작업",
            capabilities=["general"],
            agent_id="worker",
            worktree="worktree",
            status=TaskStatus.FAILED,
            failed_action=TaskAction.EXECUTE,
            error="agent worker produced no commit for expected-task",
        )
        state = RunState(
            id="run-1",
            spec_path="plan.md",
            spec_digest="abc",
            repo_path="repo",
            main_branch="main",
            stage=Stage.FAILED,
            base_commit="a" * 40,
            tasks=[task],
        )

        with patch.object(pipeline.git, "commit_subjects_since", return_value=["feat(other-task): unrelated dependency"]):
            pipeline._restore_legacy_no_commit_retry_action(state, task)

        self.assertEqual(task.failed_action, TaskAction.EXECUTE)

    def test_merge_rejects_task_branch_changed_after_verification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] 결과 생성\n", encoding="utf-8")
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(auto_commit=True, verify_commands=((sys.executable, "-c", "raise SystemExit(0)"),)),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
            pipeline = Pipeline(config)
            state = pipeline.execute(pipeline.confirm_plan(pipeline.start(spec).id).id, manual=True)
            task = state.tasks[0]
            worktree = Path(task.worktree)
            (worktree / "result.txt").write_text("done\n", encoding="utf-8")
            state = pipeline.complete_task(state.id, task.id)
            state = pipeline.verify(state.id)
            with (
                patch.object(pipeline.git, "remote_configured", return_value=True),
                patch.object(pipeline.git, "push_branch"),
                patch.object(pipeline.git, "remote_branch_head", return_value=state.verified_integration_head),
            ):
                state = pipeline.push(state.id, approved=True)
            (worktree / "late.txt").write_text("late\n", encoding="utf-8")
            git(worktree, "add", "late.txt")
            git(worktree, "commit", "-m", "late change")
            main_head = pipeline.git.head(repo)

            with (
                patch.object(pipeline.git, "remote_configured", return_value=True),
                self.assertRaisesRegex(PipelineError, "changed after verification"),
            ):
                pipeline.merge(state.id, approved=True)

            invalidated = pipeline.status(state.id)
            self.assertEqual(invalidated.stage, Stage.READY_TO_MERGE)
            self.assertEqual(invalidated.verified_task_heads, {})
            self.assertEqual(invalidated.verified_main_head, "")
            self.assertEqual(invalidated.verified_integration_head, "")
            self.assertEqual(pipeline.git.head(repo), main_head)

    def test_legacy_merged_run_can_verify_and_push(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(verify_commands=((sys.executable, "-c", "raise SystemExit(0)"),)),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
            pipeline = Pipeline(config)
            state = RunState(
                id="legacy-merged",
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(repo),
                main_branch="main",
                stage=Stage.MERGED,
                tasks=[
                    WorkTask(id="done", title="done", capabilities=["general"], status=TaskStatus.MERGED)
                ],
            )
            pipeline.store.save(state)

            verified = pipeline.verify(state.id)
            with (
                patch.object(pipeline.git, "remote_configured", return_value=True),
                patch.object(pipeline.git, "push") as push,
                patch.object(pipeline.git, "remote_branch_head", return_value=pipeline.git.head(repo)),
            ):
                pushed = pipeline.push(verified.id, approved=True)

            self.assertEqual(verified.verified_task_heads, {})
            self.assertEqual(pushed.stage, Stage.PUSHED)
            push.assert_called_once_with("origin")

    def test_execute_keeps_planning_base_when_main_changed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] 결과 생성\n", encoding="utf-8")
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(AgentConfig("general", ("general",), (), 1),),
            )
            pipeline = Pipeline(config)
            state = pipeline.start(spec)
            state = pipeline.confirm_plan(state.id)
            planned_base = state.base_commit
            (repo / "README.md").write_text("changed\n", encoding="utf-8")
            git(repo, "add", "README.md")
            git(repo, "commit", "-m", "advance main")

            restored = pipeline.execute(state.id, manual=True)

            self.assertEqual(restored.stage, Stage.EXECUTING)
            self.assertEqual(restored.tasks[0].status, TaskStatus.WAITING)
            self.assertEqual(pipeline.git.head(Path(restored.tasks[0].worktree)), planned_base)
            self.assertFalse(pipeline.store.lock_path(state.id).exists())

    def test_dirty_main_allows_shared_execution_and_verification_when_disjoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            dirty_path = pipeline.repo / "local-main.txt"
            dirty_path.write_text("keep local\n", encoding="utf-8")

            state = pipeline.execute(state.id, manual=True)
            worktree = Path(state.tasks[0].worktree)
            (worktree / "result.txt").write_text("done\n", encoding="utf-8")
            state = pipeline.complete_task(state.id, state.tasks[0].id)
            state.tasks[0].verify_commands = [[sys.executable, "-c", "pass"]]
            pipeline.store.save(state)

            verified = pipeline.verify(state.id)
            _, _, control = pipeline.status_with_controls(state.id)

            self.assertEqual(verified.stage, Stage.VERIFIED)
            self.assertEqual(control.status, IntegrationStatus.VERIFIED)
            self.assertEqual(control.reason_code, "main_dirty_disjoint")
            self.assertTrue(control.can_apply_main)
            self.assertTrue(control.main_dirty)
            dirty_path.unlink()

            (pipeline.repo / "README.md").write_text("main advanced\n", encoding="utf-8")
            git(pipeline.repo, "add", "README.md")
            git(pipeline.repo, "commit", "-m", "advance main after verification")
            _, _, stale = pipeline.status_with_controls(state.id)

            self.assertEqual(stale.status, IntegrationStatus.STALE)
            self.assertEqual(stale.reason_code, "main_changed")
            self.assertTrue(stale.can_verify)

            reverified = pipeline.verify(state.id)

            self.assertEqual(reverified.stage, Stage.VERIFIED)
            self.assertEqual(reverified.verified_main_head, pipeline.git.head(pipeline.repo))
            self.assertTrue(reverified.verified_integration_head)

    def test_dirty_main_allows_isolated_execution_and_verification_but_blocks_apply(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory), mode=ExecutionWorkspaceMode.ISOLATED)
            planned_base = state.base_commit
            (pipeline.repo / "README.md").write_text("main advanced\n", encoding="utf-8")
            git(pipeline.repo, "add", "README.md")
            git(pipeline.repo, "commit", "-m", "advance main before task execution")
            latest_main_head = pipeline.git.head(pipeline.repo)
            dirty_path = pipeline.repo / "local-main.txt"
            dirty_path.write_text("keep local\n", encoding="utf-8")

            state = pipeline.execute(state.id, manual=True)
            self.assertEqual(state.base_commit, planned_base)
            task = state.tasks[0]
            Path(task.worktree, "result.txt").write_text("done\n", encoding="utf-8")
            state = pipeline.complete_task(state.id, task.id)
            state.tasks[0].verify_commands = [[sys.executable, "-c", "pass"]]
            pipeline.store.save(state)

            verified = pipeline.verify(state.id)
            _, _, control = pipeline.status_with_controls(state.id)

            self.assertEqual(verified.stage, Stage.VERIFIED)
            self.assertEqual(verified.verified_main_head, latest_main_head)
            self.assertEqual(control.status, IntegrationStatus.APPLY_BLOCKED)
            self.assertEqual(control.reason_code, "main_dirty")
            self.assertFalse(control.can_apply_main)
            self.assertEqual(dirty_path.read_text(encoding="utf-8"), "keep local\n")
            self.assertEqual(pipeline.git.head(pipeline.repo), latest_main_head)

    def test_branch_mismatch_blocks_verification_without_hiding_stale_main(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline, state = self._ready_manual_run(root, repo)
            git(repo, "checkout", "-b", "feature")

            _, _, blocked = pipeline.status_with_controls(state.id)
            self.assertEqual(blocked.status, IntegrationStatus.NEEDS_VERIFICATION)
            self.assertEqual(blocked.reason_code, "branch_mismatch")
            self.assertFalse(blocked.can_verify)
            self.assertIsNone(blocked.main_dirty)
            with patch.object(pipeline.git, "current_branch", side_effect=GitError("branch query failed")):
                _, _, unknown = pipeline.status_with_controls(state.id)
            self.assertEqual(unknown.status, IntegrationStatus.UNKNOWN)
            self.assertEqual(unknown.reason_code, "query_failed")
            self.assertIsNone(unknown.main_dirty)
            with self.assertRaisesRegex(GitError, "expected branch 'main'"):
                pipeline.verify(state.id)

            git(repo, "checkout", "main")
            verified = pipeline.verify(state.id)
            git(repo, "checkout", "feature")
            _, _, apply_blocked = pipeline.status_with_controls(state.id)
            self.assertEqual(apply_blocked.status, IntegrationStatus.APPLY_BLOCKED)
            self.assertEqual(apply_blocked.reason_code, "branch_mismatch")
            self.assertFalse(apply_blocked.can_apply_main)

            git(repo, "checkout", "main")
            (repo / "late-main.txt").write_text("latest\n", encoding="utf-8")
            git(repo, "add", "late-main.txt")
            git(repo, "commit", "-m", "advance main after verification")
            git(repo, "checkout", "feature")
            _, _, stale = pipeline.status_with_controls(state.id)
            self.assertEqual(stale.status, IntegrationStatus.STALE)
            self.assertEqual(stale.reason_code, "main_changed")
            self.assertFalse(stale.can_verify)
            self.assertIn("Main으로 돌아온 뒤 재검증", stale.reason)
            self.assertEqual(pipeline.status(state.id).tasks[0].status, TaskStatus.COMPLETED)
            self.assertEqual(verified.verified_main_head, pipeline.git.branch_head("feature"))

            git(repo, "checkout", "main")
            _, _, ready = pipeline.status_with_controls(state.id)
            self.assertEqual(ready.status, IntegrationStatus.STALE)
            self.assertTrue(ready.can_verify)

    def test_execution_control_blocks_original_branch_mismatch_but_not_dirty_main(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            git(pipeline.repo, "checkout", "-b", "feature")

            _, blocked, _ = pipeline.status_with_controls(state.id)
            self.assertEqual(blocked.situation, RunExecutionSituation.UNAVAILABLE)
            self.assertEqual(blocked.action, RunExecutionAction.NONE)
            self.assertIn("Main으로 돌아온 뒤", blocked.reason)
            with self.assertRaisesRegex(GitError, "expected branch 'main'"):
                pipeline.execute(state.id, manual=True)

            git(pipeline.repo, "checkout", "main")
            (pipeline.repo / "local-main.txt").write_text("keep local\n", encoding="utf-8")
            _, ready, _ = pipeline.status_with_controls(state.id)
            self.assertEqual(ready.action, RunExecutionAction.EXECUTE)
            state = pipeline.execute(state.id, manual=True)
            git(pipeline.repo, "checkout", "feature")
            _, resume_blocked, _ = pipeline.status_with_controls(state.id)
            self.assertEqual(resume_blocked.action, RunExecutionAction.NONE)
            self.assertEqual(resume_blocked.situation, RunExecutionSituation.UNAVAILABLE)
            self.assertEqual(state.tasks[0].status, TaskStatus.WAITING)

            Path(state.tasks[0].worktree, "result.txt").write_text("done\n", encoding="utf-8")
            with self.assertRaisesRegex(GitError, "expected branch 'main'"):
                pipeline.complete_task(state.id, state.tasks[0].id)
            self.assertEqual(pipeline.status(state.id).tasks[0].status, TaskStatus.WAITING)

            failed = pipeline.status(state.id)
            failed.fail_step(RunStep.AGENT_EXECUTION, "interrupted")
            pipeline.store.save(failed)
            _, failed_resume, _ = pipeline.status_with_controls(state.id)
            self.assertEqual(failed_resume.action, RunExecutionAction.NONE)
            self.assertEqual(failed_resume.situation, RunExecutionSituation.UNAVAILABLE)

            with patch.object(pipeline.git, "current_branch", side_effect=GitError("branch query failed")):
                _, unknown, _ = pipeline.status_with_controls(state.id)
            self.assertEqual(unknown.situation, RunExecutionSituation.STATUS_UNKNOWN)
            self.assertIn("branch query failed", unknown.reason)

    def test_shared_work_branch_push_rejects_original_branch_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state = pipeline.execute(state.id, manual=True)
            Path(state.tasks[0].worktree, "result.txt").write_text("done\n", encoding="utf-8")
            state = pipeline.complete_task(state.id, state.tasks[0].id)
            state.tasks[0].verify_commands = [[sys.executable, "-c", "pass"]]
            pipeline.store.save(state)
            verified = pipeline.verify(state.id)
            git(pipeline.repo, "checkout", "-b", "feature")

            with patch.object(pipeline.git, "remote_configured", return_value=True), patch.object(pipeline.git, "push_branch") as push_branch:
                with self.assertRaisesRegex(GitError, "expected branch 'main'"):
                    pipeline.push(verified.id, approved=True)

            push_branch.assert_not_called()
            self.assertEqual(pipeline.status(verified.id).stage, Stage.VERIFIED)

    def test_dirty_main_overlap_blocks_shared_apply_without_changing_main(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state = pipeline.execute(state.id, manual=True)
            worktree = Path(state.tasks[0].worktree)
            (worktree / "result.txt").write_text("verified\n", encoding="utf-8")
            state = pipeline.complete_task(state.id, state.tasks[0].id)
            state.tasks[0].verify_commands = [[sys.executable, "-c", "pass"]]
            pipeline.store.save(state)
            verified = pipeline.verify(state.id)
            original_main = pipeline.git.head(pipeline.repo)
            (pipeline.repo / "local-main.txt").write_text("separate local\n", encoding="utf-8")
            _, _, initially_safe = pipeline.status_with_controls(state.id)
            self.assertTrue(initially_safe.can_apply_main)
            (pipeline.repo / "result.txt").write_text("local\n", encoding="utf-8")

            _, _, control = pipeline.status_with_controls(state.id)
            self.assertEqual(control.status, IntegrationStatus.APPLY_BLOCKED)
            self.assertEqual(control.reason_code, "main_overlap")
            self.assertFalse(control.can_apply_main)
            with self.assertRaisesRegex(GitError, "overlap verified work"):
                pipeline.merge(verified.id, approved=True)
            self.assertEqual(pipeline.git.head(pipeline.repo), original_main)
            self.assertEqual((pipeline.repo / "result.txt").read_text(encoding="utf-8"), "local\n")
            self.assertEqual((pipeline.repo / "local-main.txt").read_text(encoding="utf-8"), "separate local\n")

    def test_shared_work_branch_push_can_reverify_after_main_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state = pipeline.execute(state.id, manual=True)
            worktree = Path(state.tasks[0].worktree)
            (worktree / "result.txt").write_text("done\n", encoding="utf-8")
            state = pipeline.complete_task(state.id, state.tasks[0].id)
            state.tasks[0].verify_commands = [[sys.executable, "-c", "pass"]]
            pipeline.store.save(state)
            verified = pipeline.verify(state.id)
            with (
                patch.object(pipeline.git, "remote_configured", return_value=True),
                patch.object(pipeline.git, "push_branch"),
                patch.object(pipeline.git, "remote_branch_head", return_value=verified.verified_integration_head),
            ):
                pushed = pipeline.push(verified.id, approved=True)
            previous_integration_head = pushed.verified_integration_head

            (pipeline.repo / "README.md").write_text("main advanced\n", encoding="utf-8")
            git(pipeline.repo, "add", "README.md")
            git(pipeline.repo, "commit", "-m", "advance main after work branch push")
            latest_main_head = pipeline.git.head(pipeline.repo)
            _, _, stale = pipeline.status_with_controls(state.id)

            self.assertEqual(pushed.stage, Stage.WORK_BRANCH_PUSHED)
            self.assertEqual(stale.status, IntegrationStatus.STALE)
            self.assertTrue(stale.can_verify)

            reverified = pipeline.verify(state.id)

            self.assertEqual(reverified.stage, Stage.VERIFIED)
            self.assertEqual(reverified.verified_main_head, latest_main_head)
            self.assertNotEqual(reverified.verified_integration_head, previous_integration_head)
            self.assertEqual(reverified.pushed_work_branch_head, "")

    def test_shared_work_branch_push_fails_when_remote_commit_does_not_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._scope_test_run(Path(directory))
            state = pipeline.execute(state.id, manual=True)
            worktree = Path(state.tasks[0].worktree)
            (worktree / "result.txt").write_text("done\n", encoding="utf-8")
            state = pipeline.complete_task(state.id, state.tasks[0].id)
            state.tasks[0].verify_commands = [[sys.executable, "-c", "pass"]]
            pipeline.store.save(state)
            verified = pipeline.verify(state.id)
            request_id = str(uuid.uuid4())

            with (
                patch.object(pipeline.git, "remote_configured", return_value=True),
                patch.object(pipeline.git, "push_branch"),
                patch.object(pipeline.git, "remote_branch_head", return_value="0" * 40),
                self.assertRaisesRegex(PipelineError, "remote branch commit does not match pushed commit"),
            ):
                pipeline.push(verified.id, approved=True, request_id=request_id)

            failed = pipeline.status(verified.id)
            operation = pipeline.store.load_operation(verified.id, request_id)
            self.assertEqual(failed.stage, Stage.FAILED)
            self.assertEqual(failed.failed_step, RunStep.PUSH)
            self.assertEqual(failed.push_receipts, [])
            self.assertIsNotNone(operation)
            self.assertEqual(operation.phase, "confirming_remote")
            self.assertEqual(operation.status, "failed")
            self.assertEqual(operation.result_commit, "")

    def test_manual_completion_without_commit_keeps_run_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] 결과 생성\n", encoding="utf-8")
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(AgentConfig("general", ("general",), (), 1),),
            )
            pipeline = Pipeline(config)
            state = pipeline.execute(pipeline.confirm_plan(pipeline.start(spec).id).id, manual=True)

            with self.assertRaisesRegex(PipelineError, "produced no commit in the shared workspace"):
                pipeline.complete_task(state.id, state.tasks[0].id)

            restored = pipeline.status(state.id)
            self.assertEqual(restored.stage, Stage.EXECUTING)
            self.assertIsNone(restored.active_step)
            self.assertFalse(pipeline.store.lock_path(state.id).exists())

    def test_agent_timeout_is_logged_and_marks_failed_step(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] 오래 실행\n", encoding="utf-8")
            script = "import sys, time; sys.stdin.read(); print('started', flush=True); time.sleep(10)"
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(agent_timeout_seconds=1),
                agents=(AgentConfig("slow-ai", ("general",), (sys.executable, "-c", script), 1),),
            )
            pipeline = Pipeline(config)

            state = pipeline.execute(pipeline.confirm_plan(pipeline.start(spec).id).id)

            task = state.tasks[0]
            self.assertEqual(state.stage, Stage.FAILED)
            self.assertEqual(state.failed_step, RunStep.AGENT_EXECUTION)
            self.assertIn("timed out after 1 seconds", state.failure_message)
            self.assertEqual(task.status, TaskStatus.FAILED)
            self.assertEqual(task.failed_action, TaskAction.EXECUTE)
            self.assertEqual(task.attempt_count, 1)
            self.assertIsNone(task.active_action)
            self.assertIn("timed out after 1 seconds", task.error)
            self.assertIn("timed out after 1 seconds", Path(task.log_path).read_text(encoding="utf-8"))
            self.assertFalse(pipeline.store.lock_path(state.id).exists())

    def test_retry_task_runs_only_selected_failed_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] 첫 번째 결과\n- [general] 두 번째 결과\n", encoding="utf-8")
            script = (
                "import sys; from pathlib import Path; sys.stdin.read(); "
                "marker=Path('.attempted'); "
                "first=not marker.exists(); marker.write_text('attempted'); "
                "sys.exit(3) if first else "
                "Path('result.txt').write_text('done\\n', encoding='utf-8')"
            )
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(auto_commit=True),
                agents=(AgentConfig("worker", ("general",), (sys.executable, "-c", script), 2),),
            )
            pipeline = Pipeline(config)

            failed = pipeline.execute(pipeline.confirm_plan(pipeline.start(spec).id).id)
            selected_id = failed.tasks[0].id
            retried = pipeline.retry_task(failed.id, selected_id)

            selected = retried.tasks[0]
            untouched = retried.tasks[1]
            self.assertEqual(retried.stage, Stage.EXECUTING)
            self.assertEqual(selected.status, TaskStatus.COMPLETED)
            self.assertEqual(selected.attempt_count, 2)
            self.assertIsNone(selected.failed_action)
            self.assertEqual(untouched.status, TaskStatus.PENDING)
            self.assertEqual(untouched.attempt_count, 0)

    def test_execute_task_runs_only_selected_ready_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] 첫 번째 결과\n- [general] 두 번째 결과\n", encoding="utf-8")
            script = (
                "import os, sys; from pathlib import Path; sys.stdin.read(); "
                "task=os.environ['AI_ORCHESTRATOR_TASK_ID']; "
                "Path(task + '.txt').write_text('done\\n', encoding='utf-8')"
            )
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(auto_commit=True, max_parallel=2),
                agents=(
                    AgentConfig("worker", ("general",), (sys.executable, "-c", script), 2, provider_id="local"),
                    AgentConfig("claude-worker", ("general",), (sys.executable, "-c", script), 2, provider_id="claude"),
                ),
                routing=RoutingConfig(default_provider="local"),
            )
            pipeline = Pipeline(config)
            planned = pipeline.start(spec)
            planned = pipeline.confirm_plan(planned.id)
            selected_id = planned.tasks[0].id
            remaining_id = planned.tasks[1].id

            partial = pipeline.execute_task(planned.id, selected_id)

            selected = next(task for task in partial.tasks if task.id == selected_id)
            remaining = next(task for task in partial.tasks if task.id == remaining_id)
            self.assertEqual(partial.stage, Stage.EXECUTING)
            self.assertIsNone(partial.active_step)
            self.assertEqual(selected.status, TaskStatus.COMPLETED)
            self.assertEqual(selected.readiness, TaskReadiness.DONE)
            self.assertEqual(selected.attempt_count, 1)
            self.assertTrue(Path(selected.worktree, f"{selected_id}.txt").is_file())
            self.assertEqual(remaining.status, TaskStatus.PENDING)
            self.assertEqual(remaining.readiness, TaskReadiness.READY)
            self.assertEqual(remaining.attempt_count, 0)
            self.assertFalse(Path(remaining.worktree, f"{remaining_id}.txt").exists())

            with self.assertRaisesRegex(PipelineError, "edit and reconfirm the plan"):
                pipeline.execute(partial.id, agent_overrides={selected_id: "claude-worker"})

            with self.assertRaisesRegex(PipelineError, "edit and reconfirm the plan"):
                pipeline.execute_task(partial.id, remaining_id, agent_overrides={remaining_id: "claude-worker"})

            completed = pipeline.execute_task(partial.id, remaining_id)

            self.assertEqual(completed.stage, Stage.READY_TO_MERGE)
            self.assertTrue(all(task.status == TaskStatus.COMPLETED for task in completed.tasks))
            selected = next(task for task in completed.tasks if task.id == selected_id)
            remaining = next(task for task in completed.tasks if task.id == remaining_id)
            self.assertEqual(selected.agent_id, "worker")
            self.assertEqual(selected.provider_id, "local")
            self.assertEqual(remaining.agent_id, "worker")
            self.assertEqual(remaining.provider_id, "local")

    def test_execute_task_rejects_blocked_pending_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] 기반 결과\n- [general] 후속 결과\n", encoding="utf-8")
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(AgentConfig("manual", ("general",), (), 2),),
            )
            pipeline = Pipeline(config)
            planned = pipeline.start(spec)
            planned.tasks[1].dependencies = [planned.tasks[0].id]
            planned.refresh_task_readiness()
            pipeline.store.save(planned)

            with self.assertRaisesRegex(PipelineError, "blocked by incomplete dependencies"):
                pipeline.execute_task(planned.id, planned.tasks[1].id)

    def test_retry_task_manual_handoff_can_be_completed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] 결과 생성\n", encoding="utf-8")
            script = "import sys; from pathlib import Path; sys.stdin.read(); Path('partial.txt').write_text('partial\\n'); sys.exit(3)"
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(auto_commit=True),
                agents=(AgentConfig("worker", ("general",), (sys.executable, "-c", script), 1),),
            )
            pipeline = Pipeline(config)
            failed = pipeline.execute(pipeline.confirm_plan(pipeline.start(spec).id).id)
            task = failed.tasks[0]

            waiting = pipeline.retry_task(failed.id, task.id, manual=True)

            self.assertEqual(waiting.stage, Stage.EXECUTING)
            self.assertEqual(waiting.tasks[0].status, TaskStatus.WAITING)
            completed = pipeline.complete_task(waiting.id, task.id)
            self.assertEqual(completed.stage, Stage.READY_TO_MERGE)
            self.assertIsNone(completed.tasks[0].failed_action)

    def test_retry_task_resumes_failed_review_without_rerunning_executor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            flag = root / "review-attempted"
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] 결과 생성\n", encoding="utf-8")
            executor_script = "import sys; from pathlib import Path; sys.stdin.read(); Path('result.txt').write_text('done\\n', encoding='utf-8')"
            reviewer_script = (
                "import sys; from pathlib import Path; sys.stdin.read(); "
                f"flag=Path({str(flag)!r}); first=not flag.exists(); "
                "flag.write_text('attempted'); "
                "sys.exit(4) if first else "
                'print(\'AI_REVIEW_RESULT: {"verdict":"approved",\''
                '+\'"summary":"ok","findings":[]}\')'
            )
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(auto_commit=True),
                agents=(
                    AgentConfig("executor", ("general",), (sys.executable, "-c", executor_script), 1, provider_id="local"),
                    AgentConfig("reviewer", ("general",), (sys.executable, "-c", reviewer_script), 1, provider_id="claude"),
                ),
                routing=RoutingConfig(default_provider="local", review_required=True, max_review_cycles=2),
            )
            pipeline = Pipeline(config)
            pipeline._claude_auth_status = Mock(return_value=(True, "claude_subscription", "로그인됨"))

            failed = pipeline.execute(pipeline.confirm_plan(pipeline.start(spec).id).id)
            self.assertEqual(failed.tasks[0].failed_action, TaskAction.REVIEW)
            retried = pipeline.retry_task(failed.id, failed.tasks[0].id)

            task = retried.tasks[0]
            self.assertEqual(retried.stage, Stage.READY_TO_MERGE)
            self.assertEqual(task.status, TaskStatus.COMPLETED)
            self.assertEqual(task.attempt_count, 3)
            self.assertEqual(task.review_status, ReviewStatus.APPROVED)
            self.assertIsNone(task.failed_action)

    def test_retry_task_resumes_failed_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            flag = root / "revision-attempted"
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] 결과 생성\n", encoding="utf-8")
            executor_script = (
                "import sys; from pathlib import Path; prompt=sys.stdin.read(); "
                f"flag=Path({str(flag)!r}); revision='Review revision' in prompt; "
                "first_revision=revision and not flag.exists(); "
                "flag.write_text('attempted') if revision else None; "
                "sys.exit(5) if first_revision else "
                "Path('result.txt').write_text("
                "'revised\\n' if revision else 'initial\\n', encoding='utf-8')"
            )
            reviewer_script = (
                "import sys; from pathlib import Path; sys.stdin.read(); "
                "revised=Path('result.txt').read_text()=='revised\\n'; "
                "print('AI_REVIEW_RESULT: '+("
                '\'{"verdict":"approved","summary":"ok",\''
                "+'\"findings\":[]}' if revised else "
                '\'{"verdict":"changes_requested",\''
                '+\'"summary":"revise",\''
                '+\'"findings":["update result"]}\'))'
            )
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(auto_commit=True),
                agents=(
                    AgentConfig("executor", ("general",), (sys.executable, "-c", executor_script), 1, provider_id="local"),
                    AgentConfig("reviewer", ("general",), (sys.executable, "-c", reviewer_script), 1, provider_id="claude"),
                ),
                routing=RoutingConfig(default_provider="local", review_required=True, max_review_cycles=2),
            )
            pipeline = Pipeline(config)
            pipeline._claude_auth_status = Mock(return_value=(True, "claude_subscription", "fixture connected"))

            failed = pipeline.execute(pipeline.confirm_plan(pipeline.start(spec).id).id)
            task = failed.tasks[0]
            self.assertEqual(task.failed_action, TaskAction.REVISE)
            self.assertEqual(task.review_cycles, 1)

            retried = pipeline.retry_task(failed.id, task.id)

            task = retried.tasks[0]
            self.assertEqual(retried.stage, Stage.READY_TO_MERGE)
            self.assertEqual(task.review_status, ReviewStatus.APPROVED)
            self.assertEqual(task.review_cycles, 2)
            self.assertEqual(task.attempt_count, 5)
            self.assertEqual((Path(task.worktree) / "result.txt").read_text(encoding="utf-8"), "revised\n")

    def test_resume_collects_interrupted_action_and_continues(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] 결과 생성\n", encoding="utf-8")
            script = "import sys; from pathlib import Path; sys.stdin.read(); Path('result.txt').write_text('done\\n', encoding='utf-8')"
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(auto_commit=True),
                agents=(AgentConfig("worker", ("general",), (sys.executable, "-c", script), 1),),
            )
            pipeline = Pipeline(config)
            interrupted = pipeline.execute(pipeline.confirm_plan(pipeline.start(spec).id).id, manual=True)
            task = interrupted.tasks[0]
            task.status = TaskStatus.RUNNING
            task.begin_action(TaskAction.EXECUTE)
            pipeline.store.save(interrupted)

            resumed = pipeline.resume(interrupted.id)

            task = resumed.tasks[0]
            self.assertEqual(resumed.stage, Stage.READY_TO_MERGE)
            self.assertEqual(task.status, TaskStatus.COMPLETED)
            self.assertEqual(task.attempt_count, 2)
            self.assertIsNone(task.active_action)
            self.assertIsNone(task.failed_action)

    def test_resume_restores_safe_non_agent_stages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=root),
                execution=ExecutionConfig(),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
            pipeline = Pipeline(config)
            mappings = (
                (RunStep.VERIFY, Stage.MERGED),
                (RunStep.PUSH, Stage.MERGED),
                (RunStep.DEPLOY, Stage.PUSHED),
            )
            for index, (failed_step, expected_stage) in enumerate(mappings):
                state = RunState(
                    id=f"run-{index}",
                    spec_path="plan.md",
                    spec_digest="abc",
                    repo_path=str(root),
                    main_branch="main",
                    stage=Stage.FAILED,
                    failed_step=failed_step,
                    failure_message="failed",
                )
                pipeline.store.save(state)

                restored = pipeline.resume(state.id)

                self.assertEqual(restored.stage, expected_stage)
                self.assertIsNone(restored.failed_step)
                self.assertEqual(restored.failure_message, "")

            manual = RunState(
                id="manual",
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.FAILED,
                failed_step=RunStep.MANUAL_COMPLETION,
                failure_message="review failed",
                tasks=[
                    WorkTask(id="t01", title="manual", capabilities=["general"], status=TaskStatus.FAILED)
                ],
            )
            pipeline.store.save(manual)
            restored = pipeline.resume(manual.id)
            self.assertEqual(restored.stage, Stage.EXECUTING)
            self.assertEqual(restored.tasks[0].status, TaskStatus.WAITING)

    def test_resume_refuses_partial_merge_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=root),
                execution=ExecutionConfig(),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
            pipeline = Pipeline(config)
            state = RunState(
                id="merge-failed",
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.FAILED,
                failed_step=RunStep.MERGE,
                failure_message="merge failed",
            )
            pipeline.store.save(state)

            with self.assertRaisesRegex(PipelineError, "cannot safely resume"):
                pipeline.resume(state.id)

            self.assertFalse(pipeline.store.lock_path(state.id).exists())

    def test_retry_task_rejects_legacy_failure_without_step(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=root),
                execution=ExecutionConfig(),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
            pipeline = Pipeline(config)
            state = RunState(
                id="legacy-failed",
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.FAILED,
                tasks=[
                    WorkTask(id="t01", title="legacy", capabilities=["general"], status=TaskStatus.FAILED)
                ],
            )
            pipeline.store.save(state)

            with self.assertRaisesRegex(PipelineError, "unknown failure"):
                pipeline.retry_task(state.id, "t01")

    def test_windows_timeout_uses_taskkill_for_process_tree(self) -> None:
        process = Mock()
        process.pid = 4321
        process.poll.side_effect = [None, None]

        with patch("ai_orchestrator.pipeline.os.name", "nt"), patch("ai_orchestrator.pipeline.subprocess.run") as run:
            Pipeline._terminate_agent_process(process)

        command = run.call_args.args[0]
        self.assertEqual(command, ["taskkill", "/PID", "4321", "/T", "/F"])
        self.assertEqual(run.call_args.kwargs["timeout"], AGENT_TERMINATION_TIMEOUT_SECONDS)
        process.kill.assert_called_once_with()

    def test_provider_timeout_does_not_wait_forever_for_output_drain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            process = Mock()
            process.stdin = Mock()
            process.stdout = Mock()
            process.stderr = None
            process.communicate.side_effect = [
                subprocess.TimeoutExpired(cmd=[sys.executable], timeout=1, output="started\n"),
                subprocess.TimeoutExpired(cmd=[sys.executable], timeout=AGENT_OUTPUT_DRAIN_TIMEOUT_SECONDS, output="started\n"),
            ]
            agent = AgentConfig("slow-ai", ("general",), (sys.executable, "-c", "pass"), 1)
            config = Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=root), execution=ExecutionConfig(), agents=(agent,))
            pipeline = Pipeline(config)
            log_path = root / "provider.log"

            with (
                patch("ai_orchestrator.pipeline.subprocess.Popen", return_value=process),
                patch.object(pipeline, "_terminate_agent_process"),
                self.assertRaisesRegex(ProviderTimeoutError, "timed out after 1 seconds"),
            ):
                pipeline._invoke_provider_command(
                    agent=agent,
                    command_template=(sys.executable, "-c", "pass"),
                    replacements={"{run_id}": "run-1", "{task_id}": "task-1"},
                    cwd=root,
                    prompt="prompt",
                    prompt_path=str(root / "prompt.md"),
                    log_path=log_path,
                    action="execute",
                    task_id="task-1",
                    timeout_seconds=1,
                )

            self.assertEqual(process.communicate.call_count, 2)
            process.stdin.close.assert_called_once_with()
            process.stdout.close.assert_called_once_with()
            self.assertIn("timed out after 1 seconds", log_path.read_text(encoding="utf-8"))

    def test_push_and_deploy_require_independent_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=root),
                execution=ExecutionConfig(),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
            pipeline = Pipeline(config)

            with self.assertRaisesRegex(ApprovalRequired, "push requires --approve"):
                pipeline.push("missing", approved=False)
            with self.assertRaisesRegex(ApprovalRequired, "deploy requires --approve"):
                pipeline.deploy("missing", approved=False)

    def test_stale_lock_clear_requires_approval_and_known_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=root),
                execution=ExecutionConfig(),
                agents=(AgentConfig("manual", ("general",), (), 1),),
            )
            pipeline = Pipeline(config)
            state = RunState(id="run-1", spec_path="plan.md", spec_digest="abc", repo_path=str(root), main_branch="main", stage=Stage.PLANNED)
            pipeline.store.save(state)

            with pipeline.store.lock(state.id, "execute"):
                active = pipeline.run_lock_status(state.id)
                self.assertEqual(active.state, RunLockState.ACTIVE)
                with self.assertRaisesRegex(ApprovalRequired, "requires --approve"):
                    pipeline.clear_run_lock(state.id, approved=False)
                with patch.object(StateStore, "_pid_is_alive", return_value=False):
                    cleared = pipeline.clear_run_lock(state.id, approved=True)

            self.assertEqual(cleared.state, RunLockState.UNLOCKED)
            cleared_again = pipeline.clear_run_lock(state.id, approved=True)
            self.assertEqual(cleared_again.state, RunLockState.UNLOCKED)
            with self.assertRaisesRegex(ValueError, "unknown run"):
                pipeline.run_lock_status("missing")

    def test_automatic_cross_provider_review_and_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] 결과 파일 생성\n", encoding="utf-8")
            executor_script = (
                "import sys; from pathlib import Path; "
                "prompt=sys.stdin.read(); "
                "value='revised\\n' if 'Review revision' in prompt else 'initial\\n'; "
                "Path('result.txt').write_text(value, encoding='utf-8'); print('done')"
            )
            reviewer_script = (
                "import sys; from pathlib import Path; sys.stdin.read(); "
                "revised=Path('result.txt').read_text(encoding='utf-8')=='revised\\n'; "
                "print('AI_REVIEW_RESULT: '+"
                '(\'{\'+\'"verdict":"approved","summary":"ok","findings":[]\'+\'}\' '
                "if revised else "
                '\'{\'+\'"verdict":"changes_requested","summary":"revise",\''
                "+'\"findings\":[\"update result\"]'+'}'))"
            )
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(auto_commit=True),
                agents=(
                    AgentConfig("codex-ai", ("general",), (sys.executable, "-c", executor_script), 2, provider_id="local"),
                    AgentConfig("claude-ai", ("general",), (sys.executable, "-c", reviewer_script), 2, provider_id="claude"),
                ),
                routing=RoutingConfig(default_provider="local", review_required=True, max_review_cycles=2),
            )
            pipeline = Pipeline(config)
            pipeline._claude_auth_status = Mock(return_value=(True, "claude_subscription", "fixture connected"))

            state = pipeline.start(spec)
            state = pipeline.confirm_plan(state.id)
            state = pipeline.execute(state.id)

            task = state.tasks[0]
            self.assertEqual(state.stage, Stage.READY_TO_MERGE)
            self.assertEqual(task.status, TaskStatus.COMPLETED)
            self.assertEqual(task.provider_id, "local")
            self.assertEqual(task.reviewer_provider_id, "claude")
            self.assertEqual(task.review_status, ReviewStatus.APPROVED)
            self.assertEqual(task.review_cycles, 2)
            log_dir = pipeline.store.run_dir(state.id) / "logs"
            self.assertTrue((log_dir / f"{task.id}-review-1.log").exists())
            self.assertTrue((log_dir / f"{task.id}-review-1.json").exists())
            self.assertTrue((log_dir / f"{task.id}-revision-1.log").exists())
            self.assertTrue((log_dir / f"{task.id}-review-2.log").exists())
            self.assertEqual((Path(task.worktree) / "result.txt").read_text(encoding="utf-8"), "revised\n")

    def test_reviewer_worktree_change_fails_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] 결과 파일 생성\n", encoding="utf-8")
            executor_script = "import sys; from pathlib import Path; sys.stdin.read(); Path('result.txt').write_text('done\\n', encoding='utf-8')"
            reviewer_script = (
                "import sys; from pathlib import Path; sys.stdin.read(); "
                "Path('review-edit.txt').write_text('bad\\n', encoding='utf-8'); "
                'print(\'AI_REVIEW_RESULT: {"verdict":"approved",\''
                '\'"summary":"ok","findings":[]}\')'
            )
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(auto_commit=True),
                agents=(
                    AgentConfig("codex-ai", ("general",), (sys.executable, "-c", executor_script), 2, provider_id="local"),
                    AgentConfig("claude-ai", ("general",), (sys.executable, "-c", reviewer_script), 2, provider_id="claude"),
                ),
                routing=RoutingConfig(default_provider="local", review_required=True),
            )
            pipeline = Pipeline(config)
            pipeline._claude_auth_status = Mock(return_value=(True, "claude_subscription", "로그인됨"))

            state = pipeline.start(spec)
            state = pipeline.confirm_plan(state.id)
            state = pipeline.execute(state.id)

            self.assertEqual(state.stage, Stage.FAILED)
            self.assertEqual(state.tasks[0].status, TaskStatus.FAILED)
            self.assertEqual(state.tasks[0].review_status, ReviewStatus.FAILED)
            self.assertIn("worktree has uncommitted changes", state.tasks[0].error)

    def test_reviewer_commit_fails_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec = root / "plan.md"
            spec.write_text("## 작업\n\n- [general] 결과 파일 생성\n", encoding="utf-8")
            executor_script = "import sys; from pathlib import Path; sys.stdin.read(); Path('result.txt').write_text('done\\n', encoding='utf-8')"
            reviewer_script = (
                "import subprocess, sys; from pathlib import Path; sys.stdin.read(); "
                "Path('review-commit.txt').write_text('bad\\n', encoding='utf-8'); "
                "subprocess.run(['git','add','review-commit.txt'], check=True); "
                "subprocess.run(['git','commit','-m','bad reviewer commit'], check=True, "
                "stdout=subprocess.PIPE); "
                'print(\'AI_REVIEW_RESULT: {"verdict":"approved",\''
                '\'"summary":"ok","findings":[]}\')'
            )
            config = Config(
                path=root / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(auto_commit=True),
                agents=(
                    AgentConfig("codex-ai", ("general",), (sys.executable, "-c", executor_script), 2, provider_id="local"),
                    AgentConfig("claude-ai", ("general",), (sys.executable, "-c", reviewer_script), 2, provider_id="claude"),
                ),
                routing=RoutingConfig(default_provider="local", review_required=True),
            )
            pipeline = Pipeline(config)
            pipeline._claude_auth_status = Mock(return_value=(True, "claude_subscription", "fixture connected"))

            state = pipeline.start(spec)
            state = pipeline.confirm_plan(state.id)
            state = pipeline.execute(state.id)

            self.assertEqual(state.stage, Stage.FAILED)
            self.assertEqual(state.tasks[0].review_status, ReviewStatus.FAILED)
            self.assertIn("changed HEAD", state.tasks[0].error)

    def test_review_result_protocol_is_required(self) -> None:
        with self.assertRaisesRegex(PipelineError, "exactly one"):
            Pipeline._parse_review("review completed without a verdict")

    def test_docs_only_planning_records_greenfield_gate_without_creating_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline = Pipeline(Config(path=root / "config.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=()))

            state = pipeline.prepare_planning(
                "",
                planning_mode="directed",
                planning_request="새 데스크톱 앱을 계획해 주세요.",
                repository_intent="new_project",
            )

            self.assertEqual(state.repository_maturity.kind.value, "docs_only")  # type: ignore[union-attr]
            self.assertEqual(state.repository_intent, "new_project")
            self.assertEqual(state.greenfield_phase, "stack_decision_required")
            self.assertEqual(state.tasks, [])

    def test_ambiguous_repository_requires_explicit_intent_for_desktop_planning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            (repo / "sample.py").write_text("print('sample')", encoding="utf-8")
            pipeline = Pipeline(Config(path=root / "config.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=()))

            with self.assertRaisesRegex(PipelineError, "repository structure is ambiguous"):
                pipeline.prepare_planning(
                    "",
                    planning_mode="directed",
                    planning_request="기능을 계획해 주세요.",
                    repository_intent="",
                )

    def _greenfield_guidance_run(self, root: Path) -> tuple[Pipeline, RunState]:
        pipeline, state = self._scope_test_run(root)
        state.repository_intent = "new_project"
        state.planning_agent_id = "reviewer"
        state.tasks = []
        state = pipeline._apply_plan(state, Plan("만들 프로그램 확인", False, [], questions=["어떤 프로그램을 만들까요?"]))
        return pipeline, state

    def test_greenfield_goal_questions_save_without_invented_candidates_or_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._greenfield_guidance_run(Path(directory))
            self.assertEqual(state.stage, Stage.NEEDS_CLARIFICATION)
            self.assertEqual(state.greenfield_phase, "questions_required")
            self.assertEqual(state.current_tech_stack_decision().options, [])
            self.assertFalse(state.tech_stack_confirmation_allowed())
            self.assertEqual(state.tasks, [])
            self.assertIsNone(state.bootstrap_spec)

    def test_greenfield_goal_only_ai_result_passes_validation_but_empty_result_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._greenfield_guidance_run(Path(directory))
            payload = {"summary": "제품 목표 확인", "server_work": False, "tasks": [], "questions": ["어떤 프로그램을 만들까요?"]}
            options = dict(source_root=None, source_index=None, required_instruction_paths=set(), execution_agents=(),
                           planning_mode=PlanningMode.DIRECTED, require_directory_task_draft=False, greenfield_bootstrap=True,
                           greenfield_initial=True)
            plan = pipeline._validated_planning_plan("AI_PLAN_RESULT: " + json.dumps(payload, ensure_ascii=False), **options)
            self.assertEqual(plan.tasks, [])
            self.assertEqual(plan.tech_stack_options, [])
            self.assertEqual(plan.questions, payload["questions"])
            payload["questions"] = []
            with self.assertRaises(PlanningError):
                pipeline._validated_planning_plan("AI_PLAN_RESULT: " + json.dumps(payload, ensure_ascii=False), **options)

    def test_greenfield_answer_source_read_failure_is_saved_and_can_retry_the_same_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._greenfield_guidance_run(Path(directory))
            snapshot = Path(state.spec_snapshot_path)
            original = snapshot.read_text(encoding="utf-8")
            snapshot.unlink()
            values = dict(request_id="source-retry", expected_revision=state.plan_revision,
                          conversation_revision=state.planning_conversation_revision, answer_message="개인 메모 앱",
                          expected_tech_stack_revision=state.current_tech_stack_decision().revision)
            with self.assertRaises(OSError):
                pipeline.request_planning_conversation_apply(state.id, **values)
            failed = pipeline.store.load(state.id)
            self.assertIsNone(failed.active_step)
            self.assertEqual(failed.planning_apply_requests[0].status, PlanningApplyStatus.FAILED)
            self.assertEqual(failed.planning_apply_requests[0].answer_message, values["answer_message"])
            snapshot.write_text(original, encoding="utf-8")
            with patch.object(pipeline, "_build_plan", return_value=Plan("추가 조건", False, [], questions=["운영체제는 무엇인가요?"])):
                updated = pipeline.request_planning_conversation_apply(state.id, **values, retry_failed=True)
            self.assertEqual(updated.planning_apply_requests[0].status, PlanningApplyStatus.SUCCEEDED)
            self.assertEqual(sum(message.text == values["answer_message"] for message in updated.planning_messages), 1)

    def test_greenfield_answer_and_recommendation_share_one_saved_request_and_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._greenfield_guidance_run(Path(directory))
            option = TechStackOption("python", "Python", 1, TechStackComponents(languages=["Python"]))
            values = dict(request_id="goal-answer", expected_revision=state.plan_revision,
                          conversation_revision=state.planning_conversation_revision, answer_message="오프라인 메모 앱입니다.",
                          expected_tech_stack_revision=state.current_tech_stack_decision().revision)
            with patch.object(pipeline, "_build_plan", return_value=Plan("추천", False, [], tech_stack_options=[option])) as build:
                updated = pipeline.request_planning_conversation_apply(state.id, **values)
                replayed = pipeline.request_planning_conversation_apply(state.id, **values)
            self.assertEqual(build.call_count, 1)
            self.assertIn(values["answer_message"], build.call_args.kwargs["clarification_context"])
            self.assertEqual(sum(message.text == values["answer_message"] for message in replayed.planning_messages), 1)
            self.assertEqual(updated.current_tech_stack_decision().revision, 2)
            self.assertEqual(updated.greenfield_phase, "options_ready")
            self.assertEqual(len(updated.planning_apply_requests), 1)
            self.assertEqual(updated.planning_apply_requests[0].answer_conversation_revision, updated.planning_conversation_revision)
            self.assertEqual(updated.tasks, [])
            with self.assertRaisesRegex(PipelineError, "다른 기술 추천 요청"):
                pipeline.request_planning_conversation_apply(state.id, **{**values, "answer_message": "다른 목표입니다."})

    def test_greenfield_answer_failure_preserves_answer_and_retries_without_appending_twice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._greenfield_guidance_run(Path(directory))
            values = dict(request_id="goal-answer-retry", expected_revision=state.plan_revision,
                          conversation_revision=state.planning_conversation_revision, answer_message="개인 메모를 저장합니다.",
                          expected_tech_stack_revision=state.current_tech_stack_decision().revision)
            with patch.object(pipeline, "_build_plan", side_effect=PlanningError("추천 생성 실패")):
                with self.assertRaisesRegex(PlanningError, "추천 생성 실패"):
                    pipeline.request_planning_conversation_apply(state.id, **values)
            failed = pipeline.store.load(state.id)
            self.assertEqual(failed.planning_apply_requests[0].answer_message, values["answer_message"])
            self.assertEqual(failed.planning_apply_requests[0].status, PlanningApplyStatus.FAILED)
            self.assertIsNone(failed.active_step)
            with patch.object(pipeline, "_build_plan", return_value=Plan("추가 확인", False, [], questions=["대상 운영체제는 무엇인가요?"])):
                updated = pipeline.request_planning_conversation_apply(state.id, **values, retry_failed=True)
            self.assertEqual(sum(message.text == values["answer_message"] for message in updated.planning_messages), 1)
            self.assertEqual(len(updated.planning_apply_requests), 1)
            self.assertEqual(updated.planning_apply_requests[0].status, PlanningApplyStatus.SUCCEEDED)
            self.assertEqual(updated.planning_questions, ["대상 운영체제는 무엇인가요?"])

    def test_greenfield_answer_rejects_stale_candidate_plan_or_discussion_without_saving(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._greenfield_guidance_run(Path(directory))
            values = dict(request_id="goal-stale", expected_revision=state.plan_revision,
                          conversation_revision=state.planning_conversation_revision, answer_message="메모 앱입니다.",
                          expected_tech_stack_revision=state.current_tech_stack_decision().revision)
            for changes in [{"expected_tech_stack_revision": 0}, {"expected_revision": 0}, {"conversation_revision": 99}]:
                with self.subTest(changes=changes), self.assertRaises(PipelineError):
                    pipeline.request_planning_conversation_apply(state.id, **{**values, **changes})
            saved = pipeline.store.load(state.id)
            self.assertEqual(saved.planning_apply_requests, [])
            self.assertFalse(any(message.text == values["answer_message"] for message in saved.planning_messages))

    def test_greenfield_saved_answer_retry_does_not_override_a_later_discussion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._greenfield_guidance_run(Path(directory))
            values = dict(request_id="goal-changed", expected_revision=state.plan_revision,
                          conversation_revision=state.planning_conversation_revision, answer_message="메모 앱입니다.",
                          expected_tech_stack_revision=state.current_tech_stack_decision().revision)
            with patch.object(pipeline, "_build_plan", side_effect=PlanningError("실패")), self.assertRaises(PlanningError):
                pipeline.request_planning_conversation_apply(state.id, **values)
            failed = pipeline.store.load(state.id)
            pipeline._append_planning_user_message(failed, "동기화도 필요합니다.")
            pipeline.store.save(failed)
            with self.assertRaisesRegex(PipelineError, "답변이나 계획이 변경"):
                pipeline.request_planning_conversation_apply(state.id, **values, retry_failed=True)

    def test_greenfield_bootstrap_plan_failure_preserves_the_confirmed_choice_for_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._greenfield_guidance_run(Path(directory))
            option = TechStackOption("python", "Python", 1, TechStackComponents(languages=["Python"]))
            state = pipeline._apply_plan(state, Plan("추천", False, [], tech_stack_options=[option]))
            state = pipeline.confirm_tech_stack(state.id, option_id="python", expected_revision=2)
            values = dict(request_id="bootstrap-plan", expected_revision=state.plan_revision,
                          conversation_revision=state.planning_conversation_revision, expected_tech_stack_revision=2)
            with patch.object(pipeline, "_build_plan", return_value=Plan("잘못된 재추천", False, [], tech_stack_options=[option])):
                with self.assertRaisesRegex(PipelineError, "구성 결정은 보존"):
                    pipeline.request_planning_conversation_apply(state.id, **values)
            failed = pipeline.store.load(state.id)
            self.assertEqual(failed.current_tech_stack_decision().selected_option_id, "python")
            self.assertEqual(failed.current_tech_stack_decision().status, TechStackDecisionStatus.CONFIRMED)
            task = WorkTask(id="project-bootstrap", title="기본 구조", description="실행 가능한 구조를 준비합니다.",
                            capabilities=["general"], expected_paths=["pyproject.toml", "src/main.py"],
                            acceptance_criteria=["실행과 테스트 성공"], verify_commands=[[sys.executable, "-m", "unittest"]], agent_id="worker")
            with patch.object(pipeline, "_build_plan", return_value=Plan("기본 구조", False, [task])):
                updated = pipeline.request_planning_conversation_apply(state.id, **values, retry_failed=True)
            self.assertEqual(updated.greenfield_phase, "bootstrap_ready")
            self.assertEqual(updated.bootstrap_spec.decision_revision, 2)
            self.assertEqual(updated.planning_apply_requests[0].status, PlanningApplyStatus.SUCCEEDED)
            self.assertFalse((pipeline.repo / "pyproject.toml").exists())
            with self.assertRaisesRegex(PipelineError, "검토한 계획이 변경"):
                pipeline.confirm_plan(state.id, expected_revision=updated.plan_revision - 1)
            with self.assertRaisesRegex(PipelineError, "기본 구조 범위가 변경"):
                pipeline.confirm_plan(state.id, expected_revision=updated.plan_revision, expected_bootstrap_digest="stale")

    def test_greenfield_choice_questions_allow_direct_confirmation_without_new_run_or_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline = Pipeline(Config(path=root / "config.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=()))
            state = pipeline.prepare_planning("", planning_mode="directed", planning_request="최소 콘솔 프로젝트", repository_intent="new_project")
            option = TechStackOption("ts", "TypeScript와 Node.js 최소 콘솔 프로젝트", 1,
                                     TechStackComponents(languages=["TypeScript"], runtimes=["Node.js LTS"]))
            question = "빈 프로젝트의 설치·빌드·테스트를 검증할 기술 구성으로 추천한 TypeScript와 Node.js를 선택할까요?"
            state = pipeline._apply_plan(state, Plan("기술 후보", False, [], questions=[question], tech_stack_options=[option]))
            with self.assertRaisesRegex(PipelineError, "현재 revision 1"):
                pipeline.confirm_tech_stack(state.id, option_id="ts", expected_revision=0)
            with self.assertRaisesRegex(PipelineError, "unknown technology stack option"):
                pipeline.confirm_tech_stack(state.id, option_id="other", expected_revision=1)
            confirmed = pipeline.confirm_tech_stack(state.id, option_id="ts", expected_revision=1)
            self.assertEqual(confirmed.id, state.id)
            self.assertEqual(confirmed.greenfield_phase, "stack_confirmed")
            self.assertEqual(confirmed.planning_questions, [])
            self.assertEqual(confirmed.current_tech_stack_decision().status, TechStackDecisionStatus.CONFIRMED)
            self.assertIn("ts", confirmed.current_tech_stack_decision().answers[-1])
            self.assertEqual(confirmed.tasks, [])
            self.assertEqual(len(pipeline.store.list_runs()), 1)
            self.assertFalse((repo / "package.json").exists())
            retried = pipeline.confirm_tech_stack(state.id, option_id="ts", expected_revision=1)
            self.assertEqual(len(retried.planning_messages), len(confirmed.planning_messages))

    def test_greenfield_questions_block_confirmation_until_candidates_are_refreshed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline = Pipeline(Config(path=root / "config.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=()))
            state = pipeline.prepare_planning(
                "", planning_mode="directed", planning_request="로컬 앱을 계획해 주세요.", repository_intent="new_project",
            )
            option = TechStackOption(
                option_id="python", label="Python", recommendation_rank=1,
                components=TechStackComponents(languages=["Python"]), version_policy=["지원 버전"],
                requirement_fit=["로컬 실행"], tradeoffs=["패키징 필요"],
            )
            plan = Plan("기술 후보", False, [], questions=["실행할 운영체제는 무엇인가요?"], tech_stack_options=[option])
            state = pipeline._apply_plan(state, plan)
            with self.assertRaisesRegex(PipelineError, "질문에 먼저 답해"):
                pipeline.confirm_tech_stack(state.id, option_id="python", expected_revision=1)
            saved = pipeline.store.load(state.id)
            self.assertEqual(saved.greenfield_phase, "questions_required")
            self.assertEqual(saved.current_tech_stack_decision().status, TechStackDecisionStatus.QUESTIONS_REQUIRED)
            self.assertEqual(saved.tasks, [])

            refreshed = pipeline._apply_plan(saved, Plan("답변을 반영한 기술 후보", False, [], tech_stack_options=[option]))
            self.assertEqual(refreshed.current_tech_stack_decision().revision, 2)
            with self.assertRaisesRegex(PipelineError, "현재 revision 2"):
                pipeline.confirm_tech_stack(state.id, option_id="python", expected_revision=1)
            confirmed = pipeline.confirm_tech_stack(state.id, option_id="python", expected_revision=2)
            self.assertEqual(confirmed.greenfield_phase, "stack_confirmed")
            self.assertEqual(confirmed.current_tech_stack_decision().status, TechStackDecisionStatus.CONFIRMED)
            self.assertEqual(confirmed.tasks, [])

    def test_sdk_greenfield_answer_refreshes_candidates_before_explicit_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            planner = AgentConfig("planner", ("planning", "general"), (), 2, provider_id="codex", review_command=())
            config = Config(
                path=root / "orchestrator.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(),
                agents=(planner,), planning=PlanningConfig(agent_id="planner", max_attempts=2),
            )
            payload = {
                "summary": "로컬 앱 기술 후보", "server_work": False, "tasks": [], "questions": ["실행할 운영체제는 무엇인가요?"],
                "source_paths": [], "instruction_paths": [],
                "tech_stack_options": [{
                    "option_id": "python", "label": "Python", "recommendation_rank": 1,
                    "components": {"languages": ["Python"]}, "version_policy": ["지원 버전"],
                    "requirement_fit": ["로컬 실행"], "tradeoffs": ["패키징 필요"],
                    "unresolved_constraints": [], "required_external_dependencies": [],
                }],
            }
            first_output = "AI_PLAN_RESULT: " + json.dumps(payload, ensure_ascii=False)
            payload["questions"] = []
            sdk = connected_codex_sdk()
            sdk.run_turn.side_effect = [first_output, "Windows용 후보를 갱신해 주세요.", "AI_PLAN_RESULT: " + json.dumps(payload, ensure_ascii=False)]
            pipeline = Pipeline(config, codex_sdk=sdk)
            prepared = pipeline.prepare_planning(
                "", planning_mode="directed", planning_request="로컬 앱을 계획해 주세요.", repository_intent="new_project",
            )
            waiting = pipeline.run_planning(prepared.id)
            self.assertEqual(waiting.greenfield_phase, "questions_required")
            with self.assertRaisesRegex(PipelineError, "질문에 먼저 답해"):
                pipeline.confirm_tech_stack(waiting.id, option_id="python", expected_revision=1)
            chatted = pipeline.send_planning_message(waiting.id, "Windows에서 실행합니다.")
            self.assertEqual(chatted.current_tech_stack_decision().revision, 1)
            compact_prompt = pipeline._planning_materialization_prompt(chatted)
            self.assertIn("Technology candidate refresh", compact_prompt)
            self.assertIn("return questions: []", compact_prompt)
            self.assertIn("Windows에서 실행합니다.", compact_prompt)
            refreshed = pipeline.apply_planning_conversation(waiting.id)
            self.assertEqual(refreshed.greenfield_phase, "options_ready")
            self.assertEqual(refreshed.planning_questions, [])
            self.assertEqual(refreshed.current_tech_stack_decision().revision, 2)
            self.assertEqual(refreshed.tasks, [])
            requests = [item.args[0] for item in sdk.run_turn.call_args_list]
            self.assertEqual(len(requests), 3)
            self.assertEqual(requests[1].conversation_id, requests[2].conversation_id)
            self.assertIn("explicit user selection UI", requests[2].prompt)
            self.assertIn("questions: []", requests[2].prompt)
            self.assertIn("Windows에서 실행합니다.", requests[2].prompt)
            confirmed = pipeline.confirm_tech_stack(waiting.id, option_id="python", expected_revision=2)
            self.assertEqual(confirmed.greenfield_phase, "stack_confirmed")
            self.assertEqual(confirmed.tasks, [])
            self.assertNotIn("Technology candidate refresh", pipeline._planning_materialization_prompt(confirmed))

    def test_greenfield_stack_confirmation_checks_revision_and_does_not_create_project_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            pipeline = Pipeline(Config(path=root / "config.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=()))
            state = pipeline.prepare_planning(
                "",
                planning_mode="directed",
                planning_request="새 데스크톱 앱을 계획해 주세요.",
                repository_intent="new_project",
            )
            before = subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True)
            plan = Plan(
                "기술 구성 후보",
                False,
                [],
                tech_stack_options=[
                    TechStackOption(
                        option_id="electron-typescript",
                        label="Electron + TypeScript",
                        recommendation_rank=1,
                        components=TechStackComponents(languages=["TypeScript"], application_frameworks=["Electron"]),
                        version_policy=["Node.js LTS 범위"],
                        requirement_fit=["Windows 데스크톱 앱"],
                        tradeoffs=["번들 크기"],
                    )
                ],
            )
            state = pipeline._apply_plan(state, plan)

            self.assertEqual(state.greenfield_phase, "options_ready")
            self.assertEqual(state.tech_stack_decisions[-1].revision, 1)
            with self.assertRaisesRegex(PipelineError, "현재 revision 1"):
                pipeline.confirm_tech_stack(state.id, option_id="electron-typescript", expected_revision=0)

            confirmed = pipeline.confirm_tech_stack(state.id, option_id="electron-typescript", expected_revision=1)

            self.assertEqual(confirmed.greenfield_phase, "stack_confirmed")
            self.assertEqual(confirmed.tech_stack_decisions[-1].status, TechStackDecisionStatus.CONFIRMED)
            self.assertEqual(confirmed.tech_stack_decisions[-1].selected_option_id, "electron-typescript")
            self.assertEqual(confirmed.tasks, [])
            self.assertGreater(confirmed.planning_conversation_revision, state.planning_conversation_revision)
            revised = pipeline._apply_plan(
                confirmed,
                Plan(
                    "수정된 기술 구성 후보",
                    False,
                    [],
                    tech_stack_options=[
                        TechStackOption(
                            option_id="dotnet-wpf",
                            label=".NET + WPF",
                            recommendation_rank=1,
                            components=TechStackComponents(languages=["C#"], application_frameworks=["WPF"]),
                            version_policy=["지원 중인 .NET LTS"],
                            requirement_fit=["Windows 네이티브 데스크톱 앱"],
                            tradeoffs=["Windows 전용"],
                        )
                    ],
                ),
            )
            self.assertEqual([decision.revision for decision in revised.tech_stack_decisions], [1, 2])
            self.assertEqual(revised.tech_stack_decisions[0].status, TechStackDecisionStatus.SUPERSEDED)
            self.assertEqual(subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True), before)

    def test_bootstrap_spec_preview_and_stale_path_block_execution_before_workspace_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            worker = AgentConfig("worker", ("general",), (sys.executable, "-c", "pass"), 1, provider_id="local")
            pipeline = Pipeline(
                Config(path=root / "config.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=(worker,))
            )
            state = pipeline.prepare_planning(
                "",
                planning_mode="directed",
                planning_request="새 데스크톱 앱을 계획해 주세요.",
                repository_intent="new_project",
            )
            state = pipeline._apply_plan(
                state,
                Plan(
                    "기술 구성 후보",
                    False,
                    [],
                    tech_stack_options=[
                        TechStackOption(
                            option_id="electron-typescript",
                            label="Electron + TypeScript",
                            recommendation_rank=1,
                            components=TechStackComponents(
                                languages=["TypeScript"],
                                runtimes=["Node.js LTS"],
                                package_and_build_tools=["npm"],
                                test_tools=["Node test runner"],
                            ),
                        )
                    ],
                ),
            )
            state = pipeline.confirm_tech_stack(state.id, option_id="electron-typescript", expected_revision=1)
            state = pipeline._apply_plan(
                state,
                Plan(
                    "기본 구조 생성",
                    False,
                    [
                        WorkTask(
                            id="project-bootstrap",
                            title="최소 실행 기반 생성",
                            description="앱의 최소 실행 기반을 만든다.",
                            agent_id="worker", provider_id="local",
                            capabilities=["general"],
                            acceptance_criteria=["개발 실행 명령이 시작된다.", "baseline 검증이 통과한다."],
                            expected_paths=["package.json", "src/**"],
                            verify_commands=[["npm", "test"]],
                        )
                    ],
                ),
            )

            spec = pipeline.preview_bootstrap(state.id)

            self.assertEqual(spec.decision_revision, 1)
            self.assertEqual(spec.planned_paths, ["package.json", "src/**", "AGENTS.md"])
            self.assertEqual(spec.required_tools, ["TypeScript", "Node.js LTS", "npm", "Node test runner"])
            self.assertEqual(spec.verify_commands, [["npm", "test"]])
            self.assertEqual(spec.path_snapshot, [])
            self.assertIsNotNone(spec.agent_instructions)
            self.assertEqual(spec.agent_instructions.mode, "create_from_template")  # type: ignore[union-attr]
            self.assertIn("Electron + TypeScript", spec.agent_instructions.rendered_content)  # type: ignore[union-attr]
            self.assertIn("AGENTS.md", state.tasks[0].expected_paths)
            prompt = pipeline._prompt(state, state.tasks[0], "계획")
            self.assertIn("Create `AGENTS.md` with exactly", prompt)
            self.assertIn(spec.agent_instructions.rendered_content.rstrip(), prompt)  # type: ignore[union-attr]
            self.assertEqual(len(spec.digest), 64)
            pipeline._verify_bootstrap_spec_current(state)

            with self.assertRaisesRegex(PipelineError, "기술 구성 결정이 변경"):
                pipeline.configure_bootstrap_agent_instructions(
                    state.id,
                    create=False,
                    expected_revision=0,
                    expected_digest=spec.digest,
                )
            with self.assertRaisesRegex(PipelineError, "초기화 계획이 변경"):
                pipeline.configure_bootstrap_agent_instructions(
                    state.id,
                    create=False,
                    expected_revision=1,
                    expected_digest="stale-digest",
                )

            state = pipeline.configure_bootstrap_agent_instructions(
                state.id,
                create=False,
                expected_revision=1,
                expected_digest=spec.digest,
            )
            skipped_spec = state.bootstrap_spec
            self.assertIsNotNone(skipped_spec)
            self.assertEqual(skipped_spec.agent_instructions.mode, "skip_by_user")  # type: ignore[union-attr]
            self.assertNotIn("AGENTS.md", skipped_spec.planned_paths)  # type: ignore[union-attr]
            self.assertNotIn("AGENTS.md", state.tasks[0].expected_paths)
            self.assertNotIn(BOOTSTRAP_AGENTS_ACCEPTANCE, state.tasks[0].acceptance_criteria)
            self.assertIn("excluded by user", pipeline._prompt(state, state.tasks[0], "계획"))
            stored_plan = json.loads(Path(state.structured_plan_path).read_text(encoding="utf-8"))
            self.assertNotIn("AGENTS.md", stored_plan["tasks"][0]["expected_paths"])

            state = pipeline.configure_bootstrap_agent_instructions(
                state.id,
                create=True,
                expected_revision=1,
                expected_digest=skipped_spec.digest,  # type: ignore[union-attr]
            )
            spec = state.bootstrap_spec
            self.assertIsNotNone(spec)
            self.assertEqual(spec.agent_instructions.mode, "create_from_template")  # type: ignore[union-attr]
            self.assertIn("AGENTS.md", state.tasks[0].expected_paths)
            self.assertIn(BOOTSTRAP_AGENTS_ACCEPTANCE, state.tasks[0].acceptance_criteria)
            stored_plan = json.loads(Path(state.structured_plan_path).read_text(encoding="utf-8"))
            self.assertIn("AGENTS.md", stored_plan["tasks"][0]["expected_paths"])

            state = pipeline.confirm_plan(state.id)
            (repo / "package.json").write_text('{"name":"occupied"}\n', encoding="utf-8")

            with self.assertRaisesRegex(PipelineError, "package.json"):
                pipeline.execute(state.id)

            persisted = pipeline.status(state.id)
            self.assertEqual(persisted.stage, Stage.PLANNED)
            self.assertEqual(persisted.greenfield_phase, "bootstrap_ready")
            self.assertFalse((repo / ".ai_auto_work").exists())

    def test_bootstrap_spec_preserves_existing_agents_and_detects_later_edit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            (repo / "AGENTS.md").write_text("# Existing instructions\n", encoding="utf-8")
            pipeline = Pipeline(Config(path=root / "config.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=()))
            state = pipeline.prepare_planning(
                "",
                planning_mode="directed",
                planning_request="새 도구를 계획해 주세요.",
                repository_intent="new_project",
            )
            state = pipeline._apply_plan(
                state,
                Plan(
                    "기술 구성 후보",
                    False,
                    [],
                    tech_stack_options=[
                        TechStackOption(
                            option_id="python",
                            label="Python",
                            recommendation_rank=1,
                            components=TechStackComponents(languages=["Python"]),
                        )
                    ],
                ),
            )
            state = pipeline.confirm_tech_stack(state.id, option_id="python", expected_revision=1)
            state = pipeline._apply_plan(
                state,
                Plan(
                    "기본 구조 생성",
                    False,
                    [WorkTask(id="project-bootstrap", title="초기화", capabilities=["general"], expected_paths=["src/**"])],
                ),
            )

            spec = pipeline.preview_bootstrap(state.id)

            self.assertIsNotNone(spec.agent_instructions)
            self.assertEqual(spec.agent_instructions.mode, "preserve_existing")  # type: ignore[union-attr]
            self.assertNotIn("AGENTS.md", spec.planned_paths)
            self.assertEqual([item.relative_path for item in spec.path_snapshot], ["AGENTS.md"])
            self.assertIn("Preserve `AGENTS.md` exactly", pipeline._prompt(state, state.tasks[0], "계획"))
            with self.assertRaisesRegex(PipelineError, "기존 AGENTS.md"):
                pipeline.configure_bootstrap_agent_instructions(
                    state.id,
                    create=False,
                    expected_revision=1,
                    expected_digest=spec.digest,
                )
            (repo / "AGENTS.md").write_text("# Edited instructions\n", encoding="utf-8")
            with self.assertRaisesRegex(PipelineError, "AGENTS.md"):
                pipeline._verify_bootstrap_spec_current(state)

    def test_greenfield_plan_accepts_only_questions_then_one_bootstrap_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            worker = AgentConfig("worker", ("general",), (), 1, provider_id="local")
            pipeline = Pipeline(
                Config(path=root / "config.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=(worker,))
            )
            questions = (
                'AI_PLAN_RESULT: {"summary":"기술 구성 선택","server_work":false,'
                '"source_paths":[],"instruction_paths":[],"tasks":[],'
                '"questions":["배포 대상 Windows 버전을 알려 주세요."],'
                '"tech_stack_options":[{"option_id":"electron-typescript","label":"Electron + TypeScript",'
                '"recommendation_rank":1,"components":{"languages":["TypeScript"],"runtimes":["Node.js LTS"],'
                '"application_frameworks":["Electron"],"ui_frameworks":["React"],"persistence":[],'
                '"package_and_build_tools":["npm"],"test_tools":["Node test runner"],'
                '"style_and_analysis":["TypeScript strict"],"packaging_and_deployment":["Windows installer"]},'
                '"version_policy":["LTS 범위"],"requirement_fit":["Windows 데스크톱 앱"],'
                '"tradeoffs":["번들 크기"],"unresolved_constraints":["Windows 버전"],'
                '"required_external_dependencies":[]}]}'
            )
            plan = pipeline._validated_planning_plan(
                questions,
                source_root=None,
                source_index=None,
                required_instruction_paths=set(),
                execution_agents=(worker,),
                planning_mode=PlanningMode.DIRECTED,
                require_directory_task_draft=False,
                greenfield_bootstrap=True,
                greenfield_initial=True,
            )
            self.assertEqual(plan.tasks, [])
            self.assertEqual(plan.tech_stack_options[0].option_id, "electron-typescript")
            feature = (
                'AI_PLAN_RESULT: {"summary":"기능 구현","server_work":false,'
                '"source_paths":[],"instruction_paths":[],"questions":[],"tasks":['
                '{"id":"feature","title":"제품 기능 구현","description":"기능을 만든다.",'
                '"capabilities":["general"],"depends_on":[],"acceptance_criteria":["기능이 동작한다."],'
                '"expected_paths":["src/**"],"forbidden_paths":[],"verify_commands":[["python","-m","compileall","src"]],'
                '"risk_level":"low","provider_id":"local","model":"","reasoning_effort":""}]}'
            )
            with self.assertRaisesRegex(PlanningError, "exactly one project-bootstrap"):
                pipeline._validated_planning_plan(
                    feature,
                    source_root=None,
                    source_index=None,
                    required_instruction_paths=set(),
                    execution_agents=(worker,),
                    planning_mode=PlanningMode.DIRECTED,
                    require_directory_task_draft=False,
                    greenfield_bootstrap=True,
                    greenfield_initial=False,
                )
            feature_plan = pipeline._validated_planning_plan(
                feature,
                source_root=None,
                source_index=None,
                required_instruction_paths=set(),
                execution_agents=(worker,),
                planning_mode=PlanningMode.DIRECTED,
                require_directory_task_draft=False,
                greenfield_feature=True,
            )
            self.assertEqual([task.id for task in feature_plan.tasks], ["feature"])

    def test_verified_bootstrap_generates_feature_plan_and_preserves_completed_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec_path = root / "plan.md"
            spec_path.write_text("제품 기능 요구사항", encoding="utf-8")
            worker = AgentConfig(
                "worker",
                ("general",),
                (sys.executable, "-c", "import sys; sys.stdin.read()"),
                1,
                provider_id="local",
            )
            pipeline = Pipeline(
                Config(path=root / "config.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=(worker,))
            )
            bootstrap = WorkTask(
                id="project-bootstrap",
                title="기본 구조",
                description="기본 구조를 만든다.",
                capabilities=["general"],
                acceptance_criteria=["실행된다."],
                expected_paths=["package.json"],
                verify_commands=[["npm", "test"]],
                status=TaskStatus.COMPLETED,
                completed_commit="b" * 40,
            )
            state = RunState(
                id="feature-plan",
                spec_path=str(spec_path),
                spec_snapshot_path=str(spec_path),
                spec_digest="digest",
                repo_path=str(repo),
                main_branch="main",
                stage=Stage.VERIFIED,
                repository_intent="new_project",
                greenfield_phase="feature_planning_ready",
                tech_stack_decisions=[
                    TechStackDecision(
                        decision_id="decision",
                        revision=1,
                        status=TechStackDecisionStatus.CONFIRMED,
                        project_root=str(repo),
                        requirement_sources=[],
                        answers=[],
                        options=[TechStackOption("typescript", "TypeScript", 1, TechStackComponents(languages=["TypeScript"]))],
                        selected_option_id="typescript",
                    )
                ],
                bootstrap_spec=BootstrapSpec(
                    decision_id="decision",
                    decision_revision=1,
                    target_root=str(repo),
                    planned_paths=["package.json"],
                    steps=["기본 구조"],
                    required_tools=["TypeScript"],
                    verify_commands=[["npm", "test"]],
                    excluded_external_actions=["deployment"],
                    path_snapshot=[],
                    digest="bootstrap-digest",
                    verified_integration_head="c" * 40,
                    verified_at="2026-09-16T00:00:00+00:00",
                ),
                tasks=[bootstrap],
            )
            pipeline.store.save(state)
            feature_plan = Plan(
                "첫 기능 계획",
                False,
                [
                    WorkTask(
                        id="first-feature",
                        title="첫 기능",
                        description="첫 기능을 구현한다.",
                        capabilities=["general"],
                        acceptance_criteria=["기능이 동작한다."],
                        expected_paths=["src/**"],
                        verify_commands=[["npm", "test"]],
                        agent_id="worker",
                        provider_id="local",
                    )
                ],
            )

            with patch.object(pipeline, "_build_plan", return_value=feature_plan) as build_plan:
                generated = pipeline.generate_feature_plan(state.id)

            self.assertEqual(generated.stage, Stage.PLANNED)
            self.assertEqual(generated.greenfield_phase, "feature_plan_ready")
            self.assertEqual(generated.plan_revision, 1)
            self.assertEqual(generated.tasks[0].status, TaskStatus.COMPLETED)
            self.assertEqual(generated.tasks[0].completed_commit, "b" * 40)
            self.assertEqual(generated.tasks[1].dependencies, ["project-bootstrap"])
            self.assertEqual(generated.tasks[1].readiness, TaskReadiness.READY)
            self.assertEqual(generated.bootstrap_spec.feature_plan_attempts, 1)  # type: ignore[union-attr]
            self.assertIn('"verified_integration_head": "' + "c" * 40, build_plan.call_args.kwargs["clarification_context"])

            changed_drafts = [pipeline._task_plan_draft(task) for task in generated.tasks]
            changed_drafts[0]["title"] = "변경하면 안 되는 기본 구조"
            with self.assertRaisesRegex(PipelineError, "project-bootstrap Task는 수정할 수 없습니다"):
                pipeline.update_plan(state.id, changed_drafts)

            confirmed = pipeline.confirm_plan(state.id)
            self.assertTrue(confirmed.plan_is_approved)
            self.assertEqual(confirmed.tasks[0].status, TaskStatus.COMPLETED)

    def test_feature_plan_failure_preserves_verified_bootstrap_for_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            spec_path = root / "plan.md"
            spec_path.write_text("제품 기능 요구사항", encoding="utf-8")
            pipeline = Pipeline(Config(path=root / "config.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=()))
            state = RunState(
                id="feature-plan-failure",
                spec_path=str(spec_path),
                spec_snapshot_path=str(spec_path),
                spec_digest="digest",
                repo_path=str(repo),
                main_branch="main",
                stage=Stage.VERIFIED,
                repository_intent="new_project",
                greenfield_phase="feature_planning_ready",
                tech_stack_decisions=[
                    TechStackDecision(
                        decision_id="decision",
                        revision=1,
                        status=TechStackDecisionStatus.CONFIRMED,
                        project_root=str(repo),
                        requirement_sources=[],
                        answers=[],
                        options=[TechStackOption("python", "Python", 1, TechStackComponents(languages=["Python"]))],
                        selected_option_id="python",
                    )
                ],
                bootstrap_spec=BootstrapSpec(
                    decision_id="decision",
                    decision_revision=1,
                    target_root=str(repo),
                    planned_paths=["pyproject.toml"],
                    steps=["기본 구조"],
                    required_tools=["Python"],
                    verify_commands=[["python", "-m", "pytest"]],
                    excluded_external_actions=[],
                    path_snapshot=[],
                    digest="bootstrap-digest",
                    verified_integration_head="d" * 40,
                    verified_at="2026-09-16T00:00:00+00:00",
                ),
                tasks=[WorkTask("project-bootstrap", "기본 구조", ["general"], status=TaskStatus.COMPLETED)],
            )
            pipeline.store.save(state)

            with patch.object(pipeline, "_build_plan", side_effect=PlanningError("provider unavailable")):
                with self.assertRaisesRegex(PlanningError, "provider unavailable"):
                    pipeline.generate_feature_plan(state.id)

            persisted = pipeline.status(state.id)
            self.assertEqual(persisted.stage, Stage.VERIFIED)
            self.assertEqual(persisted.greenfield_phase, "feature_planning_ready")
            self.assertEqual(persisted.tasks[0].status, TaskStatus.COMPLETED)
            self.assertEqual(persisted.bootstrap_spec.feature_plan_attempts, 1)  # type: ignore[union-attr]
            self.assertEqual(persisted.bootstrap_spec.feature_plan_error, "provider unavailable")  # type: ignore[union-attr]

    def test_run_fixes_code_style_snapshot_for_worker_and_reviewer_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            (repo / "main.py").write_text("pass\n", encoding="utf-8")
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml",
                    project=ProjectConfig(repo=repo),
                    execution=ExecutionConfig(),
                    agents=(),
                ),
                code_style_preference=ProjectCodeStylePreference(),
                code_style_preference_revision=7,
            )

            state = pipeline.prepare_planning(
                "",
                planning_mode=PlanningMode.DIRECTED,
                planning_request="Python 파일을 수정해 주세요.",
            )
            task = WorkTask(
                "style-task",
                "스타일 적용",
                ["general"],
                description="스타일 snapshot을 적용한다.",
                acceptance_criteria=["고정 규칙을 따른다."],
                expected_paths=["main.py"],
                verify_commands=[["python", "-m", "ruff", "check", "."]],
            )
            state.tasks.append(task)

            assert state.code_style_snapshot is not None
            self.assertEqual(state.code_style_snapshot.preference_revision, 7)
            self.assertEqual(state.code_style_snapshot.rules[0].standard_id, "pep8")
            (repo / "AGENTS.md").write_text("Python 코드 스타일 규칙을 따릅니다.\n", encoding="utf-8")
            task.action_results.append(
                TaskActionResult(
                    action="execute",
                    changed_paths=["main.py"],
                    code_style_evidence=inspect_task_code_style(repo, state.code_style_snapshot, ["main.py"]),
                )
            )
            worker_prompt = pipeline._prompt(state, task, "spec")
            reviewer_prompt = pipeline._review_prompt(state, task, 1)
            self.assertIn("Fixed project code style snapshot", worker_prompt)
            self.assertIn("pep8", worker_prompt)
            self.assertIn("pep8", reviewer_prompt)
            self.assertIn("Actual changed-path code style evidence", reviewer_prompt)
            self.assertIn("added: AGENTS.md", reviewer_prompt)
            restored = RunState.from_dict(state.to_dict())
            restored_evidence = restored.tasks[0].action_results[0].code_style_evidence
            self.assertIsNotNone(restored_evidence)
            self.assertEqual(restored_evidence.rule_changes, ("added: AGENTS.md",))  # type: ignore[union-attr]

    def test_task_verification_persists_failed_code_style_check_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._repository(root)
            (repo / "main.py").write_text("pass\n", encoding="utf-8")
            (repo / "ruff.toml").write_text("line-length = 100\n", encoding="utf-8")
            git(repo, "add", ".")
            git(repo, "commit", "-m", "style config")
            pipeline = Pipeline(
                Config(path=root / "orchestrator.toml", project=ProjectConfig(repo=repo), execution=ExecutionConfig(), agents=())
            )
            command = ["python", "-m", "ruff", "check", "."]
            task = WorkTask(
                id="style-check",
                title="스타일 검사",
                capabilities=["general"],
                worktree=str(repo),
                started_commit=pipeline.git.head(repo),
                verify_commands=[command],
                action_results=[TaskActionResult(action="verify", changed_paths=["main.py"])],
            )
            state = RunState(
                id="style-check-run",
                spec_path="",
                spec_digest="digest",
                repo_path=str(repo),
                main_branch="main",
                stage=Stage.EXECUTING,
                tasks=[task],
                code_style_snapshot=CodeStyleSnapshot.from_profile(inspect_project_code_style(repo)),
            )
            pipeline.store.save(state)
            (pipeline.store.run_dir(state.id) / "logs").mkdir(parents=True, exist_ok=True)

            with patch("ai_orchestrator.pipeline.run_command", return_value=Mock(returncode=7, stdout="lint failed")):
                with self.assertRaisesRegex(PipelineError, "task verification command failed"):
                    pipeline._perform_task_verification(state, task)

            evidence = task.action_results[-1].code_style_evidence
            self.assertIsNotNone(evidence)
            self.assertEqual(evidence.checks[0].last_result, "failed")  # type: ignore[union-attr]

    @staticmethod
    def _repository(root: Path) -> Path:
        repo = root / "repo"
        repo.mkdir()
        git(repo, "init", "-b", "main")
        git(repo, "config", "user.email", "test@example.com")
        git(repo, "config", "user.name", "Test")
        (repo / ".gitignore").write_text(".ai-orchestrator/\n", encoding="utf-8")
        (repo / "README.md").write_text("initial\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "-m", "initial")
        return repo

    @staticmethod
    def _counting_planning_pipeline(root: Path, repo: Path) -> tuple[Pipeline, Path]:
        counter = root / "planning-invocations.txt"
        planner_script = (
            "import json, sys; from pathlib import Path; sys.stdin.read(); "
            f"counter=Path({str(counter)!r}); "
            "counter.write_text(counter.read_text(encoding='utf-8') + '1\\n' "
            "if counter.exists() else '1\\n', encoding='utf-8'); "
            "payload={'summary':'캐시 검증 계획','server_work':False,"
            "'source_paths':[],'instruction_paths':[],'tasks':["
            "{'id':'cache-task','title':'캐시 검증 구현',"
            "'description':'계획 결과 캐시 동작을 검증한다.',"
            "'capabilities':['general'],'depends_on':[],"
            "'acceptance_criteria':['동일 입력은 같은 계획을 사용한다.'],"
            "'expected_paths':['README.md'],'forbidden_paths':[],"
            f"'verify_commands':[[{sys.executable!r},'-c','pass']],"
            "'risk_level':'low'}],'questions':[]}; "
            "print('AI_PLAN_RESULT: '+json.dumps(payload, ensure_ascii=False))"
        )
        planner = AgentConfig(
            "planner",
            ("planning",),
            (sys.executable, "-c", planner_script),
            1,
            provider_id="custom",
            review_command=(sys.executable, "-c", planner_script),
        )
        worker = AgentConfig("worker", ("general",), (sys.executable, "-c", "import sys; sys.stdin.read()"), 1, provider_id="custom")
        config = Config(
            path=root / "orchestrator.toml",
            project=ProjectConfig(repo=repo),
            execution=ExecutionConfig(),
            agents=(planner, worker),
            planning=PlanningConfig(agent_id="planner", max_attempts=2, reuse_results=True),
        )
        return Pipeline(config), counter

    @staticmethod
    def _waiting_manual_run(root: Path, repo: Path) -> tuple[Pipeline, RunState]:
        spec = root / "requirements.md"
        spec.write_text("## 작업\n\n- [general] 결과 생성\n", encoding="utf-8")
        config = Config(
            path=root / "orchestrator.toml",
            project=ProjectConfig(repo=repo),
            execution=ExecutionConfig(
                auto_commit=True, verify_commands=((sys.executable, "-c", "from pathlib import Path; assert Path('result.txt').exists()"),)
            ),
            agents=(AgentConfig("manual", ("general",), (), 1),),
        )
        pipeline = Pipeline(config)
        state = pipeline.start(spec)
        state.workspace_mode = ExecutionWorkspaceMode.ISOLATED
        pipeline.store.save(state)
        state = pipeline.confirm_plan(state.id)
        state = pipeline.execute(state.id, manual=True)
        return pipeline, state

    @staticmethod
    def _ready_manual_run(root: Path, repo: Path) -> tuple[Pipeline, RunState]:
        pipeline, state = PipelineTest._waiting_manual_run(root, repo)
        task = state.tasks[0]
        Path(task.worktree, "result.txt").write_text("done\n", encoding="utf-8")
        state = pipeline.complete_task(state.id, task.id)
        return pipeline, state

    @staticmethod
    def _merged_manual_run(root: Path, repo: Path) -> tuple[Pipeline, RunState]:
        pipeline, state = PipelineTest._ready_manual_run(root, repo)
        state = pipeline.verify(state.id)
        return pipeline, pipeline.merge(state.id, approved=True)


if __name__ == "__main__":
    unittest.main()
