from __future__ import annotations

import json
import shlex
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import WorkspaceLocation, WorkspaceLocationSource
from .worker_mcp import WorkerMcpError, WorkerMcpServer, parse_mcp_servers


DEFAULT_WORKTREE_DIR = ".ai_auto_work/worktree"
LEGACY_DEFAULT_WORKTREE_DIR = ".ai-worktrees"
DEFAULT_TASK_VERIFY_COMMAND_TIMEOUT_SECONDS = 900
DEFAULT_TASK_VERIFY_TOTAL_TIMEOUT_SECONDS = 1800


@dataclass(frozen=True, slots=True)
class AgentConfig:
    id: str
    capabilities: tuple[str, ...]
    command: tuple[str, ...]
    max_tasks: int = 1
    provider_id: str = "custom"
    model: str = ""
    review_command: tuple[str, ...] = field(default_factory=tuple)
    sandbox_mode: str = "workspace-write"
    approval_mode: str = "auto-review"
    review_sandbox_mode: str = "read-only"
    review_approval_mode: str = "deny-all"
    manual_only: bool = False


@dataclass(frozen=True, slots=True)
class RoutingRule:
    capabilities: tuple[str, ...]
    provider_id: str


@dataclass(frozen=True, slots=True)
class RoutingConfig:
    default_provider: str = ""
    review_required: bool = False
    max_review_cycles: int = 2
    rules: tuple[RoutingRule, ...] = field(default_factory=tuple)
    balance_providers: bool = True


@dataclass(frozen=True, slots=True)
class PlanningConfig:
    agent_id: str = ""
    max_attempts: int = 2
    reuse_results: bool = True
    timeout_seconds: int = 600


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    repo: Path
    main_branch: str = "main"
    remote: str = "origin"
    state_dir: str = ".ai-orchestrator"
    worktree_dir: str = DEFAULT_WORKTREE_DIR


@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    max_parallel: int = 3
    auto_commit: bool = True
    verify_commands: tuple[tuple[str, ...], ...] = field(default_factory=tuple)
    deploy_command: tuple[str, ...] = field(default_factory=tuple)
    agent_timeout_seconds: int = 1800
    task_verify_command_timeout_seconds: int = DEFAULT_TASK_VERIFY_COMMAND_TIMEOUT_SECONDS
    task_verify_total_timeout_seconds: int = DEFAULT_TASK_VERIFY_TOTAL_TIMEOUT_SECONDS
    integration_verify_command_timeout_seconds: int = 600
    integration_verify_total_timeout_seconds: int = 1800
    verification_repair_limit: int = 2


@dataclass(frozen=True, slots=True)
class Config:
    path: Path
    project: ProjectConfig
    execution: ExecutionConfig
    agents: tuple[AgentConfig, ...]
    routing: RoutingConfig = field(default_factory=RoutingConfig)
    planning: PlanningConfig = field(default_factory=PlanningConfig)
    worker_mcp_servers: tuple[WorkerMcpServer, ...] = ()


class ConfigError(ValueError):
    pass


def resolve_workspace_location(project: ProjectConfig) -> WorkspaceLocation:
    configured = str(project.worktree_dir).strip()
    if not configured:
        raise ConfigError("project.worktree_dir must not be empty")
    normalized = Path(configured).as_posix().rstrip("/")
    if normalized in {DEFAULT_WORKTREE_DIR, LEGACY_DEFAULT_WORKTREE_DIR}:
        return WorkspaceLocation(
            root=str((project.repo / DEFAULT_WORKTREE_DIR).resolve()),
            source=WorkspaceLocationSource.PROJECT_DEFAULT,
            notice_code=("legacy_default_alias" if normalized == LEGACY_DEFAULT_WORKTREE_DIR else ""),
        )
    configured_path = Path(configured).expanduser()
    root = configured_path.resolve() if configured_path.is_absolute() else (project.repo.parent / configured_path).resolve()
    return WorkspaceLocation(root=str(root), source=WorkspaceLocationSource.CUSTOM_LEGACY)


CODEX_REASONING_EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")
CLAUDE_REASONING_EFFORTS = ("low", "medium", "high", "xhigh", "max")
CODEX_MODEL_PRESETS = ("gpt-6.1-sol", "gpt-6.1-terra", "gpt-6-luna")
CLAUDE_MODEL_PRESETS = ("fable", "opus", "sonnet", "claude-opus-5-5", "claude-fable-5", "claude-opus-5", "claude-sonnet-5")
NVIDIA_MODEL_PRESETS = ("nvidia/nemotron-3-super-120b-a12b",)
CODEX_SANDBOX_MODES = ("read-only", "workspace-write", "danger-full-access")
CODEX_APPROVAL_MODES = ("deny-all", "auto-review")


def create_default_config(path: str | Path, repo: str | Path, *, main_branch: str = "main") -> Path:
    config_path = Path(path).expanduser().resolve()
    repo_path = Path(repo).expanduser().resolve()
    if config_path.exists():
        raise ConfigError(f"config already exists: {config_path}")
    if not repo_path.is_dir():
        raise ConfigError(f"project repository not found: {repo_path}")

    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = config_path.with_name(f"{config_path.name}.tmp")
    temporary.write_text(_default_config_text(repo_path, main_branch=main_branch), encoding="utf-8")
    if config_path.exists():
        temporary.unlink(missing_ok=True)
        raise ConfigError(f"config already exists: {config_path}")
    temporary.replace(config_path)
    return config_path


def _default_config_text(repo: Path, *, main_branch: str = "main") -> str:
    repo_value = json.dumps(str(repo), ensure_ascii=False)
    branch_value = json.dumps(main_branch.strip() or "main", ensure_ascii=False)
    return f"""[project]
repo = {repo_value}
main_branch = {branch_value}
remote = "origin"
state_dir = ".ai-orchestrator"
worktree_dir = ".ai_auto_work/worktree"

[execution]
max_parallel = 3
auto_commit = true
agent_timeout_seconds = 1800
task_verify_command_timeout_seconds = {DEFAULT_TASK_VERIFY_COMMAND_TIMEOUT_SECONDS}
task_verify_total_timeout_seconds = {DEFAULT_TASK_VERIFY_TOTAL_TIMEOUT_SECONDS}
integration_verify_command_timeout_seconds = 600
integration_verify_total_timeout_seconds = 1800
verification_repair_limit = 2
verify_commands = []
deploy_command = []

[planning]
agent = "codex-general"
max_attempts = 2
reuse_results = true
timeout_seconds = 600

[routing]
default_provider = "codex"
balance_providers = true
review_required = false
max_review_cycles = 2

[[agents]]
id = "codex-general"
provider = "codex"
model = "gpt-6.1-sol"
capabilities = [
  "general", "planning", "architecture", "backend", "api", "database",
  "frontend", "mobile", "infra", "security", "qa", "docs", "review",
]
max_tasks = 4
sandbox_mode = "workspace-write"
approval_mode = "auto-review"
review_sandbox_mode = "read-only"
review_approval_mode = "deny-all"

[[agents]]
id = "claude-general"
provider = "claude"
model = "sonnet"
capabilities = [
  "general", "planning", "architecture", "backend", "api", "database",
  "frontend", "mobile", "infra", "security", "qa", "docs", "review",
]
max_tasks = 12
command = [
  "claude", "-p", "Follow the task instructions provided through standard input.",
  "--model", "sonnet", "--output-format", "text", "--max-turns", "30",
  "--allowedTools", "Read,Write,Edit,Glob,Grep,Bash",
  "--disallowedTools", "Bash(git commit:*),Bash(git merge:*),Bash(git push:*)",
]
review_command = [
  "claude", "-p", "Follow the review instructions provided through standard input.",
  "--model", "sonnet", "--output-format", "text", "--max-turns", "15",
  "--allowedTools", "Read,Glob,Grep,Bash(git diff:*),Bash(git log:*),Bash(git status:*)",
]
"""


def supported_models(provider_id: str, configured_models: tuple[str, ...] = ()) -> tuple[str, ...]:
    configured = tuple(model.strip() for model in configured_models if model.strip())
    provider = provider_id.strip().casefold()
    presets: tuple[str, ...] = ()
    if provider == "codex":
        presets = CODEX_MODEL_PRESETS
    elif provider == "claude":
        presets = CLAUDE_MODEL_PRESETS
    elif provider == "nvidia":
        presets = NVIDIA_MODEL_PRESETS
    return tuple(dict.fromkeys((*configured, *presets)))


def supported_reasoning_efforts(provider_id: str, model: str = "") -> tuple[str, ...]:
    provider = provider_id.strip().casefold()
    selected_model = model.strip().casefold()
    if provider == "codex":
        if selected_model in {"gpt-5.6-luna", "gpt-6-astra", "gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna"}:
            return CODEX_REASONING_EFFORTS[:-1]
        return CODEX_REASONING_EFFORTS
    if provider == "claude":
        return CLAUDE_REASONING_EFFORTS
    return ()


def _command(value: Any, field_name: str) -> tuple[str, ...]:
    if value in (None, "", []):
        return ()
    if isinstance(value, str):
        return tuple(shlex.split(value))
    if isinstance(value, list) and all(isinstance(part, str) for part in value):
        return tuple(value)
    raise ConfigError(f"{field_name} must be a string or an array of strings")


def _provider_id(agent_id: str, command: tuple[str, ...], configured: Any) -> str:
    explicit = str(configured or "").strip().casefold()
    if explicit:
        return explicit
    executable = Path(command[0]).stem.casefold() if command else ""
    for known in ("codex", "claude"):
        if known in executable or known in agent_id.casefold():
            return known
    return "custom"


def _positive_int(value: Any, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{field_name} must be a positive integer") from exc
    if parsed < 1:
        raise ConfigError(f"{field_name} must be a positive integer")
    return parsed


def load_config(path: str | Path) -> Config:
    config_path = Path(path).expanduser().resolve()
    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"config not found: {config_path}") from exc

    project_raw = raw.get("project", {})
    repo_value = project_raw.get("repo", ".")
    repo = (config_path.parent / repo_value).resolve()
    project = ProjectConfig(
        repo=repo,
        main_branch=project_raw.get("main_branch", "main"),
        remote=project_raw.get("remote", "origin"),
        state_dir=project_raw.get("state_dir", ".ai-orchestrator"),
        worktree_dir=project_raw.get("worktree_dir", DEFAULT_WORKTREE_DIR),
    )

    execution_raw = raw.get("execution", {})
    verify_raw = execution_raw.get("verify_commands", [])
    if not isinstance(verify_raw, list):
        raise ConfigError("execution.verify_commands must be an array")
    execution = ExecutionConfig(
        max_parallel=max(1, int(execution_raw.get("max_parallel", 3))),
        auto_commit=bool(execution_raw.get("auto_commit", True)),
        agent_timeout_seconds=_positive_int(execution_raw.get("agent_timeout_seconds", 1800), "execution.agent_timeout_seconds"),
        task_verify_command_timeout_seconds=_positive_int(
            execution_raw.get("task_verify_command_timeout_seconds", DEFAULT_TASK_VERIFY_COMMAND_TIMEOUT_SECONDS),
            "execution.task_verify_command_timeout_seconds",
        ),
        task_verify_total_timeout_seconds=_positive_int(
            execution_raw.get("task_verify_total_timeout_seconds", DEFAULT_TASK_VERIFY_TOTAL_TIMEOUT_SECONDS),
            "execution.task_verify_total_timeout_seconds",
        ),
        integration_verify_command_timeout_seconds=_positive_int(
            execution_raw.get("integration_verify_command_timeout_seconds", 600), "execution.integration_verify_command_timeout_seconds"
        ),
        integration_verify_total_timeout_seconds=_positive_int(
            execution_raw.get("integration_verify_total_timeout_seconds", 1800), "execution.integration_verify_total_timeout_seconds"
        ),
        verification_repair_limit=_positive_int(execution_raw.get("verification_repair_limit", 2), "execution.verification_repair_limit"),
        verify_commands=tuple(_command(value, "execution.verify_commands") for value in verify_raw),
        deploy_command=_command(execution_raw.get("deploy_command", []), "execution.deploy_command"),
    )

    agents: list[AgentConfig] = []
    agent_ids: set[str] = set()
    for item in raw.get("agents", []):
        agent_id = str(item.get("id", "")).strip()
        if not agent_id:
            raise ConfigError("every agent requires an id")
        if agent_id in agent_ids:
            raise ConfigError(f"duplicate agent id: {agent_id}")
        agent_ids.add(agent_id)
        command = _command(item.get("command", []), f"agents.{agent_id}.command")
        review_command = _command(item.get("review_command", []), f"agents.{agent_id}.review_command")
        provider_id = _provider_id(agent_id, command, item.get("provider"))
        sandbox_mode = str(item.get("sandbox_mode", "workspace-write")).strip().casefold()
        approval_mode = str(item.get("approval_mode", "auto-review")).strip().casefold()
        review_sandbox_mode = str(item.get("review_sandbox_mode", "read-only")).strip().casefold()
        review_approval_mode = str(item.get("review_approval_mode", "deny-all")).strip().casefold()
        if provider_id == "codex":
            for field_name, value, supported in (
                ("sandbox_mode", sandbox_mode, CODEX_SANDBOX_MODES),
                ("approval_mode", approval_mode, CODEX_APPROVAL_MODES),
                ("review_sandbox_mode", review_sandbox_mode, CODEX_SANDBOX_MODES),
                ("review_approval_mode", review_approval_mode, CODEX_APPROVAL_MODES),
            ):
                if value not in supported:
                    available = ", ".join(supported)
                    raise ConfigError(f"agents.{agent_id}.{field_name} must be one of: {available}")
            command = ()
            review_command = ()
        agents.append(
            AgentConfig(
                id=agent_id,
                capabilities=tuple(str(value).lower() for value in item.get("capabilities", [])),
                command=command,
                max_tasks=max(1, int(item.get("max_tasks", 1))),
                provider_id=provider_id,
                model=str(item.get("model", "")).strip(),
                review_command=review_command,
                sandbox_mode=sandbox_mode,
                approval_mode=approval_mode,
                review_sandbox_mode=review_sandbox_mode,
                review_approval_mode=review_approval_mode,
            )
        )
    if not agents:
        raise ConfigError("at least one [[agents]] entry is required")

    planning_raw = raw.get("planning", {})
    if not isinstance(planning_raw, dict):
        raise ConfigError("planning must be a table")
    planning = PlanningConfig(
        agent_id=str(planning_raw.get("agent", "")).strip(),
        max_attempts=_positive_int(planning_raw.get("max_attempts", 2), "planning.max_attempts"),
        reuse_results=bool(planning_raw.get("reuse_results", True)),
        timeout_seconds=_positive_int(planning_raw.get("timeout_seconds", 600), "planning.timeout_seconds"),
    )
    if planning.agent_id and planning.agent_id not in agent_ids:
        raise ConfigError(f"planning agent not found: {planning.agent_id}")
    if planning.agent_id:
        planning_agent = next(agent for agent in agents if agent.id == planning.agent_id)
        if planning_agent.provider_id != "codex" and not (
            planning_agent.review_command or planning_agent.command
        ):
            raise ConfigError(f"planning agent requires a command: {planning.agent_id}")

    routing_raw = raw.get("routing", {})
    rules: list[RoutingRule] = []
    for index, item in enumerate(routing_raw.get("rules", []), start=1):
        capabilities = tuple(str(value).strip().casefold() for value in item.get("capabilities", []) if str(value).strip())
        provider_id = str(item.get("provider", "")).strip().casefold()
        if not capabilities or not provider_id:
            raise ConfigError(f"routing rule {index} requires capabilities and provider")
        rules.append(RoutingRule(capabilities, provider_id))
    balance_providers = routing_raw.get("balance_providers", True)
    if not isinstance(balance_providers, bool):
        raise ConfigError("routing.balance_providers must be a boolean")
    routing = RoutingConfig(
        default_provider=str(routing_raw.get("default_provider", "")).strip().casefold(),
        review_required=bool(routing_raw.get("review_required", False)),
        max_review_cycles=max(1, int(routing_raw.get("max_review_cycles", 2))),
        rules=tuple(rules),
        balance_providers=balance_providers,
    )
    provider_ids = {agent.provider_id for agent in agents}
    referenced = {rule.provider_id for rule in routing.rules}
    if routing.default_provider:
        referenced.add(routing.default_provider)
    missing_providers = referenced - provider_ids
    if missing_providers:
        missing = ", ".join(sorted(missing_providers))
        raise ConfigError(f"routing references providers without agents: {missing}")
    if routing.review_required and len(provider_ids) < 2:
        raise ConfigError("routing.review_required needs at least two providers")
    try:
        worker_mcp_servers = parse_mcp_servers(raw.get("mcp_servers", {}))
    except WorkerMcpError as exc:
        raise ConfigError(str(exc)) from exc
    return Config(path=config_path, project=project, execution=execution, agents=tuple(agents), routing=routing, planning=planning,
                  worker_mcp_servers=worker_mcp_servers)
