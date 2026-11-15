from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ..models import TechStackOption, WorkTask


TASK_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

PLAN_MARKER = "AI_PLAN_RESULT:"

CAPABILITY_ALIASES = {
    "server": "backend",
    "서버": "backend",
    "백엔드": "backend",
    "db": "database",
    "데이터베이스": "database",
    "front": "frontend",
    "프론트": "frontend",
    "test": "qa",
    "테스트": "qa",
}


@dataclass(frozen=True, slots=True)
class Plan:
    summary: str
    server_work: bool
    tasks: list[WorkTask]
    questions: list[str] = field(default_factory=list)
    source_paths: list[str] = field(default_factory=list)
    instruction_paths: list[str] = field(default_factory=list)
    tech_stack_options: list[TechStackOption] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PlanningSourceDocument:
    relative_path: str
    path: Path
    content: str


class PlanningError(ValueError):
    pass
