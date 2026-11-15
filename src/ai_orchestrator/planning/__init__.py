"""Planning contracts and pure rules; runtime uses explicit submodules."""

from .contracts import CAPABILITY_ALIASES, PLAN_MARKER, TASK_ID, Plan, PlanningError, PlanningSourceDocument
from .prompts import (
    execution_profile_guidance, planning_prompt, render_planning_attempt_prompt, render_planning_chat_prompt,
    technology_stack_plan_example,
)
from .protocol import parse_structured_plan, structured_plan_dict, validate_relative_paths
from .validation import (
    task_path_matches, task_paths_may_overlap, validate_task_graph, validate_user_checks,
    validate_plan_document_references, validate_planning_phase,
)
from .assignment import assign_agents, assign_plan_agents, assign_task_agent_overrides, select_agent_for_provider
from .changes import (
    RESULT_REVISION_PROPOSAL_MARKER, PlanDraftValidator, PendingTaskPlan, PlanningApplyRequests,
    merge_pending_task_plan, parse_result_revision_proposal,
)
from .preview import (
    PlanningPreviewRecords, PlanningPreviewWorkflow, planning_preview_operations, planning_task_editable,
    planning_preview_task_fields, validate_planning_preview_payload, planning_apply_request,
)

from .result_revisions import (
    ResultRevisionRecords, ResultRevisionWorkflow, result_revision_evidence, result_revision_available_paths, result_revision_context,
)

__all__ = [
    "ResultRevisionRecords", "ResultRevisionWorkflow", "result_revision_evidence", "result_revision_available_paths", "result_revision_context",
    "PlanningPreviewRecords", "PlanningPreviewWorkflow", "planning_task_editable", "planning_preview_task_fields",
    "validate_planning_preview_payload", "planning_apply_request",
    "RESULT_REVISION_PROPOSAL_MARKER", "PlanDraftValidator", "PendingTaskPlan", "PlanningApplyRequests",
    "merge_pending_task_plan", "parse_result_revision_proposal", "planning_preview_operations",
    "CAPABILITY_ALIASES", "PLAN_MARKER", "TASK_ID", "Plan", "PlanningError", "PlanningSourceDocument",
    "execution_profile_guidance", "planning_prompt", "render_planning_attempt_prompt", "render_planning_chat_prompt",
    "technology_stack_plan_example", "parse_structured_plan", "structured_plan_dict", "validate_relative_paths",
    "task_path_matches", "task_paths_may_overlap", "validate_task_graph", "validate_user_checks",
    "validate_plan_document_references", "validate_planning_phase",
    "assign_agents", "assign_plan_agents", "assign_task_agent_overrides", "select_agent_for_provider",
]
