from __future__ import annotations

import hashlib

from .models import ConflictResolutionStatus, RunState, Stage, TaskStatus, UserNotificationEvent, WorkTask


def retry_wait_event(
    state: RunState, project_key: str, task: WorkTask, request_id: str, *, completed: bool = False, occurred_at: str = "",
) -> UserNotificationEvent:
    code = "remaining_tasks_resume_required" if completed else "task_retry_required"
    commit = task.completed_commit if completed else ""
    return _event(
        state, project_key,
        source_key=f"task:{task.id}:{code}:{state.plan_revision}:{task.last_attempt_id}:{commit}:{request_id}",
        kind="attention_required", summary_code=code, target_kind="run" if completed else "task",
        target_id=state.id if completed else task.id, request_id=request_id, related_targets=[task.id],
        occurred_at=occurred_at or task.last_attempt_finished_at,
    )


def notification_events_for_state(state: RunState, *, project_key: str, deployment_configured: bool) -> list[UserNotificationEvent]:
    events: list[UserNotificationEvent] = []
    for task in state.tasks:
        if task.status in {TaskStatus.COMPLETED, TaskStatus.MERGED} and task.completed_commit:
            events.append(
                _event(
                    state,
                    project_key,
                    source_key=f"task:{task.id}:completed:{task.completed_commit}",
                    kind="completed",
                    summary_code="task_completed",
                    occurred_at=task.last_attempt_finished_at or state.updated_at,
                    target_kind="task",
                    target_id=task.id,
                    related_targets=[task.id],
                    os_eligible=False,
                )
            )
        if task.status == TaskStatus.WAITING:
            events.append(
                _task_attention_event(state, project_key, task, "manual_task_required", task.last_attempt_id or task.started_commit or "waiting")
            )
        if task.status == TaskStatus.STOPPED:
            events.append(_task_attention_event(state, project_key, task, "stopped_task_requires_action", task.stop_request_id or task.last_attempt_id))

    if state.stage == Stage.NEEDS_CLARIFICATION:
        events.append(
            _event(
                state,
                project_key,
                source_key=f"run:{state.id}:clarification:{state.plan_revision}:{state.planning_attempts}",
                kind="attention_required",
                summary_code="planning_clarification_required",
                target_kind="planning",
                target_id=state.id,
            )
        )
    elif state.stage == Stage.PLANNED and not state.plan_is_approved:
        events.append(
            _event(
                state,
                project_key,
                source_key=f"run:{state.id}:plan-confirmation:{state.plan_revision}",
                kind="attention_required",
                summary_code="plan_confirmation_required",
                target_kind="planning",
                target_id=state.id,
            )
        )
    elif state.stage == Stage.READY_TO_MERGE:
        events.append(
            _event(
                state,
                project_key,
                source_key=f"run:{state.id}:integration-required:{_completed_head_key(state)}",
                kind="attention_required",
                summary_code="integration_verification_required",
                target_kind="verification",
                target_id=state.id,
            )
        )
    elif state.stage == Stage.VERIFIED:
        summary_code = "work_branch_push_required" if state.workspace_mode.value == "shared" else "main_apply_required"
        events.append(
            _event(
                state,
                project_key,
                source_key=f"run:{state.id}:{summary_code}:{state.verified_integration_head}",
                kind="attention_required",
                summary_code=summary_code,
                target_kind="operations",
                target_id=state.id,
                verification_attempt_id=_latest_verification_attempt_id(state),
            )
        )
    elif state.stage == Stage.WORK_BRANCH_PUSHED:
        events.append(
            _event(
                state,
                project_key,
                source_key=f"run:{state.id}:main-apply:{state.pushed_work_branch_head}",
                kind="attention_required",
                summary_code="main_apply_required",
                target_kind="operations",
                target_id=state.id,
                verification_attempt_id=_latest_verification_attempt_id(state),
            )
        )
    elif state.stage == Stage.MERGED:
        events.append(
            _event(
                state,
                project_key,
                source_key=f"run:{state.id}:main-push:{state.verified_integration_head}",
                kind="attention_required",
                summary_code="main_push_required",
                target_kind="operations",
                target_id=state.id,
            )
        )
    elif state.stage == Stage.PUSHED:
        if deployment_configured:
            events.append(
                _event(
                    state,
                    project_key,
                    source_key=f"run:{state.id}:deployment:{state.verified_integration_head}",
                    kind="attention_required",
                    summary_code="deployment_approval_required",
                    target_kind="operations",
                    target_id=state.id,
                )
            )
        else:
            events.append(_group_completed_event(state, project_key))
    elif state.stage == Stage.DEPLOYED:
        events.append(_group_completed_event(state, project_key))
    elif state.stage == Stage.FAILED:
        events.append(_failure_event(state, project_key))
    return events


def synchronize_notification_events(
    state: RunState, *, project_key: str, deployment_configured: bool
) -> None:
    known = {event.source_key for event in state.notification_events}
    for event in notification_events_for_state(state, project_key=project_key, deployment_configured=deployment_configured):
        if event.source_key not in known:
            state.notification_events.append(event)
            known.add(event.source_key)
    state.notification_events.sort(key=lambda event: (event.occurred_at, event.event_id))


def _task_attention_event(
    state: RunState, project_key: str, task: WorkTask, summary_code: str, revision: str
) -> UserNotificationEvent:
    return _event(
        state,
        project_key,
        source_key=f"task:{task.id}:{summary_code}:{revision or state.updated_at}",
        kind="attention_required",
        summary_code=summary_code,
        occurred_at=task.stopped_at or task.last_attempt_finished_at or state.updated_at,
        target_kind="task",
        target_id=task.id,
        request_id=task.stop_request_id,
        related_targets=[task.id],
    )


def _failure_event(state: RunState, project_key: str) -> UserNotificationEvent:
    conflict = state.integration_conflict
    if conflict is not None and conflict.resolution_status not in {
        ConflictResolutionStatus.APPLIED,
        ConflictResolutionStatus.STALE,
    }:
        candidate = conflict.candidate
        if candidate is not None and conflict.resolution_status == ConflictResolutionStatus.CANDIDATE_READY:
            return _event(
                state,
                project_key,
                source_key=f"conflict:{conflict.id}:candidate:{candidate.id}:{candidate.revision}",
                kind="attention_required",
                summary_code="conflict_candidate_ready",
                occurred_at=candidate.created_at or state.updated_at,
                target_kind="conflict",
                target_id=conflict.id,
                request_id=candidate.request_id,
                verification_attempt_id=conflict.verification_attempt_id,
                related_targets=[item.path for item in conflict.files],
            )
        return _event(
            state,
            project_key,
            source_key=f"conflict:{conflict.id}:detected:{conflict.fingerprint}",
            kind="failed",
            summary_code="integration_conflict",
            occurred_at=conflict.detected_at or state.updated_at,
            target_kind="conflict",
            target_id=conflict.id,
            verification_attempt_id=conflict.verification_attempt_id,
            related_targets=[item.path for item in conflict.files],
        )

    task = next((item for item in reversed(state.tasks) if item.status == TaskStatus.FAILED), None)
    if task is not None:
        attempt = task.last_attempt_id or task.last_attempt_finished_at or state.updated_at
        return _event(
            state,
            project_key,
            source_key=f"task:{task.id}:failed:{attempt}",
            kind="failed",
            summary_code="task_failed",
            occurred_at=task.last_attempt_finished_at or state.updated_at,
            target_kind="task",
            target_id=task.id,
            related_targets=[task.id],
        )

    verification_attempt_id = _latest_verification_attempt_id(state)
    summary_code = "verification_failed" if state.failed_step and state.failed_step.value == "verify" else "run_failed"
    failure_revision = verification_attempt_id or _latest_stage_event_at(state) or state.updated_at
    return _event(
        state,
        project_key,
        source_key=f"run:{state.id}:{summary_code}:{failure_revision}",
        kind="failed",
        summary_code=summary_code,
        target_kind="verification" if summary_code == "verification_failed" else "run",
        target_id=state.id,
        verification_attempt_id=verification_attempt_id,
    )


def _group_completed_event(state: RunState, project_key: str) -> UserNotificationEvent:
    return _event(
        state,
        project_key,
        source_key=f"run:{state.id}:completed:{state.verified_integration_head or _completed_head_key(state)}",
        kind="completed",
        summary_code="group_completed",
        target_kind="operations",
        target_id=state.id,
    )


def _event(
    state: RunState,
    project_key: str,
    *,
    source_key: str,
    kind: str,
    summary_code: str,
    target_kind: str,
    target_id: str,
    occurred_at: str = "",
    request_id: str = "",
    verification_attempt_id: str = "",
    related_targets: list[str] | None = None,
    os_eligible: bool = True,
) -> UserNotificationEvent:
    identity = f"{project_key}\0{state.id}\0{source_key}"
    return UserNotificationEvent(
        event_id=hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        source_key=source_key,
        project_key=project_key,
        run_id=state.id,
        run_title=state.summary or state.id,
        target_kind=target_kind,
        target_id=target_id,
        request_id=request_id,
        verification_attempt_id=verification_attempt_id,
        kind=kind,
        occurred_at=occurred_at or state.updated_at,
        summary_code=summary_code,
        related_targets=list(related_targets or []),
        os_eligible=os_eligible,
    )


def _completed_head_key(state: RunState) -> str:
    commits = [task.completed_commit for task in state.tasks if task.completed_commit]
    return ":".join(commits) or f"revision-{state.plan_revision}"


def _latest_verification_attempt_id(state: RunState) -> str:
    return state.verification_attempts[-1].id if state.verification_attempts else ""


def _latest_stage_event_at(state: RunState) -> str:
    return next((event.at for event in reversed(state.events) if event.kind == "stage"), "")
