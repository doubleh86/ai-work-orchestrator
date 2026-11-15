from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_orchestrator.application import OrchestratorApplication
from ai_orchestrator.config import Config, ExecutionConfig, ProjectConfig
from ai_orchestrator.registry import RegisteredProject, RegistryError


@pytest.mark.parametrize("method", ["_pipeline", "workspace_location", "project_capabilities"])
def test_changed_repository_in_project_config_is_rejected_by_every_consumer(tmp_path: Path, monkeypatch, method: str) -> None:
    project = RegisteredProject("project", tmp_path / "original", tmp_path / "config.toml", "created")
    registry = Mock()
    registry.get.return_value = project
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
