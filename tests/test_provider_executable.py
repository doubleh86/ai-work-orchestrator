import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_orchestrator import provider_executable
from ai_orchestrator.provider_executable import (
    ProviderExecutableError,
    clear_claude_executable,
    resolve_provider_executable,
    selected_claude_executable,
    set_claude_executable,
)


@pytest.mark.skipif(os.name == "nt", reason="Claude user install fallback is POSIX only")
def test_claude_user_install_is_found_when_missing_from_path(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(provider_executable, "_claude_settings_path", lambda: tmp_path / "selection.json")
    version = tmp_path / "versions" / "2.1.319"
    version.parent.mkdir()
    version.write_text("fixture", encoding="utf-8")
    version.chmod(0o755)
    launcher = tmp_path / ".local" / "bin" / "claude"
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to(version)

    with patch("ai_orchestrator.provider_executable.shutil.which", return_value=None), patch(
        "ai_orchestrator.provider_executable.Path.home", return_value=tmp_path
    ):
        assert resolve_provider_executable("claude") == str(launcher)
        assert resolve_provider_executable("other-provider") == ""


@pytest.mark.skipif(os.name == "nt", reason="Claude user install fallback is POSIX only")
def test_claude_path_precedes_user_install_and_non_executable_fallback_is_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(provider_executable, "_claude_settings_path", lambda: tmp_path / "selection.json")
    launcher = tmp_path / ".local" / "bin" / "claude"
    launcher.parent.mkdir(parents=True)
    launcher.write_text("fixture", encoding="utf-8")
    launcher.chmod(0o644)
    with patch("ai_orchestrator.provider_executable.Path.home", return_value=tmp_path), patch(
        "ai_orchestrator.provider_executable.shutil.which", return_value="/path/claude"
    ):
        assert resolve_provider_executable("claude") == "/path/claude"
    with patch("ai_orchestrator.provider_executable.Path.home", return_value=tmp_path), patch(
        "ai_orchestrator.provider_executable.shutil.which", return_value=None
    ):
        assert resolve_provider_executable("claude") == ""


def test_selected_claude_path_persists_and_blocks_silent_fallback_when_missing(tmp_path: Path, monkeypatch) -> None:
    settings = tmp_path / "app" / "claude-executable.json"
    monkeypatch.setattr(provider_executable, "_claude_settings_path", lambda: settings)
    launcher = tmp_path / "Claude Code" / ("claude.exe" if os.name == "nt" else "claude")
    launcher.parent.mkdir()
    launcher.write_text("fixture", encoding="utf-8")
    launcher.chmod(0o755)
    with patch("ai_orchestrator.provider_executable.shutil.which", return_value="/path/claude"):
        assert set_claude_executable(str(launcher)) == str(launcher)
        assert json.loads(settings.read_text(encoding="utf-8"))["path"] == str(launcher)
        assert selected_claude_executable() == str(launcher)
        assert resolve_provider_executable("claude") == str(launcher)
        launcher.unlink()
        assert resolve_provider_executable("claude") == ""
        clear_claude_executable()
        assert selected_claude_executable() == ""
        assert resolve_provider_executable("claude") == "/path/claude"


def test_invalid_selection_is_rejected_without_replacing_saved_path(tmp_path: Path, monkeypatch) -> None:
    settings = tmp_path / "app" / "claude-executable.json"
    monkeypatch.setattr(provider_executable, "_claude_settings_path", lambda: settings)
    launcher = tmp_path / ("claude.exe" if os.name == "nt" else "claude")
    launcher.write_text("fixture", encoding="utf-8")
    launcher.chmod(0o755)
    set_claude_executable(str(launcher))
    for path in ("relative/claude", str(tmp_path / "other"), str(tmp_path / "missing" / launcher.name)):
        with pytest.raises(ProviderExecutableError):
            set_claude_executable(path)
        assert selected_claude_executable() == str(launcher)
    settings.write_text('{"path": 123}', encoding="utf-8")
    with pytest.raises(ProviderExecutableError, match="설정 형식"):
        selected_claude_executable()
    clear_claude_executable()
    assert selected_claude_executable() == ""
