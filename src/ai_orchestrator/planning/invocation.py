"""Planning calls with caller-owned policy scope and SDK lifetime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, ContextManager, Protocol

from ..codex_sdk import CodexSdkProgress
from ..config import AgentConfig
from ..effort_policy import resolve_reasoning_profile
from ..errors import PipelineError
from ..models import EffortMode, EffortPlanningBinding, EffortPolicyState, ProfileSource, ResolvedEffortPolicy, RunState
from ..usage import UsageContext


class PlanningPolicyLoader(Protocol):
    def __call__(self, run_id: str, *, archived_chat: bool = False) -> EffortPolicyState: ...


class PlanningPolicyPath(Protocol):
    def __call__(self, run_id: str, *, archived_chat: bool = False) -> Path: ...


class StartPlanning(Protocol):
    def __call__(self, run_id: str, request_id: str, *, archived_chat: bool = False) -> EffortPlanningBinding: ...


class PlanningSessionCommand(Protocol):
    def __call__(self, agent: AgentConfig, command_template: tuple[str, ...], session_id: str, *, resume: bool) -> tuple[str, ...]: ...


class PlanningProgressRecorder(Protocol):
    def __call__(self, state: RunState, progress: CodexSdkProgress, *, persist_state: Callable[[RunState], None]) -> None: ...


class PlanningProviderInvocation(Protocol):
    def __call__(
        self, *, agent: AgentConfig, command_template: tuple[str, ...], replacements: dict[str, str], cwd: Path,
        prompt: str, prompt_path: str, log_path: Path, action: str, usage_context: UsageContext, task_id: str,
        timeout_seconds: float, model: str, reasoning_effort: str, progress_callback: Callable[[CodexSdkProgress], None],
        sdk_conversation_id: str,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class PlanningInvocationRecords:
    save_state: Callable[[RunState], None]
    load_effort_policy: PlanningPolicyLoader
    effort_policy_path: PlanningPolicyPath
    start_effort_planning: StartPlanning


@dataclass(frozen=True, slots=True)
class PlanningInvocation:
    repo: Path
    records: PlanningInvocationRecords
    command: Callable[[AgentConfig, str], tuple[str, ...]]
    command_with_model: Callable[[AgentConfig, tuple[str, ...], str], tuple[str, ...]]
    command_with_effort: Callable[[AgentConfig, tuple[str, ...], str, str], tuple[str, ...]]
    command_with_session: PlanningSessionCommand
    with_effort_mode_guidance: Callable[[str, EffortMode], str]
    record_progress: PlanningProgressRecorder
    conversation_id: Callable[[RunState], str]
    invoke_provider: PlanningProviderInvocation

    def invoke(
        self,
        state: RunState,
        agent: AgentConfig,
        prompt: str,
        prompt_path: Path,
        log_path: Path,
        *,
        timeout_seconds: float | None = None,
        claude_session_id: str = "",
        resume_claude_session: bool = False,
        persist_state: Callable[[RunState], None] | None = None,
        sdk_conversation_id: str = "",
        usage_purpose: str = "planning",
        effort_context: tuple[str, str, ResolvedEffortPolicy] | None = None,
        default_timeout: float,
        sdk_available: bool,
    ) -> str:
        persist = persist_state or self.records.save_state
        context = effort_context
        archive_options = {"archived_chat": True} if state.archive is not None and usage_purpose == "chat" else {}
        profile = None
        usage_context = UsageContext(state.id, usage_purpose)
        if context is not None and context[0] == state.id:
            policy = context[2]
            binding = self.records.load_effort_policy(state.id, **archive_options).planning_binding(context[1])
            if binding is None:
                raise PipelineError("Planning usage requires its fixed policy binding")
            usage_context = UsageContext(
                state.id, "planning" if binding.purpose == "planning_preview" else binding.purpose,
                operation_request_id=context[1], policy_id=policy.policy_id, mode=policy.mode.value,
            )
            profile = policy.planning_profile
            if profile is None or (profile.agent_id, profile.provider_id) != (agent.id, agent.provider_id):
                raise PipelineError("Planning agent differs from the fixed effort policy")
            prompt = self.with_effort_mode_guidance(prompt, policy.mode)
            prompt_path.write_text(prompt, encoding="utf-8")
        elif (self.records.effort_policy_path(state.id, **archive_options).exists() or (
            archive_options and self.records.effort_policy_path(state.id).exists()
        )) and self.records.load_effort_policy(state.id, **archive_options).selected_mode is not None:
            raise PipelineError("Planning requires a fixed effort policy request before invoking AI")
        model = profile.model if profile is not None else state.planning_model or agent.model
        reasoning_effort = profile.reasoning_effort if profile is not None else state.planning_reasoning_effort
        if (profile is None and agent.provider_id in {"codex", "claude"}
                and state.planning_profile_source not in {ProfileSource.MANUAL, ProfileSource.LEGACY}):
            decision = resolve_reasoning_profile(
                mode=EffortMode.BALANCED, provider_id=agent.provider_id, model=model, reasoning_effort=reasoning_effort,
                profile_source=state.planning_profile_source, baseline_reasoning_effort=state.planning_effort_baseline_reasoning,
                purpose="planning", configured_model=agent.model,
            )
            if decision.unsupported_effects:
                raise PipelineError("automatic Planning model requires its original profile baseline")
            model, reasoning_effort = decision.model, decision.reasoning_effort
        command_template = self.command(agent, "review")
        command_template = self.command_with_model(agent, command_template, model)
        command_template = self.command_with_effort(
            agent, command_template, reasoning_effort, model
        )
        if claude_session_id:
            command_template = self.command_with_session(agent, command_template, claude_session_id, resume=resume_claude_session)
        elif resume_claude_session:
            raise PipelineError("Claude planning session resume requires a session id")
        replacements = {
            "{worktree}": str(self.repo),
            "{prompt}": str(prompt_path),
            "{task_id}": "planning",
            "{run_id}": state.id,
        }
        if agent.provider_id in {"claude", "codex"} and state.spec_path:
            source = Path(state.spec_path)
            if source.is_absolute() and source.is_dir() and not source.is_relative_to(self.repo):
                replacements["{planning_source}"] = str(source)
        if agent.provider_id == "codex" and sdk_available:
            state.add_event("planning", "planning transport selected: codex SDK")
            persist(state)
        if context is not None and context[0] == state.id:
            self.records.start_effort_planning(state.id, context[1], **archive_options)
        return self.invoke_provider(
            agent=agent,
            command_template=command_template,
            replacements=replacements,
            cwd=self.repo,
            prompt=prompt,
            prompt_path=str(prompt_path),
            log_path=log_path,
            action="planning",
            usage_context=usage_context,
            task_id="planning",
            timeout_seconds=(default_timeout if timeout_seconds is None else timeout_seconds),
            model=model,
            reasoning_effort=reasoning_effort,
            progress_callback=lambda progress: self.record_progress(state, progress, persist_state=persist),
            sdk_conversation_id=sdk_conversation_id or self.conversation_id(state),
        )


def record_planning_progress(
    state: RunState, progress: CodexSdkProgress, *, state_lock: ContextManager[object], persist_state: Callable[[RunState], None],
) -> None:
    message = f"codex sdk progress: {progress.phase}"
    if progress.detail:
        message += f" | {progress.detail}"
    with state_lock:
        if state.events and state.events[-1].message == message:
            return
        state.add_event("planning_progress", message)
        persist_state(state)
