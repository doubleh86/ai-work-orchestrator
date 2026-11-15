"""Record execution ownership and stops under caller-owned locks."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, ContextManager, Iterator, Protocol

from ..errors import PipelineError
from ..execution_control import DispatchPaused, ExecutionStopped
from ..models import ExecutionControlRecord, OperationRecord, RunState, TaskAction, WorkTask, utc_now


class FinishExecution(Protocol):
    def __call__(self, owned: ExecutionControlRecord, *, failed: bool) -> None: ...


@dataclass(frozen=True, slots=True)
class ExecutionControlRecords:
    control_lock: Callable[[str], ContextManager[object]]
    load_control: Callable[[str], ExecutionControlRecord | None]
    save_control: Callable[[ExecutionControlRecord], None]
    load_operation: Callable[[str, str], OperationRecord | None]
    claim_operation: Callable[[OperationRecord], tuple[OperationRecord, bool]]
    save_operation: Callable[[OperationRecord], None]
    save_result: Callable[[str, str, dict[str, object]], str]


def make_stop_operation(
    run_id: str, *, request_id: str, execution_id: str, scope: str, task_id: str = "", attempt_id: str = "",
    invocation_id: str = "", chat_message: str = "",
) -> OperationRecord:
    """Build an operation from a validated stop target and message."""
    payload = {
        "execution_id": execution_id,
        "scope": scope,
        "task_id": task_id,
        "attempt_id": attempt_id,
        "invocation_id": invocation_id,
        **({"chat_message": chat_message} if chat_message else {}),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return OperationRecord(
        request_id=request_id,
        run_id=run_id,
        action="stop",
        digest=digest,
        phase="requested",
        execution_id=execution_id,
        task_id=task_id,
        attempt_id=attempt_id,
        invocation_id=invocation_id,
        scope=scope,
        reason="user_requested",
    )


@dataclass(frozen=True, slots=True)
class ExecutionControlService:
    records: ExecutionControlRecords

    @contextmanager
    def session(self, run_id: str, scope: str, *, finish: FinishExecution) -> Iterator[ExecutionControlRecord]:
        record = ExecutionControlRecord(run_id=run_id, execution_id=str(uuid.uuid4()), scope=scope, owner_pid=os.getpid())
        with self.records.control_lock(run_id):
            current = self.records.load_control(run_id)
            if current is not None and current.phase == "stopping" and current.stop_request_id:
                operation = self.records.load_operation(run_id, current.stop_request_id)
                if operation is not None and operation.status == "running":
                    operation.update(
                        "confirmation_required",
                        status="partial",
                        error="이전 실행 owner가 종료되어 중지 결과를 확인할 수 없습니다.",
                        error_code="stop_confirmation_required",
                    )
                    self.records.save_operation(operation)
            self.records.save_control(record)
        failed = False
        try:
            yield record
        except BaseException:
            failed = True
            raise
        finally:
            finish(record, failed=failed)

    @contextmanager
    def owned_session(self, run_id: str, scope: str) -> Iterator[ExecutionControlRecord]:
        with self.session(run_id, scope, finish=self.finish_session) as record:
            yield record

    def finish_session(self, owned: ExecutionControlRecord, *, failed: bool) -> None:
        with self.records.control_lock(owned.run_id):
            current = self.records.load_control(owned.run_id)
            if current is None or current.execution_id != owned.execution_id:
                return
            if current.phase == "stopped":
                return
            if current.phase == "stopping" and current.stop_request_id:
                operation = self.records.load_operation(owned.run_id, current.stop_request_id)
                if operation is not None:
                    if failed:
                        operation.update(
                            "confirmation_required",
                            status="partial",
                            error="중지 요청과 동시에 실행 오류가 발생해 종료 결과 확인이 필요합니다.",
                            error_code="stop_confirmation_required",
                        )
                    else:
                        operation.update("already_finished", status="succeeded")
                    self.records.save_operation(operation)
                current.phase = "confirmation_required" if failed else "finished"
            else:
                current.phase = "failed" if failed else "finished"
                current.dispatch_paused = False
            current.task_id = ""
            current.task_title = ""
            current.action = ""
            current.attempt_id = ""
            current.invocation_id = ""
            self.records.save_control(current)

    def set_active_task(self, state: RunState, task: WorkTask, action: TaskAction, attempt_id: str, invocation_id: str) -> None:
        with self.records.control_lock(state.id):
            control = self.records.load_control(state.id)
            if control is None or control.owner_pid != os.getpid() or control.phase not in {"running", "stopping"}:
                return
            if control.dispatch_paused:
                raise DispatchPaused("중지 요청 이후 새 Task 시작을 보류했습니다.", request_id=control.stop_request_id)
            control.scope = "task"
            control.task_id = task.id
            control.task_title = task.title
            control.action = action.value
            control.attempt_id = attempt_id
            control.invocation_id = invocation_id
            control.active_targets[task.id] = {
                "task_title": task.title,
                "action": action.value,
                "attempt_id": attempt_id,
                "invocation_id": invocation_id,
            }
            self.records.save_control(control)

    def clear_active_task(self, run_id: str, task_id: str, attempt_id: str) -> None:
        with self.records.control_lock(run_id):
            control = self.records.load_control(run_id)
            if control is None or control.owner_pid != os.getpid():
                return
            target = control.active_targets.get(task_id)
            if target is None or target.get("attempt_id") != attempt_id:
                return
            control.active_targets.pop(task_id, None)
            if control.task_id == task_id:
                control.task_id = ""
                control.task_title = ""
                control.action = ""
                control.attempt_id = ""
                control.invocation_id = ""
                if control.active_targets:
                    next_task_id, next_target = next(iter(control.active_targets.items()))
                    control.task_id = next_task_id
                    control.task_title = next_target.get("task_title", "")
                    control.action = next_target.get("action", "")
                    control.attempt_id = next_target.get("attempt_id", "")
                    control.invocation_id = next_target.get("invocation_id", "")
            self.records.save_control(control)

    def confirm_stopped(self, run_id: str, request_id: str) -> None:
        with self.records.control_lock(run_id):
            control = self.records.load_control(run_id)
            if control is None or control.stop_request_id != request_id:
                return
            stopped_task_id = control.task_id
            control.phase = "stopped"
            control.dispatch_paused = True
            if stopped_task_id:
                control.active_targets.pop(stopped_task_id, None)
            if control.active_targets:
                next_task_id, next_target = next(iter(control.active_targets.items()))
                control.phase = "running"
                control.task_id = next_task_id
                control.task_title = next_target.get("task_title", "")
                control.action = next_target.get("action", "")
                control.attempt_id = next_target.get("attempt_id", "")
                control.invocation_id = next_target.get("invocation_id", "")
                control.stop_request_id = ""
            self.records.save_control(control)
            operation = self.records.load_operation(run_id, request_id)
            if operation is not None:
                operation.update("stopped", status="succeeded")
                operation.finished_at = utc_now()
                self.records.save_operation(operation)

    def record_checkpoint(self, state: RunState, request_id: str, *, task: WorkTask | None = None) -> None:
        if not request_id:
            return
        operation = self.records.load_operation(state.id, request_id)
        if operation is None:
            return
        task_data = None
        if task is not None:
            task_data = next((item for item in state.to_dict()["tasks"] if item["id"] == task.id), None)
        checkpoint = {
            "kind": "execution_stop_checkpoint",
            "run_id": state.id,
            "execution_id": operation.execution_id,
            "scope": operation.scope,
            "task": task_data,
            "verification_attempt": (
                state.to_dict()["verification_attempts"][-1]
                if operation.scope == "verification" and state.verification_attempts
                else None
            ),
            "workspace": str(Path(task.worktree).resolve()) if task is not None and task.worktree else state.execution_worktree,
            "recorded_at": utc_now(),
        }
        operation.checkpoint_ref = self.records.save_result(state.id, request_id, checkpoint)
        self.records.save_operation(operation)

    def request_stop(self, operation: OperationRecord) -> tuple[OperationRecord, bool]:
        run_id = operation.run_id
        normalized_request_id = operation.request_id
        normalized_execution_id = operation.execution_id
        scope = operation.scope
        task_id = operation.task_id
        attempt_id = operation.attempt_id
        invocation_id = operation.invocation_id
        digest = operation.digest
        existing, created = self.records.claim_operation(operation)
        if not created:
            if existing.action != "stop" or existing.digest != digest:
                raise PipelineError("requestId가 다른 중지 대상에 사용되었습니다.")
            return existing, False
        with self.records.control_lock(run_id):
            control = self.records.load_control(run_id)
            if control is None or control.phase not in {"running", "stopping"}:
                operation.update("already_finished", status="succeeded")
            elif control.execution_id != normalized_execution_id:
                operation.update("target_changed", status="failed", error="실행 대상이 바뀌었습니다.", error_code="target_changed")
            elif control.scope != scope:
                operation.update("target_changed", status="failed", error="중지할 Task 또는 단계가 바뀌었습니다.", error_code="target_changed")
            elif task_id and task_id not in control.active_targets:
                operation.update("target_changed", status="failed", error="중지할 Task 또는 단계가 바뀌었습니다.", error_code="target_changed")
            elif task_id and (
                (attempt_id and control.active_targets[task_id].get("attempt_id") != attempt_id)
                or (invocation_id and control.active_targets[task_id].get("invocation_id") != invocation_id)
            ):
                operation.update("target_changed", status="failed", error="중지할 실행 시도가 바뀌었습니다.", error_code="target_changed")
            elif control.phase == "stopping" and control.stop_request_id:
                operation.result_ref = control.stop_request_id
                operation.update("linked", status="succeeded")
            else:
                operation.accepted_at = utc_now()
                operation.update("stopping")
                control.dispatch_paused = True
                control.stop_request_id = normalized_request_id
                control.phase = "stopping"
                if task_id:
                    target = control.active_targets[task_id]
                    control.task_id = task_id
                    control.task_title = target.get("task_title", "")
                    control.action = target.get("action", "")
                    control.attempt_id = target.get("attempt_id", "")
                    control.invocation_id = target.get("invocation_id", "")
                self.records.save_control(control)
            self.records.save_operation(operation)
        return operation, True


class StoredStopSignal:
    def __init__(
        self,
        load_control: Callable[[str], ExecutionControlRecord | None],
        run_id: str,
        execution_id: str,
        *,
        task_id: str = "",
        attempt_id: str = "",
        invocation_id: str = "",
        scope: str = "task",
    ) -> None:
        self.load_control = load_control
        self.run_id = run_id
        self.execution_id = execution_id
        self.task_id = task_id
        self.attempt_id = attempt_id
        self.invocation_id = invocation_id
        self.scope = scope
        self.request_id = ""

    def is_set(self) -> bool:
        try:
            control = self.load_control(self.run_id)
        except ValueError:
            return False
        if control is None or control.execution_id != self.execution_id or control.phase != "stopping" or not control.stop_request_id:
            return False
        if control.scope != self.scope:
            return False
        if self.task_id:
            target = control.active_targets.get(self.task_id)
            if target is None or control.task_id != self.task_id:
                return False
            if self.attempt_id and target.get("attempt_id") != self.attempt_id:
                return False
            if self.invocation_id and target.get("invocation_id") != self.invocation_id:
                return False
        elif self.attempt_id and control.attempt_id != self.attempt_id:
            return False
        elif self.invocation_id and control.invocation_id != self.invocation_id:
            return False
        self.request_id = control.stop_request_id
        return True


def make_stored_stop_signal(
    load_control: Callable[[str], ExecutionControlRecord | None], state: RunState, task: WorkTask | None = None, *, scope: str = "task",
) -> StoredStopSignal | None:
    control = load_control(state.id)
    if control is None or control.owner_pid != os.getpid() or control.phase not in {"running", "stopping"}:
        return None
    return StoredStopSignal(
        load_control,
        state.id,
        control.execution_id,
        task_id=(task.id if task else ""),
        attempt_id=(task.last_attempt_id if task else ""),
        invocation_id=(task.active_invocation_id if task else ""),
        scope=scope,
    )


EXECUTION_RUN_LOCK_OPERATIONS = frozenset({"execute", "resume", "execute-task", "retry-task", "complete-task"})


def raise_if_stopped(signal: StoredStopSignal | None) -> None:
    if signal is not None and signal.is_set():
        raise ExecutionStopped("사용자 요청에 따라 실행을 중지했습니다.", request_id=signal.request_id)
