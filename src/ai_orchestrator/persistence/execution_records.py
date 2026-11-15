"""Bounded persistence ports for execution and control workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, ContextManager, Protocol
from ..models import EffortExecutionBinding, EffortPolicyState, ExecutionControlRecord, OperationRecord, ResolvedEffortPolicy, RunLockStatus, RunState


class AbandonEffortExecution(Protocol):
    def __call__(self, run_id: str, execution_request_id: str) -> EffortExecutionBinding:
        ...


class ClaimOperation(Protocol):
    def __call__(self, record: OperationRecord) -> tuple[OperationRecord, bool]:
        ...


class ClearStaleLock(Protocol):
    def __call__(self, run_id: str) -> RunLockStatus:
        ...


class FinishEffortExecution(Protocol):
    def __call__(self, run_id: str, execution_request_id: str) -> EffortExecutionBinding:
        ...


class InspectLock(Protocol):
    def __call__(self, run_id: str) -> RunLockStatus:
        ...


class InspectPlanningChatLock(Protocol):
    def __call__(self, run_id: str) -> RunLockStatus:
        ...


class LatestOperation(Protocol):
    def __call__(self, run_id: str, action: str) -> OperationRecord | None:
        ...


class ListRuns(Protocol):
    def __call__(self) -> list[RunState]:
        ...


class Load(Protocol):
    def __call__(self, run_id: str) -> RunState:
        ...


class LoadEffortPolicy(Protocol):
    def __call__(self, run_id: str, *, archived_chat: bool=...) -> EffortPolicyState:
        ...


class LoadExecutionControl(Protocol):
    def __call__(self, run_id: str) -> ExecutionControlRecord | None:
        ...


class LoadOperation(Protocol):
    def __call__(self, run_id: str, request_id: str) -> OperationRecord | None:
        ...


class LoadOperationResult(Protocol):
    def __call__(self, record: OperationRecord) -> dict[str, object] | None:
        ...


class LoadPlanningApplyPreview(Protocol):
    def __call__(self, run_id: str) -> dict[str, object] | None:
        ...


class LoadRevisionRequests(Protocol):
    def __call__(self, run_id: str) -> list[dict[str, object]]:
        ...


class LoadTaskExecutionProfiles(Protocol):
    def __call__(self, run_id: str) -> dict[str, dict[str, object]]:
        ...


class Lock(Protocol):
    def __call__(self, run_id: str, operation: str) -> ContextManager[object]:
        ...


class PlanningChatLock(Protocol):
    def __call__(self, run_id: str, operation: str=...) -> ContextManager[object]:
        ...


class PrepareEffortExecution(Protocol):
    def __call__(
        self,
        run_id: str,
        policy: ResolvedEffortPolicy,
        *,
        execution_request_id: str,
        expected_revision: int,
        preserve_reservation: bool=...,
    ) -> EffortExecutionBinding:
        ...


class RecentOperations(Protocol):
    def __call__(self, run_id: str, action: str, *, limit: int=...) -> list[OperationRecord]:
        ...


class RequestControlLock(Protocol):
    def __call__(self, run_id: str) -> ContextManager[object]:
        ...


class RevisionRequestsLock(Protocol):
    def __call__(self, run_id: str) -> ContextManager[object]:
        ...


class RunDir(Protocol):
    def __call__(self, run_id: str) -> Path:
        ...


class Save(Protocol):
    def __call__(self, state: RunState) -> None:
        ...


class SaveOperation(Protocol):
    def __call__(self, record: OperationRecord) -> None:
        ...


class SaveOperationResult(Protocol):
    def __call__(self, run_id: str, request_id: str, result: dict[str, object]) -> str:
        ...


class SavePlanningChat(Protocol):
    def __call__(self, state: RunState) -> None:
        ...


class SaveRevisionRequests(Protocol):
    def __call__(self, run_id: str, requests: list[dict[str, object]]) -> None:
        ...


class SaveTaskExecutionProfiles(Protocol):
    def __call__(self, run_id: str, profiles: dict[str, dict[str, object]]) -> None:
        ...


class StartEffortExecution(Protocol):
    def __call__(self, run_id: str, execution_request_id: str) -> EffortExecutionBinding:
        ...


@dataclass(frozen=True, slots=True)
class WorkspaceAccessRecords:
    load: Load


@dataclass(frozen=True, slots=True)
class ExecutionProfilesRecords:
    inspect_lock: InspectLock
    load: Load
    load_effort_policy: LoadEffortPolicy
    load_task_execution_profiles: LoadTaskExecutionProfiles
    planning_chat_lock: PlanningChatLock
    save: Save
    save_task_execution_profiles: SaveTaskExecutionProfiles


@dataclass(frozen=True, slots=True)
class ExecutionPolicyLifecycleRecords:
    abandon_effort_execution: AbandonEffortExecution
    finish_effort_execution: FinishEffortExecution
    load: Load
    load_effort_policy: LoadEffortPolicy
    load_task_execution_profiles: LoadTaskExecutionProfiles
    prepare_effort_execution: PrepareEffortExecution
    save: Save
    start_effort_execution: StartEffortExecution


@dataclass(frozen=True, slots=True)
class VerificationCommandsRecords:
    run_dir: RunDir


@dataclass(frozen=True, slots=True)
class TaskWorkflowsRecords:
    load_effort_policy: LoadEffortPolicy
    load_execution_control: LoadExecutionControl
    run_dir: RunDir
    save: Save


@dataclass(frozen=True, slots=True)
class ExecutionFlowRecords:
    load: Load
    load_task_execution_profiles: LoadTaskExecutionProfiles
    planning_chat_lock: PlanningChatLock
    save: Save
    save_planning_chat: SavePlanningChat


@dataclass(frozen=True, slots=True)
class ExecutionMessagesRecords:
    load: Load
    planning_chat_lock: PlanningChatLock
    save_planning_chat: SavePlanningChat


@dataclass(frozen=True, slots=True)
class RecoveryFlowRecords:
    claim_operation: ClaimOperation
    inspect_lock: InspectLock
    latest_operation: LatestOperation
    list_runs: ListRuns
    load: Load
    load_operation: LoadOperation
    load_operation_result: LoadOperationResult
    save_operation: SaveOperation
    save_operation_result: SaveOperationResult


@dataclass(frozen=True, slots=True)
class VerificationFlowRecords:
    load: Load
    planning_chat_lock: PlanningChatLock
    run_dir: RunDir
    save: Save


@dataclass(frozen=True, slots=True)
class ScopeApprovalActionsRecords:
    claim_operation: ClaimOperation
    load: Load
    load_effort_policy: LoadEffortPolicy
    load_execution_control: LoadExecutionControl
    load_operation: LoadOperation
    load_planning_apply_preview: LoadPlanningApplyPreview
    lock: Lock
    planning_chat_lock: PlanningChatLock
    recent_operations: RecentOperations
    request_control_lock: RequestControlLock
    save: Save
    save_operation: SaveOperation


@dataclass(frozen=True, slots=True)
class ExecutionCommandsRecords:
    claim_operation: ClaimOperation
    inspect_lock: InspectLock
    latest_operation: LatestOperation
    load: Load
    load_execution_control: LoadExecutionControl
    load_operation: LoadOperation
    lock: Lock
    planning_chat_lock: PlanningChatLock
    request_control_lock: RequestControlLock
    revision_requests_lock: RevisionRequestsLock
    save: Save
    save_operation: SaveOperation


@dataclass(frozen=True, slots=True)
class RunControlCommandsRecords:
    claim_operation: ClaimOperation
    clear_stale_lock: ClearStaleLock
    inspect_lock: InspectLock
    inspect_planning_chat_lock: InspectPlanningChatLock
    latest_operation: LatestOperation
    load: Load
    load_execution_control: LoadExecutionControl
    load_operation: LoadOperation
    load_revision_requests: LoadRevisionRequests
    lock: Lock
    planning_chat_lock: PlanningChatLock
    request_control_lock: RequestControlLock
    revision_requests_lock: RevisionRequestsLock
    run_dir: RunDir
    save: Save
    save_operation: SaveOperation
    save_operation_result: SaveOperationResult
    save_planning_chat: SavePlanningChat
    save_revision_requests: SaveRevisionRequests
