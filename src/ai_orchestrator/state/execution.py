from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..code_style import CodeStyleTaskEvidence
from ..progress import ProgressObservation
from .common import (
    ProfileSource,
    ReviewStatus,
    RiskLevel,
    RunExecutionAction,
    RunExecutionSituation,
    RunLockState,
    TaskAction,
    TaskReadiness,
    TaskStatus,
    UserCheckOutcome,
    operation_created_at,
    utc_now,
)


@dataclass(slots=True)
class ResultFileChange:
    path: str
    change: str


@dataclass(slots=True)
class TaskResultRecord:
    baseline_commit: str
    result_commit: str
    captured_at: str
    files_state: str = "unavailable"
    files: list[ResultFileChange] = field(default_factory=list)
    error: str = ""
    self_report: str = ""
    verification_status: str = "unverified"
    passed_commands: list[list[str]] = field(default_factory=list)
    manual_verification_note: str = ""


@dataclass(slots=True)
class GroupResultRecord:
    verification_attempt_id: str
    main_commit: str
    result_commit: str
    captured_at: str
    files_state: str = "unavailable"
    files: list[ResultFileChange] = field(default_factory=list)
    error: str = ""


@dataclass(slots=True)
class TaskActionResult:
    action: str
    attempt_id: str = ""
    invocation_id: str = ""
    status: str = "running"
    started_at: str = field(default_factory=utc_now)
    finished_at: str = ""
    worker_response: str = ""
    baseline_commit: str = ""
    result_commit: str = ""
    changed_paths: list[str] = field(default_factory=list)
    passed_commands: list[list[str]] = field(default_factory=list)
    code_style_evidence: CodeStyleTaskEvidence | None = None
    review_verdict: str = ""
    review_findings: list[str] = field(default_factory=list)
    error: str = ""
    verification_context_digest: str = ""
    verification_failure_kind: str = ""
    verification_context_inputs: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OperationRecord:
    request_id: str
    run_id: str
    action: str
    digest: str
    phase: str
    status: str = "running"
    expected_main_head: str = ""
    target_head: str = ""
    error: str = ""
    error_code: str = ""
    finished_at: str = ""
    result_revision: int = 0
    result_commit: str = ""
    result_ref: str = ""
    resume_request_id: str = ""
    created_at: str = field(default_factory=operation_created_at)
    updated_at: str = field(default_factory=operation_created_at)
    execution_id: str = ""
    task_id: str = ""
    attempt_id: str = ""
    invocation_id: str = ""
    scope: str = ""
    reason: str = ""
    accepted_at: str = ""
    checkpoint_ref: str = ""
    progress_observation: ProgressObservation | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> OperationRecord:
        payload = dict(raw)
        observation = payload.get("progress_observation")
        if isinstance(observation, dict):
            payload["progress_observation"] = ProgressObservation(**observation)
        elif observation is not None:
            raise TypeError("progress_observation must be an object or null")
        return cls(**payload)

    def update(self, phase: str, *, status: str | None = None, error: str = "", error_code: str = "") -> None:
        self.phase = phase
        if status is not None:
            self.status = status
        self.error = error
        self.error_code = error_code
        self.updated_at = operation_created_at()
        if status in {"succeeded", "failed", "partial", "interrupted"}:
            self.finished_at = self.updated_at

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExecutionControlRecord:
    run_id: str
    execution_id: str
    scope: str
    owner_pid: int
    phase: str = "running"
    dispatch_paused: bool = False
    task_id: str = ""
    task_title: str = ""
    action: str = ""
    attempt_id: str = ""
    invocation_id: str = ""
    stop_request_id: str = ""
    active_targets: dict[str, dict[str, str]] = field(default_factory=dict)
    started_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WorkTask:
    id: str
    title: str
    capabilities: list[str]
    description: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    expected_paths: list[str] = field(default_factory=list)
    forbidden_paths: list[str] = field(default_factory=list)
    verify_commands: list[list[str]] = field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    readiness: TaskReadiness = TaskReadiness.READY
    blocked_by: list[str] = field(default_factory=list)
    agent_id: str = ""
    provider_id: str = ""
    model: str = ""
    reasoning_effort: str = ""
    profile_source: ProfileSource = ProfileSource.LEGACY
    effort_baseline_reasoning: str | None = None
    effective_model: str = ""
    effective_reasoning_effort: str = ""
    reviewer_agent_id: str = ""
    reviewer_provider_id: str = ""
    reviewer_model: str = ""
    review_policy_added: bool = False
    routing_reason: str = ""
    routing_confidence: float = 0.0
    model_selection_reason: str = ""
    model_escalation_policy_id: str = ""
    model_escalation_result_index: int = -1
    status: TaskStatus = TaskStatus.PENDING
    review_status: ReviewStatus = ReviewStatus.NOT_REQUIRED
    review_cycles: int = 0
    review_summary: str = ""
    review_findings: list[str] = field(default_factory=list)
    last_review_commit: str = ""
    branch: str = ""
    worktree: str = ""
    started_commit: str = ""
    completed_commit: str = ""
    prompt_path: str = ""
    log_path: str = ""
    error: str = ""
    active_action: TaskAction | None = None
    failed_action: TaskAction | None = None
    attempt_count: int = 0
    last_attempt_id: str = ""
    last_attempt_started_at: str = ""
    last_attempt_finished_at: str = ""
    active_invocation_id: str = ""
    stop_request_id: str = ""
    stopped_at: str = ""
    progress_phase: str = ""
    progress_detail: str = ""
    progress_updated_at: str = ""
    progress_observation: ProgressObservation | None = None
    is_prerequisite: bool = False
    conflict_dependencies: list[str] = field(default_factory=list)
    conflict_group: list[str] = field(default_factory=list)
    action_results: list[TaskActionResult] = field(default_factory=list)
    result_history: list[TaskResultRecord] = field(default_factory=list)
    implementation_notes: list[str] = field(default_factory=list)

    @property
    def execution_dependencies(self) -> list[str]:
        return list(dict.fromkeys([*self.dependencies, *self.conflict_dependencies]))

    def begin_action(self, action: TaskAction, *, count_attempt: bool = True, attempt_id: str = "", invocation_id: str = "") -> None:
        self.active_action = action
        self.failed_action = None
        if count_attempt:
            self.attempt_count += 1
        self.last_attempt_id = attempt_id
        self.active_invocation_id = invocation_id
        self.stop_request_id = ""
        self.stopped_at = ""
        self.last_attempt_started_at = utc_now()
        self.last_attempt_finished_at = ""
        self.error = ""
        self.clear_progress()
        if action in {TaskAction.EXECUTE, TaskAction.REVISE}:
            self.clear_effective_profile()

    def set_effective_profile(self, model: str, reasoning_effort: str) -> None:
        self.effective_model = model
        self.effective_reasoning_effort = reasoning_effort

    def clear_effective_profile(self) -> None:
        self.effective_model = ""
        self.effective_reasoning_effort = ""

    def update_progress(self, phase: str, detail: str = "") -> None:
        self.progress_phase = phase
        self.progress_detail = detail
        self.progress_updated_at = utc_now()

    def clear_progress(self, *, reset_observation: bool = True) -> None:
        self.progress_phase = ""
        self.progress_detail = ""
        self.progress_updated_at = ""
        if reset_observation:
            self.progress_observation = None

    def complete_action(self, action: TaskAction) -> None:
        if self.active_action == action:
            self.active_action = None
        self.failed_action = None
        self.last_attempt_finished_at = utc_now()
        self.active_invocation_id = ""
        self.clear_progress(reset_observation=False)

    def fail_action(self, action: TaskAction, message: str) -> None:
        self.active_action = None
        self.failed_action = action
        self.last_attempt_finished_at = utc_now()
        self.active_invocation_id = ""
        self.error = message
        self.clear_progress(reset_observation=False)

    def stop_action(self, action: TaskAction, request_id: str) -> None:
        self.active_action = None
        self.failed_action = action
        self.status = TaskStatus.STOPPED
        self.stop_request_id = request_id
        self.stopped_at = utc_now()
        self.last_attempt_finished_at = self.stopped_at
        self.active_invocation_id = ""
        self.error = ""
        self.clear_progress(reset_observation=False)


@dataclass(frozen=True, slots=True)
class UserCheck:
    id: str
    title: str
    instructions: str
    acceptance_criteria: tuple[str, ...]
    after_task_id: str = ""
    blocks_task_ids: tuple[str, ...] = ()
    required_for_integration: bool = False


@dataclass(frozen=True, slots=True)
class UserCheckResult:
    reference_commit: str
    outcome: UserCheckOutcome
    note: str
    recorded_at: str


@dataclass(frozen=True, slots=True)
class ProviderChoice:
    provider_id: str
    agent_id: str
    model: str = ""
    is_default: bool = False
    max_tasks: int = 1


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    id: str
    available: bool
    executable: str
    agent_ids: tuple[str, ...]
    authenticated: bool | None = None
    auth_method: str = ""
    auth_label: str = ""


@dataclass(frozen=True, slots=True)
class RunLockStatus:
    run_id: str
    state: RunLockState
    operation: str = ""
    pid: int | None = None
    host: str = ""
    acquired_at: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RunExecutionControl:
    situation: RunExecutionSituation
    action: RunExecutionAction
    reason: str
    lock_state: RunLockState
    operation: str = ""
    active_task_id: str = ""
    active_task_title: str = ""
    execution_id: str = ""
    active_attempt_id: str = ""
    active_invocation_id: str = ""
    can_stop: bool = False
    stop_scope: str = ""
    stop_request_id: str = ""
    stop_phase: str = ""
    dispatch_paused: bool = False
    checked_at: str = field(default_factory=utc_now)
