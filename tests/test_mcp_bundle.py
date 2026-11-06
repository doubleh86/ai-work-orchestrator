from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ai_orchestrator import mcp_bundle


def _bundle(directory: Path, content: bytes) -> Path:
    (directory / "_internal").mkdir(parents=True)
    executable = directory / "ai-orchestrator-backend.exe"
    executable.write_bytes(content)
    return executable


def test_app_startup_prepares_only_registered_connections(tmp_path: Path) -> None:
    root = tmp_path / "user" / "mcp"
    bundled = _bundle(tmp_path / "app", b"bundled fixture")
    assert mcp_bundle.stage_bundled_runtime(bundled, root) is None
    assert not root.exists()


def test_registration_and_app_upgrade_reuse_launcher_and_keep_open_runtime(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "user" / "mcp"
    bundled = _bundle(tmp_path / "app", b"bundled fixture")
    commands = []

    def register(command: list[str], *, registration: bool) -> int:
        assert registration
        commands.append(command)
        return 0

    monkeypatch.setattr(mcp_bundle, "_run_external", register)
    monkeypatch.setattr(mcp_bundle, "__version__", "0.4.0")
    mcp_bundle.register_codex_connection(bundled, root, "codex.exe")
    launcher = root / "launcher" / bundled.name
    assert launcher.read_bytes() == b"bundled fixture"

    newer = _bundle(tmp_path / "new app", b"new app fixture")
    monkeypatch.setattr(mcp_bundle, "__version__", "0.5.0")
    assert mcp_bundle.stage_bundled_runtime(newer, root) == launcher
    assert len(commands) == 1
    assert launcher.read_bytes() == b"bundled fixture"
    selected, version = mcp_bundle._selected_runtime(root, launcher, (0, 4, 0))
    assert version == (0, 5, 0) and selected.read_bytes() == b"new app fixture"

    monkeypatch.setattr(mcp_bundle, "__version__", "0.4.0")
    mcp_bundle.register_codex_connection(bundled, root, "codex.exe")
    assert commands == [["codex.exe", "mcp", "add", "ai_work_orchestrator", "--", str(launcher), "mcp-auto"]] * 2
    assert mcp_bundle._selected_runtime(root, launcher, (0, 4, 0)) == (selected, version)


def test_incomplete_upgrade_does_not_replace_existing_runtime(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "user" / "mcp"
    bundled = _bundle(tmp_path / "app", b"bundled fixture")
    monkeypatch.setattr(mcp_bundle, "__version__", "0.4.0")
    launcher = mcp_bundle.stage_bundled_runtime(bundled, root, install=True)
    monkeypatch.setattr(mcp_bundle, "__version__", "0.4.1")
    with pytest.raises(ValueError, match="동봉된 연결 파일"):
        mcp_bundle.stage_bundled_runtime(tmp_path / "missing" / bundled.name, root)
    assert launcher is not None and launcher.read_bytes() == b"bundled fixture"
    assert mcp_bundle._selected_runtime(root, launcher, (0, 4, 0)) == (launcher, (0, 4, 0))
    assert list((root / "versions").iterdir()) == []


def test_failed_codex_command_does_not_report_registration(tmp_path: Path, monkeypatch) -> None:
    bundled = _bundle(tmp_path / "app", b"bundled fixture")
    monkeypatch.setattr(mcp_bundle, "_run_external", lambda *args, **kwargs: 3)
    with pytest.raises(subprocess.CalledProcessError) as failure:
        mcp_bundle.register_codex_connection(bundled, tmp_path / "mcp", "codex.exe")
    assert failure.value.returncode == 3
