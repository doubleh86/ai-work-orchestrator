"""Compose execution and control owners from narrow per-role ports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable
from .execution import ExecutionControlService, TaskExecutionPreparation, TaskRetryGuidance
from .execution.control_messages import ExecutionMessages
from .execution.flow import ExecutionFlow
from .execution.lifecycle import StoredStopSignal, make_stored_stop_signal
from .execution.operation_lifecycle import RunStepLifecycle
from .execution.policy_lifecycle import ExecutionPolicyLifecycle
from .execution.profile_workflows import ExecutionProfiles
from .execution.provider_choices import ProviderAvailability
from .execution.provider_runtime import ProviderRuntime
from .execution.task_workflows import TaskWorkflows
from .execution.verification_commands import VerificationCommands
from .execution.verification_sandbox import VerificationSandbox
from .integration.recovery_flow import RecoveryFlow
from .integration.verification_flow import VerificationFlow
from .integration.workspace_access import WorkspaceAccess
from .models import RunState, WorkTask
from .orchestration.control import RunControlCommands
from .orchestration.effort import EffortCommands
from .orchestration.execution import ExecutionCommands
from .orchestration.planning import PlanningCommands
from .orchestration.providers import ProviderQueries
from .orchestration.queries import RunQueries
from .orchestration.scope_approval import ScopeApprovalActions
from .persistence.execution_records import (
    ExecutionCommandsRecords,
    ExecutionFlowRecords,
    ExecutionMessagesRecords,
    ExecutionPolicyLifecycleRecords,
    ExecutionProfilesRecords,
    RecoveryFlowRecords,
    RunControlCommandsRecords,
    ScopeApprovalActionsRecords,
    TaskWorkflowsRecords,
    VerificationCommandsRecords,
    VerificationFlowRecords,
    WorkspaceAccessRecords,
)
from .persistence.run_lookup import RunLookup
from .planning.plan_files import PlanFiles
from .planning.policy_scope import PlanningPolicyScope
from .queries.scope_proposals import ScopeProposalQueries

if TYPE_CHECKING:
    from .pipeline_bootstrap import PipelineResources


@dataclass(frozen=True, slots=True)
class ExecutionRuntime:
    workspace: WorkspaceAccess
    profiles: ExecutionProfiles
    policy: ExecutionPolicyLifecycle
    verification_commands: VerificationCommands
    tasks: TaskWorkflows
    flow: ExecutionFlow
    messages: ExecutionMessages
    recovery: RecoveryFlow
    verification: VerificationFlow
    scope: ScopeApprovalActions
    execution_commands: ExecutionCommands
    control: RunControlCommands


def build_execution_runtime(
    resources: PipelineResources,
    *,
    execution_control: ExecutionControlService,
    steps: RunStepLifecycle,
    planning_policy: PlanningPolicyScope,
    runs: RunQueries,
    providers: ProviderQueries,
    effort: EffortCommands,
    lookup: RunLookup,
    plan_files: PlanFiles,
    availability: ProviderAvailability,
    retry_guidance: TaskRetryGuidance,
    scope_proposals: ScopeProposalQueries,
    provider: ProviderRuntime[StoredStopSignal],
    planning: PlanningCommands,
    task_preparation: Callable[[], TaskExecutionPreparation],
) -> ExecutionRuntime:
    def stop_signal(state: RunState, task: WorkTask | None = None, *, scope: str = "task") -> StoredStopSignal | None:
        return make_stored_stop_signal(resources.store.load_execution_control, state, task, scope=scope)

    workspace = WorkspaceAccess(
        records=WorkspaceAccessRecords(
            load=lambda *args, **options: resources.store.load(*args, **options),
        ),
        integration_inspector=runs.controls.inspector,
        project_settings=lambda: resources.config.project,
        read_git=lambda: resources.git,
    )

    profiles = ExecutionProfiles(
        records=ExecutionProfilesRecords(
            inspect_lock=lambda *args, **options: resources.store.inspect_lock(*args, **options),
            load=lambda *args, **options: resources.store.load(*args, **options),
            load_effort_policy=lambda *args, **options: resources.store.load_effort_policy(*args, **options),
            load_task_execution_profiles=lambda *args, **options: resources.store.load_task_execution_profiles(*args, **options),
            planning_chat_lock=lambda *args, **options: resources.store.planning_chat_lock(*args, **options),
            save=lambda *args, **options: resources.store.save(*args, **options),
            save_task_execution_profiles=lambda *args, **options: resources.store.save_task_execution_profiles(*args, **options),
        ),
        availability=availability,
        registered_models=lambda: tuple(resources.nvidia_model_api_keys),
        read_agents=lambda: resources.agents,
        agents_settings=lambda: resources.config.agents,
        files=plan_files,
        lookup=lookup,
        usage=resources.account_usage,
        connections=providers.connections,
        routing_settings=lambda: resources.config.routing,
        state_lock=resources.state_lock,
    )

    policy = ExecutionPolicyLifecycle(
        records=ExecutionPolicyLifecycleRecords(
            abandon_effort_execution=lambda *args, **options: resources.store.abandon_effort_execution(*args, **options),
            finish_effort_execution=lambda *args, **options: resources.store.finish_effort_execution(*args, **options),
            load=lambda *args, **options: resources.store.load(*args, **options),
            load_effort_policy=lambda *args, **options: resources.store.load_effort_policy(*args, **options),
            load_task_execution_profiles=lambda *args, **options: resources.store.load_task_execution_profiles(*args, **options),
            prepare_effort_execution=lambda *args, **options: resources.store.prepare_effort_execution(*args, **options),
            save=lambda *args, **options: resources.store.save(*args, **options),
            start_effort_execution=lambda *args, **options: resources.store.start_effort_execution(*args, **options),
        ),
        availability=availability,
        previews=effort.previews,
        read_agents=lambda: resources.agents,
        planning_settings=lambda: resources.config.planning,
        profiles=profiles,
    )

    verification_commands = VerificationCommands(
        records=VerificationCommandsRecords(
            run_dir=lambda *args, **options: resources.store.run_dir(*args, **options),
        ),
        read_git=lambda: resources.git,
        execution_settings=lambda: resources.config.execution,
        read_dotnet_executable=lambda: resources.dotnet_executable,
        sandbox=VerificationSandbox(resources.repo, resources.store.root),
    )

    tasks = TaskWorkflows(
        records=TaskWorkflowsRecords(
            load_effort_policy=lambda *args, **options: resources.store.load_effort_policy(*args, **options),
            load_execution_control=lambda *args, **options: resources.store.load_execution_control(*args, **options),
            run_dir=lambda *args, **options: resources.store.run_dir(*args, **options),
            save=lambda *args, **options: resources.store.save(*args, **options),
        ),
        control=execution_control,
        state_lock=resources.state_lock,
        stop_signal=stop_signal,
        execution_settings=lambda: resources.config.execution,
        read_git=lambda: resources.git,
        workspace=workspace,
        read_agents=lambda: resources.agents,
        routing_settings=lambda: resources.config.routing,
        verification_commands=verification_commands,
        read_dotnet_executable=lambda: resources.dotnet_executable,
        profiles=profiles,
        retry_guidance=retry_guidance,
        provider=provider,
        policy=policy,
    )

    flow = ExecutionFlow(
        records=ExecutionFlowRecords(
            load=lambda *args, **options: resources.store.load(*args, **options),
            load_task_execution_profiles=lambda *args, **options: resources.store.load_task_execution_profiles(*args, **options),
            planning_chat_lock=lambda *args, **options: resources.store.planning_chat_lock(*args, **options),
            save=lambda *args, **options: resources.store.save(*args, **options),
            save_planning_chat=lambda *args, **options: resources.store.save_planning_chat(*args, **options),
        ),
        tasks=tasks,
        workspace=workspace,
        verification_commands=verification_commands,
        lookup=lookup,
        profiles=profiles,
        policy=policy,
        availability=availability,
        read_agents=lambda: resources.agents,
        ensure_verification=planning.ensure_verification,
        preparation=task_preparation,
        steps=steps,
        bootstrap=planning.bootstrap,
        control=execution_control,
        state_lock=resources.state_lock,
        execution_settings=lambda: resources.config.execution,
    )

    messages = ExecutionMessages(
        records=ExecutionMessagesRecords(
            load=lambda *args, **options: resources.store.load(*args, **options),
            planning_chat_lock=lambda *args, **options: resources.store.planning_chat_lock(*args, **options),
            save_planning_chat=lambda *args, **options: resources.store.save_planning_chat(*args, **options),
        ),
        planning_messages=planning.messages,
    )

    recovery = RecoveryFlow(
        records=RecoveryFlowRecords(
            claim_operation=lambda *args, **options: resources.store.claim_operation(*args, **options),
            inspect_lock=lambda *args, **options: resources.store.inspect_lock(*args, **options),
            latest_operation=lambda *args, **options: resources.store.latest_operation(*args, **options),
            list_runs=lambda *args, **options: resources.store.list_runs(*args, **options),
            load=lambda *args, **options: resources.store.load(*args, **options),
            load_operation=lambda *args, **options: resources.store.load_operation(*args, **options),
            load_operation_result=lambda *args, **options: resources.store.load_operation_result(*args, **options),
            save_operation=lambda *args, **options: resources.store.save_operation(*args, **options),
            save_operation_result=lambda *args, **options: resources.store.save_operation_result(*args, **options),
        ),
        workspace=workspace,
        read_git=lambda: resources.git,
        read_repo=lambda: resources.repo,
        planning_lifecycle=planning.lifecycle,
        planning_policy=planning_policy,
    )

    verification = VerificationFlow(
        records=VerificationFlowRecords(
            load=lambda *args, **options: resources.store.load(*args, **options),
            planning_chat_lock=lambda *args, **options: resources.store.planning_chat_lock(*args, **options),
            run_dir=lambda *args, **options: resources.store.run_dir(*args, **options),
            save=lambda *args, **options: resources.store.save(*args, **options),
        ),
        planning_lifecycle=planning.lifecycle,
        control=execution_control,
        verification_commands=verification_commands,
        availability=availability,
        workspace=workspace,
        provider=provider,
        stop_signal=stop_signal,
        tasks=tasks,
        agents_settings=lambda: resources.config.agents,
        read_git=lambda: resources.git,
        ensure_verification=planning.ensure_verification,
        lookup=lookup,
        steps=steps,
        execution_settings=lambda: resources.config.execution,
        read_repo=lambda: resources.repo,
    )

    scope = ScopeApprovalActions(
        records=ScopeApprovalActionsRecords(
            claim_operation=lambda *args, **options: resources.store.claim_operation(*args, **options),
            load=lambda *args, **options: resources.store.load(*args, **options),
            load_effort_policy=lambda *args, **options: resources.store.load_effort_policy(*args, **options),
            load_execution_control=lambda *args, **options: resources.store.load_execution_control(*args, **options),
            load_operation=lambda *args, **options: resources.store.load_operation(*args, **options),
            load_planning_apply_preview=lambda *args, **options: resources.store.load_planning_apply_preview(*args, **options),
            lock=lambda *args, **options: resources.store.lock(*args, **options),
            planning_chat_lock=lambda *args, **options: resources.store.planning_chat_lock(*args, **options),
            recent_operations=lambda *args, **options: resources.store.recent_operations(*args, **options),
            request_control_lock=lambda *args, **options: resources.store.request_control_lock(*args, **options),
            save=lambda *args, **options: resources.store.save(*args, **options),
            save_operation=lambda *args, **options: resources.store.save_operation(*args, **options),
        ),
        planning_lifecycle=planning.lifecycle,
        proposals=scope_proposals,
        flow=flow,
        control=execution_control,
        files=plan_files,
        planning_previews=planning.previews,
    )

    execution_commands = ExecutionCommands(
        records=ExecutionCommandsRecords(
            claim_operation=lambda *args, **options: resources.store.claim_operation(*args, **options),
            inspect_lock=lambda *args, **options: resources.store.inspect_lock(*args, **options),
            latest_operation=lambda *args, **options: resources.store.latest_operation(*args, **options),
            load=lambda *args, **options: resources.store.load(*args, **options),
            load_execution_control=lambda *args, **options: resources.store.load_execution_control(*args, **options),
            load_operation=lambda *args, **options: resources.store.load_operation(*args, **options),
            lock=lambda *args, **options: resources.store.lock(*args, **options),
            planning_chat_lock=lambda *args, **options: resources.store.planning_chat_lock(*args, **options),
            request_control_lock=lambda *args, **options: resources.store.request_control_lock(*args, **options),
            revision_requests_lock=lambda *args, **options: resources.store.revision_requests_lock(*args, **options),
            save=lambda *args, **options: resources.store.save(*args, **options),
            save_operation=lambda *args, **options: resources.store.save_operation(*args, **options),
        ),
        lookup=lookup,
        profiles=profiles,
        flow=flow,
        control=execution_control,
        scope=scope,
        proposals=scope_proposals,
        tasks=tasks,
        retry_guidance=retry_guidance,
        read_git=lambda: resources.git,
        policy=policy,
        read_repo=lambda: resources.repo,
        steps=steps,
        workspace=workspace,
        execution_settings=lambda: resources.config.execution,
    )

    control = RunControlCommands(
        records=RunControlCommandsRecords(
            claim_operation=lambda *args, **options: resources.store.claim_operation(*args, **options),
            clear_stale_lock=lambda *args, **options: resources.store.clear_stale_lock(*args, **options),
            inspect_lock=lambda *args, **options: resources.store.inspect_lock(*args, **options),
            inspect_planning_chat_lock=lambda *args, **options: resources.store.inspect_planning_chat_lock(*args, **options),
            latest_operation=lambda *args, **options: resources.store.latest_operation(*args, **options),
            load=lambda *args, **options: resources.store.load(*args, **options),
            load_execution_control=lambda *args, **options: resources.store.load_execution_control(*args, **options),
            load_operation=lambda *args, **options: resources.store.load_operation(*args, **options),
            load_revision_requests=lambda *args, **options: resources.store.load_revision_requests(*args, **options),
            lock=lambda *args, **options: resources.store.lock(*args, **options),
            planning_chat_lock=lambda *args, **options: resources.store.planning_chat_lock(*args, **options),
            request_control_lock=lambda *args, **options: resources.store.request_control_lock(*args, **options),
            revision_requests_lock=lambda *args, **options: resources.store.revision_requests_lock(*args, **options),
            run_dir=lambda *args, **options: resources.store.run_dir(*args, **options),
            save=lambda *args, **options: resources.store.save(*args, **options),
            save_operation=lambda *args, **options: resources.store.save_operation(*args, **options),
            save_operation_result=lambda *args, **options: resources.store.save_operation_result(*args, **options),
            save_planning_chat=lambda *args, **options: resources.store.save_planning_chat(*args, **options),
            save_revision_requests=lambda *args, **options: resources.store.save_revision_requests(*args, **options),
        ),
        control=execution_control,
        messages=messages,
        recovery=recovery,
        planning_messages=planning.messages,
        planning_profiles=planning.profiles,
        workspace=workspace,
        sdk=lambda: resources.codex_sdk,
        proposals=scope_proposals,
        tasks=tasks,
        scope=scope,
        execution=execution_commands,
        runs=runs,
        planning_ai=planning.ai,
        planning_policy=planning_policy,
        flow=flow,
        verification=verification,
        planning=planning,
        availability=availability,
        connections=providers.connections,
        lookup=lookup,
        profiles=profiles,
        agents_settings=lambda: resources.config.agents,
        retry_guidance=retry_guidance,
        ensure_verification=planning.ensure_verification,
        execution_settings=lambda: resources.config.execution,
    )

    return ExecutionRuntime(
        workspace,
        profiles,
        policy,
        verification_commands,
        tasks,
        flow,
        messages,
        recovery,
        verification,
        scope,
        execution_commands,
        control,
    )
