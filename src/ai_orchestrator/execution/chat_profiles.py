"""Prepare and save chat-selected profiles before recovery attempts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, ContextManager, Protocol

from ..config import AgentConfig
from ..errors import PipelineError
from ..models import ExecutionControlRecord, OperationRecord, RunState, Stage, TaskStatus, WorkTask
from ..project_chat import TaskProfileCommand
from ..planning import PlanningError, select_agent_for_provider


class ChatProfileSave(Protocol):
    def __call__(
        self, state: RunState, task_id: str, *, agent_id: str, model: str, reasoning_effort: str, expected_profile: dict[str, str]
    ) -> RunState:
        ...


class ChatProfileRepair(Protocol):
    def __call__(
        self, run_id: str, task_id: str, *, request_id: str, message: str, fingerprint: str, conversation_revision: int,
        parent_request_id: str = "", recovery_fingerprint: str = "",
    ) -> RunState:
        ...


@dataclass(frozen=True, slots=True)
class ChatProfileRecords:
    load_run: Callable[[str], RunState]
    load_operation: Callable[[str, str], OperationRecord | None]
    save_operation: Callable[[OperationRecord], None]
    control_lock: Callable[[str], ContextManager[None]]


@dataclass(frozen=True, slots=True)
class SavedChatProfile:
    state: RunState
    task: WorkTask
    operation: OperationRecord
    provider: str
    model: str
    effort: str
    retry: bool


@dataclass(frozen=True, slots=True)
class ChatExecutionProfiles:
    records: ChatProfileRecords
    read_agents: Callable[[], tuple[AgentConfig, ...]]
    is_selectable: Callable[[AgentConfig, str], bool]
    connected_providers: Callable[[set[str]], set[str]]
    find_task: Callable[[RunState, str], WorkTask]
    validate_target: Callable[[RunState, OperationRecord], None]
    save_profile: ChatProfileSave
    fingerprint: Callable[[RunState], str]
    record_chat: Callable[[str, str, str], RunState]
    retry_context: Callable[[str, str], dict[str, object]]
    repair: ChatProfileRepair

    def save_locked(self, state: RunState, run_id: str, request_id: str, step_id: str) -> SavedChatProfile:
        record = self.records.load_operation(run_id, request_id)
        if record is None or record.status != "running" or record.phase != "acting" or record.payload.get("step_id") != step_id:
            raise PipelineError("실행 AI 변경 요청이 취소되었거나 대상이 변경됐습니다.")
        self.validate_target(state, record)
        decision = record.payload["decision"]
        task = self.find_task(state, str(decision["task_id"]))
        provider = str(decision["provider"])
        agents = tuple(
            agent for agent in self.read_agents()
            if agent.provider_id == provider and self.is_selectable(agent, "execute")
            and (set(task.capabilities) & set(agent.capabilities) or "general" in agent.capabilities)
        )
        if not agents or provider not in self.connected_providers({provider}):
            raise PipelineError(f"이 작업에 사용할 수 있는 {provider} 연결이 없습니다. AI 연결을 확인해 주세요.")
        agent = next((candidate for candidate in agents if candidate.id == task.agent_id), None)
        if agent is None:
            try:
                agent = select_agent_for_provider(task, agents, provider, purpose="execution")
            except PlanningError as exc:
                raise PipelineError(str(exc)) from exc
        model = str(decision["model"]) or (task.model if task.agent_id == agent.id else agent.model)
        effort = str(decision["reasoning_effort"]) or (
            task.reasoning_effort if task.agent_id == agent.id and task.model == model else ""
        )
        with self.records.control_lock(run_id):
            latest = self.records.load_operation(run_id, request_id)
            if latest is None or latest.status != "running" or latest.phase != "acting" or latest.payload.get("step_id") != step_id:
                raise PipelineError("실행 AI 변경 요청이 취소됐습니다.")
            self.save_profile(
                state, task.id, agent_id=agent.id, model=model, reasoning_effort=effort,
                expected_profile=decision["expected_profile"],
            )
            saved = self.records.load_run(run_id)
            saved_task = self.find_task(saved, task.id)
            if (saved_task.agent_id, saved_task.provider_id, saved_task.model, saved_task.reasoning_effort) != (agent.id, provider, model, effort):
                raise PipelineError("저장된 실행 AI 설정을 확인하지 못했습니다.")
            latest.payload["fingerprint"] = self.fingerprint(saved)
            if not decision["retry"]:
                latest.update("completed", status="succeeded")
            self.records.save_operation(latest)
        return SavedChatProfile(saved, task, latest, provider, model, effort, decision["retry"])

    def finish(self, run_id: str, request_id: str, step_id: str, change: SavedChatProfile) -> dict[str, object]:
        saved, task, latest = change.state, change.task, change.operation
        provider, model, effort = change.provider, change.model, change.effort

        provider_label = "Codex" if provider == "codex" else "Claude"
        profile = " · ".join(value for value in (provider_label, model, effort) if value)
        self.record_chat(run_id, "", f"‘{task.title}’의 다음 실행 AI를 {profile}(으)로 저장했습니다.")
        if not change.retry:
            return latest.to_dict()

        context = self.retry_context(run_id, task.id)
        final = self.repair(
            run_id, task.id, request_id=step_id, message="저장한 실행 AI로 실패 작업을 복구하고 계속 진행해 주세요.",
            fingerprint=context["fingerprint"], conversation_revision=saved.planning_conversation_revision,
            parent_request_id=request_id, recovery_fingerprint=context["recovery"]["fingerprint"],
        )
        with self.records.control_lock(run_id):
            latest = self.records.load_operation(run_id, request_id)
            if latest is None:
                raise PipelineError("실행 AI 변경 요청의 복구 결과를 찾지 못했습니다.")
            if latest.status != "running":
                return latest.to_dict()
            if final.stage == Stage.FAILED:
                latest.update("blocked", status="failed", error=final.failure_message or "저장한 실행 AI로 복구하지 못했습니다.")
            else:
                latest.update("completed", status="succeeded")
            self.records.save_operation(latest)
        completed = sum(task.status in {TaskStatus.COMPLETED, TaskStatus.MERGED} for task in final.tasks)
        summary = f"{profile} 복구 결과 · {completed}/{len(final.tasks)} 완료"
        if latest.error:
            summary += f" · {latest.error}"
        self.record_chat(run_id, "", summary)
        return latest.to_dict()



@dataclass(frozen=True, slots=True)
class ChatProfileDecision:
    load_run: Callable[[str], RunState]
    load_operation: Callable[[str, str], OperationRecord | None]
    save_operation: Callable[[OperationRecord], None]
    load_control: Callable[[str], ExecutionControlRecord | None]
    validate_target: Callable[[RunState, OperationRecord], None]
    find_task: Callable[[RunState, str], WorkTask]
    profile_view: Callable[[RunState], RunState]
    profile_snapshot: Callable[[WorkTask], dict[str, str]]

    def prepare_locked(self, run_id: str, request_id: str, command: TaskProfileCommand) -> dict[str, object]:
        record = self.load_operation(run_id, request_id)
        if record is None or record.status != "running" or record.phase != "deciding":
            raise PipelineError("실행 AI 변경 요청이 이미 종료됐습니다.")
        state = self.load_run(run_id)
        self.validate_target(state, record)
        target = command.target
        candidates = [task for task in state.tasks if target in {task.id, task.title}]
        if not candidates:
            failed = re.match(r"^실패(?:한)?\s+", target)
            target = re.sub(r"(?:^|\s)(?:작업|Task)(?:을|를|만)?$", "", target[failed.end():] if failed else target).strip()
            eligible = [task for task in state.tasks if not failed or task.status == TaskStatus.FAILED]
            if target and target not in {"이거", "이", "해당", "선택한"}:
                words = re.findall(r"[\w-]+", target.casefold())
                candidates = [task for task in eligible if target in {task.id, task.title} or (
                    len(words) >= 2 and set(words) <= set(re.findall(r"[\w-]+", task.title.casefold()))
                )]
            else:
                focused_id = record.payload["expected"].get("taskId")
                candidates = [task for task in eligible if task.id == focused_id] if focused_id else [
                    task for task in eligible if task.status == TaskStatus.FAILED
                ]
        if len(candidates) != 1:
            raise PipelineError("실행 AI를 바꿀 작업을 하나로 특정하지 못했습니다. 작업 제목이나 ID를 포함해 다시 요청해 주세요.")
        task = candidates[0]
        expected = record.payload["expected"]
        execution = self.load_control(run_id)
        if "executionId" in expected and expected["executionId"] != (execution.execution_id if execution else ""):
            raise PipelineError("화면의 그룹 실행이 변경됐습니다. 최신 상태에서 다시 요청해 주세요.")
        if expected.get("taskId") == task.id and "attemptId" in expected and expected["attemptId"] != task.last_attempt_id:
            raise PipelineError("화면의 작업 시도와 현재 시도가 다릅니다. 최신 상태에서 다시 요청해 주세요.")
        if command.retry and task.status != TaskStatus.FAILED:
            raise PipelineError("변경과 재시도를 함께 요청하려면 실패한 작업을 지정해 주세요.")
        record.payload["decision"] = {
            "action": "set_execution_profile", "task_id": task.id, "provider": command.provider,
            "model": command.model, "reasoning_effort": command.reasoning_effort, "retry": command.retry,
            "expected_profile": self.profile_snapshot(self.find_task(self.profile_view(state), task.id)),
        }
        record.phase = "decision_ready"
        self.save_operation(record)
        return record.to_dict()
