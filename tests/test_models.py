import unittest

from ai_orchestrator.code_style import CodeStyleCheck, CodeStyleRule, CodeStyleSnapshot
from ai_orchestrator.models import (
    ArchiveCleanupStatus,
    ArchiveCleanupTarget,
    BootstrapPathState,
    BootstrapSpec,
    ConflictResolutionStatus,
    DirectionChangeRequest,
    DirectionChangeStatus,
    ExecutionWorkspaceMode,
    GroupResultRecord,
    IntegrationConflict,
    IntegrationConflictFile,
    PlanningMessage,
    PlanningMessageRole,
    PlanningApplyRequest,
    PlanningApplyStatus,
    PlanningMode,
    ProfileSource,
    PushReceipt,
    RepositoryMaturityAssessment,
    RepositoryMaturityEvidence,
    RepositoryMaturityKind,
    ReviewStatus,
    ResultFileChange,
    RiskLevel,
    RunState,
    RunSummary,
    RunArchive,
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
)
from ai_orchestrator.progress import ProgressObservation


class RunStateTest(unittest.TestCase):
    def test_stack_choice_questions_are_conservative_and_recomputed_for_legacy_states(self) -> None:
        decision = TechStackDecision("choice", 1, TechStackDecisionStatus.QUESTIONS_REQUIRED, "repo", [], [], [
            TechStackOption("ts", "TypeScript와 Node.js 최소 콘솔 프로젝트", 1,
                            TechStackComponents(languages=["TypeScript"], runtimes=["Node.js LTS"])),
        ])
        choices = [
            "빈 프로젝트의 설치·빌드·테스트를 검증할 기술 구성으로 추천한 TypeScript와 Node.js를 선택할까요?",
            "추천한 구성을 선택할까요?", "추천한 TypeScript와 Node.js를 확정할까요?",
        ]
        self.assertTrue(decision.selection_questions_only(choices))
        for questions in [[], ["실행할 운영체제는 무엇인가요?"], ["추천한 Rust를 선택할까요?"],
                          [choices[0], "배포 대상과 사용자 인증 요구를 알려주세요."],
                          ["추천한 구성을 선택할까요? 서버 운영체제는 무엇인가요?"],
                          ["추천한 TypeScript와 Node.js를 선택할까요? 필요한 기능도 알려주세요."],
                          ["Node.js 버전은 무엇을 선택할까요?"], ["설치 권한을 승인할까요?"], [""]]:
            with self.subTest(questions=questions):
                self.assertFalse(decision.selection_questions_only(questions))
        state = RunState(id="choice", spec_path="", spec_digest="", repo_path="repo", main_branch="main",
                         stage=Stage.NEEDS_CLARIFICATION, repository_intent="new_project", planning_questions=choices,
                         tech_stack_decisions=[decision])
        payload = state.to_dict()
        self.assertTrue(payload.pop("tech_stack_confirmation_allowed"))
        restored = RunState.from_dict(payload)
        self.assertTrue(restored.tech_stack_confirmation_allowed())
        restored.planning_questions.append("사용자 인증 방식은 무엇인가요?")
        self.assertFalse(restored.to_dict()["tech_stack_confirmation_allowed"])
        payload["tech_stack_confirmation_allowed"] = True
        payload["planning_questions"] = ["지원할 운영체제는 무엇인가요?"]
        self.assertFalse(RunState.from_dict(payload).tech_stack_confirmation_allowed())

    def test_run_summary_reports_failure_waiting_and_plan_confirmation(self) -> None:
        state = RunState(
            id="summary",
            spec_path="plan.md",
            spec_digest="digest",
            repo_path="repo",
            main_branch="main",
            stage=Stage.PLANNED,
            plan_revision=3,
            plan_approved_revision=2,
            tasks=[
                WorkTask(id="failed", title="실패", capabilities=[], status=TaskStatus.FAILED),
                WorkTask(id="waiting", title="대기", capabilities=[], status=TaskStatus.WAITING),
            ],
        )

        summary = RunSummary.from_state(
            state,
            attention_reasons=("plan_confirmation", "manual_completion"),
            execution_situation="unavailable",
            checked_at="2026-09-16T00:00:00+00:00",
        )

        self.assertEqual(summary.failed_task_count, 1)
        self.assertEqual(summary.waiting_task_count, 1)
        self.assertFalse(summary.plan_is_approved)
        self.assertEqual(summary.attention_reasons, ("plan_confirmation", "manual_completion"))

    def test_code_style_snapshot_round_trip_and_legacy_default(self) -> None:
        state = RunState(
            id="style",
            spec_path="plan.md",
            spec_digest="digest",
            repo_path="repo",
            main_branch="main",
            stage=Stage.REVIEWED,
            code_style_snapshot=CodeStyleSnapshot(
                preference_revision=2,
                status="detected",
                detected_languages=("python",),
                rules=(CodeStyleRule("python", "ruff", "tool_config", "pyproject.toml", 20, "abc"),),
                checks=(CodeStyleCheck("python", ("python", "-m", "ruff", "check", "."), "pyproject.toml"),),
                diagnostics=(),
                created_at="2026-09-16T00:00:00+00:00",
            ),
        )

        restored = RunState.from_dict(state.to_dict())
        legacy = state.to_dict()
        legacy.pop("code_style_snapshot")

        self.assertEqual(restored.code_style_snapshot, state.code_style_snapshot)
        self.assertIsNone(RunState.from_dict(legacy).code_style_snapshot)

    def test_repository_maturity_and_greenfield_gate_round_trip(self) -> None:
        state = RunState(
            id="greenfield",
            spec_path="plans",
            spec_digest="digest",
            repo_path="repo",
            main_branch="main",
            stage=Stage.NEEDS_CLARIFICATION,
            repository_maturity=RepositoryMaturityAssessment(
                kind=RepositoryMaturityKind.DOCS_ONLY,
                evidence=[RepositoryMaturityEvidence("README.md", "document", [])],
                inspected_file_count=1,
            ),
            repository_intent="new_project",
            greenfield_phase="questions_required",
            tech_stack_decisions=[
                TechStackDecision(
                    decision_id="decision-greenfield",
                    revision=1,
                    status=TechStackDecisionStatus.OPTIONS_READY,
                    project_root="repo",
                    requirement_sources=["plans/product.md"],
                    answers=["데스크톱 앱"],
                    options=[
                        TechStackOption(
                            option_id="electron-typescript",
                            label="Electron + TypeScript",
                            recommendation_rank=1,
                            components=TechStackComponents(
                                languages=["TypeScript"],
                                runtimes=["Node.js"],
                                application_frameworks=["Electron"],
                            ),
                            version_policy=["현재 LTS 범위"],
                            requirement_fit=["Windows 데스크톱 배포"],
                            tradeoffs=["번들 크기"],
                        )
                    ],
                )
            ],
            bootstrap_spec=BootstrapSpec(
                decision_id="decision-greenfield",
                decision_revision=1,
                target_root="repo",
                planned_paths=["package.json", "src/**"],
                steps=["최소 실행 기반을 만든다."],
                required_tools=["Node.js", "npm"],
                verify_commands=[["npm", "test"]],
                excluded_external_actions=["deployment"],
                path_snapshot=[BootstrapPathState("src", "directory")],
                digest="bootstrap-digest",
                verified_integration_head="a" * 40,
                verified_at="2026-09-16T00:00:00+00:00",
                feature_plan_attempts=2,
                feature_plan_error="retryable planning error",
            ),
        )

        restored = RunState.from_dict(state.to_dict())

        self.assertEqual(restored.to_dict(), state.to_dict())

    def test_archive_record_round_trips_with_cleanup_targets(self) -> None:
        state = RunState(
            id="archived",
            spec_path="plan.md",
            spec_digest="digest",
            repo_path="repo",
            main_branch="main",
            stage=Stage.PUSHED,
            archive=RunArchive(
                archived_at="2026-09-14T00:00:00+00:00",
                source_revision="revision",
                snapshot_path="snapshot.json",
                manifest_path="manifest.json",
                summary_path="summary.md",
                fingerprint="fingerprint",
                cleanup_status=ArchiveCleanupStatus.PARTIAL,
                cleanup_targets=[
                    ArchiveCleanupTarget("task-task-1", "worktree", "a" * 40, status="blocked", error="dirty")
                ],
            ),
        )

        restored = RunState.from_dict(state.to_dict())

        self.assertEqual(restored.to_dict(), state.to_dict())
        self.assertEqual(restored.archive.cleanup_status, ArchiveCleanupStatus.PARTIAL)  # type: ignore[union-attr]

    def test_planning_apply_request_round_trip_and_legacy_revision_default(self) -> None:
        state = RunState(
            id="planning-apply",
            spec_path="plan.md",
            spec_digest="abc",
            repo_path="repo",
            main_branch="main",
            stage=Stage.PLANNED,
            planning_messages=[PlanningMessage(PlanningMessageRole.USER, "조건 추가")],
            planning_conversation_revision=4,
            planning_applied_conversation_revision=2,
            planning_apply_requests=[
                PlanningApplyRequest(
                    request_id="apply-1",
                    conversation_revision=4,
                    plan_revision=3,
                    context_snapshot="snapshot",
                    status=PlanningApplyStatus.QUEUED,
                    answer_message="개인 메모 앱",
                    answer_conversation_revision=5,
                    tech_stack_revision=2,
                )
            ],
        )

        restored = RunState.from_dict(state.to_dict())

        self.assertEqual(restored.to_dict(), state.to_dict())
        legacy = state.to_dict()
        legacy.pop("planning_conversation_revision")
        legacy.pop("planning_applied_conversation_revision")
        legacy.pop("planning_apply_requests")
        restored_legacy = RunState.from_dict(legacy)
        self.assertEqual(restored_legacy.planning_conversation_revision, 1)
        self.assertEqual(restored_legacy.planning_applied_conversation_revision, 0)
        self.assertEqual(restored_legacy.planning_apply_requests, [])

    def test_direction_change_round_trip_and_legacy_default(self) -> None:
        state = RunState(
            id="direction", spec_path="plan.md", spec_digest="abc", repo_path="repo", main_branch="main",
            stage=Stage.EXECUTING,
            direction_change_requests=[DirectionChangeRequest(
                request_id="direction-1", text="다음 작업의 범위를 줄여 주세요", task_id="task-1",
                task_title="진행 중", status=DirectionChangeStatus.QUEUED, next_step="미리보기 확인",
            )],
        )
        restored = RunState.from_dict(state.to_dict())
        self.assertEqual(restored.direction_change_requests, state.direction_change_requests)
        legacy = state.to_dict()
        legacy.pop("direction_change_requests")
        self.assertEqual(RunState.from_dict(legacy).direction_change_requests, [])

    def test_progress_observation_round_trip_and_action_boundary(self) -> None:
        task = WorkTask(id="progress", title="진행 관측", capabilities=[])
        task.begin_action(TaskAction.EXECUTE)
        task.progress_observation = ProgressObservation(
            attempt_id="progress:1:execute",
            invocation_id="invocation-1",
            turn_id="turn-1",
            phase="analyzing_request",
            phase_started_at="2026-09-09T00:00:00+00:00",
            last_event_received_at="2026-09-09T00:00:05+00:00",
            last_activity_changed_at="2026-09-09T00:00:00+00:00",
            event_seq=3,
            activity_seq=1,
        )
        state = RunState(id="run", spec_path="plan.md", spec_digest="abc", repo_path="repo", main_branch="main", stage=Stage.EXECUTING, tasks=[task])

        restored = RunState.from_dict(state.to_dict()).tasks[0]

        self.assertEqual(restored.progress_observation, task.progress_observation)
        restored.complete_action(TaskAction.EXECUTE)
        self.assertIsNotNone(restored.progress_observation)
        restored.begin_action(TaskAction.EXECUTE)
        self.assertIsNone(restored.progress_observation)

    def test_execution_evidence_round_trip_and_legacy_defaults(self) -> None:
        state = RunState(
            id="evidence",
            spec_path="plan.md",
            spec_digest="abc",
            repo_path="repo",
            main_branch="main",
            stage=Stage.FAILED,
            tasks=[
                WorkTask(
                    "task",
                    "Task",
                    ["general"],
                    action_results=[
                        TaskActionResult(
                            "execute", attempt_id="attempt-1", status="failed", worker_response="partial",
                            baseline_commit="before", changed_paths=["a.py"], error="scope"
                        ),
                        TaskActionResult("verify", status="succeeded", result_commit="after", passed_commands=[["python", "check.py"]]),
                    ],
                )
            ],
            verification_attempts=[
                VerificationAttempt(
                    status="failed",
                    main_head="main",
                    integration_head="integration",
                    task_heads={"task": "after"},
                    current_command=["test"],
                    passed_commands=[["build"]],
                    commit_queue_task_ids=["task"],
                    failure_phase="verification_command",
                    failed_command=["test"],
                    candidate_task_ids=["task"],
                    attribution_reason="single command owner",
                    error="tests failed",
                    log_path="attempt.log",
                )
            ],
        )
        state.tasks[0].last_attempt_id = "attempt-1"
        self.assertEqual(RunState.from_dict(state.to_dict()).to_dict(), state.to_dict())
        legacy = state.to_dict()
        legacy["schema_version"] = 15
        legacy.pop("verification_attempts")
        legacy["tasks"][0].pop("action_results")
        legacy["tasks"][0].pop("last_attempt_id")
        restored = RunState.from_dict(legacy)
        self.assertEqual(restored.verification_attempts, [])
        self.assertEqual(restored.tasks[0].action_results, [])

    def test_conflict_schedule_round_trip_and_legacy_defaults(self) -> None:
        state = RunState(
            id="schedule",
            spec_path="plan.md",
            spec_digest="abc",
            repo_path="repo",
            main_branch="main",
            stage=Stage.PLANNED,
            tasks=[
                WorkTask("base", "Base", ["general"], is_prerequisite=True, conflict_group=["base", "consumer"]),
                WorkTask("consumer", "Consumer", ["general"], conflict_dependencies=["base"], conflict_group=["base", "consumer"]),
            ],
        )
        restored = RunState.from_dict(state.to_dict())
        self.assertEqual(restored.schema_version, 39)
        self.assertTrue(restored.tasks[0].is_prerequisite)
        self.assertEqual(restored.tasks[1].execution_dependencies, ["base"])
        restored.refresh_task_readiness()
        self.assertEqual(restored.tasks[1].blocked_by, ["base"])
        restored.tasks[0].status = TaskStatus.COMPLETED
        restored.refresh_task_readiness()
        self.assertEqual(restored.tasks[1].readiness, TaskReadiness.READY)
        legacy = state.to_dict()
        legacy["schema_version"] = 14
        for task in legacy["tasks"]:
            for field in ("is_prerequisite", "conflict_dependencies", "conflict_group"):
                task.pop(field)
        previous = RunState.from_dict(legacy)
        self.assertFalse(previous.tasks[0].is_prerequisite)
        self.assertEqual(previous.tasks[1].execution_dependencies, [])
        self.assertEqual(previous.tasks[1].conflict_group, [])

    def test_round_trip(self) -> None:
        state = RunState(
            id="run-1",
            spec_path="/tmp/spec.md",
            spec_digest="abc",
            repo_path="/tmp/repo",
            main_branch="main",
            stage=Stage.PLANNED,
            workspace_mode=ExecutionWorkspaceMode.SHARED,
            workspace_location=WorkspaceLocation(
                root="/tmp/repo/.ai_auto_work/worktree",
                source=WorkspaceLocationSource.PROJECT_DEFAULT,
            ),
            execution_branch="ai/run-1",
            execution_worktree="/tmp/worktrees/run-1/work",
            pushed_work_branch_head="pushedhead",
            push_receipts=[
                PushReceipt(
                    scope="work_branch",
                    remote="origin",
                    branch="ai/run-1",
                    local_commit="pushedhead",
                    remote_commit="pushedhead",
                    operation_request_id="push-request",
                    pushed_at="2026-09-22T00:00:00+00:00",
                )
            ],
            planning_mode=PlanningMode.DIRECTED,
            planning_request="알림 조회 API만 계획해 주세요.",
            plan_revision=3,
            plan_approved_revision=3,
            base_commit="deadbeef",
            verified_task_heads={"t01-api": "cafebabe"},
            verified_main_head="mainhead",
            verified_integration_head="integrationhead",
            tasks=[
                WorkTask(
                    id="t01-api",
                    title="API 구현",
                    capabilities=["backend"],
                    description="알림 조회 API를 구현한다.",
                    acceptance_criteria=["인증된 사용자가 알림을 조회한다"],
                    dependencies=["schema"],
                    expected_paths=["src/api/**"],
                    forbidden_paths=["migrations/**"],
                    verify_commands=[["python", "-m", "unittest"]],
                    risk_level=RiskLevel.HIGH,
                    agent_id="backend-ai",
                    provider_id="codex",
                    reasoning_effort="high",
                    effective_model="gpt-5.6-sol",
                    effective_reasoning_effort="high",
                    reviewer_agent_id="review-ai",
                    reviewer_provider_id="claude",
                    review_status=ReviewStatus.APPROVED,
                    review_cycles=1,
                    review_summary="approved",
                    started_commit="starthead",
                    completed_commit="completehead",
                )
            ],
        )
        state.add_event("test", "saved")
        state.tasks[0].begin_action(TaskAction.REVIEW)
        self.assertEqual(state.tasks[0].effective_model, "gpt-5.6-sol")
        self.assertEqual(state.tasks[0].effective_reasoning_effort, "high")
        state.tasks[0].update_progress("plan_step", "관련 코드 확인")
        self.assertEqual(state.tasks[0].progress_phase, "plan_step")
        self.assertEqual(state.tasks[0].progress_detail, "관련 코드 확인")
        self.assertTrue(state.tasks[0].progress_updated_at)
        state.tasks[0].fail_action(TaskAction.REVIEW, "review interrupted")
        state.begin_verification(3)
        state.update_verification_progress("running_command", "python -m unittest", current=2)
        state.begin_step(RunStep.AGENT_EXECUTION)
        state.fail_step(RunStep.AGENT_EXECUTION, "agent timed out")

        restored = RunState.from_dict(state.to_dict())

        self.assertEqual(restored.stage, Stage.FAILED)
        self.assertEqual(restored.tasks[0].agent_id, "backend-ai")
        self.assertEqual(restored.tasks[0].provider_id, "codex")
        self.assertEqual(restored.tasks[0].reasoning_effort, "high")
        self.assertEqual(restored.tasks[0].effective_model, "gpt-5.6-sol")
        self.assertEqual(restored.tasks[0].effective_reasoning_effort, "high")
        self.assertEqual(restored.tasks[0].description, "알림 조회 API를 구현한다.")
        self.assertEqual(restored.tasks[0].acceptance_criteria, ["인증된 사용자가 알림을 조회한다"])
        self.assertEqual(restored.tasks[0].dependencies, ["schema"])
        self.assertEqual(restored.tasks[0].expected_paths, ["src/api/**"])
        self.assertEqual(restored.tasks[0].forbidden_paths, ["migrations/**"])
        self.assertEqual(restored.tasks[0].verify_commands, [["python", "-m", "unittest"]])
        self.assertEqual(restored.tasks[0].risk_level, RiskLevel.HIGH)
        self.assertEqual(restored.tasks[0].readiness, TaskReadiness.BLOCKED)
        self.assertEqual(restored.tasks[0].blocked_by, ["schema"])
        self.assertEqual(restored.tasks[0].review_status, ReviewStatus.APPROVED)
        self.assertEqual(restored.tasks[0].reviewer_provider_id, "claude")
        self.assertEqual(restored.events[0].message, "saved")
        self.assertEqual(restored.base_commit, "deadbeef")
        self.assertEqual(restored.workspace_mode, ExecutionWorkspaceMode.SHARED)
        self.assertEqual(restored.workspace_location, state.workspace_location)
        self.assertEqual(restored.execution_branch, "ai/run-1")
        self.assertEqual(restored.execution_worktree, "/tmp/worktrees/run-1/work")
        self.assertEqual(restored.pushed_work_branch_head, "pushedhead")
        self.assertEqual(restored.push_receipts, state.push_receipts)
        self.assertEqual(restored.tasks[0].started_commit, "starthead")
        self.assertEqual(restored.tasks[0].completed_commit, "completehead")
        self.assertEqual(restored.verified_task_heads, {"t01-api": "cafebabe"})
        self.assertEqual(restored.verified_main_head, "mainhead")
        self.assertEqual(restored.verified_integration_head, "integrationhead")
        self.assertEqual(restored.verification_progress_phase, "running_command")
        self.assertEqual(restored.verification_progress_detail, "python -m unittest")
        self.assertEqual(restored.verification_progress_current, 2)
        self.assertEqual(restored.verification_progress_total, 3)
        self.assertTrue(restored.verification_started_at)
        self.assertTrue(restored.verification_progress_updated_at)
        self.assertEqual(restored.failed_step, RunStep.AGENT_EXECUTION)
        self.assertEqual(restored.failure_message, "agent timed out")
        self.assertIsNone(restored.active_step)
        self.assertEqual(restored.tasks[0].failed_action, TaskAction.REVIEW)
        self.assertEqual(restored.tasks[0].attempt_count, 1)
        self.assertEqual(restored.plan_revision, 3)
        self.assertEqual(restored.plan_approved_revision, 3)
        self.assertTrue(restored.plan_is_approved)
        self.assertEqual(restored.planning_mode, PlanningMode.DIRECTED)
        self.assertEqual(restored.planning_request, "알림 조회 API만 계획해 주세요.")
        self.assertTrue(restored.tasks[0].last_attempt_started_at)
        self.assertTrue(restored.tasks[0].last_attempt_finished_at)
        self.assertEqual(restored.tasks[0].progress_phase, "")
        self.assertEqual(restored.tasks[0].progress_detail, "")
        self.assertEqual(restored.tasks[0].progress_updated_at, "")

    def test_reads_state_without_recovery_fields(self) -> None:
        restored = RunState.from_dict(
            {
                "id": "legacy",
                "spec_path": "plan.md",
                "spec_digest": "abc",
                "repo_path": "repo",
                "main_branch": "main",
                "stage": "planned",
                "tasks": [{"id": "t01", "title": "legacy task", "capabilities": []}],
            }
        )

        self.assertEqual(restored.schema_version, 1)
        self.assertEqual(restored.workspace_mode, ExecutionWorkspaceMode.ISOLATED)
        self.assertEqual(restored.execution_branch, "")
        self.assertEqual(restored.execution_worktree, "")
        self.assertEqual(restored.pushed_work_branch_head, "")
        self.assertEqual(restored.push_receipts, [])
        self.assertEqual(restored.base_commit, "")
        self.assertEqual(restored.verified_task_heads, {})
        self.assertEqual(restored.verified_main_head, "")
        self.assertEqual(restored.verified_integration_head, "")
        self.assertEqual(restored.verification_progress_phase, "")
        self.assertEqual(restored.verification_progress_detail, "")
        self.assertEqual(restored.verification_progress_current, 0)
        self.assertEqual(restored.verification_progress_total, 0)
        self.assertEqual(restored.verification_started_at, "")
        self.assertEqual(restored.verification_progress_updated_at, "")
        self.assertIsNone(restored.active_step)
        self.assertIsNone(restored.failed_step)
        self.assertIsNone(restored.tasks[0].active_action)
        self.assertIsNone(restored.tasks[0].failed_action)
        self.assertEqual(restored.tasks[0].attempt_count, 0)
        self.assertEqual(restored.tasks[0].description, "")
        self.assertEqual(restored.tasks[0].acceptance_criteria, [])
        self.assertEqual(restored.tasks[0].dependencies, [])
        self.assertEqual(restored.tasks[0].expected_paths, [])
        self.assertEqual(restored.tasks[0].forbidden_paths, [])
        self.assertEqual(restored.tasks[0].verify_commands, [])
        self.assertEqual(restored.tasks[0].risk_level, RiskLevel.MEDIUM)
        self.assertEqual(restored.tasks[0].readiness, TaskReadiness.READY)
        self.assertEqual(restored.planning_model, "")
        self.assertEqual(restored.planning_reasoning_effort, "")
        self.assertEqual(restored.planning_claude_session_id, "")
        self.assertEqual(restored.planning_mode, PlanningMode.AUTO)
        self.assertEqual(restored.planning_request, "")
        self.assertEqual(restored.tasks[0].reasoning_effort, "")
        self.assertEqual(restored.tasks[0].effective_model, "")
        self.assertEqual(restored.tasks[0].effective_reasoning_effort, "")
        self.assertEqual(restored.tasks[0].progress_phase, "")
        self.assertEqual(restored.tasks[0].progress_detail, "")
        self.assertEqual(restored.tasks[0].progress_updated_at, "")
        self.assertEqual(restored.tasks[0].started_commit, "")
        self.assertEqual(restored.tasks[0].completed_commit, "")
        self.assertEqual(restored.plan_revision, 0)
        self.assertTrue(restored.plan_is_approved)

        schema_two = restored.to_dict()
        schema_two["schema_version"] = 2
        schema_two["tasks"][0].pop("expected_paths")
        schema_two["tasks"][0].pop("forbidden_paths")
        schema_two["tasks"][0].pop("verify_commands")
        schema_two["tasks"][0].pop("risk_level")
        schema_two["tasks"][0].pop("readiness")
        schema_two["tasks"][0].pop("blocked_by")

        restored_schema_two = RunState.from_dict(schema_two)

        self.assertEqual(restored_schema_two.schema_version, 2)
        self.assertEqual(restored_schema_two.tasks[0].expected_paths, [])
        self.assertEqual(restored_schema_two.tasks[0].readiness, TaskReadiness.READY)

    def test_begin_execution_clears_previous_effective_profile(self) -> None:
        task = WorkTask(id="runtime-profile", title="실제 프로필 추적", capabilities=[], effective_model="gpt-previous", effective_reasoning_effort="medium")

        task.begin_action(TaskAction.EXECUTE)

        self.assertEqual(task.effective_model, "")
        self.assertEqual(task.effective_reasoning_effort, "")

    def test_verification_action_does_not_increment_agent_attempts(self) -> None:
        task = WorkTask(id="verify-only", title="검증만 재실행", capabilities=[], attempt_count=2)

        task.begin_action(TaskAction.VERIFY, count_attempt=False)
        task.fail_action(TaskAction.VERIFY, "npm command failed")

        self.assertEqual(task.attempt_count, 2)
        self.assertEqual(task.failed_action, TaskAction.VERIFY)

    def test_round_trips_planning_clarification_state(self) -> None:
        state = RunState(
            id="clarify",
            spec_path="plan.txt",
            spec_digest="abc",
            repo_path="repo",
            main_branch="main",
            stage=Stage.NEEDS_CLARIFICATION,
            planning_questions=["실시간 알림인가요?"],
            planning_agent_id="planner",
            planning_provider_id="codex",
            planning_model="gpt-5.6-terra",
            planning_reasoning_effort="xhigh",
            planning_claude_session_id=("3b79eb26-4234-48b8-bb8c-f9d0b0c731b1"),
            planning_attempts=1,
            structured_plan_path="plan.json",
            clarification_paths=["answers.md"],
            planning_messages=[
                PlanningMessage(role=PlanningMessageRole.USER, text="비동기 조회로 구현합니다."),
                PlanningMessage(role=PlanningMessageRole.ASSISTANT, text="Task 1개로 계획했습니다."),
            ],
            planning_follow_up_requests=["후속 검증 Task를 계획합니다."],
        )

        restored = RunState.from_dict(state.to_dict())

        self.assertEqual(restored.stage, Stage.NEEDS_CLARIFICATION)
        self.assertEqual(restored.planning_questions, ["실시간 알림인가요?"])
        self.assertEqual(restored.planning_agent_id, "planner")
        self.assertEqual(restored.planning_provider_id, "codex")
        self.assertEqual(restored.planning_model, "gpt-5.6-terra")
        self.assertEqual(restored.planning_reasoning_effort, "xhigh")
        self.assertEqual(restored.planning_claude_session_id, "3b79eb26-4234-48b8-bb8c-f9d0b0c731b1")
        self.assertEqual(restored.planning_attempts, 1)
        self.assertEqual(restored.clarification_paths, ["answers.md"])
        self.assertEqual([message.role for message in restored.planning_messages], [PlanningMessageRole.USER, PlanningMessageRole.ASSISTANT])
        self.assertEqual(restored.planning_messages[0].text, "비동기 조회로 구현합니다.")
        self.assertEqual(restored.planning_follow_up_requests, ["후속 검증 Task를 계획합니다."])
        self.assertEqual(restored.schema_version, 39)

    def test_result_history_survives_state_round_trip_and_legacy_has_no_final_evidence(self) -> None:
        prior = TaskResultRecord("a" * 40, "b" * 40, "2026-09-29T00:00:00+00:00", files_state="none")
        latest = TaskResultRecord(
            "b" * 40, "c" * 40, "2026-09-29T01:00:00+00:00", files_state="confirmed",
            files=[ResultFileChange("added.txt", "A"), ResultFileChange("deleted.txt", "D")],
            self_report="작업 완료", verification_status="passed", passed_commands=[["python", "-m", "pytest"]],
        )
        state = RunState(
            id="result-history", spec_path="plan.md", spec_digest="digest", repo_path="repo", main_branch="main",
            stage=Stage.VERIFIED, tasks=[WorkTask("task", "Task", ["general"], result_history=[prior, latest])],
            group_result_history=[GroupResultRecord(
                "attempt", "a" * 40, "c" * 40, "2026-09-29T02:00:00+00:00",
                files_state="confirmed", files=[ResultFileChange("added.txt", "A")],
            )],
        )
        restored = RunState.from_dict(state.to_dict())
        self.assertEqual(restored.to_dict(), state.to_dict())
        self.assertEqual([item.files_state for item in restored.tasks[0].result_history], ["none", "confirmed"])

        legacy = state.to_dict()
        legacy.pop("group_result_history")
        legacy["tasks"][0].pop("result_history")
        restored_legacy = RunState.from_dict(legacy)
        self.assertEqual(restored_legacy.tasks[0].result_history, [])
        self.assertEqual(restored_legacy.group_result_history, [])

    def test_profile_sources_round_trip_and_missing_values_remain_legacy(self) -> None:
        state = RunState(
            id="profile-source", spec_path="plan.md", spec_digest="digest", repo_path="repo", main_branch="main",
            stage=Stage.PLANNED, planning_profile_source=ProfileSource.MANUAL,
            tasks=[WorkTask("t01", "Task", ["general"], profile_source=ProfileSource.ROUTING)],
        )
        restored = RunState.from_dict(state.to_dict())
        self.assertEqual(restored.planning_profile_source, ProfileSource.MANUAL)
        self.assertEqual(restored.tasks[0].profile_source, ProfileSource.ROUTING)

        legacy = state.to_dict()
        legacy["schema_version"] = 34
        legacy.pop("planning_profile_source")
        legacy["tasks"][0].pop("profile_source")
        restored_legacy = RunState.from_dict(legacy)
        self.assertEqual(restored_legacy.planning_profile_source, ProfileSource.LEGACY)
        self.assertEqual(restored_legacy.tasks[0].profile_source, ProfileSource.LEGACY)

    def test_legacy_integration_conflict_restores_one_recovery_task_and_new_basis_supersedes_it(self) -> None:
        first = IntegrationConflict(
            id="conflict-first",
            verification_attempt_id="verify-first",
            main_head="main-a",
            work_head="work-a",
            merge_base_heads=["base"],
            files=[IntegrationConflictFile(path="README.md", kind="both_modified")],
            fingerprint="a" * 64,
        )
        state = RunState(
            id="recovery",
            spec_path="plan.md",
            spec_digest="abc",
            repo_path="repo",
            main_branch="main",
            stage=Stage.FAILED,
            integration_conflict=first,
        )
        legacy = state.to_dict()
        legacy.pop("recovery_tasks")

        restored = RunState.from_dict(legacy)

        self.assertEqual(len(restored.recovery_tasks), 1)
        recovery = restored.recovery_tasks[0]
        self.assertEqual(recovery.id, "recovery-aaaaaaaaaaaaaaaa")
        self.assertIs(restored.integration_conflict, recovery.conflict)
        self.assertEqual(recovery.verification_attempt_ids, ["verify-first"])
        self.assertIs(restored.register_integration_conflict(first), recovery)
        self.assertEqual(len(restored.recovery_tasks), 1)

        second = IntegrationConflict(
            id="conflict-second",
            verification_attempt_id="verify-second",
            main_head="main-b",
            work_head="work-b",
            merge_base_heads=["base"],
            files=[IntegrationConflictFile(path="README.md", kind="both_modified")],
            fingerprint="b" * 64,
            resolution_status=ConflictResolutionStatus.UNRESOLVED,
        )
        current = restored.register_integration_conflict(second)
        self.assertEqual(len(restored.recovery_tasks), 2)
        self.assertEqual(recovery.superseded_by, current.id)
        self.assertIs(restored.integration_conflict, current.conflict)

    def test_plan_revision_invalidates_and_restores_approval(self) -> None:
        state = RunState(id="review", spec_path="plan.md", spec_digest="abc", repo_path="repo", main_branch="main", stage=Stage.PLANNED)

        self.assertTrue(state.plan_is_approved)

        state.revise_plan()

        self.assertEqual(state.plan_revision, 1)
        self.assertFalse(state.plan_is_approved)

        state.approve_plan()

        self.assertEqual(state.plan_approved_revision, 1)
        self.assertTrue(state.plan_is_approved)

    def test_calculates_ready_and_blocked_from_dependency_status(self) -> None:
        base = WorkTask(id="base", title="base", capabilities=["general"])
        dependent = WorkTask(id="dependent", title="dependent", capabilities=["general"], dependencies=["base"])
        state = RunState(
            id="readiness", spec_path="plan.md", spec_digest="abc", repo_path="repo", main_branch="main", stage=Stage.PLANNED, tasks=[base, dependent]
        )

        state.refresh_task_readiness()

        self.assertEqual(base.readiness, TaskReadiness.READY)
        self.assertEqual(dependent.readiness, TaskReadiness.BLOCKED)
        self.assertEqual(dependent.blocked_by, ["base"])

        base.status = TaskStatus.COMPLETED
        state.refresh_task_readiness()

        self.assertEqual(base.readiness, TaskReadiness.DONE)
        self.assertEqual(dependent.readiness, TaskReadiness.READY)
        self.assertEqual(dependent.blocked_by, [])

        base.status = TaskStatus.FAILED
        state.refresh_task_readiness()

        self.assertEqual(base.readiness, TaskReadiness.FAILED)
        self.assertEqual(dependent.readiness, TaskReadiness.BLOCKED)


if __name__ == "__main__":
    unittest.main()
