"""Dispatch prepared tasks inside the caller's execution policy and run lock."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, ContextManager, Mapping

from ..config import AgentConfig
from ..errors import PipelineError
from ..git_contracts import GitError
from ..models import DirectionChangeStatus, RunState, RunStep, TaskAction, TaskStatus, WorkTask
from ..persistence.errors import RunLockedError


@dataclass(frozen=True, slots=True)
class DispatchRecords:
    load_state: Callable[[str], RunState]
    save_state: Callable[[RunState], None]
    planning_chat_lock: Callable[[str], ContextManager[object]]


@dataclass(frozen=True, slots=True)
class TaskDispatcher:
    records: DispatchRecords
    agents: Mapping[str, AgentConfig]
    ready_tasks: Callable[[RunState, list[WorkTask]], list[WorkTask]]
    shared_workspace: Callable[[RunState], bool]
    agent_available: Callable[[AgentConfig, str], bool]
    apply_queued_profiles: Callable[[RunState], None]
    pause_for_direction_change: Callable[[RunState], RunState | None]
    apply_quota_fallbacks: Callable[[RunState, list[WorkTask]], None]
    prepare_task: Callable[[RunState, WorkTask], None]
    run_batch: Callable[[RunState, list[WorkTask], dict[str, TaskAction]], None]
    apply_changes_after_batch: Callable[[RunState], RunState | None]
    advance_completed: Callable[[RunState], None]

    def run(
        self, state: RunState, *, manual: bool, excluded_task_ids: set[str], selected_task_ids: set[str] | None = None,
    ) -> RunState:
        if any(item.status != DirectionChangeStatus.APPLIED for item in state.direction_change_requests):
            raise PipelineError("방향 수정 요청의 변경 미리보기를 확인·반영한 뒤 다음 Task를 실행해 주세요.")

        pending = [
            task
            for task in state.tasks
            if task.status in {TaskStatus.PENDING, TaskStatus.WAITING, TaskStatus.STOPPED}
            and task.id not in excluded_task_ids
            and (selected_task_ids is None or task.id in selected_task_ids)
        ]
        if manual:
            state.begin_step(RunStep.AGENT_EXECUTION)
            ready = self.ready_tasks(state, pending)
            if self.shared_workspace(state):
                ready = ready[:1]
            with self.records.planning_chat_lock(state.id):
                self.apply_queued_profiles(state)
                for task in ready:
                    task.status = TaskStatus.RUNNING
                self.records.save_state(state)
            if pending and not ready:
                message = "no tasks have completed dependencies for manual handoff"
                state.fail_step(RunStep.AGENT_EXECUTION, message)
                self.records.save_state(state)
                raise PipelineError(message)
            for task in ready:
                try:
                    self.prepare_task(state, task)
                except (GitError, PipelineError) as exc:
                    task.status = TaskStatus.FAILED
                    task.failed_action = task.failed_action or TaskAction.EXECUTE
                    task.error = str(exc)
                    state.fail_step(RunStep.AGENT_EXECUTION, str(exc))
                    self.records.save_state(state)
                    raise
                task.status = TaskStatus.WAITING
            state.complete_step(RunStep.AGENT_EXECUTION)
            state.add_event("execution", "manual agent handoff prepared")
            if state.user_check_plan:
                self.advance_completed(state)
            self.records.save_state(state)
            return state

        missing_agents: set[str] = set()
        for task in pending:
            resume_action = task.failed_action or TaskAction.EXECUTE
            required: list[tuple[str, str]] = []
            if resume_action != TaskAction.VERIFY:
                required.append((task.reviewer_agent_id, "review"))
                if resume_action != TaskAction.REVIEW:
                    required.insert(0, (task.agent_id, "execute"))
            for agent_id, action in required:
                agent = self.agents.get(agent_id)
                if agent_id and (agent is None or not self.agent_available(agent, action)):
                    missing_agents.add(agent_id)
        if missing_agents:
            names = ", ".join(sorted(missing_agents))
            message = f"agents unavailable for execution: {names}; configure provider runtime or use --manual"
            state.fail_step(RunStep.AGENT_EXECUTION, message)
            self.records.save_state(state)
            raise PipelineError(message)

        state.begin_step(RunStep.AGENT_EXECUTION)
        resume_actions = {task.id: task.failed_action or TaskAction.EXECUTE for task in pending}
        remaining = list(pending)
        while remaining:
            ready = self.ready_tasks(state, remaining)
            if self.shared_workspace(state):
                ready = ready[:1]
            if not ready:
                blocked = ", ".join(task.id for task in remaining)
                message = f"tasks blocked by incomplete dependencies: {blocked}"
                state.fail_step(RunStep.AGENT_EXECUTION, message)
                self.records.save_state(state)
                return state
            runnable: list[WorkTask] = []
            with self.records.planning_chat_lock(state.id):
                paused = self.pause_for_direction_change(self.records.load_state(state.id))
                if paused is not None:
                    return paused
                self.apply_queued_profiles(state)
                self.apply_quota_fallbacks(state, ready)
                for task in ready:
                    task.status = TaskStatus.RUNNING
                    task.update_progress("preparing_task", "선행 결과와 Git·실행 환경을 확인하고 있습니다.")
                    state.add_event("execution", f"{task.id} execution preparation started")
                state.refresh_task_readiness()
                self.records.save_state(state)
            for task in ready:
                try:
                    self.prepare_task(state, task)
                except (GitError, PipelineError) as exc:
                    task.status = TaskStatus.FAILED
                    task.failed_action = resume_actions[task.id]
                    task.error = str(exc)
                    task.clear_progress()
                    state.add_event("task", f"{task.id} failed: {exc}")
                else:
                    runnable.append(task)
            state.refresh_task_readiness()
            self.records.save_state(state)
            self.run_batch(state, runnable, resume_actions)
            if any(task.status == TaskStatus.STOPPED for task in state.tasks):
                state.active_step = None
                state.failed_step = None
                state.failure_message = ""
                state.add_event("execution", "사용자 요청으로 그룹 실행을 중지하고 작업을 보존했습니다.")
                state.refresh_task_readiness()
                self.records.save_state(state)
                return state
            try:
                applied = self.apply_changes_after_batch(state)
            except RunLockedError:
                failed = [task for task in state.tasks if task.status == TaskStatus.FAILED]
                if failed:
                    state.fail_step(RunStep.AGENT_EXECUTION, "; ".join(f"{task.id}: {task.error}" for task in failed))
                else:
                    state.complete_step(RunStep.AGENT_EXECUTION)
                state.add_event("planning", "Planning 대화가 진행 중입니다. 대화 종료 후 같은 그룹에 적용해 주세요.")
                self.records.save_state(state)
                return self.records.load_state(state.id)
            if applied is not None:
                return applied
            if any(task.status == TaskStatus.FAILED for task in ready):
                break
            completed_ids = {task.id for task in ready}
            remaining = [task for task in remaining if task.id not in completed_ids]

        failed_tasks = [f"{task.id}: {task.error}" for task in state.tasks if task.status == TaskStatus.FAILED]
        if failed_tasks:
            state.fail_step(RunStep.AGENT_EXECUTION, "one or more agent tasks failed: " + "; ".join(failed_tasks))
        elif all(task.status == TaskStatus.COMPLETED for task in state.tasks):
            state.complete_step(RunStep.AGENT_EXECUTION)
            self.advance_completed(state)
        elif selected_task_ids is not None or excluded_task_ids:
            state.complete_step(RunStep.AGENT_EXECUTION)
            if selected_task_ids is not None:
                state.add_event("execution", "selected agent task completed")
        state.refresh_task_readiness()
        self.records.save_state(state)
        return state
