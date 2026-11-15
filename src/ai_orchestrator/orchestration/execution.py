"""ExecutionCommands with explicit feature and persistence dependencies."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, ContextManager
from ..config import ExecutionConfig
from ..errors import ApprovalRequired as ApprovalRequired, PipelineError
from ..execution import ExecutionControlService, TaskRetryGuidance, retry_task_contract_digest, scope_contract_digest
from ..execution.flow import ExecutionFlow
from ..execution.manual_tasks import ManualTaskDeferral
from ..execution.operation_lifecycle import RunStepLifecycle
from ..execution.policy_lifecycle import ExecutionPolicyLifecycle
from ..execution.preparation import advance_completed_tasks
from ..execution.profile_workflows import ExecutionProfiles
from ..execution.retry_guidance import task_verification_timed_out
from ..execution.task_workflows import TaskWorkflows
from ..execution.user_checks import UserCheckRecorder
from ..git import GitError, GitWorkspace, LOCAL_GIT_TIMEOUT_SECONDS, run_command
from ..integration import uses_shared_workspace
from ..integration.workspace_access import WorkspaceAccess
from ..models import OperationRecord, RunLockState, RunState, RunStep, Stage, TaskReadiness, TaskStatus, UserCheckOutcome, WorkTask
from ..orchestration.scope_approval import ScopeApprovalActions
from ..persistence.execution_records import ExecutionCommandsRecords
from ..persistence.run_lookup import RunLookup, find_task
from ..planning.apply_requests import normalize_planning_apply_request_id
from ..queries.scope_proposals import ScopeProposalQueries
from ..scope_consent import scope_proposal_id


@dataclass
class ExecutionCommands:
    records: ExecutionCommandsRecords
    lookup: RunLookup
    profiles: ExecutionProfiles
    flow: ExecutionFlow
    control: ExecutionControlService
    scope: ScopeApprovalActions
    proposals: ScopeProposalQueries
    tasks: TaskWorkflows
    retry_guidance: TaskRetryGuidance
    read_git: Callable[[], GitWorkspace]
    policy: ExecutionPolicyLifecycle
    read_repo: Callable[[], Path]
    steps: RunStepLifecycle
    workspace: WorkspaceAccess
    execution_settings: Callable[[], ExecutionConfig]

    def update_task_execution_profile(
        self, run_id: str, task_id: str, *, agent_id: str, model: str, reasoning_effort: str, expected_profile: dict[str, str]
    ) -> RunState:
        queued = self.profiles.queue_task_execution_profile(
            run_id, task_id, agent_id=agent_id, model=model, reasoning_effort=reasoning_effort, expected_profile=expected_profile
        )
        if queued is not None:
            return queued
        with self.records.lock(run_id, "update-task-execution-profile"), self.records.planning_chat_lock(run_id):
            state = self.lookup.at(run_id, {Stage.EXECUTING, Stage.FAILED})
            return self.profiles.save_task_execution_profile_locked(
                state, task_id, agent_id=agent_id, model=model, reasoning_effort=reasoning_effort, expected_profile=expected_profile,
            )


    def execution_profile_view(self, state: RunState) -> RunState:
        return self.profiles.service().view(state)


    def execute(
        self,
        run_id: str,
        *,
        manual: bool = False,
        agent_overrides: dict[str, str] | None = None,
        model_overrides: dict[str, str] | None = None,
        reasoning_effort_overrides: dict[str, str] | None = None,
        expected_revision: int | None = None,
    ) -> RunState:
        with self.records.lock(run_id, "execute"):
            with self.control.owned_session(run_id, "task"):
                state = self.lookup.at(run_id, {Stage.PLANNED, Stage.EXECUTING, Stage.FAILED})
                if expected_revision is not None and state.plan_revision != expected_revision:
                    raise PipelineError("실행하려던 계획이 변경됐습니다. 최신 계획을 다시 확인해 주세요.")
                return self.flow.execute(
                    state,
                    manual=manual,
                    agent_overrides=agent_overrides,
                    model_overrides=model_overrides,
                    reasoning_effort_overrides=reasoning_effort_overrides,
                )


    def resume(self, run_id: str, *, manual: bool = False, expected_revision: int | None = None) -> RunState:
        with self.records.lock(run_id, "resume"):
            state = self.records.load(run_id)
            if expected_revision is not None and state.plan_revision != expected_revision:
                raise PipelineError("재개하려던 계획이 변경됐습니다. 최신 계획을 다시 확인해 주세요.")
            if state.stage not in {Stage.PLANNED, Stage.EXECUTING, Stage.FAILED} or (
                state.stage == Stage.FAILED and state.failed_step is None
            ):
                raise PipelineError(f"run {run_id} at '{state.stage.value}' has no resumable failure")
            with self.control.owned_session(run_id, "task"):
                return self.flow.resume(run_id, manual=manual)


    def approve_task_scope(self, run_id: str, task_id: str, *, request_id: str, review_id: str,
                           approved: bool) -> dict[str, object]:
        if not approved:
            raise ApprovalRequired("작업 경로 추가와 재시도에는 사용자 확인이 필요합니다.")
        request_id = normalize_planning_apply_request_id(request_id)
        digest = scope_proposal_id({"task_id": task_id, "review_id": review_id})
        with self.records.request_control_lock(run_id):
            existing = self.records.load_operation(run_id, request_id)
            if existing is not None:
                if existing.action != "mcp_scope_approval" or existing.digest != digest:
                    raise PipelineError("같은 요청 ID를 다른 경로 승인에 사용할 수 없습니다.")
                result = self.scope.scope_approval_result(existing)
                if result["retry_status"] == "running" and self.records.inspect_lock(run_id).state != RunLockState.ACTIVE:
                    result.update(retry_status="confirmation_required", scope_applied=True if result["scope_applied"] else None,
                                  error="이전 요청이 중단됐습니다. 현재 허용 경로와 실행 기록을 확인해 주세요.")
                return result
            chat = self.records.latest_operation(run_id, "chat_control")
            if chat is not None and chat.status == "running":
                raise PipelineError("작업 그룹 채팅에서 다른 요청이 진행 중입니다.")
            state = self.records.load(run_id)
            proposal = self.proposals.proposal(state, task_id)
            if not proposal or scope_proposal_id(proposal) != review_id:
                raise PipelineError("승인할 작업·시도·경로가 바뀌었습니다. 실패 상세를 다시 확인해 주세요.")
            step_id = str(uuid.uuid4())
            record = OperationRecord(
                request_id=request_id, run_id=run_id, action="mcp_scope_approval", digest=digest, phase="acting",
                payload={"intent": "project", "fingerprint": proposal["fingerprint"], "step_id": step_id,
                         "scope_approval": {"proposal": proposal, "resume": True}, "message": "MCP 사용자 확인"},
            )
            _, created = self.records.claim_operation(record)
            if not created:
                raise PipelineError("경로 승인 요청 ID가 이미 사용됐습니다.")
        error = ""
        try:
            self.scope.apply_chat_scope_approval(run_id, request_id, step_id)
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            with self.records.request_control_lock(run_id):
                record = self.records.load_operation(run_id, request_id) or record
                result = self.scope.scope_approval_result(record)
                record.update("completed", status="succeeded" if result["retry_status"] == "succeeded" else "failed",
                              error=error or str(result["error"]))
                self.records.save_operation(record)
        return self.scope.scope_approval_result(record)


    def retry_task(self, run_id: str, task_id: str, *, manual: bool = False) -> RunState:
        with self.records.lock(run_id, "retry-task"):
            with self.control.owned_session(run_id, "task"):
                state = self.lookup.at(run_id, {Stage.EXECUTING, Stage.FAILED})
                task = find_task(state, task_id)
                if task.status in {TaskStatus.RUNNING, TaskStatus.REVIEWING, TaskStatus.REVISING} or task.active_action:
                    self.tasks.mark_task_interrupted(task)
                if task.status not in {TaskStatus.FAILED, TaskStatus.STOPPED}:
                    raise PipelineError(f"task {task_id} is not failed, interrupted, or stopped")
                if state.stage == Stage.FAILED and state.failed_step != RunStep.AGENT_EXECUTION:
                    step = state.failed_step.value if state.failed_step else "unknown"
                    raise PipelineError(f"task retry is not valid for {step} failure")
                context = self.retry_guidance.context(state, task_id)
                instruction = context["instruction"] if context["instruction_current"] else None
                self.tasks.restore_legacy_no_commit_retry_action(state, task)
                if task_verification_timed_out(task):
                    self.tasks.extend_task_timeout_for_recovery(state)
                previous_attempt = task.last_attempt_id
                result = self.flow.execute(state, manual=manual, selected_task_ids={task_id}, retry_selected=True, recover_saved_profiles=True)
                completed = find_task(result, task_id)
                if (isinstance(instruction, dict) and completed.status == TaskStatus.COMPLETED and completed.completed_commit
                        and completed.last_attempt_id and completed.last_attempt_id != previous_attempt
                        and instruction.get("task_contract_digest") == retry_task_contract_digest(completed)
                        and result.stage == Stage.EXECUTING
                        and any(item.status == TaskStatus.PENDING and item.readiness == TaskReadiness.READY for item in result.tasks)
                        and not any(item.status in {TaskStatus.FAILED, TaskStatus.WAITING, TaskStatus.STOPPED} for item in result.tasks)):
                    self.retry_guidance.record_wait(result, completed, str(instruction["request_id"]), completed=True)
                return result


    def execute_task(
        self,
        run_id: str,
        task_id: str,
        *,
        manual: bool = False,
        agent_overrides: dict[str, str] | None = None,
        model_overrides: dict[str, str] | None = None,
        reasoning_effort_overrides: dict[str, str] | None = None,
    ) -> RunState:
        selected_ids = {task_id}
        for name, overrides in (
            ("provider", agent_overrides),
            ("model", model_overrides),
            ("reasoning", reasoning_effort_overrides),
        ):
            unexpected = set(overrides or {}) - selected_ids
            if unexpected:
                raise PipelineError(f"individual task {name} overrides contain other tasks: " + ", ".join(sorted(unexpected)))
        with self.records.lock(run_id, "execute-task"):
            with self.control.owned_session(run_id, "task"):
                return self.flow.execute_task_locked(
                    run_id,
                    task_id,
                    manual=manual,
                    agent_overrides=agent_overrides,
                    model_overrides=model_overrides,
                    reasoning_effort_overrides=reasoning_effort_overrides,
                )


    def set_manual_task_deferred(self, run_id: str, task_id: str, *, deferred: bool) -> RunState:
        operation = "defer-manual-task" if deferred else "resume-manual-task"
        with self.records.lock(run_id, operation), self.records.planning_chat_lock(run_id):
            state = self.lookup.at(run_id, {Stage.EXECUTING})
            return ManualTaskDeferral(
                git=self.read_git(), uses_shared=uses_shared_workspace, find_task=find_task,
                load_control=self.records.load_execution_control, clean_workspace=self.tasks.clean_manual_workspace,
                activate_tasks=self.tasks.activate_manual_tasks, merge_dependencies=self.tasks.merge_task_dependencies, save_state=self.records.save,
            ).set_deferred(state, run_id, task_id, deferred=deferred)


    def record_user_check(
        self, run_id: str, check_id: str, *, expected_revision: int, expected_commit: str, outcome: str, note: str,
    ) -> RunState:
        note = note.strip()
        if not note or len(note) > 1800:
            raise PipelineError("확인 결과 메모를 1~1800자로 입력해 주세요.")
        try:
            selected = UserCheckOutcome(outcome)
        except ValueError as exc:
            raise PipelineError("사용자 확인 결과는 통과, 실패, 보류 중에서 선택해 주세요.") from exc
        with self.records.lock(run_id, "record-user-check"):
            state = self.lookup.at(run_id, {Stage.PLANNED, Stage.EXECUTING, Stage.FAILED, Stage.READY_TO_MERGE, Stage.VERIFIED,
                                           Stage.WORK_BRANCH_PUSHED, Stage.MERGED, Stage.PUSHED, Stage.DEPLOYED})
            self.policy.require_confirmed_plan(state)
            recorded = UserCheckRecorder(
                inspect_commit=lambda reference: run_command(
                    ["git", "cat-file", "-e", f"{reference}^{{commit}}"], self.read_repo(),
                    non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
                ),
            ).record(state, check_id, expected_revision=expected_revision, expected_commit=expected_commit, selected=selected, note=note)
            if not recorded:
                return state
            if state.stage == Stage.EXECUTING and not state.active_execution_request_id:
                advance_completed_tasks(state)
            self.records.save(state)
            return state


    def complete_manual_verification(
        self, run_id: str, task_id: str, *, note: str, expected_commit: str, expected_revision: int,
    ) -> RunState:
        note = note.strip()
        if not 1 <= len(note) <= 4000 or "\0" in note:
            raise PipelineError("수동 검증 환경과 확인 결과를 1~4000자로 입력해 주세요.")
        with self.records.lock(run_id, "complete-task"), self.records.planning_chat_lock(run_id):
            state = self.lookup.at(run_id, {Stage.EXECUTING, Stage.READY_TO_MERGE})
            task = find_task(state, task_id)
            self.tasks.require_manual_task_version(state, task, expected_commit, expected_revision)
            result = task.result_history[-1] if task.result_history else None
            if (task.status == TaskStatus.COMPLETED and task.completed_commit == expected_commit and result is not None
                    and result.result_commit == expected_commit and result.manual_verification_note == note):
                return state
            self.tasks.require_waiting_manual_workspace(state, task)
            self.tasks.check_manual_review(task, expected_commit, manual_verification=True)
            with self.steps.step(state, RunStep.MANUAL_COMPLETION):
                return self.tasks.complete_task(state, task, manual_verification_note=note)


    def handoff_manual_task_to_ai(
        self, run_id: str, task_id: str, *, expected_commit: str, expected_revision: int,
    ) -> RunState:
        with self.records.lock(run_id, "execute-task"):
            with self.records.planning_chat_lock(run_id):
                state = self.lookup.at(run_id, {Stage.EXECUTING})
                task = find_task(state, task_id)
                self.tasks.require_manual_task_version(state, task, expected_commit, expected_revision)
                self.tasks.require_waiting_manual_workspace(state, task)
            with self.control.owned_session(run_id, "task"):
                return self.flow.execute(state, manual=False, selected_task_ids={task_id}, recover_saved_profiles=True)


    def complete_task(self, run_id: str, task_id: str) -> RunState:
        with self.records.lock(run_id, "complete-task"):
            state = self.lookup.at(run_id, {Stage.EXECUTING})
            task = find_task(state, task_id)
            if task.status != TaskStatus.WAITING:
                raise PipelineError(f"task {task_id} is not waiting for manual completion")
            self.workspace.ensure_execution_workspace_ready()
            worktree = Path(task.worktree)
            try:
                self.tasks.validate_task_change_scope(task, state)
                if self.execution_settings().auto_commit:
                    self.read_git().commit_all(
                        worktree,
                        f'feat({task.id}): {task.title}',
                        non_interactive=True,
                        timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
                    )
                self.tasks.validate_task_change_scope(task, state)
            except (GitError, PipelineError) as exc:
                task.error = str(exc)
                state.add_event("task", f"{task.id} manual completion blocked: {exc}")
                self.records.save(state)
                raise
            if uses_shared_workspace(state):
                current_head = self.read_git().head(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
                if task.started_commit and current_head == task.started_commit:
                    raise PipelineError(f"task {task.id} produced no commit in the shared workspace")
            elif not self.read_git().branch_has_changes(task.branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS):
                raise PipelineError(f"task {task.id} has no commits to merge")
            if task.reviewer_agent_id:
                head = self.read_git().head(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
                self.tasks.check_manual_review(task, head)
            with self.steps.step(state, RunStep.MANUAL_COMPLETION):
                return self.tasks.complete_task(state, task)


    def task_retry_context(self, run_id: str, task_id: str) -> dict[str, object]:
        before = self.records.inspect_lock(run_id)
        state = self.records.load(run_id)
        context = self.retry_guidance.context(state, task_id)
        after = self.records.inspect_lock(run_id)
        if before != after or after.state != RunLockState.UNLOCKED:
            context.update(can_save=False, reason="작업 그룹의 실행 잠금 상태를 확인하고 종료 후 다시 시도하세요.")
            context["recovery"].update(can_execute=False, kind="unavailable", reason_code="execution_lock")
            if context["scope_review"]:
                context["scope_review"]["review_id"] = ""
        return context


    def record_task_diagnosis(self, run_id: str, task_id: str, fingerprint: str, diagnosis: str) -> None:
        diagnosis = diagnosis.strip()
        if not diagnosis or len(diagnosis) > 8000:
            raise PipelineError("점검 결과를 1~8000자로 입력해 주세요.")
        with self.records.lock(run_id, "record-task-diagnosis"), self.records.planning_chat_lock(run_id):
            self.tasks.retry().diagnose(run_id, task_id, fingerprint, diagnosis)


    def save_task_retry_instruction(
        self, run_id: str, task_id: str, *, request_id: str, text: str, fingerprint: str
    ) -> dict[str, object]:
        try:
            normalized_id = str(uuid.UUID(request_id))
        except (ValueError, AttributeError) as exc:
            raise PipelineError("수정 지시 요청 ID가 올바르지 않습니다.") from exc
        instruction = text.strip()
        if not instruction or len(instruction) > 8000:
            raise PipelineError("수정 지시를 1~8000자로 입력해 주세요.")
        with self.records.lock(run_id, "retry-instruction-save"), self.records.revision_requests_lock(run_id):
            return self.tasks.retry().save_instruction(run_id, task_id, normalized_id, instruction, fingerprint)


    def task_failure_message(self, task: WorkTask) -> str:
        """조회용 오류를 요약하며 저장된 실패와 action 원문은 변경하지 않는다."""
        review = self.tasks.task_scope_review(task)
        return review.error(scope_contract_digest(task)) if review else task.error
