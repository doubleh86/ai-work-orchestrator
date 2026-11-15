import os
import uuid
from pathlib import Path

from ai_orchestrator.execution import ExecutionControlRecords, ExecutionControlService
from ai_orchestrator.models import ExecutionControlRecord
from ai_orchestrator.store import StateStore


def service_for(store: StateStore) -> ExecutionControlService:
    return ExecutionControlService(ExecutionControlRecords(
        control_lock=store.execution_control_lock,
        load_control=store.load_execution_control,
        save_control=store.save_execution_control,
        load_operation=store.load_operation,
        claim_operation=store.claim_operation,
        save_operation=store.save_operation,
        save_result=store.save_operation_result,
    ))


def test_late_attempt_cleanup_preserves_newer_active_task(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    control = ExecutionControlRecord(
        run_id="run", execution_id=str(uuid.uuid4()), scope="task", owner_pid=os.getpid(),
        task_id="task", task_title="New attempt", action="revise", attempt_id="new-attempt", invocation_id="new-invocation",
        active_targets={"task": {
            "task_title": "New attempt", "action": "revise", "attempt_id": "new-attempt", "invocation_id": "new-invocation",
        }},
    )
    store.save_execution_control(control)
    before = store.execution_control_path("run").read_bytes()

    service_for(store).clear_active_task("run", "task", "old-attempt")

    assert store.execution_control_path("run").read_bytes() == before
    restored = store.load_execution_control("run")
    assert restored is not None
    assert restored.task_id == "task"
    assert restored.active_targets["task"]["invocation_id"] == "new-invocation"


def test_old_session_finish_preserves_newer_execution(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    old = ExecutionControlRecord("run", str(uuid.uuid4()), "task", os.getpid())
    current = ExecutionControlRecord(
        "run", str(uuid.uuid4()), "verification", os.getpid(), phase="stopping", dispatch_paused=True,
        stop_request_id=str(uuid.uuid4()),
    )
    store.save_execution_control(current)
    before = store.execution_control_path("run").read_bytes()

    service_for(store).finish_session(old, failed=True)

    assert store.execution_control_path("run").read_bytes() == before
    restored = store.load_execution_control("run")
    assert restored is not None
    assert restored.execution_id == current.execution_id
    assert restored.phase == "stopping"
