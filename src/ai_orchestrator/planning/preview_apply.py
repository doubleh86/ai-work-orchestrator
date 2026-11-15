"""Validate and apply saved planning previews under caller-owned locks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from ..errors import PipelineError
from ..models import DirectionChangeStatus, PlanningApplyRequest, PlanningApplyStatus, RunState, Stage, TaskStatus, WorkTask, utc_now
from .contracts import Plan
from .validation import validate_task_graph


class ApplyPreviewPendingPlan(Protocol):
    def __call__(self, state: RunState, *, apply_request: PlanningApplyRequest, prepared_plan: Plan) -> RunState: ...


@dataclass(frozen=True, slots=True)
class PreviewApplyRecords:
    load_run: Callable[[str], RunState]
    load_preview: Callable[[str], dict[str, object] | None]
    save_state: Callable[[RunState], None]
    save_chat: Callable[[RunState], None]


@dataclass(frozen=True, slots=True)
class PlanningPreviewApplication:
    records: PreviewApplyRecords
    validate_payload: Callable[[dict[str, object]], None]
    find_request: Callable[[RunState, str], PlanningApplyRequest | None]
    fingerprint: Callable[[RunState], str]
    changes: Callable[[RunState, Plan], list[dict[str, object]]]
    task_fields: Callable[[WorkTask], dict[str, object]]
    apply_pending: ApplyPreviewPendingPlan
    apply_initial: Callable[[RunState, Plan], RunState]
    public: Callable[[RunState, dict[str, object]], dict[str, object]]

    def apply_locked(self, run_id: str, *, preview_id: str, fingerprint: str, candidate_digest: str) -> dict[str, object]:
        state = self.records.load_run(run_id)
        preview = self.records.load_preview(run_id)
        if preview is None or preview.get("preview_id") != preview_id:
            raise PipelineError("Planning 미리보기를 찾을 수 없습니다. 다시 생성해 주세요.")
        self.validate_payload(preview)
        if preview.get("fingerprint") != fingerprint or preview.get("candidate_digest") != candidate_digest:
            raise PipelineError("확인한 Planning 후보와 저장된 후보가 다릅니다. 다시 확인해 주세요.")
        existing = self.find_request(state, str(preview.get("request_id", "")))
        if existing is not None and existing.status == PlanningApplyStatus.SUCCEEDED:
            return {"run": state, "preview": self.public(state, preview)}
        if self.fingerprint(state) != fingerprint:
            raise PipelineError("대화·Task·그룹 상태가 변경되었습니다. 미리보기를 다시 생성해 주세요.")
        if not preview.get("can_apply"):
            raise PipelineError("보존할 Task 변경 또는 실행 중인 작업이 있습니다. 새 후속 Task로 계획하거나 종료 후 다시 미리보기를 만드세요.")
        payload = preview["plan"]
        if not isinstance(payload, dict) or not isinstance(payload.get("tasks"), list):
            raise PipelineError("저장된 Planning 후보 형식이 올바르지 않습니다.")
        if payload.get("questions") or payload.get("tech_stack_options"):
            raise PipelineError("질문·기술 구성 후보는 Task 변경 미리보기로 반영할 수 없습니다.")
        raw_state = state.to_dict()
        raw_state["tasks"] = payload["tasks"]
        restored = RunState.from_dict(raw_state)
        plan = Plan(
            summary=str(payload["summary"]), server_work=bool(payload["server_work"]), tasks=restored.tasks,
            source_paths=list(payload.get("source_paths", [])), instruction_paths=list(payload.get("instruction_paths", [])),
        )
        if any(task.status not in {TaskStatus.PENDING, TaskStatus.WAITING} or task.active_action or task.action_results for task in plan.tasks):
            raise PipelineError("저장된 Planning 후보에 실행 결과가 섞여 있습니다. 미리보기를 다시 생성해 주세요.")
        changes = self.changes(state, plan)
        if changes != preview.get("changes") or any(item["kind"] == "review_required" for item in changes):
            raise PipelineError("보존할 Task 상태 또는 후보 차이가 변경되었습니다. 미리보기를 다시 생성해 주세요.")
        validate_task_graph(plan.tasks)
        original = {task.id: self.task_fields(task) for task in state.tasks}
        request = PlanningApplyRequest(
            request_id=str(preview["request_id"]), conversation_revision=state.planning_conversation_revision,
            plan_revision=state.plan_revision, context_snapshot="", status=PlanningApplyStatus.APPLYING,
        )
        state.planning_apply_requests.append(request)
        if state.stage in {Stage.EXECUTING, Stage.READY_TO_MERGE} or (state.stage == Stage.FAILED and state.tasks):
            updated = self.apply_pending(state, apply_request=request, prepared_plan=plan)
        else:
            updated = self.apply_initial(state, plan)
        final = {task.id: self.task_fields(task) for task in updated.tasks}
        request.status = PlanningApplyStatus.SUCCEEDED
        request.completed_at = utc_now()
        request.added_tasks = len(final.keys() - original.keys())
        request.excluded_tasks = len(original.keys() - final.keys())
        request.updated_tasks = sum(original[key] != final[key] for key in original.keys() & final.keys())
        request.unchanged_tasks = len(final) - request.added_tasks - request.updated_tasks
        updated.planning_applied_conversation_revision = max(
            updated.planning_applied_conversation_revision, request.conversation_revision
        )
        direction_ids = set(preview.get("direction_request_ids", []))
        for item in updated.direction_change_requests:
            if item.request_id in direction_ids:
                item.status = DirectionChangeStatus.APPLIED
                item.preview_id = preview_id
                item.next_step = "Task 변경 반영 완료"
                item.error = ""
                item.updated_at = utc_now()
        self.records.save_state(updated)
        self.records.save_chat(updated)
        return {"run": updated, "preview": self.public(updated, preview)}
