from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_orchestrator.config import ProjectConfig
from ai_orchestrator.errors import PipelineError
from ai_orchestrator.git import GitWorkspace
from ai_orchestrator.integration import IntegrationInspector, WorkspaceLayout
from ai_orchestrator.models import (
    ExecutionWorkspaceMode, IntegrationStatus, RunLockState, RunLockStatus, RunState, Stage, WorkTask,
)


def test_integration_apis_load_without_pipeline_or_store() -> None:
    script = """
import importlib.abc
import sys

class RejectCoordinator(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'ai_orchestrator.pipeline', 'ai_orchestrator.store', 'ai_orchestrator.desktop_rpc'}:
            raise AssertionError('integration APIs must not import the run coordinator or store')

sys.meta_path.insert(0, RejectCoordinator())
from ai_orchestrator.integration import (
    ConflictCandidateBuilder, ConflictInspector, ConflictResolutionService,
    IntegrationInspector, MainChangeService, WorkspaceInspector, WorkspaceLayout, WorkspaceLifecycle,
)
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_shared_layout_rejects_a_task_outside_the_run_boundary_without_creating_paths(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    layout = WorkspaceLayout(ProjectConfig(repo=repository))
    state = RunState(
        "run", "plan.md", "digest", str(repository), "main", Stage.PLANNED,
        workspace_mode=ExecutionWorkspaceMode.SHARED,
        tasks=[WorkTask("task", "task", ["general"], worktree=str(tmp_path / "foreign"))],
    )
    with pytest.raises(PipelineError, match="outside the run layout"):
        layout.shared_boundary(state)
    assert not repository.exists()


def test_active_verification_does_not_probe_main_or_operation_recovery(tmp_path: Path) -> None:
    git = Mock(spec=GitWorkspace)
    git.remote_configured.return_value = True
    operation = Mock(side_effect=AssertionError("live verification takes precedence over recovery queries"))
    project_lock = Mock(side_effect=AssertionError("live verification must not inspect project recovery locks"))
    state = RunState("run", "plan.md", "digest", str(tmp_path), "main", Stage.READY_TO_MERGE)
    inspector = IntegrationInspector(git, "origin", (tmp_path / "state",), operation, project_lock)
    control = inspector.control(state, RunLockStatus(state.id, RunLockState.ACTIVE, operation="verify"))
    assert control.status == IntegrationStatus.VERIFYING
    assert not control.can_apply_main
    operation.assert_not_called()
    project_lock.assert_not_called()
    git.ensure_repository.assert_not_called()
