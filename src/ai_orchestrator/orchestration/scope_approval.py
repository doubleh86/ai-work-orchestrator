"""ScopeApprovalActions with explicit feature and persistence dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, ContextManager
from ..errors import PipelineError
from ..execution import ExecutionControlService
from ..execution.flow import ExecutionFlow
from ..execution.scope_approval import ScopeApprovalRecords, ScopeApprovalWorkflow
from ..models import OperationRecord, RunState, TaskStatus
from ..persistence.execution_records import ScopeApprovalActionsRecords
from ..persistence.run_lookup import find_task
from ..planning import PlanningPreviewWorkflow
from ..planning.lifecycle import PlanningLifecycle
from ..planning.plan_files import PlanFiles
from ..queries.scope_approval import ScopeApprovalQueries
from ..queries.scope_proposals import ScopeProposalQueries


@dataclass
class ScopeApprovalActions:
    records: ScopeApprovalActionsRecords
    planning_lifecycle: PlanningLifecycle
    proposals: ScopeProposalQueries
    flow: ExecutionFlow
    control: ExecutionControlService
    files: PlanFiles
    planning_previews: Callable[[], PlanningPreviewWorkflow]

    def scope_approval_queries(self) -> ScopeApprovalQueries:
        return ScopeApprovalQueries(self.records.load, self.records.load_operation, self.records.recent_operations)


    def scope_approval_result(self, record: OperationRecord) -> dict[str, object]:
        return self.scope_approval_queries().result(record)


    def apply_chat_scope_approval(self, run_id: str, parent_id: str, step_id: str) -> RunState:
        workflow = ScopeApprovalWorkflow(
            records=ScopeApprovalRecords(
                self.records.load, self.records.load_operation, self.records.load_planning_apply_preview, self.records.load_effort_policy,
                self.records.claim_operation, self.records.save_operation, self.records.save, self.records.request_control_lock,
            ),
            validate_target=self.validate_chat_control_target, scope_proposal=self.proposals.proposal,
            public_preview=self.planning_previews().public, plan_paths=self.files.result_paths,
            preview_changes=self.planning_previews().changes, apply_plan=self.planning_lifecycle.apply_pending, find_task=find_task,
        )
        with self.records.lock(run_id, "retry-task"):
            with self.records.planning_chat_lock(run_id):
                applied = workflow.apply_locked(run_id, parent_id, step_id)
                state, operation, task_id = applied.state, applied.operation, applied.task_id
            with self.records.request_control_lock(run_id):
                parent = self.records.load_operation(run_id, parent_id)
                if parent is None or parent.status != "running" or parent.phase != "acting" or parent.payload.get("step_id") != step_id:
                    operation.update("applied", status="partial", error="경로 반영 후 요청이 취소돼 재시도는 시작하지 않았습니다.")
                    self.records.save_operation(operation)
                    return state
                parent.payload["fingerprint"] = self.proposals.fingerprint(state)
                parent.payload["scope_approval_consumed"] = True
                self.records.save_operation(parent)
                operation.update("executing" if applied.resume else "completed",
                                 status="running" if applied.resume else "succeeded")
                self.records.save_operation(operation)
            if not applied.resume:
                return state
            try:
                with self.control.owned_session(run_id, "task"):
                    state = self.flow.execute(state, manual=False, selected_task_ids={task_id}, retry_selected=True, recover_saved_profiles=True)
            except Exception as exc:
                operation.update("execution_failed", status="failed", error=f"허용 경로 반영은 완료됐지만 재시도에 실패했습니다: {exc}")
                self.records.save_operation(operation)
                raise
            target = find_task(state, task_id)
            operation.update("completed", status="succeeded" if target.status == TaskStatus.COMPLETED else "failed",
                             error="" if target.status == TaskStatus.COMPLETED else target.error or state.failure_message)
            self.records.save_operation(operation)
            return state


    def validate_chat_control_target(self, state: RunState, record: OperationRecord) -> None:
        if record.payload.get("intent") == "project":
            if state.archive or self.proposals.fingerprint(state) != record.payload.get("fingerprint"):
                raise PipelineError("AI 판단 이후 계획·대화·실행 대상이 변경됐습니다. 현재 상태에서 다시 요청해 주세요.")
            return
        expected = record.payload["expected"]
        if (state.archive or state.plan_revision != expected.get("planRevision")
                or state.planning_conversation_revision != expected.get("conversationRevision", 0)):
            raise PipelineError("복구 직전에 계획·대화·보관 상태가 변경됐습니다.")
        execution = self.records.load_execution_control(state.id)
        if (execution.execution_id if execution else "") != expected.get("executionId", ""):
            raise PipelineError("복구 직전에 대상 실행이 변경됐습니다.")
