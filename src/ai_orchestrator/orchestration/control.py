"""RunControlCommands with explicit feature and persistence dependencies."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, ContextManager, Iterator
from ..codex_sdk import CodexSdkManager
from ..config import AgentConfig, ExecutionConfig
from ..errors import ApprovalRequired as ApprovalRequired, PipelineError
from ..execution import (
    ExecutionControlService,
    ProjectChatAction,
    ProjectChatDecisionResult,
    ProjectChatRecords,
    TaskRetryGuidance,
    VerificationRepairRecords,
    VerificationRepairWorkflow,
    make_stop_operation,
    retry_task_contract_digest,
    scope_contract_digest,
    task_execution_profile_snapshot,
)
from ..execution.chat_profiles import ChatExecutionProfiles, ChatProfileDecision, ChatProfileRecords
from ..execution.chat_recovery import ChatRecoveryChildren, ChatRecoveryRecords, ChatTaskRecovery
from ..execution.control_messages import ExecutionMessages
from ..execution.flow import ExecutionFlow
from ..execution.profile_workflows import ExecutionProfiles
from ..execution.provider_choices import ConnectedProviderQueries, ProviderAvailability
from ..execution.retry_guidance import task_verification_timed_out
from ..execution.scope_consent import ScopeConsentRecorder
from ..execution.task_workflows import TaskWorkflows
from ..git import GitError
from ..integration import conflict_request_id, raise_existing_recovery_operation
from ..integration.recovery_apply import RecoveryApplication, RecoveryApplyRecords
from ..integration.recovery_flow import RecoveryFlow
from ..integration.verification_flow import VerificationFlow
from ..integration.workspace_access import WorkspaceAccess
from ..models import (
    IntegrationControl,
    OperationRecord,
    PlanningMessageRole,
    RunExecutionControl,
    RunLockState,
    RunLockStatus,
    RunState,
    RunStep,
    Stage,
    TaskAction,
    TaskStatus,
)
from ..orchestration.chat_workflows import ChatControlAdvancement, ProjectChatActions, ProjectChatDecisions
from ..orchestration.execution import ExecutionCommands
from ..orchestration.planning import PlanningCommands
from ..orchestration.queries import RunQueries
from ..orchestration.scope_approval import ScopeApprovalActions
from ..persistence.errors import RunLockedError
from ..persistence.execution_records import RunControlCommandsRecords
from ..persistence.run_lookup import RunLookup, find_task
from ..planning.ai import PlanningAI
from ..planning.apply_requests import normalize_planning_apply_request_id
from ..planning.control_decisions import ControlPlanningInvocation, ProjectDecisionContext
from ..planning.conversation import planning_conversation_id, planning_message_requests_apply, task_plan_draft
from ..planning.messages import PlanningMessages
from ..planning.policy_scope import PlanningPolicyScope
from ..planning.profiles import PlanningProfiles
from ..planning.request_records import PlanningRequestRecords
from ..project_chat import MAX_REPAIRS, TaskProfileCommand, task_profile_command
from ..queries.scope_proposals import ScopeProposalQueries


@dataclass
class RunControlCommands:
    records: RunControlCommandsRecords
    control: ExecutionControlService
    messages: ExecutionMessages
    recovery: RecoveryFlow
    planning_messages: PlanningMessages
    planning_profiles: PlanningProfiles
    workspace: WorkspaceAccess
    sdk: Callable[[], CodexSdkManager | None]
    proposals: ScopeProposalQueries
    tasks: TaskWorkflows
    scope: ScopeApprovalActions
    execution: ExecutionCommands
    runs: RunQueries
    planning_ai: PlanningAI
    planning_policy: PlanningPolicyScope
    flow: ExecutionFlow
    verification: VerificationFlow
    planning: PlanningCommands
    availability: ProviderAvailability
    connections: ConnectedProviderQueries
    lookup: RunLookup
    profiles: ExecutionProfiles
    agents_settings: Callable[[], tuple[AgentConfig, ...]]
    retry_guidance: TaskRetryGuidance
    ensure_verification: Callable[[RunState], None]
    execution_settings: Callable[[], ExecutionConfig]

    def request_stop(
        self,
        run_id: str,
        *,
        request_id: str,
        execution_id: str,
        scope: str,
        task_id: str = "",
        attempt_id: str = "",
        invocation_id: str = "",
        chat_message: str = "",
    ) -> OperationRecord:
        chat_message = chat_message.strip()
        if len(chat_message) > 1800:
            raise PipelineError("중지 요청을 1800자 이내로 입력해 주세요.")
        try:
            normalized_request_id = str(uuid.UUID(request_id.strip()))
            normalized_execution_id = str(uuid.UUID(execution_id.strip()))
        except (AttributeError, ValueError) as exc:
            raise PipelineError("중지 요청과 실행 ID는 UUID 형식이어야 합니다.") from exc
        if scope not in {"task", "verification"}:
            raise PipelineError("중지 범위는 task 또는 verification이어야 합니다.")
        operation = make_stop_operation(
            run_id, request_id=normalized_request_id, execution_id=normalized_execution_id, scope=scope,
            task_id=task_id, attempt_id=attempt_id, invocation_id=invocation_id, chat_message=chat_message,
        )
        operation, created = self.control.request_stop(operation)
        if not created:
            return operation
        if chat_message:
            summary = "중지 요청을 접수했습니다. 실행 종료와 작업 보존을 확인하고 있습니다."
            if operation.phase == "already_finished":
                summary = "대상 실행이 이미 종료되어 중지할 작업이 없습니다."
            elif operation.status == "failed":
                summary = f"중지 요청을 처리하지 못했습니다. {operation.error}"
            self.messages.record(run_id, chat_message, summary)
        return operation


    def recovery_plan(self, run_id: str, *, request_id: str = "") -> dict[str, object]:
        with self.records.lock(run_id, "recovery-preview"):
            state = self.records.load(run_id)
            operation, created = self.recovery.claim_recovery_operation(
                state,
                "recovery_preview",
                request_id,
                self.recovery.recovery_preview_input(state),
                "checking_failure",
            )
            if not created:
                result = self.recovery.replayed_recovery_result(operation)
                if result is not None:
                    return result
            try:
                operation.update("checking_failure")
                self.records.save_operation(operation)

                def update_phase(phase: str) -> None:
                    operation.update(phase)
                    self.records.save_operation(operation)

                plan = self.recovery.recovery_plan(state, progress_callback=update_phase)
                operation.result_ref = self.records.save_operation_result(state.id, operation.request_id, plan)
                operation.result_revision = state.plan_revision
                operation.update("preview_ready", status="succeeded")
                self.records.save_operation(operation)
                return plan
            except Exception as exc:
                self.recovery.fail_recovery_operation(operation, exc)
                raise


    def apply_recovery(
        self,
        run_id: str,
        fingerprint: str,
        source_ids: list[str],
        *,
        approved: bool,
        request_id: str = "",
        resume_request_id: str = "",
    ) -> RunState:
        if not approved:
            raise PipelineError("복구안 적용에는 명시적인 승인이 필요합니다.")
        with self.records.lock(run_id, "recovery-apply"), self.records.planning_chat_lock(run_id):
            return RecoveryApplication(
                records=RecoveryApplyRecords(self.records.load, self.records.save, self.records.save_planning_chat,
                                             self.records.save_operation, self.records.save_operation_result),
                claim_operation=self.recovery.claim_recovery_operation, raise_existing=raise_existing_recovery_operation,
                resume_replanning=self.recovery.validate_recovery_replan_resume, recovery_plan=self.recovery.recovery_plan,
                configure_profile=self.planning_profiles.configure, shared_boundary=self.workspace.shared_workspace_boundary,
                recover_commits=self.recovery.integrate_recovery_commits, append_user=self.planning_messages.append_user,
                replan=self.recovery.replan_recovery_tasks, fail_operation=self.recovery.fail_recovery_operation,
            ).apply(run_id, fingerprint, source_ids, request_id=request_id, resume_request_id=resume_request_id)


    def recovery_operation(self, run_id: str, request_id: str) -> dict[str, object]:
        return self.recovery.recovery_workflow().operation(run_id, request_id)


    def latest_recovery_operation(self, run_id: str, kind: str) -> dict[str, object] | None:
        return self.recovery.recovery_workflow().latest(run_id, kind)


    def planning_request_records(self) -> PlanningRequestRecords:
        return PlanningRequestRecords(
            load_run=self.records.load, claim_operation=self.records.claim_operation, load_operation=self.records.load_operation,
            save_operation=self.records.save_operation, requests_apply=planning_message_requests_apply,
        )


    def begin_planning_request(self, run_id: str, *, request_id: str, kind: str, message: str = "") -> dict[str, object]:
        request_id = normalize_planning_apply_request_id(request_id)
        if kind not in {"plan", "replan", "chat"}:
            raise PipelineError("Unknown Planning request kind")
        with self.records.request_control_lock(run_id):
            return self.planning_request_records().begin_locked(run_id, request_id, kind, message)


    def finish_planning_request(self, run_id: str, *, request_id: str, phase: str, error: str = "") -> dict[str, object]:
        if phase not in {"succeeded", "failed", "interrupted"}:
            raise PipelineError("Unknown Planning completion phase")
        request_id = normalize_planning_apply_request_id(request_id)
        with self.records.request_control_lock(run_id):
            records = self.planning_request_records()
            record = records.owner_locked(run_id, request_id)
            if record.status != "running":
                return record.to_dict()
        if phase == "interrupted":
            state = self.records.load(run_id)
            if record.reason in {"plan", "replan"} and state.active_step == RunStep.PLANNING:
                self.interrupt_planning(run_id, approved=True)
            else:
                if self.records.inspect_planning_chat_lock(run_id).state == RunLockState.ACTIVE:
                    raise PipelineError("대화 프로세스 종료를 확인하지 못했습니다.")
                if state.active_step == RunStep.PLANNING:
                    lock = self.records.inspect_lock(run_id)
                    if lock.state == RunLockState.STALE:
                        self.records.clear_stale_lock(run_id)
                    elif lock.state != RunLockState.UNLOCKED:
                        raise PipelineError("기획 프로세스 종료를 확인하지 못했습니다.")
                    with self.records.lock(run_id, "interrupt-chat"):
                        state = self.records.load(run_id)
                        state.complete_step(RunStep.PLANNING)
                        self.records.save(state)
                with self.records.planning_chat_lock(run_id):
                    state = self.records.load(run_id)
                    self.planning_messages.append_assistant(state, "답변을 중단했습니다. 기존 작업 결과는 유지됩니다.", counts_as_discussion=False)
                    self.records.save_planning_chat(state)
        with self.records.request_control_lock(run_id):
            return records.finish_locked(run_id, request_id, phase, error)


    def interrupt_planning(self, run_id: str, *, approved: bool) -> RunState:
        if not approved:
            raise ApprovalRequired("planning interruption requires approval")
        lock_status = self.records.inspect_lock(run_id)
        if lock_status.state == RunLockState.STALE:
            self.records.clear_stale_lock(run_id)
        with self.records.lock(run_id, "interrupt-planning"):
            state = self.records.load(run_id)
            if state.stage == Stage.FAILED and state.failed_step == RunStep.PLANNING:
                return state
            if state.active_step != RunStep.PLANNING:
                raise PipelineError(f"run {run_id} has no active Planning operation")
            state.fail_step(RunStep.PLANNING, "사용자가 Planning 작업을 중단했습니다.")
            self.records.save(state)
            if self.sdk() is not None:
                self.sdk().close_conversation(planning_conversation_id(state))
            return state


    def run_lock_status(self, run_id: str) -> RunLockStatus:
        self.lookup.require_known(run_id)
        return self.records.inspect_lock(run_id)


    def clear_run_lock(self, run_id: str, *, approved: bool) -> RunLockStatus:
        if not approved:
            raise ApprovalRequired("lock clear requires --approve")
        self.lookup.require_known(run_id)
        merge_operation = self.records.latest_operation(run_id, "merge")
        if merge_operation is not None and merge_operation.phase == "applying_main" and merge_operation.status == "running":
            raise PipelineError("중단된 Main 반영은 단독 실행 잠금 해제로 처리할 수 없습니다. 원본 상태를 먼저 확인하세요.")
        return self.records.clear_stale_lock(run_id)


    def project_chat_actions(self, state: RunState, control: RunExecutionControl, integration: IntegrationControl,
                              repairs: int, scope_approval: dict[str, object] | None = None) -> list[str]:
        actions = ["reply", "ask"]
        if state.archive:
            return actions
        if control.can_stop:
            return actions + ["stop"]
        if control.lock_state == RunLockState.STALE:
            return actions + ["clear_lock"]
        if control.lock_state != RunLockState.UNLOCKED or state.active_step == RunStep.PLANNING:
            return actions
        editable = state.stage in {Stage.PLANNED, Stage.EXECUTING} or (
            state.stage == Stage.FAILED and state.failed_step == RunStep.AGENT_EXECUTION)
        if editable and any(task.status in {TaskStatus.PENDING, TaskStatus.FAILED} and self.tasks.task_scope_review(task) is None
                            for task in state.tasks):
            actions.append("refine")
        failures = [task for task in state.tasks if task.status in {TaskStatus.FAILED, TaskStatus.STOPPED}]
        if editable and not failures:
            actions.append("continue")
        if editable and len(failures) == 1 and repairs < MAX_REPAIRS and self.tasks.task_scope_review(failures[0]) is None:
            actions.append("repair")
        if (scope_approval and repairs < MAX_REPAIRS
                and self.proposals.proposal(state, str(scope_approval["proposal"]["task_id"])) == scope_approval["proposal"]):
            actions.append("approve_scope")
        if integration.can_verify and state.stage in {Stage.READY_TO_MERGE, Stage.FAILED}:
            if state.stage != Stage.FAILED or state.failed_step == RunStep.VERIFY and repairs < MAX_REPAIRS:
                actions.append("verify")
        return actions


    @staticmethod
    def chat_scope_question(proposal: dict[str, object]) -> str:
        return ("이 작업을 수정하려면 다음 파일을 허용 경로에 추가해야 합니다.\n\n"
                + "\n".join(f"- {path}" for path in proposal["paths"])
                + "\n\n기존 구현·완료 작업·검증 명령은 유지합니다. 이 경로를 추가하고 같은 작업을 수정·재검증할까요? "
                  "원하시는 대로 말씀해 주세요. 경로만 추가하고 실행을 미룰 수도 있습니다.")


    def chat_scope_was_offered(self, state: RunState, proposal: dict[str, object]) -> bool:
        return self.scope.scope_approval_queries().was_offered(state, proposal)


    def decide_scope_consent(self, run_id: str, record: OperationRecord) -> dict[str, object] | None:
        candidate = record.payload["scope_consent_candidate"]
        proposal = candidate["proposal"]
        message = str(record.payload["message"])
        if not candidate["offered"] and not all(path in message.replace("\\", "/") for path in proposal["paths"]):
            raise PipelineError("사용자에게 제시된 경로 승인 대상을 확인하지 못했습니다.")
        with self.records.planning_chat_lock(run_id):
            state = self.records.load(run_id)
            self.scope.validate_chat_control_target(state, record)
            if self.proposals.proposal(state, str(proposal["task_id"])) != proposal:
                raise PipelineError("승인할 작업 범위가 변경됐습니다. 최신 제안을 확인해 주세요.")
            consent = self.control_planning_invocation().scope_consent(
                state, run_id, record, candidate, proposal, message,
            )
        recorder = ScopeConsentRecorder(
            load_operation=self.records.load_operation, load_run=self.records.load, save_operation=self.records.save_operation,
            validate_target=self.scope.validate_chat_control_target, scope_proposal=self.proposals.proposal,
            scope_question=self.chat_scope_question,
        )
        with self.records.request_control_lock(run_id):
            latest, response = recorder.record_locked(run_id, record, proposal, consent)
        if consent.intent in {"approve", "approve_only"}:
            return self.prepare_chat_scope_decision(run_id, record.request_id)
        if consent.intent in {"decline", "unclear"}:
            self.messages.record(run_id, "", response)
            return latest.to_dict()
        return None


    def prepare_chat_scope_decision(self, run_id: str, request_id: str) -> dict[str, object]:
        with self.records.request_control_lock(run_id):
            record = self.records.load_operation(run_id, request_id)
            if record is None or record.status != "running" or record.phase != "deciding":
                raise PipelineError("경로 승인 요청이 취소되었거나 이미 처리됐습니다.")
            approval = record.payload["scope_approval"]
            state = self.records.load(run_id)
            self.scope.validate_chat_control_target(state, record)
            proposal = self.proposals.proposal(state, str(approval["proposal"]["task_id"]))
            if proposal != approval["proposal"]:
                raise PipelineError("승인할 작업 범위가 변경됐습니다. 최신 제안을 확인해 주세요.")
            record.payload["decision"] = {"action": "approve_scope", "authorized": True, "task_id": proposal["task_id"],
                                          "instruction": "", "message": "승인한 경로를 계획에 반영합니다."}
            record.phase = "decision_ready"
            self.records.save_operation(record)
            return record.to_dict()


    def advance_project_chat(self, run_id: str, request_id: str, *, suspend: bool) -> dict[str, object]:
        return self.chat_control_advancement().advance_project(run_id, request_id, suspend=suspend)


    def prepare_chat_execution_profile(
        self, run_id: str, request_id: str, command: TaskProfileCommand,
    ) -> dict[str, object]:
        with self.records.request_control_lock(run_id):
            return ChatProfileDecision(
                load_run=self.records.load, load_operation=self.records.load_operation, save_operation=self.records.save_operation,
                load_control=self.records.load_execution_control, validate_target=self.scope.validate_chat_control_target,
                find_task=find_task, profile_view=self.execution.execution_profile_view, profile_snapshot=task_execution_profile_snapshot,
            ).prepare_locked(run_id, request_id, command)


    def project_chat_records(self) -> ProjectChatRecords:
        return ProjectChatRecords(
            load_run=self.records.load, load_operation=self.records.load_operation,
            save_operation=self.records.save_operation, control_lock=self.records.request_control_lock,
        )


    def project_chat_decisions(self) -> ProjectChatDecisions:
        return ProjectChatDecisions(
            records=self.project_chat_records(), status=self.runs.status_with_controls,
            fingerprint=self.proposals.fingerprint, generate=self.generate_project_chat_decision,
            validate_target=self.scope.validate_chat_control_target, scope_proposal=self.proposals.proposal,
            scope_question=self.chat_scope_question, record_chat=self.messages.record,
        )


    def control_planning_invocation(self) -> ControlPlanningInvocation:
        return ControlPlanningInvocation(
            run_directory=self.records.run_dir, save_chat=self.records.save_planning_chat,
            configure_profile=self.planning_profiles.configure, effort_scope=self.planning_policy.scope,
            invoke=self.planning_ai.invoke,
        )


    def generate_project_chat_decision(
        self, run_id: str, request_id: str, record: OperationRecord, control: RunExecutionControl,
        integration: IntegrationControl, expected: dict[str, object],
    ) -> ProjectChatDecisionResult:
        if not record.payload["history"] and (command := task_profile_command(str(record.payload["message"]))):
            return ProjectChatDecisionResult(self.prepare_chat_execution_profile(run_id, request_id, command), handled=True)
        if record.payload.get("scope_approval") and not record.payload.get("scope_approval_consumed"):
            return ProjectChatDecisionResult(self.prepare_chat_scope_decision(run_id, request_id), handled=True)
        if record.payload.get("scope_consent_candidate") and not record.payload.get("scope_approval_consumed"):
            consent_result = self.decide_scope_consent(run_id, record)
            if consent_result is not None:
                return ProjectChatDecisionResult(consent_result, handled=True)
        with self.records.planning_chat_lock(run_id):
            state = self.records.load(run_id)
            decision = self.control_planning_invocation().project(
                state, run_id, request_id, record, control, integration, expected,
                context_builder=ProjectDecisionContext(
                    actions=self.project_chat_actions, scope_proposal=self.proposals.proposal, load_operation=self.records.load_operation,
                    task_draft=task_plan_draft, scope_digest=scope_contract_digest, scope_review=self.tasks.task_scope_review,
                ),
            )
        return ProjectChatDecisionResult(decision)


    def decide_project_chat(self, run_id: str, request_id: str) -> dict[str, object]:
        return self.project_chat_decisions().decide(run_id, request_id)


    def perform_project_chat(self, run_id: str, request_id: str, step_id: str) -> dict[str, object]:
        try:
            return self.perform_project_action(run_id, request_id, step_id)
        except (PipelineError, GitError, RunLockedError, OSError) as exc:
            with self.records.request_control_lock(run_id):
                record = self.records.load_operation(run_id, request_id)
                if record and record.payload.get("intent") == "project" and record.status == "running":
                    record.update("blocked", status="failed", error=str(exc))
                    self.records.save_operation(record)
            self.messages.record(run_id, "", f"요청을 진행하지 못했습니다. {exc}")
            raise


    def project_chat_action_workflow(self) -> ProjectChatActions:
        return ProjectChatActions(
            records=self.project_chat_records(), status=self.runs.status_with_controls,
            fingerprint=self.proposals.fingerprint, validate_target=self.scope.validate_chat_control_target,
            allowed=self.project_chat_actions, perform_profile=self.perform_chat_execution_profile,
            execute_action=self.execute_project_chat_action, record_chat=self.messages.record,
        )


    def execute_project_chat_action(self, command: ProjectChatAction) -> OperationRecord:
        run_id, request_id, step_id = command.run_id, command.request_id, command.step_id
        state, control, record = command.state, command.control, command.record
        decision, action = command.decision, command.kind
        if action == "approve_scope":
            self.scope.apply_chat_scope_approval(run_id, request_id, step_id)
            record = self.records.load_operation(run_id, request_id) or record
        elif action == "clear_lock":
            self.clear_run_lock(run_id, approved=True)
        elif action == "stop":
            self.request_stop(run_id, request_id=step_id, execution_id=control.execution_id, scope=control.stop_scope,
                task_id=control.active_task_id, attempt_id=control.active_attempt_id, invocation_id=control.active_invocation_id)
            deadline = time.monotonic() + 60
            while True:
                _, current, _ = self.runs.status_with_controls(run_id)
                if current.execution_id != control.execution_id:
                    raise PipelineError("중지 대상을 확인하는 동안 다른 실행이 시작됐습니다.")
                if current.lock_state == RunLockState.UNLOCKED and current.stop_phase == "stopped":
                    break
                if current.stop_phase == "confirmation_required" or time.monotonic() >= deadline:
                    raise PipelineError("실행 종료를 확인하지 못해 후속 작업을 시작하지 않았습니다.")
                time.sleep(0.25)
        elif action == "repair":
            task_id = str(decision.get("task_id", ""))
            context = self.execution.task_retry_context(run_id, task_id)
            self.repair_task_from_chat(run_id, task_id, request_id=step_id, message=str(decision["instruction"]),
                fingerprint=context["fingerprint"], conversation_revision=state.planning_conversation_revision,
                parent_request_id=request_id, recovery_fingerprint=context["recovery"]["fingerprint"])
        elif action == "verify" and state.stage == Stage.FAILED:
            self.verify_and_repair(run_id, request_id=step_id, parent_request_id=request_id,
                                   max_repairs=MAX_REPAIRS - record.payload["repairs"])
        else:
            if (action == "continue" and state.stage == Stage.PLANNED
                    and (not state.plan_revision or state.plan_approved_revision != state.plan_revision)):
                self.planning.confirm_plan(run_id, expected_revision=state.plan_revision)
                # confirm_plan may initialize the revision of a legacy plan; all task contracts remain unchanged.
                confirmed = self.records.load(run_id)
                if state.plan_revision == 0:
                    record.payload["fingerprint"] = self.proposals.fingerprint(confirmed)
                    record.payload["expected"]["planRevision"] = confirmed.plan_revision
            lock_operation = {"continue": "resume", "verify": "verify", "refine": "project-chat-refine"}.get(action, "project-chat")
            with self.records.lock(run_id, lock_operation):
                current = self.records.load(run_id)
                self.scope.validate_chat_control_target(current, record)
                if action == "refine":
                    task = find_task(current, str(decision.get("task_id", "")))
                    if task.status not in {TaskStatus.PENDING, TaskStatus.FAILED} or task.active_action:
                        raise PipelineError("아직 시작하지 않았거나 실패한 작업의 구현 지시만 보완할 수 있습니다.")
                    instruction = str(decision["instruction"])
                    if instruction not in task.implementation_notes:
                        task.implementation_notes.append(instruction)
                        self.records.save(current)
                elif action == "continue":
                    with self.control.owned_session(run_id, "task"):
                        self.flow.resume(run_id, manual=False)
                elif action == "verify":
                    with self.control.owned_session(run_id, "verification"):
                        self.verification.verify_locked(run_id)
                else:
                    raise PipelineError("허용되지 않은 AI 행동입니다.")
        return record


    def perform_project_action(self, run_id: str, request_id: str, step_id: str) -> dict[str, object]:
        return self.project_chat_action_workflow().perform(run_id, request_id, step_id)


    def perform_chat_execution_profile(self, run_id: str, request_id: str, step_id: str) -> dict[str, object]:
        profiles = ChatExecutionProfiles(
            records=ChatProfileRecords(
                self.records.load, self.records.load_operation, self.records.save_operation, self.records.request_control_lock,
            ),
            read_agents=lambda: self.agents_settings(),
            is_selectable=self.availability.is_selectable,
            connected_providers=self.connections.ids,
            find_task=find_task,
            validate_target=self.scope.validate_chat_control_target,
            save_profile=self.profiles.save_task_execution_profile_locked,
            fingerprint=self.proposals.fingerprint,
            record_chat=self.messages.record,
            retry_context=self.execution.task_retry_context,
            repair=self.repair_task_from_chat,
        )
        with self.records.lock(run_id, "update-task-execution-profile"), self.records.planning_chat_lock(run_id):
            state = self.lookup.at(run_id, {Stage.EXECUTING, Stage.FAILED})
            saved = profiles.save_locked(state, run_id, request_id, step_id)
        return profiles.finish(run_id, request_id, step_id, saved)


    def request_chat_control(self, run_id: str, *, request_id: str, intent: str, message: str,
                             expected: dict[str, object], session_id: str = "", profile: dict[str, str] | None = None) -> dict[str, object]:
        request_id = normalize_planning_apply_request_id(request_id)
        message_limit = 65536 if intent == "project" else 1800
        if intent not in {"stop", "repair", "stop_repair", "project"} or not message.strip() or len(message) > message_limit:
            raise PipelineError("채팅 요청 내용이나 길이가 올바르지 않습니다.")
        digest = hashlib.sha256(json.dumps([intent, message, expected, profile], sort_keys=True).encode()).hexdigest()
        with self.records.request_control_lock(run_id):
            old = self.records.load_operation(run_id, request_id)
            if old:
                if old.action != "chat_control" or old.digest != digest:
                    raise PipelineError("같은 요청 ID를 다른 명령에 사용할 수 없습니다.")
                return old.to_dict()
            previous = self.records.latest_operation(run_id, "chat_control")
            if previous and previous.status == "running":
                if not session_id or previous.payload.get("session_id") == session_id:
                    raise PipelineError("이 그룹의 중지·복구 요청이 이미 진행 중입니다.")
                previous.update("blocked", status="partial", error="앱 재시작 후 새 명시적 요청으로 이전 복구 예약을 보류했습니다.")
                self.records.save_operation(previous)
            state = self.records.load(run_id)
            if state.archive or state.plan_revision != expected.get("planRevision"):
                raise PipelineError("작업 그룹 또는 계획이 변경됐습니다.")
            if state.planning_conversation_revision != expected.get("conversationRevision", 0):
                raise PipelineError("작업 대화가 변경됐습니다.")
            record = OperationRecord(request_id=request_id, run_id=run_id, action="chat_control", digest=digest, phase="accepted",
                                     payload={"intent": intent, "message": message, "expected": expected,
                                              "stop_id": str(uuid.uuid4()), "recovery_id": str(uuid.uuid4()), "session_id": session_id,
                                              "profile": profile or {}, "decisions": 0, "repairs": 0, "history": []})
            if intent == "project":
                proposal = self.proposals.proposal(state, str(expected.get("taskId", "")))
                if proposal is not None:
                    offered = self.chat_scope_was_offered(state, proposal)
                    if offered or all(path in message.replace("\\", "/") for path in proposal["paths"]):
                        last = state.planning_messages[-1] if state.planning_messages else None
                        previous_response = last.text[-2000:] if last and last.role == PlanningMessageRole.ASSISTANT else ""
                        record.payload["scope_consent_candidate"] = {"proposal": proposal, "offered": offered,
                                                                     "previous_response": previous_response}
            self.records.claim_operation(record)
        self.messages.record(run_id, message, "현재 프로젝트와 작업 상태를 확인하고 있습니다." if intent == "project"
                                    else "중지·복구 요청을 접수했습니다. 이 대화의 원래 작업에서 진행합니다.")
        return record.to_dict()


    def chat_control_advancement(self) -> ChatControlAdvancement:
        return ChatControlAdvancement(
            records=ProjectChatRecords(
                self.records.load, self.records.load_operation, self.records.save_operation, self.records.request_control_lock,
            ),
            status=self.runs.status_with_controls,
            retry_context=self.retry_guidance.context,
            record_chat=self.messages.record,
        )


    def advance_chat_control(self, run_id: str, request_id: str, *, suspend: bool = False) -> dict[str, object]:
        current = self.records.load_operation(run_id, request_id)
        if current and current.payload.get("intent") == "project":
            return self.advance_project_chat(run_id, request_id, suspend=suspend)
        return self.chat_control_advancement().advance(run_id, request_id, suspend=suspend)


    def cancel_chat_control(self, run_id: str, request_id: str) -> dict[str, object]:
        cancelled = False
        defer_message = False
        with self.records.request_control_lock(run_id):
            record = self.records.load_operation(run_id, request_id)
            if record is None or record.action != "chat_control":
                raise PipelineError("복구 요청을 찾지 못했습니다.")
            if record.status == "running" and record.phase not in {"repairing", "verifying"}:
                defer_message = record.payload.get("intent") == "project" and record.phase in {"deciding", "acting"}
                record.update("cancelled", status="interrupted")
                self.records.save_operation(record)
                cancelled = True
        if cancelled and not defer_message:
            self.messages.record(run_id, "", "복구 예약을 취소했습니다. 이미 접수한 실행 중지 요청은 유지됩니다.")
        return record.to_dict()


    @contextmanager
    def chat_control_child(self, run_id: str, parent_id: str, child_id: str, phase: str) -> Iterator[None]:
        if not parent_id:
            yield
            return
        parent = self.records.load_operation(run_id, parent_id)
        if parent and parent.payload.get("intent") == "project":
            if parent.status != "running" or parent.phase != "acting" or parent.payload.get("recovery_id") != child_id:
                raise PipelineError("자율 작업 요청이 취소되었거나 이미 처리됐습니다.")
            self.scope.validate_chat_control_target(self.records.load(run_id), parent)
            yield
            return
        with ChatRecoveryChildren(
            load_run=self.records.load, load_operation=self.records.load_operation, save_operation=self.records.save_operation,
            control_lock=self.records.request_control_lock, validate_target=self.scope.validate_chat_control_target,
            record_chat=self.messages.record,
        ).scope(run_id, parent_id, child_id, phase):
            yield


    def repair_task_from_chat(
        self, run_id: str, task_id: str, *, request_id: str, message: str, fingerprint: str, conversation_revision: int,
        parent_request_id: str = "", recovery_fingerprint: str = "",
    ) -> RunState:
        with self.chat_control_child(run_id, parent_request_id, request_id, "repairing"):
            return self.repair_task_locked(run_id, task_id, request_id=request_id, message=message,
                                               fingerprint=fingerprint, conversation_revision=conversation_revision,
                                               parent_request_id=parent_request_id, recovery_fingerprint=recovery_fingerprint)


    def repair_task_locked(
        self, run_id: str, task_id: str, *, request_id: str, message: str, fingerprint: str, conversation_revision: int,
        parent_request_id: str = "", recovery_fingerprint: str = "",
    ) -> RunState:
        try:
            normalized_id = str(uuid.UUID(request_id))
        except (ValueError, AttributeError) as exc:
            raise PipelineError("복구 요청 ID가 올바르지 않습니다.") from exc
        message = message.strip()
        if not message or len(message) > 1800:
            raise PipelineError("복구 요청을 1~1800자로 입력해 주세요.")
        recovery = ChatTaskRecovery(
            records=ChatRecoveryRecords(self.records.load, self.records.load_operation, self.records.load_revision_requests,
                                        self.records.save_revision_requests, self.records.save_planning_chat),
            validate_parent=self.scope.validate_chat_control_target, retry_context=self.retry_guidance.context, find_task=find_task,
            scope_review=self.tasks.task_scope_review, scope_digest=scope_contract_digest,
            restore_legacy=self.tasks.restore_legacy_no_commit_retry_action, verification_timed_out=task_verification_timed_out,
            recovery_capability=self.retry_guidance.capability, retry_digest=retry_task_contract_digest,
            append_user=self.planning_messages.append_user, append_assistant=self.planning_messages.append_assistant,
        )
        with self.records.lock(run_id, "retry-task"):
            with self.records.planning_chat_lock(run_id), self.records.revision_requests_lock(run_id):
                prepared = recovery.prepare(
                    run_id, task_id, normalized_id=normalized_id, message=message, fingerprint=fingerprint,
                    conversation_revision=conversation_revision, parent_request_id=parent_request_id,
                    recovery_fingerprint=recovery_fingerprint,
                )
                state = prepared.state
                if prepared.replayed:
                    return state
                verification_only = prepared.verification_only
            with self.control.owned_session(run_id, "task"):
                # The run lock covers instruction acceptance and the entire existing execution loop.
                # With one failed Task this retries it and dispatches remaining Tasks only on success.
                if verification_only:
                    self.tasks.extend_task_timeout_for_recovery(state)
                find_task(state, task_id).failed_action = TaskAction.VERIFY if verification_only else TaskAction.EXECUTE
                if find_task(state, task_id).status == TaskStatus.STOPPED:
                    find_task(state, task_id).status = TaskStatus.PENDING
                    find_task(state, task_id).error = ""
                    state.refresh_task_readiness()
                state.add_event("task_repair", f"{task_id} 사용자 채팅 요청으로 수정·검증과 남은 작업을 시작합니다")
                self.records.save(state)
                return self.flow.execute(state, manual=False, recover_saved_profiles=True)


    def verification_repair_workflow(self) -> VerificationRepairWorkflow:
        return VerificationRepairWorkflow(
            records=VerificationRepairRecords(
                load_run=self.records.load, claim=self.records.claim_operation,
                save_state=self.records.save, save_operation=self.records.save_operation,
            ),
            default_limit=lambda: self.execution_settings().verification_repair_limit,
            record_chat=self.messages.record, ensure_policy=self.ensure_verification,
            verify=self.verification.verify_locked, failure_is_repairable=self.verification.verification_failure_is_repairable,
            repair=self.verification.repair_verification_failure, finish=self.verification.finish_verification_repair,
            interrupt_repair=self.verification.restore_verification_repair_stop,
        )


    def verify_and_repair(self, run_id: str, *, request_id: str, chat_message: str = "", parent_request_id: str = "",
                           max_repairs: int | None = None) -> RunState:
        chat_message = chat_message.strip()
        if len(chat_message) > 1800:
            raise PipelineError("복구 요청을 1800자 이내로 입력해 주세요.")
        normalized_request_id = conflict_request_id(request_id)
        with self.records.lock(run_id, "verify-and-repair"):
            if parent_request_id:
                parent = self.records.load_operation(run_id, parent_request_id)
                if parent is None:
                    raise PipelineError("복구 요청 기록을 찾지 못했습니다.")
                self.scope.validate_chat_control_target(self.records.load(run_id), parent)
            with self.control.owned_session(run_id, "verification"):
                return self.verification_repair_workflow().run(
                    run_id, normalized_request_id, chat_message, max_repairs=max_repairs,
                )
