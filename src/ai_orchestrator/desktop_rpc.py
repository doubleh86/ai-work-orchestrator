from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, TextIO

from .account_usage import AccountUsage, read_claude_quota
from .codex_sdk import CodexSdkManager, read_codex_quota
from .code_style import ProjectCodeStylePreference, inspect_project_code_style
from .config import create_default_config, load_config, resolve_workspace_location, supported_models, supported_reasoning_efforts
from .document_index import PlanningSourceIndex
from .git import (
    create_initial_commit,
    initialize_git_repository,
    inspect_git_readiness,
    preview_git_initialization,
    preview_initial_commit,
)
from .models import RunState, Stage, UserCheck, utc_now
from .pipeline import Pipeline, PipelineError
from .nvidia_agent import current_nvidia_model_keys, nvidia_credential_scope, redact_nvidia_output
from .repository_maturity import inspect_repository_maturity
from .registry import ProjectRegistry, RegisteredProject, RegistryError

RPC_VERSION = 1

_LONG_RUNNING_RPC_METHODS = frozenset(
    {
        "runs.decideProjectChat", "runs.performProjectChat",
        "runs.recoveryPlan",
        "runs.applyRecovery",
        "runs.prepareConflictResolution",
        "runs.applyConflictResolution",
        "projects.updateMain",
        "projects.initializeGit",
        "projects.createInitialCommit",
        "projects.mainChanges",
        "projects.mainChangeDiff",
        "projects.refreshMainRemote",
        "projects.commitMainChanges",
        "projects.commitAndPushMainChanges",
        "projects.pushMainCommits",
        "projects.checkDotnet",
        "planning.refreshIndex",
        "runs.preparePlanning",
        "runs.proposeResultRevision",
        "runs.createResultRevision",
        "runs.runPlanning",
        "runs.start",
        "runs.sendPlanningMessage",
        "runs.previewPlanningApply",
        "runs.applyPlanningPreview",
        "runs.applyEffortModeToPlan",
        "runs.applyPlanningConversation",
        "planning.generateFeaturePlan",
        "runs.execute",
        "runs.resume",
        "tasks.execute",
        "tasks.retry",
        "tasks.repairFromChat",
        "tasks.complete",
        "tasks.completeManualVerification",
        "runs.recordUserCheck",
        "connections.registerExternal",
        "runs.launchResult",
        "runs.registerResult",
        "tasks.handoffToAi",
        "tasks.deferManual",
        "tasks.resumeManual",
        "runs.verify",
        "runs.verifyAndRepair",
        "runs.updatePlan",
        "runs.confirmPlan",
        "runs.merge",
        "runs.push",
        "runs.retryMainPush",
        "runs.recoverMainApply",
        "runs.deploy",
        "runs.archive",
        "runs.retryArchiveCleanup",
        "runs.delete",
        "workspaces.cleanup",
    }
)
_STATUS_RPC_METHODS = frozenset(
    {
        "system.hello",
        "connections.externalGuide",
        "runs.resultArtifact",
        "auth.codex.status",
        "auth.claude.status",
        "providers.accountUsage",
        "auth.codex.get",
        "projects.list",
        "runs.activeGroups",
        "runs.attentionItems",
        "projects.capabilities",
        "projects.codeStyleProfile",
        "projects.inspectGitReadiness",
        "projects.previewGitInitialization",
        "projects.previewInitialCommit",
        "planning.inspectRepositoryMaturity",
        "planning.previewBootstrap",
        "projects.workspaceLocation",
        "notifications.list",
        "runs.list",
        "runs.archivePlan",
        "runs.get",
        "runs.getPlanningPreview",
        "runs.planningPreviewStatus",
        "runs.previewEffortMode",
        "runs.usage",
        "tasks.retryContext",
        "runs.resultRevisions",
        "operations.get",
        "operations.latest",
        "runs.integrationConflict",
        "tasks.log",
        "workspaces.list",
        "locks.get",
    }
)


class RpcError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class DesktopApplication:
    def __init__(self, registry: ProjectRegistry, *, codex_sdk: CodexSdkManager | None = None):
        self.registry = registry
        self.codex_sdk = codex_sdk or CodexSdkManager()
        self._prepared_indexes: dict[tuple[str, str], PlanningSourceIndex] = {}
        self._prepared_index_lock = threading.Lock()
        self._active_group_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="active-group-query")
        self._active_group_futures: dict[str, Future[list[dict[str, object]]]] = {}
        self._attention_item_futures: dict[str, Future[list[dict[str, object]]]] = {}
        self._user_check_futures: dict[str, Future[list[dict[str, object]]]] = {}
        self._active_group_lock = threading.Lock()

    def close(self) -> None:
        self._active_group_executor.shutdown(wait=False, cancel_futures=True)
        self.codex_sdk.close()

    def projects(self) -> list[object]:
        return self.registry.list()

    def active_groups(self) -> dict[str, object]:
        return self._project_summary_snapshot(self._active_groups_for_project, self._active_group_futures, "last_activity_at")

    def attention_items(self) -> dict[str, object]:
        return self._project_summary_snapshot(self._attention_items_for_project, self._attention_item_futures, "updated_at")

    def user_check_items(self, project_name: str = "") -> dict[str, object]:
        return self._project_summary_snapshot(self._user_checks_for_project, self._user_check_futures, "updated_at", project_name)

    def _project_summary_snapshot(
        self, query: Callable[[str], list[dict[str, object]]], cached: dict[str, Future[list[dict[str, object]]]], sort_field: str,
        project_name: str = "",
    ) -> dict[str, object]:
        checked_at = utc_now()
        futures: dict[str, Future[list[dict[str, object]]]] = {}
        projects = [self.registry.get(project_name)] if project_name else self.registry.list()
        with self._active_group_lock:
            for project in projects:
                future = cached.get(project.name)
                if future is None or future.done():
                    future = self._active_group_executor.submit(query, project.name)
                    cached[project.name] = future
                futures[project.name] = future
        completed, _ = wait(set(futures.values()), timeout=5)
        items: list[dict[str, object]] = []
        errors: list[dict[str, str]] = []
        for project_name, future in futures.items():
            if future not in completed:
                errors.append({"project_name": project_name, "error": "프로젝트 상태 조회 시간이 초과됐습니다.", "checked_at": checked_at})
                continue
            try:
                items.extend({"project_name": project_name, **item} for item in future.result())
            except Exception as exc:
                errors.append({"project_name": project_name, "error": str(exc), "checked_at": checked_at})
            finally:
                with self._active_group_lock:
                    if cached.get(project_name) is future:
                        del cached[project_name]
        items.sort(key=lambda item: str(item[sort_field]), reverse=True)
        return {"items": items, "errors": errors, "checked_at": checked_at}

    def _active_groups_for_project(self, project_name: str) -> list[dict[str, object]]:
        return self._pipeline(project_name).active_group_summaries()

    def _attention_items_for_project(self, project_name: str) -> list[dict[str, object]]:
        return self._pipeline(project_name).attention_item_summaries()

    def _user_checks_for_project(self, project_name: str) -> list[dict[str, object]]:
        return self._pipeline(project_name).user_check_summaries()

    def codex_auth_status(self) -> object:
        return self.codex_sdk.login_status()

    def claude_auth_status(self) -> object:
        return Pipeline.claude_connection_status()

    def set_claude_executable(self, path: str) -> object:
        from .provider_executable import set_claude_executable

        set_claude_executable(path)
        return Pipeline.claude_connection_status()

    def clear_claude_executable(self) -> object:
        from .provider_executable import clear_claude_executable

        clear_claude_executable()
        return Pipeline.claude_connection_status()

    def account_usage(self, provider: str) -> AccountUsage:
        if provider == "codex":
            return read_codex_quota()
        return read_claude_quota(Pipeline.claude_connection_status())

    def start_codex_auth(self, method: str, request_id: str) -> object:
        return self.codex_sdk.start_login(method, request_id)

    def connect_codex_api_key(self, api_key: str, request_id: str) -> object:
        return self.codex_sdk.login_api_key(api_key, request_id)

    def codex_auth_attempt(self, attempt_id: str) -> object:
        return self.codex_sdk.login_attempt(attempt_id)

    def cancel_codex_auth(self, attempt_id: str) -> object:
        return self.codex_sdk.cancel_login(attempt_id)

    def register_project(
        self, name: str, repo: str | Path, config_path: str | Path | None = None, planning_source_dir: str | Path | None = None
    ) -> object:
        repo_path = Path(repo).expanduser().resolve()
        if not repo_path.is_dir():
            raise RegistryError(f"project repository not found: {repo_path}")
        readiness = inspect_git_readiness(repo_path)
        if readiness.kind != "ready":
            raise RegistryError(f"project repository is not ready: {readiness.kind}")
        if config_path:
            configured = Path(config_path).expanduser()
            selected_config = configured.resolve() if configured.is_absolute() else (repo_path / configured).resolve()
        else:
            repository_config = repo_path / "orchestrator.toml"
            if repository_config.is_file():
                selected_config = repository_config
            else:
                selected_config = self.registry.managed_config_path(repo_path)
                if not selected_config.is_file():
                    create_default_config(selected_config, repo_path, main_branch=readiness.main_branch or "main")
        config = load_config(selected_config)
        if config.project.repo != repo_path:
            raise RegistryError(f"registered repository does not match project.repo in config: {repo_path} != {config.project.repo}")
        return self.registry.add(name or repo_path.name, repo_path, selected_config, planning_source_dir)

    def inspect_git_readiness(self, repo: str | Path) -> object:
        return inspect_git_readiness(repo)

    def preview_git_initialization(self, repo: str | Path) -> object:
        return preview_git_initialization(repo)

    def initialize_git(self, repo: str | Path, expected_kind: str, *, approved: bool) -> object:
        if not approved:
            raise RpcError("approval_required", "Git initialization requires explicit approval")
        return initialize_git_repository(repo, expected_kind=expected_kind)

    def preview_initial_commit(self, repo: str | Path) -> object:
        return preview_initial_commit(repo)

    def create_initial_commit(
        self,
        repo: str | Path,
        snapshot_id: str,
        selected_paths: list[str],
        message: str,
        *,
        author_name: str,
        author_email: str,
        save_author: bool,
        allow_empty: bool,
        approved: bool,
    ) -> object:
        if not approved:
            raise RpcError("approval_required", "initial commit requires explicit approval")
        return create_initial_commit(
            repo,
            snapshot_id,
            selected_paths,
            message,
            author_name=author_name,
            author_email=author_email,
            save_author=save_author,
            allow_empty=allow_empty,
        )

    def remove_project(self, project_name: str, *, approved: bool) -> object:
        if not approved:
            raise RpcError("approval_required", "project removal requires explicit approval")
        return self.registry.remove(project_name)

    def update_planning_source(self, project_name: str, source_root: str | Path | None) -> object:
        return self.registry.update_planning_source(project_name, source_root)

    def runs(self, project_name: str, *, scope: str = "all") -> list[object]:
        return self._pipeline(project_name).list_summaries(scope)

    def result_revisions(self, project_name: str, run_id: str) -> object:
        return self._pipeline(project_name).result_revision_requests(run_id)

    def propose_result_revision(self, project_name: str, run_id: str, *, proposal_id: str, text: str, focus_task_id: str) -> object:
        return self._pipeline(project_name).propose_result_revision(
            run_id, proposal_id=proposal_id, text=text, focus_task_id=focus_task_id
        )

    def create_result_revision(
        self, project_name: str, run_id: str, *, request_id: str, text: str,
        task_ids: list[str], paths: list[str], proposal_id: str = "",
    ) -> object:
        return self._pipeline(project_name).create_result_revision_request(
            run_id, request_id=request_id, text=text, task_ids=task_ids, paths=paths, proposal_id=proposal_id
        )

    def notifications(self, project_name: str, *, after_cursor: str = "", limit: int = 100) -> object:
        return self._pipeline(project_name).notifications(after_cursor=after_cursor, limit=limit)

    def update_dotnet(self, project_name: str, executable: str) -> object:
        return self.registry.update_dotnet(project_name, executable)

    def workspace_location(self, project_name: str) -> object:
        project = self.registry.get(project_name)
        config = load_config(project.config_path)
        if config.project.repo != project.repo:
            raise RegistryError(f"registered project config changed repository: {project.name}")
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
        project = self.registry.get(project_name)
        config = load_config(project.config_path)
        if config.project.repo != project.repo:
            raise RegistryError(f"registered project config changed repository: {project.name}")
        return {
            "deployment_configured": bool(config.execution.deploy_command),
            "repository_maturity": asdict(inspect_repository_maturity(project.repo)),
        }

    def code_style_profile(self, project_name: str) -> object:
        project = self.registry.get(project_name)
        return inspect_project_code_style(
            project.repo,
            project.code_style_preference,
            preference_revision=project.code_style_preference_revision,
        ).to_dict()

    def preview_code_style_preference(self, project_name: str, preference: ProjectCodeStylePreference) -> object:
        project = self.registry.get(project_name)
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
            raise RpcError("approval_required", "code style preference update requires explicit approval")
        project = self.registry.update_code_style_preference(
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
        project = self.registry.get(project_name)
        return asdict(inspect_repository_maturity(project.repo))

    def check_dotnet(self, project_name: str, run_id: str, task_id: str) -> object:
        return self._pipeline(project_name).check_dotnet(run_id=run_id, task_id=task_id)

    def status(self, project_name: str, run_id: str, *, include_user_checks: bool = False) -> object:
        pipeline = self._pipeline(project_name)
        state, execution_control, integration_control = pipeline.status_with_controls(run_id)
        result = _run_state_view(pipeline.execution_profile_view(state))
        messages = {task.id: pipeline.task_failure_message(task) for task in state.tasks}
        for task in result["tasks"]:
            task["error"] = messages[task["id"]]
        result["execution_control"] = execution_control
        result["project_chat_available"] = bool(state.tasks) and state.archive is None and state.stage in {
            Stage.PLANNED, Stage.EXECUTING, Stage.FAILED, Stage.READY_TO_MERGE, Stage.VERIFIED,
            Stage.WORK_BRANCH_PUSHED, Stage.MERGED, Stage.PUSHED, Stage.DEPLOYED,
        }
        result["integration_control"] = integration_control
        result["main_operations"] = pipeline.latest_main_operations(run_id)
        result["effort_control"] = pipeline.effort_control(run_id, expected_state=state)
        result["waiting_prompt"] = pipeline.waiting_prompt(state, execution_control, integration_control)
        if include_user_checks:
            result["user_checks"] = pipeline.user_checks(state, include_recorded=True)
        return result

    def preview_effort_mode(self, project_name: str, run_id: str, mode: str, expected_revision: int) -> object:
        return self._pipeline(project_name).desktop_effort_mode_preview(run_id, mode, expected_revision=expected_revision)

    def usage(self, project_name: str, run_id: str, *, execution_request_id: str, cursor: str, limit: int) -> object:
        return self._pipeline(project_name).usage(run_id, execution_request_id=execution_request_id, cursor=cursor, limit=limit)

    def set_effort_mode(
        self, project_name: str, run_id: str, mode: str, target: str, expected_revision: int, request_id: str
    ) -> object:
        return self._pipeline(project_name).set_effort_mode(
            run_id, mode, target=target, expected_revision=expected_revision, request_id=request_id
        )

    def cancel_effort_reservation(self, project_name: str, run_id: str, expected_revision: int, request_id: str) -> object:
        return self._pipeline(project_name).cancel_effort_reservation(run_id, expected_revision=expected_revision, request_id=request_id)

    def apply_effort_mode_to_plan(
        self, project_name: str, run_id: str, mode: str, policy_revision: int, plan_revision: int, reviewers: dict[str, str] | None
    ) -> object:
        return self._pipeline(project_name).apply_effort_mode_to_plan(
            run_id, mode, expected_policy_revision=policy_revision, expected_plan_revision=plan_revision, reviewer_agent_ids=reviewers
        )

    def preview_bootstrap(self, project_name: str, run_id: str) -> object:
        return self._pipeline(project_name).preview_bootstrap(run_id)

    def generate_feature_plan(self, project_name: str, run_id: str) -> object:
        return self._pipeline(project_name).generate_feature_plan(run_id)

    def interrupt_planning(self, project_name: str, run_id: str, *, approved: bool) -> object:
        return self._pipeline(project_name).interrupt_planning(run_id, approved=approved)

    def begin_planning_request(self, project_name: str, run_id: str, *, request_id: str, kind: str, message: str = "") -> object:
        return self._pipeline(project_name).begin_planning_request(run_id, request_id=request_id, kind=kind, message=message)

    def request_chat_control(self, project_name: str, run_id: str, **values: object) -> object:
        return self._pipeline(project_name).request_chat_control(run_id, **values)

    def decide_project_chat(self, project_name: str, run_id: str, request_id: str) -> object:
        return self._pipeline(project_name).decide_project_chat(run_id, request_id)

    def perform_project_chat(self, project_name: str, run_id: str, request_id: str, step_id: str) -> object:
        return self._pipeline(project_name).perform_project_chat(run_id, request_id, step_id)

    def advance_chat_control(self, project_name: str, run_id: str, request_id: str, *, suspend: bool) -> object:
        return self._pipeline(project_name).advance_chat_control(run_id, request_id, suspend=suspend)

    def cancel_chat_control(self, project_name: str, run_id: str, request_id: str) -> object:
        return self._pipeline(project_name).cancel_chat_control(run_id, request_id)

    def finish_planning_request(self, project_name: str, run_id: str, *, request_id: str, phase: str, error: str) -> object:
        return self._pipeline(project_name).finish_planning_request(run_id, request_id=request_id, phase=phase, error=error)

    def task_log(self, project_name: str, run_id: str, task_id: str) -> str:
        return self._pipeline(project_name).task_log(run_id, task_id)

    def update_main(self, project_name: str, *, approved: bool) -> object:
        return self._pipeline(project_name).update_main(approved=approved)

    def main_changes(self, project_name: str, *, refresh_remote: bool = False) -> object:
        return self._pipeline(project_name).main_changes(refresh_remote=refresh_remote)

    def main_change_diff(self, project_name: str, snapshot_id: str, path: str, mode: str) -> object:
        return self._pipeline(project_name).main_change_diff(snapshot_id, path, mode)

    def commit_main_changes(
        self, project_name: str, snapshot_id: str, selections: list[tuple[str, str]], message: str, *, approved: bool
    ) -> object:
        return self._pipeline(project_name).commit_main_changes(snapshot_id, selections, message, approved=approved)

    def commit_and_push_main_changes(
        self, project_name: str, snapshot_id: str, selections: list[tuple[str, str]], message: str, *, approved: bool
    ) -> object:
        return self._pipeline(project_name).commit_and_push_main_changes(snapshot_id, selections, message, approved=approved)

    def push_main_commits(self, project_name: str, snapshot_id: str, *, approved: bool) -> object:
        return self._pipeline(project_name).push_main_commits(snapshot_id, approved=approved)

    def planning_provider_choices(self, project_name: str) -> list[object]:
        choices = self._pipeline(project_name).planning_provider_choices()
        return _expanded_provider_choices(choices)

    def execution_provider_choices(self, project_name: str, capabilities: list[str]) -> list[object]:
        choices = self._pipeline(project_name).execution_provider_choices(capabilities)
        return _expanded_provider_choices(choices)

    def provider_statuses(self, project_name: str) -> list[object]:
        return self._pipeline(project_name).provider_statuses()

    def refresh_planning_index(self, project_name: str, source_root: str | Path) -> object:
        index = self._pipeline(project_name).refresh_planning_index(source_root)
        token_key = (project_name, str(Path(index.source_root).resolve()))
        with self._prepared_index_lock:
            self._prepared_indexes[token_key] = index
        return {
            "source_root": index.source_root,
            "generated_at": index.generated_at,
            "document_count": index.document_count,
            "reused_count": index.reused_count,
            "updated_count": index.updated_count,
            "added_count": index.added_count,
            "modified_count": index.modified_count,
            "deleted_count": index.deleted_count,
        }

    def start(
        self,
        project_name: str,
        spec_path: str | Path,
        *,
        planning_agent_id: str = "",
        planning_model: str = "",
        planning_reasoning_effort: str = "",
        planning_mode: str = "auto",
        planning_request: str = "",
        effort_mode: str = "balanced",
        planning_profile_source: str | None = None,
    ) -> object:
        pipeline = self._pipeline(project_name)
        selected_agent_id = self._desktop_planning_agent_id(pipeline, planning_agent_id)
        return pipeline.start(
            spec_path,
            planning_agent_id=selected_agent_id,
            planning_model=planning_model,
            planning_reasoning_effort=planning_reasoning_effort,
            planning_mode=planning_mode,
            planning_request=planning_request,
            effort_mode=effort_mode,
            planning_profile_source=planning_profile_source,
        )

    def prepare_planning(
        self,
        project_name: str,
        spec_path: str | Path,
        *,
        planning_agent_id: str = "",
        planning_model: str = "",
        planning_reasoning_effort: str = "",
        planning_mode: str = "auto",
        planning_request: str = "",
        prepared_index_generated_at: str = "",
        repository_intent: str = "",
        effort_mode: str = "balanced",
        planning_profile_source: str | None = None,
        reserved_run_id: str = "",
    ) -> object:
        pipeline = self._pipeline(project_name)
        selected_agent_id = self._desktop_planning_agent_id(pipeline, planning_agent_id)
        raw_spec_path = str(spec_path).strip()
        issued_index = None
        if raw_spec_path:
            token_key = (project_name, str(Path(raw_spec_path).expanduser().resolve()))
            with self._prepared_index_lock:
                issued_index = self._prepared_indexes.pop(token_key, None)
        accepted_index = issued_index if issued_index is not None and prepared_index_generated_at == issued_index.generated_at else None
        return pipeline.prepare_planning(
            spec_path,
            planning_agent_id=selected_agent_id,
            planning_model=planning_model,
            planning_reasoning_effort=planning_reasoning_effort,
            planning_mode=planning_mode,
            planning_request=planning_request,
            prepared_source_index=accepted_index,
            repository_intent=repository_intent,
            effort_mode=effort_mode,
            planning_profile_source=planning_profile_source,
            **({"reserved_run_id": reserved_run_id} if reserved_run_id else {}),
        )

    @staticmethod
    def _desktop_planning_agent_id(pipeline: Pipeline, requested_agent_id: str) -> str:
        choices = pipeline.planning_provider_choices()
        requested = requested_agent_id.strip()
        if requested:
            if any(choice.agent_id == requested for choice in choices):
                return requested
            raise RpcError("provider_excluded", "선택한 Planning 모델은 현재 신규 선택에서 제외되어 있습니다. 다른 모델을 선택해 주세요.")
        if not choices:
            raise RpcError("provider_unavailable", "사용 가능한 Planning 모델이 없습니다. Provider 연결 상태를 확인해 주세요.")
        return choices[0].agent_id

    @staticmethod
    def _ensure_desktop_execution_profiles(
        pipeline: Pipeline, run_id: str, agent_overrides: dict[str, str], *, task_ids: set[str] | None = None
    ) -> None:
        state = pipeline.status(run_id)
        check_blocked = state.user_check_blocked_task_ids()
        for task in state.tasks:
            if task.id in check_blocked or (task_ids is not None and task.id not in task_ids):
                continue
            if task.status.value not in {"pending", "waiting", "failed", "stopped"}:
                continue
            choices = pipeline.execution_provider_choices(task.capabilities)
            selected_agent_id = agent_overrides.get(task.id, task.agent_id)
            selected = next((choice for choice in choices if choice.agent_id == selected_agent_id), None)
            if selected is None:
                raise RpcError(
                    "provider_unavailable",
                    f"Task {task.id}의 실행 AI를 사용할 수 없습니다. AI 연결과 실행 모델을 확인해 주세요.",
                )

    def external_planning_context(self, project: RegisteredProject) -> dict[str, object]:
        return self._pipeline(project.name, expected_project=project).external_planning_context()

    def submit_external_plan(
        self, project: RegisteredProject, run_id: str, *, expected_base_commit: str, summary: str, requirements: str,
        task_drafts: list[dict[str, object]], server_work: bool, user_checks: tuple[UserCheck, ...] = (),
    ) -> RunState:
        return self._pipeline(project.name, expected_project=project).submit_external_plan(
            run_id, expected_base_commit=expected_base_commit, summary=summary, requirements=requirements,
            task_drafts=task_drafts, server_work=server_work, user_checks=user_checks,
        )

    def record_user_check(
        self, project_name: str, run_id: str, check_id: str, *, expected_revision: int, expected_commit: str, outcome: str, note: str,
    ) -> RunState:
        return self._pipeline(project_name).record_user_check(
            run_id, check_id, expected_revision=expected_revision, expected_commit=expected_commit, outcome=outcome, note=note,
        )

    def run_planning(self, project_name: str, run_id: str) -> object:
        return self._pipeline(project_name).run_planning(run_id)

    def send_planning_message(
        self,
        project_name: str,
        run_id: str,
        message: str,
        *,
        planning_agent_id: str | None = None,
        planning_model: str | None = None,
        planning_reasoning_effort: str | None = None,
    ) -> object:
        pipeline = self._pipeline(project_name)
        selected_agent_id = self._desktop_planning_agent_id(pipeline, planning_agent_id or "")
        return pipeline.send_planning_message(
            run_id, message, planning_agent_id=selected_agent_id, planning_model=planning_model, planning_reasoning_effort=planning_reasoning_effort
        )

    def request_direction_change(self, project_name: str, run_id: str, *, request_id: str, text: str) -> object:
        return self._pipeline(project_name).request_direction_change(run_id, request_id=request_id, text=text)

    def apply_planning_conversation(
        self,
        project_name: str,
        run_id: str,
        *,
        request_id: str,
        expected_revision: int,
        conversation_revision: int,
        answer_message: str = "",
        expected_tech_stack_revision: int | None = None,
        retry_failed: bool = False,
        planning_agent_id: str | None = None,
        planning_model: str | None = None,
        planning_reasoning_effort: str | None = None,
    ) -> object:
        pipeline = self._pipeline(project_name)
        if pipeline.status(run_id).repository_intent != "new_project":
            raise PipelineError("Task 계획 반영은 미리보기를 생성하고 확인한 뒤 진행해 주세요.")
        profile_options: dict[str, object] = {}
        if planning_agent_id is not None or planning_model is not None or planning_reasoning_effort is not None:
            profile_options = {
                "planning_agent_id": self._desktop_planning_agent_id(pipeline, planning_agent_id or ""),
                "planning_model": planning_model,
                "planning_reasoning_effort": planning_reasoning_effort,
            }
        return pipeline.request_planning_conversation_apply(
            run_id,
            request_id=request_id,
            expected_revision=expected_revision,
            conversation_revision=conversation_revision,
            **({"answer_message": answer_message, "expected_tech_stack_revision": expected_tech_stack_revision,
                "retry_failed": retry_failed} if expected_tech_stack_revision is not None or answer_message or retry_failed else {}),
            **profile_options,
        )

    def planning_apply_preview(self, project_name: str, run_id: str) -> object:
        return self._pipeline(project_name).planning_apply_preview(run_id)

    def planning_preview_status(self, project_name: str, run_id: str) -> object:
        return self._pipeline(project_name).planning_preview_status(run_id)

    def task_retry_context(self, project_name: str, run_id: str, task_id: str) -> object:
        return self._pipeline(project_name).task_retry_context(run_id, task_id)

    def record_task_diagnosis(self, project_name: str, run_id: str, task_id: str, fingerprint: str, diagnosis: str) -> None:
        self._pipeline(project_name).record_task_diagnosis(run_id, task_id, fingerprint, diagnosis)

    def save_task_retry_instruction(
        self, project_name: str, run_id: str, task_id: str, *, request_id: str, text: str, fingerprint: str
    ) -> object:
        return self._pipeline(project_name).save_task_retry_instruction(
            run_id, task_id, request_id=request_id, text=text, fingerprint=fingerprint
        )

    def preview_planning_apply(self, project_name: str, run_id: str, *, request_id: str) -> object:
        return self._pipeline(project_name).preview_planning_apply(run_id, request_id=request_id)

    def apply_planning_preview(
        self, project_name: str, run_id: str, *, preview_id: str, fingerprint: str, candidate_digest: str
    ) -> object:
        return self._pipeline(project_name).apply_planning_preview(
            run_id, preview_id=preview_id, fingerprint=fingerprint, candidate_digest=candidate_digest
        )

    def confirm_tech_stack(self, project_name: str, run_id: str, *, option_id: str, expected_revision: int) -> object:
        return self._pipeline(project_name).confirm_tech_stack(
            run_id,
            option_id=option_id,
            expected_revision=expected_revision,
        )

    def configure_bootstrap_agent_instructions(
        self,
        project_name: str,
        run_id: str,
        *,
        create: bool,
        expected_revision: int,
        expected_digest: str,
    ) -> object:
        return self._pipeline(project_name).configure_bootstrap_agent_instructions(
            run_id,
            create=create,
            expected_revision=expected_revision,
            expected_digest=expected_digest,
        )

    def execute(
        self,
        project_name: str,
        run_id: str,
        *,
        agent_overrides: dict[str, str] | None = None,
        model_overrides: dict[str, str] | None = None,
        reasoning_effort_overrides: dict[str, str] | None = None,
        expected_revision: int | None = None,
    ) -> object:
        pipeline = self._pipeline(project_name)
        self._ensure_desktop_execution_profiles(pipeline, run_id, agent_overrides or {})
        return pipeline.execute(
            run_id, agent_overrides=agent_overrides, model_overrides=model_overrides, reasoning_effort_overrides=reasoning_effort_overrides,
            **({"expected_revision": expected_revision} if expected_revision is not None else {}),
        )

    def resume(self, project_name: str, run_id: str, *, expected_revision: int | None = None) -> object:
        pipeline = self._pipeline(project_name)
        self._ensure_desktop_execution_profiles(pipeline, run_id, {})
        return pipeline.resume(run_id, **({"expected_revision": expected_revision} if expected_revision is not None else {}))

    def request_stop(
        self,
        project_name: str,
        run_id: str,
        *,
        request_id: str,
        execution_id: str,
        scope: str,
        task_id: str = "",
        attempt_id: str = "",
        invocation_id: str = "",
        chat_message: str = "",
    ) -> object:
        return self._pipeline(project_name).request_stop(
            run_id,
            request_id=request_id,
            execution_id=execution_id,
            scope=scope,
            task_id=task_id,
            attempt_id=attempt_id,
            invocation_id=invocation_id,
            **({"chat_message": chat_message} if chat_message else {}),
        )

    def recovery_plan(self, project_name: str, run_id: str, *, request_id: str = "") -> object:
        return self._pipeline(project_name).recovery_plan(run_id, request_id=request_id)

    def apply_recovery(
        self,
        project_name: str,
        run_id: str,
        fingerprint: str,
        source_ids: list[str],
        *,
        approved: bool,
        request_id: str = "",
        resume_request_id: str = "",
    ) -> object:
        return self._pipeline(project_name).apply_recovery(
            run_id,
            fingerprint,
            source_ids,
            approved=approved,
            request_id=request_id,
            resume_request_id=resume_request_id,
        )

    def recovery_operation(self, project_name: str, run_id: str, request_id: str) -> object:
        return self._pipeline(project_name).recovery_operation(run_id, request_id)

    def latest_recovery_operation(self, project_name: str, run_id: str, kind: str) -> object:
        return self._pipeline(project_name).latest_recovery_operation(run_id, kind)

    def execute_task(
        self,
        project_name: str,
        run_id: str,
        task_id: str,
        *,
        agent_overrides: dict[str, str] | None = None,
        model_overrides: dict[str, str] | None = None,
        reasoning_effort_overrides: dict[str, str] | None = None,
    ) -> object:
        pipeline = self._pipeline(project_name)
        self._ensure_desktop_execution_profiles(pipeline, run_id, agent_overrides or {}, task_ids={task_id})
        return pipeline.execute_task(
            run_id, task_id, agent_overrides=agent_overrides, model_overrides=model_overrides, reasoning_effort_overrides=reasoning_effort_overrides
        )

    def retry_task(self, project_name: str, run_id: str, task_id: str) -> object:
        pipeline = self._pipeline(project_name)
        self._ensure_desktop_execution_profiles(pipeline, run_id, {}, task_ids={task_id})
        return pipeline.retry_task(run_id, task_id)

    def repair_task_from_chat(
        self, project_name: str, run_id: str, task_id: str, *, request_id: str, message: str,
        fingerprint: str, conversation_revision: int, parent_request_id: str = "", recovery_fingerprint: str = "",
    ) -> object:
        pipeline = self._pipeline(project_name)
        self._ensure_desktop_execution_profiles(pipeline, run_id, {})
        return pipeline.repair_task_from_chat(
            run_id, task_id, request_id=request_id, message=message, fingerprint=fingerprint, conversation_revision=conversation_revision,
            **({"parent_request_id": parent_request_id} if parent_request_id else {}),
            **({"recovery_fingerprint": recovery_fingerprint} if recovery_fingerprint else {}),
        )

    def result_artifact(self, project_name: str, run_id: str) -> object:
        return self._pipeline(project_name).result_artifact_info(run_id)

    def register_result(self, project_name: str, run_id: str, *, kind: str, relative_path: str, expected_commit: str) -> object:
        return self._pipeline(project_name).register_result_artifact(
            run_id, kind=kind, relative_path=relative_path, expected_commit=expected_commit,
        )

    def launch_result(self, project_name: str, run_id: str, *, expected_digest: str, device_id: str = "") -> object:
        return self._pipeline(project_name).launch_result_artifact(run_id, expected_digest=expected_digest, device_id=device_id)

    def verify(self, project_name: str, run_id: str) -> object:
        return self._pipeline(project_name).verify(run_id)

    def verify_and_repair(self, project_name: str, run_id: str, request_id: str, chat_message: str = "", parent_request_id: str = "") -> object:
        return self._pipeline(project_name).verify_and_repair(
            run_id, request_id=request_id, **({"chat_message": chat_message} if chat_message else {}),
            **({"parent_request_id": parent_request_id} if parent_request_id else {}),
        )

    def complete_task(self, project_name: str, run_id: str, task_id: str) -> object:
        return self._pipeline(project_name).complete_task(run_id, task_id)

    def complete_manual_verification(
        self, project_name: str, run_id: str, task_id: str, *, note: str, expected_commit: str, expected_revision: int,
    ) -> object:
        return self._pipeline(project_name).complete_manual_verification(
            run_id, task_id, note=note, expected_commit=expected_commit, expected_revision=expected_revision,
        )

    def handoff_manual_task_to_ai(self, project_name: str, run_id: str, task_id: str, *, expected_commit: str, expected_revision: int) -> object:
        pipeline = self._pipeline(project_name)
        self._ensure_desktop_execution_profiles(pipeline, run_id, {}, task_ids={task_id})
        return pipeline.handoff_manual_task_to_ai(run_id, task_id, expected_commit=expected_commit, expected_revision=expected_revision)

    def set_manual_task_deferred(self, project_name: str, run_id: str, task_id: str, *, deferred: bool) -> object:
        return self._pipeline(project_name).set_manual_task_deferred(run_id, task_id, deferred=deferred)

    def exclude_tasks(self, project_name: str, run_id: str, task_ids: list[str], *, approved: bool) -> object:
        if not approved:
            raise RpcError("approval_required", "task exclusion requires explicit approval")
        return self._pipeline(project_name).exclude_tasks(run_id, task_ids)

    def update_plan(
        self, project_name: str, run_id: str, task_drafts: list[dict[str, object]], *, expected_revision: int | None = None,
    ) -> object:
        options = {"expected_revision": expected_revision} if expected_revision is not None else {}
        return self._pipeline(project_name).update_plan(run_id, task_drafts, **options)

    def update_task_execution_profile(
        self, project_name: str, run_id: str, task_id: str, *, agent_id: str, model: str, reasoning_effort: str,
        expected_profile: dict[str, str],
    ) -> object:
        return self._pipeline(project_name).update_task_execution_profile(
            run_id, task_id, agent_id=agent_id, model=model, reasoning_effort=reasoning_effort, expected_profile=expected_profile
        )

    def confirm_plan(
        self, project_name: str, run_id: str, *, expected_revision: int | None = None, expected_bootstrap_digest: str = ""
    ) -> object:
        if expected_revision is None and not expected_bootstrap_digest:
            return self._pipeline(project_name).confirm_plan(run_id)
        return self._pipeline(project_name).confirm_plan(
            run_id, expected_revision=expected_revision, expected_bootstrap_digest=expected_bootstrap_digest
        )

    def approved_run_action(
        self, project_name: str, run_id: str, action: str, *, approved: bool, request_id: str = "",
        expected_repo: str = "", expected_commit: str = "",
    ) -> object:
        pipeline = self._pipeline(project_name)
        if action == "merge":
            return pipeline.merge(run_id, approved=approved, request_id=request_id)
        if action == "push":
            return pipeline.push(run_id, approved=approved, request_id=request_id)
        if action == "retryMainPush":
            return pipeline.retry_main_push(run_id, approved=approved, request_id=request_id)
        if action == "recoverMainApply":
            return pipeline.recover_main_apply(
                run_id, approved=approved, request_id=request_id, expected_repo=expected_repo, expected_commit=expected_commit
            )
        if action == "deploy":
            return pipeline.deploy(run_id, approved=approved)
        raise RpcError("invalid_params", f"unsupported run action: {action}")

    def preview_main_apply(self, project_name: str, run_id: str) -> dict[str, object]:
        return self._pipeline(project_name).preview_main_apply(run_id)

    def apply_reviewed_main(self, project_name: str, run_id: str, *, request_id: str, review_id: str,
                            approved: bool) -> tuple[RunState, str]:
        return self._pipeline(project_name).apply_reviewed_main(run_id, request_id=request_id, review_id=review_id, approved=approved)

    def approve_task_scope(self, project_name: str, run_id: str, task_id: str, *, request_id: str, review_id: str,
                           approved: bool) -> dict[str, object]:
        return self._pipeline(project_name).approve_task_scope(run_id, task_id, request_id=request_id, review_id=review_id,
                                                               approved=approved)

    def delete_run(self, project_name: str, run_id: str, *, approved: bool) -> object:
        return self._pipeline(project_name).delete_run(run_id, approved=approved)

    def archive_plan(self, project_name: str, run_id: str) -> object:
        return self._pipeline(project_name).archive_plan(run_id)

    def archive_run(
        self,
        project_name: str,
        run_id: str,
        *,
        expected_revision: str,
        fingerprint: str,
        request_id: str,
        approved: bool,
    ) -> object:
        return self._pipeline(project_name).archive_run(
            run_id,
            expected_revision=expected_revision,
            fingerprint=fingerprint,
            request_id=request_id,
            approved=approved,
        )

    def retry_archive_cleanup(
        self,
        project_name: str,
        run_id: str,
        *,
        fingerprint: str,
        request_id: str,
        approved: bool,
    ) -> object:
        return self._pipeline(project_name).retry_archive_cleanup(
            run_id,
            fingerprint=fingerprint,
            request_id=request_id,
            approved=approved,
        )

    def workspace_statuses(self, project_name: str, run_id: str) -> list[object]:
        return self._pipeline(project_name).workspace_statuses(run_id)

    def cleanup_workspace(self, project_name: str, run_id: str, task_id: str, *, approved: bool) -> object:
        return self._pipeline(project_name).cleanup_workspace(run_id, task_id, approved=approved)

    def integration_conflict(
        self, project_name: str, run_id: str, conflict_id: str = "", file_path: str = "", recovery_task_id: str = ""
    ) -> object:
        return self._pipeline(project_name).integration_conflict(
            run_id, conflict_id=conflict_id, file_path=file_path, recovery_task_id=recovery_task_id
        )

    def prepare_conflict_resolution(self, project_name: str, run_id: str, **values: str) -> object:
        pipeline = self._pipeline(project_name)
        requested = values.get("agent_id", "")
        choices = pipeline.execution_provider_choices(["general"])
        selected = next((choice for choice in choices if choice.agent_id == requested), None) if requested else (choices[0] if choices else None)
        if selected is None:
            raise RpcError("provider_excluded", "사용 가능한 충돌 해결 모델이 없습니다. 다른 모델을 선택해 주세요.")
        return pipeline.prepare_conflict_resolution(run_id, **{**values, "agent_id": selected.agent_id})

    def apply_conflict_resolution(self, project_name: str, run_id: str, *, approved: bool, **values: object) -> object:
        return self._pipeline(project_name).apply_conflict_resolution(run_id, approved=approved, **values)

    def run_lock_status(self, project_name: str, run_id: str) -> object:
        return self._pipeline(project_name).run_lock_status(run_id)

    def clear_run_lock(self, project_name: str, run_id: str, *, approved: bool) -> object:
        return self._pipeline(project_name).clear_run_lock(run_id, approved=approved)

    def _pipeline(self, project_name: str, *, expected_project: RegisteredProject | None = None) -> Pipeline:
        project = self.registry.get(project_name)
        if expected_project is not None and project != expected_project:
            raise RegistryError("프로젝트 등록 정보가 변경됐습니다. 계획 컨텍스트를 다시 조회해 주세요.")
        config = load_config(project.config_path)
        if config.project.repo != project.repo:
            raise RegistryError(f"registered project config changed repository: {project.name}")
        return Pipeline(
            config,
            codex_sdk=self.codex_sdk,
            dotnet_executable=project.dotnet_executable,
            code_style_preference=project.code_style_preference,
            code_style_preference_revision=project.code_style_preference_revision,
        )


class RpcService:
    def __init__(self, application: DesktopApplication):
        self.application = application

    def dispatch(self, method: str, params: object) -> object:
        values = _object_params(params)
        if method == "system.hello":
            return {"rpcVersion": RPC_VERSION, "application": "ai-work-orchestrator"}
        if method == "connections.externalGuide":
            from .mcp_bundle import external_connection_guide

            return external_connection_guide(self.application.registry.path)
        if method == "connections.registerExternal":
            from .mcp_bundle import register_external_connection

            return register_external_connection(_required_string(values, "client"), self.application.registry.path)
        if method == "auth.codex.status":
            return self.application.codex_auth_status()
        if method == "auth.claude.status":
            return self.application.claude_auth_status()
        if method == "auth.claude.setExecutable":
            return self.application.set_claude_executable(_required_string(values, "path"))
        if method == "auth.claude.clearExecutable":
            return self.application.clear_claude_executable()
        if method == "providers.accountUsage":
            provider = _required_string(values, "provider")
            if provider not in {"codex", "claude"}:
                raise RpcError("invalid_params", "provider must be codex or claude")
            return self.application.account_usage(provider)
        if method == "auth.codex.start":
            login_method = _required_string(values, "method")
            if login_method not in {"browser", "device_code"}:
                raise RpcError("invalid_params", "Codex login method must be browser or device_code")
            return self.application.start_codex_auth(login_method, _required_string(values, "requestId"))
        if method == "auth.codex.apiKey":
            if isinstance(values.get("apiKey"), str) and any(c in values["apiKey"] for c in ("\x00", "\n", "\r")):
                raise RpcError("invalid_params", "OpenAI API 키를 공백 없는 한 줄로 입력해 주세요.")
            api_key = _required_string(values, "apiKey")
            if len(api_key) > 4096 or any(ord(character) < 33 or ord(character) > 126 for character in api_key):
                raise RpcError("invalid_params", "OpenAI API 키를 공백 없는 한 줄로 입력해 주세요.")
            return self.application.connect_codex_api_key(api_key, _required_string(values, "requestId"))
        if method == "auth.codex.get":
            return self.application.codex_auth_attempt(_required_string(values, "attemptId"))
        if method == "auth.codex.cancel":
            return self.application.cancel_codex_auth(_required_string(values, "attemptId"))
        if method == "projects.list":
            return self.application.projects()
        if method == "runs.activeGroups":
            return self.application.active_groups()
        if method == "runs.attentionItems":
            return self.application.attention_items()
        if method == "projects.inspectGitReadiness":
            return self.application.inspect_git_readiness(_required_path_string(values, "repo"))
        if method == "projects.previewGitInitialization":
            return self.application.preview_git_initialization(_required_path_string(values, "repo"))
        if method == "projects.initializeGit":
            return self.application.initialize_git(
                _required_path_string(values, "repo"),
                _required_string(values, "expectedKind"),
                approved=_required_approval(values),
            )
        if method == "projects.previewInitialCommit":
            return self.application.preview_initial_commit(_required_path_string(values, "repo"))
        if method == "projects.createInitialCommit":
            return self.application.create_initial_commit(
                _required_path_string(values, "repo"),
                _required_string(values, "snapshotId"),
                _string_list(values, "selectedPaths"),
                _required_string(values, "message"),
                author_name=_optional_string(values, "authorName"),
                author_email=_optional_string(values, "authorEmail"),
                save_author=_boolean(values, "saveAuthor", default=True),
                allow_empty=_boolean(values, "allowEmpty", default=False),
                approved=_required_approval(values),
            )
        if method == "projects.add":
            return self.application.register_project(
                _optional_string(values, "name"),
                _required_string(values, "repo"),
                _optional_string(values, "configPath") or None,
                _optional_string(values, "planningSourceDir") or None,
            )
        allowed_project_methods = {
            "runs.decideProjectChat", "runs.performProjectChat",
            "runs.requestChatControl", "runs.advanceChatControl", "runs.cancelChatControl",
            "runs.beginPlanningRequest", "runs.finishPlanningRequest",
            "runs.recoveryPlan",
            "runs.applyRecovery",
            "runs.integrationConflict",
            "runs.prepareConflictResolution",
            "runs.applyConflictResolution",
            "projects.updateDotnet",
            "projects.capabilities",
            "projects.codeStyleProfile",
            "projects.previewCodeStylePreference",
            "projects.updateCodeStylePreference",
            "planning.inspectRepositoryMaturity",
            "planning.previewBootstrap",
            "planning.generateFeaturePlan",
            "projects.workspaceLocation",
            "projects.checkDotnet",
            "projects.remove",
            "projects.updatePlanningSource",
            "projects.updateMain",
            "projects.mainChanges",
            "projects.mainChangeDiff",
            "projects.refreshMainRemote",
            "projects.commitMainChanges",
            "projects.commitAndPushMainChanges",
            "projects.pushMainCommits",
            "providers.planning",
            "providers.execution",
            "providers.status",
            "planning.refreshIndex",
            "runs.preparePlanning",
            "runs.proposeResultRevision",
            "runs.createResultRevision",
            "runs.runPlanning",
            "runs.list",
            "runs.archivePlan",
            "runs.archive",
            "runs.retryArchiveCleanup",
            "notifications.list",
            "runs.get",
            "runs.getPlanningPreview",
            "runs.planningPreviewStatus",
            "runs.previewEffortMode",
            "runs.usage",
            "runs.setEffortMode",
            "runs.cancelEffortReservation",
            "runs.applyEffortModeToPlan",
            "tasks.retryContext",
            "tasks.saveRetryInstruction",
            "runs.resultRevisions",
            "operations.get",
            "operations.latest",
            "runs.interruptPlanning",
            "runs.start",
            "runs.sendPlanningMessage",
            "runs.requestDirectionChange",
            "runs.previewPlanningApply",
            "runs.applyPlanningPreview",
            "runs.applyPlanningConversation",
            "runs.confirmTechStack",
            "runs.configureBootstrapInstructions",
            "tasks.log",
            "runs.execute",
            "runs.resume",
            "runs.requestStop",
            "tasks.execute",
            "tasks.retry",
            "tasks.repairFromChat",
            "tasks.updateExecutionProfile",
            "tasks.complete",
            "tasks.completeManualVerification",
            "runs.recordUserCheck",
            "runs.resultArtifact",
            "runs.registerResult",
            "runs.launchResult",
            "tasks.handoffToAi",
            "tasks.deferManual",
            "tasks.resumeManual",
            "runs.verify",
            "runs.verifyAndRepair",
            "runs.excludeTasks",
            "runs.updatePlan",
            "runs.confirmPlan",
            "runs.merge",
            "runs.push",
            "runs.retryMainPush",
            "runs.recoverMainApply",
            "runs.deploy",
            "runs.delete",
            "workspaces.list",
            "workspaces.cleanup",
            "locks.get",
            "locks.clear",
        }
        if method not in allowed_project_methods:
            raise RpcError("method_not_found", f"unsupported RPC method: {method}")
        project_name = _required_string(values, "projectName")
        if method == "projects.updateDotnet":
            return self.application.update_dotnet(project_name, _optional_string(values, "executable"))
        if method == "projects.capabilities":
            return self.application.project_capabilities(project_name)
        if method == "projects.codeStyleProfile":
            return self.application.code_style_profile(project_name)
        if method == "projects.previewCodeStylePreference":
            return self.application.preview_code_style_preference(project_name, _code_style_preference(values))
        if method == "projects.updateCodeStylePreference":
            return self.application.update_code_style_preference(
                project_name,
                _code_style_preference(values),
                _required_integer(values, "expectedRevision"),
                approved=_required_approval(values),
            )
        if method == "planning.inspectRepositoryMaturity":
            return self.application.inspect_repository_maturity(project_name)
        if method == "projects.workspaceLocation":
            return self.application.workspace_location(project_name)
        if method == "projects.checkDotnet":
            return self.application.check_dotnet(project_name, _optional_string(values, "runId"), _optional_string(values, "taskId"))
        if method == "projects.remove":
            return self.application.remove_project(project_name, approved=_required_approval(values))
        if method == "projects.updatePlanningSource":
            return self.application.update_planning_source(project_name, _optional_string(values, "sourceRoot") or None)
        if method == "projects.updateMain":
            return self.application.update_main(project_name, approved=_required_approval(values))
        if method == "projects.mainChanges":
            return self.application.main_changes(project_name)
        if method == "projects.refreshMainRemote":
            return self.application.main_changes(project_name, refresh_remote=True)
        if method == "projects.mainChangeDiff":
            return self.application.main_change_diff(
                project_name,
                _required_string(values, "snapshotId"),
                _required_path_string(values, "path"),
                _required_string(values, "mode"),
            )
        if method in {"projects.commitMainChanges", "projects.commitAndPushMainChanges"}:
            selections = _main_change_selections(values)
            arguments = (
                project_name,
                _required_string(values, "snapshotId"),
                selections,
                _required_string(values, "message"),
            )
            if method == "projects.commitMainChanges":
                return self.application.commit_main_changes(*arguments, approved=_required_approval(values))
            return self.application.commit_and_push_main_changes(*arguments, approved=_required_approval(values))
        if method == "projects.pushMainCommits":
            return self.application.push_main_commits(
                project_name, _required_string(values, "snapshotId"), approved=_required_approval(values)
            )
        if method == "providers.planning":
            return self.application.planning_provider_choices(project_name)
        if method == "providers.execution":
            return self.application.execution_provider_choices(project_name, _string_list(values, "capabilities"))
        if method == "providers.status":
            return self.application.provider_statuses(project_name)
        if method == "planning.refreshIndex":
            return self.application.refresh_planning_index(project_name, _required_string(values, "sourceRoot"))
        if method == "runs.list":
            scope = _optional_string(values, "scope")
            return self.application.runs(project_name, scope=scope) if scope else self.application.runs(project_name)
        if method == "notifications.list":
            limit = values.get("limit", 100)
            if not isinstance(limit, int) or isinstance(limit, bool):
                raise RpcError("invalid_params", "notification limit must be an integer")
            return self.application.notifications(project_name, after_cursor=_optional_string(values, "afterCursor"), limit=limit)
        if method == "runs.preparePlanning":
            return self.application.prepare_planning(
                project_name,
                _optional_string(values, "specPath"),
                planning_agent_id=_optional_string(values, "planningAgentId"),
                planning_model=_optional_string(values, "planningModel"),
                planning_reasoning_effort=_optional_string(values, "planningReasoningEffort"),
                planning_mode=(_optional_string(values, "planningMode") or "auto"),
                planning_request=_optional_string(values, "planningRequest"),
                prepared_index_generated_at=_optional_string(values, "preparedIndexGeneratedAt"),
                repository_intent=_optional_string(values, "repositoryIntent"),
                effort_mode=(_optional_string(values, "effortMode") or "balanced"),
                planning_profile_source=_nullable_string(values, "planningProfileSource"),
            )
        if method == "runs.start":
            return self.application.start(
                project_name,
                _required_string(values, "specPath"),
                planning_agent_id=_optional_string(values, "planningAgentId"),
                planning_model=_optional_string(values, "planningModel"),
                planning_reasoning_effort=_optional_string(values, "planningReasoningEffort"),
                planning_mode=(_optional_string(values, "planningMode") or "auto"),
                planning_request=_optional_string(values, "planningRequest"),
                effort_mode=(_optional_string(values, "effortMode") or "balanced"),
                planning_profile_source=_nullable_string(values, "planningProfileSource"),
            )
        run_id = _required_string(values, "runId")
        if method == "runs.resultArtifact":
            return self.application.result_artifact(project_name, run_id)
        if method == "runs.registerResult":
            return self.application.register_result(project_name, run_id, kind=_required_string(values, "kind"),
                                                    relative_path=_required_string(values, "relativePath"),
                                                    expected_commit=_required_string(values, "expectedCommit"))
        if method == "runs.launchResult":
            return self.application.launch_result(project_name, run_id, expected_digest=_required_string(values, "expectedDigest"),
                                                  device_id=_optional_string(values, "deviceId"))
        if method == "runs.requestChatControl":
            expected = values.get("expected")
            if not isinstance(expected, dict):
                raise RpcError("invalid_params", "expected must be an object")
            profile = values.get("profile", {})
            if not isinstance(profile, dict) or any(key not in {"planningAgentId", "planningModel", "planningReasoningEffort"}
                                                   or not isinstance(value, str) for key, value in profile.items()):
                raise RpcError("invalid_params", "profile must contain Planning profile strings")
            return self.application.request_chat_control(project_name, run_id, request_id=_required_string(values, "requestId"),
                                                         intent=_required_string(values, "intent"), message=_required_string(values, "message"),
                                                         expected=expected, session_id=_optional_string(values, "sessionId"), profile=profile)
        if method == "runs.decideProjectChat":
            return self.application.decide_project_chat(project_name, run_id, _required_string(values, "requestId"))
        if method == "runs.performProjectChat":
            return self.application.perform_project_chat(project_name, run_id, _required_string(values, "requestId"),
                                                        _required_string(values, "stepId"))
        if method == "runs.advanceChatControl":
            return self.application.advance_chat_control(project_name, run_id, _required_string(values, "requestId"),
                                                         suspend=_boolean(values, "suspend", default=False))
        if method == "runs.cancelChatControl":
            return self.application.cancel_chat_control(project_name, run_id, _required_string(values, "requestId"))
        if method == "runs.beginPlanningRequest":
            return self.application.begin_planning_request(project_name, run_id, request_id=_required_string(values, "requestId"),
                                                           kind=_required_string(values, "kind"), message=_optional_string(values, "message"))
        if method == "runs.finishPlanningRequest":
            return self.application.finish_planning_request(project_name, run_id, request_id=_required_string(values, "requestId"),
                                                            phase=_required_string(values, "phase"), error=_optional_string(values, "error"))
        if method == "planning.previewBootstrap":
            return self.application.preview_bootstrap(project_name, run_id)
        if method == "planning.generateFeaturePlan":
            return self.application.generate_feature_plan(project_name, run_id)
        if method == "runs.archivePlan":
            return self.application.archive_plan(project_name, run_id)
        if method == "runs.archive":
            return self.application.archive_run(
                project_name,
                run_id,
                expected_revision=_required_string(values, "expectedRevision"),
                fingerprint=_required_string(values, "fingerprint"),
                request_id=_required_string(values, "requestId"),
                approved=_required_approval(values),
            )
        if method == "runs.retryArchiveCleanup":
            return self.application.retry_archive_cleanup(
                project_name,
                run_id,
                fingerprint=_required_string(values, "fingerprint"),
                request_id=_required_string(values, "requestId"),
                approved=_required_approval(values),
            )
        if method == "runs.runPlanning":
            return self.application.run_planning(project_name, run_id)
        if method == "runs.get":
            return self.application.status(project_name, run_id, **({"include_user_checks": True} if values.get("includeUserChecks") is True else {}))
        if method == "runs.usage":
            return self.application.usage(
                project_name, run_id, execution_request_id=_optional_string(values, "executionRequestId"),
                cursor=_optional_string(values, "cursor"), limit=_required_integer(values, "limit") if "limit" in values else 50,
            )
        if method == "runs.getPlanningPreview":
            return self.application.planning_apply_preview(project_name, run_id)
        if method == "runs.planningPreviewStatus":
            return self.application.planning_preview_status(project_name, run_id)
        if method == "runs.previewEffortMode":
            return self.application.preview_effort_mode(
                project_name, run_id, _required_string(values, "mode"), _required_integer(values, "expectedRevision")
            )
        if method == "runs.setEffortMode":
            return self.application.set_effort_mode(
                project_name, run_id, _required_string(values, "mode"), _required_string(values, "target"),
                _required_integer(values, "expectedPolicyRevision"), _required_string(values, "requestId"),
            )
        if method == "runs.cancelEffortReservation":
            return self.application.cancel_effort_reservation(
                project_name, run_id, _required_integer(values, "expectedPolicyRevision"), _required_string(values, "requestId"),
            )
        if method == "runs.applyEffortModeToPlan":
            return self.application.apply_effort_mode_to_plan(
                project_name, run_id, _required_string(values, "mode"), _required_integer(values, "expectedPolicyRevision"),
                _required_integer(values, "expectedPlanRevision"), _string_map(values, "reviewerAgentIds"),
            )
        if method == "tasks.retryContext":
            return self.application.task_retry_context(project_name, run_id, _required_string(values, "taskId"))
        if method == "tasks.repairFromChat":
            return self.application.repair_task_from_chat(
                project_name, run_id, _required_string(values, "taskId"), request_id=_required_string(values, "requestId"),
                message=_required_string(values, "message"), fingerprint=_required_string(values, "fingerprint"),
                conversation_revision=_required_integer(values, "conversationRevision"),
                **({"recovery_fingerprint": _optional_string(values, "recoveryFingerprint")} if "recoveryFingerprint" in values else {}),
                **({"parent_request_id": _required_string(values, "parentRequestId")} if "parentRequestId" in values else {}),
            )
        if method == "tasks.saveRetryInstruction":
            return self.application.save_task_retry_instruction(
                project_name, run_id, _required_string(values, "taskId"), request_id=_required_string(values, "requestId"),
                text=_required_string(values, "text"), fingerprint=_required_string(values, "fingerprint"),
            )
        if method == "runs.resultRevisions":
            return self.application.result_revisions(project_name, run_id)
        if method == "runs.proposeResultRevision":
            return self.application.propose_result_revision(
                project_name, run_id, proposal_id=_required_string(values, "proposalId"),
                text=_optional_string(values, "text"), focus_task_id=_optional_string(values, "focusTaskId"),
            )
        if method == "runs.createResultRevision":
            return self.application.create_result_revision(
                project_name, run_id, request_id=_required_string(values, "requestId"),
                text=_optional_string(values, "text"), task_ids=_string_list(values, "taskIds"),
                paths=_string_list(values, "paths"), proposal_id=_optional_string(values, "proposalId"),
            )
        if method == "runs.integrationConflict":
            return self.application.integration_conflict(
                project_name,
                run_id,
                _optional_string(values, "conflictId"),
                _optional_string(values, "filePath"),
                _optional_string(values, "recoveryTaskId"),
            )
        if method == "runs.interruptPlanning":
            return self.application.interrupt_planning(project_name, run_id, approved=_required_approval(values))
        if method == "runs.sendPlanningMessage":
            return self.application.send_planning_message(
                project_name,
                run_id,
                _required_string(values, "message"),
                planning_agent_id=_nullable_string(values, "planningAgentId"),
                planning_model=_nullable_string(values, "planningModel"),
                planning_reasoning_effort=_nullable_string(values, "planningReasoningEffort"),
            )
        if method == "runs.applyPlanningConversation":
            technology_options: dict[str, object] = {}
            if "expectedTechStackRevision" in values or "answer" in values or "retryFailed" in values:
                technology_options = {
                    "answer_message": _optional_string(values, "answer"),
                    "expected_tech_stack_revision": _required_integer(values, "expectedTechStackRevision"),
                    "retry_failed": _boolean(values, "retryFailed", default=False),
                }
            if any(name in values for name in ("planningAgentId", "planningModel", "planningReasoningEffort")):
                technology_options.update({
                    "planning_agent_id": _nullable_string(values, "planningAgentId"),
                    "planning_model": _nullable_string(values, "planningModel"),
                    "planning_reasoning_effort": _nullable_string(values, "planningReasoningEffort"),
                })
            return self.application.apply_planning_conversation(
                project_name,
                run_id,
                request_id=_required_string(values, "requestId"),
                expected_revision=_required_integer(values, "expectedRevision"),
                conversation_revision=_required_integer(values, "conversationRevision"),
                **technology_options,
            )
        if method == "runs.requestDirectionChange":
            return self.application.request_direction_change(
                project_name, run_id, request_id=_required_string(values, "requestId"), text=_required_string(values, "text")
            )
        if method == "runs.previewPlanningApply":
            return self.application.preview_planning_apply(
                project_name, run_id, request_id=_required_string(values, "requestId")
            )
        if method == "runs.applyPlanningPreview":
            return self.application.apply_planning_preview(
                project_name, run_id, preview_id=_required_string(values, "previewId"),
                fingerprint=_required_string(values, "fingerprint"),
                candidate_digest=_required_string(values, "candidateDigest"),
            )
        if method == "runs.confirmTechStack":
            return self.application.confirm_tech_stack(
                project_name,
                run_id,
                option_id=_required_string(values, "optionId"),
                expected_revision=_required_integer(values, "expectedRevision"),
            )
        if method == "runs.configureBootstrapInstructions":
            return self.application.configure_bootstrap_agent_instructions(
                project_name,
                run_id,
                create=_boolean(values, "create", default=True),
                expected_revision=_required_integer(values, "expectedRevision"),
                expected_digest=_required_string(values, "expectedDigest"),
            )
        if method == "tasks.log":
            task_id = _required_string(values, "taskId")
            return self.application.task_log(project_name, run_id, task_id)
        if method == "runs.execute":
            return self.application.execute(
                project_name,
                run_id,
                agent_overrides=_string_map(values, "agentOverrides"),
                model_overrides=_string_map(values, "modelOverrides"),
                reasoning_effort_overrides=_string_map(values, "reasoningEffortOverrides"),
            )
        if method == "runs.resume":
            return self.application.resume(project_name, run_id)
        if method == "runs.requestStop":
            return self.application.request_stop(
                project_name,
                run_id,
                request_id=_required_string(values, "requestId"),
                execution_id=_required_string(values, "executionId"),
                scope=_required_string(values, "scope"),
                task_id=_optional_string(values, "taskId"),
                attempt_id=_optional_string(values, "attemptId"),
                invocation_id=_optional_string(values, "invocationId"),
                **({"chat_message": _required_string(values, "chatMessage")} if "chatMessage" in values else {}),
            )
        if method == "runs.recoveryPlan":
            request_id = _optional_string(values, "requestId")
            return self.application.recovery_plan(project_name, run_id, **({"request_id": request_id} if request_id else {}))
        if method == "runs.applyRecovery":
            selected = values.get("sourceIds")
            if not isinstance(selected, list) or not all(isinstance(item, str) for item in selected):
                raise RpcError("invalid_params", "sourceIds must be an array of strings")
            recovery_options: dict[str, object] = {"approved": _required_approval(values)}
            request_id = _optional_string(values, "requestId")
            resume_request_id = _optional_string(values, "resumeRequestId")
            if request_id:
                recovery_options["request_id"] = request_id
            if resume_request_id:
                recovery_options["resume_request_id"] = resume_request_id
            return self.application.apply_recovery(
                project_name,
                run_id,
                _required_string(values, "fingerprint"),
                selected,
                **recovery_options,
            )
        if method == "operations.get":
            return self.application.recovery_operation(project_name, run_id, _required_string(values, "requestId"))
        if method == "operations.latest":
            return self.application.latest_recovery_operation(project_name, run_id, _required_string(values, "kind"))
        if method == "runs.prepareConflictResolution":
            return self.application.prepare_conflict_resolution(
                project_name,
                run_id,
                conflict_id=_required_string(values, "conflictId"),
                fingerprint=_required_string(values, "fingerprint"),
                request_id=_required_string(values, "requestId"),
                agent_id=_optional_string(values, "agentId"),
                model=_optional_string(values, "model"),
                reasoning_effort=_optional_string(values, "reasoningEffort"),
            )
        if method == "runs.applyConflictResolution":
            revision = values.get("candidateRevision")
            if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
                raise RpcError("invalid_params", "candidateRevision must be a positive integer")
            return self.application.apply_conflict_resolution(
                project_name,
                run_id,
                conflict_id=_required_string(values, "conflictId"),
                candidate_id=_required_string(values, "candidateId"),
                candidate_revision=revision,
                fingerprint=_required_string(values, "fingerprint"),
                request_id=_required_string(values, "requestId"),
                approved=_required_approval(values),
            )
        if method == "tasks.execute":
            task_id = _required_string(values, "taskId")
            return self.application.execute_task(
                project_name,
                run_id,
                task_id,
                agent_overrides=_string_map(values, "agentOverrides"),
                model_overrides=_string_map(values, "modelOverrides"),
                reasoning_effort_overrides=_string_map(values, "reasoningEffortOverrides"),
            )
        if method == "tasks.retry":
            task_id = _required_string(values, "taskId")
            return self.application.retry_task(project_name, run_id, task_id)
        if method == "tasks.updateExecutionProfile":
            expected = _string_map(values, "expectedProfile")
            if expected is None or set(expected) != {"agent_id", "model", "reasoning_effort", "last_attempt_id", "status"}:
                raise RpcError("invalid_params", "expectedProfile must contain the displayed execution profile, attempt and status")
            return self.application.update_task_execution_profile(
                project_name, run_id, _required_string(values, "taskId"), agent_id=_required_string(values, "agentId"),
                model=_optional_string(values, "model"), reasoning_effort=_optional_string(values, "reasoningEffort"), expected_profile=expected,
            )
        if method == "runs.verify":
            return self.application.verify(project_name, run_id)
        if method == "runs.verifyAndRepair":
            return self.application.verify_and_repair(
                project_name, run_id, _required_string(values, "requestId"),
                **({"chat_message": _required_string(values, "chatMessage")} if "chatMessage" in values else {}),
                **({"parent_request_id": _required_string(values, "parentRequestId")} if "parentRequestId" in values else {}),
            )
        if method == "tasks.complete":
            return self.application.complete_task(project_name, run_id, _required_string(values, "taskId"))
        if method == "tasks.completeManualVerification":
            return self.application.complete_manual_verification(
                project_name, run_id, _required_string(values, "taskId"), note=_required_string(values, "note"),
                expected_commit=_required_string(values, "expectedCommit"), expected_revision=_required_integer(values, "expectedRevision"),
            )
        if method == "runs.recordUserCheck":
            return self.application.record_user_check(
                project_name, run_id, _required_string(values, "checkId"), outcome=_required_string(values, "outcome"),
                note=_required_string(values, "note"), expected_commit=_required_string(values, "expectedCommit"),
                expected_revision=_required_integer(values, "expectedRevision"),
            )
        if method == "tasks.handoffToAi":
            return self.application.handoff_manual_task_to_ai(
                project_name, run_id, _required_string(values, "taskId"),
                expected_commit=_required_string(values, "expectedCommit"), expected_revision=_required_integer(values, "expectedRevision"),
            )
        if method in {"tasks.deferManual", "tasks.resumeManual"}:
            return self.application.set_manual_task_deferred(
                project_name, run_id, _required_string(values, "taskId"), deferred=method == "tasks.deferManual"
            )
        if method == "runs.excludeTasks":
            return self.application.exclude_tasks(
                project_name, run_id, _string_list(values, "taskIds", required=True), approved=_required_approval(values)
            )
        if method == "runs.updatePlan":
            return self.application.update_plan(
                project_name, run_id, _object_list(values, "tasks", required=True),
                **({"expected_revision": _required_integer(values, "expectedRevision")} if "expectedRevision" in values else {}),
            )
        if method == "runs.confirmPlan":
            if "expectedRevision" in values or "bootstrapDigest" in values:
                return self.application.confirm_plan(
                    project_name, run_id, expected_revision=_required_integer(values, "expectedRevision"),
                    expected_bootstrap_digest=_optional_string(values, "bootstrapDigest"),
                )
            return self.application.confirm_plan(project_name, run_id)
        if method in {"runs.merge", "runs.push", "runs.retryMainPush", "runs.recoverMainApply", "runs.deploy"}:
            approved = _required_approval(values)
            recovery_target = {
                "expected_repo": _required_string(values, "repoPath"),
                "expected_commit": _required_string(values, "targetCommit"),
            } if method == "runs.recoverMainApply" else {}
            return self.application.approved_run_action(
                project_name,
                run_id,
                method.removeprefix("runs."),
                approved=approved,
                request_id=_optional_string(values, "requestId"),
                **recovery_target,
            )
        if method == "runs.delete":
            return self.application.delete_run(project_name, run_id, approved=_required_approval(values))
        if method == "workspaces.list":
            return self.application.workspace_statuses(project_name, run_id)
        if method == "workspaces.cleanup":
            return self.application.cleanup_workspace(project_name, run_id, _required_string(values, "taskId"), approved=_required_approval(values))
        if method == "locks.get":
            return self.application.run_lock_status(project_name, run_id)
        if method == "locks.clear":
            return self.application.clear_run_lock(project_name, run_id, approved=_required_approval(values))
        raise RpcError("method_not_found", f"unsupported RPC method: {method}")


def _object_params(params: object) -> dict[str, object]:
    if params is None:
        return {}
    if not isinstance(params, dict):
        raise RpcError("invalid_params", "params must be an object")
    return params


def _required_string(params: dict[str, object], name: str) -> str:
    value = params.get(name)
    if not isinstance(value, str) or not value.strip():
        raise RpcError("invalid_params", f"{name} must be a non-empty string")
    return value.strip()


def _required_path_string(params: dict[str, object], name: str) -> str:
    value = params.get(name)
    if not isinstance(value, str) or not value:
        raise RpcError("invalid_params", f"{name} must be a non-empty string")
    return value


def _main_change_selections(params: dict[str, object]) -> list[tuple[str, str]]:
    raw = params.get("selections")
    if not isinstance(raw, list) or not raw:
        raise RpcError("invalid_params", "selections must be a non-empty array")
    selections: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise RpcError("invalid_params", "each Main change selection must be an object")
        path = item.get("path")
        mode = item.get("mode")
        if not isinstance(path, str) or not path or not isinstance(mode, str) or mode not in {"staged", "whole"}:
            raise RpcError("invalid_params", "Main change selection requires path and staged/whole mode")
        selections.append((path, mode))
    return selections


def _code_style_preference(params: dict[str, object]) -> ProjectCodeStylePreference:
    try:
        return ProjectCodeStylePreference.from_dict(params.get("preference"))
    except ValueError as exc:
        raise RpcError("invalid_params", str(exc)) from exc


def _required_integer(params: dict[str, object], name: str) -> int:
    value = params.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RpcError("invalid_params", f"{name} must be a non-negative integer")
    return value


def _optional_string(params: dict[str, object], name: str) -> str:
    value = params.get(name, "")
    if not isinstance(value, str):
        raise RpcError("invalid_params", f"{name} must be a string")
    return value.strip()


def _nullable_string(params: dict[str, object], name: str) -> str | None:
    if name not in params:
        return None
    return _optional_string(params, name)


def _string_list(params: dict[str, object], name: str, *, required: bool = False) -> list[str]:
    value = params.get(name, [])
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise RpcError("invalid_params", f"{name} must be an array of non-empty strings")
    result = [item.strip() for item in value]
    if required and not result:
        raise RpcError("invalid_params", f"{name} must not be empty")
    return result


def _boolean(params: dict[str, object], name: str, *, default: bool) -> bool:
    value = params.get(name, default)
    if not isinstance(value, bool):
        raise RpcError("invalid_params", f"{name} must be a boolean")
    return value


def _string_map(params: dict[str, object], name: str) -> dict[str, str] | None:
    if name not in params:
        return None
    value = params[name]
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and key.strip() and isinstance(item, str)
        for key, item in value.items()
    ):
        raise RpcError("invalid_params", f"{name} must be an object with string values")
    return {str(key).strip(): str(item).strip() for key, item in value.items()}


def _object_list(params: dict[str, object], name: str, *, required: bool = False) -> list[dict[str, object]]:
    value = params.get(name, [])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise RpcError("invalid_params", f"{name} must be an array of objects")
    if required and not value:
        raise RpcError("invalid_params", f"{name} must not be empty")
    return [dict(item) for item in value]


def _required_approval(params: dict[str, object]) -> bool:
    if params.get("approved") is not True:
        raise RpcError("approval_required", "this operation requires explicit native approval")
    return True


def _expanded_provider_choices(choices: list[object]) -> list[object]:
    expanded: list[dict[str, object]] = []
    for raw_choice in choices:
        provider_id = str(getattr(raw_choice, "provider_id"))
        configured_model = str(getattr(raw_choice, "model", ""))
        models = supported_models(provider_id, (configured_model,) if configured_model else ())
        if provider_id == "nvidia":
            models = tuple(dict.fromkeys((*models, *current_nvidia_model_keys())))
        # Do not offer automatic selection when it would restore an
        # excluded model.
        if not configured_model.strip() or configured_model.strip() in models:
            models = ("",) + models
        for model in dict.fromkeys(models):
            expanded.append(
                {
                    "provider_id": provider_id,
                    "agent_id": str(getattr(raw_choice, "agent_id")),
                    "model": model,
                    "configured_model": configured_model,
                    "reasoning_efforts": list(supported_reasoning_efforts(provider_id, model)),
                    "is_default": bool(getattr(raw_choice, "is_default", False)),
                    "max_tasks": int(getattr(raw_choice, "max_tasks", 1)),
                }
            )
    return expanded


def _run_state_view(state: RunState) -> dict[str, Any]:
    result = state.to_dict()
    if state.user_check_plan:
        result["planned_user_checks"] = Pipeline.planned_user_checks(state, include_notes=True)
        result["user_check_blocked_task_ids"] = sorted(state.user_check_blocked_task_ids())
    return result


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, RunState):
        return _json_value(_run_state_view(value))
    if hasattr(value, "to_dict"):
        return _json_value(value.to_dict())  # type: ignore[attr-defined]
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise TypeError(f"unsupported RPC result type: {type(value).__name__}")


def handle_request(service: RpcService, raw: object) -> dict[str, object]:
    request_id: object = None
    credential = raw.get("nvidia_api_key") if isinstance(raw, dict) else None
    secrets = [credential] if isinstance(credential, str) else []
    if isinstance(raw, dict) and raw.get("method") == "auth.codex.apiKey" and isinstance(raw.get("params"), dict):
        codex_key = raw["params"].get("apiKey")
        if isinstance(codex_key, str) and codex_key.strip():
            secrets.append(codex_key.strip())
    model_credentials = raw.get("nvidia_model_api_keys") if isinstance(raw, dict) else None
    if isinstance(model_credentials, dict):
        secrets.extend(key for key in model_credentials.values() if isinstance(key, str))

    def error_message(error: Exception) -> str:
        message = redact_nvidia_output(str(error), {})
        for key in sorted(set(secrets), key=len, reverse=True):
            message = redact_nvidia_output(message, {"NVIDIA_API_KEY": key})
        return message
    try:
        if not isinstance(raw, dict):
            raise RpcError("invalid_request", "request must be an object")
        request_id = raw.get("id")
        if not isinstance(request_id, (str, int)):
            raise RpcError("invalid_request", "id must be a string or integer")
        method = raw.get("method")
        if not isinstance(method, str) or not method.strip():
            raise RpcError("invalid_request", "method must be a non-empty string")
        with nvidia_credential_scope(raw.get("nvidia_api_key"), model_credentials):
            result = service.dispatch(method.strip(), raw.get("params"))
        return {"id": request_id, "result": _json_value(result)}
    except RpcError as exc:
        return {"id": request_id, "error": {"code": exc.code, "message": error_message(exc)}}
    # RPC boundary must preserve a valid response frame.
    except Exception as exc:
        return {"id": request_id, "error": {"code": "application_error", "message": error_message(exc)}}


def serve(service: RpcService, input_stream: TextIO, output_stream: TextIO) -> None:
    output_lock = threading.Lock()

    def write_response(response: dict[str, object]) -> None:
        frame = json.dumps(response, ensure_ascii=True) + "\n"
        with output_lock:
            output_stream.write(frame)
            output_stream.flush()

    def process(raw: object) -> None:
        write_response(handle_request(service, raw))

    with (
        ThreadPoolExecutor(max_workers=4, thread_name_prefix="desktop-status-rpc") as status_executor,
        ThreadPoolExecutor(max_workers=4, thread_name_prefix="desktop-control-rpc") as control_executor,
        ThreadPoolExecutor(max_workers=4, thread_name_prefix="desktop-work-rpc") as work_executor,
    ):
        for line in input_stream:
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                write_response({"id": None, "error": {"code": "parse_error", "message": str(exc)}})
            else:
                method = raw.get("method") if isinstance(raw, dict) else None
                if method in _LONG_RUNNING_RPC_METHODS:
                    executor = work_executor
                elif method in _STATUS_RPC_METHODS:
                    executor = status_executor
                else:
                    executor = control_executor
                executor.submit(process, raw)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Work Orchestrator Electron backend")
    parser.add_argument("--registry", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_standard_streams()
    args = build_parser().parse_args(argv)
    registry = ProjectRegistry(args.registry or None)
    application = DesktopApplication(registry)
    service = RpcService(application)
    try:
        serve(service, sys.stdin, sys.stdout)
    finally:
        application.close()
    return 0


def _configure_standard_streams() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="strict")


if __name__ == "__main__":
    raise SystemExit(main())
