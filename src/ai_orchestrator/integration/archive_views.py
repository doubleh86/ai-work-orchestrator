"""Read-only archive eligibility, identities and preserved result views."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Callable, Iterator

from ..errors import PipelineError
from ..models import ArchiveCleanupTarget, ConflictResolutionStatus, PlanningApplyStatus, RunState, Stage


def archive_block_reasons(state: RunState, *, remote_configured: bool, deployment_configured: bool) -> list[str]:
    reasons: list[str] = []
    final_stages = {Stage.DEPLOYED} if deployment_configured else {Stage.PUSHED, Stage.DEPLOYED}
    if not remote_configured and not deployment_configured:
        final_stages.add(Stage.MERGED)
    if state.stage not in final_stages:
        reasons.append("Main 반영과 필요한 원격 전송·배포가 완료된 그룹만 보관할 수 있습니다.")
    if any(task.active_action for task in state.tasks) or state.active_step is not None:
        reasons.append("진행 중인 실행 또는 기획 작업이 있습니다.")
    if any(request.status in {PlanningApplyStatus.QUEUED, PlanningApplyStatus.APPLYING} for request in state.planning_apply_requests):
        reasons.append("적용 대기 중인 Planning 변경이 있습니다.")
    if state.integration_conflict and state.integration_conflict.resolution_status not in {
        ConflictResolutionStatus.APPLIED,
        ConflictResolutionStatus.STALE,
    }:
        reasons.append("완료되지 않은 Main 통합 충돌 복구가 있습니다.")
    return reasons


def archive_fingerprint(state: RunState, targets: list[ArchiveCleanupTarget]) -> str:
    payload = {
        "run_id": state.id,
        "revision": state.updated_at,
        "stage": state.stage.value,
        "targets": [
            [target.id, target.recorded_path, target.expected_head, target.status]
            for target in targets
        ],
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def archive_summary(
    state: RunState, archived_at: str, targets: list[ArchiveCleanupTarget]
) -> str:
    task_lines: list[str] = []
    for task in state.tasks:
        task_lines.append(f"### {task.id}: {task.title}")
        task_lines.append(f"- 상태: {task.status.value} · 결과 commit: {task.completed_commit or '기록 없음'}")
        result = task.result_history[-1] if task.result_history else None
        if result is None or result.result_commit != task.completed_commit:
            task_lines.append("- 한 일: 최종 작업 내용 기록 없음")
            task_lines.append("- 최종 변경 파일 확인 불가")
            continue
        task_lines.append(
            f"- 한 일: 최종 commit에 {len(result.files)}개 파일 변경"
            if result.files_state == "confirmed" else "- 한 일: 파일 변경 없음"
            if result.files_state == "none" else "- 한 일: 최종 작업 내용 확인 불가"
        )
        if result.self_report:
            task_lines.append("- AI 자체 보고: " + " / ".join(result.self_report.splitlines()))
        if result.manual_verification_note:
            task_lines.append("- 수동 검증 결과: " + " / ".join(result.manual_verification_note.splitlines()))
        if result.verification_status == "passed" or not result.manual_verification_note:
            task_lines.append(f"- 검증: {'Task 검증 통과' if result.verification_status == 'passed' else '미검증'}")
        task_lines.append(f"- 완료 시각: {result.captured_at}")
        if result.files_state == "confirmed":
            task_lines.extend(f"  - {item.change} {item.path}" for item in result.files)
        elif result.files_state == "none":
            task_lines.append("- 파일 변경 없음")
        else:
            task_lines.append("- 최종 변경 파일 확인 불가" + (f": {result.error}" if result.error else ""))
        task_lines.append("")
    verification = state.verification_attempts[-1] if state.verification_attempts else None
    group = state.group_result_history[-1] if state.group_result_history else None
    if (
        group is None or group.result_commit != state.verified_integration_head
        or verification is None or verification.status != "succeeded"
        or group.verification_attempt_id != verification.id
    ):
        group_lines = [
            "통합 검증 완료 · 최종 변경 파일 확인 불가" if verification is not None and verification.status == "succeeded"
            else "통합 검증 실패 · 최종 변경 파일 확인 불가" if verification is not None and verification.status == "failed"
            else "통합 검증 대기 · 최종 변경 파일 확인 불가"
        ]
    elif group.files_state == "confirmed":
        group_lines = [f"검증한 통합 commit: {group.result_commit} · 최종 변경 파일 {len(group.files)}개"]
        group_lines.extend(f"- {item.change} {item.path}" for item in group.files)
    elif group.files_state == "none":
        group_lines = [f"검증한 통합 commit: {group.result_commit} · 파일 변경 없음"]
    else:
        group_lines = ["최종 변경 파일 확인 불가" + (f": {group.error}" if group.error else "")]
    group_text = "\n".join(group_lines)
    task_text = "\n".join(task_lines) if task_lines else "- Task 기록 없음"
    return (
        f"# {state.summary or state.id}\n\n"
        f"- 그룹 ID: `{state.id}`\n"
        f"- 원래 최종 상태: `{state.stage.value}`\n"
        f"- 보관 시각: `{archived_at}`\n"
        f"- 검증 결과: `{verification.status if verification else '기록 없음'}`\n"
        f"- 정리 대상: {len(targets)}개\n\n"
        "## 그룹 통합 결과\n\n"
        f"{group_text}\n\n"
        "## Task 결과\n\n"
        f"{task_text}\n\n"
        "원문 상태와 기획 대화, 실행·검증 로그는 같은 기록 폴더에 보존됩니다."
    )


def archived_run_plan(state: RunState, *, run_directory: Callable[[str], Path]) -> dict[str, object]:
    archive = state.archive
    if archive is None:
        raise PipelineError("보관 상태를 찾을 수 없습니다.")
    return {
        "run_id": state.id,
        "expected_revision": archive.source_revision,
        "fingerprint": archive.fingerprint,
        "can_archive": False,
        "block_reasons": ["이미 보관된 작업 그룹입니다."],
        "archived": True,
        "archive": state.to_dict()["archive"],
        "cleanup_targets": [archive_target_payload(target) for target in archive.cleanup_targets],
        "record_path": str(run_directory(state.id).resolve()),
        "preserved_records": [],
    }


def archive_target_payload(target: ArchiveCleanupTarget) -> dict[str, str]:
    return {
        "id": target.id,
        "recorded_path": target.recorded_path,
        "expected_head": target.expected_head,
        "status": target.status,
        "error": target.error,
        "archive_ref": target.archive_ref,
    }


def archive_request_id(request_id: str) -> str:
    try:
        return str(uuid.UUID(request_id.strip()))
    except (AttributeError, ValueError) as exc:
        raise PipelineError("requestId는 UUID 형식이어야 합니다.") from exc


def archive_commit_references(state: RunState) -> Iterator[tuple[str, str]]:
    commits: list[tuple[str, str]] = []
    commits.extend((f"task-{index}", task.completed_commit) for index, task in enumerate(state.tasks, start=1) if task.completed_commit)
    if state.verified_integration_head:
        commits.append(("verified-integration", state.verified_integration_head))
    candidate = state.integration_conflict.candidate if state.integration_conflict else None
    if candidate is not None and candidate.commit:
        commits.append(("conflict-candidate", candidate.commit))
    seen: set[str] = set()
    for label, commit in commits:
        if commit in seen:
            continue
        seen.add(commit)
        reference = f"refs/ai-orchestrator/archive/{state.id}/{label}"
        yield reference, commit
