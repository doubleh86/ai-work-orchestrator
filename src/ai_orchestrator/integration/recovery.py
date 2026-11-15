"""Recovery candidates and operation receipts under caller-owned locks."""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from ..errors import PipelineError
from ..git import GitWorkspace, LOCAL_GIT_TIMEOUT_SECONDS
from ..models import OperationRecord, RunLockState, RunLockStatus, RunState, Stage, TaskStatus, WorkTask


class RecoveryWorkspaceClean(Protocol):
    def __call__(self, worktree: Path, *, timeout_seconds: float) -> None: ...


@dataclass(frozen=True, slots=True)
class RecoveryRecords:
    load_run: Callable[[str], RunState]
    list_runs: Callable[[], list[RunState]]
    claim: Callable[[OperationRecord], tuple[OperationRecord, bool]]
    load: Callable[[str, str], OperationRecord | None]
    save: Callable[[OperationRecord], None]
    load_result: Callable[[OperationRecord], dict[str, object] | None]
    save_result: Callable[[str, str, dict[str, object]], str]
    inspect_lock: Callable[[str], RunLockStatus]
    latest: Callable[[str, str], OperationRecord | None]


def recovery_operation_digest(payload: dict[str, object]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def raise_existing_recovery_operation(operation: OperationRecord) -> None:
    if operation.status == "running":
        raise PipelineError(f"동일한 복구 요청이 진행 중입니다: {operation.request_id} ({operation.phase})")
    if operation.status == "partial":
        raise PipelineError(f"복구 결과가 부분 적용됐습니다. 재계획을 다시 시도해 주세요: {operation.request_id}")
    raise PipelineError(operation.error or f"이전 복구 요청이 {operation.status} 상태입니다: {operation.phase}")


@dataclass(frozen=True, slots=True)
class RecoveryWorkflow:
    git: GitWorkspace
    repo: Path
    records: RecoveryRecords
    shared_boundary: Callable[[RunState], tuple[str, Path]]
    ensure_clean: RecoveryWorkspaceClean
    task_draft: Callable[[WorkTask], dict[str, object]]
    uses_shared_workspace: Callable[[RunState], bool]

    def plan(self, state: RunState, *, progress_callback: Callable[[str], None] | None = None) -> dict[str, object]:
        if state.stage != Stage.FAILED or not self.uses_shared_workspace(state):
            raise PipelineError("자동 복구안은 실패한 공유 작업 그룹에서 생성할 수 있습니다.")
        if any(task.active_action or task.status in {TaskStatus.RUNNING, TaskStatus.REVIEWING, TaskStatus.REVISING} for task in state.tasks):
            raise PipelineError("실행 중인 Task가 있어 복구할 수 없습니다.")
        if progress_callback is not None:
            progress_callback("collecting_sources")
        deadline = time.monotonic() + 45.0

        def remaining(step: str) -> float:
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise PipelineError(f"복구안 조회 제한 시간(45초)을 초과했습니다. 마지막 단계: {step}. 복구는 적용되지 않았습니다.")
            return min(LOCAL_GIT_TIMEOUT_SECONDS, seconds)

        branch, worktree = self.shared_boundary(state)
        registered = self.git.list_worktrees(non_interactive=True, timeout_seconds=remaining("작업공간 등록 확인"))
        if not any(item.path.resolve() == worktree and item.branch == branch for item in registered):
            raise PipelineError("현재 그룹의 등록된 작업 branch를 확인할 수 없습니다.")
        self.ensure_clean(worktree, timeout_seconds=remaining("미커밋 변경 확인"))
        baseline = self.git.head(worktree, non_interactive=True, timeout_seconds=remaining("현재 commit 확인"))
        ancestors: dict[str, bool] = {}
        sources: list[dict[str, object]] = []
        for source in self.records.list_runs():
            remaining("다른 그룹 결과 조회")
            if source.id == state.id or Path(source.repo_path).resolve() != self.repo.resolve():
                continue
            if source.active_step or any(
                task.active_action or task.status in {TaskStatus.RUNNING, TaskStatus.REVIEWING, TaskStatus.REVISING} for task in source.tasks
            ):
                continue
            completed = [
                task
                for task in source.tasks
                if task.status in {TaskStatus.COMPLETED, TaskStatus.MERGED} and re.fullmatch(r"[0-9a-f]{40}", task.completed_commit)
            ]
            missing = []
            for task in completed:
                if task.completed_commit not in ancestors:
                    ancestors[task.completed_commit] = self.git.contains_branch(
                        worktree, task.completed_commit, non_interactive=True, timeout_seconds=remaining("선행 commit 비교")
                    )
                if not ancestors[task.completed_commit]:
                    missing.append(task)
            if not missing:
                continue
            sources.append(
                {
                    "run_id": source.id,
                    "summary": source.summary,
                    "commits": list(dict.fromkeys(task.completed_commit for task in missing)),
                    "completed_tasks": [task.title for task in missing],
                    "pending_tasks": [self.task_draft(task) for task in source.tasks if task.status in {TaskStatus.PENDING, TaskStatus.FAILED}],
                }
            )
        remaining("복구안 정리")
        details = [
            {
                "id": task.id,
                "title": task.title,
                "error": task.error,
                "response": (task.action_results[-1].worker_response[-4000:] if task.action_results else ""),
            }
            for task in state.tasks
            if task.status == TaskStatus.FAILED
        ]
        plan: dict[str, object] = {
            "run_id": state.id,
            "baseline": baseline,
            "worktree": str(worktree),
            "failure": state.failure_message,
            "failed_tasks": details,
            "sources": sources,
            "queued_requests": state.planning_follow_up_requests,
            "tasks": [self.task_draft(task) for task in state.tasks],
            "task_states": [[task.id, task.status.value, task.started_commit, task.completed_commit] for task in state.tasks],
        }
        plan["fingerprint"] = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        return plan

    def claim(
        self,
        state: RunState,
        action: str,
        request_id: str,
        payload: dict[str, object],
        phase: str,
        *,
        resume_request_id: str = "",
    ) -> tuple[OperationRecord, bool]:
        try:
            normalized = str(uuid.UUID(request_id.strip())) if request_id else str(uuid.uuid4())
        except ValueError as exc:
            raise PipelineError("requestId는 UUID 형식이어야 합니다.") from exc
        operation = OperationRecord(
            request_id=normalized,
            run_id=state.id,
            action=action,
            digest=recovery_operation_digest(payload),
            phase=phase,
            resume_request_id=resume_request_id,
        )
        existing, created = self.records.claim(operation)
        if not created and (existing.action != action or existing.digest != operation.digest):
            raise PipelineError("requestId가 다른 복구 요청이나 입력에 사용되었습니다.")
        return existing, created

    def preview_input(self, state: RunState) -> dict[str, object]:
        return {
            "run_id": state.id,
            "stage": state.stage.value,
            "updated_at": state.updated_at,
            "failure": state.failure_message,
            "plan_revision": state.plan_revision,
            "queued_requests": state.planning_follow_up_requests,
            "tasks": [
                {
                    "plan": self.task_draft(task),
                    "status": task.status.value,
                    "error": task.error,
                    "started_commit": task.started_commit,
                    "completed_commit": task.completed_commit,
                }
                for task in state.tasks
            ],
        }

    def replay(self, operation: OperationRecord) -> dict[str, object] | None:
        if operation.status == "succeeded":
            result = self.records.load_result(operation)
            if result is None:
                raise PipelineError("완료된 복구안 조회 요청에 결과 snapshot이 없습니다.")
            return result
        raise_existing_recovery_operation(operation)
        return None

    def payload(self, operation: OperationRecord) -> dict[str, object]:
        payload = operation.to_dict()
        payload["result"] = self.records.load_result(operation)
        payload["lock_state"] = self.records.inspect_lock(operation.run_id).state.value
        return payload

    def reconcile(self, operation: OperationRecord) -> None:
        if operation.status != "running":
            return
        lock = self.records.inspect_lock(operation.run_id)
        expected_lock_operation = "recovery-preview" if operation.action == "recovery_preview" else "recovery-apply"
        if lock.state == RunLockState.ACTIVE and lock.operation == expected_lock_operation:
            return
        if lock.state in {RunLockState.UNVERIFIABLE, RunLockState.MALFORMED}:
            return
        if operation.action == "recovery_apply" and operation.phase == "replanning" and operation.result_commit:
            operation.update(
                operation.phase,
                status="partial",
                error="완료 결과 통합 뒤 실행 프로세스가 종료되어 Task 재계획 결과를 확인하지 못했습니다.",
                error_code="replanning_interrupted",
            )
            self.records.save(operation)
            return
        operation.update(
            operation.phase,
            status="interrupted",
            error="복구 요청을 실행한 프로세스가 종료되어 최종 결과를 확인하지 못했습니다.",
            error_code="operation_interrupted",
        )
        self.records.save(operation)

    def resume_replanning(
        self, state: RunState, operation: OperationRecord, fingerprint: str, source_ids: list[str]
    ) -> str:
        try:
            resume_id = str(uuid.UUID(operation.resume_request_id.strip()))
        except ValueError as exc:
            raise PipelineError("resumeRequestId는 UUID 형식이어야 합니다.") from exc
        previous = self.records.load(state.id, resume_id)
        if previous is None or previous.action != "recovery_apply" or previous.status != "partial":
            raise PipelineError("재개할 부분 적용 복구 요청을 찾을 수 없습니다.")
        result = self.records.load_result(previous)
        if result is None:
            raise PipelineError("부분 적용 복구 요청의 통합 결과가 없습니다.")
        if result.get("fingerprint") != fingerprint or result.get("source_ids") != list(dict.fromkeys(source_ids)):
            raise PipelineError("재계획 재시도 입력이 부분 적용된 복구안과 일치하지 않습니다.")
        integrated = str(result.get("result_commit", ""))
        _, worktree = self.shared_boundary(state)
        if not integrated or self.git.head(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS) != integrated:
            raise PipelineError("부분 적용 뒤 작업 commit이 변경됐습니다. 새 복구안을 검토해 주세요.")
        operation.result_commit = integrated
        operation.result_ref = self.records.save_result(
            state.id,
            operation.request_id,
            {"fingerprint": fingerprint, "source_ids": list(dict.fromkeys(source_ids)), "result_commit": integrated},
        )
        return integrated

    def fail(self, operation: OperationRecord, error: Exception) -> None:
        if operation.status == "partial":
            return
        operation.update(operation.phase, status="failed", error=str(error), error_code=type(error).__name__)
        self.records.save(operation)

    def operation(self, run_id: str, request_id: str) -> dict[str, object]:
        self.records.load_run(run_id)
        try:
            normalized = str(uuid.UUID(request_id.strip()))
        except ValueError as exc:
            raise PipelineError("requestId는 UUID 형식이어야 합니다.") from exc
        operation = self.records.load(run_id, normalized)
        if operation is None:
            raise PipelineError(f"복구 요청 기록을 찾을 수 없습니다: {normalized}")
        self.reconcile(operation)
        return self.payload(operation)

    def latest(self, run_id: str, kind: str) -> dict[str, object] | None:
        state = self.records.load_run(run_id)
        if kind not in {"recovery_preview", "recovery_apply"}:
            raise PipelineError(f"지원하지 않는 복구 요청 종류입니다: {kind}")
        operation = self.records.latest(run_id, kind)
        if operation is None:
            return None
        if kind == "recovery_preview" and operation.digest != recovery_operation_digest(self.preview_input(state)):
            return None
        self.reconcile(operation)
        return self.payload(operation)
