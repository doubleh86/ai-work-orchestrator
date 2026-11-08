from __future__ import annotations

import subprocess
import json
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
    mcp_bundle.register_codex_connection(bundled, root, "codex.exe", allow_planning=True)
    base_command = ["codex.exe", "mcp", "add", "ai_work_orchestrator", "--", str(launcher), "mcp-auto"]
    assert commands == [base_command, [*base_command, "--allow-planning"]]
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


def test_claude_store_and_classic_configs_keep_their_own_settings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(mcp_bundle.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(mcp_bundle, "_windows_claude_package_families", lambda: ("Claude_fixture",))
    classic = tmp_path / "roaming" / "Claude" / "claude_desktop_config.json"
    store = tmp_path / "local" / "Packages" / "Claude_fixture" / "LocalCache" / "Roaming" / "Claude" / classic.name
    for path, label in ((classic, "classic"), (store, "store")):
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"theme": label, "mcpServers": {label: {"command": label}}}), encoding="utf-8")
    assert mcp_bundle.claude_desktop_config_paths() == (classic, store)
    registry = tmp_path / "projects.json"
    result = mcp_bundle.register_external_connection("claude", registry)
    assert result["status"] == "registered" and result["restart_required"]
    for path, label in ((classic, "classic"), (store, "store")):
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["theme"] == label and saved["mcpServers"][label] == {"command": label}
        assert saved["mcpServers"]["ai_work_orchestrator"]["args"][-3:] == ["--registry", str(registry), "--allow-control"]
        assert ("store" if label == "classic" else "classic") not in saved["mcpServers"]


def test_claude_store_config_is_created_even_when_claude_has_not_created_one(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(mcp_bundle.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(mcp_bundle, "_windows_claude_package_families", lambda: ("Claude_fixture",))
    assert mcp_bundle.register_external_connection("claude", tmp_path / "projects.json")["status"] == "registered"
    assert all(path.is_file() for path in mcp_bundle.claude_desktop_config_paths())


def test_claude_package_discovery_failure_does_not_report_saved_settings(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(mcp_bundle.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "roaming"))
    def fail():
        raise RuntimeError("fixture package query failure")
    monkeypatch.setattr(mcp_bundle, "_windows_claude_package_families", fail)
    with pytest.raises(RuntimeError, match="package query"):
        mcp_bundle.register_external_connection("claude", tmp_path / "projects.json")
    assert not (tmp_path / "roaming").exists()


def test_prompt_registration_helper_uses_the_exact_client_and_registry(tmp_path: Path, monkeypatch, capsys) -> None:
    from ai_orchestrator.cli import main

    calls = []
    def register(client, registry):
        calls.append((client, registry))
        return {"status": "registered", "client": client, "restart_required": True}
    monkeypatch.setattr(mcp_bundle, "register_external_connection", register)
    registry = (tmp_path / "project data" / "projects.json").resolve()
    guide = mcp_bundle.external_connection_guide(registry)
    assert guide["registration_args"][:2] == ["-m", "ai_orchestrator.cli"]
    assert main([*guide["registration_args"][2:], "--client", "claude"]) == 0
    assert calls == [("claude", registry)]
    assert json.loads(capsys.readouterr().out)["status"] == "registered"
    monkeypatch.setattr(mcp_bundle, "register_external_connection", lambda *_: {"status": "client_missing"})
    assert main(["mcp-register", "--registry", str(registry), "--client", "codex"]) == 2


def test_claude_code_registration_uses_resolved_user_install(tmp_path: Path, monkeypatch) -> None:
    commands = []
    monkeypatch.setattr(mcp_bundle, "external_connection_guide", lambda *_args, **_kwargs: {"command": "orchestrator", "args": ["mcp"]})
    monkeypatch.setattr(mcp_bundle, "resolve_provider_executable", lambda _name: "/local/claude")

    def run(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(mcp_bundle.subprocess, "run", run)
    result = mcp_bundle.register_external_connection("claude-code", tmp_path / "projects.json")
    assert result["status"] == "registered"
    assert commands[0][:3] == ["/local/claude", "mcp", "add"]


def test_frozen_backend_forwards_registration_to_cli(monkeypatch) -> None:
    import runpy
    import ai_orchestrator.cli

    entry = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "desktop_backend.py"))
    calls = []
    monkeypatch.setattr(ai_orchestrator.cli, "main", lambda args: calls.append(args) or 0)
    args = ["mcp-register", "--client", "claude"]
    assert entry["main"](args) == 0 and calls == [args]
