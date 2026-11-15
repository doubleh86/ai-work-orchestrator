"""Public execution APIs; Pipeline owns approvals, policy bindings and run locks."""

from .batch import TaskBatchExecutor
from .dispatch import DispatchRecords, TaskDispatcher
from .preparation import TaskWorkspacePreparation, TaskExecutionRecords, TaskExecutionPreparation
from .scheduling import deferred_execution_task_ids, waiting_for_user_checks, ready_tasks, commit_queue_tasks
from .provider_runner import (
    AGENT_OUTPUT_DRAIN_TIMEOUT_SECONDS,
    AGENT_TERMINATION_TIMEOUT_SECONDS,
    CODEX_INPUT_LIMIT_CHARACTERS,
    ProviderInputLimitError,
    ProviderRequestLimited,
    ProviderRunError,
    ProviderRunner,
    ProviderRuntimeOptions,
    ProviderTimedOut,
    ProviderUnavailable,
)
from .verification_runner import (
    DOTNET_BUILD_OUTPUT_ACCESS_ERROR,
    INTEGRATION_VERIFICATION_COMMAND_TIMEOUT_SECONDS,
    VerificationCommandError,
    VerificationRunError,
    VerificationRunner,
    VerificationRuntimeOptions,
)
from .task_verification import (
    TaskVerificationFailed,
    TaskVerificationRunner,
    TaskVerificationRuntimeOptions,
    TaskVerificationTimedOut,
)
from .review import REVIEW_MARKER, ReviewProtocolError, ReviewRequest, parse_review, render_review_prompt, render_revision_prompt
from .recovery import (
    AutomaticRecoveryDecision,
    automatic_recovery_decision,
    recovery_timeout_limits,
    timeout_retry_context,
    verification_failure_fingerprint,
    verification_failure_is_repairable,
    verification_timed_out,
)
from .task_prompts import (
    TASK_EXECUTION_EFFICIENCY_GUIDANCE, TASK_WORKTREE_CONTRACT, BootstrapInstructionSnapshot, TaskPromptRequest,
    render_automatic_correction_prompt, render_retry_instruction, render_task_attempt_prompt, render_task_prompt,
    with_effort_mode_guidance, with_project_dotnet_guidance, with_task_execution_efficiency_guidance, with_task_worktree_contract,
)

from .errors import TaskVerificationFailure, TaskVerificationTimeout
from .results import brief_worker_report, committed_result_files, record_task_result
from .task_attempts import TaskAttemptRunner, TaskReviewCycles
from .task_runner import TaskRecoveryRunner

from .task_actions import TaskActionRunner
from .task_evidence import (
    TaskScopeInspector, scope_contract_digest, scope_path_matches, task_scope_review, scope_review_paths_allowed, refresh_task_code_style_evidence,
)
from .verification_evidence import TaskCancellation, TaskVerificationService

from .lifecycle import ExecutionControlRecords, ExecutionControlService, make_stop_operation
from .task_activity import TaskActivityRecorder, infer_task_action, mark_task_interrupted, collect_interrupted_tasks

from .profiles import (
    TaskProfileValidator, task_execution_profile_snapshot, assign_next_execution_profile,
    normalize_agent_id, normalize_model, normalize_reasoning_effort, validate_reasoning_effort, validate_task_profile_override_targets,
)
from .profile_requests import TaskProfileRecords, TaskProfileService

from .quota import QuotaFallbackService, apply_quota_profile, quota_fallback_matches

from .model_escalation import AutomaticModelEscalation, automatic_model_escalation_matches

from .policy_snapshot import ExecutionPolicyValidator, build_execution_policy_snapshot

from .effort_preview import EffortPreviewBuilder

from .effort_plan import EffortPlanApplicator, EffortPlanChange

from .effort_queries import EffortQueries, EffortQueryRecords, effort_state_key, effort_reservation_allowed

from .provider_choices import ProviderChoiceQueries, connected_provider_ids

from .provider_status import ProviderStatusQueries

from .verification_repair import VerificationRepairRunner, VerificationRepairProposal, VerificationRepairRecords, VerificationRepairWorkflow
from .claude_connection import claude_connection_details, unknown_claude_connection

from .retry_guidance import RetryGuidanceRecords, TaskRetryGuidance, retry_task_contract_digest

from .project_chat import (
    ProjectChatRecords, ProjectChatDecisionResult, ProjectChatAction,
)

__all__ = [
    "TaskExecutionRecords", "TaskExecutionPreparation",
    "ProjectChatAction",
    "ProjectChatRecords", "ProjectChatDecisionResult",
    "VerificationRepairRecords", "VerificationRepairWorkflow",
    "RetryGuidanceRecords", "TaskRetryGuidance", "retry_task_contract_digest",
    "VerificationRepairRunner", "VerificationRepairProposal", "claude_connection_details", "unknown_claude_connection",
    "ProviderStatusQueries",
    "ProviderChoiceQueries", "connected_provider_ids",
    "EffortQueries", "EffortQueryRecords", "effort_state_key", "effort_reservation_allowed",
    "EffortPlanApplicator", "EffortPlanChange",
    "EffortPreviewBuilder",
    "ExecutionPolicyValidator", "build_execution_policy_snapshot",
    "AutomaticModelEscalation", "automatic_model_escalation_matches",
    "QuotaFallbackService", "apply_quota_profile", "quota_fallback_matches",
    "TaskProfileValidator", "TaskProfileRecords", "TaskProfileService", "task_execution_profile_snapshot", "assign_next_execution_profile",
    "normalize_agent_id", "normalize_model", "normalize_reasoning_effort", "validate_reasoning_effort", "validate_task_profile_override_targets",
    "ExecutionControlRecords", "ExecutionControlService", "make_stop_operation", "TaskActivityRecorder",
    "infer_task_action", "mark_task_interrupted", "collect_interrupted_tasks",
    "TaskActionRunner", "TaskScopeInspector", "TaskVerificationService", "TaskCancellation",
    "scope_contract_digest", "scope_path_matches", "task_scope_review", "scope_review_paths_allowed", "refresh_task_code_style_evidence",
    "TaskRecoveryRunner", "TaskAttemptRunner", "TaskReviewCycles", "TaskVerificationFailure", "TaskVerificationTimeout",
    "brief_worker_report", "committed_result_files", "record_task_result",
    "DispatchRecords", "TaskDispatcher", "TaskBatchExecutor", "TaskWorkspacePreparation",
    "deferred_execution_task_ids", "waiting_for_user_checks", "ready_tasks", "commit_queue_tasks",
    "AGENT_OUTPUT_DRAIN_TIMEOUT_SECONDS", "AGENT_TERMINATION_TIMEOUT_SECONDS", "CODEX_INPUT_LIMIT_CHARACTERS",
    "ProviderInputLimitError", "ProviderRequestLimited", "ProviderRunError", "ProviderRunner", "ProviderRuntimeOptions",
    "ProviderTimedOut", "ProviderUnavailable",
    "DOTNET_BUILD_OUTPUT_ACCESS_ERROR", "INTEGRATION_VERIFICATION_COMMAND_TIMEOUT_SECONDS",
    "VerificationCommandError", "VerificationRunError", "VerificationRunner", "VerificationRuntimeOptions",
    "TaskVerificationFailed", "TaskVerificationRunner", "TaskVerificationRuntimeOptions", "TaskVerificationTimedOut",
    "REVIEW_MARKER", "ReviewProtocolError", "ReviewRequest", "parse_review", "render_review_prompt", "render_revision_prompt",
    "AutomaticRecoveryDecision", "automatic_recovery_decision", "recovery_timeout_limits", "timeout_retry_context",
    "verification_failure_fingerprint", "verification_failure_is_repairable", "verification_timed_out",
    "TASK_EXECUTION_EFFICIENCY_GUIDANCE", "TASK_WORKTREE_CONTRACT", "BootstrapInstructionSnapshot", "TaskPromptRequest",
    "render_automatic_correction_prompt", "render_retry_instruction", "render_task_attempt_prompt", "render_task_prompt",
    "with_effort_mode_guidance", "with_project_dotnet_guidance", "with_task_execution_efficiency_guidance", "with_task_worktree_contract",
]

from .invocation import InvocationUsageRecords, ProviderInvocation
