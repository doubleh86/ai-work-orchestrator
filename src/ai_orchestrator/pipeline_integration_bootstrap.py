"""Compose integration and lifecycle commands without performing operations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from .execution import ExecutionControlService
from .execution.lifecycle import StoredStopSignal
from .execution.operation_lifecycle import RunStepLifecycle
from .execution.provider_choices import ProviderAvailability
from .execution.provider_runtime import ProviderRuntime
from .execution.task_logs import read_task_log_tail
from .execution.task_workflows import TaskWorkflows
from .integration import MainChangeService
from .integration.archive_flow import ArchiveFlow
from .integration.conflict_flow import ConflictFlow
from .integration.main_apply_flow import MainApplyFlow
from .integration.verification_flow import VerificationFlow
from .integration.workspace_access import WorkspaceAccess
from .integration.workspace_flows import WorkspaceFlows
from .orchestration.control import RunControlCommands
from .orchestration.integration import IntegrationCommands
from .orchestration.lifecycle import LifecycleCommands
from .orchestration.planning import PlanningCommands
from .orchestration.queries import RunQueries, TASK_LOG_DISPLAY_LIMIT_BYTES
from .persistence.integration_records import (
    ArchiveFlowRecords,
    ConflictFlowRecords,
    IntegrationCommandsRecords,
    LifecycleCommandsRecords,
    MainApplyFlowRecords,
    WorkspaceFlowsRecords,
)
from .persistence.run_lookup import RunLookup

if TYPE_CHECKING:
    from .pipeline_bootstrap import PipelineResources


@dataclass(frozen=True, slots=True)
class IntegrationRuntime:
    workspaces: WorkspaceFlows
    archive: ArchiveFlow
    conflicts: ConflictFlow
    main: MainApplyFlow
    integration_commands: IntegrationCommands
    lifecycle_commands: LifecycleCommands


def build_integration_runtime(
    resources: PipelineResources,
    *,
    steps: RunStepLifecycle,
    execution_control: ExecutionControlService,
    lookup: RunLookup,
    runs: RunQueries,
    run_control: RunControlCommands,
    workspace: WorkspaceAccess,
    tasks: TaskWorkflows,
    verification: VerificationFlow,
    planning: PlanningCommands,
    availability: ProviderAvailability,
    provider: ProviderRuntime[StoredStopSignal],
) -> IntegrationRuntime:
    def main_changes_service() -> MainChangeService:
        return MainChangeService(
            resources.git, resources.repo, resources.config.project.remote, resources.config.project.main_branch,
            (resources.store.root,), resources.store.save_main_change_snapshot, resources.store.load_main_change_snapshot,
        )

    def read_log_tail(path: Path) -> str:
        return read_task_log_tail(path, limit_bytes=TASK_LOG_DISPLAY_LIMIT_BYTES)

    workspaces = WorkspaceFlows(
        records=WorkspaceFlowsRecords(
            inspect_lock=lambda *args, **options: resources.store.inspect_lock(*args, **options),
            save=lambda *args, **options: resources.store.save(*args, **options),
        ),
        workspace=workspace,
        read_git=lambda: resources.git,
        read_repo=lambda: resources.repo,
        state_root=lambda: resources.store.root,
        sdk=lambda: resources.codex_sdk,
    )

    archive = ArchiveFlow(
        records=ArchiveFlowRecords(
            archive_preserved_files=lambda *args, **options: resources.store.archive_preserved_files(*args, **options),
            claim_operation=lambda *args, **options: resources.store.claim_operation(*args, **options),
            load=lambda *args, **options: resources.store.load(*args, **options),
            run_dir=lambda *args, **options: resources.store.run_dir(*args, **options),
            save=lambda *args, **options: resources.store.save(*args, **options),
            save_archive_manifest=lambda *args, **options: resources.store.save_archive_manifest(*args, **options),
            save_archive_snapshot=lambda *args, **options: resources.store.save_archive_snapshot(*args, **options),
            save_archive_summary=lambda *args, **options: resources.store.save_archive_summary(*args, **options),
            save_operation=lambda *args, **options: resources.store.save_operation(*args, **options),
        ),
        workspaces=workspaces,
        sdk=lambda: resources.codex_sdk,
        execution_settings=lambda: resources.config.execution,
        project_settings=lambda: resources.config.project,
        read_git=lambda: resources.git,
    )

    conflicts = ConflictFlow(
        records=ConflictFlowRecords(
            claim_operation=lambda *args, **options: resources.store.claim_operation(*args, **options),
            load=lambda *args, **options: resources.store.load(*args, **options),
            load_operation=lambda *args, **options: resources.store.load_operation(*args, **options),
            run_dir=lambda *args, **options: resources.store.run_dir(*args, **options),
            save=lambda *args, **options: resources.store.save(*args, **options),
            save_operation=lambda *args, **options: resources.store.save_operation(*args, **options),
        ),
        read_log_tail=read_log_tail,
        read_git=lambda: resources.git,
        read_repo=lambda: resources.repo,
        workspaces=workspaces,
        availability=availability,
        planning_settings=lambda: resources.config.planning,
        workspace=workspace,
        provider=provider,
        state_lock=resources.state_lock,
    )

    main = MainApplyFlow(
        records=MainApplyFlowRecords(
            claim_operation=lambda *args, **options: resources.store.claim_operation(*args, **options),
            load_operation=lambda *args, **options: resources.store.load_operation(*args, **options),
            run_dir=lambda *args, **options: resources.store.run_dir(*args, **options),
            save=lambda *args, **options: resources.store.save(*args, **options),
            save_operation=lambda *args, **options: resources.store.save_operation(*args, **options),
        ),
        inspector=runs.controls.inspector,
        tasks=tasks,
        read_repo=lambda: resources.repo,
        verification=verification,
        workspace=workspace,
        steps=steps,
        project_settings=lambda: resources.config.project,
        read_git=lambda: resources.git,
        state_root=lambda: resources.store.root,
        workspaces=workspaces,
        execution_settings=lambda: resources.config.execution,
    )

    integration_commands = IntegrationCommands(
        records=IntegrationCommandsRecords(
            clear_stale_lock=lambda *args, **options: resources.store.clear_stale_lock(*args, **options),
            clear_stale_project_git_lock=lambda *args, **options: resources.store.clear_stale_project_git_lock(*args, **options),
            inspect_lock=lambda *args, **options: resources.store.inspect_lock(*args, **options),
            latest_operation=lambda *args, **options: resources.store.latest_operation(*args, **options),
            load=lambda *args, **options: resources.store.load(*args, **options),
            load_operation=lambda *args, **options: resources.store.load_operation(*args, **options),
            load_result_artifact=lambda *args, **options: resources.store.load_result_artifact(*args, **options),
            lock=lambda *args, **options: resources.store.lock(*args, **options),
            planning_chat_lock=lambda *args, **options: resources.store.planning_chat_lock(*args, **options),
            project_git_lock=lambda *args, **options: resources.store.project_git_lock(*args, **options),
            save=lambda *args, **options: resources.store.save(*args, **options),
            save_operation=lambda *args, **options: resources.store.save_operation(*args, **options),
            save_result_artifact=lambda *args, **options: resources.store.save_result_artifact(*args, **options),
        ),
        main_changes_service=main_changes_service,
        project_settings=lambda: resources.config.project,
        read_git=lambda: resources.git,
        read_repo=lambda: resources.repo,
        state_root=lambda: resources.store.root,
        main=main,
        runs=runs,
        workspaces=workspaces,
        controls=runs.controls,
        verification=verification,
        steps=steps,
        workspace=workspace,
        control=execution_control,
        planning_lifecycle=planning.lifecycle,
        run_control=run_control,
        conflicts=conflicts,
        lookup=lookup,
        execution_settings=lambda: resources.config.execution,
    )

    lifecycle_commands = LifecycleCommands(
        records=LifecycleCommandsRecords(
            clear_stale_lock=lambda *args, **options: resources.store.clear_stale_lock(*args, **options),
            delete=lambda *args, **options: resources.store.delete(*args, **options),
            inspect_lock=lambda *args, **options: resources.store.inspect_lock(*args, **options),
            list_runs=lambda *args, **options: resources.store.list_runs(*args, **options),
            load=lambda *args, **options: resources.store.load(*args, **options),
            lock=lambda *args, **options: resources.store.lock(*args, **options),
            planning_chat_lock=lambda *args, **options: resources.store.planning_chat_lock(*args, **options),
            project_git_lock=lambda *args, **options: resources.store.project_git_lock(*args, **options),
            run_dir=lambda *args, **options: resources.store.run_dir(*args, **options),
            save=lambda *args, **options: resources.store.save(*args, **options),
        ),
        archive=archive,
        workspaces=workspaces,
        read_git=lambda: resources.git,
        sdk=lambda: resources.codex_sdk,
        lookup=lookup,
        workspace=workspace,
    )

    return IntegrationRuntime(workspaces, archive, conflicts, main, integration_commands, lifecycle_commands)
