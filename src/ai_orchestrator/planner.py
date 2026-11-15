from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from .config import AgentConfig, RoutingConfig, supported_models, supported_reasoning_efforts
from .document_index import SUPPORTED_DOCUMENT_SUFFIXES
from .planning import (
    CAPABILITY_ALIASES, PLAN_MARKER, TASK_ID, Plan, PlanningError, PlanningSourceDocument,
    execution_profile_guidance, planning_prompt, technology_stack_plan_example, parse_structured_plan, structured_plan_dict,
    task_path_matches, task_paths_may_overlap, validate_task_graph, validate_user_checks,
    validate_relative_paths as _relative_paths, assign_agents as _assign_agents,
    assign_plan_agents, select_agent_for_provider, assign_task_agent_overrides,
)
from .models import (
    EffortMode, PlanningMode, ProfileSource, ReviewStatus, RiskLevel, TaskReadiness, TechStackComponents, TechStackOption, UserCheck, WorkTask,
)
from .model_selection import AUTOMATIC_CODEX_MODELS, CODEX_SOL_MODEL, automatic_claude_profile, select_claude_model, select_codex_model

TAGGED_TASK = re.compile(r"^\s*[-*]\s+\[([^\]]+)\]\s+(.+?)\s*$")
PLAIN_TASK = re.compile(r"^\s*[-*]\s+(?!\[[ xX]\]\s)(.+?)\s*$")
ROOT_REPOSITORY_INSTRUCTION_PATHS = ("AGENTS.md", "AGENTS.local.md")

KEYWORDS: dict[str, tuple[str, ...]] = {
    "backend": ("server", "backend", "api", "database", "db", "auth", "서버", "백엔드", "데이터베이스", "인증"),
    "frontend": ("frontend", "web", "ui", "screen", "client", "프론트", "화면", "클라이언트"),
    "mobile": ("mobile", "ios", "android", "앱", "모바일"),
    "infra": ("infra", "deploy", "docker", "kubernetes", "cloud", "배포", "인프라"),
    "qa": ("test", "qa", "verify", "테스트", "검증"),
    "security": ("security", "permission", "보안", "권한"),
    "docs": ("docs", "document", "readme", "문서"),
    "planning": ("plan", "requirement", "spec", "기획", "요구사항", "명세"),
    "architecture": ("architecture", "design", "아키텍처", "설계", "구조"),
    "review": ("review", "audit", "리뷰", "검토", "감사"),
}

SERVER_CAPABILITIES = {"backend", "infra", "database", "api"}
HIGH_RISK_CAPABILITIES = {"security", "infra", "database"}
MEDIUM_RISK_CAPABILITIES = {"backend", "api", "mobile", "architecture"}


def read_planning_document(path: str | Path) -> str:
    document_path = Path(path).expanduser().resolve()
    if document_path.is_dir():
        return _planning_directory_reference(document_path)
    return _read_planning_file(document_path)


def _planning_directory_reference(directory_path: Path) -> str:
    document_count = 0
    for candidate in directory_path.rglob("*"):
        if not candidate.is_file() or candidate.suffix.casefold() not in SUPPORTED_DOCUMENT_SUFFIXES:
            continue
        resolved = candidate.resolve()
        if not resolved.is_relative_to(directory_path):
            continue
        document_count += 1

    if document_count == 0:
        raise PlanningError(f"planning document directory contains no supported documents: {directory_path}")
    return f"""# Planning source directory

Source root: `{directory_path.as_posix()}`
Supported document count: {document_count}

Treat this directory as a read-only context root. Follow the active repository
instructions, search for relevant material, and read only the documents needed
for the requested implementation plan. Do not ingest the entire directory.
"""


def read_planning_source_documents(source_root: str | Path, source_paths: list[str]) -> list[PlanningSourceDocument]:
    root = Path(source_root).expanduser().resolve()
    if not root.is_dir():
        raise PlanningError(f"planning source directory not found: {root}")
    relative_paths = _relative_paths(source_paths, "source_paths", allow_empty=True)
    documents: list[PlanningSourceDocument] = []
    for relative_path in sorted(relative_paths, key=lambda value: (value.casefold(), value)):
        parsed = PurePosixPath(relative_path)
        document_path = root.joinpath(*parsed.parts).resolve()
        if not document_path.is_relative_to(root):
            raise PlanningError(f"source_paths must stay inside planning source directory: {relative_path}")
        if document_path.suffix.casefold() not in SUPPORTED_DOCUMENT_SUFFIXES:
            raise PlanningError(f"source_paths contains unsupported document: {relative_path}")
        if not document_path.is_file():
            raise PlanningError(f"source_paths document not found: {relative_path}")
        content = _read_utf8_document(document_path)
        if not content.strip():
            raise PlanningError(f"source_paths document is empty: {relative_path}")
        documents.append(PlanningSourceDocument(relative_path=relative_path, path=document_path, content=content))
    return documents


def discover_repository_instruction_documents(repository_root: str | Path) -> list[PlanningSourceDocument]:
    root = Path(repository_root).expanduser().resolve()
    if not root.is_dir():
        raise PlanningError(f"repository root not found: {root}")
    instruction_paths = [relative_path for relative_path in ROOT_REPOSITORY_INSTRUCTION_PATHS if (root / relative_path).is_file()]
    return read_repository_instruction_documents(root, instruction_paths)


def read_repository_instruction_documents(repository_root: str | Path, instruction_paths: list[str]) -> list[PlanningSourceDocument]:
    root = Path(repository_root).expanduser().resolve()
    if not root.is_dir():
        raise PlanningError(f"repository root not found: {root}")
    relative_paths = _relative_paths(instruction_paths, "instruction_paths", allow_empty=True)
    documents: list[PlanningSourceDocument] = []
    for relative_path in relative_paths:
        parsed = PurePosixPath(relative_path)
        document_path = root.joinpath(*parsed.parts).resolve()
        if not document_path.is_relative_to(root):
            raise PlanningError(f"instruction_paths must stay inside repository root: {relative_path}")
        if document_path.suffix.casefold() not in SUPPORTED_DOCUMENT_SUFFIXES:
            raise PlanningError(f"instruction_paths contains unsupported document: {relative_path}")
        if not document_path.is_file():
            raise PlanningError(f"instruction_paths document not found: {relative_path}")
        content = _read_utf8_document(document_path)
        if not content.strip():
            raise PlanningError(f"instruction_paths document is empty: {relative_path}")
        documents.append(PlanningSourceDocument(relative_path=relative_path, path=document_path, content=content))
    return documents


def _read_planning_file(document_path: Path) -> str:
    suffix = document_path.suffix.casefold()
    if suffix not in SUPPORTED_DOCUMENT_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_DOCUMENT_SUFFIXES))
        raise PlanningError(f"unsupported planning document format '{suffix or 'none'}'; supported formats: {supported}")
    content = _read_utf8_document(document_path)
    if not content.strip():
        raise PlanningError("planning document is empty")
    return content


def _read_utf8_document(document_path: Path) -> str:
    try:
        return document_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise PlanningError(f"planning document must be UTF-8 text: {document_path}") from exc


def infer_capabilities(text: str) -> list[str]:
    normalized = text.casefold()
    found = [capability for capability, keywords in KEYWORDS.items() if any(keyword.casefold() in normalized for keyword in keywords)]
    return found or ["general"]


def _task_lines(markdown: str) -> list[tuple[str, list[str]]]:
    lines = markdown.splitlines()
    in_tasks = False
    saw_task_heading = False
    selected: list[str] = []
    fallback: list[str] = []

    for line in lines:
        heading = line.strip().casefold()
        if heading.startswith("## "):
            title = heading[3:].strip()
            in_tasks = title in {"작업", "작업 목록", "tasks", "implementation tasks"}
            saw_task_heading = saw_task_heading or in_tasks
            continue
        if TAGGED_TASK.match(line) or PLAIN_TASK.match(line):
            fallback.append(line)
            if in_tasks:
                selected.append(line)

    source = selected if saw_task_heading else fallback
    result: list[tuple[str, list[str]]] = []
    for line in source:
        tagged = TAGGED_TASK.match(line)
        if tagged:
            capabilities = []
            for value in tagged.group(1).split(","):
                normalized = value.strip().casefold()
                if normalized:
                    capabilities.append(CAPABILITY_ALIASES.get(normalized, normalized))
            result.append((tagged.group(2).strip(), capabilities or ["general"]))
            continue
        plain = PLAIN_TASK.match(line)
        if plain:
            title = plain.group(1).strip()
            result.append((title, infer_capabilities(title)))
    return result


def _slug(index: int, title: str) -> str:
    ascii_words = re.findall(r"[a-z0-9]+", title.casefold())
    suffix = "-".join(ascii_words[:4]) or "task"
    return f"t{index:02d}-{suffix}"[:48].rstrip("-")


def build_plan(spec_path: str | Path, agents: tuple[AgentConfig, ...], routing: RoutingConfig | None = None, *, sequential: bool = False) -> Plan:
    path = Path(spec_path)
    markdown = path.read_text(encoding="utf-8")
    raw_tasks = _task_lines(markdown)
    if not raw_tasks:
        raise PlanningError("no tasks found; add bullet items under a '## 작업' or '## Tasks' heading")

    tasks = [
        WorkTask(
            id=_slug(index, title),
            title=title,
            description=title,
            capabilities=capabilities,
            acceptance_criteria=[f"{title} 작업이 완료되고 관련 검증을 통과한다"],
            risk_level=_infer_risk_level(capabilities),
        )
        for index, (title, capabilities) in enumerate(raw_tasks, start=1)
    ]
    _assign_agents(tasks, agents, routing or RoutingConfig(), sequential=sequential)
    all_capabilities = {value for task in tasks for value in task.capabilities}
    server_work = bool(all_capabilities & SERVER_CAPABILITIES) or bool(set(infer_capabilities(markdown)) & SERVER_CAPABILITIES)
    agent_ids = {agent_id for task in tasks for agent_id in (task.agent_id, task.reviewer_agent_id) if agent_id}
    provider_count = len({provider_id for task in tasks for provider_id in (task.provider_id, task.reviewer_provider_id) if provider_id})
    summary = f"작업 {len(tasks)}개, 에이전트 {len(agent_ids)}개, 공급자 {provider_count}개"
    return Plan(summary=summary, server_work=server_work, tasks=tasks)


def _infer_risk_level(capabilities: list[str]) -> RiskLevel:
    selected = set(capabilities)
    if selected & HIGH_RISK_CAPABILITIES:
        return RiskLevel.HIGH
    if selected & MEDIUM_RISK_CAPABILITIES:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW
