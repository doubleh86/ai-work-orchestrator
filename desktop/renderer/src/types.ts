export type UsageCoverage = "complete" | "partial" | "unavailable";

export interface NextStepWaitingPrompt {
  source_key: string;
  kind: "retry" | "resume" | "verification" | "main_review";
  action: "retry" | "resume" | "verify" | "operations";
  task_id: string;
  question: string;
  remaining_count: number;
  next_task_id: string;
  next_task_title: string;
}

export interface TokenCounts {
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  cached_input_tokens: number | null;
  cache_write_input_tokens: number | null;
  reasoning_output_tokens: number | null;
}

export interface UsageSummary extends TokenCounts {
  field_coverage: Record<keyof TokenCounts, number>;
  call_count: number;
  reported_call_count: number;
  complete_call_count: number;
  running_call_count: number;
  coverage: UsageCoverage;
  latest_observed_at: string;
}

export interface UsageRecord extends TokenCounts {
  invocation_id: string;
  execution_request_id: string;
  operation_request_id: string;
  policy_id: string;
  task_id: string;
  attempt_id: string;
  purpose: string;
  provider: string;
  model_requested: string;
  model_effective: string;
  mode: EffortMode | null;
  thread_id: string;
  turn_id: string;
  source_revision: number;
  usage_epoch: string;
  source_kind: "unavailable" | "thread_delta" | "turn_total";
  missing_reason: string;
  created_at: string;
  observed_at: string;
  outcome: "running" | "completed" | "failed" | "cancelled" | "interrupted";
  finalized: boolean;
  coverage: UsageCoverage;
}

export interface TaskUsageSummary extends UsageSummary {
  task_id: string;
  by_purpose: (UsageSummary & { key: string })[];
  attempts: (UsageSummary & { attempt_id: string; by_purpose: (UsageSummary & { key: string })[];
    profiles: { provider: string; model_requested: string; model_effective: string }[] })[];
}

export interface UsageSnapshot {
  history_scope: "recorded_calls";
  recording_started_at: string;
  summary: UsageSummary;
  by_mode: (UsageSummary & { key: string })[];
  by_purpose: (UsageSummary & { key: string })[];
  task_summaries?: TaskUsageSummary[];
  execution_request_id: string;
  execution_requests: string[];
  execution_summary: UsageSummary;
  execution_is_active: boolean;
  records: UsageRecord[];
  next_cursor: string;
}

export interface RegisteredProject {
  name: string;
  repo: string;
  config_path: string;
  created_at: string;
  planning_source_dir: string | null;
  dotnet_executable: string;
  code_style_preference: ProjectCodeStylePreference;
  code_style_preference_revision: number;
}

export type GitReadinessKind =
  | "ready"
  | "unborn"
  | "not_initialized"
  | "inside_other_repository"
  | "git_unavailable"
  | "invalid";

export interface GitRepositoryReadiness {
  kind: GitReadinessKind;
  selected_path: string;
  repository_root: string;
  main_branch: string;
  head_commit: string;
  remote_configured: boolean;
  author_configured: boolean;
  diagnostics: string[];
}

export interface GitInitializationPreview {
  selected_path: string;
  branch: string;
  exclude_paths: string[];
  creates_repository: boolean;
  changes_remote: boolean;
}

export interface GitInitialCommitFile {
  path: string;
  status: string;
  staged: boolean;
  selected_by_default: boolean;
  exclusion_reason: string;
}

export interface GitInitialCommitPreview {
  snapshot_id: string;
  readiness: GitRepositoryReadiness;
  changes: GitInitialCommitFile[];
  author_name: string;
  author_email: string;
}

export type CodeStylePreferenceMode = "repository_first" | "repository_only";
export type CodeStyleProfileStatus = "detected" | "partial" | "unspecified" | "conflict" | "unavailable";

export interface ProjectCodeStylePreference {
  mode: CodeStylePreferenceMode;
  fallback_by_language: Record<string, string>;
  custom_instruction_paths: string[];
}

export interface CodeStyleRule {
  language: string;
  standard_id: string;
  source_kind: "repository_instruction" | "editorconfig" | "tool_config" | "custom_instruction" | "fallback";
  source_path: string;
  precedence: number;
  content_digest: string;
}

export interface CodeStyleCheck {
  language: string;
  argv: string[];
  source_path: string;
  configured: boolean;
  last_result: "not_run" | "passed" | "failed" | "unavailable";
}

export interface CodeStyleDiagnostic {
  code: string;
  message: string;
  source_path: string;
}

export interface ProjectCodeStyleProfile {
  status: CodeStyleProfileStatus;
  preference_revision: number;
  preference: ProjectCodeStylePreference;
  detected_languages: string[];
  rules: CodeStyleRule[];
  checks: CodeStyleCheck[];
  diagnostics: CodeStyleDiagnostic[];
  detected_at: string;
}

export interface CodeStyleSnapshot {
  preference_revision: number;
  status: CodeStyleProfileStatus;
  detected_languages: string[];
  rules: CodeStyleRule[];
  checks: CodeStyleCheck[];
  diagnostics: CodeStyleDiagnostic[];
  created_at: string;
}

export interface CodeStyleTaskEvidence {
  changed_paths: string[];
  applicable_rules: CodeStyleRule[];
  checks: CodeStyleCheck[];
  rules_changed: boolean;
  rule_changes: string[];
  diagnostics: CodeStyleDiagnostic[];
  created_at: string;
}

export interface ProjectCapabilities {
  deployment_configured: boolean;
  repository_maturity: RepositoryMaturityAssessment;
}

export type RepositoryMaturityKind = "existing_code" | "docs_only" | "ambiguous";

export interface RepositoryMaturityEvidence {
  relative_path: string;
  evidence_kind: "source" | "manifest" | "build" | "test" | "document" | "generated" | "unknown";
  stack_hints: string[];
}

export interface RepositoryMaturityAssessment {
  kind: RepositoryMaturityKind;
  evidence: RepositoryMaturityEvidence[];
  ignored_roots: string[];
  detected_application_roots: string[];
  diagnostics: string[];
  inspected_file_count: number;
  truncated: boolean;
}

export interface TechStackComponents {
  languages: string[];
  runtimes: string[];
  application_frameworks: string[];
  ui_frameworks: string[];
  persistence: string[];
  package_and_build_tools: string[];
  test_tools: string[];
  style_and_analysis: string[];
  packaging_and_deployment: string[];
}

export interface TechStackOption {
  option_id: string;
  label: string;
  recommendation_rank: number;
  components: TechStackComponents;
  version_policy: string[];
  requirement_fit: string[];
  tradeoffs: string[];
  unresolved_constraints: string[];
  required_external_dependencies: string[];
}

export interface TechStackDecision {
  decision_id: string;
  revision: number;
  status: "questions_required" | "options_ready" | "confirmed" | "superseded";
  project_root: string;
  requirement_sources: string[];
  answers: string[];
  options: TechStackOption[];
  selected_option_id: string;
  confirmed_at: string;
  confirmed_by: string;
  created_at: string;
}

export interface BootstrapPathState {
  relative_path: string;
  entry_kind: "file" | "directory" | "symlink";
  content_digest: string;
}

export interface BootstrapAgentInstructions {
  mode: "create_from_template" | "preserve_existing" | "skip_by_user";
  path: string;
  template_version: string;
  rendered_content: string;
  content_digest: string;
  task_path_injected: boolean;
  task_acceptance_injected: boolean;
}

export interface BootstrapSpec {
  decision_id: string;
  decision_revision: number;
  target_root: string;
  planned_paths: string[];
  steps: string[];
  required_tools: string[];
  verify_commands: string[][];
  excluded_external_actions: string[];
  path_snapshot: BootstrapPathState[];
  digest: string;
  agent_instructions?: BootstrapAgentInstructions | null;
  verified_integration_head: string;
  verified_at: string;
  feature_plan_attempts: number;
  feature_plan_error: string;
  created_at: string;
}

export interface DotnetDiagnostic {
  executable: string;
  log: string;
  error: string;
}

export interface WorkspaceLocation {
  root: string;
  source: "project_default" | "custom_legacy" | "legacy_record";
  layout_version: number;
  notice_code: string;
}

export interface ProjectWorkspaceLocation extends WorkspaceLocation {
  repo: string;
  created: boolean;
}

export interface RunEvent {
  at: string;
  kind: string;
  message: string;
}

export interface PlanningMessage {
  role: "user" | "assistant";
  text: string;
  at: string;
}

export interface PlanningApplyRequest {
  answer_message?: string;
  answer_conversation_revision?: number;
  tech_stack_revision?: number;
  request_id: string;
  conversation_revision: number;
  plan_revision: number;
  status: "queued" | "applying" | "succeeded" | "failed";
  created_at: string;
  completed_at: string;
  added_tasks: number;
  updated_tasks: number;
  excluded_tasks: number;
  unchanged_tasks: number;
  error_code: string;
  error: string;
}

export type PlanningMode = "directed" | "auto";

export interface TaskActionResult {
  action: string;
  verification_context_digest?: string;
  verification_failure_kind?: string;
  attempt_id?: string;
  invocation_id?: string;
  status: string;
  started_at: string;
  finished_at: string;
  worker_response: string;
  baseline_commit: string;
  result_commit: string;
  changed_paths: string[];
  passed_commands: string[][];
  code_style_evidence?: CodeStyleTaskEvidence | null;
  review_verdict: string;
  review_findings: string[];
  error: string;
}

export interface ResultFileChange {
  path: string;
  change: string;
}

export interface DirectionChangeRequest {
  request_id: string;
  text: string;
  task_id: string;
  task_title: string;
  status: "received" | "queued" | "reviewing" | "awaiting_confirmation" | "applied" | "blocked";
  next_step: string;
  preview_id: string;
  error: string;
  created_at: string;
  updated_at: string;
}

export interface TaskResultRecord {
  baseline_commit: string;
  result_commit: string;
  captured_at: string;
  files_state: "confirmed" | "none" | "unavailable";
  files: ResultFileChange[];
  error: string;
  self_report: string;
  verification_status: "passed" | "unverified";
  passed_commands: string[][];
  manual_verification_note?: string;
}

export interface GroupResultRecord {
  verification_attempt_id: string;
  main_commit: string;
  result_commit: string;
  captured_at: string;
  files_state: "confirmed" | "none" | "unavailable";
  files: ResultFileChange[];
  error: string;
}

export interface VerificationAttempt {
  id: string;
  status: string;
  started_at: string;
  finished_at: string;
  main_head: string;
  task_heads: Record<string, string>;
  integration_head: string;
  phase: string;
  current_command: string[];
  passed_commands: string[][];
  commit_queue_task_ids: string[];
  last_integrated_task_id: string;
  failed_task_id: string;
  failure_phase: string;
  failed_command: string[];
  candidate_task_ids: string[];
  attribution_reason: string;
  log_path: string;
  error: string;
  stop_reason: string;
  command_timeout_seconds: number;
  total_timeout_seconds: number;
  repair_count: number;
}

export interface PushReceipt {
  scope: "work_branch" | "main";
  remote: string;
  branch: string;
  local_commit: string;
  remote_commit: string;
  operation_request_id: string;
  pushed_at: string;
}

export interface ProgressObservation {
  attempt_id: string;
  invocation_id: string;
  turn_id: string;
  phase: string;
  detail: string;
  phase_started_at: string;
  last_event_received_at: string;
  last_activity_changed_at: string;
  event_seq: number;
  activity_seq: number;
  evidence_kind: string;
}

export interface WorkTask {
  model_selection_reason?: string;
  model_escalation_policy_id?: string;
  model_escalation_result_index?: number;
  profile_source?: "manual" | "mode" | "routing" | "legacy";
  attempt_count?: number;
  id: string;
  title: string;
  description: string;
  capabilities: string[];
  acceptance_criteria: string[];
  status: string;
  readiness: string;
  risk_level: string;
  blocked_by: string[];
  dependencies: string[];
  is_prerequisite: boolean;
  conflict_dependencies: string[];
  conflict_group: string[];
  action_results: TaskActionResult[];
  result_history: TaskResultRecord[];
  expected_paths: string[];
  forbidden_paths: string[];
  verify_commands: string[][];
  model: string;
  agent_id: string;
  provider_id: string;
  reasoning_effort: string;
  effective_model: string;
  effective_reasoning_effort: string;
  review_status: string;
  error: string;
  worktree: string;
  started_commit: string;
  completed_commit: string;
  progress_phase: string;
  progress_detail: string;
  progress_updated_at: string;
  progress_observation?: ProgressObservation | null;
  active_action?: string | null;
  failed_action?: string | null;
  last_attempt_id?: string;
  last_attempt_started_at?: string;
  last_attempt_finished_at?: string;
  active_invocation_id?: string;
  stop_request_id?: string;
  stopped_at?: string;
}

export type EffortMode = "economy" | "balanced" | "focused";

export interface EffortControl {
  policy_revision: number;
  plan_revision: number;
  stage: string;
  selected_mode: EffortMode | null;
  pending_execution_mode: EffortMode | null;
  pending_request_id: string;
  last_mutation: { request_id: string; action: string } | null;
  current_policy: { policy_id: string; mode: EffortMode; plan_revision: number } | null;
  planning_policy?: { policy_id: string; mode: EffortMode; planning_profile: EffortReasoning | null } | null;
  planning_request_status?: string;
  planning_request_started_at?: string;
  current_binding_status: string;
  requires_plan_review: boolean;
  manual_exception_count: number;
  can_select_plan: boolean;
  can_apply_plan: boolean;
  can_reserve: boolean;
  can_cancel_reservation: boolean;
  consistent: boolean;
  reason: string;
}

export interface EffortReasoning {
  selection_reason?: string;
  provider_id: string;
  model: string;
  reasoning_effort: string;
  profile_source: "manual" | "mode" | "routing" | "legacy";
}

export interface EffortModePreview {
  mode: EffortMode;
  policy_revision: number;
  plan_revision: number;
  planning_reasoning: EffortReasoning | null;
  tasks: {
    task_id: string;
    current_reasoning_effort: string;
    reasoning: EffortReasoning;
    current_reviewer_agent_id: string;
    review: { required: boolean; policy_added: boolean; policy_removed: boolean; requires_reviewer: boolean };
    reviewer_options: { agent_id: string; provider_id: string; model: string }[];
  }[];
  manual_exception_ids: string[];
  unsupported_effects: string[];
  requires_plan_review: boolean;
  can_apply: boolean;
}

export type UserCheckOutcome = "passed" | "failed" | "deferred";

export interface PlannedUserCheck {
  check_id: string;
  title: string;
  instructions: string;
  acceptance_criteria: string[];
  after_task_id: string;
  blocks_task_ids: string[];
  required_for_integration: boolean;
  status: "pending" | "waiting" | UserCheckOutcome;
  reference_commit: string | null;
  recorded_at: string | null;
  note: string;
}

export interface RunState {
  planned_user_checks?: PlannedUserCheck[];
  user_check_blocked_task_ids?: string[];
  project_chat_available?: boolean;
  tech_stack_confirmation_allowed?: boolean;
  id: string;
  summary: string;
  stage: string;
  updated_at: string;
  created_at: string;
  base_commit: string;
  repo_path: string;
  workspace_mode: "isolated" | "shared";
  workspace_location?: WorkspaceLocation | null;
  execution_branch: string;
  execution_worktree: string;
  pushed_work_branch_head: string;
  push_receipts: PushReceipt[];
  spec_path: string;
  main_branch: string;
  planning_agent_id: string;
  planning_model: string;
  planning_provider_id: string;
  planning_reasoning_effort: string;
  planning_mode: PlanningMode;
  planning_request: string;
  external_plan_digest?: string;
  revision_source_run_id?: string;
  revision_request_id?: string;
  revision_request_text?: string;
  revision_source_task_ids?: string[];
  revision_source_paths?: string[];
  planning_attempts: number;
  failure_message: string;
  active_step: string | null;
  failed_step: string | null;
  verification_progress_phase: string;
  verification_progress_detail: string;
  verification_progress_current: number;
  verification_progress_total: number;
  verification_started_at: string;
  verification_progress_updated_at: string;
  verification_attempts: VerificationAttempt[];
  group_result_history: GroupResultRecord[];
  verified_main_head: string;
  verified_integration_head: string;
  verification_policy_version: number;
  task_verify_command_timeout_seconds: number;
  task_verify_total_timeout_seconds: number;
  integration_verify_command_timeout_seconds: number;
  integration_verify_total_timeout_seconds: number;
  verification_repair_limit: number;
  verification_repair_count: number;
  verification_repair_head: string;
  verification_repair_main_head: string;
  verification_repair_task_heads: Record<string, string>;
  planning_questions: string[];
  planning_messages: PlanningMessage[];
  planning_follow_up_requests: string[];
  planning_conversation_revision: number;
  planning_applied_conversation_revision: number;
  planning_apply_requests: PlanningApplyRequest[];
  direction_change_requests?: DirectionChangeRequest[];
  repository_maturity?: RepositoryMaturityAssessment | null;
  code_style_snapshot?: CodeStyleSnapshot | null;
  repository_intent?: "" | "existing_structure" | "new_project";
  greenfield_phase?: "" | "stack_decision_required" | "questions_required" | "options_ready" | "stack_confirmed" | "bootstrap_ready" | "bootstrap_running" | "bootstrap_verifying" | "feature_planning_ready" | "feature_planning" | "feature_plan_ready";
  tech_stack_decisions?: TechStackDecision[];
  bootstrap_spec?: BootstrapSpec | null;
  plan_revision: number;
  plan_approved_revision: number;
  execution_control?: RunExecutionControl;
  waiting_prompt?: NextStepWaitingPrompt | null;
  effort_control?: EffortControl;
  integration_control?: IntegrationControl;
  main_operations?: MainOperations;
  tasks: WorkTask[];
  events: RunEvent[];
  integration_conflict?: IntegrationConflict | null;
  recovery_tasks?: RecoveryTask[];
  archive?: RunArchive | null;
}

export interface ArchiveCleanupTarget {
  id: string;
  recorded_path: string;
  expected_head: string;
  status: string;
  error: string;
  archive_ref: string;
}

export interface RunArchive {
  archived_at: string;
  source_revision: string;
  snapshot_path: string;
  manifest_path: string;
  summary_path: string;
  fingerprint: string;
  cleanup_status: "pending" | "running" | "completed" | "partial" | "blocked";
  cleanup_request_id: string;
  cleanup_targets: ArchiveCleanupTarget[];
}

export interface PlanningApplyPreviewChange {
  task_id: string;
  title: string;
  kind: "added" | "modified" | "excluded" | "unchanged" | "review_required";
  fields: string[];
  reason?: string;
}

export interface PlanningPreviewOperation {
  kind: "planning_chat" | "preview_generation" | "preview_comparison" | "task_execute" | "task_review"
    | "task_verify" | "plan_apply" | "run_verify" | "run_operation";
  operation: string;
  started_at: string;
  stage_changed_at: string;
  last_activity_at: string;
  task_id: string;
  task_title: string;
}

export interface PlanningPreviewStatus {
  phase: "idle" | "chat" | "generating" | "comparing" | "ready" | "applied" | "failed" | "check_required" | "interrupted";
  preview: PlanningApplyPreview | null;
  request_id: string;
  last_activity_at: string;
  checked_at: string;
  error: string;
  lock_state: string;
  can_generate: boolean;
  work_state: "idle" | "active" | "unknown" | "interrupted";
  active_operations: PlanningPreviewOperation[];
  can_apply: boolean;
}

export interface TaskRetryContext {
  recovery?: {
    kind: "repair" | "verify_with_timeout_adjustment" | "verify" | "diagnose" | "unavailable";
    can_execute: boolean; reason_code: string; current_limits: number[]; proposed_limits: number[];
    will_change: boolean; history_known: boolean; fingerprint: string; changed_factors: string[];
  };
  task_id: string;
  plan_revision: number;
  attempt_id: string;
  title: string;
  error: string;
  response: string;
  acceptance_criteria: string[];
  fingerprint: string;
  can_save: boolean;
  reason: string;
  instruction: ResultRevisionRequest | null;
  instruction_current: boolean;
}

export interface PlanningApplyPreview {
  preview_id: string;
  request_id: string;
  run_id: string;
  run_title: string;
  created_at: string;
  plan_revision: number;
  conversation_revision: number;
  fingerprint: string;
  candidate_digest: string;
  changes: PlanningApplyPreviewChange[];
  can_apply: boolean;
  apply_after: string;
  dependency_impact: boolean;
  verification_impact: boolean;
  completed_task_rerun: boolean;
  completed_task_review: boolean;
  direction_request_ids?: string[];
  status: "preview" | "applied";
  stale: boolean;
  actual?: { added: number; modified: number; excluded: number; unchanged: number };
}

export interface ResultRevisionRequest {
  request_id: string;
  text: string;
  task_ids: string[];
  paths: string[];
  target_run_id: string;
  created_at: string;
  handling?: "planning" | "same_task_retry";
  proposal_id?: string;
  proposal_summary?: string;
}

export interface ResultRevisionProposal {
  proposal_id: string;
  fingerprint: string;
  text: string;
  focus_task_id: string;
  status: "generating" | "ready" | "needs_clarification" | "failed";
  summary: string;
  reason: string;
  task_ids: string[];
  paths: string[];
  question: string;
  next_action: "retry_task" | "same_group_plan" | "linked_group" | "recovery" | "";
  error: string;
  created_at: string;
  stale: boolean;
}

export interface ResultRevisionLinks {
  requests: ResultRevisionRequest[];
  proposals: ResultRevisionProposal[];
  origin: RunSummary | null;
  children: RunSummary[];
}

export interface RunArchivePlan {
  run_id: string;
  expected_revision: string;
  fingerprint: string;
  can_archive: boolean;
  block_reasons: string[];
  archived: boolean;
  archive: RunArchive | null;
  cleanup_targets: ArchiveCleanupTarget[];
  record_path: string;
  preserved_records: string[];
}

export interface IntegrationConflictFile {
  path: string;
  kind: string;
  base_blob: string;
  work_blob: string;
  main_blob: string;
  base_mode: string;
  work_mode: string;
  main_mode: string;
  binary: boolean;
  supported: boolean;
}

export interface ConflictResolutionCandidate {
  id: string;
  request_id: string;
  revision: number;
  status: string;
  worktree: string;
  commit: string;
  changed_paths: string[];
  content_digest: string;
  summary: string;
  error: string;
  created_at: string;
  applied_at: string;
  apply_request_id: string;
}

export interface IntegrationConflict {
  id: string;
  verification_attempt_id: string;
  main_head: string;
  work_head: string;
  merge_base_heads: string[];
  files: IntegrationConflictFile[];
  fingerprint: string;
  detected_at: string;
  abort_status: string;
  abort_error: string;
  resolution_status: string;
  candidate: ConflictResolutionCandidate | null;
  error: string;
}

export interface RecoveryTask {
  id: string;
  kind: "conflict_resolution" | string;
  source_key: string;
  title: string;
  conflict: IntegrationConflict;
  operation_request_ids: string[];
  verification_attempt_ids: string[];
  created_at: string;
  superseded_by: string;
}

export interface ConflictOperationAttempt {
  request_id: string;
  action: string;
  status: string;
  phase: string;
  error: string;
  created_at?: string;
  updated_at?: string;
  result_commit?: string;
  progress_observation?: ProgressObservation | null;
  log: string;
}

export interface IntegrationConflictDetail {
  conflict: IntegrationConflict;
  recovery_task?: RecoveryTask | null;
  attempts?: ConflictOperationAttempt[];
  selected_file: null | {
    path: string;
    kind: string;
    base: string;
    work: string;
    main: string;
    candidate: string;
    candidate_state?: "not_generated" | "generating" | "ready" | "missing" | "read_failed";
    candidate_error?: string;
  };
  can_prepare: boolean;
  can_apply: boolean;
  prepare_block_reason?: string;
  apply_block_reason?: string;
}

export type RunExecutionSituation =
  | "ready"
  | "running"
  | "preparing"
  | "resumable"
  | "waiting_user_check"
  | "attention_required"
  | "tasks_complete"
  | "status_unknown"
  | "unavailable";

export type RunExecutionAction = "execute" | "resume" | "none";

export interface RunExecutionControl {
  situation: RunExecutionSituation;
  action: RunExecutionAction;
  reason: string;
  lock_state: string;
  operation: string;
  active_task_id: string;
  active_task_title: string;
  execution_id: string;
  active_attempt_id: string;
  active_invocation_id: string;
  can_stop: boolean;
  stop_scope: string;
  stop_request_id: string;
  stop_phase: string;
  dispatch_paused: boolean;
  checked_at: string;
}

export type IntegrationStatus =
  | "not_ready"
  | "needs_verification"
  | "verifying"
  | "verified"
  | "stale"
  | "conflict"
  | "apply_blocked"
  | "main_push_pending"
  | "applied"
  | "unknown";

export interface IntegrationControl {
  status: IntegrationStatus;
  reason: string;
  reason_code: string;
  can_verify: boolean;
  can_apply_main: boolean;
  can_recover_main_apply?: boolean;
  main_dirty: boolean | null;
  verified_main_head: string;
  current_main_head: string;
  verified_integration_head: string;
  current_integration_head: string;
  remote_configured: boolean;
  checked_at: string;
}

export interface MainOperation {
  phase: string;
  status: string;
  error: string;
  updated_at: string;
}

export interface MainOperations {
  merge: MainOperation | null;
  push: MainOperation | null;
  retry_main_push: MainOperation | null;
}

export interface RunSummary {
  id: string;
  summary: string;
  stage: string;
  updated_at: string;
  created_at: string;
  task_count: number;
  completed_task_count: number;
  archived: boolean;
  archived_at: string;
  cleanup_status: string;
  failed_task_count: number;
  waiting_task_count: number;
  plan_is_approved: boolean;
  attention_reasons: string[];
  execution_situation: string;
  pipeline_complete: boolean;
  checked_at: string;
}

export interface ActiveGroupSummary {
  project_name: string;
  run_id: string;
  title: string;
  stage: string;
  completed_task_count: number;
  task_count: number;
  status: "active" | "check_required";
  activity_kinds: string[];
  last_activity_at: string;
  checked_at: string;
  stale?: boolean;
}

export interface ActiveGroupSnapshot {
  items: ActiveGroupSummary[];
  errors: { project_name: string; error: string; checked_at: string }[];
  checked_at: string;
}

export interface AttentionItem {
  project_name: string;
  run_id: string;
  run_title: string;
  stage: string;
  kind: string;
  title: string;
  reason: string;
  view: "tasks" | "planning" | "operations";
  task_id: string;
  status: "actionable" | "check_required";
  updated_at: string;
  checked_at: string;
  stale?: boolean;
}

export interface AttentionSnapshot {
  items: AttentionItem[];
  errors: { project_name: string; error: string; checked_at: string }[];
  checked_at: string;
}

export interface ProviderProfile {
  provider_id: string;
  agent_id: string;
  model: string;
  configured_model: string;
  reasoning_efforts: string[];
  is_default: boolean;
  max_tasks: number;
}

export interface ProviderStatus {
  id: string;
  available: boolean;
  executable: string;
  agent_ids: string[];
  authenticated: boolean | null;
  auth_method: string;
  auth_label: string;
}

export interface WorkspaceStatus {
  run_id: string;
  task_id: string;
  state: string;
  run_stage?: string;
  branch: string;
  worktree: string;
  cleanup_safe: boolean;
  reason: string;
}

export interface RunLockStatus {
  run_id: string;
  state: string;
  operation: string;
  reason: string;
}

export interface RepositoryUpdate {
  before_commit: string;
  after_commit: string;
  branch: string;
  remote: string;
  changed?: boolean;
  remaining_change_count: number;
  sync: MainSyncStatus | null;
}

export type MainChangeSelectionMode = "staged" | "whole";

export interface MainChangeItem {
  path: string;
  status: string;
  staged: boolean;
  unstaged: boolean;
  staged_status: string;
  unstaged_status: string;
  original_path: string;
}

export interface MainSyncStatus {
  local_head: string;
  remote_head: string;
  remote: string;
  target_branch: string;
  relation: "equal" | "ahead" | "behind" | "diverged" | "unknown";
  ahead: number | null;
  behind: number | null;
  checked_at: string;
  error: string;
}

export interface MainChangeSnapshot {
  snapshot_id: string;
  repo_path: string;
  branch: string;
  expected_branch: string;
  changes: MainChangeItem[];
  excluded_count: number;
  sync: MainSyncStatus;
  blocked_reason: string;
}

export interface MainChangeDiff {
  snapshot_id: string;
  path: string;
  mode: MainChangeSelectionMode;
  content: string;
  binary: boolean;
  truncated: boolean;
}

export interface MainMutationResult {
  phase: "commit_completed" | "push_completed" | "push_failed";
  commit: string;
  commit_created: boolean;
  pushed: boolean;
  remaining_change_count: number;
  snapshot: MainChangeSnapshot;
  error: string;
}

export interface PlanningSourceIndex {
  source_root: string;
  generated_at: string;
  document_count: number;
  reused_count: number;
  updated_count: number;
  added_count: number;
  modified_count: number;
  deleted_count: number;
}

export interface TaskProfileSelection {
  agentId: string;
  model: string;
  reasoningEffort: string;
}
