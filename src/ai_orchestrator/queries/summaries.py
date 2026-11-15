"""Read-only run list composition using caller-owned query ports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from ..git import GitError
from ..models import RunExecutionControl, RunExecutionSituation, RunLockState, RunLockStatus, RunState, RunSummary, Stage, TaskStatus, utc_now


class SummaryAttentionReasons(Protocol):
    def __call__(
        self, state: RunState, control: RunExecutionControl, *, deployment_configured: bool, remote_configured: bool,
    ) -> tuple[str, ...]: ...


class AttentionDecision(Protocol):
    def __call__(
        self, state: RunState, control: RunExecutionControl, *, remote_configured: bool, deployment_configured: bool,
    ) -> tuple[str, str, str, str, str] | None: ...


@dataclass(frozen=True, slots=True)
class RunSummaryRecords:
    list_runs: Callable[[], list[RunState]]
    list_run_summaries: Callable[[str], list[RunSummary]]
    inspect_lock: Callable[[str], RunLockStatus]
    inspect_planning_chat_lock: Callable[[str], RunLockStatus]


@dataclass(frozen=True, slots=True)
class RunSummaryQueries:
    records: RunSummaryRecords
    deployment_configured: Callable[[], bool]
    remote_configured: Callable[[], bool]
    execution_control: Callable[[RunState], RunExecutionControl]
    attention_reasons: SummaryAttentionReasons
    attention_decision: AttentionDecision
    active_group_kind: Callable[[str], str]
    user_checks: Callable[[RunState], list[dict[str, object]]]
    waiting_prompt: Callable[[RunState, RunExecutionControl], dict[str, object] | None]

    def list_summaries(self, scope: str = "all") -> list[RunSummary]:
        if scope not in {"active", "archived", "all"}:
            raise ValueError(f"unsupported run list scope: {scope}")
        deployment_configured = self.deployment_configured()
        try:
            remote_configured = self.remote_configured()
        except (GitError, OSError):
            remote_configured = True
        summaries: list[RunSummary] = []
        for state in self.records.list_runs():
            archived = state.archive is not None
            if (scope == "active" and archived) or (scope == "archived" and not archived):
                continue
            checked_at = utc_now()
            if archived:
                summaries.append(
                    RunSummary.from_state(
                        state,
                        execution_situation=RunExecutionSituation.UNAVAILABLE.value,
                        pipeline_complete=True,
                        checked_at=checked_at,
                    )
                )
                continue
            control = self.execution_control(state)
            reasons = self.attention_reasons(
                state,
                control,
                deployment_configured=deployment_configured,
                remote_configured=remote_configured,
            )
            complete = state.stage == Stage.DEPLOYED or (
                not deployment_configured
                and (state.stage == Stage.PUSHED or (state.stage == Stage.MERGED and not remote_configured))
            )
            summaries.append(
                RunSummary.from_state(
                    state,
                    attention_reasons=reasons,
                    execution_situation=control.situation.value,
                    pipeline_complete=complete,
                    checked_at=checked_at,
                )
            )
        return sorted(summaries, key=lambda item: item.archived_at if item.archived else item.created_at, reverse=True)

    def user_check_summaries(self) -> list[dict[str, object]]:
        return [
            {"run_id": state.id, "run_title": state.summary or state.id, "updated_at": state.updated_at, **check}
            for state in self.records.list_runs()
            for check in self.user_checks(state)
        ]

    def attention_item_summaries(self) -> list[dict[str, object]]:
        """Derive unresolved human decisions without changing run state."""
        checked_at = utc_now()
        remote_configured = self.remote_configured()
        deployment_configured = self.deployment_configured()
        items: list[dict[str, object]] = []
        for state in self.records.list_runs():
            if state.archive is not None or state.stage == Stage.DEPLOYED:
                continue
            if state.stage == Stage.PUSHED and not deployment_configured:
                continue
            if state.stage == Stage.MERGED and not remote_configured and not deployment_configured:
                continue
            control = self.execution_control(state)
            try:
                chat_before = self.records.inspect_planning_chat_lock(state.id)
                chat_after = self.records.inspect_planning_chat_lock(state.id)
            except (OSError, ValueError):
                chat_before = chat_after = None
            uncertain = (
                control.situation == RunExecutionSituation.STATUS_UNKNOWN
                or control.lock_state not in {RunLockState.UNLOCKED, RunLockState.ACTIVE}
                or chat_after is None or chat_before != chat_after
                or chat_after.state not in {RunLockState.UNLOCKED, RunLockState.ACTIVE}
            )
            if uncertain:
                decision = ("status_check", "실행 상태 확인", "잠금 또는 실행 상태를 확인해야 합니다.", "operations", "")
            elif control.lock_state == RunLockState.ACTIVE or chat_after.state == RunLockState.ACTIVE:
                continue
            else:
                prompt = self.waiting_prompt(state, control)
                if prompt and prompt["kind"] in {"retry", "resume"}:
                    title = "이 Task 재시도" if prompt["kind"] == "retry" else "남은 Task 계속"
                    decision = (str(prompt["kind"]), title, str(prompt["question"]), "tasks", str(prompt["task_id"]))
                else:
                    decision = self.attention_decision(state, control, remote_configured=remote_configured,
                                                        deployment_configured=deployment_configured)
            if decision is None:
                continue
            kind, title, reason, view, task_id = decision
            compact_reason = " ".join(reason.split())
            item = {
                "run_id": state.id, "run_title": state.summary or state.id, "stage": state.stage.value,
                "kind": kind, "title": title, "reason": compact_reason[:320] + ("…" if len(compact_reason) > 320 else ""),
                "view": view, "task_id": task_id,
                "status": "check_required" if uncertain or kind == "status_check" else "actionable",
                "updated_at": state.updated_at, "checked_at": checked_at,
            }
            if task_id and state.stage == Stage.FAILED:
                failed_task = next((task for task in state.tasks if task.id == task_id and task.status == TaskStatus.FAILED), None)
                if failed_task is not None:
                    item["attempt_id"] = failed_task.last_attempt_id
                    key = f"{task_id}:{failed_task.last_attempt_id}"
                    item["automatic_recovery_stopped"] = any(event.kind == "task_repair_handoff" and event.message == key for event in state.events)
            items.append(item)
        return items

    def active_group_summaries(self) -> list[dict[str, object]]:
        """Read current run activity without starting work or changing locks."""
        checked_at = utc_now()
        groups: list[dict[str, object]] = []
        for summary in self.records.list_run_summaries("active"):
            run_before = self.records.inspect_lock(summary.id)
            chat_before = self.records.inspect_planning_chat_lock(summary.id)
            run_after = self.records.inspect_lock(summary.id)
            chat_after = self.records.inspect_planning_chat_lock(summary.id)
            locks = (run_after, chat_after)
            if run_before != run_after or chat_before != chat_after:
                status = "check_required"
                activity_kinds: list[str] = []
            else:
                activity_kinds = []
                if run_after.state == RunLockState.ACTIVE:
                    activity_kinds.append(self.active_group_kind(run_after.operation))
                if chat_after.state == RunLockState.ACTIVE:
                    activity_kinds.append("planning")
                if activity_kinds:
                    status = "active"
                elif any(lock.state != RunLockState.UNLOCKED for lock in locks):
                    status = "check_required"
                else:
                    continue
            groups.append({
                "run_id": summary.id,
                "title": summary.summary,
                "stage": summary.stage.value,
                "completed_task_count": summary.completed_task_count,
                "task_count": summary.task_count,
                "status": status,
                "activity_kinds": list(dict.fromkeys(activity_kinds)),
                "last_activity_at": max(summary.updated_at, *(lock.acquired_at for lock in locks)),
                "checked_at": checked_at,
            })
        return groups
