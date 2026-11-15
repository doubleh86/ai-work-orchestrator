"""Preserved failure evidence and one-use advice for task recovery."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Protocol

from ..config import DEFAULT_TASK_VERIFY_COMMAND_TIMEOUT_SECONDS, DEFAULT_TASK_VERIFY_TOTAL_TIMEOUT_SECONDS
from ..errors import PipelineError
from ..git_contracts import GitError
from ..models import ExecutionControlRecord, RunState, RunStep, Stage, TaskAction, TaskStatus, WorkTask, utc_now
from ..planning import planning_preview_task_fields
from ..scope_consent import scope_proposal_id
from ..task_scope_review import TaskScopeReview
from .recovery import recovery_timeout_limits, timeout_retry_context, verification_timed_out
from .task_prompts import render_retry_instruction


class RetryWaitRecorder(Protocol):
    def __call__(
        self, state: RunState, task: WorkTask, request_id: str, *, completed: bool = False, occurred_at: str = "",
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class RetryGuidanceRecords:
    load_run: Callable[[str], RunState]
    load_requests: Callable[[str], list[dict[str, object]]]
    save_requests: Callable[[str, list[dict[str, object]]], None]
    load_control: Callable[[str], ExecutionControlRecord | None]
    save_state: Callable[[RunState], None]


def retry_task_contract_digest(task: WorkTask) -> str:
    return hashlib.sha256(json.dumps(planning_preview_task_fields(task), sort_keys=True,
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class TaskRetryGuidance:
    records: RetryGuidanceRecords
    find_task: Callable[[RunState, str], WorkTask]
    scope_review: Callable[[WorkTask], TaskScopeReview | None]
    scope_proposal: Callable[[RunState, str], dict[str, object] | None]
    scope_digest: Callable[[WorkTask], str]
    verification_timed_out: Callable[[WorkTask], bool]
    command_timeout: Callable[[], int]
    total_timeout: Callable[[], int]
    worktree_head: Callable[[Path], str]
    dotnet_executable: Callable[[], str]
    record_wait: RetryWaitRecorder

    def instruction(self, run_id: str, task_id: str) -> str:
        request = next((item for item in reversed(self.records.load_requests(run_id))
                        if item.get("handling") == "same_task_retry" and item.get("task_ids") == [task_id]), None)
        if request is None:
            return ""
        if request.get("task_contract_digest"):
            current = self.find_task(self.records.load_run(run_id), task_id)
            if request["task_contract_digest"] != retry_task_contract_digest(current):
                return ""
        return render_retry_instruction(
            str(request["request_id"]), str(request["text"]), str(request.get("proposal_summary", "")),
        )

    def context(self, state: RunState, task_id: str) -> dict[str, object]:
        task = self.find_task(state, task_id)
        fingerprint = hashlib.sha256(json.dumps({
            "plan_revision": state.plan_revision, "stage": state.stage.value,
            "failed_step": state.failed_step.value if state.failed_step else "",
            "task": asdict(task),
        }, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
        instruction = next((item for item in reversed(self.records.load_requests(state.id))
                            if item.get("handling") == "same_task_retry" and item.get("task_ids") == [task_id]), None)
        stopped = False
        if state.stage == Stage.EXECUTING and task.status == TaskStatus.STOPPED and task.stop_request_id:
            control = self.records.load_control(state.id)
            stopped = bool(control and control.phase == "stopped" and control.scope == "task"
                           and control.stop_request_id == task.stop_request_id)
        failed = state.stage == Stage.FAILED and state.failed_step == RunStep.AGENT_EXECUTION and task.status == TaskStatus.FAILED
        can_save = (state.archive is None and (failed or stopped)
                    and state.active_step is None
                    and not any(candidate.active_action for candidate in state.tasks))
        latest = task.action_results[-1] if task.action_results else None
        current_response = (latest is not None and latest.status == "failed" and bool(task.last_attempt_id)
                            and latest.attempt_id == task.last_attempt_id
                            and (task.failed_action is None or latest.action == task.failed_action.value))
        response = latest.worker_response if latest is not None and current_response else ""
        review = self.scope_review(task)
        proposal = self.scope_proposal(state, task_id) if review and can_save else None
        return {
            "task_id": task_id, "title": task.title,
            "error": review.error(self.scope_digest(task)) if review else task.error, "response": response,
            "plan_revision": state.plan_revision, "attempt_id": task.last_attempt_id,
            "conversation_revision": state.planning_conversation_revision, "expected_paths": task.expected_paths,
            "acceptance_criteria": task.acceptance_criteria, "fingerprint": fingerprint, "can_save": can_save,
            "reason": "" if can_save else "현재 실패는 개별 Task 수정 지시 저장 대상이 아닙니다. 그룹의 현재 복구 단계를 확인하세요.",
            "instruction": instruction,
            "instruction_current": bool(instruction and instruction.get("retry_fingerprint") == fingerprint),
            "recovery": self.capability(state, task, can_execute=can_save),
            "scope_review": {"reason": review.reason, "paths": proposal["paths"] if proposal else list(review.paths),
                             "review_id": scope_proposal_id(proposal) if proposal else ""} if review else None,
        }

    def capability(self, state: RunState, task: WorkTask, *, can_execute: bool) -> dict[str, object]:
        current = [state.task_verify_command_timeout_seconds or self.command_timeout(),
                   state.task_verify_total_timeout_seconds or self.total_timeout()]
        proposed = list(recovery_timeout_limits(
            (current[0], current[1]),
            (self.command_timeout(), self.total_timeout()),
            (DEFAULT_TASK_VERIFY_COMMAND_TIMEOUT_SECONDS, DEFAULT_TASK_VERIFY_TOTAL_TIMEOUT_SECONDS),
        ))
        result: dict[str, object] = {"kind": "repair", "can_execute": can_execute, "reason_code": "" if can_execute else "unavailable",
                                    "current_limits": current, "proposed_limits": proposed, "will_change": current != proposed,
                                    "history_known": False, "fingerprint": "", "changed_factors": []}
        if self.scope_review(task) is not None:
            result.update(kind="unavailable", can_execute=False, reason_code="task_scope_review_required")
            return result
        if not self.verification_timed_out(task):
            return result
        try:
            head = self.worktree_head(Path(task.worktree))
        except (GitError, OSError):
            result.update(kind="unavailable", can_execute=False, reason_code="workspace_unavailable")
            return result
        commands = task.verify_commands
        failures = [item for item in task.action_results if item.action == TaskAction.VERIFY.value and item.status == "failed"
                    and item.verification_failure_kind == "timeout"]
        metadata = failures[-1].verification_context_inputs if failures else {}
        result.update(timeout_retry_context(
            head=head, commands=tuple(tuple(command) for command in commands), current_limits=(current[0], current[1]),
            proposed_limits=(proposed[0], proposed[1]), tool=self.dotnet_executable(),
            failed_digests=tuple(item.verification_context_digest for item in failures), latest_inputs=metadata, can_execute=can_execute,
        ))
        return result

    def diagnose(self, run_id: str, task_id: str, fingerprint: str, diagnosis: str) -> None:
        state = self.records.load_run(run_id)
        context = self.context(state, task_id)
        if not context["can_save"] or context["fingerprint"] != fingerprint:
            raise PipelineError("점검 중 작업이 변경됐습니다. 최신 실패 상태를 다시 확인해 주세요.")
        message = f"{task_id} · 시도 {context['attempt_id']}\n{diagnosis}"
        if not any(event.kind == "task_diagnosis" and event.message == message for event in state.events):
            state.add_event("task_diagnosis", message)
            self.records.save_state(state)

    def save_instruction(self, run_id: str, task_id: str, normalized_id: str, instruction: str, fingerprint: str) -> dict[str, object]:
        state = self.records.load_run(run_id)
        requests = self.records.load_requests(run_id)
        previous = next((item for item in requests if item.get("request_id") == normalized_id), None)
        if previous is not None:
            if (previous.get("handling"), previous.get("task_ids"), previous.get("text"), previous.get("retry_fingerprint")) != (
                "same_task_retry", [task_id], instruction, fingerprint
            ):
                raise PipelineError("같은 요청 ID를 다른 수정 지시에 사용할 수 없습니다.")
            context = self.context(state, task_id)
            if context["instruction_current"]:
                self.record_wait(state, self.find_task(state, task_id), normalized_id, occurred_at=str(previous["created_at"]))
            return context
        context = self.context(state, task_id)
        if not context["can_save"]:
            raise PipelineError(str(context["reason"]))
        if context["fingerprint"] != fingerprint:
            raise PipelineError("실패 Task 또는 계획이 변경됐습니다. 수정 대상을 다시 확인해 주세요.")
        requests.append({
            "request_id": normalized_id, "text": instruction, "task_ids": [task_id], "paths": [],
            "target_run_id": run_id, "created_at": utc_now(), "handling": "same_task_retry",
            "retry_fingerprint": fingerprint, "proposal_id": "", "proposal_summary": "",
            "task_contract_digest": retry_task_contract_digest(self.find_task(state, task_id)),
        })
        self.records.save_requests(run_id, requests)
        self.record_wait(state, self.find_task(state, task_id), normalized_id, occurred_at=str(requests[-1]["created_at"]))
        return self.context(state, task_id)


def task_verification_timed_out(task: WorkTask) -> bool:
    if task.failed_action != TaskAction.VERIFY:
        return False
    if verification_timed_out(task.error):
        return True
    latest = next((item for item in reversed(task.action_results) if item.action == TaskAction.VERIFY.value), None)
    return verification_timed_out(
        "", latest_status=latest.status if latest else "", latest_failure_kind=latest.verification_failure_kind if latest else "",
        latest_error=latest.error if latest else "",
    )
