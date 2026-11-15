"""Git integration queries, selected Main changes and workspace lifecycles."""

from .candidates import ConflictCandidateBuilder, ConflictResolutionProfile, candidate_content_digest
from .resolution import ConflictResolutionRecords, ConflictResolutionService
from .conflicts import (
    ConflictInspector,
    conflict_apply_block_reason,
    conflict_prepare_block_reason,
    conflict_request_id,
    conflict_resolution_prompt,
    integration_conflict_fingerprint,
    require_integration_conflict,
)
from .inspection import (
    IntegrationInspector,
)
from .layout import (
    WorkspaceLayout,
    integration_branch_name,
    shared_run_branch_name,
    uses_shared_workspace,
    workspace_is_integrated,
)
from .lifecycle import (
    WorkspaceLifecycle,
)
from .main_changes import (
    MainChangeService,
)
from .main_review import (
    main_apply_review,
)
from .workspaces import (
    WORKSPACE_STATUS_TIMEOUT_SECONDS,
    WorkspaceInspector,
)

from .recovery import RecoveryRecords, RecoveryWorkflow, recovery_operation_digest, raise_existing_recovery_operation

from .verification import CandidateVerification, VerifiedCandidate

__all__ = [
    "CandidateVerification", "VerifiedCandidate",
    "RecoveryRecords", "RecoveryWorkflow", "recovery_operation_digest", "raise_existing_recovery_operation",
    "ConflictCandidateBuilder", "ConflictResolutionProfile", "ConflictResolutionRecords",
    "ConflictResolutionService", "candidate_content_digest",
    "ConflictInspector",
    "IntegrationInspector",
    "MainChangeService",
    "WORKSPACE_STATUS_TIMEOUT_SECONDS",
    "WorkspaceInspector",
    "WorkspaceLayout",
    "WorkspaceLifecycle",
    "conflict_apply_block_reason",
    "conflict_prepare_block_reason",
    "conflict_request_id",
    "conflict_resolution_prompt",
    "integration_branch_name",
    "integration_conflict_fingerprint",
    "main_apply_review",
    "require_integration_conflict",
    "shared_run_branch_name",
    "uses_shared_workspace",
    "workspace_is_integrated",
]
