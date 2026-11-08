"""Install the MCP runtime shipped in the Windows app for local Codex use."""

from __future__ import annotations

import os
import json
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from . import __version__
from .app_paths import application_config_root
from .file_lock import exclusive_file_lock
from .provider_executable import resolve_provider_executable


_EXECUTABLE = "ai-orchestrator-backend.exe"
_Version = tuple[int, int, int]


def _version(value: str) -> _Version | None:
    match = re.fullmatch(r"(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})", value)
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


def _complete_runtime(directory: Path) -> bool:
    return (directory / _EXECUTABLE).is_file() and (directory / "_internal").is_dir()


def _selected_runtime(root: Path, bundled: Path, current: _Version) -> tuple[Path, _Version]:
    selected, version = bundled, current
    versions = root / "versions"
    if versions.is_dir():
        for directory in versions.iterdir():
            candidate = _version(directory.name)
            if candidate is not None and candidate > version and _complete_runtime(directory):
                selected, version = directory / _EXECUTABLE, candidate
    return selected, version


def _copy_path(path: Path) -> Path:
    absolute = os.path.abspath(path)
    if os.name != "nt" or absolute.startswith("\\\\?\\"):
        return Path(absolute)
    if absolute.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + absolute[2:])
    return Path("\\\\?\\" + absolute)


def _copy_runtime(source: Path, destination: Path, version: str) -> None:
    source, destination = _copy_path(source), _copy_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".staging-", dir=destination.parent) as temporary:
        stage = Path(temporary) / "runtime"
        if not _complete_runtime(source):
            raise ValueError("앱에 동봉된 연결 파일을 찾지 못했습니다.")
        stage.mkdir()
        shutil.copy2(source / _EXECUTABLE, stage / _EXECUTABLE)
        shutil.copytree(source / "_internal", stage / "_internal")
        (stage / "installed-version").write_text(version, encoding="ascii")
        stage.rename(destination)


@contextmanager
def _external_environment() -> Iterator[dict[str, str]]:
    from ctypes import windll

    # A frozen process normally prepends its own DLLs to the child's search path.
    set_dll_directory = windll.kernel32.SetDllDirectoryW
    set_dll_directory(None)
    try:
        yield {**os.environ, "PYINSTALLER_RESET_ENVIRONMENT": "1"}
    finally:
        set_dll_directory(getattr(sys, "_MEIPASS", None))


def _run_external(command: list[str], *, registration: bool = False) -> int:
    with _external_environment() as environment:
        return subprocess.run(
            command, env=environment, creationflags=subprocess.CREATE_NO_WINDOW, timeout=20 if registration else None,
            stdin=subprocess.DEVNULL if registration else sys.stdin,
            stdout=subprocess.DEVNULL if registration else sys.stdout,
            stderr=subprocess.DEVNULL if registration else sys.stderr,
        ).returncode


def _desktop_codex_executable() -> str | None:
    windows = Path(os.environ.get("SystemRoot", ""))
    powershell = windows / "System32/WindowsPowerShell/v1.0/powershell.exe"
    if not powershell.is_absolute() or not powershell.is_file():
        return None
    query = ("[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); "
             "Get-AppxPackage -Name OpenAI.Codex | Sort-Object Version -Descending | Select-Object -ExpandProperty InstallLocation")
    try:
        with _external_environment() as environment:
            result = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-Command", query],
                                    env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    text=True, encoding="utf-8", timeout=8, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    except (OSError, UnicodeError, subprocess.SubprocessError):
        return None
    for line in result.stdout.splitlines():
        candidate = Path(line.strip()) / "app/resources/codex.exe"
        if candidate.is_absolute() and candidate.is_file():
            return str(candidate)
    return None


def stage_bundled_runtime(bundled: Path, root: Path, *, install: bool = False) -> Path | None:
    launcher = root / "launcher"
    if not install and not _complete_runtime(launcher):
        return None
    version = _version(__version__)
    if version is None:
        raise ValueError("현재 앱 버전으로 Codex 연결을 준비할 수 없습니다.")

    with exclusive_file_lock(root / "setup.lock"):
        if not _complete_runtime(launcher):
            _copy_runtime(bundled.parent, launcher, __version__)
        else:
            initial_version = _version((launcher / "installed-version").read_text(encoding="ascii"))
            if initial_version is None:
                raise ValueError("설치된 Codex 연결 파일의 버전을 확인할 수 없습니다.")
            _, selected = _selected_runtime(root, launcher / _EXECUTABLE, initial_version)
            if version > selected:
                _copy_runtime(bundled.parent, root / "versions" / __version__, __version__)
    return launcher / _EXECUTABLE


def register_codex_connection(bundled: Path, root: Path, codex: str, *, allow_planning: bool = False) -> None:
    launcher = stage_bundled_runtime(bundled, root, install=True)
    if launcher is None:
        raise RuntimeError("Codex 연결 파일을 설치하지 못했습니다.")
    command = [codex, "mcp", "add", "ai_work_orchestrator", "--", str(launcher), "mcp-auto"]
    if allow_planning:
        command.append("--allow-planning")
    status = _run_external(command, registration=True)
    if status:
        raise subprocess.CalledProcessError(status, command)


def connect_packaged_mcp(*, allow_planning: bool = False) -> bool:
    from .codex_sdk import installed_codex_executable

    try:
        codex = installed_codex_executable()
    except FileNotFoundError:
        codex = _desktop_codex_executable()
        if codex is None:
            return False
    register_codex_connection(Path(sys.executable), application_config_root() / "mcp", codex, allow_planning=allow_planning)
    return True


def refresh_packaged_mcp() -> None:
    stage_bundled_runtime(Path(sys.executable), application_config_root() / "mcp")


def external_connection_guide(registry: Path, *, install: bool = False) -> dict[str, object]:
    executable = Path(sys.executable)
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            launcher = stage_bundled_runtime(executable, application_config_root() / "mcp", install=install)
            executable = launcher or executable
            args = ["mcp-auto"]
        else:
            args = ["mcp"]
    else:
        args = ["-m", "ai_orchestrator.cli", "mcp"]
    args.extend(["--registry", str(registry), "--allow-control"])
    registration_args = ([] if getattr(sys, "frozen", False) else ["-m", "ai_orchestrator.cli"])
    registration_args.extend(["mcp-register", "--registry", str(registry)])
    return {"command": str(executable), "args": args, "scope": "registered_projects", "restart_required": True,
            "registration_command": sys.executable, "registration_args": registration_args}


def _windows_claude_package_families() -> tuple[str, ...]:
    windows = Path(os.environ.get("SystemRoot", ""))
    powershell = windows / "System32/WindowsPowerShell/v1.0/powershell.exe"
    if not powershell.is_absolute() or not powershell.is_file():
        raise RuntimeError("Claude 설치 정보를 확인할 Windows 도구를 찾지 못했습니다.")
    query = ("$ErrorActionPreference = 'Stop'; [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false); "
             "Get-AppxPackage -Name Claude | Select-Object -ExpandProperty PackageFamilyName")
    try:
        command = [str(powershell), "-NoProfile", "-NonInteractive", "-Command", query]
        options = {"stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE, "stderr": subprocess.DEVNULL,
                   "text": True, "encoding": "utf-8", "timeout": 8, "check": True, "creationflags": subprocess.CREATE_NO_WINDOW}
        if getattr(sys, "frozen", False):
            with _external_environment() as environment:
                result = subprocess.run(command, env=environment, **options)
        else:
            result = subprocess.run(command, **options)
    except (OSError, UnicodeError, subprocess.SubprocessError) as exc:
        raise RuntimeError("Claude 설치 정보를 확인하지 못했습니다. 연결 설정을 다시 시도해 주세요.") from exc
    families = tuple(dict.fromkeys(line.strip() for line in result.stdout.splitlines() if line.strip()))
    if any(not re.fullmatch(r"Claude_[A-Za-z0-9]+", family) for family in families):
        raise RuntimeError("Claude 설치 경로 정보를 확인해 주세요.")
    return families


def claude_desktop_config_paths() -> tuple[Path, ...]:
    """Resolve both classic and installed MSIX Claude configuration paths."""
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        paths = [root / "Claude" / "claude_desktop_config.json"]
        local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        for family in _windows_claude_package_families():
            paths.append(local / "Packages" / family / "LocalCache" / "Roaming" / "Claude" / "claude_desktop_config.json")
        return tuple(paths)
    root = (Path.home() / "Library" / "Application Support" if sys.platform == "darwin"
            else Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"))
    return (root / "Claude" / "claude_desktop_config.json",)


def register_external_connection(client: str, registry: Path) -> dict[str, object]:
    """Register the control connection without returning other client settings."""
    if client not in {"codex", "claude", "claude-code"}:
        raise ValueError("지원하는 연결 앱을 선택해 주세요.")
    guide = external_connection_guide(registry, install=True)
    if client == "claude":
        for target in claude_desktop_config_paths():
            target.parent.mkdir(parents=True, exist_ok=True)
            with exclusive_file_lock(target.with_suffix(".orchestrator.lock")):
                settings = json.loads(target.read_text(encoding="utf-8-sig")) if target.exists() else {}
                if not isinstance(settings, dict) or not isinstance(settings.get("mcpServers", {}), dict):
                    raise ValueError("Claude 연결 설정 형식을 확인해 주세요.")
                settings.setdefault("mcpServers", {})["ai_work_orchestrator"] = {"command": guide["command"], "args": guide["args"]}
                with TemporaryDirectory(prefix=".orchestrator-", dir=target.parent) as staging:
                    temporary = Path(staging) / target.name
                    temporary.write_text(json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    delays = (0.05, 0.1, 0.2, 0.4, 0.8)
                    for attempt in range(len(delays) + 1):
                        try:
                            os.replace(temporary, target)
                            break
                        except OSError as exc:
                            if getattr(exc, "winerror", None) not in {5, 32, 33} or attempt == len(delays):
                                raise
                            time.sleep(delays[attempt])
    else:
        if client == "codex":
            from .codex_sdk import installed_codex_executable

            try:
                cli = installed_codex_executable()
            except FileNotFoundError:
                cli = _desktop_codex_executable() if sys.platform == "win32" else None
            prefix = ["mcp", "add", "ai_work_orchestrator", "--"]
        else:
            cli = resolve_provider_executable("claude")
            prefix = ["mcp", "add", "--transport", "stdio", "--scope", "user", "ai_work_orchestrator", "--"]
        if not cli:
            return {"status": "client_missing", "client": client}
        command = [cli, *prefix, str(guide["command"]), *guide["args"]]
        if getattr(sys, "frozen", False) and sys.platform == "win32":
            status = _run_external(command, registration=True)
        else:
            status = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    timeout=20, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0).returncode
        if status:
            raise RuntimeError("연결 설정을 저장하지 못했습니다. 앱 설치와 관리 정책을 확인해 주세요.")
    return {"status": "registered", "client": client, "restart_required": True}


def run_packaged_mcp(args: list[str]) -> int:
    from .cli import main

    bundled = Path(sys.executable)
    current = _version(__version__)
    if current is not None:
        try:
            executable, _ = _selected_runtime(application_config_root() / "mcp", bundled, current)
            if executable != bundled:
                return _run_external([str(executable), "mcp", *args])
        except OSError:
            print("새 Codex 연결 파일을 시작하지 못했습니다. 기존 버전으로 연결합니다.", file=sys.stderr)
    return main(["mcp", *args])
