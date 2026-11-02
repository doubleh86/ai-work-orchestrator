from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from ai_orchestrator.desktop_entry import run_desktop


def test_launcher_runs_electron_with_selected_registry(tmp_path: Path) -> None:
    root = tmp_path / "checkout"
    (root / "node_modules" / "electron").mkdir(parents=True)
    registry = tmp_path / "projects.json"

    with (
        patch("ai_orchestrator.desktop_entry._desktop_root", return_value=root),
        patch("ai_orchestrator.desktop_entry._npm_executable", return_value="npm"),
        patch("ai_orchestrator.desktop_entry.subprocess.run") as run,
    ):
        run.return_value = subprocess.CompletedProcess(["npm", "start"], 0)

        result = run_desktop(registry)

    assert result == 0
    args, kwargs = run.call_args
    assert args[0] == ["npm", "start"]
    assert kwargs["cwd"] == root
    assert "shell" not in kwargs
    assert kwargs["env"]["AI_ORCHESTRATOR_REGISTRY"] == str(registry.resolve())


def test_launcher_reports_missing_electron_dependencies(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    root = tmp_path / "checkout"
    root.mkdir()
    with (
        patch("ai_orchestrator.desktop_entry._desktop_root", return_value=root),
        patch("ai_orchestrator.desktop_entry._npm_executable", return_value="npm"),
    ):
        result = run_desktop()

    assert result == 2
    assert "npm install" in capsys.readouterr().err
