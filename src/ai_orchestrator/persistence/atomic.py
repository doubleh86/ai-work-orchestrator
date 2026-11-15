from __future__ import annotations

import json
import time
import uuid
from pathlib import Path


def write_json_atomic(target: Path, payload: dict[str, object]) -> None:
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass  # Preserve the original write error.
        raise
    delays = (0.05, 0.1, 0.2, 0.4, 0.8)
    for attempt in range(len(delays) + 1):
        try:
            temporary.replace(target)
            return
        except OSError as exc:
            if getattr(exc, "winerror", None) in {5, 32, 33} and attempt < len(delays):
                time.sleep(delays[attempt])
                continue
            raise OSError(f"상태 파일 저장 실패: {target}. 기존 파일을 삭제하지 않았습니다. 저장하려던 내용은 임시 파일에 보존했습니다: {temporary}. 원인: {exc}") from exc


def write_text_atomic(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
    delays = (0.05, 0.1, 0.2, 0.4, 0.8)
    for attempt in range(len(delays) + 1):
        try:
            temporary.replace(target)
            return
        except OSError as exc:
            if getattr(exc, "winerror", None) in {5, 32, 33} and attempt < len(delays):
                time.sleep(delays[attempt])
                continue
            raise OSError(
                f"보관 요약 저장 실패: {target}. 기존 파일을 삭제하지 않았습니다. "
                f"저장하려던 내용은 임시 파일에 보존했습니다: {temporary}. 원인: {exc}"
            ) from exc
