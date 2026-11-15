from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from .layout import uses_shared_workspace
from ..models import (
    IntegrationControl,
    IntegrationStatus,
    ResultFileChange,
    RunState,
    Stage,
)


def main_apply_review(
    state: RunState, integration: IntegrationControl, *, repository: Path,
    committed_result_files: Callable[[str, str], tuple[str, list[ResultFileChange], str]],
) -> dict[str, object]:
    attempt = state.verification_attempts[-1] if state.verification_attempts else None
    verification = ({"id": attempt.id, "status": attempt.status, "finished_at": attempt.finished_at,
                     "passed_command_count": len(attempt.passed_commands)} if attempt else None)
    can_apply = integration.can_apply_main and not state.archive and not state.active_step
    reason, reason_code = integration.reason, integration.reason_code
    files_state, files, error = committed_result_files(state.verified_main_head, state.verified_integration_head)
    attempt_matches = attempt is None or (
        attempt.status == "succeeded"
        and (not attempt.main_head or attempt.main_head == state.verified_main_head)
        and (not attempt.integration_head or attempt.integration_head == state.verified_integration_head)
    )
    if can_apply and (files_state == "unavailable" or not attempt_matches):
        can_apply = False
        reason, reason_code = error or "반영 대상의 최종 검증 성공 기록을 확인할 수 없습니다.", "review_evidence_unavailable"
    if (not can_apply and integration.status == IntegrationStatus.VERIFIED and state.stage == Stage.VERIFIED
            and uses_shared_workspace(state) and integration.remote_configured and not integration.can_apply_main):
        reason, reason_code = "검증된 작업 브랜치를 먼저 Push해야 합니다.", "work_branch_push_required"
    target = {"repo": str(repository.resolve()), "run_id": state.id, "main_branch": state.main_branch,
              "base_commit": state.verified_main_head, "current_main_commit": integration.current_main_head,
              "target_commit": state.verified_integration_head, "verification": verification}
    review = {**target, "stage": state.stage, "plan_revision": state.plan_revision, "remote_configured": integration.remote_configured}
    review_id = hashlib.sha256(json.dumps(review, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest() if can_apply else ""
    return {**target, "stage": state.stage.value, "review_id": review_id, "can_apply": can_apply,
            "reason": reason, "reason_code": reason_code, "file_count": len(files),
            "files_state": files_state, "files": [asdict(file) for file in files[:100]],
            "files_truncated": len(files) > 100, "remote_configured": integration.remote_configured}
