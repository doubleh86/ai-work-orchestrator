from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ..account_usage import AccountUsage, read_claude_quota
from ..codex_model_preferences import CODEX_MODEL_PRESETS, CodexModelPreferenceError, enabled_codex_models, save_codex_models
from ..codex_sdk import CodexSdkManager, read_codex_quota
from ..code_style import ProjectCodeStylePreference
from ..config import create_default_config, load_config
from ..git import (
    create_initial_commit,
    initialize_git_repository,
    inspect_git_readiness,
    preview_git_initialization,
    preview_initial_commit,
)
from ..models import RunState, Stage, UserCheck
from ..pipeline import Pipeline, PipelineError
from ..registry import ProjectRegistry, RegisteredProject, RegistryError
from ..worker_mcp import WorkerMcpServer
from .errors import ApplicationError
from .runtime import create_pipeline
from .views import expanded_provider_choices, planning_index_view, run_state_view
from .planning_indexes import PreparedPlanningIndexes
from .project_settings import ProjectSettingsService, registered_project_config
from .summaries import ProjectSummaryQueries


class OrchestratorApplication:
    def __init__(self, registry: ProjectRegistry, *, codex_sdk: CodexSdkManager | None = None):
        self.registry = registry
        self.codex_sdk = codex_sdk or CodexSdkManager()
        self._planning_indexes = PreparedPlanningIndexes()
        self._summary_queries = ProjectSummaryQueries(self._summary_project_names)
        self._settings = ProjectSettingsService(
            read_project=lambda name: self.registry.get(name),
            read_servers=self._project_worker_servers,
            update_servers=lambda name, servers, *, expected_revision: self.registry.update_worker_mcp_servers(
                name, servers, expected_revision=expected_revision,
            ),
            update_style=lambda name, preference, *, expected_revision: self.registry.update_code_style_preference(
                name, preference, expected_revision=expected_revision,
            ),
        )

    def close(self) -> None:
        self._summary_queries.close()
        self.codex_sdk.close()

    def projects(self) -> list[object]:
        return self.registry.list()

    def active_groups(self) -> dict[str, object]:
        return self._summary_queries.snapshot("active_groups", self._active_groups_for_project, "last_activity_at")

    def attention_items(self) -> dict[str, object]:
        return self._summary_queries.snapshot("attention_items", self._attention_items_for_project, "updated_at")

    def user_check_items(self, project_name: str = "") -> dict[str, object]:
        return self._summary_queries.snapshot("user_checks", self._user_checks_for_project, "updated_at", project_name)

    def _summary_project_names(self, project_name: str) -> list[str]:
        projects = [self.registry.get(project_name)] if project_name else self.registry.list()
        return [project.name for project in projects]

    def _active_groups_for_project(self, project_name: str) -> list[dict[str, object]]:
        return self._pipeline(project_name).active_group_summaries()

    def _attention_items_for_project(self, project_name: str) -> list[dict[str, object]]:
        return self._pipeline(project_name).attention_item_summaries()

    def _user_checks_for_project(self, project_name: str) -> list[dict[str, object]]:
        return self._pipeline(project_name).user_check_summaries()

    def codex_auth_status(self) -> object:
        return self.codex_sdk.login_status()

    def codex_model_settings(self) -> dict[str, object]:
        return {"models": list(CODEX_MODEL_PRESETS), "enabled_models": list(enabled_codex_models())}

    def update_codex_model_settings(self, models: list[str], *, expected_models: list[str]) -> dict[str, object]:
        try:
            enabled = save_codex_models(models, expected_models=expected_models)
        except CodexModelPreferenceError as exc:
            raise ApplicationError("invalid_params", str(exc)) from exc
        return {"models": list(CODEX_MODEL_PRESETS), "enabled_models": list(enabled)}

    def claude_auth_status(self) -> object:
        return Pipeline.claude_connection_status()

    def set_claude_executable(self, path: str) -> object:
        from ..provider_executable import set_claude_executable

        set_claude_executable(path)
        return Pipeline.claude_connection_status()

    def clear_claude_executable(self) -> object:
        from ..provider_executable import clear_claude_executable

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
            raise ApplicationError("approval_required", "Git initialization requires explicit approval")
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
            raise ApplicationError("approval_required", "initial commit requires explicit approval")
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
            raise ApplicationError("approval_required", "project removal requires explicit approval")
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

    def worker_mcp_connections(self, project_name: str) -> dict[str, object]:
        return self._settings.worker_mcp_connections(project_name)

    def update_worker_mcp_connections(
        self, project_name: str, configuration: object, *, expected_revision: int, approved: bool, append: bool = False,
    ) -> dict[str, object]:
        return self._settings.update_worker_mcp_connections(
            project_name, configuration, expected_revision=expected_revision, approved=approved, append=append,
        )

    def check_worker_mcp_connection(self, project_name: str, server_id: str, *, expected_revision: int) -> dict[str, object]:
        return self._settings.check_worker_mcp_connection(project_name, server_id, expected_revision=expected_revision)

    def workspace_location(self, project_name: str) -> object:
        return self._settings.workspace_location(project_name)

    def project_capabilities(self, project_name: str) -> object:
        return self._settings.project_capabilities(project_name)

    def code_style_profile(self, project_name: str) -> object:
        return self._settings.code_style_profile(project_name)

    def preview_code_style_preference(self, project_name: str, preference: ProjectCodeStylePreference) -> object:
        return self._settings.preview_code_style_preference(project_name, preference)

    def update_code_style_preference(
        self,
        project_name: str,
        preference: ProjectCodeStylePreference,
        expected_revision: int,
        *,
        approved: bool,
    ) -> object:
        return self._settings.update_code_style_preference(project_name, preference, expected_revision, approved=approved)

    def inspect_repository_maturity(self, project_name: str) -> object:
        return self._settings.inspect_repository_maturity(project_name)

    def check_dotnet(self, project_name: str, run_id: str, task_id: str) -> object:
        return self._pipeline(project_name).check_dotnet(run_id=run_id, task_id=task_id)

    def status(self, project_name: str, run_id: str, *, include_user_checks: bool = False) -> object:
        pipeline = self._pipeline(project_name)
        state, execution_control, integration_control = pipeline.status_with_controls(run_id)
        result = run_state_view(pipeline.execution_profile_view(state))
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
        return expanded_provider_choices(choices)

    def execution_provider_choices(self, project_name: str, capabilities: list[str]) -> list[object]:
        choices = self._pipeline(project_name).execution_provider_choices(capabilities)
        return expanded_provider_choices(choices)

    def provider_statuses(self, project_name: str) -> list[object]:
        return self._pipeline(project_name).provider_statuses()

    def refresh_planning_index(self, project_name: str, source_root: str | Path) -> object:
        index = self._pipeline(project_name).refresh_planning_index(source_root)
        self._planning_indexes.remember(project_name, index)
        return planning_index_view(index)

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
        accepted_index = self._planning_indexes.consume(project_name, spec_path, prepared_index_generated_at)
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
            raise ApplicationError("provider_excluded", "선택한 Planning 모델은 현재 신규 선택에서 제외되어 있습니다. 다른 모델을 선택해 주세요.")
        if not choices:
            raise ApplicationError("provider_unavailable", "사용 가능한 Planning 모델이 없습니다. Provider 연결 상태를 확인해 주세요.")
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
                raise ApplicationError(
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
            raise ApplicationError("approval_required", "task exclusion requires explicit approval")
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
        raise ApplicationError("invalid_params", f"unsupported run action: {action}")

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
            raise ApplicationError("provider_excluded", "사용 가능한 충돌 해결 모델이 없습니다. 다른 모델을 선택해 주세요.")
        return pipeline.prepare_conflict_resolution(run_id, **{**values, "agent_id": selected.agent_id})

    def apply_conflict_resolution(self, project_name: str, run_id: str, *, approved: bool, **values: object) -> object:
        return self._pipeline(project_name).apply_conflict_resolution(run_id, approved=approved, **values)

    def run_lock_status(self, project_name: str, run_id: str) -> object:
        return self._pipeline(project_name).run_lock_status(run_id)

    def clear_run_lock(self, project_name: str, run_id: str, *, approved: bool) -> object:
        return self._pipeline(project_name).clear_run_lock(run_id, approved=approved)

    def _project_worker_servers(self, project_name: str, project: RegisteredProject) -> tuple[WorkerMcpServer, ...]:
        return self._pipeline(project_name, expected_project=project).config.worker_mcp_servers

    def _pipeline(self, project_name: str, *, expected_project: RegisteredProject | None = None) -> Pipeline:
        project = self.registry.get(project_name)
        if expected_project is not None and project != expected_project:
            raise RegistryError("프로젝트 등록 정보가 변경됐습니다. 계획 컨텍스트를 다시 조회해 주세요.")
        config = registered_project_config(project)
        if project.worker_mcp_servers is not None:
            config = replace(config, worker_mcp_servers=project.worker_mcp_servers)
        return create_pipeline(
            config,
            codex_sdk=self.codex_sdk,
            dotnet_executable=project.dotnet_executable,
            code_style_preference=project.code_style_preference,
            code_style_preference_revision=project.code_style_preference_revision,
        )
