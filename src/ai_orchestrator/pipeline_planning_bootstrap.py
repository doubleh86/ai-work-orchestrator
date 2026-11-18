"""Compose planning features and commands without executing work."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING
from .code_style import CodeStyleSnapshot, inspect_project_code_style
from .codex_sdk import CodexSdkError
from .config import AgentConfig, resolve_workspace_location
from .document_index import PLANNING_INDEX_TIMEOUT_SECONDS, refresh_planning_source_index
from .errors import PipelineError
from .execution import (
    ProviderRunner,
    TaskExecutionPreparation,
    TaskExecutionRecords,
    TaskRetryGuidance,
    normalize_agent_id,
    normalize_model,
    normalize_reasoning_effort,
    retry_task_contract_digest,
    validate_reasoning_effort,
    with_effort_mode_guidance,
    provider_connection,
)
from .execution.lifecycle import StoredStopSignal, EXECUTION_RUN_LOCK_OPERATIONS
from .execution.provider_choices import ProviderAvailability
from .execution.provider_commands import agent_command, command_with_claude_session, command_with_model, command_with_reasoning_effort
from .execution.provider_runtime import ProviderRuntime
from .execution.task_prompts import task_prompt_from_state
from .git import GitError
from .integration import WorkspaceLayout, shared_run_branch_name, uses_shared_workspace
from .models import BootstrapSpec, PlanningApplyRequest, PlanningApplyStatus, RunState, WorkTask
from .orchestration.effort import EffortCommands
from .orchestration.planning import PlanningCommands, PlanningCommandRecords
from .orchestration.planning_routing import PlanningMessageRouter, PlanningMessageRecords
from .orchestration.providers import ProviderQueries
from .persistence.run_lookup import find_task, RunLookup
from .planner import Plan, PlanningError
from .planning import (
    PlanDraftValidator,
    PlanningApplyRequests,
    PlanningPreviewRecords,
    PlanningPreviewWorkflow,
    ResultRevisionRecords,
    ResultRevisionWorkflow,
    planning_apply_request,
    planning_preview_task_fields,
    planning_task_editable,
    result_revision_available_paths,
    result_revision_context,
    result_revision_evidence,
    validate_planning_preview_payload,
    source_indexes as planning_indexes,
)
from .planning.ai import PlanningAI
from .planning.apply_requests import (
    PlanningApplyRecords,
    PlanningApplyWorkflow,
    normalize_planning_apply_request_id,
    validate_planning_apply_replay,
    validate_tech_stack_apply,
    validate_tech_stack_apply_replay,
)
from .planning.bootstrap import BootstrapPlanner, file_sha256, replace_tech_stack_decision
from .planning.chat import PlanningChatRunner
from .planning.conversation import (
    clarification_context,
    planning_conversation_id,
    planning_message_is_apply_control,
    planning_message_requests_apply,
    planning_message_requests_initial_tasks,
    task_plan_draft,
)
from .planning.documents import snapshot_planning_sources
from .planning.initialization import PlanningRepositoryContext
from .planning.intake import PlanningIntake
from .planning.invocation import PlanningInvocation, PlanningInvocationRecords, record_planning_progress
from .planning.lifecycle import PlanningLifecycle
from .planning.messages import PlanningMessages
from .planning.plan_application import ConversationPlanApplication, FeaturePlanApplication, PlanContentApplication
from .planning.plan_files import PlanFiles
from .planning.plan_review import PlanConfirmation, TaskPlanExclusion, protected_greenfield_bootstrap
from .planning.policy_scope import PlanningPolicyScope
from .planning.preparation import InitialVerificationSettings, PlanningPreparation
from .planning.preview_apply import PlanningPreviewApplication, PreviewApplyRecords
from .planning.profiles import PlanningProfiles, normalize_planning_mode
from .planning.proposals import ResultRevisionAI
from .planning.result_revisions import ResultRevisionProposalPreparation
from .planning.runner import PlanningPersistence, PlanningRunner
from .planning.source_indexes import PlanningSourceIndexes
from .planning.task_apply import PendingTaskChangeRecords, PendingTaskChanges
from .repository_maturity import inspect_repository_maturity

if TYPE_CHECKING:
    from .pipeline_bootstrap import PipelineResources


def build_planning_commands(
    resources: PipelineResources,
    *,
    provider: ProviderRuntime[StoredStopSignal],
    policy_scope: PlanningPolicyScope,
    providers: ProviderQueries,
    availability: ProviderAvailability,
    lookup: RunLookup,
    files: PlanFiles,
    retry_guidance: TaskRetryGuidance,
    effort: EffortCommands,
) -> PlanningCommands:
    def ensure_git_ready() -> None:
        planning_indexes.ensure_planning_git_ready(resources.repo)

    def base_commit() -> str:
        resources.git.ensure_repository(non_interactive=True, timeout_seconds=PLANNING_INDEX_TIMEOUT_SECONDS)
        return resources.git.head(resources.repo, non_interactive=True, timeout_seconds=PLANNING_INDEX_TIMEOUT_SECONDS)

    def ensure_provider_ready(agent: AgentConfig) -> None:
        provider_connection.ensure_planning_provider_ready(
            agent,
            read_statuses=lambda provider_id: providers.status_queries().statuses(provider_id),
            api_key=resources.claude_api_key,
        )

    def verification_settings() -> InitialVerificationSettings:
        return InitialVerificationSettings(
            resources.config.execution.task_verify_command_timeout_seconds,
            resources.config.execution.task_verify_total_timeout_seconds,
            resources.config.execution.integration_verify_command_timeout_seconds,
            resources.config.execution.integration_verify_total_timeout_seconds,
            resources.config.execution.verification_repair_limit,
        )

    def snapshot_sources(state: RunState, source_root: Path, plan: Plan) -> None:
        snapshot_planning_sources(state, source_root, plan, run_directory=resources.store.run_dir)

    def replace_decision(state: RunState, plan: Plan) -> None:
        replace_tech_stack_decision(state, plan, repo=resources.repo)

    def build_bootstrap(state: RunState, task: WorkTask) -> BootstrapSpec:
        return BootstrapPlanner(resources.repo).build(state, task)

    def task_preparation() -> TaskExecutionPreparation:
        layout = WorkspaceLayout(resources.config.project)
        return TaskExecutionPreparation(
            repo=resources.repo,
            git=resources.git,
            records=TaskExecutionRecords(resources.store.run_dir, resources.store.save),
            workspace_location=layout.location,
            uses_shared_workspace=uses_shared_workspace,
            shared_branch_name=shared_run_branch_name,
            shared_worktree_path=layout.shared_path,
            shared_boundary=layout.shared_boundary,
            managed_roots=layout.managed_state_roots,
            run_worktree_root=layout.run_root,
            prompt=task_prompt_from_state,
        )

    def repository_context() -> PlanningRepositoryContext:
        return PlanningRepositoryContext(
            repo=resources.repo,
            inspect_maturity=inspect_repository_maturity,
            style_snapshot=lambda : (
                CodeStyleSnapshot.from_profile(
                    inspect_project_code_style(
                        resources.repo,
                        resources.code_style_preference,
                        preference_revision=resources.code_style_preference_revision,
                    ),
                )
            ),
        )

    def result_revisions() -> ResultRevisionWorkflow:
        return ResultRevisionWorkflow(
            records=ResultRevisionRecords(
                load_run=resources.store.load,
                list_runs=resources.store.list_runs,
                load_requests=resources.store.load_revision_requests,
                save_requests=resources.store.save_revision_requests,
                load_proposals=resources.store.load_revision_proposals,
                save_proposals=resources.store.save_revision_proposals,
                retry_lock=lambda run_id: resources.store.lock(run_id, 'retry-instruction-save'),
            ),
            fingerprint=proposals.fingerprint,
            available_paths=result_revision_available_paths,
            request_context=result_revision_context,
            prepare_linked=intake.prepare_revision_run,
            find_task=find_task,
            retry_context=retry_guidance.context,
            retry_digest=retry_task_contract_digest,
            record_wait=retry_guidance.record_wait,
            generate_proposal=proposals.generate,
        )

    def previews() -> PlanningPreviewWorkflow:
        return PlanningPreviewWorkflow(
            records=PlanningPreviewRecords(
                load_run=resources.store.load,
                load_candidate=resources.store.load_planning_apply_preview,
                save_candidate=resources.store.save_planning_apply_preview,
                load_progress=resources.store.planning_preview_progress,
                save_progress=resources.store.save_planning_preview_progress,
                save_chat=resources.store.save_planning_chat,
                run_lock=resources.store.inspect_lock,
                chat_lock=resources.store.inspect_planning_chat_lock,
            ),
            build_plan=ai.build_plan,
            clarification_context=clarification_context,
            source_index=source_indexes().snapshot,
            follow_up_request=messages.follow_up,
            file_digest=file_sha256,
            normalize_request_id=normalize_planning_apply_request_id,
            generation_errors=(PipelineError, PlanningError, OSError, ValueError, GitError, CodexSdkError),
        )

    def planning_profiles() -> PlanningProfiles:
        return PlanningProfiles(
            default_agent_id=lambda: resources.config.planning.agent_id,
            read_agent=lambda agent_id: resources.agents.get(agent_id),
            available_agent=availability.require,
            selected_mode=lambda run_id: resources.store.load_effort_policy(run_id).selected_mode,
            normalize_agent_id=normalize_agent_id,
            normalize_model=normalize_model,
            normalize_effort=normalize_reasoning_effort,
            validate_effort=validate_reasoning_effort,
        )

    def chat_runner() -> PlanningChatRunner:
        return PlanningChatRunner(
            repo=resources.repo,
            codex_sdk=resources.codex_sdk,
            save_state=resources.store.save,
            run_directory=resources.store.run_dir,
            read_timeout=lambda: resources.config.planning.timeout_seconds,
            conversation_id=planning_conversation_id,
            sdk_profile=ProviderRunner.codex_profile,
            prompt=ai.chat_prompt,
            clarification_context=clarification_context,
            sequential=uses_shared_workspace,
            result_chat_available=messages.result_available,
            execution_chat_available=messages.execution_available,
            result_evidence=result_revision_evidence,
            invoke=ai.invoke,
        )

    def plan_runner() -> PlanningRunner:
        return PlanningRunner(
            repo=resources.repo,
            planning=resources.config.planning,
            routing=resources.config.routing,
            persistence=PlanningPersistence(
                root=resources.store.root,
                run_directory=resources.store.run_dir,
                save_state=resources.store.save,
                read_preview_progress=resources.store.planning_preview_progress,
                save_preview_progress=resources.store.save_planning_preview_progress,
                read_result=resources.store.load_planning_result,
                save_result=resources.store.save_planning_result,
            ),
            available_agent=availability.require,
            sdk_profile=ProviderRunner.codex_profile,
            execution_agents=providers.choices.planning_execution_agents,
            sequential=uses_shared_workspace,
            has_uncommitted_changes=resources.git.has_uncommitted_changes,
            validate_plan=ai.validate_plan,
            cache_key=ai.cache_key,
            invoke_agent=ai.invoke,
            codex_sdk=resources.codex_sdk,
        )

    def source_indexes() -> PlanningSourceIndexes:
        return PlanningSourceIndexes(
            repo=resources.repo,
            records_root=resources.store.root,
            run_directory=resources.store.run_dir,
            workspace_root=lambda: Path(resolve_workspace_location(resources.config.project).root),
            ensure_git_ready=ensure_git_ready,
            ensure_repository=lambda timeout: resources.git.ensure_repository(non_interactive=True, timeout_seconds=timeout),
            list_project_files=lambda root, timeout: resources.git.list_project_files(root, non_interactive=True, timeout_seconds=timeout),
            read_head=lambda root, timeout: resources.git.head(root, non_interactive=True, timeout_seconds=timeout),
            has_changes=lambda root: resources.git.path_has_changes(root, non_interactive=True, timeout_seconds=PLANNING_INDEX_TIMEOUT_SECONDS),
            refresh_source_index=refresh_planning_source_index,
        )

    def draft_validator() -> PlanDraftValidator:
        return PlanDraftValidator(
            plan_paths=files.result_paths,
            read_execution_agents=providers.choices.planning_execution_agents,
            protected_bootstrap=protected_greenfield_bootstrap,
            read_agents=lambda: resources.config.agents,
            read_routing=lambda: resources.config.routing,
            registered_models=lambda: tuple(resources.nvidia_model_api_keys),
            selected_mode=lambda run_id: resources.store.load_effort_policy(run_id).selected_mode,
            shared_workspace=uses_shared_workspace,
            available_agent=availability.require,
            reviewer_compatible=availability.reviewer_compatible,
        )

    def invocation() -> PlanningInvocation:
        return PlanningInvocation(
            repo=resources.repo,
            records=PlanningInvocationRecords(
                resources.store.save,
                resources.store.load_effort_policy,
                resources.store.effort_policy_path,
                resources.store.start_effort_planning,
            ),
            command=agent_command,
            command_with_model=command_with_model,
            command_with_effort=lambda agent, command, reasoning, model: (
                command_with_reasoning_effort(agent, command, reasoning, model, validate_effort=validate_reasoning_effort)
            ),
            command_with_session=command_with_claude_session,
            with_effort_mode_guidance=with_effort_mode_guidance,
            record_progress=partial(record_planning_progress, state_lock=resources.state_lock),
            conversation_id=planning_conversation_id,
            invoke_provider=provider.invoke,
        )

    def preparation() -> PlanningPreparation:
        return PlanningPreparation(
            repo=resources.repo,
            main_branch=resources.config.project.main_branch,
            default_agent_id=resources.config.planning.agent_id,
            verification=InitialVerificationSettings(
                resources.config.execution.task_verify_command_timeout_seconds,
                resources.config.execution.task_verify_total_timeout_seconds,
                resources.config.execution.integration_verify_command_timeout_seconds,
                resources.config.execution.integration_verify_total_timeout_seconds,
                resources.config.execution.verification_repair_limit,
            ),
            workspace_location=lambda: resolve_workspace_location(resources.config.project),
            normalize_agent_id=normalize_agent_id,
            normalize_model=normalize_model,
            normalize_effort=normalize_reasoning_effort,
            normalize_mode=normalize_planning_mode,
            ensure_git_ready=ensure_git_ready,
            available_agent=availability.require,
            ensure_provider_ready=ensure_provider_ready,
            validate_effort=validate_reasoning_effort,
            read_base_commit=base_commit,
            source_index_for_start=source_indexes().for_start,
        )

    def content() -> PlanContentApplication:
        return PlanContentApplication(
            snapshot_sources=snapshot_sources,
            review_required=lambda: resources.config.routing.review_required,
            replace_decision=replace_decision,
            build_bootstrap=build_bootstrap,
        )

    def pending() -> PendingTaskChanges:
        return PendingTaskChanges(
            records=PendingTaskChangeRecords(resources.store.save, resources.store.save_planning_chat),
            build_plan=ai.build_plan,
            clarification_context=clarification_context,
            source_index=source_indexes().snapshot,
            task_editable=planning_task_editable,
            task_draft=task_plan_draft,
            append_assistant=messages.append_assistant,
        )

    def conversation() -> ConversationPlanApplication:
        return ConversationPlanApplication(
            build_plan=ai.build_plan,
            clarification_context=clarification_context,
            source_index=source_indexes().snapshot,
            apply_plan=lifecycle.apply_plan,
            task_draft=task_plan_draft,
            save_state=resources.store.save,
            save_chat=resources.store.save_planning_chat,
        )

    def feature_application() -> FeaturePlanApplication:
        return FeaturePlanApplication(write_plan=files.write_result, append_assistant=messages.append_assistant)

    def preview_application() -> PlanningPreviewApplication:
        return PlanningPreviewApplication(
            records=PreviewApplyRecords(
                resources.store.load,
                resources.store.load_planning_apply_preview,
                resources.store.save,
                resources.store.save_planning_chat,
            ),
            validate_payload=validate_planning_preview_payload,
            find_request=planning_apply_request,
            fingerprint=previews().fingerprint,
            changes=previews().changes,
            task_fields=planning_preview_task_fields,
            apply_pending=lifecycle.apply_pending,
            apply_initial=lifecycle.apply_plan,
            public=previews().public,
        )

    def apply_workflow() -> PlanningApplyWorkflow:
        return PlanningApplyWorkflow(
            records=PlanningApplyRecords(resources.store.load, resources.store.save_planning_chat, resources.store.inspect_lock),
            execution_operations=EXECUTION_RUN_LOCK_OPERATIONS,
            normalize_request_id=normalize_planning_apply_request_id,
            find_request=planning_apply_request,
            validate_replay=validate_planning_apply_replay,
            validate_stack=validate_tech_stack_apply,
            validate_stack_replay=validate_tech_stack_apply_replay,
            new_request=new_apply_request,
            configure_profile=profiles.configure,
            append_user=messages.append_user,
            append_assistant=messages.append_assistant,
            follow_up_request=messages.follow_up,
            apply_pending=lifecycle.apply_pending,
            apply_conversation=lifecycle.apply_conversation,
        )

    def message_router() -> PlanningMessageRouter:
        return PlanningMessageRouter(
            records=PlanningMessageRecords(resources.store.load, resources.store.save_planning_chat, resources.store.planning_chat_lock),
            initial_tasks=planning_message_requests_initial_tasks,
            requests_apply=planning_message_requests_apply,
            is_apply_control=planning_message_is_apply_control,
            result_available=messages.result_available,
            execution_available=messages.execution_available,
            append_user=messages.append_user,
            send_execution=commands.send_execution_message,
            preview=commands.preview_planning_apply,
            apply_request=commands.request_planning_conversation_apply,
        )

    def confirmation() -> PlanConfirmation:
        return PlanConfirmation(
            load_policy=resources.store.load_effort_policy,
            preview=effort.previews.preview_effort_mode,
            protected_bootstrap=protected_greenfield_bootstrap,
            validate_draft=draft_validator().validate,
            task_draft=task_plan_draft,
            plan_paths=files.result_paths,
        )

    def exclusion() -> TaskPlanExclusion:
        return TaskPlanExclusion(plan_paths=files.result_paths, write_plan=files.write_result, save_state=resources.store.save)

    def revision_preparation() -> ResultRevisionProposalPreparation:
        return ResultRevisionProposalPreparation(
            default_agent_id=lambda: resources.config.planning.agent_id,
            available_agent=availability.require,
            evidence=result_revision_evidence,
            run_directory=resources.store.run_dir,
        )

    def new_apply_request(
        state: RunState,
        request_id: str,
        expected_revision: int,
        conversation_revision: int,
        *,
        status: PlanningApplyStatus,
        answer_message: str='',
        tech_stack_revision: int | None=None,
    ) -> PlanningApplyRequest:
        return PlanningApplyRequests(append_user=messages.append_user, clarification_context=clarification_context).create(
            state,
            request_id,
            expected_revision,
            conversation_revision,
            status=status,
            answer_message=answer_message,
            tech_stack_revision=tech_stack_revision,
        )
    profiles = planning_profiles()
    messages = PlanningMessages(
        lambda run_id: resources.store.run_dir(run_id),
        lambda run_id: resources.store.inspect_lock(run_id),
        EXECUTION_RUN_LOCK_OPERATIONS,
    )
    ai = PlanningAI(
        policy_scope,
        resources.planning_effort,
        plan_runner,
        chat_runner,
        invocation,
        lambda: resources.config.planning.timeout_seconds,
        lambda: resources.codex_sdk is not None,
        lambda: resources.repo,
        lambda: resources.config.agents,
        lambda: resources.config.routing,
        lambda: tuple(resources.nvidia_model_api_keys),
        lambda: providers.choices.planning_execution_agents(),
    )
    intake = PlanningIntake(
        lambda run_id: resources.store.state_path(run_id),
        lambda run_id: resources.store.run_dir(run_id),
        lambda state: resources.store.save(state),
        lambda state, mode, **options: resources.store.initialize_effort_mode(state, mode, **options),
        preparation,
        repository_context,
    )
    lifecycle = PlanningLifecycle(
        lambda run_id: resources.store.run_dir(run_id),
        lambda state: resources.store.save(state),
        lambda state: resources.store.save_planning_chat(state),
        ai,
        messages,
        profiles,
        files,
        source_indexes,
        content,
        pending,
        conversation,
        feature_application,
        task_preparation,
        lambda: resources.codex_sdk,
    )
    proposals = ResultRevisionAI(
        revision_preparation,
        lambda **options: provider.invoke(**options),
        lambda: resources.codex_sdk,
        lambda: resources.config.planning.timeout_seconds,
    )
    commands = PlanningCommands(
        records=PlanningCommandRecords(
            load=lambda run_id: resources.store.load(run_id),
            save=lambda state: resources.store.save(state),
            save_chat=lambda state: resources.store.save_planning_chat(state),
            state_path=lambda run_id: resources.store.state_path(run_id),
            run_dir=lambda run_id: resources.store.run_dir(run_id),
            run_lock=lambda run_id, operation: resources.store.lock(run_id, operation),
            chat_lock=lambda run_id, operation='planning-chat': resources.store.planning_chat_lock(run_id, operation),
            revision_proposals_lock=lambda run_id: resources.store.revision_proposals_lock(run_id),
            revision_requests_lock=lambda run_id: resources.store.revision_requests_lock(run_id),
            inspect_chat_lock=lambda run_id: resources.store.inspect_planning_chat_lock(run_id),
            save_preview_progress=lambda run_id, progress: resources.store.save_planning_preview_progress(run_id, progress),
            initialize_effort=lambda state, mode, **options: resources.store.initialize_effort_mode(state, mode, **options),
        ),
        intake=intake,
        ai=ai,
        lifecycle=lifecycle,
        messages=messages,
        profiles=profiles,
        lookup=lookup,
        files=files,
        repository=lambda: resources.repo,
        main_branch=lambda: resources.config.project.main_branch,
        workspace_location=lambda: resolve_workspace_location(resources.config.project),
        read_head=lambda: resources.git.head(resources.repo, non_interactive=True, timeout_seconds=PLANNING_INDEX_TIMEOUT_SECONDS),
        ensure_git_ready=ensure_git_ready,
        ensure_verification=lambda state: verification_settings().ensure_verification(state),
        configured_agents=lambda: resources.config.agents,
        execution_capabilities=lambda : (
            sorted({capability for agent in resources.config.agents if not agent.manual_only for capability in agent.capabilities})
        ),
        tool_connections=lambda : (
            [
                {'id': server.id, 'label': server.label, 'transport': server.transport, 'status': 'configured'}
                for server in resources.config.worker_mcp_servers
                if server.enabled
            ]
        ),
        repository_context=repository_context,
        source_indexes=source_indexes,
        result_revisions=result_revisions,
        previews=previews,
        preview_application=preview_application,
        apply_workflow=apply_workflow,
        message_router=message_router,
        draft_validator=draft_validator,
        confirmation=confirmation,
        exclusion=exclusion,
        bootstrap=lambda: BootstrapPlanner(resources.repo),
    )
    return commands
