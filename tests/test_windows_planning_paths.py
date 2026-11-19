from __future__ import annotations

import os
import shutil
import stat
import tempfile
from pathlib import Path

import pytest

from ai_orchestrator.config import Config, ExecutionConfig, ProjectConfig
from ai_orchestrator.git import GitWorkspace, inspect_git_readiness, run_command
from ai_orchestrator.models import Stage
from ai_orchestrator.pipeline import Pipeline
from ai_orchestrator.planner import read_planning_document
from ai_orchestrator.windows_paths import filesystem_path


@pytest.mark.skipif(os.name != "nt", reason="requires Windows directory junctions")
def test_planning_preflight_and_state_work_beyond_windows_max_path(tmp_path, monkeypatch):
    cleaned = tmp_path / ("a" * 100)
    repo = cleaned / ("b" * 100) / ("c" * 78)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    assert len(str(repo)) >= 260
    filesystem_path(repo).mkdir(parents=True)
    try:
        run_command(["git", "init", "-b", "main"], repo)
        GitWorkspace(repo, "main").ensure_repository(non_interactive=True)
        readiness = inspect_git_readiness(repo)
        assert readiness.kind == "unborn", readiness.diagnostics
        assert os.path.samefile(readiness.repository_root, filesystem_path(repo))
        run_command([
            "git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
            "-c", f"core.hooksPath={tmp_path / 'fixture-hooks'}",
            "commit", "--allow-empty", "-m", "Planning fixture",
        ], repo)
        spec = repo / "plan.md"
        filesystem_path(spec).write_text("Fixture plan", encoding="utf-8")
        assert read_planning_document(spec) == "Fixture plan"

        pipeline = Pipeline(Config(tmp_path / "orchestrator.toml", ProjectConfig(repo), ExecutionConfig(), ()))
        state = pipeline.prepare_planning(spec)
        saved = pipeline.store.load(state.id)
        assert saved.stage == Stage.REVIEWED and saved.base_commit
        assert Path(saved.spec_snapshot_path).read_text(encoding="utf-8") == "Fixture plan"
        assert not list(tmp_path.glob("awo-*"))
    finally:
        def remove_readonly_git_object(remove, path, error):
            if not isinstance(error[1], PermissionError):
                raise error[1]
            os.chmod(path, stat.S_IWRITE)
            remove(path)

        shutil.rmtree(filesystem_path(cleaned, reserve=128), onerror=remove_readonly_git_object)
