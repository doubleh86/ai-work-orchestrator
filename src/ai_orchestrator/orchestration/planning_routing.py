"""Route planning messages using existing caller-provided control ports."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Callable, ContextManager, Protocol
from ..errors import PipelineError
from ..models import RunState


class PlanningMessageChannel(Protocol):
    def __call__(
        self, run_id: str, message: str, *, planning_agent_id: str | None, planning_model: str | None,
        planning_reasoning_effort: str | None,
    ) -> RunState: ...


class PlanningMessageAppend(Protocol):
    def __call__(self, state: RunState, message: str, *, counts_as_discussion: bool) -> None: ...


class PlanningMessagePreview(Protocol):
    def __call__(self, run_id: str, *, request_id: str) -> dict[str, object]: ...


class PlanningMessageApply(Protocol):
    def __call__(
        self, run_id: str, *, request_id: str, expected_revision: int, conversation_revision: int, control_message: str,
        planning_agent_id: str | None, planning_model: str | None, planning_reasoning_effort: str | None,
    ) -> RunState: ...


@dataclass(frozen=True, slots=True)
class PlanningMessageRecords:
    load_run: Callable[[str], RunState]
    save_chat: Callable[[RunState], None]
    chat_lock: Callable[[str], ContextManager[None]]


@dataclass(frozen=True, slots=True)
class PlanningMessageRouter:
    records: PlanningMessageRecords
    initial_tasks: Callable[[RunState, str], bool]
    requests_apply: Callable[[str], bool]
    is_apply_control: Callable[[str], bool]
    result_available: Callable[[RunState], bool]
    execution_available: Callable[[RunState], bool]
    append_user: PlanningMessageAppend
    send_execution: PlanningMessageChannel
    preview: PlanningMessagePreview
    apply_request: PlanningMessageApply

    def route(
        self, run_id: str, message: str, *, planning_agent_id: str | None, planning_model: str | None,
        planning_reasoning_effort: str | None,
    ) -> RunState | None:
        current = self.records.load_run(run_id)
        if current.archive is not None:
            return self.send_execution(
                run_id,
                message,
                planning_agent_id=planning_agent_id,
                planning_model=planning_model,
                planning_reasoning_effort=planning_reasoning_effort,
            )
        initial_tasks = self.initial_tasks(current, message)
        if initial_tasks or self.requests_apply(message):
            if self.result_available(current):
                raise PipelineError("완료한 결과의 수정은 결과 화면에서 대화로 수정안을 만든 뒤 확인·저장해 주세요. 기존 결과는 보존됩니다.")
            inline_change = initial_tasks or not self.is_apply_control(message)
            if current.repository_intent != "new_project" or inline_change:
                with self.records.chat_lock(run_id):
                    state = self.records.load_run(run_id)
                    if initial_tasks:
                        initial_tasks = self.initial_tasks(state, message)
                    self.append_user(state, message, counts_as_discussion=inline_change)
                    self.records.save_chat(state)
                current = state
            if current.repository_intent != "new_project" and not initial_tasks:
                self.preview(run_id, request_id=str(uuid.uuid4()))
                return self.records.load_run(run_id)
            return self.apply_request(
                run_id,
                request_id=str(uuid.uuid4()),
                expected_revision=current.plan_revision,
                conversation_revision=current.planning_conversation_revision,
                control_message="" if inline_change else message,
                planning_agent_id=planning_agent_id,
                planning_model=planning_model,
                planning_reasoning_effort=planning_reasoning_effort,
            )
        if self.execution_available(current) or self.result_available(current):
            return self.send_execution(
                run_id,
                message,
                planning_agent_id=planning_agent_id,
                planning_model=planning_model,
                planning_reasoning_effort=planning_reasoning_effort,
            )
        return None
