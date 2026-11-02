import tempfile
import unittest
from pathlib import Path

from ai_orchestrator.config import (
    DEFAULT_WORKTREE_DIR,
    ConfigError,
    ProjectConfig,
    create_default_config,
    load_config,
    resolve_workspace_location,
    supported_models,
    supported_reasoning_efforts,
)
from ai_orchestrator.models import WorkspaceLocationSource


class ConfigTest(unittest.TestCase):
    def test_creates_loadable_default_config_outside_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            config_path = root / "app-data" / "orchestrator.toml"

            created = create_default_config(config_path, repo)
            config = load_config(created)

            self.assertEqual(created, config_path.resolve())
            self.assertEqual(config.project.repo, repo.resolve())
            self.assertEqual(config.planning.agent_id, "codex-general")
            self.assertTrue(config.planning.reuse_results)
            self.assertEqual(config.planning.timeout_seconds, 600)
            self.assertEqual({agent.provider_id for agent in config.agents}, {"codex", "claude"})
            codex = next(agent for agent in config.agents if agent.provider_id == "codex")
            self.assertEqual(codex.command, ())
            self.assertEqual(codex.model, "gpt-6.1-sol")
            self.assertEqual(codex.review_command, ())
            self.assertEqual(codex.sandbox_mode, "workspace-write")
            self.assertEqual(codex.approval_mode, "auto-review")
            self.assertEqual(codex.review_sandbox_mode, "read-only")
            self.assertEqual(codex.review_approval_mode, "deny-all")
            self.assertEqual(config.execution.verify_commands, ())
            self.assertEqual(config.execution.task_verify_command_timeout_seconds, 900)
            self.assertEqual(config.execution.task_verify_total_timeout_seconds, 1800)
            self.assertEqual(config.execution.integration_verify_command_timeout_seconds, 600)
            self.assertEqual(config.execution.integration_verify_total_timeout_seconds, 1800)
            self.assertEqual(config.execution.verification_repair_limit, 2)
            self.assertEqual(config.project.worktree_dir, DEFAULT_WORKTREE_DIR)
            self.assertIn('worktree_dir = ".ai_auto_work/worktree"', config_path.read_text(encoding="utf-8"))
            self.assertFalse((repo / "orchestrator.toml").exists())
            with self.assertRaisesRegex(ConfigError, "already exists"):
                create_default_config(config_path, repo)

    def test_resolves_new_and_legacy_defaults_inside_each_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("프로젝트 A", "project-b"):
                repo = root / name
                repo.mkdir()
                for configured in (DEFAULT_WORKTREE_DIR, ".ai-worktrees"):
                    with self.subTest(project=name, configured=configured):
                        location = resolve_workspace_location(ProjectConfig(repo=repo, worktree_dir=configured))
                        self.assertEqual(Path(location.root), (repo / ".ai_auto_work" / "worktree").resolve())
                        self.assertEqual(location.source, WorkspaceLocationSource.PROJECT_DEFAULT)
                        self.assertEqual(location.notice_code, "legacy_default_alias" if configured == ".ai-worktrees" else "")

    def test_preserves_custom_relative_and_absolute_worktree_locations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            relative = resolve_workspace_location(ProjectConfig(repo=repo, worktree_dir="custom/worktrees"))
            absolute_root = root / "absolute-worktrees"
            absolute = resolve_workspace_location(ProjectConfig(repo=repo, worktree_dir=str(absolute_root)))
            self.assertEqual(Path(relative.root), (root / "custom" / "worktrees").resolve())
            self.assertEqual(Path(absolute.root), absolute_root.resolve())
            self.assertEqual(relative.source, WorkspaceLocationSource.CUSTOM_LEGACY)
            self.assertEqual(absolute.source, WorkspaceLocationSource.CUSTOM_LEGACY)

    def test_reports_provider_model_presets_with_configured_model_first(self) -> None:
        self.assertEqual(
            supported_models("codex", ("project-codex",)),
            ("project-codex", "gpt-6.1-sol", "gpt-6.1-terra", "gpt-6-luna"),
        )
        self.assertIn("claude-opus-5", supported_models("claude"))
        self.assertIn("claude-opus-5-5", supported_models("claude"))
        self.assertEqual(supported_models("claude", ("claude-opus-5-5",))[0], "claude-opus-5-5")
        self.assertEqual(supported_models("claude", ("claude-opus-5-5",)).count("claude-opus-5-5"), 1)
        self.assertNotIn("gpt-5.6-sol", supported_models("codex"))
        self.assertNotIn("gpt-6-sol", supported_models("codex"))
        self.assertNotIn("gpt-6-astra", supported_models("codex"))
        self.assertIn("gpt-6-luna", supported_models("codex"))
        self.assertEqual(supported_models("codex", ("gpt-5.6-sol",))[0], "gpt-5.6-sol")
        self.assertEqual(supported_models("codex", ("gpt-6-astra",)).count("gpt-6-astra"), 1)
        self.assertEqual(supported_models("custom", ("local-model",)), ("local-model",))

    def test_reports_provider_and_model_reasoning_efforts(self) -> None:
        self.assertEqual(supported_reasoning_efforts("codex", "gpt-6-astra"), ("low", "medium", "high", "xhigh", "max"))
        self.assertEqual(supported_reasoning_efforts("codex", "gpt-5.6-sol"), ("low", "medium", "high", "xhigh", "max", "ultra"))
        self.assertEqual(supported_reasoning_efforts("codex", "gpt-5.6-terra"), ("low", "medium", "high", "xhigh", "max", "ultra"))
        self.assertEqual(supported_reasoning_efforts("codex", "gpt-5.6-luna"), ("low", "medium", "high", "xhigh", "max"))
        self.assertEqual(supported_reasoning_efforts("codex", "gpt-6-sol"), ("low", "medium", "high", "xhigh", "max"))
        self.assertEqual(supported_reasoning_efforts("codex", "gpt-6.1-sol"), ("low", "medium", "high", "xhigh", "max"))
        self.assertEqual(supported_reasoning_efforts("codex", "gpt-6.1-terra"), ("low", "medium", "high", "xhigh", "max", "ultra"))
        self.assertEqual(supported_reasoning_efforts("codex", "gpt-6-luna"), ("low", "medium", "high", "xhigh", "max"))
        self.assertEqual(supported_reasoning_efforts("claude", "sonnet"), ("low", "medium", "high", "xhigh", "max"))

    def test_loads_relative_repo_and_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "repo").mkdir()
            config_path = root / "orchestrator.toml"
            config_path.write_text(
                """
[project]
repo = "repo"

[execution]
agent_timeout_seconds = 45
task_verify_command_timeout_seconds = 12
task_verify_total_timeout_seconds = 34
integration_verify_command_timeout_seconds = 56
integration_verify_total_timeout_seconds = 78
verification_repair_limit = 1
verify_commands = [["python3", "-m", "unittest"]]

[[agents]]
id = "general"
capabilities = ["general"]
command = "tool --flag"
""",
                encoding="utf-8",
            )

            config = load_config(config_path)

        self.assertEqual(config.project.repo, (root / "repo").resolve())
        self.assertEqual(config.agents[0].command, ("tool", "--flag"))
        self.assertEqual(config.execution.verify_commands[0], ("python3", "-m", "unittest"))
        self.assertEqual(config.execution.agent_timeout_seconds, 45)
        self.assertEqual(config.execution.task_verify_command_timeout_seconds, 12)
        self.assertEqual(config.execution.task_verify_total_timeout_seconds, 34)
        self.assertEqual(config.execution.integration_verify_command_timeout_seconds, 56)
        self.assertEqual(config.execution.integration_verify_total_timeout_seconds, 78)
        self.assertEqual(config.execution.verification_repair_limit, 1)

    def test_loads_codex_sdk_profiles_without_commands(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "codex-sdk.toml"
            path.write_text(
                """
[[agents]]
id = "general"
provider = "codex"
capabilities = ["general"]
sandbox_mode = "danger-full-access"
approval_mode = "deny-all"
review_sandbox_mode = "read-only"
review_approval_mode = "auto-review"
""",
                encoding="utf-8",
            )

            config = load_config(path)

        agent = config.agents[0]
        self.assertEqual(agent.command, ())
        self.assertEqual(agent.sandbox_mode, "danger-full-access")
        self.assertEqual(agent.approval_mode, "deny-all")
        self.assertEqual(agent.review_sandbox_mode, "read-only")
        self.assertEqual(agent.review_approval_mode, "auto-review")

    def test_legacy_codex_commands_are_never_executed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy-codex.toml"
            path.write_text(
                """
[[agents]]
id = "general"
provider = "codex"
capabilities = ["general"]
command = ["codex", "exec", "-"]
review_command = ["codex", "exec", "--sandbox", "read-only", "-"]
""",
                encoding="utf-8",
            )

            config = load_config(path)

        self.assertEqual(config.agents[0].command, ())
        self.assertEqual(config.agents[0].review_command, ())

    def test_rejects_unknown_codex_sdk_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid-codex.toml"
            path.write_text(
                """
[[agents]]
id = "general"
provider = "codex"
capabilities = ["general"]
sandbox_mode = "unrestricted"
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "sandbox_mode"):
                load_config(path)

    def test_requires_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.toml"
            path.write_text("[project]\nrepo = '.'\n", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)

    def test_loads_multi_provider_routing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "routing.toml"
            path.write_text(
                """
[routing]
default_provider = "codex"
review_required = true
max_review_cycles = 2

[[routing.rules]]
capabilities = ["security", "docs"]
provider = "claude"

[[agents]]
id = "codex-agent"
provider = "codex"
capabilities = ["general"]
review_sandbox_mode = "read-only"
review_approval_mode = "deny-all"

[[agents]]
id = "claude-agent"
provider = "claude"
model = "sonnet"
capabilities = ["general", "security"]
command = ["claude", "-p"]
""",
                encoding="utf-8",
            )

            config = load_config(path)

        self.assertEqual(config.routing.default_provider, "codex")
        self.assertTrue(config.routing.review_required)
        self.assertEqual(config.routing.rules[0].provider_id, "claude")
        self.assertEqual(config.agents[1].model, "sonnet")
        self.assertEqual(config.agents[0].review_command, ())
        self.assertEqual(config.agents[0].review_sandbox_mode, "read-only")

    def test_review_requires_two_providers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.toml"
            path.write_text(
                """
[routing]
default_provider = "codex"
review_required = true

[[agents]]
id = "codex-agent"
provider = "codex"
capabilities = ["general"]
""",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ConfigError, "at least two providers"):
                load_config(path)

    def test_agent_timeout_must_be_positive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.toml"
            path.write_text(
                """
[execution]
agent_timeout_seconds = 0

[[agents]]
id = "general"
capabilities = ["general"]
command = ["tool"]
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "positive integer"):
                load_config(path)

    def test_loads_structured_planning_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "planning.toml"
            path.write_text(
                """
[planning]
agent = "planner"
max_attempts = 3
reuse_results = false
timeout_seconds = 75

[[agents]]
id = "planner"
provider = "codex"
capabilities = ["planning", "general"]
review_sandbox_mode = "read-only"
review_approval_mode = "deny-all"
""",
                encoding="utf-8",
            )

            config = load_config(path)

        self.assertEqual(config.planning.agent_id, "planner")
        self.assertEqual(config.planning.max_attempts, 3)
        self.assertFalse(config.planning.reuse_results)
        self.assertEqual(config.planning.timeout_seconds, 75)

    def test_planning_timeout_must_be_positive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "planning.toml"
            path.write_text(
                """
[planning]
timeout_seconds = 0

[[agents]]
id = "general"
capabilities = ["general"]
command = ["tool"]
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "positive integer"):
                load_config(path)

    def test_rejects_unknown_structured_planning_agent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "planning.toml"
            path.write_text(
                """
[planning]
agent = "missing"

[[agents]]
id = "worker"
capabilities = ["general"]
command = ["tool"]
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "planning agent not found"):
                load_config(path)

    def test_rejects_structured_planning_agent_without_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "planning.toml"
            path.write_text(
                """
[planning]
agent = "manual"

[[agents]]
id = "manual"
capabilities = ["general"]
command = []
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "requires a command"):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
