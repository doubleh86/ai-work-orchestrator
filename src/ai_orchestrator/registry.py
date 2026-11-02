from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from .app_paths import application_config_root
from .code_style import CodeStyleError, ProjectCodeStylePreference, normalize_custom_instruction_paths

REGISTRY_SCHEMA_VERSION = 3
SUPPORTED_REGISTRY_SCHEMA_VERSIONS = {1, 2, REGISTRY_SCHEMA_VERSION}


class RegistryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RegisteredProject:
    name: str
    repo: Path
    config_path: Path
    created_at: str
    planning_source_dir: Path | None = None
    dotnet_executable: str = ""
    code_style_preference: ProjectCodeStylePreference = field(default_factory=ProjectCodeStylePreference)
    code_style_preference_revision: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "repo": str(self.repo),
            "config_path": str(self.config_path),
            "created_at": self.created_at,
            "dotnet_executable": self.dotnet_executable,
            "planning_source_dir": (str(self.planning_source_dir) if self.planning_source_dir is not None else None),
            "code_style_preference": self.code_style_preference.to_dict(),
            "code_style_preference_revision": self.code_style_preference_revision,
        }

    @classmethod
    def from_dict(cls, raw: object) -> "RegisteredProject":
        if not isinstance(raw, dict):
            raise RegistryError("registry project entry must be an object")
        values: dict[str, str] = {}
        for field_name in ("name", "repo", "config_path", "created_at"):
            value = raw.get(field_name)
            if not isinstance(value, str) or not value.strip():
                raise RegistryError(f"registry project {field_name} must be a non-empty string")
            values[field_name] = value.strip()
        planning_source_raw = raw.get("planning_source_dir")
        if planning_source_raw is None:
            planning_source_dir = None
        elif not isinstance(planning_source_raw, str) or not planning_source_raw.strip():
            raise RegistryError("registry project planning_source_dir must be a non-empty string or null")
        else:
            planning_source_dir = Path(planning_source_raw).expanduser().resolve()
        dotnet_executable = raw.get("dotnet_executable", "")
        if not isinstance(dotnet_executable, str):
            raise RegistryError("registry project dotnet_executable must be a string")
        try:
            code_style_preference = ProjectCodeStylePreference.from_dict(raw.get("code_style_preference"))
        except CodeStyleError as exc:
            raise RegistryError(str(exc)) from exc
        try:
            code_style_preference_revision = int(raw.get("code_style_preference_revision", 0))
        except (TypeError, ValueError) as exc:
            raise RegistryError("registry project code_style_preference_revision must be a non-negative integer") from exc
        if code_style_preference_revision < 0:
            raise RegistryError("registry project code_style_preference_revision must be a non-negative integer")
        return cls(
            name=values["name"],
            repo=Path(values["repo"]).expanduser().resolve(),
            config_path=Path(values["config_path"]).expanduser().resolve(),
            created_at=values["created_at"],
            planning_source_dir=planning_source_dir,
            dotnet_executable=dotnet_executable,
            code_style_preference=code_style_preference,
            code_style_preference_revision=code_style_preference_revision,
        )


def default_registry_path(*, platform: str | None = None, environment: Mapping[str, str] | None = None, home: Path | None = None) -> Path:
    return (application_config_root(platform=platform, environment=environment, home=home) / "projects.json").resolve()


class ProjectRegistry:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path).expanduser().resolve() if path is not None else default_registry_path()

    def list(self) -> list[RegisteredProject]:
        projects = self._load()
        return sorted(projects, key=lambda item: item.name.casefold())

    def get(self, name: str) -> RegisteredProject:
        normalized = self._normalize_name(name)
        for project in self._load():
            if project.name.casefold() == normalized:
                return project
        raise RegistryError(f"unknown project: {name}")

    def add(
        self, name: str, repo: str | Path, config_path: str | Path | None = None, planning_source_dir: str | Path | None = None
    ) -> RegisteredProject:
        normalized = self._normalize_name(name)
        repo_path = Path(repo).expanduser().resolve()
        if not repo_path.is_dir():
            raise RegistryError(f"project repository not found: {repo_path}")
        selected_config = Path(config_path).expanduser().resolve() if config_path is not None else (repo_path / "orchestrator.toml").resolve()
        if not selected_config.is_file():
            raise RegistryError(f"project config not found: {selected_config}")
        selected_planning_source = self._planning_source_path(planning_source_dir)

        projects = self._load()
        if any(project.name.casefold() == normalized for project in projects):
            raise RegistryError(f"project name already registered: {name.strip()}")
        if any(project.repo == repo_path for project in projects):
            raise RegistryError(f"project repository already registered: {repo_path}")
        project = RegisteredProject(
            name=name.strip(),
            repo=repo_path,
            config_path=selected_config,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            planning_source_dir=selected_planning_source,
        )
        projects.append(project)
        self._save(projects)
        return project

    def managed_config_path(self, repo: str | Path) -> Path:
        repo_path = Path(repo).expanduser().resolve()
        identity = os.path.normcase(str(repo_path))
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        return (self.path.parent / "project-configs" / digest / "orchestrator.toml").resolve()

    def update_planning_source(self, name: str, planning_source_dir: str | Path | None) -> RegisteredProject:
        normalized = self._normalize_name(name)
        selected_source = self._planning_source_path(planning_source_dir)
        projects = self._load()
        for index, project in enumerate(projects):
            if project.name.casefold() == normalized:
                updated = replace(project, planning_source_dir=selected_source)
                projects[index] = updated
                self._save(projects)
                return updated
        raise RegistryError(f"unknown project: {name}")

    def update_dotnet(self, name: str, executable: str) -> RegisteredProject:
        selected = executable.strip()
        if selected:
            path = Path(selected).expanduser()
            if not path.is_absolute() or path.name.casefold() not in {"dotnet", "dotnet.exe"}:
                raise RegistryError("dotnet 실행 파일의 절대 경로를 입력하세요.")
            if not path.is_file():
                raise RegistryError(f"dotnet 실행 파일을 찾지 못했습니다: {path}")
            selected = str(path.resolve())
        normalized = self._normalize_name(name)
        projects = self._load()
        for index, project in enumerate(projects):
            if project.name.casefold() == normalized:
                updated = replace(project, dotnet_executable=selected)
                projects[index] = updated
                self._save(projects)
                return updated
        raise RegistryError(f"unknown project: {name}")

    def update_code_style_preference(
        self,
        name: str,
        preference: ProjectCodeStylePreference,
        *,
        expected_revision: int,
    ) -> RegisteredProject:
        normalized = self._normalize_name(name)
        projects = self._load()
        for index, project in enumerate(projects):
            if project.name.casefold() != normalized:
                continue
            if project.code_style_preference_revision != expected_revision:
                raise RegistryError(
                    "코드 스타일 설정이 다른 창에서 변경되었습니다. 최신 설정을 다시 불러온 뒤 저장하세요."
                )
            try:
                custom_paths = normalize_custom_instruction_paths(project.repo, preference.custom_instruction_paths)
            except CodeStyleError as exc:
                raise RegistryError(str(exc)) from exc
            normalized_preference = replace(preference, custom_instruction_paths=custom_paths)
            updated = replace(
                project,
                code_style_preference=normalized_preference,
                code_style_preference_revision=expected_revision + 1,
            )
            projects[index] = updated
            self._save(projects)
            return updated
        raise RegistryError(f"unknown project: {name}")

    def remove(self, name: str) -> RegisteredProject:
        normalized = self._normalize_name(name)
        projects = self._load()
        for index, project in enumerate(projects):
            if project.name.casefold() == normalized:
                removed = projects.pop(index)
                self._save(projects)
                return removed
        raise RegistryError(f"unknown project: {name}")

    def _load(self) -> list[RegisteredProject]:
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RegistryError(f"invalid project registry: {self.path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise RegistryError("project registry must be a JSON object")
        version = raw.get("schema_version")
        if version not in SUPPORTED_REGISTRY_SCHEMA_VERSIONS:
            raise RegistryError(f"unsupported project registry schema: {version}")
        entries = raw.get("projects")
        if not isinstance(entries, list):
            raise RegistryError("project registry projects must be an array")
        projects = [RegisteredProject.from_dict(item) for item in entries]
        names = [project.name.casefold() for project in projects]
        if len(names) != len(set(names)):
            raise RegistryError("project registry contains duplicate names")
        repos = [project.repo for project in projects]
        if len(repos) != len(set(repos)):
            raise RegistryError("project registry contains duplicate repositories")
        return projects

    def _save(self, projects: list[RegisteredProject]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"schema_version": REGISTRY_SCHEMA_VERSION, "projects": [project.to_dict() for project in projects]}, ensure_ascii=False, indent=2
            )
            + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)

    @staticmethod
    def _planning_source_path(planning_source_dir: str | Path | None) -> Path | None:
        if planning_source_dir is None or not str(planning_source_dir).strip():
            return None
        selected = Path(planning_source_dir).expanduser().resolve()
        if not selected.is_dir():
            raise RegistryError(f"planning source directory not found: {selected}")
        return selected

    @staticmethod
    def _normalize_name(name: str) -> str:
        if not isinstance(name, str) or not name.strip():
            raise RegistryError("project name must be a non-empty string")
        if any(character in name for character in "\r\n\t"):
            raise RegistryError("project name cannot contain control characters")
        return name.strip().casefold()
