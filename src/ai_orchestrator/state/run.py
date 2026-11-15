from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..code_style import CodeStyleSnapshot
from .codec import (
    decode_run_state_fields,
    decode_run_summary_fields,
)
from .common import (
    CURRENT_STATE_SCHEMA_VERSION,
    ConflictResolutionStatus,
    Event,
    ExecutionWorkspaceMode,
    PlanningMode,
    ProfileSource,
    RunStep,
    Stage,
    TaskReadiness,
    TaskStatus,
    TechStackDecisionStatus,
    UserCheckOutcome,
    UserNotificationEvent,
    utc_now,
)
from .execution import (
    GroupResultRecord,
    UserCheck,
    UserCheckResult,
    WorkTask,
)
from .integration import (
    IntegrationConflict,
    PushReceipt,
    RecoveryTask,
    RunArchive,
    VerificationAttempt,
    WorkspaceLocation,
    conflict_source_key,
)
from .planning import (
    BootstrapSpec,
    DirectionChangeRequest,
    PlanningApplyRequest,
    PlanningMessage,
    RepositoryMaturityAssessment,
    TechStackDecision,
)


@dataclass(slots=True)
class RunState:
    id: str
    spec_path: str
    spec_digest: str
    repo_path: str
    main_branch: str
    stage: Stage
    spec_snapshot_path: str = ""
    server_work: bool = False
    summary: str = ""
    tasks: list[WorkTask] = field(default_factory=list)
    planning_questions: list[str] = field(default_factory=list)
    planning_agent_id: str = ""
    planning_provider_id: str = ""
    planning_model: str = ""
    planning_reasoning_effort: str = ""
    planning_profile_source: ProfileSource = ProfileSource.LEGACY
    planning_effort_baseline_reasoning: str | None = None
    planning_claude_session_id: str = ""
    planning_mode: PlanningMode = PlanningMode.AUTO
    planning_request: str = ""
    revision_source_run_id: str = ""
    revision_request_id: str = ""
    revision_request_text: str = ""
    revision_source_task_ids: list[str] = field(default_factory=list)
    revision_source_paths: list[str] = field(default_factory=list)
    planning_attempts: int = 0
    structured_plan_path: str = ""
    clarification_paths: list[str] = field(default_factory=list)
    planning_messages: list[PlanningMessage] = field(default_factory=list)
    planning_follow_up_requests: list[str] = field(default_factory=list)
    planning_conversation_revision: int = 0
    planning_applied_conversation_revision: int = 0
    planning_apply_requests: list[PlanningApplyRequest] = field(default_factory=list)
    direction_change_requests: list[DirectionChangeRequest] = field(default_factory=list)
    repository_maturity: RepositoryMaturityAssessment | None = None
    code_style_snapshot: CodeStyleSnapshot | None = None
    repository_intent: str = ""
    greenfield_phase: str = ""
    tech_stack_decisions: list[TechStackDecision] = field(default_factory=list)
    bootstrap_spec: BootstrapSpec | None = None
    plan_revision: int = 0
    plan_approved_revision: int = 0
    active_policy_id: str = ""
    active_execution_request_id: str = ""
    events: list[Event] = field(default_factory=list)
    notification_events: list[UserNotificationEvent] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    schema_version: int = CURRENT_STATE_SCHEMA_VERSION
    workspace_mode: ExecutionWorkspaceMode = ExecutionWorkspaceMode.ISOLATED
    workspace_location: WorkspaceLocation | None = None
    execution_branch: str = ""
    execution_worktree: str = ""
    base_commit: str = ""
    verified_task_heads: dict[str, str] = field(default_factory=dict)
    verified_main_head: str = ""
    verified_integration_head: str = ""
    pushed_work_branch_head: str = ""
    push_receipts: list[PushReceipt] = field(default_factory=list)
    verification_progress_phase: str = ""
    verification_progress_detail: str = ""
    verification_progress_current: int = 0
    verification_progress_total: int = 0
    verification_started_at: str = ""
    verification_progress_updated_at: str = ""
    active_step: RunStep | None = None
    failed_step: RunStep | None = None
    failure_message: str = ""
    verification_attempts: list[VerificationAttempt] = field(default_factory=list)
    group_result_history: list[GroupResultRecord] = field(default_factory=list)
    integration_conflict: IntegrationConflict | None = None
    recovery_tasks: list[RecoveryTask] = field(default_factory=list)
    archive: RunArchive | None = None
    verification_policy_version: int = 1
    task_verify_command_timeout_seconds: int = 0
    task_verify_total_timeout_seconds: int = 0
    integration_verify_command_timeout_seconds: int = 0
    integration_verify_total_timeout_seconds: int = 0
    verification_repair_limit: int = 2
    verification_repair_count: int = 0
    verification_repair_head: str = ""
    verification_repair_main_head: str = ""
    verification_repair_task_heads: dict[str, str] = field(default_factory=dict)
    external_plan_digest: str = ""
    user_check_plan: list[UserCheck] = field(default_factory=list)
    user_check_results: dict[str, list[UserCheckResult]] = field(default_factory=dict)

    @property
    def plan_is_approved(self) -> bool:
        return self.plan_revision == 0 or self.plan_approved_revision == self.plan_revision

    def revise_plan(self) -> None:
        self.plan_revision = max(1, self.plan_revision + 1)
        self.plan_approved_revision = 0

    def approve_plan(self) -> None:
        if self.plan_revision > 0:
            self.plan_approved_revision = self.plan_revision

    def current_tech_stack_decision(self) -> TechStackDecision | None:
        return next(
            (decision for decision in reversed(self.tech_stack_decisions) if decision.status != TechStackDecisionStatus.SUPERSEDED),
            None,
        )

    def tech_stack_confirmation_allowed(self) -> bool:
        decision = self.current_tech_stack_decision()
        if self.repository_intent != "new_project" or self.stage not in {Stage.NEEDS_CLARIFICATION, Stage.PLANNED} or decision is None:
            return False
        return decision.status == TechStackDecisionStatus.OPTIONS_READY or (
            decision.status == TechStackDecisionStatus.QUESTIONS_REQUIRED and decision.selection_questions_only(self.planning_questions)
        )

    def add_event(self, kind: str, message: str) -> None:
        self.updated_at = utc_now()
        self.events.append(Event(at=self.updated_at, kind=kind, message=message))

    def register_integration_conflict(self, conflict: IntegrationConflict) -> RecoveryTask:
        source_key = conflict_source_key(conflict)
        existing = next(
            (
                task
                for task in self.recovery_tasks
                if task.kind == "conflict_resolution" and task.source_key == source_key
            ),
            None,
        )
        if existing is not None:
            if conflict.verification_attempt_id and conflict.verification_attempt_id not in existing.verification_attempt_ids:
                existing.verification_attempt_ids.append(conflict.verification_attempt_id)
            self.integration_conflict = existing.conflict
            return existing
        recovery_id = f"recovery-{conflict.fingerprint[:16] or conflict.id.removeprefix('conflict-')}"
        if any(task.id == recovery_id for task in self.recovery_tasks):
            recovery_id = f"{recovery_id}-{len(self.recovery_tasks) + 1}"
        for task in self.recovery_tasks:
            if not task.superseded_by and task.conflict.resolution_status != ConflictResolutionStatus.APPLIED:
                task.superseded_by = recovery_id
        recovery = RecoveryTask(
            id=recovery_id,
            kind="conflict_resolution",
            source_key=source_key,
            conflict=conflict,
            verification_attempt_ids=([conflict.verification_attempt_id] if conflict.verification_attempt_id else []),
        )
        self.recovery_tasks.append(recovery)
        self.integration_conflict = recovery.conflict
        return recovery

    def recovery_task_for_conflict(self, conflict_id: str) -> RecoveryTask | None:
        return next((task for task in self.recovery_tasks if task.conflict.id == conflict_id), None)

    def link_recovery_operation(self, conflict_id: str, request_id: str) -> None:
        task = self.recovery_task_for_conflict(conflict_id)
        if task is not None and request_id not in task.operation_request_ids:
            task.operation_request_ids.append(request_id)

    def link_recovery_verification(self, conflict_id: str, attempt_id: str) -> None:
        task = self.recovery_task_for_conflict(conflict_id)
        if task is not None and attempt_id and attempt_id not in task.verification_attempt_ids:
            task.verification_attempt_ids.append(attempt_id)

    def transition(self, stage: Stage, message: str) -> None:
        self.stage = stage
        self.add_event("stage", message)

    def begin_step(self, step: RunStep) -> None:
        self.active_step = step
        self.failed_step = None
        self.failure_message = ""
        self.add_event("step", f"{step.value} started")

    def begin_verification(self, total: int) -> None:
        started_at = utc_now()
        self.verification_progress_phase = "preparing"
        self.verification_progress_detail = ""
        self.verification_progress_current = 0
        self.verification_progress_total = total
        self.verification_started_at = started_at
        self.verification_progress_updated_at = started_at

    def update_verification_progress(self, phase: str, detail: str = "", *, current: int = 0, total: int | None = None) -> None:
        self.verification_progress_phase = phase
        if self.verification_attempts and self.verification_attempts[-1].status == "running":
            self.verification_attempts[-1].phase = phase
        self.verification_progress_detail = detail
        self.verification_progress_current = current
        if total is not None:
            self.verification_progress_total = total
        self.verification_progress_updated_at = utc_now()

    def complete_step(self, step: RunStep) -> None:
        if self.active_step == step:
            self.active_step = None
        if step == RunStep.VERIFY:
            self.update_verification_progress("completed", current=self.verification_progress_total)
        self.add_event("step", f"{step.value} completed")

    def fail_step(self, step: RunStep, message: str) -> None:
        self.active_step = None
        self.failed_step = step
        self.failure_message = message
        if step == RunStep.VERIFY:
            self.update_verification_progress("failed", message, current=self.verification_progress_current)
        self.transition(Stage.FAILED, message)

    def resume_to(self, stage: Stage, message: str) -> None:
        self.active_step = None
        self.failed_step = None
        self.failure_message = ""
        self.transition(stage, message)

    def user_check_reference(self, check: UserCheck) -> str:
        if not check.after_task_id:
            return self.base_commit
        task = next((task for task in self.tasks if task.id == check.after_task_id), None)
        if task is None or task.status not in {TaskStatus.COMPLETED, TaskStatus.MERGED}:
            return ""
        return task.completed_commit

    def current_user_check_result(self, check: UserCheck) -> UserCheckResult | None:
        reference = self.user_check_reference(check)
        if not reference:
            return None
        return next((result for result in reversed(self.user_check_results.get(check.id, [])) if result.reference_commit == reference), None)

    def unresolved_user_checks(self) -> list[UserCheck]:
        return [check for check in self.user_check_plan
                if (result := self.current_user_check_result(check)) is None or result.outcome != UserCheckOutcome.PASSED]

    def integration_user_checks_pending(self) -> bool:
        return any(check.required_for_integration for check in self.unresolved_user_checks())

    def user_check_blocked_task_ids(self) -> set[str]:
        blocked = {task_id for check in self.unresolved_user_checks() for task_id in check.blocks_task_ids}
        while blocked:
            dependents = {task.id for task in self.tasks if blocked.intersection(task.execution_dependencies)} - blocked
            if not dependents:
                break
            blocked.update(dependents)
        return blocked

    def refresh_task_readiness(self) -> None:
        statuses = {task.id: task.status for task in self.tasks}
        satisfied = {TaskStatus.COMPLETED, TaskStatus.MERGED}
        check_blockers: dict[str, list[str]] = {}
        for check in self.unresolved_user_checks():
            for task_id in check.blocks_task_ids:
                check_blockers.setdefault(task_id, []).append(check.id)
        for task in self.tasks:
            if task.status in satisfied:
                task.readiness = TaskReadiness.DONE
                task.blocked_by = []
                continue
            if task.status in {TaskStatus.FAILED, TaskStatus.STOPPED}:
                task.readiness = TaskReadiness.FAILED
                task.blocked_by = []
                continue
            if task.status in {TaskStatus.RUNNING, TaskStatus.REVIEWING, TaskStatus.REVISING}:
                task.readiness = TaskReadiness.ACTIVE
                task.blocked_by = []
                continue
            task.blocked_by = [dependency for dependency in task.execution_dependencies if statuses.get(dependency) not in satisfied]
            task.blocked_by.extend(check_blockers.get(task.id, ()))
            task.readiness = TaskReadiness.BLOCKED if task.blocked_by or task.status == TaskStatus.DEFERRED else TaskReadiness.READY

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["code_style_snapshot"] = self.code_style_snapshot.to_dict() if self.code_style_snapshot else None
        payload["tech_stack_confirmation_allowed"] = self.tech_stack_confirmation_allowed()
        return payload

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RunState":
        state = cls(**decode_run_state_fields(raw))
        state.refresh_task_readiness()
        return state


@dataclass(frozen=True, slots=True)
class RunSummary:
    id: str
    summary: str
    stage: Stage
    updated_at: str
    created_at: str
    task_count: int
    completed_task_count: int
    archived: bool = False
    archived_at: str = ""
    cleanup_status: str = ""
    failed_task_count: int = 0
    waiting_task_count: int = 0
    plan_is_approved: bool = True
    attention_reasons: tuple[str, ...] = ()
    execution_situation: str = "unavailable"
    pipeline_complete: bool = False
    checked_at: str = ""

    @classmethod
    def from_state(
        cls,
        state: RunState,
        *,
        attention_reasons: tuple[str, ...] = (),
        execution_situation: str = "unavailable",
        pipeline_complete: bool = False,
        checked_at: str = "",
    ) -> "RunSummary":
        completed = {TaskStatus.COMPLETED, TaskStatus.MERGED}
        return cls(
            id=state.id,
            summary=state.summary,
            stage=state.stage,
            updated_at=state.updated_at,
            created_at=state.created_at,
            task_count=len(state.tasks),
            completed_task_count=sum(task.status in completed for task in state.tasks),
            archived=state.archive is not None,
            archived_at=state.archive.archived_at if state.archive else "",
            cleanup_status=state.archive.cleanup_status.value if state.archive else "",
            failed_task_count=sum(task.status == TaskStatus.FAILED for task in state.tasks),
            waiting_task_count=sum(task.status == TaskStatus.WAITING for task in state.tasks),
            plan_is_approved=state.plan_is_approved,
            attention_reasons=attention_reasons,
            execution_situation=execution_situation,
            pipeline_complete=pipeline_complete,
            checked_at=checked_at,
        )

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RunSummary":
        return cls(**decode_run_summary_fields(raw))
