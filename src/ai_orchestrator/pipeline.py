"""Stable public entry points for composed orchestration commands."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor as ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Mapping, Sequence
from .account_usage import AccountUsage
from .code_style import ProjectCodeStylePreference
from .codex_sdk import CodexSdkManager
from .config import AgentConfig, Config
from .document_index import (
    DocumentIndexError as DocumentIndexError,
    PlanningSourceIndex,
    load_matching_planning_source_index as load_matching_planning_source_index,
    load_planning_source_index as load_planning_source_index,
    render_planning_source_index as render_planning_source_index,
)
from .effort_policy import EffortModePreview
from .errors import (
    ApprovalRequired as ApprovalRequired,
    VerificationInputsChanged as VerificationInputsChanged,
    PipelineError,
    ProviderTimeoutError,
    ProviderCapacityError,
    ProviderRequestLimitError,
)
from .execution import (
    TaskVerificationFailure,
    TaskVerificationTimeout,
    AGENT_OUTPUT_DRAIN_TIMEOUT_SECONDS,
    AGENT_TERMINATION_TIMEOUT_SECONDS,
    CODEX_INPUT_LIMIT_CHARACTERS,
    INTEGRATION_VERIFICATION_COMMAND_TIMEOUT_SECONDS,
    VerificationRunError as VerificationRunError,
    VerificationRuntimeOptions as VerificationRuntimeOptions,
    render_retry_instruction as render_retry_instruction,
    timeout_retry_context as timeout_retry_context,
)
from .execution.lifecycle import EXECUTION_RUN_LOCK_OPERATIONS as EXECUTION_RUN_LOCK_OPERATIONS
from .execution.provider_choices import NEW_SELECTION_EXCLUDED_PROVIDER_IDS as NEW_SELECTION_EXCLUDED_PROVIDER_IDS
from .execution.provider_connection import PROVIDER_AUTH_STATUS_TIMEOUT_SECONDS as PROVIDER_AUTH_STATUS_TIMEOUT_SECONDS
from .execution.task_workflows import TASK_AUTOMATIC_RECOVERY_LIMIT as TASK_AUTOMATIC_RECOVERY_LIMIT
from .execution_control import DispatchPaused as DispatchPaused
from .git import GitWorkspace, DotnetDiagnostic
from .integration.deletion import RUN_DELETION_TIMEOUT_SECONDS as RUN_DELETION_TIMEOUT_SECONDS
from .model_selection import automatic_claude_profile as automatic_claude_profile
from .models import (
    ArchiveCleanupStatus as ArchiveCleanupStatus,
    BootstrapSpec,
    DirectionChangeRequest as DirectionChangeRequest,
    GroupResultRecord as GroupResultRecord,
    EffortMode,
    EffortPolicyView,
    IntegrationControl,
    OperationRecord,
    MainChangeDiff,
    MainChangeSnapshot,
    MainMutationResult,
    PlanningMode,
    ProfileSource,
    ProviderChoice,
    ProviderStatus,
    PushReceipt as PushReceipt,
    RepositoryUpdate,
    RepositoryMaturityKind as RepositoryMaturityKind,
    RunDeletion,
    RunArchive as RunArchive,
    RunExecutionControl,
    RunLockStatus,
    RunState,
    RunSummary,
    TaskActionResult as TaskActionResult,
    TechStackDecision as TechStackDecision,
    UserCheck,
    UserCheckResult as UserCheckResult,
    WorkTask,
    WorkspaceStatus,
)
from .notifications import notification_events_for_state as notification_events_for_state
from .nvidia_agent import NVIDIA_SETUP as NVIDIA_SETUP, nvidia_command as nvidia_command
from .orchestration.providers import ProviderQueries
from .orchestration.queries import RunQueries, TASK_LOG_DISPLAY_LIMIT_BYTES as TASK_LOG_DISPLAY_LIMIT_BYTES
from .pipeline_bootstrap import build_pipeline_runtime
from .planner import (
    select_agent_for_provider as select_agent_for_provider,
    validate_user_checks as validate_user_checks,
    PLAN_MARKER as PLAN_MARKER,
    assign_plan_agents as assign_plan_agents,
    parse_structured_plan as parse_structured_plan,
)
from .planning import merge_pending_task_plan as merge_pending_task_plan
from .planning.bootstrap import BOOTSTRAP_AGENTS_ACCEPTANCE
from .planning.features import feature_plan_tasks as feature_plan_tasks
from .planning.preparation import DIRECTED_PLANNING_WITHOUT_SOURCE_DOCUMENT as DIRECTED_PLANNING_WITHOUT_SOURCE_DOCUMENT
from .project_chat import MAX_DECISIONS as MAX_DECISIONS, decision_prompt as decision_prompt, parse_decision as parse_decision
from .run_queries import user_checks
from .scope_consent import parse_scope_consent as parse_scope_consent, scope_consent_prompt as scope_consent_prompt
from .store import StateStore
from .task_scope_review import scope_approval_reply as scope_approval_reply
from .usage import UsageContext, UsageRecord as UsageRecord, usage_now as usage_now
from .worker_mcp import (
    WorkerMcpError as WorkerMcpError,
    check_mcp_connection as check_mcp_connection,
    configure_claude_mcp as configure_claude_mcp,
    worker_mcp_lease as worker_mcp_lease,
)


class Pipeline:
    def __init__(
        self,
        config: Config,
        *,
        codex_sdk: CodexSdkManager | None = None,
        dotnet_executable: str = "",
        code_style_preference: ProjectCodeStylePreference | None = None,
        code_style_preference_revision: int = 0,
        account_usage_reader: Callable[[str], AccountUsage] | None = None,
    ):
        self._common_runtime = build_pipeline_runtime(
            config, codex_sdk=codex_sdk, dotnet_executable=dotnet_executable,
            code_style_preference=code_style_preference, code_style_preference_revision=code_style_preference_revision,
            account_usage_reader=account_usage_reader,
        )
        self._resources = self._common_runtime.resources

    @property
    def config(self) -> Config:
        return self._resources.config

    @config.setter
    def config(self, value: Config) -> None:
        self._resources.config = value

    @property
    def repo(self) -> Path:
        return self._resources.repo

    @repo.setter
    def repo(self, value: Path) -> None:
        self._resources.repo = value

    @property
    def store(self) -> StateStore:
        return self._resources.store

    @store.setter
    def store(self, value: StateStore) -> None:
        self._resources.store = value

    @property
    def git(self) -> GitWorkspace:
        return self._resources.git

    @git.setter
    def git(self, value: GitWorkspace) -> None:
        self._resources.git = value

    @property
    def agents(self) -> dict[str, AgentConfig]:
        return self._resources.agents

    @agents.setter
    def agents(self, value: dict[str, AgentConfig]) -> None:
        self._resources.agents = value

    @property
    def dotnet_executable(self) -> str:
        return self._resources.dotnet_executable

    @dotnet_executable.setter
    def dotnet_executable(self, value: str) -> None:
        self._resources.dotnet_executable = value

    @property
    def code_style_preference(self) -> ProjectCodeStylePreference:
        return self._resources.code_style_preference

    @code_style_preference.setter
    def code_style_preference(self, value: ProjectCodeStylePreference) -> None:
        self._resources.code_style_preference = value

    @property
    def code_style_preference_revision(self) -> int:
        return self._resources.code_style_preference_revision

    @code_style_preference_revision.setter
    def code_style_preference_revision(self, value: int) -> None:
        self._resources.code_style_preference_revision = value

    @property
    def _codex_sdk(self) -> CodexSdkManager | None:
        return self._resources.codex_sdk

    @_codex_sdk.setter
    def _codex_sdk(self, value: CodexSdkManager | None) -> None:
        self._resources.codex_sdk = value

    @property
    def _nvidia_api_key(self) -> str | None:
        return self._resources.nvidia_api_key

    @_nvidia_api_key.setter
    def _nvidia_api_key(self, value: str | None) -> None:
        self._resources.nvidia_api_key = value

    @property
    def _claude_api_key(self) -> str | None:
        return self._resources.claude_api_key

    @_claude_api_key.setter
    def _claude_api_key(self, value: str | None) -> None:
        self._resources.claude_api_key = value

    @property
    def _nvidia_model_api_keys(self) -> Mapping[str, str]:
        return self._resources.nvidia_model_api_keys

    @_nvidia_model_api_keys.setter
    def _nvidia_model_api_keys(self, value: Mapping[str, str]) -> None:
        self._resources.nvidia_model_api_keys = value

    def request_stop(
        self,
        run_id: str,
        *,
        request_id: str,
        execution_id: str,
        scope: str,
        task_id: str = "",
        attempt_id: str = "",
        invocation_id: str = "",
        chat_message: str = "",
    ) -> OperationRecord:
        return self._common_runtime.execution.control.request_stop(
            run_id,
            request_id=request_id,
            execution_id=execution_id,
            scope=scope,
            task_id=task_id,
            attempt_id=attempt_id,
            invocation_id=invocation_id,
            chat_message=chat_message,
        )

    def external_planning_context(self) -> dict[str, object]:
        return self._common_runtime.planning.external_planning_context()

    def submit_external_plan(
        self, run_id: str, *, expected_base_commit: str, summary: str, requirements: str,
        task_drafts: list[dict[str, object]], server_work: bool = False, user_checks: tuple[UserCheck, ...] = (),
    ) -> RunState:
        return self._common_runtime.planning.submit_external_plan(
            run_id,
            expected_base_commit=expected_base_commit,
            summary=summary,
            requirements=requirements,
            task_drafts=task_drafts,
            server_work=server_work,
            user_checks=user_checks,
        )

    def start(
        self,
        spec_path: str | Path,
        *,
        planning_agent_id: str = "",
        planning_model: str = "",
        planning_reasoning_effort: str = "",
        planning_mode: PlanningMode | str = PlanningMode.AUTO,
        planning_request: str = "",
        effort_mode: EffortMode | str = EffortMode.BALANCED,
        planning_profile_source: ProfileSource | str | None = None,
    ) -> RunState:
        return self._common_runtime.planning.start(
            spec_path,
            planning_agent_id=planning_agent_id,
            planning_model=planning_model,
            planning_reasoning_effort=planning_reasoning_effort,
            planning_mode=planning_mode,
            planning_request=planning_request,
            effort_mode=effort_mode,
            planning_profile_source=planning_profile_source,
        )

    def prepare_planning(
        self,
        spec_path: str | Path,
        *,
        planning_agent_id: str = "",
        planning_model: str = "",
        planning_reasoning_effort: str = "",
        planning_mode: PlanningMode | str = PlanningMode.AUTO,
        planning_request: str = "",
        prepared_source_index: PlanningSourceIndex | None = None,
        repository_intent: str | None = None,
        revision_source_run_id: str = "",
        revision_request_id: str = "",
        revision_request_text: str = "",
        revision_source_task_ids: Sequence[str] = (),
        revision_source_paths: Sequence[str] = (),
        effort_mode: EffortMode | str = EffortMode.BALANCED,
        planning_profile_source: ProfileSource | str | None = None,
        reserved_run_id: str = "",
    ) -> RunState:
        return self._common_runtime.planning.prepare_planning(
            spec_path,
            planning_agent_id=planning_agent_id,
            planning_model=planning_model,
            planning_reasoning_effort=planning_reasoning_effort,
            planning_mode=planning_mode,
            planning_request=planning_request,
            prepared_source_index=prepared_source_index,
            repository_intent=repository_intent,
            revision_source_run_id=revision_source_run_id,
            revision_request_id=revision_request_id,
            revision_request_text=revision_request_text,
            revision_source_task_ids=revision_source_task_ids,
            revision_source_paths=revision_source_paths,
            effort_mode=effort_mode,
            planning_profile_source=planning_profile_source,
            reserved_run_id=reserved_run_id,
        )

    def result_revision_requests(self, run_id: str) -> dict[str, object]:
        return self._common_runtime.planning.result_revision_requests(run_id)

    def propose_result_revision(self, run_id: str, *, proposal_id: str, text: str, focus_task_id: str = "") -> dict[str, object]:
        return self._common_runtime.planning.propose_result_revision(run_id, proposal_id=proposal_id, text=text, focus_task_id=focus_task_id)

    def create_result_revision_request(
        self, run_id: str, *, request_id: str, text: str, task_ids: Sequence[str], paths: Sequence[str], proposal_id: str = ""
    ) -> dict[str, object]:
        return self._common_runtime.planning.create_result_revision_request(
            run_id,
            request_id=request_id,
            text=text,
            task_ids=task_ids,
            paths=paths,
            proposal_id=proposal_id,
        )

    def run_planning(self, run_id: str) -> RunState:
        return self._common_runtime.planning.run_planning(run_id)

    def clarify(self, run_id: str, answers_path: str | Path) -> RunState:
        return self._common_runtime.planning.clarify(run_id, answers_path)

    def clarify_text(
        self,
        run_id: str,
        answers: str,
        *,
        planning_agent_id: str | None = None,
        planning_model: str | None = None,
        planning_reasoning_effort: str | None = None,
    ) -> RunState:
        return self._common_runtime.planning.clarify_text(
            run_id,
            answers,
            planning_agent_id=planning_agent_id,
            planning_model=planning_model,
            planning_reasoning_effort=planning_reasoning_effort,
        )

    def send_planning_message(
        self,
        run_id: str,
        message: str,
        *,
        planning_agent_id: str | None = None,
        planning_model: str | None = None,
        planning_reasoning_effort: str | None = None,
    ) -> RunState:
        return self._common_runtime.planning.send_planning_message(
            run_id,
            message,
            planning_agent_id=planning_agent_id,
            planning_model=planning_model,
            planning_reasoning_effort=planning_reasoning_effort,
        )

    def request_direction_change(self, run_id: str, *, request_id: str, text: str) -> RunState:
        return self._common_runtime.planning.request_direction_change(run_id, request_id=request_id, text=text)

    def planning_apply_preview(self, run_id: str) -> dict[str, object] | None:
        return self._common_runtime.planning.planning_apply_preview(run_id)

    def planning_preview_status(self, run_id: str) -> dict[str, object]:
        return self._common_runtime.planning.planning_preview_status(run_id)

    def preview_planning_apply(self, run_id: str, *, request_id: str) -> dict[str, object]:
        return self._common_runtime.planning.preview_planning_apply(run_id, request_id=request_id)

    def apply_planning_preview(self, run_id: str, *, preview_id: str, fingerprint: str, candidate_digest: str) -> dict[str, object]:
        return self._common_runtime.planning.apply_planning_preview(
            run_id,
            preview_id=preview_id,
            fingerprint=fingerprint,
            candidate_digest=candidate_digest,
        )

    def request_planning_conversation_apply(
        self,
        run_id: str,
        *,
        request_id: str,
        expected_revision: int,
        conversation_revision: int,
        control_message: str = "",
        answer_message: str = "",
        expected_tech_stack_revision: int | None = None,
        retry_failed: bool = False,
        planning_agent_id: str | None = None,
        planning_model: str | None = None,
        planning_reasoning_effort: str | None = None,
    ) -> RunState:
        return self._common_runtime.planning.request_planning_conversation_apply(
            run_id,
            request_id=request_id,
            expected_revision=expected_revision,
            conversation_revision=conversation_revision,
            control_message=control_message,
            answer_message=answer_message,
            expected_tech_stack_revision=expected_tech_stack_revision,
            retry_failed=retry_failed,
            planning_agent_id=planning_agent_id,
            planning_model=planning_model,
            planning_reasoning_effort=planning_reasoning_effort,
        )

    def apply_planning_conversation(
        self,
        run_id: str,
        *,
        message: str = "",
        planning_agent_id: str | None = None,
        planning_model: str | None = None,
        planning_reasoning_effort: str | None = None,
    ) -> RunState:
        return self._common_runtime.planning.apply_planning_conversation(
            run_id,
            message=message,
            planning_agent_id=planning_agent_id,
            planning_model=planning_model,
            planning_reasoning_effort=planning_reasoning_effort,
        )

    def confirm_tech_stack(self, run_id: str, *, option_id: str, expected_revision: int) -> RunState:
        return self._common_runtime.planning.confirm_tech_stack(run_id, option_id=option_id, expected_revision=expected_revision)

    def preview_bootstrap(self, run_id: str) -> BootstrapSpec:
        return self._common_runtime.planning.preview_bootstrap(run_id)

    def configure_bootstrap_agent_instructions(
        self,
        run_id: str,
        *,
        create: bool,
        expected_revision: int,
        expected_digest: str,
    ) -> RunState:
        return self._common_runtime.planning.configure_bootstrap_agent_instructions(
            run_id,
            create=create,
            expected_revision=expected_revision,
            expected_digest=expected_digest,
        )

    def generate_feature_plan(self, run_id: str) -> RunState:
        return self._common_runtime.planning.generate_feature_plan(run_id)

    def refresh_planning_index(self, source_root: str | Path, *, base_commit: str = "") -> PlanningSourceIndex:
        return self._common_runtime.planning.refresh_planning_index(source_root, base_commit=base_commit)

    def status(self, run_id: str) -> RunState:
        return self._common_runtime.runs.status(run_id)

    def notifications(self, *, after_cursor: str = "", limit: int = 100) -> dict[str, object]:
        return self._common_runtime.runs.notifications(after_cursor=after_cursor, limit=limit)

    def waiting_prompt(
        self, state: RunState, control: RunExecutionControl, integration: IntegrationControl | None = None,
    ) -> dict[str, object] | None:
        return self._common_runtime.runs.waiting_prompt(state, control, integration)

    def status_with_execution_control(self, run_id: str) -> tuple[RunState, RunExecutionControl]:
        return self._common_runtime.runs.status_with_execution_control(run_id)

    def latest_main_operations(self, run_id: str) -> dict[str, dict[str, str] | None]:
        return self._common_runtime.runs.latest_main_operations(run_id)

    def status_with_controls(self, run_id: str) -> tuple[RunState, RunExecutionControl, IntegrationControl]:
        return self._common_runtime.runs.status_with_controls(run_id)

    def recovery_plan(self, run_id: str, *, request_id: str = "") -> dict[str, object]:
        return self._common_runtime.execution.control.recovery_plan(run_id, request_id=request_id)

    def apply_recovery(
        self,
        run_id: str,
        fingerprint: str,
        source_ids: list[str],
        *,
        approved: bool,
        request_id: str = "",
        resume_request_id: str = "",
    ) -> RunState:
        return self._common_runtime.execution.control.apply_recovery(
            run_id,
            fingerprint,
            source_ids,
            approved=approved,
            request_id=request_id,
            resume_request_id=resume_request_id,
        )

    def recovery_operation(self, run_id: str, request_id: str) -> dict[str, object]:
        return self._common_runtime.execution.control.recovery_operation(run_id, request_id)

    def latest_recovery_operation(self, run_id: str, kind: str) -> dict[str, object] | None:
        return self._common_runtime.execution.control.latest_recovery_operation(run_id, kind)

    def list_statuses(self) -> list[RunState]:
        return self._common_runtime.runs.list_statuses()

    def list_summaries(self, scope: str = "all") -> list[RunSummary]:
        return self._common_runtime.runs.list_summaries(scope)

    @staticmethod
    def planned_user_checks(state: RunState, *, include_notes: bool = False) -> list[dict[str, object]]:
        return RunQueries.planned_user_checks(state, include_notes=include_notes)

    @staticmethod
    def user_checks(state: RunState, *, include_recorded: bool = False) -> list[dict[str, object]]:
        return RunQueries.user_checks(state, include_recorded=include_recorded)

    def user_check_summaries(self) -> list[dict[str, object]]:
        return self._common_runtime.runs.user_check_summaries()

    def attention_item_summaries(self) -> list[dict[str, object]]:
        return self._common_runtime.runs.attention_item_summaries()

    def active_group_summaries(self) -> list[dict[str, object]]:
        return self._common_runtime.runs.active_group_summaries()

    def begin_planning_request(self, run_id: str, *, request_id: str, kind: str, message: str = "") -> dict[str, object]:
        return self._common_runtime.execution.control.begin_planning_request(run_id, request_id=request_id, kind=kind, message=message)

    def finish_planning_request(self, run_id: str, *, request_id: str, phase: str, error: str = "") -> dict[str, object]:
        return self._common_runtime.execution.control.finish_planning_request(run_id, request_id=request_id, phase=phase, error=error)

    def interrupt_planning(self, run_id: str, *, approved: bool) -> RunState:
        return self._common_runtime.execution.control.interrupt_planning(run_id, approved=approved)

    def task_log(self, run_id: str, task_id: str) -> str:
        return self._common_runtime.runs.task_log(run_id, task_id)

    def check_dotnet(self, *, run_id: str = "", task_id: str = "") -> DotnetDiagnostic:
        return self._common_runtime.runs.check_dotnet(run_id=run_id, task_id=task_id)

    def update_main(self, *, approved: bool = False) -> RepositoryUpdate:
        return self._common_runtime.integration.integration_commands.update_main(approved=approved)

    def main_changes(self, *, refresh_remote: bool = False) -> MainChangeSnapshot:
        return self._common_runtime.integration.integration_commands.main_changes(refresh_remote=refresh_remote)

    def main_change_diff(self, snapshot_id: str, path: str, mode: str) -> MainChangeDiff:
        return self._common_runtime.integration.integration_commands.main_change_diff(snapshot_id, path, mode)

    def commit_main_changes(
        self, snapshot_id: str, selections: list[tuple[str, str]], message: str, *, approved: bool = False
    ) -> MainMutationResult:
        return self._common_runtime.integration.integration_commands.commit_main_changes(snapshot_id, selections, message, approved=approved)

    def push_main_commits(self, snapshot_id: str, *, approved: bool = False) -> MainMutationResult:
        return self._common_runtime.integration.integration_commands.push_main_commits(snapshot_id, approved=approved)

    def commit_and_push_main_changes(
        self,
        snapshot_id: str,
        selections: list[tuple[str, str]],
        message: str,
        *,
        approved: bool = False,
    ) -> MainMutationResult:
        return self._common_runtime.integration.integration_commands.commit_and_push_main_changes(snapshot_id, selections, message, approved=approved)

    def planning_provider_choices(self) -> list[ProviderChoice]:
        return self._common_runtime.providers.planning_provider_choices()

    def preview_effort_mode(self, run_id: str, mode: EffortMode | str, *, expected_revision: int) -> EffortModePreview:
        return self._common_runtime.effort.preview_effort_mode(run_id, mode, expected_revision=expected_revision)

    def usage(self, run_id: str, *, execution_request_id: str = "", cursor: str = "", limit: int = 50) -> dict[str, object]:
        return self._common_runtime.runs.usage(run_id, execution_request_id=execution_request_id, cursor=cursor, limit=limit)

    def effort_control(self, run_id: str, *, expected_state: RunState | None = None) -> dict[str, object]:
        return self._common_runtime.effort.effort_control(run_id, expected_state=expected_state)

    def desktop_effort_mode_preview(self, run_id: str, mode: str, *, expected_revision: int) -> dict[str, object]:
        return self._common_runtime.effort.desktop_effort_mode_preview(run_id, mode, expected_revision=expected_revision)

    def set_effort_mode(
        self, run_id: str, mode: EffortMode | str, *, expected_revision: int, request_id: str, target: str = "planning"
    ) -> EffortPolicyView:
        return self._common_runtime.effort.set_effort_mode(run_id, mode, expected_revision=expected_revision, request_id=request_id, target=target)

    def cancel_effort_reservation(self, run_id: str, *, expected_revision: int, request_id: str) -> EffortPolicyView:
        return self._common_runtime.effort.cancel_effort_reservation(run_id, expected_revision=expected_revision, request_id=request_id)

    def apply_effort_mode_to_plan(
        self, run_id: str, mode: EffortMode | str, *, expected_policy_revision: int, expected_plan_revision: int,
        reviewer_agent_ids: dict[str, str] | None = None,
    ) -> RunState:
        return self._common_runtime.effort.apply_effort_mode_to_plan(
            run_id,
            mode,
            expected_policy_revision=expected_policy_revision,
            expected_plan_revision=expected_plan_revision,
            reviewer_agent_ids=reviewer_agent_ids,
        )

    def execution_provider_choices(self, capabilities: list[str]) -> list[ProviderChoice]:
        return self._common_runtime.providers.execution_provider_choices(capabilities)

    def provider_statuses(self, provider_id: str = "") -> list[ProviderStatus]:
        return self._common_runtime.providers.provider_statuses(provider_id)

    @staticmethod
    def account_usage(provider: str, *, claude_api_key: str | None = None) -> AccountUsage:
        return ProviderQueries.account_usage(provider, claude_api_key=claude_api_key)

    @staticmethod
    def claude_connection_status() -> dict[str, object]:
        return ProviderQueries.claude_connection_status()

    def run_lock_status(self, run_id: str) -> RunLockStatus:
        return self._common_runtime.execution.control.run_lock_status(run_id)

    def clear_run_lock(self, run_id: str, *, approved: bool) -> RunLockStatus:
        return self._common_runtime.execution.control.clear_run_lock(run_id, approved=approved)

    def archive_plan(self, run_id: str) -> dict[str, object]:
        return self._common_runtime.integration.lifecycle_commands.archive_plan(run_id)

    def archive_run(
        self,
        run_id: str,
        *,
        expected_revision: str,
        fingerprint: str,
        request_id: str,
        approved: bool,
    ) -> RunState:
        return self._common_runtime.integration.lifecycle_commands.archive_run(
            run_id,
            expected_revision=expected_revision,
            fingerprint=fingerprint,
            request_id=request_id,
            approved=approved,
        )

    def retry_archive_cleanup(
        self, run_id: str, *, fingerprint: str, request_id: str, approved: bool
    ) -> RunState:
        return self._common_runtime.integration.lifecycle_commands.retry_archive_cleanup(
            run_id,
            fingerprint=fingerprint,
            request_id=request_id,
            approved=approved,
        )

    def delete_run(self, run_id: str, *, approved: bool) -> RunDeletion:
        return self._common_runtime.integration.lifecycle_commands.delete_run(run_id, approved=approved)

    def workspace_statuses(self, run_id: str = "") -> list[WorkspaceStatus]:
        return self._common_runtime.integration.lifecycle_commands.workspace_statuses(run_id)

    def cleanup_workspace(self, run_id: str, task_id: str, *, approved: bool) -> WorkspaceStatus:
        return self._common_runtime.integration.lifecycle_commands.cleanup_workspace(run_id, task_id, approved=approved)

    def exclude_tasks(self, run_id: str, task_ids: list[str]) -> RunState:
        return self._common_runtime.planning.exclude_tasks(run_id, task_ids)

    def update_plan(self, run_id: str, task_drafts: list[dict[str, object]], *, expected_revision: int | None = None) -> RunState:
        return self._common_runtime.planning.update_plan(run_id, task_drafts, expected_revision=expected_revision)

    def update_task_execution_profile(
        self, run_id: str, task_id: str, *, agent_id: str, model: str, reasoning_effort: str, expected_profile: dict[str, str]
    ) -> RunState:
        return self._common_runtime.execution.execution_commands.update_task_execution_profile(
            run_id,
            task_id,
            agent_id=agent_id,
            model=model,
            reasoning_effort=reasoning_effort,
            expected_profile=expected_profile,
        )

    def execution_profile_view(self, state: RunState) -> RunState:
        return self._common_runtime.execution.execution_commands.execution_profile_view(state)

    def confirm_plan(self, run_id: str, *, expected_revision: int | None = None, expected_bootstrap_digest: str = "") -> RunState:
        return self._common_runtime.planning.confirm_plan(
            run_id,
            expected_revision=expected_revision,
            expected_bootstrap_digest=expected_bootstrap_digest,
        )

    def execute(
        self,
        run_id: str,
        *,
        manual: bool = False,
        agent_overrides: dict[str, str] | None = None,
        model_overrides: dict[str, str] | None = None,
        reasoning_effort_overrides: dict[str, str] | None = None,
        expected_revision: int | None = None,
    ) -> RunState:
        return self._common_runtime.execution.execution_commands.execute(
            run_id,
            manual=manual,
            agent_overrides=agent_overrides,
            model_overrides=model_overrides,
            reasoning_effort_overrides=reasoning_effort_overrides,
            expected_revision=expected_revision,
        )

    def resume(self, run_id: str, *, manual: bool = False, expected_revision: int | None = None) -> RunState:
        return self._common_runtime.execution.execution_commands.resume(run_id, manual=manual, expected_revision=expected_revision)

    def approve_task_scope(self, run_id: str, task_id: str, *, request_id: str, review_id: str,
                           approved: bool) -> dict[str, object]:
        return self._common_runtime.execution.execution_commands.approve_task_scope(
            run_id,
            task_id,
            request_id=request_id,
            review_id=review_id,
            approved=approved,
        )

    def decide_project_chat(self, run_id: str, request_id: str) -> dict[str, object]:
        return self._common_runtime.execution.control.decide_project_chat(run_id, request_id)

    def perform_project_chat(self, run_id: str, request_id: str, step_id: str) -> dict[str, object]:
        return self._common_runtime.execution.control.perform_project_chat(run_id, request_id, step_id)

    def request_chat_control(self, run_id: str, *, request_id: str, intent: str, message: str,
                             expected: dict[str, object], session_id: str = "", profile: dict[str, str] | None = None) -> dict[str, object]:
        return self._common_runtime.execution.control.request_chat_control(
            run_id,
            request_id=request_id,
            intent=intent,
            message=message,
            expected=expected,
            session_id=session_id,
            profile=profile,
        )

    def advance_chat_control(self, run_id: str, request_id: str, *, suspend: bool = False) -> dict[str, object]:
        return self._common_runtime.execution.control.advance_chat_control(run_id, request_id, suspend=suspend)

    def cancel_chat_control(self, run_id: str, request_id: str) -> dict[str, object]:
        return self._common_runtime.execution.control.cancel_chat_control(run_id, request_id)

    def repair_task_from_chat(
        self, run_id: str, task_id: str, *, request_id: str, message: str, fingerprint: str, conversation_revision: int,
        parent_request_id: str = "", recovery_fingerprint: str = "",
    ) -> RunState:
        return self._common_runtime.execution.control.repair_task_from_chat(
            run_id,
            task_id,
            request_id=request_id,
            message=message,
            fingerprint=fingerprint,
            conversation_revision=conversation_revision,
            parent_request_id=parent_request_id,
            recovery_fingerprint=recovery_fingerprint,
        )

    def retry_task(self, run_id: str, task_id: str, *, manual: bool = False) -> RunState:
        return self._common_runtime.execution.execution_commands.retry_task(run_id, task_id, manual=manual)

    def execute_task(
        self,
        run_id: str,
        task_id: str,
        *,
        manual: bool = False,
        agent_overrides: dict[str, str] | None = None,
        model_overrides: dict[str, str] | None = None,
        reasoning_effort_overrides: dict[str, str] | None = None,
    ) -> RunState:
        return self._common_runtime.execution.execution_commands.execute_task(
            run_id,
            task_id,
            manual=manual,
            agent_overrides=agent_overrides,
            model_overrides=model_overrides,
            reasoning_effort_overrides=reasoning_effort_overrides,
        )

    def set_manual_task_deferred(self, run_id: str, task_id: str, *, deferred: bool) -> RunState:
        return self._common_runtime.execution.execution_commands.set_manual_task_deferred(run_id, task_id, deferred=deferred)

    def record_user_check(
        self, run_id: str, check_id: str, *, expected_revision: int, expected_commit: str, outcome: str, note: str,
    ) -> RunState:
        return self._common_runtime.execution.execution_commands.record_user_check(
            run_id,
            check_id,
            expected_revision=expected_revision,
            expected_commit=expected_commit,
            outcome=outcome,
            note=note,
        )

    def complete_manual_verification(
        self, run_id: str, task_id: str, *, note: str, expected_commit: str, expected_revision: int,
    ) -> RunState:
        return self._common_runtime.execution.execution_commands.complete_manual_verification(
            run_id,
            task_id,
            note=note,
            expected_commit=expected_commit,
            expected_revision=expected_revision,
        )

    def handoff_manual_task_to_ai(
        self, run_id: str, task_id: str, *, expected_commit: str, expected_revision: int,
    ) -> RunState:
        return self._common_runtime.execution.execution_commands.handoff_manual_task_to_ai(
            run_id,
            task_id,
            expected_commit=expected_commit,
            expected_revision=expected_revision,
        )

    def complete_task(self, run_id: str, task_id: str) -> RunState:
        return self._common_runtime.execution.execution_commands.complete_task(run_id, task_id)

    def preview_main_apply(self, run_id: str) -> dict[str, object]:
        return self._common_runtime.integration.integration_commands.preview_main_apply(run_id)

    def apply_reviewed_main(self, run_id: str, *, request_id: str, review_id: str, approved: bool) -> tuple[RunState, str]:
        return self._common_runtime.integration.integration_commands.apply_reviewed_main(
            run_id,
            request_id=request_id,
            review_id=review_id,
            approved=approved,
        )

    def merge(self, run_id: str, *, approved: bool, request_id: str = "", review_id: str = "") -> RunState:
        return self._common_runtime.integration.integration_commands.merge(run_id, approved=approved, request_id=request_id, review_id=review_id)

    def recover_main_apply(
        self, run_id: str, *, approved: bool, request_id: str = "", expected_repo: str = "", expected_commit: str = "",
    ) -> RunState:
        return self._common_runtime.integration.integration_commands.recover_main_apply(
            run_id,
            approved=approved,
            request_id=request_id,
            expected_repo=expected_repo,
            expected_commit=expected_commit,
        )

    def retry_main_push(self, run_id: str, *, approved: bool, request_id: str = "") -> RunState:
        return self._common_runtime.integration.integration_commands.retry_main_push(run_id, approved=approved, request_id=request_id)

    def result_artifact_info(self, run_id: str) -> dict[str, object]:
        return self._common_runtime.integration.integration_commands.result_artifact_info(run_id)

    def register_result_artifact(self, run_id: str, *, kind: str, relative_path: str, expected_commit: str) -> dict[str, object]:
        return self._common_runtime.integration.integration_commands.register_result_artifact(
            run_id,
            kind=kind,
            relative_path=relative_path,
            expected_commit=expected_commit,
        )

    def launch_result_artifact(self, run_id: str, *, expected_digest: str, device_id: str = "") -> dict[str, object]:
        return self._common_runtime.integration.integration_commands.launch_result_artifact(
            run_id,
            expected_digest=expected_digest,
            device_id=device_id,
        )

    def verify(self, run_id: str) -> RunState:
        return self._common_runtime.integration.integration_commands.verify(run_id)

    def verify_and_repair(self, run_id: str, *, request_id: str, chat_message: str = "", parent_request_id: str = "") -> RunState:
        return self._common_runtime.integration.integration_commands.verify_and_repair(
            run_id,
            request_id=request_id,
            chat_message=chat_message,
            parent_request_id=parent_request_id,
        )

    def integration_conflict(
        self, run_id: str, *, conflict_id: str = "", file_path: str = "", recovery_task_id: str = ""
    ) -> dict[str, object]:
        return self._common_runtime.integration.integration_commands.integration_conflict(
            run_id,
            conflict_id=conflict_id,
            file_path=file_path,
            recovery_task_id=recovery_task_id,
        )

    def prepare_conflict_resolution(
        self,
        run_id: str,
        *,
        conflict_id: str,
        fingerprint: str,
        request_id: str,
        agent_id: str = "",
        model: str = "",
        reasoning_effort: str = "",
    ) -> dict[str, object]:
        return self._common_runtime.integration.integration_commands.prepare_conflict_resolution(
            run_id,
            conflict_id=conflict_id,
            fingerprint=fingerprint,
            request_id=request_id,
            agent_id=agent_id,
            model=model,
            reasoning_effort=reasoning_effort,
        )

    def apply_conflict_resolution(
        self,
        run_id: str,
        *,
        conflict_id: str,
        candidate_id: str,
        candidate_revision: int,
        fingerprint: str,
        request_id: str,
        approved: bool,
    ) -> RunState:
        return self._common_runtime.integration.integration_commands.apply_conflict_resolution(
            run_id,
            conflict_id=conflict_id,
            candidate_id=candidate_id,
            candidate_revision=candidate_revision,
            fingerprint=fingerprint,
            request_id=request_id,
            approved=approved,
        )

    def push(self, run_id: str, *, approved: bool, request_id: str = "") -> RunState:
        return self._common_runtime.integration.integration_commands.push(run_id, approved=approved, request_id=request_id)

    def deploy(self, run_id: str, *, approved: bool) -> RunState:
        return self._common_runtime.integration.integration_commands.deploy(run_id, approved=approved)

    def task_retry_context(self, run_id: str, task_id: str) -> dict[str, object]:
        return self._common_runtime.execution.execution_commands.task_retry_context(run_id, task_id)

    def record_task_diagnosis(self, run_id: str, task_id: str, fingerprint: str, diagnosis: str) -> None:
        return self._common_runtime.execution.execution_commands.record_task_diagnosis(run_id, task_id, fingerprint, diagnosis)

    def save_task_retry_instruction(
        self, run_id: str, task_id: str, *, request_id: str, text: str, fingerprint: str
    ) -> dict[str, object]:
        return self._common_runtime.execution.execution_commands.save_task_retry_instruction(
            run_id,
            task_id,
            request_id=request_id,
            text=text,
            fingerprint=fingerprint,
        )

    def task_failure_message(self, task: WorkTask) -> str:
        return self._common_runtime.execution.execution_commands.task_failure_message(task)
