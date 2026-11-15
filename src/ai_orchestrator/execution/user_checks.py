"""User-check evidence without approval, locks or final Run authority."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from ..errors import PipelineError
from ..models import RunState, UserCheckOutcome, UserCheckResult, utc_now

if TYPE_CHECKING:
    from subprocess import CompletedProcess


@dataclass(frozen=True, slots=True)
class UserCheckRecorder:
    inspect_commit: Callable[[str], CompletedProcess[str]]

    def record(
        self, state: RunState, check_id: str, *, expected_revision: int, expected_commit: str,
        selected: UserCheckOutcome, note: str,
    ) -> bool:
        if state.plan_revision != expected_revision:
            raise PipelineError("확인하려던 계획이 변경됐습니다. 최신 계획을 다시 열어 주세요.")
        check = next((item for item in state.user_check_plan if item.id == check_id), None)
        if check is None:
            raise PipelineError("이 작업 그룹의 사용자 확인을 찾지 못했습니다.")
        reference = state.user_check_reference(check)
        if not reference or reference != expected_commit:
            raise PipelineError("사용자 확인의 기준 커밋이 아직 없거나 변경됐습니다. 최신 결과를 다시 확인해 주세요.")
        current = state.current_user_check_result(check)
        if current and current.outcome == selected and current.note == note:
            return False
        if current and current.outcome == UserCheckOutcome.PASSED:
            raise PipelineError("이 기준 커밋의 사용자 확인은 이미 통과로 확정됐습니다.")
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", reference):
            raise PipelineError("사용자 확인의 기준 커밋이 올바르지 않습니다.")
        self.inspect_commit(reference)
        state.user_check_results.setdefault(check.id, []).append(UserCheckResult(reference, selected, note, utc_now()))
        state.refresh_task_readiness()
        state.add_event("user_check", f"{check.id} {selected.value} for {reference}")
        return True
