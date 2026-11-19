"""Launch project checks under a filesystem and network policy owned by the app."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from ..codex_sdk import installed_codex_executable
from ..execution_control import CancellationSignal
from ..git import GitError, run_command
from ..process_environment import runtime_environment

_VERIFICATION_OVERRIDES = frozenset({"DOTNET_CLI_USE_MSBUILD_SERVER", "MSBUILDUSESERVER", "MSBUILDDISABLENODEREUSE"})
_RUNTIME_TOOLS = ("python", "python3", "node", "dotnet")


def _runtime_roots(path: str, blocked_roots: tuple[Path, ...]) -> dict[str, Path]:
    roots = {}
    home = Path.home().resolve()
    for name in _RUNTIME_TOOLS:
        found = shutil.which(name, path=path)
        if not found or not Path(found).is_absolute():
            continue
        root = Path(found).resolve().parent
        if home.is_relative_to(root) or root == Path(root.anchor) or any(
            blocked.is_relative_to(root) or root.is_relative_to(blocked) for blocked in blocked_roots
        ):
            continue
        roots[name] = root
    return roots


def _windows_node_command(command: Sequence[str], roots: Mapping[str, Path]) -> Sequence[str]:
    if os.name != "nt" or not command or "node" not in roots:
        return command
    executable = Path(command[0])
    name = executable.stem.casefold()
    if executable.parent != Path(".") or name not in {"npm", "npx"}:
        return command
    node_root = roots["node"]
    entry = node_root / "node_modules" / "npm" / "bin" / f"{name}-cli.js"
    if entry.is_file():
        return str(node_root / "node.exe"), str(entry), *command[1:]
    return command


@dataclass(frozen=True, slots=True)
class VerificationSandbox:
    repo: Path
    state_root: Path

    def execute(
        self, command: Sequence[str], cwd: Path, *, timeout_seconds: float,
        cancel_signal: CancellationSignal | None, environment_overrides: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        work = cwd.resolve(strict=True)
        repo = self.repo.resolve(strict=True)
        try:
            launcher = Path(installed_codex_executable()).resolve(strict=True)
        except OSError as exc:
            raise GitError("검증 격리를 시작할 수 없습니다. 작업 PC의 Codex CLI 설치를 확인해 주세요.") from exc
        if launcher.is_relative_to(repo) or launcher.is_relative_to(work):
            raise GitError("검증 격리 실행 파일은 프로젝트와 작업 폴더 밖에 있어야 합니다.")
        parent = Path(tempfile.gettempdir()).resolve()
        if parent.is_relative_to(repo) or parent.is_relative_to(work):
            raise GitError("검증 임시 폴더는 프로젝트와 작업 폴더 밖에 있어야 합니다.")
        with tempfile.TemporaryDirectory(prefix="awo-check-", dir=parent) as folder:
            scratch = Path(folder)
            writable_tmp = scratch / "tmp"
            writable_tmp.mkdir()
            sandbox_home = scratch / "codex"
            sandbox_home.mkdir()
            profile = f"awo-check-{uuid.uuid4().hex}"
            environment = runtime_environment()
            private_state = self.state_root.resolve()
            tool_roots = _runtime_roots(environment.get("PATH", ""), (repo, work, private_state))
            fields = {
                ":root": "deny", ":minimal": "read", **dict.fromkeys(map(str, tool_roots.values()), "read"),
                str(work): "write", str(writable_tmp): "write", str(private_state): "deny", str(work / ".git"): "deny",
            }
            filesystem = ", ".join(f"{json.dumps(path, ensure_ascii=False)}={json.dumps(mode)}" for path, mode in fields.items())
            settings = f"permissions.{profile}={{filesystem={{{filesystem}}}, network={{enabled=false}}}}"
            arguments = [
                str(launcher), "sandbox", "-P", profile, "-c", settings, "-c", "project_root_markers=[]", "-C", str(work),
            ]
            if sys.platform == "win32":
                arguments.extend(("-c", "features.prefer_mxc=true"))
            arguments.extend(("--", *_windows_node_command(command, tool_roots)))
            environment["CODEX_HOME"] = str(sandbox_home)
            environment.update(dict.fromkeys(("TMPDIR", "TEMP", "TMP"), str(writable_tmp)))
            environment["DOTNET_CLI_HOME"] = str(writable_tmp)
            environment["NPM_CONFIG_CACHE"] = str(writable_tmp / "npm")
            if sys.platform == "win32":
                # Windows' restricted filesystem denies listing drive roots that Node's realpath otherwise probes.
                environment["NODE_OPTIONS"] = "--preserve-symlinks --preserve-symlinks-main"
            environment.update({name: value for name, value in (environment_overrides or {}).items() if name in _VERIFICATION_OVERRIDES})
            # Avoid resolution of the trusted launcher or its DLLs from the worktree.
            return run_command(
                arguments, scratch, check=False, non_interactive=True, timeout_seconds=timeout_seconds, encoding="utf-8",
                cancel_signal=cancel_signal, base_environment=environment,
            )
