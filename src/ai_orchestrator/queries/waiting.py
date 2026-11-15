"""Evidence-based next-step prompts without execution or state writes."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..models import (
    DirectionChangeStatus, IntegrationControl, IntegrationStatus, RunExecutionAction, RunExecutionControl, RunExecutionSituation,
    RunLockState, RunLockStatus, RunState, RunStep, Stage, TaskReadiness, TaskStatus, UserNotificationEvent, WorkTask,
)
from ..notifications import notification_events_for_state, retry_wait_event


@dataclass(frozen=True, slots=True)
class WaitingPromptRecords:
    inspect_lock: Callable[[str], RunLockStatus]
    inspect_planning_chat_lock: Callable[[str], RunLockStatus]
    load_notification_events: Callable[[str], list[UserNotificationEvent]]


@dataclass(frozen=True, slots=True)
class WaitingPromptQueries:
    repo: Path
    records: WaitingPromptRecords
    retry_context: Callable[[RunState, str], dict[str, object]]
    ready_tasks: Callable[[RunState, list[WorkTask]], list[WorkTask]]

    def waiting_prompt(
        self, state: RunState, control: RunExecutionControl, integration: IntegrationControl | None = None,
    ) -> dict[str, object] | None:
        """Return a current, evidenced next step without starting work."""
        if (state.archive is not None or state.active_step is not None or control.lock_state != RunLockState.UNLOCKED
                or control.dispatch_paused or control.stop_phase in {"stopping", "stopped", "confirmation_required"}
                or control.situation in {RunExecutionSituation.RUNNING, RunExecutionSituation.PREPARING,
                                        RunExecutionSituation.STATUS_UNKNOWN, RunExecutionSituation.UNAVAILABLE}
                or any(task.active_action or task.status in {TaskStatus.RUNNING, TaskStatus.REVIEWING, TaskStatus.REVISING} for task in state.tasks)):
            return None
        run_before = self.records.inspect_lock(state.id)
        chat_before = self.records.inspect_planning_chat_lock(state.id)
        if run_before.state != RunLockState.UNLOCKED or chat_before.state != RunLockState.UNLOCKED:
            return None
        project_key = str(self.repo.expanduser().resolve())
        recorded = [*state.notification_events, *self.records.load_notification_events(state.id)]
        prompt: dict[str, object] | None = None
        if state.stage == Stage.FAILED and state.failed_step == RunStep.AGENT_EXECUTION and control.action == RunExecutionAction.RESUME:
            for task in state.tasks:
                if task.status != TaskStatus.FAILED:
                    continue
                context = self.retry_context(state, task.id)
                instruction = context["instruction"]
                if not context["instruction_current"] or not isinstance(instruction, dict):
                    continue
                event = retry_wait_event(state, project_key, task, str(instruction["request_id"]))
                if any(item.source_key == event.source_key for item in recorded):
                    prompt = {"source_key": event.source_key, "kind": "retry", "action": "retry", "task_id": task.id,
                              "question": f"수정 지시가 저장됐습니다. ‘{task.title}’ Task를 다시 실행할까요?",
                              "remaining_count": 0, "next_task_id": "", "next_task_title": ""}
                    break
        elif state.stage == Stage.EXECUTING and control.situation == RunExecutionSituation.RESUMABLE:
            snapshot = deepcopy(state)
            candidates = [task for task in snapshot.tasks if task.status == TaskStatus.PENDING and task.readiness == TaskReadiness.READY]
            ready = self.ready_tasks(snapshot, candidates)
            blocked = any(task.status in {TaskStatus.FAILED, TaskStatus.WAITING, TaskStatus.STOPPED} for task in state.tasks)
            if (ready and not blocked and control.action == RunExecutionAction.RESUME
                    and not any(item.status != DirectionChangeStatus.APPLIED for item in state.direction_change_requests)):
                for event in reversed(recorded):
                    if event.summary_code != "remaining_tasks_resume_required" or not event.related_targets:
                        continue
                    task = next((item for item in state.tasks if item.id == event.related_targets[0]), None)
                    if task is None or task.status != TaskStatus.COMPLETED:
                        continue
                    current = retry_wait_event(state, project_key, task, event.request_id, completed=True)
                    if current.source_key != event.source_key:
                        continue
                    remaining = sum(task.status == TaskStatus.PENDING for task in state.tasks)
                    prompt = {"source_key": event.source_key, "kind": "resume", "action": "resume", "task_id": "",
                              "question": f"수정한 Task가 완료됐습니다. 남은 Task {remaining}개를 계속 진행할까요?",
                              "remaining_count": remaining, "next_task_id": ready[0].id, "next_task_title": ready[0].title}
                    break
        elif (state.stage == Stage.READY_TO_MERGE and all(task.status in {TaskStatus.COMPLETED, TaskStatus.MERGED} for task in state.tasks)
              and (integration is None or integration.can_verify and integration.status == IntegrationStatus.NEEDS_VERIFICATION)):
            event = next(item for item in notification_events_for_state(state, project_key=project_key, deployment_configured=False)
                         if item.summary_code == "integration_verification_required")
            prompt = {"source_key": event.source_key, "kind": "verification", "action": "verify", "task_id": "",
                      "question": "Task 실행이 끝났습니다. 통합 검증을 진행할까요?",
                      "remaining_count": 0, "next_task_id": "", "next_task_title": ""}
        elif (state.stage in {Stage.VERIFIED, Stage.WORK_BRANCH_PUSHED}
              and (integration is None or integration.status == IntegrationStatus.VERIFIED)):
            event = next(item for item in notification_events_for_state(state, project_key=project_key, deployment_configured=False)
                         if item.summary_code in {"main_apply_required", "work_branch_push_required"})
            prompt = {"source_key": event.source_key, "kind": "main_review", "action": "operations", "task_id": "",
                      "question": "검증이 끝났습니다. 다음 반영 단계를 확인할까요?",
                      "remaining_count": 0, "next_task_id": "", "next_task_title": ""}
        if run_before != self.records.inspect_lock(state.id) or chat_before != self.records.inspect_planning_chat_lock(state.id):
            return None
        return prompt
