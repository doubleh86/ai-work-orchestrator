from __future__ import annotations

import hashlib
import re
from pathlib import PurePosixPath
from typing import Iterable, Sequence


TEMPLATE_VERSION = "1"
_SENSITIVE = re.compile(r"(?i)(password|passwd|secret|token|api[_ -]?key|\.env)\b")
_WINDOWS_ABSOLUTE = re.compile(r"(?:^|\s)[A-Za-z]:[\\/]")


def render_greenfield_agents(
    *,
    purpose: str,
    stack_items: Sequence[str],
    planned_paths: Sequence[str],
    verify_commands: Sequence[Sequence[str]],
) -> str:
    safe_purpose = _safe_text(purpose, "기획 문서에 정의된 프로젝트")
    safe_stack = [_safe_text(item, "") for item in stack_items]
    safe_stack = [item for item in safe_stack if item]
    source_roots, test_roots = _structure_roots(planned_paths)
    build_command = _command_for(verify_commands, ("build", "compile", "package"))
    test_command = _command_for(verify_commands, ("test", "pytest"))
    style_command = _command_for(verify_commands, ("lint", "format", "ruff", "black", "eslint", "prettier", "analy"))
    return (
        "# Project Instructions\n\n"
        "## Project and stack\n"
        f"- 프로젝트 목적: {safe_purpose}\n"
        f"- 기술 구성: {' · '.join(safe_stack) or '확정된 기술 snapshot을 따름'}\n\n"
        "## Structure and boundaries\n"
        f"- 소스: {_display_roots(source_roots)}\n"
        f"- 테스트: {_display_roots(test_roots)}\n"
        "- 생성물·비밀·로컬 상태는 커밋하지 않는다.\n\n"
        "## Code style\n"
        "- 저장소의 .editorconfig와 구성된 formatter/linter/analyzer를 따른다.\n"
        "- 확인되지 않은 규칙을 임의로 추가하지 않는다.\n\n"
        "## Validation\n"
        f"- Build: {build_command}\n"
        f"- Test: {test_command}\n"
        f"- Style: {style_command}\n\n"
        "## Working rules\n"
        "- 기획 문서와 확정된 기술 snapshot의 범위 안에서 작업한다.\n"
        "- 관련 없는 파일을 정리하거나 기존 사용자 변경을 되돌리지 않는다.\n"
        "- 실패를 성공이나 빈 결과로 숨기지 않는다.\n"
    )


def content_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _safe_text(value: str, fallback: str) -> str:
    text = " ".join(str(value).split()).replace("`", "'").strip()
    if not text or _SENSITIVE.search(text) or _looks_absolute(text):
        return fallback
    return text[:240]


def _looks_absolute(value: str) -> bool:
    return bool(_WINDOWS_ABSOLUTE.search(value)) or any(marker in value for marker in ("/home/", "/Users/", "\\\\"))


def _structure_roots(paths: Sequence[str]) -> tuple[list[str], list[str]]:
    sources: list[str] = []
    tests: list[str] = []
    for raw in paths:
        normalized = str(raw).strip().replace("\\", "/")
        if not normalized or normalized == "AGENTS.md" or _looks_absolute(normalized) or ".." in PurePosixPath(normalized).parts:
            continue
        if "/" not in normalized:
            continue
        root = normalized.split("/", 1)[0]
        if not root or any(character in root for character in "*?[]"):
            continue
        target = tests if any(marker in normalized.casefold() for marker in ("test", "spec")) else sources
        if root not in target:
            target.append(root)
    return sources, tests


def _display_roots(roots: Iterable[str]) -> str:
    values = list(roots)
    return ", ".join(f"`{value}`" for value in values) if values else "구성되지 않음"


def _command_for(commands: Sequence[Sequence[str]], markers: Sequence[str]) -> str:
    for command in commands:
        lowered = " ".join(str(item).casefold() for item in command)
        if any(marker in lowered for marker in markers):
            rendered = _render_command(command)
            if rendered:
                return f"`{rendered}`"
    return "구성되지 않음"


def _render_command(command: Sequence[str]) -> str:
    parts: list[str] = []
    for raw in command:
        value = str(raw).strip()
        if not value or _SENSITIVE.search(value) or _looks_absolute(value):
            return ""
        escaped = value.replace("`", "'")
        parts.append(f'"{escaped}"' if any(character.isspace() for character in escaped) else escaped)
    return " ".join(parts)
