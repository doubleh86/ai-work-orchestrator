"""Resolve external provider commands without relying on a login shell."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from .app_paths import application_config_root
from .file_lock import exclusive_file_lock


class ProviderExecutableError(ValueError):
    pass


def _claude_settings_path() -> Path:
    return application_config_root() / "claude-executable.json"


def selected_claude_executable() -> str:
    try:
        raw = json.loads(_claude_settings_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ""
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProviderExecutableError("Claude 실행 파일 설정을 읽지 못했습니다. 경로를 다시 선택하거나 자동 탐색으로 복구하세요.") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != 1 or not isinstance(raw.get("path"), str):
        raise ProviderExecutableError("Claude 실행 파일 설정 형식이 올바르지 않습니다. 경로를 다시 선택하거나 자동 탐색으로 복구하세요.")
    path = raw["path"]
    if not path or not Path(path).is_absolute() or any(character in path for character in ("\x00", "\n", "\r")):
        raise ProviderExecutableError("Claude 실행 파일 설정 경로가 올바르지 않습니다. 경로를 다시 선택하거나 자동 탐색으로 복구하세요.")
    return path


def set_claude_executable(value: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 4096 or any(character in value for character in ("\x00", "\n", "\r")):
        raise ProviderExecutableError("Claude 실행 파일 경로를 확인해 주세요.")
    path = Path(value).expanduser()
    if not path.is_absolute() or path.name.lower() not in {"claude", "claude.exe", "claude.cmd", "claude.bat"}:
        raise ProviderExecutableError("Claude Code 실행 파일을 선택해 주세요.")
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ProviderExecutableError("선택한 Claude 실행 파일을 사용할 수 없습니다. 설치 위치를 확인해 주세요.")
    settings = _claude_settings_path()
    with exclusive_file_lock(settings.with_name(f"{settings.name}.lock")):
        temporary = settings.with_name(f"{settings.name}.tmp")
        try:
            temporary.write_text(json.dumps({"schema_version": 1, "path": str(path)}, ensure_ascii=False) + "\n", encoding="utf-8")
            temporary.replace(settings)
        finally:
            temporary.unlink(missing_ok=True)
    return str(path)


def clear_claude_executable() -> None:
    settings = _claude_settings_path()
    with exclusive_file_lock(settings.with_name(f"{settings.name}.lock")):
        settings.unlink(missing_ok=True)


def resolve_provider_executable(executable: str) -> str:
    path = Path(executable).expanduser()
    if path.parent != Path(".") and path.exists():
        return str(path.resolve())

    if executable == "claude":
        selected = selected_claude_executable()
        if selected:
            path = Path(selected)
            return selected if path.is_file() and os.access(path, os.X_OK) else ""

    found = shutil.which(executable)
    if found:
        return found

    if executable == "claude" and os.name != "nt":
        installed = Path.home() / ".local" / "bin" / "claude"
        if installed.is_file() and os.access(installed, os.X_OK):
            return str(installed)
    return ""
