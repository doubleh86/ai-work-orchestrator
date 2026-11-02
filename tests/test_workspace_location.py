import subprocess
import tempfile
import unittest
from pathlib import Path

from ai_orchestrator.config import Config, ExecutionConfig, ProjectConfig
from ai_orchestrator.git import run_command
from ai_orchestrator.models import (
    ExecutionWorkspaceMode,
    RunState,
    Stage,
    WorkTask,
    WorkspaceLocationSource,
)
from ai_orchestrator.pipeline import Pipeline, PipelineError


class WorkspaceLocationTest(unittest.TestCase):
    def test_new_runs_in_two_projects_fix_their_own_internal_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            roots = []
            for name in ("프로젝트 하나", "project-two"):
                repo = self._repository(parent / name)
                spec = repo / "plan.md"
                spec.write_text("# 계획\n", encoding="utf-8")
                run_command(["git", "add", "plan.md"], repo)
                run_command(["git", "commit", "-m", "plan"], repo)
                pipeline = self._pipeline(repo)

                state = pipeline.prepare_planning(spec)

                self.assertIsNotNone(state.workspace_location)
                self.assertEqual(Path(state.workspace_location.root), (repo / ".ai_auto_work" / "worktree").resolve())
                self.assertEqual(state.workspace_location.source, WorkspaceLocationSource.PROJECT_DEFAULT)
                roots.append(state.workspace_location.root)
            self.assertNotEqual(*roots)

    def test_shared_preparation_uses_fixed_root_and_excludes_it_from_git(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self._repository(Path(directory) / "한글 프로젝트")
            spec = repo / "plan.md"
            spec.write_text("# 계획\n", encoding="utf-8")
            run_command(["git", "add", "plan.md"], repo)
            run_command(["git", "commit", "-m", "plan"], repo)
            pipeline = self._pipeline(repo)
            state = pipeline.prepare_planning(spec)
            state.stage = Stage.PLANNED
            state.tasks = [WorkTask("task", "Task", ["general"])]
            pipeline.store.save(state)
            worktree = pipeline._shared_run_worktree_path(state)
            try:
                pipeline._prepare_tasks(state)
                self.assertEqual(Path(state.execution_worktree), worktree)
                self.assertEqual(Path(state.tasks[0].worktree), worktree)
                status = subprocess.run(
                    ["git", "status", "--porcelain", "--untracked-files=all"], cwd=repo, check=True, text=True, capture_output=True
                ).stdout
                self.assertNotIn(".ai_auto_work", status)
                exclude = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
                self.assertIn("/.ai_auto_work/worktree/", exclude)
            finally:
                if worktree.exists():
                    pipeline.git.remove_worktree(worktree, force=True)
                if pipeline.git.branch_exists(state.execution_branch):
                    pipeline.git.delete_branch(state.execution_branch, force=True)

    def test_recorded_legacy_root_is_preserved_and_conflicts_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self._repository(Path(directory) / "repo")
            pipeline = self._pipeline(repo)
            legacy_root = repo.parent / ".ai-worktrees"
            state = RunState(
                id="legacy-run",
                spec_path="plan.md",
                spec_digest="digest",
                repo_path=str(repo),
                main_branch="main",
                stage=Stage.EXECUTING,
                workspace_mode=ExecutionWorkspaceMode.SHARED,
                execution_worktree=str(legacy_root / "legacy-run" / "work"),
                tasks=[WorkTask("task", "Task", ["general"], worktree=str(legacy_root / "legacy-run" / "work"))],
            )
            location = pipeline._workspace_location(state)
            self.assertEqual(Path(location.root), legacy_root.resolve())
            self.assertEqual(location.source, WorkspaceLocationSource.LEGACY_RECORD)

            state.tasks[0].worktree = str(repo.parent / "other" / "legacy-run" / "work")
            with self.assertRaisesRegex(PipelineError, "workspace_location_conflict"):
                pipeline._workspace_location(state)

    def test_fixed_run_location_survives_later_config_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self._repository(Path(directory) / "repo")
            original = self._pipeline(repo)
            state = RunState(
                id="fixed",
                spec_path="plan.md",
                spec_digest="digest",
                repo_path=str(repo),
                main_branch="main",
                stage=Stage.PLANNED,
                workspace_location=original._workspace_location(
                    RunState("new", "plan.md", "digest", str(repo), "main", Stage.PLANNED)
                ),
            )
            changed = Pipeline(
                Config(
                    path=repo / "changed.toml",
                    project=ProjectConfig(repo=repo, worktree_dir="custom/worktrees"),
                    execution=ExecutionConfig(),
                    agents=(),
                )
            )
            self.assertEqual(changed._workspace_location(state), state.workspace_location)
            self.assertEqual(changed._verification_worktree_path(state), Path(state.workspace_location.root) / "fixed" / ".verification")

    @staticmethod
    def _pipeline(repo: Path) -> Pipeline:
        return Pipeline(
            Config(
                path=repo / "orchestrator.toml",
                project=ProjectConfig(repo=repo),
                execution=ExecutionConfig(),
                agents=(),
            )
        )

    @staticmethod
    def _repository(repo: Path) -> Path:
        repo.mkdir(parents=True)
        run_command(["git", "init", "-b", "main"], repo)
        run_command(["git", "config", "user.name", "Test"], repo)
        run_command(["git", "config", "user.email", "test@example.com"], repo)
        (repo / ".gitignore").write_text(".ai-orchestrator/\n", encoding="utf-8")
        (repo / "README.md").write_text("base\n", encoding="utf-8")
        run_command(["git", "add", "."], repo)
        run_command(["git", "commit", "-m", "base"], repo)
        return repo


if __name__ == "__main__":
    unittest.main()
