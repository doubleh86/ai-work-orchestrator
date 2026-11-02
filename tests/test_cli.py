import io
import json
import socket
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from ai_orchestrator.cli import main
from ai_orchestrator.models import RiskLevel, RunState, RunStep, Stage, TaskReadiness, WorkTask, WorkspaceState, WorkspaceStatus
from ai_orchestrator.pipeline import Pipeline
from ai_orchestrator.store import StateStore


class CliTest(unittest.TestCase):
    def test_cli_owns_and_closes_codex_sdk_manager(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path, _ = self._configured_store(root)
            output = io.StringIO()

            with patch("ai_orchestrator.cli.CodexSdkManager") as manager_type, redirect_stdout(output):
                exit_code = main(["--config", str(config_path), "status"])

            self.assertEqual(exit_code, 0)
            manager_type.assert_called_once_with()
            manager_type.return_value.close.assert_called_once_with()

    def test_workspace_status_supports_json_and_clear_requires_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path, _ = self._configured_store(root)
            status = WorkspaceStatus(
                run_id="run-1",
                task_id="task-1",
                state=WorkspaceState.STALE,
                run_stage="merged",
                task_status="merged",
                branch="ai/run-1/task-1",
                worktree=str(root / "worktree"),
                worktree_exists=True,
                worktree_registered=True,
                worktree_clean=True,
                branch_exists=True,
                branch_merged=True,
                cleanup_safe=True,
                reason="safe",
            )
            output = io.StringIO()
            with patch.object(Pipeline, "workspace_statuses", return_value=[status]):
                with redirect_stdout(output):
                    exit_code = main(["--config", str(config_path), "--json", "workspace", "status", "run-1"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(output.getvalue())[0]["state"], "stale")

            error = io.StringIO()
            with redirect_stderr(error):
                exit_code = main(["--config", str(config_path), "workspace", "clear", "run-1", "task-1"])

            self.assertEqual(exit_code, 2)
            self.assertIn("requires --approve", error.getvalue())

            output = io.StringIO()
            with patch.object(Pipeline, "cleanup_workspace", return_value=status) as cleanup:
                with redirect_stdout(output):
                    exit_code = main(["--config", str(config_path), "workspace", "clear", "run-1", "task-1", "--approve"])

            self.assertEqual(exit_code, 0)
            cleanup.assert_called_once_with("run-1", "task-1", approved=True)
            self.assertIn("cleanup=yes", output.getvalue())

    def test_project_commands_do_not_require_current_directory_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            config_path = repo / "orchestrator.toml"
            config_path.write_text(
                """
[project]
repo = "."

[[agents]]
id = "manual"
capabilities = ["general"]
command = []
""",
                encoding="utf-8",
            )
            registry_path = root / "projects.json"
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main(["--registry", str(registry_path), "project", "add", str(repo), "--name", "Example"])

            self.assertEqual(exit_code, 0)
            self.assertIn("Example", output.getvalue())

    def test_project_add_creates_managed_config_and_saves_planning_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            planning = repo / "Planning"
            repo.mkdir()
            planning.mkdir()
            registry_path = root / "app-data" / "projects.json"
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main(
                    [
                        "--registry",
                        str(registry_path),
                        "project",
                        "add",
                        str(repo),
                        "--name",
                        "Example",
                        "--planning-source",
                        "Planning",
                    ]
                )

            self.assertEqual(exit_code, 0)
            project = json.loads(registry_path.read_text(encoding="utf-8"))["projects"][0]
            config_path = Path(project["config_path"])
            self.assertTrue(config_path.is_file())
            self.assertTrue(config_path.is_relative_to(registry_path.parent.resolve()))
            self.assertFalse((repo / "orchestrator.toml").exists())
            self.assertEqual(Path(project["planning_source_dir"]), planning.resolve())

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["--registry", str(registry_path), "--json", "project", "list"])

            self.assertEqual(exit_code, 0)
            projects = json.loads(output.getvalue())
            self.assertEqual(projects[0]["name"], "Example")
            self.assertEqual(Path(projects[0]["repo"]), repo.resolve())

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["--registry", str(registry_path), "project", "remove", "Example"])

            self.assertEqual(exit_code, 0)
            self.assertIn("Example", output.getvalue())

    def test_desktop_command_does_not_require_current_directory_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            registry_path = Path(directory) / "projects.json"

            with patch("ai_orchestrator.desktop_entry.run_desktop", return_value=0) as run_desktop:
                exit_code = main(["--registry", str(registry_path), "desktop"])

            self.assertEqual(exit_code, 0)
            run_desktop.assert_called_once_with(str(registry_path))

    def test_status_displays_clarification_questions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path, store = self._configured_store(root)
            state = RunState(
                id="clarify",
                spec_path="requirements.txt",
                spec_digest="abc",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.NEEDS_CLARIFICATION,
                summary="알림 기능",
                planning_agent_id="planner",
                planning_provider_id="codex",
                planning_model="gpt-5.6-terra",
                planning_reasoning_effort="xhigh",
                planning_attempts=1,
                planning_questions=["실시간 알림인가요?"],
            )
            store.save(state)
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main(["--config", str(config_path), "status", state.id])

            self.assertEqual(exit_code, 0)
            self.assertIn("stage: needs_clarification", output.getvalue())
            self.assertIn("model=gpt-5.6-terra", output.getvalue())
            self.assertIn("reasoning=xhigh", output.getvalue())
            self.assertIn("실시간 알림인가요?", output.getvalue())

    def test_status_displays_task_graph_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path, store = self._configured_store(root)
            state = RunState(
                id="task-graph",
                spec_path="requirements.txt",
                spec_digest="abc",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.PLANNED,
                tasks=[
                    WorkTask(id="base", title="기반 구현", capabilities=["backend"]),
                    WorkTask(
                        id="api",
                        title="API 구현",
                        capabilities=["backend"],
                        agent_id="backend-ai",
                        provider_id="codex",
                        reasoning_effort="high",
                        dependencies=["base"],
                        expected_paths=["src/api/**"],
                        forbidden_paths=["migrations/**"],
                        verify_commands=[["python", "-m", "unittest"]],
                        risk_level=RiskLevel.HIGH,
                    ),
                ],
            )
            state.refresh_task_readiness()
            store.save(state)
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main(["--config", str(config_path), "status", state.id])

            self.assertEqual(exit_code, 0)
            rendered = output.getvalue()
            self.assertIn("readiness=blocked", rendered)
            self.assertIn("blocked-by=base", rendered)
            self.assertIn("risk=high", rendered)
            self.assertIn("expected=src/api/**", rendered)
            self.assertIn("reasoning=high", rendered)

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(["--config", str(config_path), "--json", "status", state.id])

            self.assertEqual(exit_code, 0)
            task = json.loads(output.getvalue())["tasks"][1]
            self.assertEqual(task["readiness"], TaskReadiness.BLOCKED)
            self.assertEqual(task["blocked_by"], ["base"])
            self.assertEqual(task["verify_commands"][0][0], "python")

    def test_clarify_command_routes_answers_to_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path, _ = self._configured_store(root)
            answers = root / "answers.md"
            answers.write_text("비동기 조회", encoding="utf-8")
            state = RunState(
                id="clarify",
                spec_path="requirements.txt",
                spec_digest="abc",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.PLANNED,
                summary="알림 기능",
            )
            output = io.StringIO()

            with patch.object(Pipeline, "clarify", return_value=state) as clarify:
                with redirect_stdout(output):
                    exit_code = main(["--config", str(config_path), "clarify", state.id, str(answers)])

            self.assertEqual(exit_code, 0)
            clarify.assert_called_once_with(state.id, str(answers))
            self.assertIn("stage: planned", output.getvalue())

    def test_lock_status_supports_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path, store = self._configured_store(root)
            self._save_run(store)
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main(["--config", str(config_path), "--json", "lock", "status", "run-1"])

            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(output.getvalue())["state"], "unlocked")

    def test_lock_clear_requires_approval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path, store = self._configured_store(root)
            self._save_run(store)
            self._write_stale_lock(store)
            error = io.StringIO()

            with redirect_stderr(error):
                exit_code = main(["--config", str(config_path), "lock", "clear", "run-1"])

            self.assertEqual(exit_code, 2)
            self.assertIn("requires --approve", error.getvalue())
            self.assertTrue(store.lock_path("run-1").exists())

            output = io.StringIO()
            with patch.object(StateStore, "_pid_is_alive", return_value=False):
                with redirect_stdout(output):
                    exit_code = main(["--config", str(config_path), "lock", "clear", "run-1", "--approve"])

            self.assertEqual(exit_code, 0)
            self.assertIn("lock: unlocked", output.getvalue())
            self.assertFalse(store.lock_path("run-1").exists())

    def test_resume_command_restores_verification_stage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path, store = self._configured_store(root)
            state = RunState(
                id="run-1",
                spec_path="plan.md",
                spec_digest="abc",
                repo_path=str(root),
                main_branch="main",
                stage=Stage.FAILED,
                failed_step=RunStep.VERIFY,
                failure_message="verification failed",
            )
            store.save(state)
            output = io.StringIO()

            with redirect_stdout(output):
                exit_code = main(["--config", str(config_path), "--json", "resume", state.id])

            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(output.getvalue())["stage"], "merged")

    @staticmethod
    def _configured_store(root: Path) -> tuple[Path, StateStore]:
        config_path = root / "orchestrator.toml"
        config_path.write_text(
            """
[project]
repo = "."

[[agents]]
id = "manual"
capabilities = ["general"]
command = []
""",
            encoding="utf-8",
        )
        return config_path, StateStore(root / ".ai-orchestrator")

    @staticmethod
    def _save_run(store: StateStore) -> None:
        store.save(RunState(id="run-1", spec_path="plan.md", spec_digest="abc", repo_path="repo", main_branch="main", stage=Stage.PLANNED))

    @staticmethod
    def _write_stale_lock(store: StateStore) -> None:
        path = store.lock_path("run-1")
        path.write_text(
            json.dumps(
                {
                    "token": "token",
                    "pid": 999999,
                    "host": socket.gethostname(),
                    "operation": "execute",
                    "acquired_at": "2026-08-25T00:00:00+00:00",
                }
            )
            + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
