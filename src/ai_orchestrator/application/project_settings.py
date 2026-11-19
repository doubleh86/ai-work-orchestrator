"""Project settings operations through explicit registry-owned updates."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Protocol

from ..code_style import ProjectCodeStylePreference, inspect_project_code_style
from ..config import Config, load_config, resolve_workspace_location
from ..git import inspect_git_readiness
from ..registry import ProjectRegistry, RegisteredProject, RegistryError
from ..repository_maturity import inspect_repository_maturity
from ..worker_mcp import WorkerMcpError, WorkerMcpServer, check_mcp_connection, parse_mcp_servers, worker_mcp_lease
from .errors import ApplicationError


def registered_project_config(project: RegisteredProject, registry: ProjectRegistry) -> Config:
    if registry.path.is_relative_to(project.repo):
        raise RegistryError("앱 등록 파일을 프로젝트 저장소 밖에 두어야 합니다.")
    selected = project.config_path.resolve()
    if project.config_path.is_relative_to(project.repo) or selected.is_relative_to(project.repo):
        readiness = inspect_git_readiness(project.repo)
        selected = registry.select_config_path(project.repo, main_branch=readiness.main_branch or "main")
    config = load_config(selected)
    if config.project.repo != project.repo:
        raise RegistryError(f"registered project config changed repository: {project.name}")
    return config


class WorkerMcpSettingsUpdate(Protocol):
    def __call__(self, name: str, servers: tuple[WorkerMcpServer, ...], *, expected_revision: int) -> RegisteredProject: ...


class CodeStyleSettingsUpdate(Protocol):
    def __call__(self, name: str, preference: ProjectCodeStylePreference, *, expected_revision: int) -> RegisteredProject: ...


@dataclass(frozen=True, slots=True)
class ProjectSettingsService:
    read_project: Callable[[str], RegisteredProject]
    read_config: Callable[[RegisteredProject], Config]
    read_servers: Callable[[str, RegisteredProject], tuple[WorkerMcpServer, ...]]
    update_servers: WorkerMcpSettingsUpdate
    update_style: CodeStyleSettingsUpdate

    def worker_mcp_connections(self, project_name: str) -> dict[str, object]:
        project = self.read_project(project_name)
        servers = self.read_servers(project_name, project)
        return {"revision": project.worker_mcp_revision, "servers": [server.to_dict() for server in servers]}

    def update_worker_mcp_connections(
        self, project_name: str, configuration: object, *, expected_revision: int, approved: bool, append: bool = False,
    ) -> dict[str, object]:
        if not approved:
            raise ApplicationError("approval_required", "도구 연결 권한 변경을 확인해 주세요.")
        try:
            servers = parse_mcp_servers(configuration)
        except WorkerMcpError as exc:
            raise ApplicationError("invalid_params", str(exc)) from exc
        if type(append) is not bool:
            raise ApplicationError("invalid_params", "append must be a boolean")
        if append:
            project = self.read_project(project_name)
            previous = self.read_servers(project_name, project)
            merged = {server.id.casefold(): server for server in previous}
            merged.update((server.id.casefold(), server) for server in servers)
            servers = tuple(merged.values())
        project = self.update_servers(project_name, servers, expected_revision=expected_revision)
        return {"revision": project.worker_mcp_revision, "servers": [server.to_dict() for server in servers]}

    def check_worker_mcp_connection(self, project_name: str, server_id: str, *, expected_revision: int) -> dict[str, object]:
        project = self.read_project(project_name)
        if project.worker_mcp_revision != expected_revision:
            raise ApplicationError("invalid_params", "도구 연결 설정이 변경됐습니다. 새로 확인해 주세요.")
        servers = self.read_servers(project_name, project)
        selected = next((server for server in servers if server.id == server_id), None)
        if selected is None:
            raise ApplicationError("invalid_params", "확인할 도구 연결을 찾지 못했습니다.")
        try:
            with worker_mcp_lease((selected,), timeout_seconds=0):
                result = check_mcp_connection(selected, project.repo, project.repo)
        except WorkerMcpError as exc:
            result = {"id": server_id, "status": "error", "message": str(exc)}
        if self.read_project(project_name).worker_mcp_revision != expected_revision:
            raise ApplicationError("invalid_params", "도구 연결 설정이 변경됐습니다. 새로 확인해 주세요.")
        return result

    def workspace_location(self, project_name: str) -> object:
        project = self.read_project(project_name)
        config = self.read_config(project)
        location = resolve_workspace_location(config.project)
        return {
            "repo": str(config.project.repo),
            "root": location.root,
            "source": location.source,
            "layout_version": location.layout_version,
            "created": Path(location.root).is_dir(),
            "notice_code": location.notice_code,
        }

    def project_capabilities(self, project_name: str) -> object:
        project = self.read_project(project_name)
        config = self.read_config(project)
        return {
            "deployment_configured": bool(config.execution.deploy_command),
            "repository_maturity": asdict(inspect_repository_maturity(project.repo)),
        }

    def code_style_profile(self, project_name: str) -> object:
        project = self.read_project(project_name)
        return inspect_project_code_style(
            project.repo,
            project.code_style_preference,
            preference_revision=project.code_style_preference_revision,
        ).to_dict()

    def preview_code_style_preference(self, project_name: str, preference: ProjectCodeStylePreference) -> object:
        project = self.read_project(project_name)
        return inspect_project_code_style(
            project.repo,
            preference,
            preference_revision=project.code_style_preference_revision,
        ).to_dict()

    def update_code_style_preference(
        self,
        project_name: str,
        preference: ProjectCodeStylePreference,
        expected_revision: int,
        *,
        approved: bool,
    ) -> object:
        if not approved:
            raise ApplicationError("approval_required", "code style preference update requires explicit approval")
        project = self.update_style(
            project_name,
            preference,
            expected_revision=expected_revision,
        )
        return inspect_project_code_style(
            project.repo,
            project.code_style_preference,
            preference_revision=project.code_style_preference_revision,
        ).to_dict()

    def inspect_repository_maturity(self, project_name: str) -> object:
        project = self.read_project(project_name)
        return asdict(inspect_repository_maturity(project.repo))
