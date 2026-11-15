"""Validate task execution profiles without owning execution or persistence."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Callable, Mapping, Protocol

from ..config import AgentConfig, supported_models, supported_reasoning_efforts
from ..errors import PipelineError
from ..models import ProfileSource, RunState, TaskAction, TaskStatus, WorkTask


class ReviewerCompatibility(Protocol):
    def __call__(self, task: WorkTask, reviewer: AgentConfig, *, policy_added: bool) -> bool: ...


def task_execution_profile_snapshot(task: WorkTask) -> dict[str, str]:
    return {
        "agent_id": task.agent_id, "model": task.model, "reasoning_effort": task.reasoning_effort,
        "last_attempt_id": task.last_attempt_id, "status": task.status.value,
    }


def assign_next_execution_profile(task: WorkTask, proposed: WorkTask) -> bool:
    changed = (task.agent_id, task.provider_id, task.model, task.reasoning_effort, task.profile_source) != (
        proposed.agent_id, proposed.provider_id, proposed.model, proposed.reasoning_effort, ProfileSource.MANUAL
    )
    task.agent_id, task.provider_id = proposed.agent_id, proposed.provider_id
    task.model, task.reasoning_effort = proposed.model, proposed.reasoning_effort
    task.profile_source = ProfileSource.MANUAL
    task.effort_baseline_reasoning = None
    task.routing_reason, task.routing_confidence = "user selected next execution profile", 1.0
    if changed and task.status == TaskStatus.FAILED:
        task.failed_action = TaskAction.EXECUTE
    return changed


def normalize_agent_id(agent_id: str) -> str:
    normalized = agent_id.strip()
    if "\x00" in normalized or "\n" in normalized or "\r" in normalized:
        raise PipelineError("agent id must be a single-line value")
    return normalized


def normalize_model(model: str) -> str:
    normalized = model.strip()
    if "\x00" in normalized or "\n" in normalized or "\r" in normalized:
        raise PipelineError("planning model must be a single-line model id")
    return normalized


def normalize_reasoning_effort(effort: str) -> str:
    normalized = effort.strip().casefold()
    if "\x00" in normalized or "\n" in normalized or "\r" in normalized:
        raise PipelineError("reasoning effort must be a single-line value")
    return normalized


def validate_reasoning_effort(agent: AgentConfig, effort: str, model: str) -> None:
    if not effort:
        return
    supported = supported_reasoning_efforts(agent.provider_id, model)
    if effort not in supported:
        available = ", ".join(supported) or "provider default only"
        raise PipelineError(f"unsupported reasoning effort for {agent.provider_id}/{model or 'default model'}: {effort}; available: {available}")


def validate_task_profile_override_targets(state: RunState, task_ids: set[str]) -> None:
    if not task_ids:
        return
    tasks = {task.id: task for task in state.tasks}
    unknown_tasks = task_ids - set(tasks)
    if unknown_tasks:
        raise PipelineError("unknown task execution profile overrides: " + ", ".join(sorted(unknown_tasks)))
    immutable_tasks = sorted(task_id for task_id in task_ids if tasks[task_id].status != TaskStatus.PENDING)
    if immutable_tasks:
        raise PipelineError("execution profile can be changed only for pending tasks: " + ", ".join(immutable_tasks))


@dataclass(frozen=True, slots=True)
class TaskProfileValidator:
    agents: Mapping[str, AgentConfig]
    configured_agents: tuple[AgentConfig, ...]
    registered_models: Callable[[], tuple[str, ...]]
    available_agent: Callable[[str, str], AgentConfig]
    is_selectable: Callable[[AgentConfig, str], bool]
    reviewer_compatible: ReviewerCompatibility

    def validate_next(
        self, state: RunState, task: WorkTask, agent_id: str, model: str, reasoning_effort: str
    ) -> WorkTask:
        agent = self.available_agent(normalize_agent_id(agent_id), "execute")
        if not self.is_selectable(agent, "execute"):
            raise PipelineError("선택한 실행 AI를 현재 사용할 수 없습니다. AI 연결을 확인해 주세요.")
        if not (set(task.capabilities) & set(agent.capabilities) or "general" in agent.capabilities):
            raise PipelineError(f"선택한 실행 AI가 작업 역량을 지원하지 않습니다: {task.id}")
        model = normalize_model(model)
        reasoning_effort = normalize_reasoning_effort(reasoning_effort)
        self.validate_model_overrides(state, {task.id: model}, {task.id: agent.id})
        self.validate_reasoning_overrides(state, {task.id: reasoning_effort}, {task.id: agent.id}, {task.id: model})
        proposed = deepcopy(task)
        proposed.agent_id, proposed.provider_id = agent.id, agent.provider_id
        proposed.model, proposed.reasoning_effort = model, reasoning_effort
        proposed.profile_source = ProfileSource.MANUAL
        if task.reviewer_agent_id:
            reviewer = self.available_agent(task.reviewer_agent_id, "review")
            if not self.reviewer_compatible(proposed, reviewer, policy_added=task.review_policy_added):
                raise PipelineError("선택한 실행 AI가 현재 리뷰 AI와 호환되지 않습니다. 다른 실행 AI를 선택해 주세요.")
        return proposed

    def validate_model_overrides(self, state: RunState, overrides: dict[str, str], agent_overrides: dict[str, str]) -> None:
        tasks = {task.id: task for task in state.tasks}
        unknown_tasks = set(overrides) - set(tasks)
        if unknown_tasks:
            raise PipelineError("unknown task model overrides: " + ", ".join(sorted(unknown_tasks)))
        for task_id, raw_model in overrides.items():
            model = normalize_model(raw_model)
            task = tasks[task_id]
            agent_id = agent_overrides.get(task_id, task.agent_id)
            agent = self.agents.get(agent_id)
            if agent is None:
                raise PipelineError(f"unknown execution agent for task {task_id}: {agent_id}")
            available_models = supported_models(
                agent.provider_id, tuple(item.model for item in self.configured_agents if item.provider_id == agent.provider_id and item.model)
            )
            if agent.provider_id == "nvidia":
                available_models += self.registered_models()
            if model and model not in available_models:
                available = ", ".join(available_models) or "provider default only"
                raise PipelineError(f"unsupported execution model for {agent.provider_id}: {model}; available: {available}")

    def validate_reasoning_overrides(
        self, state: RunState, overrides: dict[str, str], agent_overrides: dict[str, str], model_overrides: dict[str, str] | None = None
    ) -> None:
        tasks = {task.id: task for task in state.tasks}
        unknown_tasks = set(overrides) - set(tasks)
        if unknown_tasks:
            raise PipelineError("unknown task reasoning overrides: " + ", ".join(sorted(unknown_tasks)))
        for task_id, raw_effort in overrides.items():
            task = tasks[task_id]
            effort = normalize_reasoning_effort(raw_effort)
            agent_id = agent_overrides.get(task_id, task.agent_id)
            agent = self.agents.get(agent_id)
            if agent is None:
                raise PipelineError(f"unknown execution agent for task {task_id}: {agent_id}")
            model = (model_overrides or {}).get(task_id, agent.model if task_id in agent_overrides else task.model)
            validate_reasoning_effort(agent, effort, model)
