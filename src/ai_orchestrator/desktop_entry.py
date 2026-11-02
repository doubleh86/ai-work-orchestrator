from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


class DesktopLaunchError(RuntimeError):
    pass


def run_desktop(registry_path: str | Path | None = None) -> int:
    try:
        root = _desktop_root()
        npm = _npm_executable()
        if not (root / "node_modules" / "electron").is_dir():
            raise DesktopLaunchError("Electron dependencies are not installed; run 'npm install' first")
        environment = os.environ.copy()
        if registry_path is not None and str(registry_path).strip():
            environment["AI_ORCHESTRATOR_REGISTRY"] = str(Path(registry_path).expanduser().resolve())
        completed = subprocess.run([npm, "start"], cwd=root, env=environment, check=False)
        return completed.returncode
    except DesktopLaunchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _desktop_root() -> Path:
    root = Path(__file__).resolve().parents[2]
    if not (root / "package.json").is_file():
        raise DesktopLaunchError("Electron project files were not found beside the Python package")
    return root


def _npm_executable() -> str:
    candidates = ("npm.cmd", "npm") if sys.platform == "win32" else ("npm",)
    for candidate in candidates:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise DesktopLaunchError("npm executable was not found")


if __name__ == "__main__":
    raise SystemExit(run_desktop())
