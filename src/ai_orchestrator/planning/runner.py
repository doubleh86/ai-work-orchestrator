"""Planning attempts with bounded runtime dependencies.

Callers own locks, SDK lifetime and final plan application.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from ..code_style import render_code_style_snapshot
from ..codex_sdk import CodexSdkManager
from ..config import AgentConfig, PlanningConfig, RoutingConfig
from ..document_index import DocumentIndexError, PlanningSourceIndex, render_planning_request_context
from ..errors import PipelineError, ProviderCapacityError, ProviderInputTooLarge, ProviderRequestLimitError, ProviderTimeoutError
from ..git import GitError
from ..models import PlanningMode, RunState, WorkTask, utc_now
from ..persistence.errors import PlanningCacheError
from ..planner import build_plan, discover_repository_instruction_documents
from .contracts import Plan, PlanningError
from .conversation import planning_conversation_id, planning_materialization_prompt, task_plan_draft
from .prompts import execution_profile_guidance, planning_prompt, render_planning_attempt_prompt


class PlanningAgentInvocation(Protocol):
    def __call__(
        self, state: RunState, agent: AgentConfig, prompt: str, prompt_path: Path, log_path: Path, *,
        timeout_seconds: float, claude_session_id: str, resume_claude_session: bool,
        persist_state: Callable[[RunState], None], sdk_conversation_id: str,
    ) -> str: ...


class PlanningOutputValidation(Protocol):
    def __call__(
        self, output: str, *, source_root: Path | None, source_index: PlanningSourceIndex | None,
        required_instruction_paths: set[str], execution_agents: tuple[AgentConfig, ...], planning_mode: PlanningMode,
        require_directory_task_draft: bool, previous_tasks: list[WorkTask] | None, sequential: bool,
        greenfield_bootstrap: bool, greenfield_initial: bool, greenfield_feature: bool,
    ) -> Plan: ...


class PlanningRepositoryChanges(Protocol):
    def __call__(
        self, *, ignored_untracked_roots: tuple[Path, ...], non_interactive: bool, timeout_seconds: float,
    ) -> bool: ...


@dataclass(frozen=True, slots=True)
class PlanningPersistence:
    root: Path
    run_directory: Callable[[str], Path]
    save_state: Callable[[RunState], None]
    read_preview_progress: Callable[[str], dict[str, object] | None]
    save_preview_progress: Callable[[str, dict[str, object]], None]
    read_result: Callable[[str], str | None]
    save_result: Callable[[str, str], None]


@dataclass(frozen=True, slots=True)
class PlanningRunner:
    repo: Path
    planning: PlanningConfig
    routing: RoutingConfig
    persistence: PlanningPersistence
    available_agent: Callable[[str, str], AgentConfig]
    sdk_profile: Callable[[AgentConfig, str], tuple[str, str] | None]
    execution_agents: Callable[[], tuple[AgentConfig, ...]]
    sequential: Callable[[RunState], bool]
    has_uncommitted_changes: PlanningRepositoryChanges
    validate_plan: PlanningOutputValidation
    cache_key: Callable[[RunState, AgentConfig, str], str]
    invoke_agent: PlanningAgentInvocation
    codex_sdk: CodexSdkManager | None = None

    def run(
        self, state: RunState, document: str, *, clarification_context: str = "", source_index: PlanningSourceIndex | None = None,
        preview_id: str = "",
    ) -> Plan:
        def persist_preview_progress(current: RunState) -> None:
            progress = self.persistence.read_preview_progress(current.id) or {}
            if progress.get("request_id") == preview_id:
                activity = next((event.at for event in reversed(current.events) if event.kind == "planning_progress"), "")
                progress.update(updated_at=utc_now(), last_activity_at=activity)
                self.persistence.save_preview_progress(current.id, progress)

        persist_state: Callable[[RunState], None] = persist_preview_progress if preview_id else self.persistence.save_state
        artifact_root = (
            self.persistence.run_directory(state.id) / "planning-previews" / preview_id
            if preview_id else self.persistence.run_directory(state.id)
        )
        planning_timeout = self.planning.timeout_seconds
        planning_deadline = time.monotonic() + planning_timeout

        def remaining_planning_timeout() -> float:
            remaining = planning_deadline - time.monotonic()
            if remaining <= 0:
                raise ProviderTimeoutError(f"planning timed out after {planning_timeout} seconds")
            return remaining

        spec_path = Path(state.spec_path).expanduser().resolve() if state.spec_path.strip() else None
        source_root = spec_path if spec_path is not None and spec_path.is_dir() else None
        planning_agent_id = state.planning_agent_id or self.planning.agent_id
        if not planning_agent_id:
            if source_root is not None:
                raise PlanningError("planning document directory requires a configured planning agent")
            return build_plan(
                state.spec_snapshot_path, self.execution_agents(), self.routing, sequential=self.sequential(state),
            )

        try:
            agent = self.available_agent(planning_agent_id, "review")
        except PipelineError as exc:
            raise PlanningError(str(exc)) from exc
        planning_sdk_options = self.sdk_profile(agent, "planning")
        planning_uses_sdk = self.codex_sdk is not None and planning_sdk_options is not None
        state.planning_agent_id = agent.id
        state.planning_provider_id = agent.provider_id
        conversation_id = f"planning-preview:{state.id}:{preview_id}" if preview_id else planning_conversation_id(state)
        sdk_thread_continuation = False
        claude_session_id = ""
        claude_session_continuation = False
        if planning_uses_sdk and planning_sdk_options is not None:
            sandbox_mode, approval_mode = planning_sdk_options
            sdk_thread_continuation = bool(clarification_context.strip()) and (
                self.codex_sdk.has_conversation(
                    conversation_id, cwd=self.repo, model=state.planning_model or agent.model, sandbox_mode=sandbox_mode, approval_mode=approval_mode
                )
                is True
            )
            if clarification_context.strip():
                if not sdk_thread_continuation:
                    self.codex_sdk.close_conversation(conversation_id)
                state.add_event(
                    "planning",
                    (
                        "planning conversation continued on existing Codex SDK thread"
                        if sdk_thread_continuation
                        else "planning conversation restored on new Codex SDK thread"
                    ),
                )
        elif clarification_context.strip() and self.codex_sdk is not None:
            self.codex_sdk.close_conversation(conversation_id)
        if agent.provider_id == "claude":
            claude_session_id = "" if preview_id else state.planning_claude_session_id
            claude_session_continuation = bool(claude_session_id)
            if not claude_session_id:
                claude_session_id = str(uuid.uuid4())
            if clarification_context.strip():
                state.add_event(
                    "planning",
                    (
                        "planning conversation continued on existing Claude CLI session"
                        if claude_session_continuation
                        else "planning conversation restored on new Claude CLI session"
                    ),
                )
        repository_instruction_documents = discover_repository_instruction_documents(self.repo)
        required_instruction_paths = {document.relative_path for document in repository_instruction_documents}
        execution_agents = self.execution_agents()
        cache_enabled = self.planning.reuse_results and not preview_id and not sdk_thread_continuation and not claude_session_continuation
        if cache_enabled:
            try:
                repository_changed = self.has_uncommitted_changes(
                    ignored_untracked_roots=(self.persistence.root,), non_interactive=True, timeout_seconds=remaining_planning_timeout()
                )
            except ProviderTimeoutError as exc:
                raise PlanningError(str(exc)) from exc
            except GitError as exc:
                cache_enabled = False
                state.add_event("planning", f"planning result cache bypassed: {exc}")
            else:
                if repository_changed:
                    cache_enabled = False
                    state.add_event("planning", "planning result cache bypassed: repository has uncommitted changes")

        if (
            source_index is not None
            and state.planning_mode == PlanningMode.DIRECTED
            and not clarification_context.strip()
        ):
            try:
                document += "\n" + render_planning_request_context(source_index, state.planning_request)
            except DocumentIndexError as exc:
                raise PlanningError(str(exc)) from exc

        last_error = ""
        cache_key = ""
        cache_checked = False
        provider_retry_has_context = False
        greenfield_feature = state.repository_intent == "new_project" and state.greenfield_phase in {
            "feature_planning",
            "feature_planning_ready",
            "feature_plan_ready",
        }
        greenfield_bootstrap = state.repository_intent == "new_project" and not greenfield_feature
        greenfield_initial = greenfield_bootstrap and not bool(clarification_context.strip())
        require_directory_task_draft = (
            state.planning_mode == PlanningMode.AUTO
            and not bool(clarification_context.strip())
            and not greenfield_bootstrap
        )
        for attempt in range(1, self.planning.max_attempts + 1):
            base_prompt = planning_prompt(
                document,
                clarification_context,
                source_root=source_root.as_posix() if source_root else "",
                repository_root=self.repo.resolve().as_posix(),
                repository_instruction_documents=repository_instruction_documents,
                execution_agents=execution_agents,
                sequential=self.sequential(state),
                balance_providers=self.routing.balance_providers,
                planning_mode=state.planning_mode,
                planning_request=state.planning_request,
                greenfield_bootstrap=greenfield_bootstrap,
                greenfield_feature=greenfield_feature,
                code_style_context=render_code_style_snapshot(state.code_style_snapshot),
            )
            attempt_continuation = sdk_thread_continuation or claude_session_continuation
            attempt_materialization = planning_materialization_prompt(state) if not last_error and attempt_continuation else ""
            attempt_follow_up = (
                json.dumps([{"status": task.status.value, **task_plan_draft(task)} for task in state.tasks], ensure_ascii=False)
                if state.planning_follow_up_requests else None
            )
            attempt_catalog = (
                execution_profile_guidance(
                    execution_agents, sequential=self.sequential(state), balance_providers=self.routing.balance_providers,
                )
                if (last_error and provider_retry_has_context) or (not last_error and attempt_continuation) else ""
            )
            prompt = render_planning_attempt_prompt(
                base_prompt, last_error=last_error, provider_retry_has_context=provider_retry_has_context,
                continuation=attempt_continuation, materialization_prompt=attempt_materialization, greenfield_bootstrap=greenfield_bootstrap,
                follow_up_tasks=attempt_follow_up, execution_catalog=attempt_catalog,
            )
            if cache_enabled and not cache_checked:
                cache_key = self.cache_key(state, agent, prompt)
                cache_checked = True
                try:
                    cached_output = self.persistence.read_result(cache_key)
                except PlanningCacheError as exc:
                    state.add_event("planning", f"planning result cache ignored: {exc}")
                else:
                    if cached_output is None:
                        state.add_event("planning", "planning result cache miss")
                    else:
                        try:
                            plan = self.validate_plan(
                                cached_output,
                                source_root=source_root,
                                source_index=source_index,
                                required_instruction_paths=(required_instruction_paths),
                                execution_agents=execution_agents,
                                previous_tasks=state.tasks,
                                sequential=self.sequential(state),
                                planning_mode=state.planning_mode,
                                require_directory_task_draft=(require_directory_task_draft),
                                greenfield_bootstrap=greenfield_bootstrap,
                                greenfield_initial=greenfield_initial,
                                greenfield_feature=greenfield_feature,
                            )
                        except (OSError, PipelineError, PlanningError) as exc:
                            state.add_event("planning", f"planning result cache ignored: {exc}")
                        else:
                            cache_prompt_path = artifact_root / "prompts" / (f"planning-cache-{len(state.clarification_paths)}.md")
                            cache_prompt_path.parent.mkdir(parents=True, exist_ok=True)
                            cache_prompt_path.write_text(prompt, encoding="utf-8")
                            state.add_event("planning", f"planning result cache hit: provider invocation skipped ({len(prompt)} prompt characters)")
                            persist_state(state)
                            return plan
            prompt_dir = artifact_root / "prompts"
            log_dir = artifact_root / "logs"
            prompt_dir.mkdir(parents=True, exist_ok=True)
            prompt_path = prompt_dir / f"planning-{state.planning_attempts + 1}.md"
            log_path = log_dir / f"planning-{state.planning_attempts + 1}.log"
            prompt_path.write_text(prompt, encoding="utf-8")
            state.add_event("planning", f"planning prompt prepared: {len(prompt)} characters")
            state.planning_attempts += 1
            state.add_event(
                "planning",
                f"planning agent attempt {state.planning_attempts} started"
                f" with {agent.id}/{agent.provider_id}"
                + (f" with model {state.planning_model}" if state.planning_model else " with provider default model")
                + (f" and {state.planning_reasoning_effort} reasoning" if state.planning_reasoning_effort else " and provider default reasoning"),
            )
            persist_state(state)
            provider_returned = False
            try:
                output = self.invoke_agent(
                    state,
                    agent,
                    prompt,
                    prompt_path,
                    log_path,
                    timeout_seconds=(planning_timeout if planning_uses_sdk else remaining_planning_timeout()),
                    claude_session_id=claude_session_id,
                    resume_claude_session=claude_session_continuation,
                    persist_state=persist_state,
                    sdk_conversation_id=conversation_id,
                )
                provider_returned = True
                if agent.provider_id == "claude" and not state.planning_claude_session_id:
                    state.planning_claude_session_id = claude_session_id
                    claude_session_continuation = True
                    state.add_event("planning", "Claude planning session established")
                    persist_state(state)
                plan = self.validate_plan(
                    output,
                    source_root=source_root,
                    source_index=source_index,
                    required_instruction_paths=required_instruction_paths,
                    execution_agents=execution_agents,
                    previous_tasks=state.tasks,
                    sequential=self.sequential(state),
                    planning_mode=state.planning_mode,
                    require_directory_task_draft=(require_directory_task_draft),
                    greenfield_bootstrap=greenfield_bootstrap,
                    greenfield_initial=greenfield_initial,
                    greenfield_feature=greenfield_feature,
                )
            except ProviderInputTooLarge as exc:
                state.add_event("planning", f"planning agent input rejected: {exc}")
                persist_state(state)
                raise PlanningError(str(exc)) from exc
            except ProviderTimeoutError as exc:
                if planning_uses_sdk:
                    timeout_message = f"planning received no Codex SDK activity for {planning_timeout} seconds; see {log_path}"
                else:
                    timeout_message = f"planning timed out after {planning_timeout} seconds; see {log_path}"
                state.add_event("planning", f"planning agent attempt {state.planning_attempts} timed out: {timeout_message}")
                persist_state(state)
                raise PlanningError(timeout_message) from exc
            except ProviderCapacityError as exc:
                state.add_event("planning", f"planning agent attempt {state.planning_attempts} stopped for model capacity: {exc}")
                persist_state(state)
                raise PlanningError(str(exc)) from exc
            except ProviderRequestLimitError as exc:
                state.add_event("planning", f"planning agent attempt {state.planning_attempts} stopped for provider request limit: {exc}")
                persist_state(state)
                raise PlanningError(str(exc)) from exc
            except (PipelineError, PlanningError) as exc:
                last_error = str(exc)
                provider_retry_has_context = (planning_uses_sdk or agent.provider_id == "claude") and provider_returned
                state.add_event("planning", f"planning agent attempt {state.planning_attempts} failed: {exc}")
                persist_state(state)
                if attempt == self.planning.max_attempts:
                    raise PlanningError(f"planning agent failed after {attempt} attempts: {exc}") from exc
                continue
            if cache_key:
                try:
                    self.persistence.save_result(cache_key, output)
                except (OSError, PlanningCacheError) as exc:
                    state.add_event("planning", f"planning result cache write failed: {exc}")
                    persist_state(state)
            return plan
        raise AssertionError("planning attempts exhausted without a result")
