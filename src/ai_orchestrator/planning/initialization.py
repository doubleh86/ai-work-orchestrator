"""Planning input and repository context without final Run authority."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from ..code_style import CodeStyleSnapshot
from ..errors import PipelineError
from ..models import (
    ExecutionWorkspaceMode, PlanningMessage, PlanningMessageRole, PlanningMode, RepositoryMaturityAssessment,
    RepositoryMaturityKind, RunState, Stage, UserCheck, WorkspaceLocation,
)


def external_plan_input(
    run_id: str, *, expected_base_commit: str, summary: str, requirements: str,
    task_drafts: list[dict[str, object]], server_work: bool, user_checks: tuple[UserCheck, ...],
) -> tuple[str, str, str]:
    if not re.fullmatch(r"mcp-plan-[a-f0-9]{32}", run_id):
        raise PipelineError("외부 기획 제출 ID가 올바르지 않습니다.")
    summary, requirements = summary.strip(), requirements.strip()
    if not summary or len(summary) > 180 or not requirements or not 1 <= len(task_drafts) <= 64:
        raise PipelineError("계획 제목 180자 이내, 합의한 요구사항과 Task 1~64개를 제출해 주세요.")
    plan_input: list[object] = [expected_base_commit, summary, requirements, task_drafts, server_work]
    if user_checks:
        plan_input.append([asdict(check) for check in user_checks])
    payload = json.dumps(plan_input, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(payload) > 512 * 1024:
        raise PipelineError("외부 기획은 512 KiB 이하로 제출해 주세요.")
    submission_digest = hashlib.sha256(payload).hexdigest()
    return summary, requirements, submission_digest


@dataclass(frozen=True, slots=True)
class PlanningRepositoryContext:
    repo: Path
    inspect_maturity: Callable[[Path], RepositoryMaturityAssessment]
    style_snapshot: Callable[[], CodeStyleSnapshot]

    def external(
        self, run_id: str, *, expected_base_commit: str, summary: str, requirements: str,
        submission_digest: str, server_work: bool, user_checks: tuple[UserCheck, ...],
        main_branch: Callable[[], str], workspace_location: Callable[[], WorkspaceLocation],
    ) -> RunState:
        assessment = self.inspect_maturity(self.repo)
        state = RunState(
            id=run_id, spec_path="", spec_digest=hashlib.sha256(requirements.encode("utf-8")).hexdigest(),
            repo_path=str(self.repo), main_branch=main_branch(), stage=Stage.RECEIVED,
            summary=summary, server_work=server_work, base_commit=expected_base_commit,
            workspace_mode=ExecutionWorkspaceMode.SHARED, workspace_location=workspace_location(),
            repository_intent="external_plan", repository_maturity=assessment,
            code_style_snapshot=self.style_snapshot(),
            planning_mode=PlanningMode.DIRECTED, planning_request=requirements, external_plan_digest=submission_digest,
            planning_messages=[PlanningMessage(role=PlanningMessageRole.USER, text=requirements)],
            planning_conversation_revision=1, planning_applied_conversation_revision=1,
            user_check_plan=list(user_checks),
        )
        return state

    def apply(self, state: RunState, *, repository_intent: str, explicit_repository_intent: bool) -> None:
        assessment = self.inspect_maturity(self.repo)
        if explicit_repository_intent and assessment.kind == RepositoryMaturityKind.AMBIGUOUS and not repository_intent:
            raise PipelineError("repository structure is ambiguous; choose existing_structure or new_project before Planning")
        if explicit_repository_intent and assessment.kind == RepositoryMaturityKind.DOCS_ONLY and repository_intent != "new_project":
            raise PipelineError("docs-only repository cannot use existing_structure without implementation evidence")
        state.repository_maturity = assessment
        state.code_style_snapshot = self.style_snapshot()
        state.repository_intent = repository_intent
        if state.repository_intent == "new_project":
            state.greenfield_phase = "stack_decision_required"
