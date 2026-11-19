"""Compose per-Pipeline resources and scopes without commands."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Callable, ContextManager, Mapping

from .account_usage import AccountUsage, AccountUsageCache
from .claude_credentials import current_claude_api_key
from .code_style import ProjectCodeStylePreference
from .codex_sdk import CodexSdkManager
from .config import AgentConfig, Config
from .execution.lifecycle import ExecutionControlRecords, ExecutionControlService, make_stored_stop_signal
from .execution.operation_lifecycle import RunStepLifecycle, RunStepRecords
from .execution.provider_choices import ProviderAvailability, ProviderChoiceQueries, ConnectedProviderQueries
from .execution.effort_previews import EffortPreviewQueries
from .execution.provider_status import ProviderStatusQueries
from .execution import provider_connection
from .execution import EffortPreviewBuilder, EffortQueries, EffortQueryRecords, EffortPlanApplicator, TaskRetryGuidance, RetryGuidanceRecords
from .execution import ready_tasks, scope_contract_digest, task_scope_review
from .execution.effort_plan import EffortPlanApplication
from .execution.retry_guidance import task_verification_timed_out
from .execution.provider_commands import agent_command
from .execution.results import committed_result_files, record_group_result
from .git import GitWorkspace, LOCAL_GIT_TIMEOUT_SECONDS
from .integration import IntegrationInspector
from .models import EffortPlanningBinding, EffortPolicyState, ResolvedEffortPolicy, RunState, WorkTask
from .notifications import NotificationCollector, retry_wait_event, synchronize_notification_events
from .nvidia_agent import current_nvidia_api_key, current_nvidia_model_keys, nvidia_key_configured, with_nvidia_agent
from .planning.policy_scope import PlanningPolicyRecords, PlanningPolicyScope
from .planning.plan_files import PlanFiles
from .persistence.run_lookup import RunLookup, find_task
from .queries import RunSummaryQueries, RunSummaryRecords, WaitingPromptQueries, WaitingPromptRecords
from .queries.control import RunControlQueries
from .queries.scope_proposals import ScopeProposalQueries
from .run_queries import active_group_kind, attention_decision, summary_attention_reasons, user_checks
from .orchestration.queries import RunQueries, RunQueryRecords
from .orchestration.providers import ProviderQueries
from .orchestration.effort import EffortCommands, EffortCommandRecords
from .orchestration.planning import PlanningCommands
from .execution.provider_runtime import ProviderRuntime
from .execution.lifecycle import StoredStopSignal
from .execution.preparation import TaskExecutionPreparation
from .pipeline_provider_bootstrap import build_provider_runtime
from .pipeline_planning_bootstrap import build_planning_commands
from .store import StateStore
from .windows_paths import filesystem_path
from .pipeline_execution_bootstrap import ExecutionRuntime, build_execution_runtime
from .pipeline_integration_bootstrap import IntegrationRuntime, build_integration_runtime


@dataclass(slots=True)
class PipelineResources:
    """Private composition state; feature constructors receive narrow ports."""

    config: Config
    repo: Path
    store: StateStore
    git: GitWorkspace
    agents: dict[str, AgentConfig]
    codex_sdk: CodexSdkManager | None
    account_usage: AccountUsageCache
    dotnet_executable: str
    code_style_preference: ProjectCodeStylePreference
    code_style_preference_revision: int
    state_lock: ContextManager[object]
    planning_effort: ContextVar[tuple[str, str, ResolvedEffortPolicy] | None]
    nvidia_api_key: str | None = field(repr=False)
    claude_api_key: str | None = field(repr=False)
    nvidia_model_api_keys: Mapping[str, str] = field(repr=False)


@dataclass(frozen=True, slots=True)
class PipelineRuntime:
    resources: PipelineResources
    execution_control: ExecutionControlService
    steps: RunStepLifecycle
    planning_policy: PlanningPolicyScope
    runs: RunQueries
    providers: ProviderQueries
    effort: EffortCommands
    lookup: RunLookup
    plan_files: PlanFiles
    availability: ProviderAvailability
    retry_guidance: TaskRetryGuidance
    scope_proposals: ScopeProposalQueries
    provider_probes: provider_connection.ProviderConnectionProbes
    provider: ProviderRuntime[StoredStopSignal]
    planning: PlanningCommands
    task_preparation: Callable[[], TaskExecutionPreparation]
    execution: ExecutionRuntime
    integration: IntegrationRuntime


def build_pipeline_runtime(
    config: Config,
    *,
    codex_sdk: CodexSdkManager | None = None,
    dotnet_executable: str = "",
    code_style_preference: ProjectCodeStylePreference | None = None,
    code_style_preference_revision: int = 0,
    account_usage_reader: Callable[[str], AccountUsage] | None = None,
) -> PipelineRuntime:
    config = with_nvidia_agent(config)
    # Preserve request credentials across worker threads and later requests.
    nvidia_api_key = current_nvidia_api_key()
    claude_api_key = current_claude_api_key()
    nvidia_model_api_keys = current_nvidia_model_keys()
    repo = filesystem_path(config.project.repo)
    project_key = str(repo.expanduser().resolve())
    deployment_configured = bool(config.execution.deploy_command)
    resources = PipelineResources(
        config=config,
        repo=repo,
        store=StateStore(
            repo / config.project.state_dir,
            notification_sync=lambda state: synchronize_notification_events(
                state, project_key=project_key, deployment_configured=deployment_configured,
            ),
        ),
        git=GitWorkspace(repo, config.project.main_branch),
        agents={agent.id: agent for agent in config.agents},
        codex_sdk=codex_sdk,
        account_usage=AccountUsageCache(account_usage_reader),
        dotnet_executable=dotnet_executable,
        code_style_preference=code_style_preference or ProjectCodeStylePreference(),
        code_style_preference_revision=code_style_preference_revision,
        state_lock=RLock(),
        planning_effort=ContextVar("planning_effort", default=None),
        nvidia_api_key=nvidia_api_key,
        claude_api_key=claude_api_key,
        nvidia_model_api_keys=nvidia_model_api_keys,
    )
    control = ExecutionControlService(ExecutionControlRecords(
        control_lock=lambda run_id: resources.store.execution_control_lock(run_id),
        load_control=lambda run_id: resources.store.load_execution_control(run_id),
        save_control=lambda record: resources.store.save_execution_control(record),
        load_operation=lambda run_id, request_id: resources.store.load_operation(run_id, request_id),
        claim_operation=lambda operation: resources.store.claim_operation(operation),
        save_operation=lambda operation: resources.store.save_operation(operation),
        save_result=lambda run_id, request_id, value: resources.store.save_operation_result(run_id, request_id, value),
    ))
    steps = RunStepLifecycle(
        records=RunStepRecords(
            control_lock=lambda run_id: resources.store.execution_control_lock(run_id),
            load_control=lambda run_id: resources.store.load_execution_control(run_id),
            save_control=lambda record: resources.store.save_execution_control(record),
            save_state=lambda state: resources.store.save(state),
        ),
        command_timeout=lambda: resources.config.execution.integration_verify_command_timeout_seconds,
        total_timeout=lambda: resources.config.execution.integration_verify_total_timeout_seconds,
        stop_signal=lambda state: make_stored_stop_signal(resources.store.load_execution_control, state, scope="verification"),
        record_checkpoint=lambda state, request_id: control.record_checkpoint(state, request_id),
        confirm_stopped=control.confirm_stopped,
        record_group_result=lambda state: record_group_result(
            state, read_commit_files=lambda baseline, result: committed_result_files(resources.git, baseline, result),
        ),
    )

    def policy_path(run_id: str, *, archived_chat: bool = False) -> Path:
        return resources.store.effort_policy_path(run_id, archived_chat=archived_chat)

    def load_policy(run_id: str, *, archived_chat: bool = False) -> EffortPolicyState:
        return resources.store.load_effort_policy(run_id, archived_chat=archived_chat)

    def prepare_policy(
        run_id: str, policy: ResolvedEffortPolicy, *, request_id: str, expected_revision: int, purpose: str,
        archived_chat: bool = False,
    ) -> EffortPlanningBinding:
        return resources.store.prepare_effort_planning(
            run_id, policy, request_id=request_id, expected_revision=expected_revision, purpose=purpose, archived_chat=archived_chat,
        )

    def finish_policy(
        run_id: str, request_id: str, *, failed: bool = False, archived_chat: bool = False,
    ) -> EffortPlanningBinding:
        return resources.store.finish_effort_planning(run_id, request_id, failed=failed, archived_chat=archived_chat)

    provider_probes = provider_connection.ProviderConnectionProbes(
        resolve_executable=lambda value: provider_connection.resolve_provider_executable(value),
        claude_auth=lambda executable, api_key: provider_connection.claude_auth_status(executable, api_key),
    )
    availability = ProviderAvailability(
        read_agent=lambda agent_id: resources.agents.get(agent_id), sdk_ready=lambda: resources.codex_sdk is not None,
        nvidia_ready=lambda: bool(resources.nvidia_model_api_keys or nvidia_key_configured(api_key=resources.nvidia_api_key)),
        command=agent_command, resolve_executable=lambda value: provider_probes.resolve_executable(value),
    )

    planning_policy = PlanningPolicyScope(
        context=resources.planning_effort,
        records=PlanningPolicyRecords(policy_path, load_policy, prepare_policy, finish_policy),
        default_agent_id=lambda: resources.config.planning.agent_id,
        available_agent=availability.require,
    )
    lookup = RunLookup(lambda run_id: resources.store.load(run_id), lambda run_id: resources.store.state_path(run_id))
    plan_files = PlanFiles(lambda run_id: resources.store.run_dir(run_id))
    scope_proposals = ScopeProposalQueries(
        repository=lambda: resources.repo, load_control=lambda run_id: resources.store.load_execution_control(run_id),
    )

    def record_retry_wait(
        state: RunState, task: WorkTask, request_id: str, *, completed: bool = False, occurred_at: str = "",
    ) -> None:
        event = retry_wait_event(state, str(resources.repo.expanduser().resolve()), task, request_id,
                                 completed=completed, occurred_at=occurred_at)
        resources.store.save_notification_event(event)

    retry_guidance = TaskRetryGuidance(
        records=RetryGuidanceRecords(
            load_run=lambda run_id: resources.store.load(run_id), load_requests=lambda run_id: resources.store.load_revision_requests(run_id),
            save_requests=lambda run_id, requests: resources.store.save_revision_requests(run_id, requests),
            load_control=lambda run_id: resources.store.load_execution_control(run_id), save_state=lambda state: resources.store.save(state),
        ),
        find_task=find_task, scope_review=task_scope_review, scope_proposal=scope_proposals.proposal,
        scope_digest=scope_contract_digest, verification_timed_out=task_verification_timed_out,
        command_timeout=lambda: resources.config.execution.task_verify_command_timeout_seconds,
        total_timeout=lambda: resources.config.execution.task_verify_total_timeout_seconds,
        worktree_head=lambda path: resources.git.head(path, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS),
        dotnet_executable=lambda: resources.dotnet_executable, record_wait=record_retry_wait,
    )

    def integration_inspector() -> IntegrationInspector:
        return IntegrationInspector(
            resources.git, resources.config.project.remote, (resources.store.root,),
            resources.store.latest_operation, resources.store.inspect_project_git_lock,
        )

    controls = RunControlQueries(
        inspect_lock=lambda run_id: resources.store.inspect_lock(run_id),
        load_control=lambda run_id: resources.store.load_execution_control(run_id),
        read_branch=lambda: resources.git.current_branch(non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS),
        inspector=integration_inspector,
    )

    def summaries() -> RunSummaryQueries:
        return RunSummaryQueries(
            records=RunSummaryRecords(resources.store.list_runs, resources.store.list_run_summaries,
                                      resources.store.inspect_lock, resources.store.inspect_planning_chat_lock),
            deployment_configured=lambda: bool(resources.config.execution.deploy_command),
            remote_configured=lambda: resources.git.remote_configured(resources.config.project.remote),
            execution_control=controls.summary_control, attention_reasons=summary_attention_reasons,
            attention_decision=attention_decision, active_group_kind=active_group_kind,
            user_checks=user_checks, waiting_prompt=lambda state, control: waiting().waiting_prompt(state, control),
        )

    def waiting() -> WaitingPromptQueries:
        return WaitingPromptQueries(
            resources.repo,
            WaitingPromptRecords(resources.store.inspect_lock, resources.store.inspect_planning_chat_lock,
                                 resources.store.load_notification_events),
            retry_guidance.context, ready_tasks,
        )

    runs = RunQueries(
        records=RunQueryRecords(
            load=lambda run_id: resources.store.load(run_id), list_runs=lambda: resources.store.list_runs(),
            run_dir=lambda run_id: resources.store.run_dir(run_id),
            latest_operation=lambda run_id, action: resources.store.latest_operation(run_id, action),
            usage_snapshot=lambda run_id, **options: resources.store.usage_snapshot(run_id, **options),
        ),
        repository=lambda: resources.repo, dotnet_executable=lambda: resources.dotnet_executable,
        controls=controls, summaries=summaries, waiting=waiting,
        notification_collector=NotificationCollector(
            project_key=lambda: str(resources.repo.expanduser().resolve()),
            deployment_configured=lambda: bool(resources.config.execution.deploy_command),
            read_runs=lambda: resources.store.list_runs(), load_events=lambda run_id: resources.store.load_notification_events(run_id),
        ),
    )

    def provider_status_queries() -> ProviderStatusQueries:
        return ProviderStatusQueries(
            read_agents=lambda: resources.config.agents,
            read_codex_account=resources.codex_sdk.account_status if resources.codex_sdk is not None else None,
            probe_executable=provider_probes.executable,
            nvidia_configured=lambda: bool(resources.nvidia_model_api_keys) or nvidia_key_configured(api_key=resources.nvidia_api_key),
            nvidia_app_key=lambda: bool(resources.nvidia_api_key or resources.nvidia_model_api_keys),
            read_claude_auth=lambda executable: provider_probes.claude_auth(executable, resources.claude_api_key),
        )

    connections = ConnectedProviderQueries(lambda provider_id: provider_status_queries().statuses(provider_id))
    choice_queries = ProviderChoiceQueries(
        read_agents=lambda: resources.config.agents, balance_providers=lambda: resources.config.routing.balance_providers,
        is_available=lambda agent, action: availability.is_available(agent, action), is_selectable=availability.is_selectable,
        connected_providers=lambda provider_ids: connections.ids(provider_ids), read_usage=resources.account_usage.read,
    )
    providers = ProviderQueries(choice_queries, provider_status_queries, lambda: resources.config.planning.agent_id, connections)

    def effort_preview_builder() -> EffortPreviewBuilder:
        return EffortPreviewBuilder(
            agents=resources.agents, configured_agents=resources.config.agents,
            default_planning_agent_id=resources.config.planning.agent_id, review_required=resources.config.routing.review_required,
            reviewer_compatible=availability.reviewer_compatible,
            is_selectable=availability.is_selectable, is_available=lambda agent, action: availability.is_available(agent, action),
        )

    effort_previews = EffortPreviewQueries(lambda run_id: resources.store.load(run_id), load_policy, effort_preview_builder)

    def effort_queries() -> EffortQueries:
        return EffortQueries(
            records=EffortQueryRecords(
                load_state=resources.store.load, load_policy=resources.store.load_effort_policy,
                inspect_lock=resources.store.inspect_lock, inspect_chat_lock=resources.store.inspect_planning_chat_lock,
                has_archived_policy=lambda run_id: resources.store.effort_policy_path(run_id, archived_chat=True).exists(),
            ),
            build_preview=effort_previews.preview_effort_mode, read_agents=lambda: resources.config.agents,
            is_selectable=availability.is_selectable, connected_providers=lambda provider_ids: connections.ids(provider_ids),
            reviewer_compatible=availability.reviewer_compatible,
        )

    def effort_plan_application() -> EffortPlanApplication:
        return EffortPlanApplication(
            load_policy=resources.store.load_effort_policy, preview=effort_previews.preview_effort_mode,
            prepare=lambda state, preview, *, reviewer_agent_ids: EffortPlanApplicator(
                agents=resources.agents, default_planning_agent_id=resources.config.planning.agent_id,
                available_agent=availability.require, reviewer_compatible=availability.reviewer_compatible,
                is_selectable=availability.is_selectable,
            ).prepare(state, preview, reviewer_agent_ids=reviewer_agent_ids),
            plan_paths=plan_files.result_paths, write_plan=plan_files.write_result, save_state=resources.store.save,
            chat_exists=lambda run_id: resources.store.planning_chat_path(run_id).exists(), save_chat=resources.store.save_planning_chat,
        )

    effort = EffortCommands(
        records=EffortCommandRecords(
            load=lambda run_id: resources.store.load(run_id), load_effort_policy=load_policy,
            lock=lambda run_id, operation: resources.store.lock(run_id, operation),
            planning_chat_lock=lambda run_id: resources.store.planning_chat_lock(run_id),
            set_effort_mode=lambda run_id, mode, **options: resources.store.set_effort_mode(run_id, mode, **options),
            cancel_effort_reservation=lambda run_id, **options: resources.store.cancel_effort_reservation(run_id, **options),
        ),
        lookup=lookup, previews=effort_previews, queries=effort_queries, plan_application=effort_plan_application,
    )
    provider = build_provider_runtime(resources, provider_probes)
    planning = build_planning_commands(resources, provider=provider, policy_scope=planning_policy, providers=providers,
                                       availability=availability, lookup=lookup, files=plan_files, retry_guidance=retry_guidance, effort=effort)
    execution = build_execution_runtime(
        resources, execution_control=control, steps=steps, planning_policy=planning_policy, runs=runs, providers=providers,
        effort=effort, lookup=lookup, plan_files=plan_files, availability=availability, retry_guidance=retry_guidance,
        scope_proposals=scope_proposals, provider=provider, planning=planning, task_preparation=planning.lifecycle.task_preparation,
    )
    integration = build_integration_runtime(
        resources, steps=steps, execution_control=control, lookup=lookup, runs=runs, run_control=execution.control,
        workspace=execution.workspace, tasks=execution.tasks, verification=execution.verification, planning=planning,
        availability=availability, provider=provider,
    )
    return PipelineRuntime(resources, control, steps, planning_policy, runs, providers, effort, lookup, plan_files,
                           availability, retry_guidance, scope_proposals, provider_probes, provider, planning,
                           planning.lifecycle.task_preparation, execution, integration)
