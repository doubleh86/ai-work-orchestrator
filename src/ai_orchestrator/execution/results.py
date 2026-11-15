"""Committed-file evidence and idempotent Task/group result receipts."""

from __future__ import annotations

from typing import Callable

from ..git_contracts import GitError, LOCAL_GIT_TIMEOUT_SECONDS
from ..models import GroupResultRecord, ResultFileChange, RunState, TaskAction, TaskResultRecord, WorkTask, utc_now

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..git import GitWorkspace


def brief_worker_report(task: WorkTask) -> str:
    result = next(
        (item for item in reversed(task.action_results)
         if item.action in {TaskAction.EXECUTE.value, TaskAction.REVISE.value} and item.status == "succeeded" and item.worker_response.strip()),
        None,
    )
    if result is None:
        return ""
    lines = [line.strip()[:240] for line in result.worker_response.splitlines() if line.strip()]
    return "\n".join(lines[:4])[:800]


def committed_result_files(git: GitWorkspace, baseline: str, result: str) -> tuple[str, list[ResultFileChange], str]:
    if not baseline or not result:
        return "unavailable", [], "기준 또는 결과 commit 기록 없음"
    try:
        changed = git.commit_changed_files(baseline, result, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
    except (GitError, OSError):
        return "unavailable", [], "Git commit 비교 실패"
    files = [ResultFileChange(path=path, change=change) for path, change in changed]
    return ("confirmed" if files else "none"), files, ""


def record_task_result(
    task: WorkTask, *, read_commit_files: Callable[[str, str], tuple[str, list[ResultFileChange], str]],
    manual_verification_note: str = "",
) -> None:
    if (task.result_history and task.result_history[-1].result_commit == task.completed_commit
            and (not manual_verification_note or task.result_history[-1].manual_verification_note == manual_verification_note)):
        return
    files_state, files, error = read_commit_files(task.started_commit, task.completed_commit)
    verified = next(
        (item for item in reversed(task.action_results) if item.action == TaskAction.VERIFY.value and item.status == "succeeded"),
        None,
    )
    task.result_history.append(TaskResultRecord(
        baseline_commit=task.started_commit, result_commit=task.completed_commit, captured_at=utc_now(),
        files_state=files_state, files=files, error=error, self_report=brief_worker_report(task),
        verification_status="passed" if verified is not None and verified.passed_commands else "unverified",
        passed_commands=[list(command) for command in verified.passed_commands] if verified is not None else [],
        manual_verification_note=manual_verification_note,
    ))


def record_group_result(
    state: RunState, *, read_commit_files: Callable[[str, str], tuple[str, list[ResultFileChange], str]],
) -> None:
    attempt = state.verification_attempts[-1] if state.verification_attempts else None
    if attempt is None:
        return
    if state.group_result_history and state.group_result_history[-1].verification_attempt_id == attempt.id:
        return
    files_state, files, error = read_commit_files(state.verified_main_head, state.verified_integration_head)
    state.group_result_history.append(GroupResultRecord(
        verification_attempt_id=attempt.id, main_commit=state.verified_main_head,
        result_commit=state.verified_integration_head, captured_at=utc_now(),
        files_state=files_state, files=files, error=error,
    ))
