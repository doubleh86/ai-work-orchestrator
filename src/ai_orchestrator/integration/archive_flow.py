"""ArchiveFlow with explicit phase and persistence dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from ..codex_sdk import CodexSdkManager
from ..config import ExecutionConfig, ProjectConfig
from ..errors import PipelineError
from ..git import GitWorkspace, LOCAL_GIT_TIMEOUT_SECONDS
from ..integration.archive_views import (
    archive_block_reasons,
    archive_commit_references,
    archive_fingerprint,
    archive_summary,
    archive_target_payload,
    archived_run_plan,
)
from ..integration.archive_workflow import ArchiveCleanupWorkflow, ArchiveRecords, RunArchiver
from ..integration.workspace_flows import WorkspaceFlows
from ..models import OperationRecord, RunState
from ..persistence.integration_records import ArchiveFlowRecords


@dataclass
class ArchiveFlow:
    records: ArchiveFlowRecords
    workspaces: WorkspaceFlows
    sdk: Callable[[], CodexSdkManager | None]
    execution_settings: Callable[[], ExecutionConfig]
    project_settings: Callable[[], ProjectConfig]
    read_git: Callable[[], GitWorkspace]

    def cleanup(self) -> ArchiveCleanupWorkflow:
        return ArchiveCleanupWorkflow(
            load_run=self.records.load, claim_operation=self.records.claim_operation,
            save_state=self.records.save, save_operation=self.records.save_operation,
            cleanup_target=self.workspaces.cleanup_archive_target, apply_cleanup=self.apply_archive_cleanup,
        )


    def apply_archive_cleanup(self, state: RunState, operation: OperationRecord) -> RunState:
        archive = state.archive
        if archive is None:
            raise PipelineError("보관 기록이 없어 작업공간을 정리할 수 없습니다.")
        if self.sdk() is not None:
            self.sdk().discard_idle_clients()
        return self.cleanup().complete_targets(state, archive, operation)


    def archive_block_reasons(self, state: RunState) -> list[str]:
        return archive_block_reasons(
            state, remote_configured=self.read_git().remote_configured(self.project_settings().remote),
            deployment_configured=bool(self.execution_settings().deploy_command),
        )


    def protect_archive_commits(self, state: RunState) -> list[dict[str, str]]:
        protected: list[dict[str, str]] = []
        for reference, commit in archive_commit_references(state):
            self.read_git().protect_archive_ref(reference, commit, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            protected.append({"ref": reference, "commit": commit})
        return protected


    def archived_run_plan(self, state: RunState) -> dict[str, object]:
        return archived_run_plan(state, run_directory=self.records.run_dir)


    def archiver(self) -> RunArchiver:
        return RunArchiver(
            git=self.read_git(),
            records=ArchiveRecords(
                self.records.load,
                self.records.run_dir,
                self.records.claim_operation,
                self.records.save_archive_snapshot,
                self.records.save_operation,
                self.records.save_archive_summary,
                self.records.archive_preserved_files,
                self.records.save_archive_manifest,
                self.records.save,
            ),
            cleanup_targets=self.workspaces.archive_cleanup_targets,
            fingerprint=archive_fingerprint,
            block_reasons=self.archive_block_reasons,
            protect_commits=self.protect_archive_commits,
            summary=archive_summary,
            target_payload=archive_target_payload,
            cleanup=self.apply_archive_cleanup,
        )
