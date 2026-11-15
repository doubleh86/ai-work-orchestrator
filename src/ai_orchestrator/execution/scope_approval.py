"""Apply a current user-approved scope change under caller-owned locks."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable, ContextManager, Protocol

from ..errors import PipelineError
from ..models import DirectionChangeStatus, EffortPolicyState, OperationRecord, PlanningApplyRequest, PlanningApplyStatus, RunState, WorkTask
from ..planning import Plan


class ApprovedScopePlanApply(Protocol):
    def __call__(
        self, state: RunState, *, apply_request: PlanningApplyRequest, prepared_plan: Plan, preparation_task_ids: set[str],
    ) -> RunState: ...


@dataclass(frozen=True, slots=True)
class ScopeApprovalRecords:
    load_run: Callable[[str], RunState]
    load_operation: Callable[[str, str], OperationRecord | None]
    load_preview: Callable[[str], dict[str, object] | None]
    load_policy: Callable[[str], EffortPolicyState]
    claim_operation: Callable[[OperationRecord], tuple[OperationRecord, bool]]
    save_operation: Callable[[OperationRecord], None]
    save_state: Callable[[RunState], None]
    control_lock: Callable[[str], ContextManager[None]]


@dataclass(frozen=True, slots=True)
class AppliedScopeApproval:
    state: RunState
    operation: OperationRecord
    task_id: str
    resume: bool


@dataclass(frozen=True, slots=True)
class ScopeApprovalWorkflow:
    records: ScopeApprovalRecords
    validate_target: Callable[[RunState, OperationRecord], None]
    scope_proposal: Callable[[RunState, str], dict[str, object] | None]
    public_preview: Callable[[RunState, dict[str, object]], dict[str, object]]
    plan_paths: Callable[[RunState], tuple[list[str], list[str]]]
    preview_changes: Callable[[RunState, Plan], list[dict[str, object]]]
    apply_plan: ApprovedScopePlanApply
    find_task: Callable[[RunState, str], WorkTask]

    def apply_locked(self, run_id: str, parent_id: str, step_id: str) -> AppliedScopeApproval:
        state = self.records.load_run(run_id)
        parent = self.records.load_operation(run_id, parent_id)
        if parent is None or parent.status != "running" or parent.phase != "acting" or parent.payload.get("step_id") != step_id:
            raise PipelineError("경로 승인 요청이 취소되었거나 실행 대상이 바뀌었습니다.")
        self.validate_target(state, parent)
        approval = parent.payload.get("scope_approval")
        if not isinstance(approval, dict) or parent.payload.get("scope_approval_consumed"):
            raise PipelineError("사용자가 승인한 경로 변경 요청을 찾지 못했습니다.")
        proposal = approval["proposal"]
        task_id = str(proposal["task_id"])
        if self.scope_proposal(state, task_id) != proposal:
            raise PipelineError("승인한 작업·실패 시도·경로가 변경됐습니다. 최신 제안을 확인해 주세요.")
        if state.planning_follow_up_requests or any(item.status != DirectionChangeStatus.APPLIED
                                                   for item in state.direction_change_requests):
            raise PipelineError("다른 계획 변경이 대기 중입니다. 기존 변경안을 먼저 검토해 주세요.")
        preview = self.records.load_preview(run_id)
        if preview:
            public_preview = self.public_preview(state, preview)
            if public_preview.get("status") == "preview" and not public_preview.get("stale"):
                raise PipelineError("다른 계획 미리보기가 있습니다. 기존 변경안을 먼저 검토해 주세요.")
        if state.active_execution_request_id:
            binding = self.records.load_policy(run_id).binding(state.active_execution_request_id)
            if binding is None or binding.status != "finished":
                raise PipelineError("기존 실행 정책이 종료되지 않았습니다. 실행 상태를 먼저 확인해 주세요.")
        digest = hashlib.sha256(json.dumps(approval, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        previous = self.records.load_operation(run_id, step_id)
        if previous is not None:
            if previous.action != "task_scope_approval" or previous.digest != digest:
                raise PipelineError("같은 승인 요청 ID를 다른 범위에 사용할 수 없습니다.")
            raise PipelineError("이미 시작된 경로 승인 요청입니다. 기존 처리 결과를 확인해야 하며 자동으로 다시 실행하지 않습니다.")
        source_paths, instruction_paths = self.plan_paths(state)
        plan = Plan(summary=state.summary, server_work=state.server_work, tasks=deepcopy(state.tasks),
                    source_paths=source_paths, instruction_paths=instruction_paths)
        target = next(task for task in plan.tasks if task.id == task_id)
        target.expected_paths = list(dict.fromkeys([*target.expected_paths, *proposal["paths"]]))
        changes = self.preview_changes(state, plan)
        if any(item["kind"] != "unchanged" and (item["task_id"] != task_id or item["kind"] != "modified"
                                               or set(item["fields"]) != {"expected_paths"}) for item in changes):
            raise PipelineError("승인된 경로 외의 계획 변경이 포함돼 반영하지 않았습니다.")
        operation = OperationRecord(request_id=step_id, run_id=run_id, action="task_scope_approval", digest=digest,
                                    phase="accepted", payload={"proposal": proposal, "resume": approval["resume"]})
        self.records.claim_operation(operation)
        request = PlanningApplyRequest(request_id=step_id, conversation_revision=state.planning_conversation_revision,
            plan_revision=state.plan_revision, context_snapshot=json.dumps({"user_approval": parent.payload["message"],
                "scope_proposal": proposal}, ensure_ascii=False), status=PlanningApplyStatus.APPLYING)
        state.planning_apply_requests.append(request)
        with self.records.control_lock(run_id):
            fresh = self.records.load_operation(run_id, parent_id)
            if fresh is None or fresh.status != "running" or fresh.phase != "acting":
                operation.update("cancelled", status="interrupted", error="경로 반영 전에 승인이 취소됐습니다.")
                self.records.save_operation(operation)
                raise PipelineError("경로 반영 전에 승인이 취소됐습니다.")
            operation.update("applying")
            self.records.save_operation(operation)
        try:
            state = self.apply_plan(
                state, apply_request=request, prepared_plan=plan, preparation_task_ids={task_id},
            )
        except Exception as exc:
            operation.update("apply_failed", status="failed", error=str(exc))
            self.records.save_operation(operation)
            raise
        target = self.find_task(state, task_id)
        target.error = "허용 경로 반영 완료 · 수정·재검증 대기"
        state.add_event("planning", f"{task_id} 채팅에서 승인한 정확한 경로 반영: {', '.join(proposal['paths'])}")
        self.records.save_state(state)
        operation.update("applied")
        self.records.save_operation(operation)
        return AppliedScopeApproval(state, operation, task_id, approval["resume"])
