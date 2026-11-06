"""Install the MCP runtime shipped in the Windows app for local Codex use."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

from . import __version__
from .app_paths import application_config_root
from .file_lock import exclusive_file_lock


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


def register_codex_connection(bundled: Path, root: Path, codex: str) -> None:
    launcher = stage_bundled_runtime(bundled, root, install=True)
    if launcher is None:
        raise RuntimeError("Codex 연결 파일을 설치하지 못했습니다.")
    command = [codex, "mcp", "add", "ai_work_orchestrator", "--", str(launcher), "mcp-auto"]
    status = _run_external(command, registration=True)
    if status:
        raise subprocess.CalledProcessError(status, command)


def connect_packaged_mcp() -> bool:
    from .codex_sdk import installed_codex_executable

    try:
        codex = installed_codex_executable()
    except FileNotFoundError:
        codex = _desktop_codex_executable()
        if codex is None:
            return False
    register_codex_connection(Path(sys.executable), application_config_root() / "mcp", codex)
    return True


def refresh_packaged_mcp() -> None:
    stage_bundled_runtime(Path(sys.executable), application_config_root() / "mcp")


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
