"""Pending Task plan inputs and receipts under caller-owned run locks."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from ..document_index import PlanningSourceIndex
from ..errors import PipelineError
from ..models import PlanningApplyRequest, PlanningApplyStatus, RunState, RunStep, Stage, TaskStatus, WorkTask, utc_now
from .changes import PendingTaskPlan, merge_pending_task_plan
from .contracts import Plan


class TaskChangePlanBuilder(Protocol):
    def __call__(self, state: RunState, document: str, *, clarification_context: str, source_index: PlanningSourceIndex | None) -> Plan: ...


class TaskChangeAssistantMessage(Protocol):
    def __call__(self, state: RunState, message: str, *, counts_as_discussion: bool) -> None: ...


@dataclass(frozen=True, slots=True)
class TaskChangeSnapshot:
    tasks: list[WorkTask]
    stage: Stage
    failed_step: RunStep | None
    follow_up_requests: list[str]


def pending_task_change_snapshot(state: RunState) -> TaskChangeSnapshot:
    if state.stage not in {Stage.EXECUTING, Stage.FAILED, Stage.READY_TO_MERGE}:
        raise PipelineError("현재 단계에서는 같은 그룹의 Task를 변경할 수 없습니다.")
    if any(task.active_action or task.status in {TaskStatus.RUNNING, TaskStatus.REVIEWING, TaskStatus.REVISING} for task in state.tasks):
        raise PipelineError("실행 중인 Task가 끝난 뒤 적용할 수 있습니다.")
    original_tasks = deepcopy(state.tasks)
    original_stage = state.stage
    original_failed_step = state.failed_step
    original_requests = list(state.planning_follow_up_requests)
    return TaskChangeSnapshot(original_tasks, original_stage, original_failed_step, original_requests)


@dataclass(frozen=True, slots=True)
class PreparedTaskChange:
    plan: Plan
    merged_plan: PendingTaskPlan


@dataclass(frozen=True, slots=True)
class PendingTaskChangeRecords:
    save_state: Callable[[RunState], None]
    save_chat: Callable[[RunState], None]


@dataclass(frozen=True, slots=True)
class PendingTaskChanges:
    records: PendingTaskChangeRecords
    build_plan: TaskChangePlanBuilder
    clarification_context: Callable[[RunState], str]
    source_index: Callable[[RunState], PlanningSourceIndex | None]
    task_editable: Callable[[RunState, WorkTask], bool]
    task_draft: Callable[[WorkTask], dict[str, object]]
    append_assistant: TaskChangeAssistantMessage

    def begin(self, state: RunState, apply_request: PlanningApplyRequest | None) -> PlanningApplyRequest | None:
        if apply_request is None:
            apply_request = next(
                (
                    request
                    for request in state.planning_apply_requests
                    if request.status in {PlanningApplyStatus.QUEUED, PlanningApplyStatus.APPLYING}
                ),
                None,
            )
        if apply_request is not None:
            apply_request.status = PlanningApplyStatus.APPLYING
            apply_request.error_code = ""
            apply_request.error = ""
            self.records.save_chat(state)
        return apply_request

    def prepare(
        self, state: RunState, original_tasks: list[WorkTask], *, apply_request: PlanningApplyRequest | None, prepared_plan: Plan | None,
    ) -> PreparedTaskChange:
        plan = prepared_plan or self.build_plan(
            state,
            Path(state.spec_snapshot_path).read_text(encoding="utf-8"),
            clarification_context=(
                apply_request.context_snapshot
                if apply_request is not None and apply_request.context_snapshot
                else self.clarification_context(state)
            ),
            source_index=self.source_index(state),
        )
        merged_plan = merge_pending_task_plan(
            state, plan, original_tasks, task_editable=self.task_editable, task_draft=self.task_draft,
        )
        return PreparedTaskChange(plan, merged_plan)

    def complete(self, state: RunState, original_tasks: list[WorkTask], apply_request: PlanningApplyRequest | None) -> RunState:
        original_drafts = {task.id: self.task_draft(task) for task in original_tasks}
        final_drafts = {task.id: self.task_draft(task) for task in state.tasks}
        added_tasks = len(final_drafts.keys() - original_drafts.keys())
        updated_tasks = sum(
            original_drafts[task_id] != final_drafts[task_id]
            for task_id in original_drafts.keys() & final_drafts.keys()
        )
        state.planning_follow_up_requests.clear()
        self.append_assistant(
            state,
            "같은 작업 그룹의 Task에 반영했습니다. 완료 결과와 실행 이력은 보존했습니다.",
            counts_as_discussion=False,
        )
        if apply_request is not None:
            apply_request.status = PlanningApplyStatus.SUCCEEDED
            apply_request.completed_at = utc_now()
            apply_request.added_tasks = added_tasks
            apply_request.updated_tasks = updated_tasks
            apply_request.excluded_tasks = len(original_drafts.keys() - final_drafts.keys())
            apply_request.unchanged_tasks = len(final_drafts) - added_tasks - updated_tasks
            state.planning_applied_conversation_revision = max(
                state.planning_applied_conversation_revision, apply_request.conversation_revision
            )
        state.add_event("planning", "planning changes applied to existing task group")
        self.records.save_state(state)
        self.records.save_chat(state)
        return state

    def record_failure(self, state: RunState, apply_request: PlanningApplyRequest | None, exc: Exception) -> None:
        if apply_request is not None:
            apply_request.status = PlanningApplyStatus.FAILED
            apply_request.completed_at = utc_now()
            apply_request.error_code = "planning_apply_failed"
            apply_request.error = str(exc)
        state.add_event("planning", f"same-group planning apply failed: {exc}")
        self.records.save_state(state)
        self.records.save_chat(state)
