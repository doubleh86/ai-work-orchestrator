from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def operation_created_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


CURRENT_STATE_SCHEMA_VERSION = 39


LEGACY_STATE_SCHEMA_VERSION = 1


class Stage(StrEnum):
    RECEIVED = "received"
    REVIEWED = "reviewed"
    NEEDS_CLARIFICATION = "needs_clarification"
    PLANNED = "planned"
    EXECUTING = "executing"
    READY_TO_MERGE = "ready_to_merge"
    VERIFIED = "verified"
    WORK_BRANCH_PUSHED = "work_branch_pushed"
    MERGED = "merged"
    PUSHED = "pushed"
    DEPLOYED = "deployed"
    FAILED = "failed"


class RunStep(StrEnum):
    PLANNING = "planning"
    TASK_PREPARATION = "task_preparation"
    AGENT_EXECUTION = "agent_execution"
    MANUAL_COMPLETION = "manual_completion"
    MERGE = "merge"
    VERIFY = "verify"
    PUSH = "push"
    DEPLOY = "deploy"


class PlanningMessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class PlanningMode(StrEnum):
    DIRECTED = "directed"
    AUTO = "auto"


class EffortMode(StrEnum):
    ECONOMY = "economy"
    BALANCED = "balanced"
    FOCUSED = "focused"


class ProfileSource(StrEnum):
    MANUAL = "manual"
    MODE = "mode"
    ROUTING = "routing"
    LEGACY = "legacy"


class RepositoryMaturityKind(StrEnum):
    EXISTING_CODE = "existing_code"
    DOCS_ONLY = "docs_only"
    AMBIGUOUS = "ambiguous"


class TechStackDecisionStatus(StrEnum):
    QUESTIONS_REQUIRED = "questions_required"
    OPTIONS_READY = "options_ready"
    CONFIRMED = "confirmed"
    SUPERSEDED = "superseded"


class PlanningApplyStatus(StrEnum):
    QUEUED = "queued"
    APPLYING = "applying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DirectionChangeStatus(StrEnum):
    RECEIVED = "received"
    QUEUED = "queued"
    REVIEWING = "reviewing"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    APPLIED = "applied"
    BLOCKED = "blocked"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    REVIEWING = "reviewing"
    REVISING = "revising"
    WAITING = "waiting"
    DEFERRED = "deferred"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    MERGED = "merged"


class TaskReadiness(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"
    ACTIVE = "active"
    DONE = "done"
    FAILED = "failed"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskAction(StrEnum):
    EXECUTE = "execute"
    REVIEW = "review"
    REVISE = "revise"
    VERIFY = "verify"


class ReviewStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    RUNNING = "running"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    FAILED = "failed"


class RunLockState(StrEnum):
    UNLOCKED = "unlocked"
    ACTIVE = "active"
    STALE = "stale"
    UNVERIFIABLE = "unverifiable"
    MALFORMED = "malformed"


class RunExecutionSituation(StrEnum):
    READY = "ready"
    RUNNING = "running"
    PREPARING = "preparing"
    RESUMABLE = "resumable"
    WAITING_USER_CHECK = "waiting_user_check"
    ATTENTION_REQUIRED = "attention_required"
    TASKS_COMPLETE = "tasks_complete"
    STATUS_UNKNOWN = "status_unknown"
    UNAVAILABLE = "unavailable"


class RunExecutionAction(StrEnum):
    EXECUTE = "execute"
    RESUME = "resume"
    NONE = "none"


class IntegrationStatus(StrEnum):
    NOT_READY = "not_ready"
    NEEDS_VERIFICATION = "needs_verification"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    STALE = "stale"
    CONFLICT = "conflict"
    APPLY_BLOCKED = "apply_blocked"
    MAIN_PUSH_PENDING = "main_push_pending"
    APPLIED = "applied"
    UNKNOWN = "unknown"


class WorkspaceState(StrEnum):
    NOT_PREPARED = "not_prepared"
    ACTIVE = "active"
    STALE = "stale"
    CLEANED = "cleaned"
    UNSAFE = "unsafe"


class ExecutionWorkspaceMode(StrEnum):
    ISOLATED = "isolated"
    SHARED = "shared"


class WorkspaceLocationSource(StrEnum):
    PROJECT_DEFAULT = "project_default"
    CUSTOM_LEGACY = "custom_legacy"
    LEGACY_RECORD = "legacy_record"


class ConflictResolutionStatus(StrEnum):
    UNRESOLVED = "unresolved"
    GENERATING = "generating"
    CANDIDATE_READY = "candidate_ready"
    APPLYING = "applying"
    APPLIED = "applied"
    NEEDS_DECISION = "needs_decision"
    FAILED = "failed"
    STALE = "stale"
    INTERRUPTED = "interrupted"
    WORKSPACE_RECOVERY_REQUIRED = "workspace_recovery_required"


class ArchiveCleanupStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    BLOCKED = "blocked"


@dataclass(slots=True)
class Event:
    at: str
    kind: str
    message: str


@dataclass(slots=True)
class UserNotificationEvent:
    event_id: str
    source_key: str
    project_key: str
    run_id: str
    run_title: str
    target_kind: str
    target_id: str
    kind: str
    occurred_at: str
    summary_code: str
    request_id: str = ""
    verification_attempt_id: str = ""
    related_targets: list[str] = field(default_factory=list)
    os_eligible: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class UserCheckOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    DEFERRED = "deferred"
