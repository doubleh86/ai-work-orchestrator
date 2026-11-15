"""Planning apply input validation and request composition."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Protocol

from ..config import AgentConfig
from ..errors import PipelineError
from ..models import (
    PlanningApplyRequest, PlanningApplyStatus, RunLockState, RunLockStatus, RunState, RunStep, Stage, TaskStatus,
    TechStackDecisionStatus,
)


class PlanningApplyProfile(Protocol):
    def __call__(
        self, state: RunState, *, planning_agent_id: str | None, planning_model: str | None, planning_reasoning_effort: str | None
    ) -> AgentConfig:
        ...


class PlanningApplyRequestCreator(Protocol):
    def __call__(
        self,
        state: RunState,
        request_id: str,
        expected_revision: int,
        conversation_revision: int,
        *,
        status: PlanningApplyStatus,
        answer_message: str = "",
        tech_stack_revision: int | None = None,
    ) -> PlanningApplyRequest:
        ...


class PlanningApplyMessage(Protocol):
    def __call__(self, state: RunState, message: str, *, counts_as_discussion: bool) -> None: ...


class PlanningPendingApply(Protocol):
    def __call__(self, state: RunState, *, apply_request: PlanningApplyRequest) -> RunState: ...


class PlanningConversationApply(Protocol):
    def __call__(self, state: RunState, *, event_message: str, apply_request: PlanningApplyRequest) -> RunState: ...


@dataclass(frozen=True, slots=True)
class PlanningApplyInput:
    request_id: str
    expected_revision: int
    conversation_revision: int
    control_message: str = ""
    answer_message: str = ""
    expected_tech_stack_revision: int | None = None
    retry_failed: bool = False
    planning_agent_id: str | None = None
    planning_model: str | None = None
    planning_reasoning_effort: str | None = None


@dataclass(frozen=True, slots=True)
class PlanningApplyPreparation:
    request: PlanningApplyInput
    state: RunState
    execution_active: bool = False
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class PlanningApplyRecords:
    load_run: Callable[[str], RunState]
    save_chat: Callable[[RunState], None]
    inspect_lock: Callable[[str], RunLockStatus]


@dataclass(frozen=True, slots=True)
class PlanningApplyWorkflow:
    records: PlanningApplyRecords
    execution_operations: frozenset[str]
    normalize_request_id: Callable[[str], str]
    find_request: Callable[[RunState, str], PlanningApplyRequest | None]
    validate_replay: Callable[[PlanningApplyRequest, int, int], None]
    validate_stack: Callable[[RunState, int | None, str], None]
    validate_stack_replay: Callable[[PlanningApplyRequest, str, int | None], None]
    new_request: PlanningApplyRequestCreator
    configure_profile: PlanningApplyProfile
    append_user: PlanningApplyMessage
    append_assistant: PlanningApplyMessage
    follow_up_request: Callable[[RunState], str]
    apply_pending: PlanningPendingApply
    apply_conversation: PlanningConversationApply

    def prepare(self, run_id: str, inputs: PlanningApplyInput) -> PlanningApplyPreparation:
        request_id, answer_message = inputs.request_id, inputs.answer_message
        expected_revision, conversation_revision = inputs.expected_revision, inputs.conversation_revision
        expected_tech_stack_revision, retry_failed = inputs.expected_tech_stack_revision, inputs.retry_failed
        normalized_request_id = self.normalize_request_id(request_id)
        answer_message = answer_message.strip()
        normalized = replace(inputs, request_id=normalized_request_id, answer_message=answer_message)
        if answer_message and expected_tech_stack_revision is None:
            raise PipelineError("답변할 기술 후보의 revision이 필요합니다.")
        if retry_failed and expected_tech_stack_revision is None:
            raise PipelineError("기술 추천·기본 구조 계획의 저장된 요청만 이 방식으로 재시도할 수 있습니다.")
        current = self.records.load_run(run_id)
        existing = self.find_request(current, normalized_request_id)
        if existing is not None:
            self.validate_replay(existing, expected_revision, conversation_revision)
            self.validate_stack_replay(existing, answer_message, expected_tech_stack_revision)
            if not retry_failed or existing.status != PlanningApplyStatus.FAILED:
                return PlanningApplyPreparation(normalized, current, replayed=True)
        elif retry_failed:
            raise PipelineError("재시도할 저장된 계획 요청이 없습니다.")
        self.validate_stack(current, expected_tech_stack_revision, answer_message)
        if current.active_step == RunStep.PLANNING:
            raise PipelineError("Planning AI의 대화 응답이 끝난 뒤 Task에 반영할 수 있습니다.")
        execution_active = any(
            task.active_action or task.status in {TaskStatus.RUNNING, TaskStatus.REVIEWING, TaskStatus.REVISING}
            for task in current.tasks
        )
        lock = self.records.inspect_lock(run_id)
        execution_active = execution_active or (
            lock.state == RunLockState.ACTIVE and lock.operation in self.execution_operations
        )
        return PlanningApplyPreparation(normalized, current, execution_active=execution_active)

    def queue(self, run_id: str, inputs: PlanningApplyInput) -> RunState:
        normalized_request_id = inputs.request_id
        expected_revision, conversation_revision = inputs.expected_revision, inputs.conversation_revision
        control_message = inputs.control_message
        planning_agent_id, planning_model = inputs.planning_agent_id, inputs.planning_model
        planning_reasoning_effort = inputs.planning_reasoning_effort
        state = self.records.load_run(run_id)
        existing = self.find_request(state, normalized_request_id)
        if existing is not None:
            self.validate_replay(existing, expected_revision, conversation_revision)
            return state
        request = self.new_request(
            state,
            normalized_request_id,
            expected_revision,
            conversation_revision,
            status=PlanningApplyStatus.QUEUED,
        )
        if request.request_id != normalized_request_id:
            return state
        self.configure_profile(
            state,
            planning_agent_id=planning_agent_id,
            planning_model=planning_model,
            planning_reasoning_effort=planning_reasoning_effort,
        )
        if control_message:
            self.append_user(state, control_message, counts_as_discussion=False)
        follow_up = self.follow_up_request(state)
        if follow_up not in state.planning_follow_up_requests:
            state.planning_follow_up_requests.append(follow_up)
        self.append_assistant(
            state,
            "현재 실행이 끝난 뒤 같은 작업 그룹의 Task에 반영하도록 예약했습니다. 완료 결과와 실행 이력은 보존합니다.",
            counts_as_discussion=False,
        )
        state.add_event("planning", "planning apply queued during execution")
        self.records.save_chat(state)
        return state

    def apply(self, run_id: str, inputs: PlanningApplyInput) -> RunState:
        normalized_request_id = inputs.request_id
        expected_revision, conversation_revision = inputs.expected_revision, inputs.conversation_revision
        control_message, answer_message = inputs.control_message, inputs.answer_message
        expected_tech_stack_revision, retry_failed = inputs.expected_tech_stack_revision, inputs.retry_failed
        planning_agent_id, planning_model = inputs.planning_agent_id, inputs.planning_model
        planning_reasoning_effort = inputs.planning_reasoning_effort
        state = self.records.load_run(run_id)
        existing = self.find_request(state, normalized_request_id)
        if existing is not None:
            self.validate_replay(existing, expected_revision, conversation_revision)
            self.validate_stack_replay(existing, answer_message, expected_tech_stack_revision)
            if not retry_failed or existing.status != PlanningApplyStatus.FAILED:
                return state
            self.validate_stack(state, expected_tech_stack_revision, answer_message)
            if state.plan_revision != existing.plan_revision or state.planning_conversation_revision != existing.answer_conversation_revision:
                raise PipelineError("답변이나 계획이 변경되었습니다. 현재 내용을 확인하고 새 요청으로 진행해 주세요.")
            request = existing
            request.error = request.error_code = request.completed_at = ""
        else:
            self.validate_stack(state, expected_tech_stack_revision, answer_message)
            request = self.new_request(
                state, normalized_request_id, expected_revision, conversation_revision,
                status=PlanningApplyStatus.APPLYING, answer_message=answer_message,
                tech_stack_revision=expected_tech_stack_revision,
            )
        if request.request_id != normalized_request_id:
            return state
        self.configure_profile(
            state,
            planning_agent_id=planning_agent_id,
            planning_model=planning_model,
            planning_reasoning_effort=planning_reasoning_effort,
        )
        if control_message:
            self.append_user(state, control_message, counts_as_discussion=False)
        if state.stage in {Stage.EXECUTING, Stage.FAILED, Stage.READY_TO_MERGE} and state.tasks:
            follow_up = self.follow_up_request(state)
            if follow_up not in state.planning_follow_up_requests:
                state.planning_follow_up_requests.append(follow_up)
            self.records.save_chat(state)
            return self.apply_pending(state, apply_request=request)
        if state.stage == Stage.FAILED:
            if state.failed_step != RunStep.PLANNING:
                raise PipelineError(f"run {run_id} did not fail during planning")
        elif state.stage not in {Stage.NEEDS_CLARIFICATION, Stage.PLANNED}:
            raise PipelineError(
                f"run {run_id} is at '{state.stage.value}', expected '{Stage.NEEDS_CLARIFICATION.value}' or '{Stage.PLANNED.value}'"
            )
        return self.apply_conversation(
            state,
            event_message="planning apply requested from chat" if control_message else "planning apply requested",
            apply_request=request,
        )


def normalize_planning_apply_request_id(request_id: str) -> str:
    normalized = request_id.strip()
    if not normalized or len(normalized) > 128 or any(character in normalized for character in "\r\n\0"):
        raise PipelineError("planning apply requestId is invalid")
    return normalized


def validate_tech_stack_apply(state: RunState, expected_revision: int | None, answer: str) -> None:
    if expected_revision is None:
        return
    decision = state.current_tech_stack_decision()
    if state.repository_intent != "new_project" or state.tasks:
        raise PipelineError("현재 단계에서는 기술 추천이나 기본 구조 계획을 다시 작성할 수 없습니다.")
    if state.stage not in {Stage.NEEDS_CLARIFICATION, Stage.PLANNED, Stage.FAILED} or (
        state.stage == Stage.FAILED and state.failed_step != RunStep.PLANNING
    ):
        raise PipelineError("현재 기획 단계와 실패 위치를 확인해 주세요.")
    if expected_revision < 0 or (decision.revision if decision else 0) != expected_revision:
        raise PipelineError("기술 구성 후보가 변경되었습니다. 현재 추천과 질문을 확인해 주세요.")
    if answer:
        if not state.planning_questions or (decision and decision.status == TechStackDecisionStatus.CONFIRMED):
            raise PipelineError("답변할 기술 추천 질문이 변경되었습니다. 현재 단계를 확인해 주세요.")
    elif decision is None or decision.status != TechStackDecisionStatus.CONFIRMED:
        raise PipelineError("기술 구성을 먼저 결정해 주세요.")


def validate_tech_stack_apply_replay(request: PlanningApplyRequest, answer: str, expected_revision: int | None) -> None:
    if request.answer_message != answer or request.tech_stack_revision != (expected_revision or 0):
        raise PipelineError("requestId가 다른 기술 추천 요청에 사용되었습니다.")


def validate_planning_apply_replay(
    request: PlanningApplyRequest, expected_revision: int, conversation_revision: int,
) -> None:
    if request.plan_revision != expected_revision or request.conversation_revision != conversation_revision:
        raise PipelineError("requestId가 다른 Planning 반영 요청에 사용되었습니다.")
