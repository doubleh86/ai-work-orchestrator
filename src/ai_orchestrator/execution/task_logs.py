"""Bounded Task log reading and diagnostic section assembly."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from ..models import TaskStatus, WorkTask


def read_task_log_tail(path: Path, *, limit_bytes: int) -> str:
    with path.open("rb") as stream:
        size = stream.seek(0, os.SEEK_END)
        offset = max(0, size - limit_bytes)
        stream.seek(offset)
        content = stream.read(limit_bytes)
    text = content.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    if offset == 0:
        return text
    return f"[로그가 커서 최근 {limit_bytes // 1024} KiB만 표시합니다. 전체 로그: {path}]\n\n…{text}"


def render_task_log(
    task: WorkTask, run_id: str, *, run_directory: Callable[[str], Path], read_tail: Callable[[Path], str],
) -> str:
    sections: list[str] = []
    environment_path = run_directory(run_id) / "logs" / f"{task.id}-environment.log"
    if environment_path.exists():
        sections.append(read_tail(environment_path))
    if task.log_path:
        path = Path(task.log_path)
        if path.exists():
            sections.append(read_tail(path))
    verification_path = run_directory(run_id) / "logs" / f"{task.id}-verify.log"
    if verification_path.exists():
        sections.append("Task 검증 로그\n" + read_tail(verification_path))
    if task.status == TaskStatus.FAILED or task.error:
        action = task.failed_action.value if task.failed_action else "기록 없음"
        sections.append(f"[오케스트레이터 Task 실패]\nTask: {task.id}\n실패 단계: {action}\n원인: {task.error or '오류 메시지 기록 없음'}")
    if len(sections) == 1:
        return sections[0]
    return "\n\n".join(section.rstrip() for section in sections)
