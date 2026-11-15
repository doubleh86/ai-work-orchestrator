"""Derive active planning and execution display from lock snapshots."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Protocol

from ..errors import PipelineError
from ..models import (
    DirectionChangeStatus, PlanningApplyRequest, PlanningApplyStatus, RunLockState, RunLockStatus,
    RunState, RunStep, Stage, TaskStatus, WorkTask, utc_now,
)
from .contracts import Plan
from .conversation import task_plan_draft
from .validation import validate_task_graph
from ..models import TaskAction

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..document_index import PlanningSourceIndex


def planning_preview_operations(
    state: RunState, run_lock: RunLockStatus, chat_lock: RunLockStatus, progress: dict[str, object]
) -> list[dict[str, str]]:
    operations: list[dict[str, str]] = []

    def operation(kind: str, lock: RunLockStatus) -> dict[str, str]:
        return {"kind": kind, "operation": lock.operation, "started_at": lock.acquired_at,
                "stage_changed_at": lock.acquired_at, "last_activity_at": "", "task_id": "", "task_title": ""}

    applying = run_lock.state == RunLockState.ACTIVE and run_lock.operation in {"planning-apply", "planning-preview-apply"}
    if chat_lock.state == RunLockState.ACTIVE and not applying:
        item = operation("preview_generation" if chat_lock.operation == "planning-preview" else "planning_chat", chat_lock)
        if chat_lock.operation == "planning-preview":
            if progress.get("started_at") == chat_lock.acquired_at and progress.get("owner_pid") == chat_lock.pid:
                if progress.get("phase") == "comparing":
                    item["kind"] = "preview_comparison"
                item["stage_changed_at"] = str(progress.get("phase_started_at", chat_lock.acquired_at))
                item["last_activity_at"] = str(progress.get("last_activity_at", ""))
        else:
            item["last_activity_at"] = max((event.at for event in state.events
                if event.kind == "planning_progress" and event.at >= chat_lock.acquired_at), default="")
        operations.append(item)
    if run_lock.state != RunLockState.ACTIVE:
        return operations
    if applying:
        operations.append(operation("plan_apply", run_lock))
        return operations
    tasks = [task for task in state.tasks if task.active_action is not None]
    if tasks and (state.active_step == RunStep.AGENT_EXECUTION
                  or run_lock.operation in {"execute", "resume", "retry-task", "execute-task"}):
        for task in tasks:
            kinds = {TaskAction.REVIEW: "task_review", TaskAction.VERIFY: "task_verify"}
            kind = kinds.get(task.active_action, "task_execute")
            item = operation(kind, run_lock)
            observation = task.progress_observation
            started = task.last_attempt_started_at or run_lock.acquired_at
            item.update(task_id=task.id, task_title=task.title, started_at=started,
                        stage_changed_at=observation.phase_started_at if observation else task.progress_updated_at or started)
            if observation and observation.evidence_kind in {"provider_event", "activity_change"}:
                item["last_activity_at"] = observation.last_event_received_at
            operations.append(item)
    else:
        kind = ("planning_chat" if run_lock.operation.startswith("planning") else
                "run_verify" if state.active_step == RunStep.VERIFY else "run_operation")
        item = operation(kind, run_lock)
        if kind == "planning_chat":
            item["last_activity_at"] = max((event.at for event in state.events
                if event.kind == "planning_progress" and event.at >= run_lock.acquired_at), default="")
        elif kind == "run_verify":
            item["started_at"] = state.verification_started_at or run_lock.acquired_at
            item["stage_changed_at"] = state.verification_progress_updated_at or item["started_at"]
        operations.append(item)
    return operations


def planning_task_editable(state: RunState, task: WorkTask) -> bool:
    if task.active_action or task.status in {
        TaskStatus.RUNNING, TaskStatus.REVIEWING, TaskStatus.REVISING,
        TaskStatus.COMPLETED, TaskStatus.MERGED, TaskStatus.STOPPED,
    }:
        return False
    return task.status in {TaskStatus.PENDING, TaskStatus.FAILED, TaskStatus.WAITING}


def planning_preview_task_fields(task: WorkTask) -> dict[str, object]:
    return {
        **task_plan_draft(task),
        "agent_id": task.agent_id,
        "reviewer_agent_id": task.reviewer_agent_id,
        "reviewer_provider_id": task.reviewer_provider_id,
        "reviewer_model": task.reviewer_model,
    }


def validate_planning_preview_payload(preview: dict[str, object]) -> None:
    plan = preview.get("plan")
    digest = preview.get("candidate_digest")
    if not isinstance(plan, dict) or not isinstance(digest, str):
        raise PipelineError("저장된 Planning 미리보기 형식이 올바르지 않습니다.")
    actual = hashlib.sha256(json.dumps(plan, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    if actual != digest:
        raise PipelineError("저장된 Planning 후보 내용이 변경되었습니다. 미리보기를 다시 생성해 주세요.")


def planning_apply_request(state: RunState, request_id: str) -> PlanningApplyRequest | None:
    return next((request for request in state.planning_apply_requests if request.request_id == request_id), None)


class PreviewPlanBuilder(Protocol):
    def __call__(
        self, state: RunState, spec: str, *, clarification_context: str,
        source_index: PlanningSourceIndex | None, preview_id: str,
    ) -> Plan: ...


@dataclass(frozen=True, slots=True)
class PlanningPreviewRecords:
    load_run: Callable[[str], RunState]
    load_candidate: Callable[[str], dict[str, object] | None]
    save_candidate: Callable[[str, dict[str, object]], None]
    load_progress: Callable[[str], dict[str, object] | None]
    save_progress: Callable[[str, dict[str, object]], None]
    save_chat: Callable[[RunState], None]
    run_lock: Callable[[str], RunLockStatus]
    chat_lock: Callable[[str], RunLockStatus]


@dataclass(frozen=True, slots=True)
class PlanningPreviewWorkflow:
    records: PlanningPreviewRecords
    build_plan: PreviewPlanBuilder
    clarification_context: Callable[[RunState], str]
    source_index: Callable[[RunState], PlanningSourceIndex | None]
    follow_up_request: Callable[[RunState], str]
    file_digest: Callable[[Path], str]
    normalize_request_id: Callable[[str], str]
    generation_errors: tuple[type[Exception], ...]

    def fingerprint(self, state: RunState) -> str:
        raw = state.to_dict()
        plan_path = Path(state.structured_plan_path) if state.structured_plan_path else None
        plan_digest = self.file_digest(plan_path) if plan_path is not None and plan_path.is_file() else ""
        payload = {
            "stage": state.stage.value,
            "active_step": state.active_step.value if state.active_step else "",
            "plan_revision": state.plan_revision,
            "approved_revision": state.plan_approved_revision,
            "conversation_revision": state.planning_conversation_revision,
            "applied_conversation_revision": state.planning_applied_conversation_revision,
            "planning_messages": raw["planning_messages"],
            "follow_up_requests": state.planning_follow_up_requests,
            "tasks": raw["tasks"],
            "summary": state.summary,
            "spec_digest": state.spec_digest,
            "base_commit": state.base_commit,
            "repository_intent": state.repository_intent,
            "greenfield_phase": state.greenfield_phase,
            "plan_digest": plan_digest,
        }
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    def changes(self, state: RunState, plan: Plan) -> list[dict[str, object]]:
        original = {task.id: task for task in state.tasks}
        proposed = {task.id: task for task in plan.tasks}
        changes: list[dict[str, object]] = []
        for task in plan.tasks:
            previous = original.get(task.id)
            if previous is None:
                changes.append({"task_id": task.id, "title": task.title, "kind": "added", "fields": []})
                continue
            before = planning_preview_task_fields(previous)
            after = planning_preview_task_fields(task)
            fields = [name for name in before if before[name] != after[name]]
            protected = fields and not planning_task_editable(state, previous)
            changes.append({
                "task_id": task.id,
                "title": task.title,
                "kind": "review_required" if protected else "modified" if fields else "unchanged",
                "fields": fields,
                "reason": "완료·실행 중이거나 보존해야 하는 Task입니다. 새 후속 Task로 계획해 주세요." if protected else "",
            })
        for task in state.tasks:
            if task.id in proposed:
                continue
            dependents = [candidate.id for candidate in plan.tasks if task.id in candidate.dependencies]
            protected = not planning_task_editable(state, task) or bool(dependents)
            changes.append({
                "task_id": task.id,
                "title": task.title,
                "kind": "review_required" if protected else "excluded",
                "fields": [],
                "reason": (
                    f"선행 Task로 참조 중입니다: {', '.join(dependents)}" if dependents
                    else "기존 실행 결과가 있는 Task는 제외할 수 없습니다." if protected else ""
                ),
            })
        return changes

    def read(self, run_id: str) -> dict[str, object] | None:
        state = self.records.load_run(run_id)
        preview = self.records.load_candidate(run_id)
        if preview is None:
            return None
        validate_planning_preview_payload(preview)
        return self.public(state, preview)

    def public(self, state: RunState, preview: dict[str, object]) -> dict[str, object]:
        result = {key: value for key, value in preview.items() if key not in {"plan", "schema_version"}}
        result["stale"] = self.fingerprint(state) != preview.get("fingerprint")
        request = planning_apply_request(state, str(preview.get("request_id", "")))
        if request is not None and request.status == PlanningApplyStatus.SUCCEEDED:
            result["status"] = "applied"
            result["actual"] = {
                "added": request.added_tasks,
                "modified": request.updated_tasks,
                "excluded": request.excluded_tasks,
                "unchanged": request.unchanged_tasks,
            }
        return result

    def status(self, run_id: str) -> dict[str, object]:
        run_before = self.records.run_lock(run_id)
        chat_before = self.records.chat_lock(run_id)
        state = self.records.load_run(run_id)
        stored_preview = self.records.load_candidate(run_id)
        if stored_preview is not None:
            validate_planning_preview_payload(stored_preview)
        preview = self.public(state, stored_preview) if stored_preview is not None else None
        progress = self.records.load_progress(run_id) or {}
        run_after = self.records.run_lock(run_id)
        chat_after = self.records.chat_lock(run_id)
        locks = (run_after, chat_after)
        phase = "idle"
        error = ""
        last_activity = ""
        request_id = ""
        if (run_before != run_after or chat_before != chat_after
                or any(lock.state not in {RunLockState.UNLOCKED, RunLockState.ACTIVE, RunLockState.STALE} for lock in locks)):
            phase, error = "check_required", "기획 작업의 소유 상태를 확인하지 못했습니다."
        elif any(lock.state == RunLockState.STALE for lock in locks):
            phase, error = "interrupted", "기획 작업의 소유 프로세스가 종료됐습니다. 저장 결과를 확인한 뒤 다시 작성해 주세요."
        elif chat_after.state == RunLockState.ACTIVE:
            if chat_after.operation == "planning-preview":
                phase = "generating"
                if progress.get("started_at") == chat_after.acquired_at and progress.get("owner_pid") == chat_after.pid:
                    recorded_phase = str(progress.get("phase", "generating"))
                    phase = recorded_phase if recorded_phase in {"generating", "comparing"} else "comparing"
                    last_activity = str(progress.get("last_activity_at", ""))
                    request_id = str(progress.get("request_id", ""))
            else:
                phase = "chat"
        elif run_after.state == RunLockState.ACTIVE or state.active_step == RunStep.PLANNING:
            phase = "chat" if run_after.operation.startswith("planning") else "check_required"
            error = "" if phase == "chat" else "현재 그룹 작업이 진행 중입니다. 종료 후 상태를 확인해 주세요."
        elif preview is not None and (
            not preview.get("stale") or (preview.get("status") == "applied"
                                        and state.planning_conversation_revision <= state.planning_applied_conversation_revision)
        ):
            phase = "applied" if preview.get("status") == "applied" else "ready"
        elif progress.get("phase") == "failed" and progress.get("fingerprint") == self.fingerprint(state):
            phase, error = "failed", str(progress.get("error", "후보 작성에 실패했습니다."))
            last_activity = str(progress.get("last_activity_at", ""))
            request_id = str(progress.get("request_id", ""))
        uncertain = phase == "check_required" and (run_before != run_after or chat_before != chat_after
            or any(lock.state not in {RunLockState.UNLOCKED, RunLockState.ACTIVE, RunLockState.STALE} for lock in locks))
        operations = [] if uncertain or phase == "interrupted" else planning_preview_operations(state, run_after, chat_after, progress)
        work_state = "unknown" if uncertain else "interrupted" if phase == "interrupted" else "active" if operations else "idle"
        if (state.active_step is not None or any(task.active_action is not None for task in state.tasks)) and not operations and work_state == "idle":
            work_state = "unknown"
            phase, error = "check_required", "작업 단계는 남아 있지만 실행 소유 상태를 확인하지 못했습니다."
        if operations:
            last_activity = max(str(item["last_activity_at"]) for item in operations)
            if phase == "check_required":
                error = ""
        can_apply = bool(work_state == "idle" and phase == "ready" and preview and preview.get("can_apply")
                         and not preview.get("stale") and preview.get("status") == "preview")
        eligible = state.repository_intent != "new_project" and (
            state.stage in {Stage.NEEDS_CLARIFICATION, Stage.PLANNED, Stage.EXECUTING, Stage.READY_TO_MERGE}
            or (state.stage == Stage.FAILED and state.failed_step in {RunStep.PLANNING, RunStep.AGENT_EXECUTION})
        )
        return {
            "phase": phase, "preview": preview if phase in {"ready", "applied"} or work_state == "active" else None,
            "request_id": request_id, "last_activity_at": last_activity, "checked_at": utc_now(),
            "error": error, "lock_state": chat_after.state.value,
            "work_state": work_state, "active_operations": operations, "can_apply": can_apply,
            "can_generate": bool(eligible and work_state in {"idle", "interrupted"}
                                 and phase in {"idle", "failed", "interrupted"} and state.active_step is None
                                 and run_after.state == RunLockState.UNLOCKED
                                 and chat_after.state in {RunLockState.UNLOCKED, RunLockState.STALE}
                                 and (state.planning_conversation_revision > state.planning_applied_conversation_revision
                                      or state.planning_follow_up_requests)),
        }

    def create(self, run_id: str, *, request_id: str) -> dict[str, object]:
        normalized_id = self.normalize_request_id(request_id)
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", normalized_id):
            raise PipelineError("Planning 미리보기 요청 ID가 올바르지 않습니다.")
        state = self.records.load_run(run_id)
        if state.repository_intent == "new_project":
            raise PipelineError("신규 프로젝트의 기술 구성·초기화 계획은 전용 확인 단계에서 진행해 주세요.")
        if state.active_step == RunStep.PLANNING or state.stage not in {
            Stage.NEEDS_CLARIFICATION, Stage.PLANNED, Stage.EXECUTING, Stage.FAILED, Stage.READY_TO_MERGE,
        }:
            raise PipelineError("현재 단계에서는 Planning 변경 미리보기를 만들 수 없습니다.")
        if state.stage == Stage.FAILED and state.failed_step not in {RunStep.PLANNING, RunStep.AGENT_EXECUTION}:
            raise PipelineError("현재 실패 단계에서는 Task 변경 미리보기를 만들 수 없습니다.")
        if state.planning_conversation_revision <= state.planning_applied_conversation_revision and not state.planning_follow_up_requests:
            raise PipelineError("Task에 반영할 새 Planning 대화 내용이 없습니다.")
        fingerprint = self.fingerprint(state)
        previous = self.records.load_candidate(run_id)
        if previous is not None:
            validate_planning_preview_payload(previous)
            if previous.get("fingerprint") == fingerprint and (
                previous.get("request_id") == normalized_id or previous.get("status") == "preview" and previous.get("can_apply")
            ):
                return self.public(state, previous)
            if previous.get("request_id") == normalized_id:
                raise PipelineError("같은 요청 ID를 변경된 대화·계획에 다시 사용할 수 없습니다.")
        snapshot = deepcopy(state)
        if state.stage in {Stage.EXECUTING, Stage.FAILED, Stage.READY_TO_MERGE} and state.tasks:
            follow_up = self.follow_up_request(snapshot)
            if follow_up not in snapshot.planning_follow_up_requests:
                snapshot.planning_follow_up_requests.append(follow_up)
        directions = [item for item in state.direction_change_requests if item.status != DirectionChangeStatus.APPLIED]
        for item in directions:
            item.status = DirectionChangeStatus.REVIEWING
            item.error = ""
            item.updated_at = utc_now()
        if directions:
            self.records.save_chat(state)
        try:
            plan = self.build_plan(
                snapshot,
                Path(state.spec_snapshot_path).read_text(encoding="utf-8"),
                clarification_context=self.clarification_context(snapshot),
                source_index=self.source_index(snapshot),
                preview_id=normalized_id,
            )
        except self.generation_errors as exc:
            for item in directions:
                item.status = DirectionChangeStatus.QUEUED
                item.error = str(exc)
                item.next_step = "미리보기 생성 오류를 확인한 뒤 다시 시도"
                item.updated_at = utc_now()
            if directions:
                self.records.save_chat(state)
            raise
        for item in directions:
            item.status = DirectionChangeStatus.QUEUED
            item.updated_at = utc_now()
        if directions:
            self.records.save_chat(state)
        if plan.questions or plan.tech_stack_options:
            raise PipelineError("추가 질문이나 기술 구성 선택은 Planning 대화에서 먼저 완료해 주세요.")
        progress = self.records.load_progress(run_id) or {}
        progress.update(phase="comparing", updated_at=utc_now(), phase_started_at=utc_now())
        self.records.save_progress(run_id, progress)
        changes = self.changes(state, plan)
        protected_in_initial_plan = state.stage in {Stage.PLANNED, Stage.NEEDS_CLARIFICATION} and any(
            not planning_task_editable(state, task) for task in state.tasks
        )
        blocked = protected_in_initial_plan or any(item["kind"] == "review_required" for item in changes)
        if not blocked:
            validate_task_graph(plan.tasks)
        if self.fingerprint(self.records.load_run(run_id)) != fingerprint:
            raise PipelineError("미리보기 생성 중 대화·계획이 변경되었습니다. 다시 생성해 주세요.")
        plan_payload = asdict(plan)
        candidate_digest = hashlib.sha256(json.dumps(plan_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        active = bool(state.active_step is not None or any(task.active_action for task in state.tasks))
        changed_task_ids = {str(item["task_id"]) for item in changes if item["kind"] != "unchanged"}
        task_evidence = {task.id: task for task in [*state.tasks, *plan.tasks]}
        preview: dict[str, object] = {
            "preview_id": normalized_id,
            "request_id": normalized_id,
            "run_id": run_id,
            "run_title": state.summary,
            "created_at": utc_now(),
            "plan_revision": state.plan_revision,
            "conversation_revision": state.planning_conversation_revision,
            "fingerprint": fingerprint,
            "candidate_digest": candidate_digest,
            "changes": changes,
            "can_apply": not active and not blocked,
            "apply_after": "현재 Task 종료 후 미리보기 다시 생성" if active else "보존할 Task를 새 후속 Task로 계획" if blocked else "지금",
            "dependency_impact": any(
                "depends_on" in item["fields"]
                or (item["kind"] in {"added", "excluded"} and bool(task_evidence[str(item["task_id"])].dependencies))
                for item in changes
            ),
            "verification_impact": any(
                "verify_commands" in item["fields"]
                or (item["kind"] in {"added", "excluded"} and bool(task_evidence[str(item["task_id"])].verify_commands))
                for item in changes
            ),
            "completed_task_rerun": False,
            "completed_task_review": any(
                task.id in changed_task_ids and task.status in {TaskStatus.COMPLETED, TaskStatus.MERGED} for task in state.tasks
            ),
            "direction_request_ids": [item.request_id for item in directions],
            "status": "preview",
            "plan": plan_payload,
        }
        self.records.save_candidate(run_id, preview)
        for item in directions:
            item.status = (
                DirectionChangeStatus.QUEUED if active else
                DirectionChangeStatus.BLOCKED if blocked else DirectionChangeStatus.AWAITING_CONFIRMATION
            )
            item.preview_id = normalized_id
            item.next_step = (
                "현재 실행 묶음 종료 후 새 미리보기 확인" if active else
                "보존할 Task를 새 후속 Task로 계획" if blocked else "이 변경 반영 확인 대기"
            )
            item.error = "보존할 Task를 직접 변경할 수 없습니다." if blocked else ""
            item.updated_at = utc_now()
        if directions:
            self.records.save_chat(state)
        return self.public(state, preview)
