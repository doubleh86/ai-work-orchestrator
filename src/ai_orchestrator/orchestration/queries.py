"""Application queries over narrow records and query services."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from ..execution.task_logs import read_task_log_tail, render_task_log
from ..git import DotnetDiagnostic
from .. import git as git_runtime
from ..models import IntegrationControl, OperationRecord, RunExecutionAction, RunExecutionControl, RunExecutionSituation, RunState, RunSummary
from ..notifications import NotificationCollector
from ..persistence.run_lookup import find_task
from ..queries import RunSummaryQueries, WaitingPromptQueries
from ..queries.control import RunControlQueries
from ..run_queries import planned_user_checks, user_checks

TASK_LOG_DISPLAY_LIMIT_BYTES = 64 * 1024


class UsageSnapshot(Protocol):
    def __call__(self, run_id: str, *, execution_request_id: str = "", cursor: str = "", limit: int = 50) -> dict[str, object]: ...


@dataclass(frozen=True, slots=True)
class RunQueryRecords:
    load: Callable[[str], RunState]
    list_runs: Callable[[], list[RunState]]
    run_dir: Callable[[str], Path]
    latest_operation: Callable[[str, str], OperationRecord | None]
    usage_snapshot: UsageSnapshot


@dataclass(frozen=True, slots=True)
class RunQueries:
    records: RunQueryRecords
    repository: Callable[[], Path]
    dotnet_executable: Callable[[], str]
    controls: RunControlQueries
    summaries: Callable[[], RunSummaryQueries]
    waiting: Callable[[], WaitingPromptQueries]
    notification_collector: NotificationCollector

    def status(self, run_id: str) -> RunState:
        return self.records.load(run_id)

    def notifications(self, *, after_cursor: str = "", limit: int = 100) -> dict[str, object]:
        return self.notification_collector.page(after_cursor=after_cursor, limit=limit)

    def waiting_prompt(
        self, state: RunState, control: RunExecutionControl, integration: IntegrationControl | None = None,
    ) -> dict[str, object] | None:
        return self.waiting().waiting_prompt(state, control, integration)

    def status_with_execution_control(self, run_id: str) -> tuple[RunState, RunExecutionControl]:
        state, execution_control, _ = self.status_with_controls(run_id)
        return state, execution_control

    def latest_main_operations(self, run_id: str) -> dict[str, dict[str, str] | None]:
        operations: dict[str, dict[str, str] | None] = {}
        for action in ("merge", "push", "retry_main_push"):
            record = self.records.latest_operation(run_id, action)
            operations[action] = None if record is None else {
                "phase": record.phase,
                "status": record.status,
                "error": record.error,
                "updated_at": record.updated_at,
            }
        return operations

    def status_with_controls(self, run_id: str) -> tuple[RunState, RunExecutionControl, IntegrationControl]:
        lock_before = self.controls.inspect_lock(run_id)
        state = self.records.load(run_id)
        lock_after = self.controls.inspect_lock(run_id)
        try:
            execution_record = self.controls.load_control(run_id)
        except ValueError:
            execution_record = None
        if lock_before != lock_after:
            execution_control = RunExecutionControl(
                situation=RunExecutionSituation.STATUS_UNKNOWN,
                action=RunExecutionAction.NONE,
                reason="상태를 조회하는 동안 실행 잠금이 변경되었습니다. 상태를 다시 확인해 주세요.",
                lock_state=lock_after.state,
                operation=lock_after.operation,
            )
            return state, execution_control, self.controls.integration_control(state, lock_after)
        return state, self.controls.execution_control(state, lock_after, execution_record), self.controls.integration_control(state, lock_after)

    def list_statuses(self) -> list[RunState]:
        return self.records.list_runs()

    def list_summaries(self, scope: str = "all") -> list[RunSummary]:
        return self.summaries().list_summaries(scope)

    @staticmethod
    def planned_user_checks(state: RunState, *, include_notes: bool = False) -> list[dict[str, object]]:
        return planned_user_checks(state, include_notes=include_notes)

    @staticmethod
    def user_checks(state: RunState, *, include_recorded: bool = False) -> list[dict[str, object]]:
        return user_checks(state, include_recorded=include_recorded)

    def user_check_summaries(self) -> list[dict[str, object]]:
        return self.summaries().user_check_summaries()

    def attention_item_summaries(self) -> list[dict[str, object]]:
        return self.summaries().attention_item_summaries()

    def active_group_summaries(self) -> list[dict[str, object]]:
        return self.summaries().active_group_summaries()

    def task_log(self, run_id: str, task_id: str) -> str:
        state = self.records.load(run_id)
        task = find_task(state, task_id)
        return render_task_log(task, run_id, run_directory=self.records.run_dir, read_tail=self.read_log_tail)

    @staticmethod
    def read_log_tail(path: Path) -> str:
        return read_task_log_tail(path, limit_bytes=TASK_LOG_DISPLAY_LIMIT_BYTES)

    def check_dotnet(self, *, run_id: str = "", task_id: str = "") -> DotnetDiagnostic:
        cwd = self.repository()
        if run_id:
            state = self.records.load(run_id)
            if task_id:
                task = find_task(state, task_id)
                if task.worktree:
                    cwd = Path(task.worktree)
            elif state.execution_worktree:
                cwd = Path(state.execution_worktree)
        return git_runtime.diagnose_dotnet(self.dotnet_executable() or "dotnet", cwd)

    def usage(self, run_id: str, *, execution_request_id: str = "", cursor: str = "", limit: int = 50) -> dict[str, object]:
        return self.records.usage_snapshot(run_id, execution_request_id=execution_request_id, cursor=cursor, limit=limit)
