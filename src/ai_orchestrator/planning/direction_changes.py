"""Direction-change intake without execution or Run authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..errors import PipelineError
from ..models import DirectionChangeRequest, DirectionChangeStatus, RunState, Stage, TaskStatus, utc_now


@dataclass(frozen=True, slots=True)
class DirectionChangeIntake:
    append_user: Callable[[RunState, str], None]
    save_chat: Callable[[RunState], None]

    def accept(self, state: RunState, normalized_id: str, instruction: str) -> RunState:
        existing = next((item for item in state.direction_change_requests if item.request_id == normalized_id), None)
        if existing is not None:
            if existing.text != instruction:
                raise PipelineError("requestId가 다른 방향 수정 요청에 사용되었습니다.")
            return state
        if state.stage != Stage.EXECUTING or not any(task.status in {
            TaskStatus.PENDING, TaskStatus.WAITING, TaskStatus.RUNNING, TaskStatus.REVIEWING, TaskStatus.REVISING,
        } for task in state.tasks):
            raise PipelineError("실행 중인 그룹의 남은 Task가 있을 때만 방향 수정을 접수할 수 있습니다.")
        active = next((task for task in state.tasks if task.active_action or task.status in {
            TaskStatus.RUNNING, TaskStatus.REVIEWING, TaskStatus.REVISING,
        }), None)
        for item in state.direction_change_requests:
            if item.status == DirectionChangeStatus.AWAITING_CONFIRMATION:
                item.status = DirectionChangeStatus.QUEUED
                item.preview_id = ""
                item.next_step = "새 요청과 함께 미리보기를 다시 확인해 주세요."
                item.updated_at = utc_now()
        state.direction_change_requests.append(DirectionChangeRequest(
            request_id=normalized_id, text=instruction, task_id=active.id if active else "",
            task_title=active.title if active else "",
            status=DirectionChangeStatus.RECEIVED if active else DirectionChangeStatus.QUEUED,
            next_step="현재 실행 묶음 종료 후 미리보기 확인" if active else "다음 Task 시작 전 미리보기 확인",
        ))
        self.append_user(state, instruction)
        if instruction not in state.planning_follow_up_requests:
            state.planning_follow_up_requests.append(instruction)
        state.add_event("planning", "direction change request received")
        self.save_chat(state)
        return state
