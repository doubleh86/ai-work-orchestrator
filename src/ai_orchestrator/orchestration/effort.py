"""Effort validation, locks and ordered plan application."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, ContextManager, Protocol

from ..effort_policy import EffortModePreview
from ..errors import PipelineError
from ..execution import EffortQueries, effort_reservation_allowed
from ..execution.effort_previews import EffortPreviewQueries
from ..execution.effort_queries import EffortPolicyLoader
from ..execution.effort_plan import EffortPlanApplication
from ..models import EffortMode, EffortPolicyView, RunState, Stage, TaskStatus
from ..persistence.run_lookup import RunLookup


class SetEffortMode(Protocol):
    def __call__(self, run_id: str, mode: str, *, target: str, expected_revision: int, request_id: str,
                 expected_stage: Stage) -> EffortPolicyView: ...


class CancelEffortReservation(Protocol):
    def __call__(self, run_id: str, *, expected_revision: int, request_id: str, expected_stage: Stage) -> EffortPolicyView: ...


@dataclass(frozen=True, slots=True)
class EffortCommandRecords:
    load: Callable[[str], RunState]
    load_effort_policy: EffortPolicyLoader
    lock: Callable[[str, str], ContextManager[object]]
    planning_chat_lock: Callable[[str], ContextManager[object]]
    set_effort_mode: SetEffortMode
    cancel_effort_reservation: CancelEffortReservation


@dataclass(frozen=True, slots=True)
class EffortCommands:
    records: EffortCommandRecords
    lookup: RunLookup
    previews: EffortPreviewQueries
    queries: Callable[[], EffortQueries]
    plan_application: Callable[[], EffortPlanApplication]

    def preview_effort_mode(self, run_id: str, mode: EffortMode | str, *, expected_revision: int) -> EffortModePreview:
        return self.previews.preview_effort_mode(run_id, mode, expected_revision=expected_revision)

    def build_preview(
        self, state: RunState, selected: EffortMode, policy_revision: int, *, preserve_execution_profiles: bool = False,
        runtime_excluded_task_ids: frozenset[str] = frozenset(),
    ) -> EffortModePreview:
        return self.previews.build_preview(
            state, selected, policy_revision, preserve_execution_profiles=preserve_execution_profiles,
            runtime_excluded_task_ids=runtime_excluded_task_ids,
        )

    def effort_control(self, run_id: str, *, expected_state: RunState | None = None) -> dict[str, object]:
        return self.queries().control(run_id, expected_state=expected_state)

    def desktop_effort_mode_preview(self, run_id: str, mode: str, *, expected_revision: int) -> dict[str, object]:
        return self.queries().desktop_preview(run_id, mode, expected_revision=expected_revision)

    def set_effort_mode(
        self, run_id: str, mode: EffortMode | str, *, expected_revision: int, request_id: str, target: str = "planning"
    ) -> EffortPolicyView:
        try:
            selected = EffortMode(mode)
        except ValueError as exc:
            raise PipelineError(f"unsupported effort mode: {mode}") from exc
        if target == "next_execution":
            state = self.records.load(run_id)
            if not effort_reservation_allowed(state):
                raise PipelineError("다음 실행 예약은 계획·실행 중 또는 작업 실행 실패 그룹에서만 변경할 수 있습니다.")
            return self.records.set_effort_mode(
                run_id, selected.value, target=target, expected_revision=expected_revision,
                request_id=request_id, expected_stage=state.stage,
            )
        if target != "planning":
            raise PipelineError(f"unsupported effort policy target: {target}")
        with self.records.lock(run_id, "set-effort-mode"):
            state = self.lookup.at(run_id, {Stage.PLANNED})
            if state.archive or any(task.status != TaskStatus.PENDING for task in state.tasks):
                raise PipelineError("작업을 시작한 계획의 모드를 직접 변경할 수 없습니다. 다음 실행 예약을 사용하세요.")
            return self.records.set_effort_mode(
                run_id, selected.value, target=target, expected_revision=expected_revision, request_id=request_id, expected_stage=state.stage
            )

    def cancel_effort_reservation(self, run_id: str, *, expected_revision: int, request_id: str) -> EffortPolicyView:
        state = self.records.load(run_id)
        if state.archive:
            raise PipelineError("보관된 작업 그룹의 실행 예약은 변경할 수 없습니다.")
        return self.records.cancel_effort_reservation(
            run_id, expected_revision=expected_revision, request_id=request_id, expected_stage=state.stage
        )

    def apply_effort_mode_to_plan(
        self, run_id: str, mode: EffortMode | str, *, expected_policy_revision: int, expected_plan_revision: int,
        reviewer_agent_ids: dict[str, str] | None = None,
    ) -> RunState:
        try:
            selected = EffortMode(mode)
        except ValueError as exc:
            raise PipelineError(f"unsupported effort mode: {mode}") from exc
        if type(expected_plan_revision) is not int or expected_plan_revision < 0:
            raise PipelineError("expected plan revision must be a non-negative integer")
        with self.records.lock(run_id, "apply-effort-mode"), self.records.planning_chat_lock(run_id):
            state = self.lookup.at(run_id, {Stage.PLANNED})
            return self.plan_application().apply_locked(
                state, run_id, selected, expected_policy_revision=expected_policy_revision,
                expected_plan_revision=expected_plan_revision, reviewer_agent_ids=reviewer_agent_ids,
            )
