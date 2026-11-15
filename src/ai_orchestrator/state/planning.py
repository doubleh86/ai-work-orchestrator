from __future__ import annotations

import re
from dataclasses import dataclass, field

from .common import (
    DirectionChangeStatus,
    PlanningApplyStatus,
    PlanningMessageRole,
    RepositoryMaturityKind,
    TechStackDecisionStatus,
    utc_now,
)


@dataclass(slots=True)
class RepositoryMaturityEvidence:
    relative_path: str
    evidence_kind: str
    stack_hints: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RepositoryMaturityAssessment:
    kind: RepositoryMaturityKind
    evidence: list[RepositoryMaturityEvidence] = field(default_factory=list)
    ignored_roots: list[str] = field(default_factory=list)
    detected_application_roots: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    inspected_file_count: int = 0
    truncated: bool = False


@dataclass(slots=True)
class TechStackComponents:
    languages: list[str] = field(default_factory=list)
    runtimes: list[str] = field(default_factory=list)
    application_frameworks: list[str] = field(default_factory=list)
    ui_frameworks: list[str] = field(default_factory=list)
    persistence: list[str] = field(default_factory=list)
    package_and_build_tools: list[str] = field(default_factory=list)
    test_tools: list[str] = field(default_factory=list)
    style_and_analysis: list[str] = field(default_factory=list)
    packaging_and_deployment: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TechStackOption:
    option_id: str
    label: str
    recommendation_rank: int
    components: TechStackComponents
    version_policy: list[str] = field(default_factory=list)
    requirement_fit: list[str] = field(default_factory=list)
    tradeoffs: list[str] = field(default_factory=list)
    unresolved_constraints: list[str] = field(default_factory=list)
    required_external_dependencies: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TechStackDecision:
    decision_id: str
    revision: int
    status: TechStackDecisionStatus
    project_root: str
    requirement_sources: list[str]
    answers: list[str]
    options: list[TechStackOption]
    selected_option_id: str = ""
    confirmed_at: str = ""
    confirmed_by: str = ""
    created_at: str = field(default_factory=utc_now)

    def selection_questions_only(self, questions: list[str]) -> bool:
        """Recognize explicit candidate-choice questions conservatively."""
        if not questions or not self.options:
            return False
        names = {option.label for option in self.options}
        for option in self.options:
            for name in option.components.languages + option.components.runtimes:
                names.add(name)
                names.add(name.removesuffix(" LTS"))
        subjects = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True) if name)
        subject = rf"(?:{subjects})(?:\s*(?:와|과|및|[·,/+])\s*(?:{subjects}))*"
        patterns = [
            r"(?:추천한|추천된|제안한|제안된) (?:기술 )?(?:구성|후보|기술 스택)(?:을|를) (?:선택|확정)할까요[?？]?",
            rf"(?:추천한|추천된|제안한|제안된) {subject}(?: 구성)?(?:을|를) (?:선택|확정)할까요[?？]?",
            rf"(?:(?:빈 프로젝트의 )?설치·빌드·테스트를 검증할 )?기술 구성으로 (?:추천한|제안한) {subject}(?:을|를) 선택할까요[?？]?",
            r"(?:어떤|어느) (?:기술 구성|기술 스택|후보)(?:을|를) 선택하시겠습니까[?？]?",
            r"(?:Would you like to|Shall we) (?:select|confirm) the recommended (?:stack|option)\?",
        ]
        return all(any(re.fullmatch(pattern, question.strip(), re.IGNORECASE) for pattern in patterns) for question in questions)


@dataclass(slots=True)
class BootstrapPathState:
    relative_path: str
    entry_kind: str
    content_digest: str = ""


@dataclass(slots=True)
class BootstrapAgentInstructions:
    mode: str
    path: str = "AGENTS.md"
    template_version: str = "1"
    rendered_content: str = ""
    content_digest: str = ""
    task_path_injected: bool = False
    task_acceptance_injected: bool = False


@dataclass(slots=True)
class BootstrapSpec:
    decision_id: str
    decision_revision: int
    target_root: str
    planned_paths: list[str]
    steps: list[str]
    required_tools: list[str]
    verify_commands: list[list[str]]
    excluded_external_actions: list[str]
    path_snapshot: list[BootstrapPathState]
    digest: str
    agent_instructions: BootstrapAgentInstructions | None = None
    verified_integration_head: str = ""
    verified_at: str = ""
    feature_plan_attempts: int = 0
    feature_plan_error: str = ""
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class PlanningMessage:
    role: PlanningMessageRole
    text: str
    at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class PlanningApplyRequest:
    request_id: str
    conversation_revision: int
    plan_revision: int
    context_snapshot: str
    status: PlanningApplyStatus = PlanningApplyStatus.QUEUED
    created_at: str = field(default_factory=utc_now)
    completed_at: str = ""
    added_tasks: int = 0
    updated_tasks: int = 0
    excluded_tasks: int = 0
    unchanged_tasks: int = 0
    error_code: str = ""
    error: str = ""
    answer_message: str = ""
    answer_conversation_revision: int = 0
    tech_stack_revision: int = 0


@dataclass(slots=True)
class DirectionChangeRequest:
    request_id: str
    text: str
    task_id: str
    task_title: str
    status: DirectionChangeStatus = DirectionChangeStatus.RECEIVED
    next_step: str = ""
    preview_id: str = ""
    error: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
