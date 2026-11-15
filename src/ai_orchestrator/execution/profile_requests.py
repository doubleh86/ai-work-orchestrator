"""Save, display and consume next-task selections under caller-owned locks."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Callable, Mapping

from ..config import AgentConfig
from ..errors import PipelineError
from ..models import EffortPolicyState, ProfileSource, RunState, RunStep, Stage, TaskStatus, WorkTask, utc_now
from .profiles import assign_next_execution_profile, task_execution_profile_snapshot

TaskProfileRequests = dict[str, dict[str, object]]


@dataclass(frozen=True, slots=True)
class TaskProfileRecords:
    load_requests: Callable[[str], TaskProfileRequests]
    save_requests: Callable[[str, TaskProfileRequests], None]
    save_state: Callable[[RunState], None]
    load_policy: Callable[[str], EffortPolicyState]


@dataclass(frozen=True, slots=True)
class TaskProfileService:
    agents: Mapping[str, AgentConfig]
    records: TaskProfileRecords
    validate: Callable[[RunState, WorkTask, str, str, str], WorkTask]
    find_task: Callable[[RunState, str], WorkTask]
    refresh_plan: Callable[[RunState], None]

    def save(
        self, state: RunState, task_id: str, *, agent_id: str, model: str, reasoning_effort: str, expected_profile: dict[str, str]
    ) -> RunState:
        run_id = state.id
        if state.stage == Stage.FAILED and state.failed_step != RunStep.AGENT_EXECUTION:
            raise PipelineError("Agent 실행 실패 단계에서만 다음 실행 모델을 변경할 수 있습니다.")
        if state.active_step is not None or any(
            task.active_action or task.status in {TaskStatus.RUNNING, TaskStatus.REVIEWING, TaskStatus.REVISING} for task in state.tasks
        ):
            raise PipelineError("그룹 작업이 진행 중입니다. 멈춘 상태에서 다음 실행 모델을 변경해 주세요.")
        policy = self.records.load_policy(run_id)
        if any(binding.status in {"prepared", "started"} for binding in policy.execution_bindings):
            raise PipelineError("확인되지 않은 실행 예약이 있습니다. 실행 상태를 확인한 뒤 모델을 변경해 주세요.")
        task = self.find_task(state, task_id)
        if task.status not in {TaskStatus.PENDING, TaskStatus.FAILED}:
            raise PipelineError("실패하거나 아직 시작하지 않은 Task의 다음 실행 모델만 변경할 수 있습니다.")
        visible_task = self.find_task(self.view(state), task_id)
        if expected_profile != task_execution_profile_snapshot(visible_task):
            raise PipelineError("작업 상태 또는 저장된 모델이 변경됐습니다. 최신 설정을 다시 확인해 주세요.")
        proposed = self.validate(state, task, agent_id, model, reasoning_effort)
        changed = assign_next_execution_profile(task, proposed)
        profiles = self.records.load_requests(run_id)
        if not changed and task.profile_source == ProfileSource.MANUAL and task.id not in profiles:
            return state
        self.refresh_plan(state)
        state.add_event(
            "routing", f"{task.id} next execution profile saved: {task.provider_id}/{task.agent_id} · {task.model or 'provider default'}"
        )
        self.records.save_state(state)
        if profiles.pop(task.id, None) is not None:
            self.records.save_requests(run_id, profiles)
        return state

    def view(self, state: RunState) -> RunState:
        """Show saved next profiles without changing the execution owner's state."""
        profiles = self.records.load_requests(state.id)
        if not profiles:
            return state
        visible = deepcopy(state)
        for task in visible.tasks:
            request = profiles.get(task.id)
            if (request is None or task.status != TaskStatus.PENDING or task.active_action
                    or request["plan_revision"] != state.plan_revision
                    or request["expected"] != task_execution_profile_snapshot(task)):
                continue
            selection = request["selection"]
            agent = self.agents.get(selection["agent_id"])
            if agent is None:
                continue
            proposed = deepcopy(task)
            proposed.agent_id, proposed.provider_id = agent.id, agent.provider_id
            proposed.model, proposed.reasoning_effort = selection["model"], selection["reasoning_effort"]
            assign_next_execution_profile(task, proposed)
        return visible

    def apply_queued(self, state: RunState) -> bool:
        """Consume selections at a dispatch boundary under the Planning chat lock."""
        profiles = self.records.load_requests(state.id)
        if not profiles:
            return False
        changes: list[tuple[WorkTask, WorkTask]] = []
        consumed: list[str] = []
        try:
            for task_id, request in profiles.items():
                if "applied_policy_id" in request:
                    continue
                task = self.find_task(state, task_id)
                consumed.append(task_id)
                selection = request["selection"]
                current = {"agent_id": task.agent_id, "model": task.model, "reasoning_effort": task.reasoning_effort}
                if current == selection and task.profile_source == ProfileSource.MANUAL:
                    continue
                if (task.status != TaskStatus.PENDING or task.active_action or request["plan_revision"] != state.plan_revision
                        or request["expected"] != task_execution_profile_snapshot(task)):
                    raise PipelineError(f"대기 모델 변경 대상의 상태 또는 계획이 변경됐습니다: {task.id}. 최신 설정을 확인해 주세요.")
                proposed = self.validate(
                    state, task, selection["agent_id"], selection["model"], selection["reasoning_effort"]
                )
                changes.append((task, proposed))
        except PipelineError as exc:
            state.fail_step(RunStep.AGENT_EXECUTION, str(exc))
            self.records.save_state(state)
            raise
        if changes:
            if any(task.active_action or task.status in {TaskStatus.RUNNING, TaskStatus.REVIEWING, TaskStatus.REVISING} for task in state.tasks):
                raise PipelineError("진행 중인 Task가 끝난 뒤 대기 모델 변경을 반영할 수 있습니다.")
            policy = self.records.load_policy(state.id).policy(state.active_policy_id) if state.active_policy_id else None
            if state.active_policy_id and policy is None:
                raise PipelineError("started effort execution policy snapshot is missing")
            for task, proposed in changes:
                receipt = dict(profiles[task.id])
                receipt["applied_policy_id"] = state.active_policy_id
                receipt["policy_baseline"] = dict(policy.task_profiles)[task.id].to_dict() if policy else None
                profiles[f"{task.id}@{state.active_policy_id or 'unbound'}"] = receipt
            # Keep the pending selection until state is saved, with its policy
            # receipt already durable so an interrupted application can replay.
            self.records.save_requests(state.id, profiles)
            for task, proposed in changes:
                assign_next_execution_profile(task, proposed)
                state.add_event("routing", f"{task.id} saved next execution profile applied: {task.provider_id}/{task.agent_id} · {task.model}")
            self.refresh_plan(state)
            self.records.save_state(state)
        if consumed:
            for task_id in consumed:
                profiles.pop(task_id)
            self.records.save_requests(state.id, profiles)
        return bool(changes)

    def queue(
        self, run_id: str, state: RunState, task_id: str, *, agent_id: str, model: str, reasoning_effort: str,
        expected_profile: dict[str, str],
    ) -> RunState:
        task = self.find_task(state, task_id)
        if task.status != TaskStatus.PENDING or task.active_action:
            raise PipelineError("실행 중인 그룹에서는 아직 시작하지 않은 Task의 모델만 변경할 수 있습니다.")
        if state.active_step not in {None, RunStep.AGENT_EXECUTION}:
            raise PipelineError("현재 단계에서는 다음 실행 모델을 변경할 수 없습니다.")
        visible_task = self.find_task(self.view(state), task_id)
        if expected_profile != task_execution_profile_snapshot(visible_task):
            raise PipelineError("작업 상태 또는 저장된 모델이 변경됐습니다. 최신 설정을 다시 확인해 주세요.")
        proposed = self.validate(state, task, agent_id, model, reasoning_effort)
        profiles = self.records.load_requests(run_id)
        profiles[task.id] = {
            "expected": task_execution_profile_snapshot(task), "plan_revision": state.plan_revision, "saved_at": utc_now(),
            "selection": {"agent_id": proposed.agent_id, "model": proposed.model, "reasoning_effort": proposed.reasoning_effort},
        }
        self.records.save_requests(run_id, profiles)
        return self.view(state)
