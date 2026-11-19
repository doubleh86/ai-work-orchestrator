from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_orchestrator.application import OrchestratorApplication
from ai_orchestrator.config import Config, ExecutionConfig, ProjectConfig
from ai_orchestrator.application.project_settings import registered_project_config
from ai_orchestrator.registry import ProjectRegistry, RegisteredProject, RegistryError


def test_legacy_project_uses_managed_settings_without_loading_the_checkout_config(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    checkout_config = repo / "orchestrator.toml"
    checkout_config.write_text("Repository-owned settings fixture", encoding="utf-8")
    registry = ProjectRegistry(tmp_path / "app" / "projects.json")
    project = RegisteredProject("project", repo, checkout_config, "created")
    monkeypatch.setattr("ai_orchestrator.application.project_settings.inspect_git_readiness", Mock(return_value=Mock(main_branch="trunk")))

    config = registered_project_config(project, registry)
    assert config.path == registry.managed_config_path(repo)
    assert config.project.main_branch == "trunk"
    assert checkout_config.read_text(encoding="utf-8") == "Repository-owned settings fixture"


@pytest.mark.parametrize("method", ["_pipeline", "workspace_location", "project_capabilities"])
def test_changed_repository_in_project_config_is_rejected_by_every_consumer(tmp_path: Path, monkeypatch, method: str) -> None:
    project = RegisteredProject("project", tmp_path / "original", tmp_path / "config.toml", "created")
    registry = Mock()
    registry.get.return_value = project
    registry.path = tmp_path / "projects.json"
    config = Config(
        path=project.config_path, project=ProjectConfig(repo=tmp_path / "different"), execution=ExecutionConfig(), agents=(),
    )
    load = Mock(return_value=config)
    factory = Mock()
    monkeypatch.setattr("ai_orchestrator.application.project_settings.load_config", load)
    monkeypatch.setattr("ai_orchestrator.application.service.create_pipeline", factory)
    application = OrchestratorApplication(registry, codex_sdk=Mock())
    try:
        with pytest.raises(RegistryError, match="registered project config changed repository: project"):
            getattr(application, method)("project")
        load.assert_called_once_with(project.config_path)
        factory.assert_not_called()
    finally:
        application.close()
