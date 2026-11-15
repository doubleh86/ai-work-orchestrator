"""Coordinate chat decisions and execution receipts under request locks."""

from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from ..errors import PipelineError
from ..execution.project_chat import ProjectChatRecords, ProjectChatDecisionResult, ProjectChatAction
from ..git import GitError
from ..models import IntegrationControl, OperationRecord, RunExecutionControl, RunLockState, RunState, RunStep, Stage, TaskStatus
from ..persistence.errors import RunLockedError
from ..project_chat import MAX_DECISIONS


@dataclass(frozen=True, slots=True)
class ProjectChatDecisions:
    records: ProjectChatRecords
    status: Callable[[str], tuple[RunState, RunExecutionControl, IntegrationControl]]
    fingerprint: Callable[[RunState], str]
    generate: Callable[[str, str, OperationRecord, RunExecutionControl, IntegrationControl, dict[str, object]], ProjectChatDecisionResult]
    validate_target: Callable[[RunState, OperationRecord], None]
    scope_proposal: Callable[[RunState, str], dict[str, object] | None]
    scope_question: Callable[[dict[str, object]], str]
    record_chat: Callable[[str, str, str], RunState]

    def decide(self, run_id: str, request_id: str) -> dict[str, object]:
        with self.records.control_lock(run_id):
            record = self.records.load_operation(run_id, request_id)
            if record is None or record.payload.get("intent") != "project":
                raise PipelineError("프로젝트 채팅 요청을 찾지 못했습니다.")
            if record.status != "running" or record.phase not in {"accepted", "observed"}:
                return record.to_dict()
            if record.payload["decisions"] >= MAX_DECISIONS:
                record.update("blocked", status="failed", error="자율 진행 한도에 도달했습니다. 현재 결과와 남은 작업을 확인해 주세요.")
                self.records.save_operation(record)
                return record.to_dict()
            state, control, integration = self.status(run_id)
            expected = record.payload["expected"]
            if (state.archive or state.plan_revision != expected["planRevision"]
                    or state.planning_conversation_revision != expected["conversationRevision"]):
                raise PipelineError("계획 또는 대화가 변경돼 자동 진행을 멈췄습니다.")
            record.payload["fingerprint"] = self.fingerprint(state)
            record.payload["decisions"] += 1
            record.payload["step_id"] = str(uuid.uuid4())
            record.phase = "deciding"
            self.records.save_operation(record)
        try:
            generated = self.generate(run_id, request_id, record, control, integration, expected)
            if generated.handled:
                return generated.payload
            decision = generated.payload
            with self.records.control_lock(run_id):
                latest = self.records.load_operation(run_id, request_id)
                if latest is None or latest.status != "running" or latest.phase != "deciding":
                    raise PipelineError("AI 응답 전에 요청이 취소됐습니다.")
                current = self.records.load_run(run_id)
                if decision["action"] not in {"reply", "ask"}:
                    self.validate_target(current, latest)
                proposal = self.scope_proposal(current, str(expected.get("taskId", "")))
                answering_question = latest.payload.get("scope_consent", {}).get("intent") == "question"
                if proposal and (decision["action"] in {"ask", "approve_scope", "repair", "continue"}
                                 or decision["action"] == "reply" and not answering_question and ("approve_scope" in decision["message"]
                                     or any(path in decision["message"] for path in proposal["paths"]))):
                    latest.payload["scope_proposal"] = proposal
                    decision = {"action": "ask", "authorized": False, "task_id": proposal["task_id"], "instruction": "",
                                "message": self.scope_question(proposal)}
                latest.payload["decision"] = decision
                if decision["action"] in {"reply", "ask"}:
                    latest.update("completed" if decision["action"] == "reply" else "needs_input", status="succeeded")
                else:
                    latest.phase = "decision_ready"
                self.records.save_operation(latest)
            if decision["action"] in {"reply", "ask"}:
                self.record_chat(run_id, "", str(decision["message"]))
            return latest.to_dict()
        except Exception as exc:
            with self.records.control_lock(run_id):
                latest = self.records.load_operation(run_id, request_id)
                if latest and latest.status == "running":
                    latest.update("blocked", status="failed", error=str(exc))
                    self.records.save_operation(latest)
            self.record_chat(run_id, "", f"요청을 진행하지 못했습니다. {exc}")
            raise


@dataclass(frozen=True, slots=True)
class ProjectChatActions:
    records: ProjectChatRecords
    status: Callable[[str], tuple[RunState, RunExecutionControl, IntegrationControl]]
    fingerprint: Callable[[RunState], str]
    validate_target: Callable[[RunState, OperationRecord], None]
    allowed: Callable[[RunState, RunExecutionControl, IntegrationControl, int, dict[str, object] | None], list[str]]
    perform_profile: Callable[[str, str, str], dict[str, object]]
    execute_action: Callable[[ProjectChatAction], OperationRecord]
    record_chat: Callable[[str, str, str], RunState]

    def perform(self, run_id: str, request_id: str, step_id: str) -> dict[str, object]:
        state, control, integration = self.status(run_id)
        with self.records.control_lock(run_id):
            record = self.records.load_operation(run_id, request_id)
            if record is None or record.payload.get("intent") != "project" or record.payload.get("step_id") != step_id:
                raise PipelineError("AI 행동의 요청 대상이 일치하지 않습니다.")
            if record.status != "running" or record.phase != "decision_ready":
                return record.to_dict()
            self.validate_target(state, record)
            decision = record.payload["decision"]
            action = str(decision["action"])
            allowed = self.allowed(state, control, integration, record.payload["repairs"], record.payload.get("scope_approval"))
            if action == "set_execution_profile":
                if control.lock_state != RunLockState.UNLOCKED:
                    raise PipelineError("그룹 작업이 진행 중입니다. 종료 후 실행 AI를 변경해 주세요.")
            elif action not in allowed:
                raise PipelineError("현재 상태에서 실행할 수 없는 AI 행동입니다.")
            signature = hashlib.sha256(json.dumps([record.payload["fingerprint"], decision], sort_keys=True).encode()).hexdigest()
            if any(item["signature"] == signature for item in record.payload["history"]):
                raise PipelineError("같은 상태의 같은 행동을 반복하지 않습니다. 새로운 진단이나 사용자 입력이 필요합니다.")
            record.phase = "acting"
            record.payload["recovery_id"] = step_id
            if action in {"repair", "approve_scope"}:
                record.payload["repairs"] += 1
            self.records.save_operation(record)
        if action == "set_execution_profile":
            return self.perform_profile(run_id, request_id, step_id)
        error = ""
        try:
            record = self.execute_action(ProjectChatAction(run_id, request_id, step_id, state, control, record, decision, action))
        except (PipelineError, GitError, RunLockedError, OSError, subprocess.SubprocessError) as exc:
            error = str(exc)
        final = self.records.load_run(run_id)
        _, final_control, _ = self.status(run_id)
        result = {"action": action, "task_id": decision.get("task_id", ""), "signature": signature,
                  "stage": final.stage.value, "error": error or final.failure_message,
                  "completed": sum(task.status in {TaskStatus.COMPLETED, TaskStatus.MERGED} for task in final.tasks),
                  "total": len(final.tasks)}
        if action == "approve_scope":
            scope_operation = self.records.load_operation(run_id, step_id)
            result["error"] = error or (scope_operation.error if scope_operation else "승인 처리 결과를 확인하지 못했습니다.")
        with self.records.control_lock(run_id):
            latest = self.records.load_operation(run_id, request_id)
            if latest is None:
                raise PipelineError("실행 결과의 요청 기록을 찾지 못했습니다.")
            latest.payload["history"].append(result)
            if action == "verify" and state.stage == Stage.FAILED:
                latest.payload["repairs"] += final.verification_repair_count
            latest.payload["expected"] = record.payload["expected"]
            if latest.status == "running":
                if action == "approve_scope" and not record.payload["scope_approval"]["resume"] and not result["error"]:
                    latest.update("completed", status="succeeded")
                elif (final.plan_revision != record.payload["expected"]["planRevision"]
                        or final.planning_conversation_revision != record.payload["expected"]["conversationRevision"]):
                    latest.update("blocked", status="failed", error="작업 중 계획 또는 대화가 변경돼 후속 자동 진행을 멈췄습니다.")
                elif (action != "stop" and final_control.stop_phase in {"stopping", "stopped", "confirmation_required"}
                        and (final_control.stop_request_id != control.stop_request_id or final_control.execution_id != control.execution_id)):
                    latest.update("interrupted", status="interrupted", error="사용자의 중지 요청으로 자율 진행도 멈췄습니다.")
                elif error and self.fingerprint(final) == record.payload["fingerprint"]:
                    latest.update("blocked", status="failed", error=error)
                else:
                    latest.phase = "observed"
            self.records.save_operation(latest)
        action_label = {"continue": "작업 진행", "stop": "작업 중지", "repair": "수정·재검증", "verify": "최종 검증",
                        "clear_lock": "종료된 실행의 잠금 해제", "refine": "구현 지시 보완", "approve_scope": "승인한 경로 반영·재검증"}[action]
        if action == "approve_scope" and not record.payload["scope_approval"]["resume"]:
            action_label = "승인한 경로만 반영 · 작업 실행은 대기"
        detail = f"{action_label} 결과 · {result['completed']}/{result['total']} 완료" + (f" · {result['error']}" if result["error"] else "")
        self.record_chat(run_id, "", f"요청을 진행하지 못했습니다. {error}" if error else detail)
        return latest.to_dict()


@dataclass(frozen=True, slots=True)
class ChatControlAdvancement:
    records: ProjectChatRecords
    status: Callable[[str], tuple[RunState, RunExecutionControl, IntegrationControl]]
    retry_context: Callable[[RunState, str], dict[str, object]]
    record_chat: Callable[[str, str, str], RunState]

    def advance(self, run_id: str, request_id: str, *, suspend: bool = False) -> dict[str, object]:
        state, control, integration = self.status(run_id)
        with self.records.control_lock(run_id):
            record = self.records.load_operation(run_id, request_id)
            if record is None or record.action != "chat_control":
                raise PipelineError("중지·복구 요청을 찾지 못했습니다.")
            response: dict[str, object] = {"operation": record.to_dict(), "next_action": "none", "params": {}}
            if record.status != "running":
                return response
            data = record.payload
            expected = data["expected"]
            reason = ""
            if suspend:
                reason = "진행 확인이 중단돼 복구를 보류했습니다. 기존 실행 상태를 확인해 주세요."
            elif state.archive or state.plan_revision != expected.get("planRevision"):
                reason = "원래 작업의 계획 또는 보관 상태가 변경돼 복구를 시작하지 않았습니다."
            elif state.planning_conversation_revision != expected.get("conversationRevision", 0):
                reason = "원래 작업의 대화가 변경돼 복구를 시작하지 않았습니다."
            stop = self.records.load_operation(run_id, str(data["stop_id"]))
            if not reason and record.phase in {"repairing", "verifying"}:
                return response
            if not reason and (control.can_stop or control.stop_phase == "stopping" or record.phase == "stopping"):
                if control.execution_id != expected.get("executionId") or control.stop_scope != expected.get("scope"):
                    reason = "중지 대상 실행이 변경됐습니다. 복구는 시작하지 않았습니다."
                elif stop is None:
                    task_id = str(expected.get("taskId") or "")
                    target = next((task for task in state.tasks if task.id == task_id), None)
                    if control.stop_scope == "task" and (target is None or target.last_attempt_id != expected.get("attemptId")
                                                          or target.active_invocation_id != expected.get("invocationId")):
                        reason = "중지할 Task의 실행 시도가 변경됐습니다."
                    else:
                        record.phase = "stopping"
                        self.records.save_operation(record)
                        response.update(next_action="stop", params={"requestId": data["stop_id"], "executionId": control.execution_id,
                                        "scope": control.stop_scope, "taskId": task_id,
                                        "attemptId": expected.get("attemptId", ""), "invocationId": expected.get("invocationId", "")})
                elif stop.status == "failed" or control.stop_phase == "confirmation_required":
                    reason = stop.error or "실행 종료와 작업 보존을 확인하지 못했습니다."
                elif control.lock_state == RunLockState.UNLOCKED and state.active_step is None:
                    if data["intent"] == "stop":
                        record.update("completed", status="succeeded")
                    elif control.stop_phase != "stopped" or stop.phase not in {"stopped", "linked"}:
                        reason = "대상 실행이 중지 전에 종료됐습니다. 최신 결과를 확인해 주세요."
                    else:
                        record.phase = "stop_confirmed"
                elif (datetime.now(timezone.utc) - datetime.fromisoformat(stop.created_at)).total_seconds() > 60:
                    reason = "중지 완료 확인이 지연돼 복구를 보류했습니다. 중지 요청은 유지됩니다."
            elif not reason and data["intent"] == "stop":
                reason = "현재 중지할 실행이 없습니다."
            if not reason and record.status == "running" and record.phase in {"accepted", "stop_confirmed"}:
                candidates = [task for task in state.tasks if task.status in {TaskStatus.FAILED, TaskStatus.STOPPED}]
                if len(candidates) == 1 and (not expected.get("taskId") or candidates[0].id == expected["taskId"]):
                    target = candidates[0]
                    context = self.retry_context(state, target.id)
                    if (control.lock_state != RunLockState.UNLOCKED or not context["can_save"]
                            or not context["recovery"]["can_execute"]
                            or any(task.id != target.id and task.status not in {
                                TaskStatus.PENDING, TaskStatus.DEFERRED, TaskStatus.COMPLETED, TaskStatus.MERGED,
                            }
                                   for task in state.tasks)):
                        reason = str(context["reason"]) or ("수정 범위 확인이 필요합니다. 채팅에서 필요한 경로와 이유를 검토하고 계획에 반영해 주세요."
                                  if context["recovery"]["reason_code"] == "task_scope_review_required" else
                                  "같은 조건의 시간 초과입니다. 지연 원인을 확인한 뒤 다시 요청해 주세요."
                                  if context["recovery"]["reason_code"] == "same_timeout_context" else "다른 실행 또는 미해결 작업을 확인해 주세요.")
                    elif expected.get("attemptId") and target.last_attempt_id != expected["attemptId"]:
                        reason = "복구할 Task의 실행 시도가 변경됐습니다."
                    else:
                        response.update(next_action="repair", params={"requestId": data["recovery_id"], "taskId": target.id,
                                        "message": data["message"], "fingerprint": context["fingerprint"],
                                        "conversationRevision": state.planning_conversation_revision, "parentRequestId": request_id,
                                        "recoveryFingerprint": context["recovery"]["fingerprint"]})
                elif integration.can_verify and (state.stage == Stage.READY_TO_MERGE
                                                  or state.stage == Stage.FAILED and state.failed_step == RunStep.VERIFY):
                    response.update(next_action="verify", params={"requestId": data["recovery_id"], "parentRequestId": request_id})
                else:
                    reason = "현재 상태에서 복구할 작업을 하나로 특정하지 못했습니다."
            if reason:
                record.update("blocked", status="failed", error=reason)
            self.records.save_operation(record)
            response["operation"] = record.to_dict()
        if reason:
            self.record_chat(run_id, "", reason)
        return response

    def advance_project(self, run_id: str, request_id: str, *, suspend: bool) -> dict[str, object]:
        with self.records.control_lock(run_id):
            record = self.records.load_operation(run_id, request_id)
            if record is None:
                raise PipelineError("프로젝트 채팅 요청을 찾지 못했습니다.")
            if suspend and record.status == "running":
                record.update("confirmation_required", status="partial", error="진행 확인이 중단됐습니다. 자동으로 다시 실행하지 않습니다.")
                self.records.save_operation(record)
            action = "none"
            if record.status == "running":
                if record.phase in {"accepted", "observed"}:
                    action = "decide"
                elif record.phase == "decision_ready":
                    action = "act"
            return {"operation": record.to_dict(), "next_action": action,
                    "params": {"requestId": request_id, "stepId": record.payload.get("step_id", "")}}
