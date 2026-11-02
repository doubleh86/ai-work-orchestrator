import json
import tempfile
import unittest
from pathlib import Path

from ai_orchestrator.code_style import ProjectCodeStylePreference
from ai_orchestrator.registry import ProjectRegistry, RegistryError, default_registry_path


class ProjectRegistryTest(unittest.TestCase):
    def test_code_style_preference_is_revisioned_and_project_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._project(root, "repo")
            (repo / "Docs").mkdir()
            (repo / "Docs" / "Style.md").write_text("# Style\n", encoding="utf-8")
            registry = ProjectRegistry(root / "projects.json")
            project = registry.add("Example", repo)
            preference = ProjectCodeStylePreference(
                mode="repository_only",
                fallback_by_language={},
                custom_instruction_paths=("Docs\\Style.md",),
            )

            updated = registry.update_code_style_preference("Example", preference, expected_revision=0)

            self.assertEqual(updated.code_style_preference_revision, 1)
            self.assertEqual(updated.code_style_preference.custom_instruction_paths, ("Docs/Style.md",))
            self.assertEqual(ProjectRegistry(registry.path).get("Example"), updated)
            with self.assertRaisesRegex(RegistryError, "최신 설정"):
                registry.update_code_style_preference("Example", preference, expected_revision=0)
            self.assertEqual(project.code_style_preference_revision, 0)

    def test_dotnet_setting_persists_per_project_and_can_return_to_auto(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = ProjectRegistry(root / "projects.json")
            for name in ("first", "second"):
                repo = root / name
                repo.mkdir()
                (repo / "orchestrator.toml").write_text("config", encoding="utf-8")
                registry.add(name, repo)
            executable = root / "dotnet.exe"
            executable.touch()
            updated = registry.update_dotnet("FIRST", str(executable))
            self.assertEqual(updated.dotnet_executable, str(executable.resolve()))
            self.assertEqual(ProjectRegistry(registry.path).get("first"), updated)
            self.assertEqual(registry.get("second").dotnet_executable, "")
            for invalid in (
                "dotnet",
                str(root / "missing" / "dotnet.exe"),
                str(root / "projects.json"),
            ):
                with self.subTest(path=invalid), self.assertRaises(RegistryError):
                    registry.update_dotnet("first", invalid)
            self.assertEqual(registry.get("first"), updated)
            self.assertEqual(registry.update_dotnet("first", "").dotnet_executable, "")
            raw = json.loads(registry.path.read_text(encoding="utf-8"))
            for project in raw["projects"]:
                project.pop("dotnet_executable")
            registry.path.write_text(json.dumps(raw), encoding="utf-8")
            self.assertEqual(registry.get("first").dotnet_executable, "")

    def test_default_registry_path_uses_platform_conventions(self) -> None:
        home = Path("/users/test")
        self.assertEqual(
            default_registry_path(platform="darwin", environment={}, home=home),
            Path("/users/test/Library/Application Support/ai-work-orchestrator/projects.json").resolve(),
        )
        self.assertEqual(
            default_registry_path(platform="win32", environment={"APPDATA": "C:/Users/test/AppData/Roaming"}, home=home),
            Path("C:/Users/test/AppData/Roaming/ai-work-orchestrator/projects.json").resolve(),
        )
        self.assertEqual(
            default_registry_path(platform="linux", environment={"XDG_CONFIG_HOME": "/users/test/config"}, home=home),
            Path("/users/test/config/ai-work-orchestrator/projects.json").resolve(),
        )

    def test_add_list_get_and_remove_project_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            config = repo / "orchestrator.toml"
            config.write_text("config", encoding="utf-8")
            registry = ProjectRegistry(root / "registry" / "projects.json")

            project = registry.add("Example", repo)

            self.assertEqual(project.name, "Example")
            self.assertEqual(registry.get("example"), project)
            self.assertEqual(registry.list(), [project])
            self.assertFalse(registry.path.with_suffix(".tmp").exists())
            raw = json.loads(registry.path.read_text(encoding="utf-8"))
            self.assertEqual(raw["schema_version"], 3)

            removed = registry.remove("EXAMPLE")

            self.assertEqual(removed, project)
            self.assertEqual(registry.list(), [])

    def test_managed_config_path_and_planning_source_are_project_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._project(root, "repo")
            planning = root / "planning"
            planning.mkdir()
            registry = ProjectRegistry(root / "app" / "projects.json")

            first_path = registry.managed_config_path(repo)
            project = registry.add("Example", repo)
            updated = registry.update_planning_source("Example", planning)

            self.assertEqual(first_path, registry.managed_config_path(repo))
            self.assertTrue(first_path.is_relative_to(registry.path.parent))
            self.assertEqual(updated.planning_source_dir, planning.resolve())
            self.assertEqual(registry.get("Example").planning_source_dir, planning.resolve())
            self.assertEqual(project.planning_source_dir, None)

    def test_reads_version_one_registry_without_planning_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self._project(root, "repo")
            path = root / "projects.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "projects": [
                            {
                                "name": "Example",
                                "repo": str(repo),
                                "config_path": str(repo / "orchestrator.toml"),
                                "created_at": "2026-08-27T00:00:00+00:00",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            project = ProjectRegistry(path).get("Example")

            self.assertIsNone(project.planning_source_dir)

    def test_rejects_duplicate_name_and_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self._project(root, "first")
            second = self._project(root, "second")
            registry = ProjectRegistry(root / "projects.json")
            registry.add("Project", first)

            with self.assertRaisesRegex(RegistryError, "name already"):
                registry.add("project", second)
            with self.assertRaisesRegex(RegistryError, "repository already"):
                registry.add("Different", first)

    def test_corrupt_registry_is_not_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "projects.json"
            path.write_text("not-json", encoding="utf-8")
            registry = ProjectRegistry(path)

            with self.assertRaisesRegex(RegistryError, "invalid project registry"):
                registry.list()

    @staticmethod
    def _project(root: Path, name: str) -> Path:
        repo = root / name
        repo.mkdir()
        (repo / "orchestrator.toml").write_text("config", encoding="utf-8")
        return repo


if __name__ == "__main__":
    unittest.main()
