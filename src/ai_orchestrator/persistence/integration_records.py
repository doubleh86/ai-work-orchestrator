"""Role-specific persistence contracts for integration and workspace commands."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ContextManager, Protocol
from .execution_records import (
    ClaimOperation,
    ClearStaleLock,
    InspectLock,
    LatestOperation,
    ListRuns,
    Load,
    LoadOperation,
    Lock,
    PlanningChatLock,
    RunDir,
    Save,
    SaveOperation,
)
from ..models import RunLockStatus, RunState


class ArchivePreservedFiles(Protocol):
    def __call__(self, run_id: str, *, excluded_operation_request_ids: tuple[str, ...]=...) -> list[dict[str, object]]:
        ...


class ClearStaleProjectGitLock(Protocol):
    def __call__(self, *, expected_operation: str) -> RunLockStatus:
        ...


class Delete(Protocol):
    def __call__(self, run_id: str) -> None:
        ...


class LoadResultArtifact(Protocol):
    def __call__(self, run_id: str) -> dict[str, object] | None:
        ...


class ProjectGitLock(Protocol):
    def __call__(self, operation: str) -> ContextManager[object]:
        ...


class SaveArchiveManifest(Protocol):
    def __call__(self, run_id: str, payload: dict[str, object]) -> tuple[Path, str]:
        ...


class SaveArchiveSnapshot(Protocol):
    def __call__(self, state: RunState) -> tuple[Path, str]:
        ...


class SaveArchiveSummary(Protocol):
    def __call__(self, run_id: str, content: str) -> Path:
        ...


class SaveResultArtifact(Protocol):
    def __call__(self, run_id: str, payload: dict[str, object]) -> None:
        ...


@dataclass(frozen=True, slots=True)
class WorkspaceFlowsRecords:
    inspect_lock: InspectLock
    save: Save


@dataclass(frozen=True, slots=True)
class ArchiveFlowRecords:
    archive_preserved_files: ArchivePreservedFiles
    claim_operation: ClaimOperation
    load: Load
    run_dir: RunDir
    save: Save
    save_archive_manifest: SaveArchiveManifest
    save_archive_snapshot: SaveArchiveSnapshot
    save_archive_summary: SaveArchiveSummary
    save_operation: SaveOperation


@dataclass(frozen=True, slots=True)
class ConflictFlowRecords:
    claim_operation: ClaimOperation
    load: Load
    load_operation: LoadOperation
    run_dir: RunDir
    save: Save
    save_operation: SaveOperation


@dataclass(frozen=True, slots=True)
class MainApplyFlowRecords:
    claim_operation: ClaimOperation
    load_operation: LoadOperation
    run_dir: RunDir
    save: Save
    save_operation: SaveOperation


@dataclass(frozen=True, slots=True)
class IntegrationCommandsRecords:
    clear_stale_lock: ClearStaleLock
    clear_stale_project_git_lock: ClearStaleProjectGitLock
    inspect_lock: InspectLock
    latest_operation: LatestOperation
    load: Load
    load_operation: LoadOperation
    load_result_artifact: LoadResultArtifact
    lock: Lock
    planning_chat_lock: PlanningChatLock
    project_git_lock: ProjectGitLock
    save: Save
    save_operation: SaveOperation
    save_result_artifact: SaveResultArtifact


@dataclass(frozen=True, slots=True)
class LifecycleCommandsRecords:
    clear_stale_lock: ClearStaleLock
    delete: Delete
    inspect_lock: InspectLock
    list_runs: ListRuns
    load: Load
    lock: Lock
    planning_chat_lock: PlanningChatLock
    project_git_lock: ProjectGitLock
    run_dir: RunDir
    save: Save
