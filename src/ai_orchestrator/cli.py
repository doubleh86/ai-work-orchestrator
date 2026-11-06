from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .codex_sdk import CodexSdkManager
from .config import ConfigError, create_default_config, load_config
from .models import ProviderStatus, RunLockStatus, RunState, WorkspaceStatus
from .pipeline import Pipeline, PipelineError
from .registry import ProjectRegistry, RegisteredProject, RegistryError

DEFAULT_CONFIG = "orchestrator.toml"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-orchestrator",
        description=(
            "Orchestrate sequential AI coding tasks in a shared run worktree through verification, branch push, main application, and deploy."
        ),
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="path to TOML config")
    parser.add_argument("--registry", default="", help="path to project registry JSON")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    mcp = sub.add_parser("mcp", help="serve orchestrator tools over MCP stdio")
    mcp.add_argument("--allow-write", action="store_true", help="enable document, planning, and recovery actions")
    mcp.add_argument("--projects-root", type=Path, help="existing host folder in which MCP can create new projects")

    start = sub.add_parser("start", help="receive, review, and plan a specification")
    start.add_argument("spec", help="planning document file or directory")

    clarify = sub.add_parser("clarify", help="answer planning questions and re-run planning")
    clarify.add_argument("run_id")
    clarify.add_argument("answers")

    execute = sub.add_parser("execute", help="prepare the run worktree and execute tasks in order")
    execute.add_argument("run_id")
    execute.add_argument("--manual", action="store_true", help="prepare handoff only")

    resume = sub.add_parser("resume", help="resume a supported interrupted run")
    resume.add_argument("run_id")
    resume.add_argument("--manual", action="store_true", help="prepare handoff only")

    retry = sub.add_parser("retry-task", help="retry one failed agent task")
    retry.add_argument("run_id")
    retry.add_argument("task_id")
    retry.add_argument("--manual", action="store_true", help="prepare handoff only")

    complete = sub.add_parser("complete-task", help="complete a manually handled task")
    complete.add_argument("run_id")
    complete.add_argument("task_id")

    for name, help_text in (
        ("merge", "apply verified work to main and push main"),
        ("push", "push the verified work branch"),
        ("deploy", "run the configured deployment command"),
    ):
        item = sub.add_parser(name, help=help_text)
        item.add_argument("run_id")
        item.add_argument("--approve", action="store_true", help="approve this side effect")

    verify = sub.add_parser("verify", help="run configured verification commands")
    verify.add_argument("run_id")

    status = sub.add_parser("status", help="show one run or list all runs")
    status.add_argument("run_id", nargs="?")

    lock = sub.add_parser("lock", help="inspect or clear a run lock")
    lock_sub = lock.add_subparsers(dest="lock_command", required=True)
    lock_status = lock_sub.add_parser("status", help="inspect a run lock")
    lock_status.add_argument("run_id")
    lock_clear = lock_sub.add_parser("clear", help="clear a confirmed stale run lock")
    lock_clear.add_argument("run_id")
    lock_clear.add_argument("--approve", action="store_true", help="approve stale lock removal")

    provider = sub.add_parser("provider", help="inspect configured AI providers")
    provider_sub = provider.add_subparsers(dest="provider_command", required=True)
    provider_sub.add_parser("list", help="list configured providers")
    doctor = provider_sub.add_parser("doctor", help="check provider executable availability")
    doctor.add_argument("provider_id", nargs="?")

    workspace = sub.add_parser("workspace", help="inspect or clear run and legacy task workspaces")
    workspace_sub = workspace.add_subparsers(dest="workspace_command", required=True)
    workspace_status = workspace_sub.add_parser("status", help="inspect work branch and worktree state")
    workspace_status.add_argument("run_id", nargs="?")
    workspace_clear = workspace_sub.add_parser("clear", help="remove a confirmed stale run or task workspace")
    workspace_clear.add_argument("run_id")
    workspace_clear.add_argument("task_id")
    workspace_clear.add_argument("--approve", action="store_true", help="approve worktree and branch removal")

    project = sub.add_parser("project", help="manage registered projects")
    project_sub = project.add_subparsers(dest="project_command", required=True)
    project_add = project_sub.add_parser("add", help="register a target project")
    project_add.add_argument("repo")
    project_add.add_argument("--name", default="")
    project_add.add_argument("--project-config", default="")
    project_add.add_argument("--planning-source", default="", help="planning document directory, relative to the project repository")
    project_sub.add_parser("list", help="list registered projects")
    project_remove = project_sub.add_parser("remove", help="remove a project registry entry")
    project_remove.add_argument("name")

    sub.add_parser("desktop", help="open the macOS/Windows desktop app")
    return parser


def _display(state: RunState, as_json: bool) -> None:
    if as_json:
        print(json.dumps(state.to_dict(), ensure_ascii=False, indent=2))
        return
    print(f"run: {state.id}")
    print(f"stage: {state.stage.value}")
    print(f"base commit: {state.base_commit or 'unknown'}")
    print(f"workspace mode: {state.workspace_mode.value}")
    if state.execution_branch:
        print(f"work branch: {state.execution_branch}")
    if state.execution_worktree:
        print(f"worktree: {state.execution_worktree}")
    if state.active_step:
        print(f"active step: {state.active_step.value}")
    if state.failed_step:
        print(f"failed step: {state.failed_step.value} ({state.failure_message})")
    print(f"server work: {'yes' if state.server_work else 'no'}")
    print(f"summary: {state.summary}")
    if state.planning_agent_id:
        print(
            "planning: "
            f"{state.planning_agent_id}/{state.planning_provider_id or 'custom'} "
            f"model={state.planning_model or 'provider-default'} "
            f"reasoning={state.planning_reasoning_effort or 'provider-default'} "
            f"({state.planning_attempts} attempts)"
        )
    if state.planning_questions:
        print("clarification questions:")
        for question in state.planning_questions:
            print(f"  - {question}")
    if state.tasks:
        print("tasks:")
        for task in state.tasks:
            executor = f"{task.agent_id}/{task.provider_id or 'custom'}" if task.agent_id else "unassigned"
            reasoning = f"; reasoning={task.reasoning_effort or 'provider-default'}" if task.agent_id else ""
            reviewer = ""
            if task.reviewer_agent_id:
                reviewer = f"; review -> {task.reviewer_agent_id}/{task.reviewer_provider_id} [{task.review_status.value}]"
            action = ""
            if task.active_action:
                action = f"; action={task.active_action.value}"
            elif task.failed_action:
                action = f"; failed-action={task.failed_action.value}"
            dependencies = ""
            if task.dependencies:
                dependencies = f"; depends-on={','.join(task.dependencies)}"
            if task.conflict_dependencies:
                dependencies += f"; conflict-after={','.join(task.conflict_dependencies)}"
            blocked = ""
            if task.blocked_by:
                blocked = f"; blocked-by={','.join(task.blocked_by)}"
            print(f"  - {task.id} [{task.status.value}] -> {executor}{reasoning}{reviewer}{action}{dependencies}{blocked}: {task.title}")
            expected = ",".join(task.expected_paths) or "unspecified"
            forbidden = ",".join(task.forbidden_paths) or "none"
            commands = " | ".join(" ".join(command) for command in task.verify_commands) or "unspecified"
            print(
                f"    readiness={task.readiness.value}; "
                f"risk={task.risk_level.value}; expected={expected}; "
                f"forbidden={forbidden}; verify={commands}"
            )
            if task.conflict_group:
                print(f"    potential-conflict-group={','.join(task.conflict_group)}")
            if task.is_prerequisite:
                print("    shared-contract-prerequisite=true")
            if task.action_results:
                latest = task.action_results[-1]
                print(
                    f"    result={latest.action}/{latest.status}; "
                    f"attempt-records={len(task.action_results)}; "
                    f"commit={latest.result_commit or 'unrecorded'}"
                )
    if state.verification_attempts:
        print("verification-attempts:")
        for index, attempt in enumerate(state.verification_attempts, start=1):
            print(
                f"  - {index} [{attempt.status}]; "
                f"commit={attempt.integration_head or 'unrecorded'}; "
                f"passed-commands={len(attempt.passed_commands)}; "
                f"failed-task={attempt.failed_task_id or 'undetermined'}"
            )
            if attempt.error:
                print(f"    error={attempt.error}")


def _display_providers(statuses: list[ProviderStatus], as_json: bool) -> None:
    if as_json:
        print(json.dumps([asdict(status) for status in statuses], ensure_ascii=False))
        return
    for status in statuses:
        availability = "available" if status.available else "unavailable"
        executable = status.executable or "not found"
        agents = ", ".join(status.agent_ids)
        print(f"{status.id}\t{availability}\t{executable}\t{agents}")


def _display_lock(status: RunLockStatus, as_json: bool) -> None:
    if as_json:
        print(json.dumps(asdict(status), ensure_ascii=False, indent=2))
        return
    print(f"run: {status.run_id}")
    print(f"lock: {status.state.value}")
    if status.operation:
        print(f"operation: {status.operation}")
    if status.pid is not None:
        print(f"owner: pid={status.pid} host={status.host}")
    if status.acquired_at:
        print(f"acquired at: {status.acquired_at}")
    print(f"reason: {status.reason}")


def _display_workspaces(statuses: list[WorkspaceStatus], as_json: bool) -> None:
    if as_json:
        print(json.dumps([asdict(status) for status in statuses], ensure_ascii=False, indent=2))
        return
    if not statuses:
        print("no task workspaces")
        return
    for status in statuses:
        cleanup = "yes" if status.cleanup_safe else "no"
        print(f"{status.run_id}\t{status.task_id}\t{status.state.value}\tcleanup={cleanup}\t{status.reason}")


def _display_projects(projects: list[RegisteredProject], as_json: bool) -> None:
    if as_json:
        print(json.dumps([project.to_dict() for project in projects], ensure_ascii=False, indent=2))
        return
    if not projects:
        print("no projects")
        return
    for project in projects:
        print(f"{project.name}\t{project.repo}\t{project.config_path}")


def _project_command(args: argparse.Namespace) -> int:
    registry = ProjectRegistry(args.registry or None)
    if args.project_command == "add":
        repo = Path(args.repo).expanduser().resolve()
        if not repo.is_dir():
            raise RegistryError(f"project repository not found: {repo}")
        if args.project_config:
            configured = Path(args.project_config).expanduser()
            config_path = configured.resolve() if configured.is_absolute() else (repo / configured).resolve()
        else:
            repository_config = repo / DEFAULT_CONFIG
            if repository_config.is_file():
                config_path = repository_config
            else:
                config_path = registry.managed_config_path(repo)
                if not config_path.is_file():
                    create_default_config(config_path, repo)
        config = load_config(config_path)
        if config.project.repo != repo:
            raise RegistryError(f"registered repository does not match project.repo in config: {repo} != {config.project.repo}")
        planning_source = None
        if args.planning_source:
            configured_source = Path(args.planning_source).expanduser()
            planning_source = configured_source.resolve() if configured_source.is_absolute() else (repo / configured_source).resolve()
        project = registry.add(args.name or repo.name, repo, config_path, planning_source)
        _display_projects([project], args.json)
    elif args.project_command == "list":
        _display_projects(registry.list(), args.json)
    else:
        project = registry.remove(args.name)
        _display_projects([project], args.json)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    codex_sdk: CodexSdkManager | None = None
    try:
        if args.command == "project":
            return _project_command(args)
        if args.command == "desktop":
            from .desktop_entry import run_desktop

            return run_desktop(args.registry or None)
        if args.command == "mcp":
            try:
                from .mcp_server import serve
            except ModuleNotFoundError as exc:
                if exc.name not in {"mcp", "anyio", "pydantic"}:
                    raise
                raise ConfigError("Install MCP support from the source checkout: python -m pip install -e '.[mcp]'") from exc
            serve(args.registry or None, allow_write=args.allow_write, projects_root=args.projects_root)
            return 0
        config = load_config(args.config)
        codex_sdk = CodexSdkManager()
        pipeline = Pipeline(config, codex_sdk=codex_sdk)
        if args.command == "start":
            state = pipeline.start(args.spec)
        elif args.command == "clarify":
            state = pipeline.clarify(args.run_id, args.answers)
        elif args.command == "execute":
            state = pipeline.execute(args.run_id, manual=args.manual)
        elif args.command == "resume":
            state = pipeline.resume(args.run_id, manual=args.manual)
        elif args.command == "retry-task":
            state = pipeline.retry_task(args.run_id, args.task_id, manual=args.manual)
        elif args.command == "complete-task":
            state = pipeline.complete_task(args.run_id, args.task_id)
        elif args.command == "merge":
            state = pipeline.merge(args.run_id, approved=args.approve)
        elif args.command == "verify":
            state = pipeline.verify(args.run_id)
        elif args.command == "push":
            state = pipeline.push(args.run_id, approved=args.approve)
        elif args.command == "deploy":
            state = pipeline.deploy(args.run_id, approved=args.approve)
        elif args.command == "status":
            if args.run_id:
                _display(pipeline.status(args.run_id), args.json)
            else:
                states = pipeline.list_statuses()
                if args.json:
                    print(json.dumps([state.to_dict() for state in states], ensure_ascii=False))
                elif not states:
                    print("no runs")
                else:
                    for item in states:
                        print(f"{item.id}\t{item.stage.value}\t{item.summary}")
            return 0
        elif args.command == "lock":
            if args.lock_command == "status":
                lock_status = pipeline.run_lock_status(args.run_id)
            else:
                lock_status = pipeline.clear_run_lock(args.run_id, approved=args.approve)
            _display_lock(lock_status, args.json)
            return 0
        elif args.command == "provider":
            provider_id = getattr(args, "provider_id", None) or ""
            statuses = pipeline.provider_statuses(provider_id)
            _display_providers(statuses, args.json)
            if args.provider_command == "doctor" and any(not status.available for status in statuses):
                raise PipelineError("one or more providers are unavailable")
            return 0
        elif args.command == "workspace":
            if args.workspace_command == "status":
                statuses = pipeline.workspace_statuses(args.run_id or "")
            else:
                statuses = [
                    pipeline.cleanup_workspace(args.run_id, args.task_id, approved=args.approve)
                ]
            _display_workspaces(statuses, args.json)
            return 0
        else:  # pragma: no cover - argparse guarantees a command
            raise AssertionError(args.command)
        _display(state, args.json)
        return 0
    except (ConfigError, PipelineError, RegistryError, RuntimeError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        if codex_sdk is not None:
            codex_sdk.close()


if __name__ == "__main__":
    raise SystemExit(main())
