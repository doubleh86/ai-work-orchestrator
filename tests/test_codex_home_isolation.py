from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_orchestrator.app_paths import application_config_root
from ai_orchestrator.codex_sdk import CodexSdkError, CodexSdkManager, _new_client
from ai_orchestrator.registry import default_registry_path


@pytest.mark.parametrize(("platform", "environment", "relative"), [
    ("win32", {}, "AppData/Roaming/ai-work-orchestrator"),
    ("darwin", {}, "Library/Application Support/ai-work-orchestrator"),
    ("linux", {}, ".config/ai-work-orchestrator"),
])
def test_application_root_keeps_registry_and_sdk_paths_consistent(tmp_path, platform, environment, relative):
    root = application_config_root(platform=platform, environment=environment, home=tmp_path)
    assert root == (tmp_path / relative).resolve()
    assert default_registry_path(platform=platform, environment=environment, home=tmp_path) == root / "projects.json"
    assert not root.exists()


@pytest.mark.parametrize(("platform", "variable"), [("win32", "APPDATA"), ("linux", "XDG_CONFIG_HOME")])
def test_application_root_keeps_explicit_platform_location(tmp_path, platform, variable):
    root = application_config_root(platform=platform, environment={variable: str(tmp_path / "configured")}, home=tmp_path / "user")
    assert root == (tmp_path / "configured" / "ai-work-orchestrator").resolve()


def test_registry_path_preserves_existing_file_alias_resolution(tmp_path):
    root = tmp_path / "app"
    root.mkdir()
    target = tmp_path / "existing-projects.json"
    target.write_text("{}", encoding="utf-8")
    try:
        (root / "projects.json").symlink_to(target)
    except OSError:
        pytest.skip("file symlinks are unavailable")
    with patch("ai_orchestrator.registry.application_config_root", return_value=root):
        assert default_registry_path() == target.resolve()


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_sdk_factory_isolates_home_and_credentials_without_changing_parent_environment(tmp_path, monkeypatch, platform):
    root = tmp_path / "app"
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "shared"))
    monkeypatch.setenv("CODEX_SQLITE_HOME", str(tmp_path / "shared-db"))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fixture-inherited-openai")
    monkeypatch.setenv("CODEX_API_KEY", "sk-fixture-inherited-codex")
    monkeypatch.setenv("CODEX_ACCESS_TOKEN", "fixture-inherited-token")
    with (patch("ai_orchestrator.codex_sdk.application_config_root", return_value=root),
          patch("ai_orchestrator.codex_sdk.sys.platform", platform), patch("openai_codex.Codex") as create):
        _new_client()
        _new_client()
    assert create.call_count == 2
    for call in create.call_args_list:
        config = call.args[0]
        assert config.env == {
            "CODEX_HOME": str(root / "codex"), "CODEX_SQLITE_HOME": str(root / "codex"),
            "OPENAI_API_KEY": "", "CODEX_API_KEY": "", "CODEX_ACCESS_TOKEN": "",
        }
        expected = (
            ('cli_auth_credentials_store="file"', 'features.prefer_mxc=true') if platform == "win32"
            else ('cli_auth_credentials_store="file"',)
        )
        assert config.config_overrides == expected
        assert config.codex_bin is None and config.launch_args_override is None
        assert config.client_name == "ai_work_orchestrator"
    assert (root / "codex").is_dir()
    if os.name != "nt":
        assert (root / "codex").stat().st_mode & 0o777 == 0o700
    assert os.environ["CODEX_HOME"] == str(tmp_path / "shared")
    assert os.environ["CODEX_SQLITE_HOME"] == str(tmp_path / "shared-db")
    assert os.environ["OPENAI_API_KEY"] == "sk-fixture-inherited-openai"
    assert os.environ["CODEX_API_KEY"] == "sk-fixture-inherited-codex"
    assert os.environ["CODEX_ACCESS_TOKEN"] == "fixture-inherited-token"
    assert not (tmp_path / "shared").exists()


def test_home_creation_failure_never_falls_back_to_shared_authentication(tmp_path):
    with (
        patch("ai_orchestrator.codex_sdk.application_config_root", return_value=tmp_path / "app"),
        patch.object(Path, "mkdir", side_effect=PermissionError("fixture denied")),
        patch("openai_codex.Codex") as create,
    ):
        manager = CodexSdkManager()
        try:
            state = manager.login_status()
        finally:
            manager.close()
    assert state.status == "status_error" and state.error_code == "auth_permission_denied"
    create.assert_not_called()


def test_symlink_home_is_rejected_before_runtime_start(tmp_path):
    with (
        patch("ai_orchestrator.codex_sdk.application_config_root", return_value=tmp_path / "app"),
        patch.object(Path, "is_symlink", return_value=True),
        patch("openai_codex.Codex") as create,
        pytest.raises(CodexSdkError, match="심볼릭 링크"),
    ):
        _new_client()
    create.assert_not_called()


def test_real_sdk_authentication_is_shared_only_between_orchestrator_clients(tmp_path, monkeypatch):
    shared = tmp_path / "shared-codex"
    shared.mkdir()
    # This is synthetic test data, never a user's authentication file.
    previous = json.dumps({"OPENAI_API_KEY": "sk-fixture-shared-only", "tokens": None, "last_refresh": None})
    shared_auth = shared / "auth.json"
    shared_auth.write_text(previous, encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(shared))
    monkeypatch.setenv("CODEX_SQLITE_HOME", str(shared))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fixture-inherited-openai")
    monkeypatch.setenv("CODEX_API_KEY", "sk-fixture-inherited-codex")
    monkeypatch.setenv("CODEX_ACCESS_TOKEN", "fixture-inherited-token")
    app_root = tmp_path / "app"
    with patch("ai_orchestrator.codex_sdk.application_config_root", return_value=app_root):
        manager = CodexSdkManager()
        try:
            initial = manager.login_status()
            assert initial.status == "signed_out", initial
            connected = manager.login_api_key("sk-fixture-orchestrator-only", "fixture-api-login")
            assert (connected.status, connected.auth_method) == ("connected", "api_key"), connected
            assert "sk-fixture" not in repr(connected)
            assert manager.login_status().auth_method == "api_key"
        finally:
            manager.close()
        for _ in range(2):
            other_backend = CodexSdkManager()
            try:
                status = other_backend.login_status()
                assert status.status == "connected" and status.auth_method == "api_key"
            finally:
                other_backend.close()
    assert (app_root / "codex" / "auth.json").is_file()
    assert shared_auth.read_text(encoding="utf-8") == previous
    assert os.environ["CODEX_HOME"] == str(shared)
    assert os.environ["OPENAI_API_KEY"] == "sk-fixture-inherited-openai"
