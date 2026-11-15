from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable

from .models import (
    DirectionChangeStatus, ExecutionControlRecord, RunExecutionAction, RunExecutionControl, RunExecutionSituation,
    RunLockState, RunLockStatus, RunState, RunStep, Stage, TaskStatus,
)


@dataclass(frozen=True, slots=True)
class BranchSnapshot:
    branch: str = ""
    error: str | None = None


def run_execution_control(
    state: RunState, lock: RunLockStatus, execution_record: ExecutionControlRecord | None = None,
    *, waiting_for_user_checks: Callable[[], bool], read_branch: Callable[[], BranchSnapshot],
    deferred_task_ids: Callable[[], set[str]], has_main_push_recovery: Callable[[], bool],
    uses_shared_workspace: Callable[[], bool],
) -> RunExecutionControl:
    active_task = next(
        (
            task
            for task in state.tasks
            if task.active_action or task.status in {TaskStatus.RUNNING, TaskStatus.REVIEWING, TaskStatus.REVISING}
        ),
        None,
    )
    details = {
        "lock_state": lock.state,
        "operation": lock.operation,
        "active_task_id": active_task.id if active_task else "",
        "active_task_title": active_task.title if active_task else "",
        "execution_id": execution_record.execution_id if execution_record else "",
        "active_attempt_id": execution_record.attempt_id if execution_record else "",
        "active_invocation_id": execution_record.invocation_id if execution_record else "",
        "can_stop": bool(
            execution_record
            and execution_record.phase == "running"
            and lock.state == RunLockState.ACTIVE
            and execution_record.scope in {"task", "verification"}
        ),
        "stop_scope": execution_record.scope if execution_record else "",
        "stop_request_id": execution_record.stop_request_id if execution_record else "",
        "stop_phase": execution_record.phase if execution_record else "",
        "dispatch_paused": execution_record.dispatch_paused if execution_record else False,
    }
    if execution_record and execution_record.task_id:
        details["active_task_id"] = execution_record.task_id
        details["active_task_title"] = execution_record.task_title
    if lock.state == RunLockState.ACTIVE:
        if execution_record and execution_record.phase == "stopping":
            return RunExecutionControl(
                situation=RunExecutionSituation.RUNNING,
                action=RunExecutionAction.NONE,
                reason="중지 요청을 접수했고 실행 종료와 작업 보존을 확인하고 있습니다.",
                **details,
            )
        if active_task:
            return RunExecutionControl(
                situation=RunExecutionSituation.RUNNING,
                action=RunExecutionAction.NONE,
                reason=f"{active_task.title} 작업이 진행 중입니다.",
                **details,
            )
        if state.active_step == RunStep.AGENT_EXECUTION:
            return RunExecutionControl(
                situation=RunExecutionSituation.PREPARING,
                action=RunExecutionAction.NONE,
                reason="그룹 실행이 다음 작업을 준비하고 있습니다.",
                **details,
            )
        return RunExecutionControl(
            situation=RunExecutionSituation.RUNNING,
            action=RunExecutionAction.NONE,
            reason="그룹 작업이 진행 중입니다.",
            **details,
        )
    if lock.state == RunLockState.STALE:
        return RunExecutionControl(
            situation=RunExecutionSituation.ATTENTION_REQUIRED,
            action=RunExecutionAction.NONE,
            reason="중단된 실행 잠금이 있습니다. 통합·정리에서 잠금 상태를 확인해 주세요.",
            **details,
        )
    if lock.state in {RunLockState.UNVERIFIABLE, RunLockState.MALFORMED}:
        return RunExecutionControl(
            situation=RunExecutionSituation.STATUS_UNKNOWN,
            action=RunExecutionAction.NONE,
            reason="실행 잠금 상태를 확인할 수 없습니다. 상태를 다시 확인해 주세요.",
            **details,
        )
    if execution_record and execution_record.phase == "confirmation_required":
        return RunExecutionControl(
            situation=RunExecutionSituation.STATUS_UNKNOWN,
            action=RunExecutionAction.NONE,
            reason="중지 뒤 실행 종료 또는 작업 보존을 확인하지 못했습니다. 상태를 다시 확인해 주세요.",
            **details,
        )
    if state.stage in {Stage.READY_TO_MERGE, Stage.VERIFIED, Stage.WORK_BRANCH_PUSHED, Stage.MERGED, Stage.PUSHED, Stage.DEPLOYED}:
        return RunExecutionControl(
            situation=RunExecutionSituation.TASKS_COMPLETE,
            action=RunExecutionAction.NONE,
            reason="Task 실행이 끝났습니다. 통합·정리에서 다음 단계를 확인해 주세요.",
            **details,
        )
    if (state.stage in {Stage.PLANNED, Stage.EXECUTING} and state.plan_is_approved
            and not state.active_execution_request_id and waiting_for_user_checks()):
        return RunExecutionControl(
            situation=RunExecutionSituation.WAITING_USER_CHECK, action=RunExecutionAction.NONE,
            reason="다음 작업이나 통합에 필요한 사용자 확인을 기록해 주세요.", **details,
        )
    branch_sensitive_failure = state.stage == Stage.FAILED and state.failed_step in {
        RunStep.AGENT_EXECUTION, RunStep.MANUAL_COMPLETION, RunStep.VERIFY, RunStep.PUSH, RunStep.MERGE,
    }
    if (state.stage in {Stage.PLANNED, Stage.EXECUTING} and (state.stage != Stage.PLANNED or state.plan_is_approved)) or branch_sensitive_failure:
        branch = read_branch()
        if branch.error is not None:
            return RunExecutionControl(
                situation=RunExecutionSituation.STATUS_UNKNOWN,
                action=RunExecutionAction.NONE,
                reason=f"원본 체크아웃 branch를 확인하지 못했습니다: {branch.error}",
                **details,
            )
        if branch.branch != state.main_branch:
            return RunExecutionControl(
                situation=RunExecutionSituation.UNAVAILABLE,
                action=RunExecutionAction.NONE,
                reason="현재 체크아웃된 branch가 Main이 아닙니다. Main으로 돌아온 뒤 Task 실행·재개를 다시 확인하세요.",
                **details,
            )
    if execution_record and execution_record.phase == "stopped" and state.stage in {Stage.PLANNED, Stage.EXECUTING}:
        return RunExecutionControl(
            situation=RunExecutionSituation.RESUMABLE,
            action=RunExecutionAction.RESUME,
            reason="사용자가 실행을 중지했습니다. 변경과 로그를 보존했으며 그룹을 재개할 수 있습니다.",
            **details,
        )
    if state.stage == Stage.PLANNED:
        if not state.plan_is_approved:
            return RunExecutionControl(
                situation=RunExecutionSituation.UNAVAILABLE,
                action=RunExecutionAction.NONE,
                reason="Task 내용을 확인하고 계획을 확정해 주세요.",
                **details,
            )
        if not state.tasks:
            return RunExecutionControl(
                situation=RunExecutionSituation.UNAVAILABLE,
                action=RunExecutionAction.NONE,
                reason="실행할 Task가 없습니다.",
                **details,
            )
        return RunExecutionControl(
            situation=RunExecutionSituation.READY,
            action=RunExecutionAction.EXECUTE,
            reason="준비된 Task를 실행할 수 있습니다.",
            **details,
        )
    if state.stage == Stage.EXECUTING:
        deferred = deferred_task_ids()
        if deferred and not any(task.id not in deferred and task.status in {TaskStatus.PENDING, TaskStatus.WAITING, TaskStatus.STOPPED}
                                for task in state.tasks):
            return RunExecutionControl(
                situation=RunExecutionSituation.RESUMABLE,
                action=RunExecutionAction.NONE,
                reason="보류한 수동 작업을 다시 열어 검증을 이어갈 수 있습니다.",
                **details,
            )
        return RunExecutionControl(
            situation=RunExecutionSituation.RESUMABLE,
            action=RunExecutionAction.RESUME,
            reason="현재 실행 잠금이 없습니다. 중단된 지점부터 그룹을 재개할 수 있습니다.",
            **details,
        )
    if state.stage == Stage.FAILED:
        if has_main_push_recovery():
            return RunExecutionControl(
                situation=RunExecutionSituation.UNAVAILABLE,
                action=RunExecutionAction.NONE,
                reason="로컬 Main 반영은 완료됐습니다. 통합·정리에서 원격 Main Push 상태를 확인하세요.",
                **details,
            )
        resumable_steps = {RunStep.AGENT_EXECUTION, RunStep.MANUAL_COMPLETION, RunStep.VERIFY, RunStep.PUSH, RunStep.DEPLOY}
        if uses_shared_workspace():
            resumable_steps.add(RunStep.MERGE)
        if state.failed_step in resumable_steps:
            return RunExecutionControl(
                situation=RunExecutionSituation.RESUMABLE,
                action=RunExecutionAction.RESUME,
                reason="실패 근거를 확인한 뒤 현재 그룹을 재개할 수 있습니다.",
                **details,
            )
        reason = (
            "Planning 탭에서 실패 내용을 확인하고 요청을 수정해 주세요."
            if state.failed_step == RunStep.PLANNING
            else "이 실패 단계는 그룹 재개를 지원하지 않습니다. 실패 근거를 확인해 주세요."
        )
        return RunExecutionControl(
            situation=RunExecutionSituation.ATTENTION_REQUIRED,
            action=RunExecutionAction.NONE,
            reason=reason,
            **details,
        )
    return RunExecutionControl(
        situation=RunExecutionSituation.UNAVAILABLE,
        action=RunExecutionAction.NONE,
        reason="현재 단계에서는 Task를 실행할 수 없습니다.",
        **details,
    )


def planned_user_checks(state: RunState, *, include_notes: bool = False) -> list[dict[str, object]]:
    checks: list[dict[str, object]] = []
    for check in state.user_check_plan:
        reference = state.user_check_reference(check)
        result = state.current_user_check_result(check)
        checks.append({
            **asdict(check), "check_id": check.id, "kind": "planned_check",
            "status": result.outcome.value if result else "waiting" if reference else "pending",
            "reference_commit": reference or None, "recorded_at": result.recorded_at if result else None,
            **({"note": result.note if result else ""} if include_notes else {}),
        })
    return checks


def user_checks(state: RunState, *, include_recorded: bool = False) -> list[dict[str, object]]:
    """Report saved manual work and evidence for the current task result."""
    checks = [check for check in planned_user_checks(state)
              if include_recorded or (state.archive is None and state.plan_is_approved and check["status"] in {"waiting", "failed", "deferred"})]
    for task in state.tasks:
        recorded_at = None
        if state.archive is None and task.status in {TaskStatus.WAITING, TaskStatus.DEFERRED}:
            status = task.status.value
            reference_commit = task.started_commit
        elif include_recorded and task.status in {TaskStatus.COMPLETED, TaskStatus.MERGED} and task.result_history:
            result = task.result_history[-1]
            if not task.completed_commit or result.result_commit != task.completed_commit or not result.manual_verification_note:
                continue
            status = "verification_recorded"
            reference_commit = result.result_commit
            recorded_at = result.captured_at
        else:
            continue
        checks.append({
            "task_id": task.id, "title": task.title, "status": status,
            "instructions": task.description, "acceptance_criteria": task.acceptance_criteria,
            "reference_commit": reference_commit or None, "recorded_at": recorded_at,
        })
    return checks


def attention_decision(
    state: RunState, control: RunExecutionControl, *, remote_configured: bool, deployment_configured: bool,
) -> tuple[str, str, str, str, str] | None:
    if state.stage == Stage.NEEDS_CLARIFICATION:
        return ("planning_questions", "기획 질문에 답변", "계획을 이어가려면 질문에 답변해야 합니다.", "planning", "")
    if state.stage == Stage.FAILED and state.failed_step == RunStep.PLANNING:
        return ("planning_recovery", "기획 실패 확인", state.failure_message or "기획을 다시 확인해야 합니다.", "planning", "")
    if state.stage == Stage.FAILED:
        task = next((task for task in state.tasks if task.status == TaskStatus.FAILED), None)
        view = "tasks" if task else "operations"
        reason = state.failure_message or (task.error if task else "") or "실패 근거와 복구 방법을 확인하세요."
        return ("failure_recovery", "실패 복구 검토", reason, view, task.id if task else "")
    if control.situation == RunExecutionSituation.WAITING_USER_CHECK:
        return ("user_check", "사용자 확인 대기", control.reason, "tasks", "")
    waiting = next((task for task in state.tasks if task.status == TaskStatus.WAITING), None)
    if waiting:
        return ("manual_completion", "수동 작업 확인", f"{waiting.title}의 수동 작업과 완료 조건을 확인하세요.", "tasks", waiting.id)
    direction = next((item for item in reversed(state.direction_change_requests) if item.status != DirectionChangeStatus.APPLIED), None)
    if direction:
        return ("direction_review", "방향 수정 검토", direction.error or "접수한 방향 수정의 변경 내용을 확인하세요.", "tasks", "")
    if state.stage == Stage.PLANNED:
        if not state.plan_is_approved:
            return ("plan_confirmation", "계획 확정 검토", "실행할 Task와 완료 조건을 확인한 뒤 계획을 확정하세요.", "tasks", "")
        if control.action != RunExecutionAction.EXECUTE:
            return ("status_check", "실행 상태 확인", control.reason, "tasks", "")
        return ("execution_start", "작업 실행 선택", "확정된 계획의 작업 실행을 시작할 수 있습니다.", "tasks", "")
    deferred = next((task for task in state.tasks if task.status == TaskStatus.DEFERRED), None)
    if deferred and control.situation == RunExecutionSituation.RESUMABLE and control.action == RunExecutionAction.NONE:
        return ("manual_completion", "수동 검증 보류", control.reason, "tasks", deferred.id)
    if control.situation == RunExecutionSituation.RESUMABLE:
        return ("resume", "그룹 재개 검토", control.reason, "tasks", "")
    if state.stage == Stage.READY_TO_MERGE:
        return ("verification", "통합 검증 확인", "Task 실행이 끝났습니다. 통합 검증을 확인하세요.", "operations", "")
    if state.stage in {Stage.VERIFIED, Stage.WORK_BRANCH_PUSHED}:
        return ("main_review", "검증 결과·Main 반영 검토", "검증 결과와 최신 Main 상태를 확인한 뒤 반영을 결정하세요.", "operations", "")
    if state.stage == Stage.MERGED and remote_configured:
        return ("main_push", "Main Push 검토", "Main 반영 결과와 원격 Push 상태를 확인하세요.", "operations", "")
    if deployment_configured and state.stage in {Stage.MERGED, Stage.PUSHED}:
        return ("deployment", "배포 검토", "완료된 변경과 배포 대상을 확인하세요.", "operations", "")
    if control.situation == RunExecutionSituation.ATTENTION_REQUIRED:
        return ("status_check", "실행 상태 확인", control.reason, "operations", "")
    return None


def active_group_kind(operation: str) -> str:
    if operation.startswith("planning") or operation in {"generate-feature-plan", "tech-stack-confirm"}:
        return "planning"
    if operation in {"execute", "resume", "retry-task", "execute-task", "complete-task"}:
        return "task"
    if operation in {"verify", "verify-and-repair"}:
        return "verification"
    if operation in {"push", "retry-main-push"}:
        return "push"
    if operation == "deploy":
        return "deployment"
    if operation in {"merge", "recover-main-apply"} or operation.startswith(("conflict-resolution", "recovery-")):
        return "integration"
    return "maintenance"


def summary_attention_reasons(
    state: RunState,
    control: RunExecutionControl,
    *,
    deployment_configured: bool,
    remote_configured: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if state.stage == Stage.NEEDS_CLARIFICATION:
        reasons.append("planning_questions")
    if state.stage == Stage.PLANNED and not state.plan_is_approved:
        reasons.append("plan_confirmation")
    if any(task.status in {TaskStatus.WAITING, TaskStatus.DEFERRED} for task in state.tasks) or state.failed_step == RunStep.MANUAL_COMPLETION:
        reasons.append("manual_completion")
    if control.situation == RunExecutionSituation.WAITING_USER_CHECK:
        reasons.append("user_check")
    if control.situation == RunExecutionSituation.RESUMABLE:
        reasons.append("resume")
    if state.stage == Stage.FAILED:
        reasons.append("failure_recovery")
    if control.situation == RunExecutionSituation.ATTENTION_REQUIRED:
        reasons.append("execution_attention")
    if control.situation == RunExecutionSituation.STATUS_UNKNOWN:
        reasons.append("status_unknown")
    local_completion = state.stage == Stage.MERGED and not remote_configured
    if state.stage in {Stage.READY_TO_MERGE, Stage.VERIFIED, Stage.WORK_BRANCH_PUSHED} or (state.stage == Stage.MERGED and not local_completion):
        reasons.append("integration")
    if deployment_configured and (state.stage == Stage.PUSHED or local_completion):
        reasons.append("deployment")
    return tuple(dict.fromkeys(reasons))
