"""Planning AI calls within the shared request policy scope."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from .policy_scope import PlanningPolicyScope
from ..config import RoutingConfig, AgentConfig
from ..document_index import PlanningSourceIndex
from ..execution import ProviderRunner
from ..execution.provider_commands import agent_command
from ..models import PlanningMode, WorkTask, ResolvedEffortPolicy, RunState
from ..planner import execution_profile_guidance, Plan
from ..planning import render_planning_chat_prompt
from .chat import PlanningChatRunner
from .conversation import clarification_context
from .invocation import PlanningInvocation
from .output import planning_cache_key, validated_planning_plan
from .runner import PlanningRunner


@dataclass
class PlanningAI:
    policy_scope: PlanningPolicyScope
    context: ContextVar[tuple[str, str, ResolvedEffortPolicy] | None]
    plan_runner: Callable[[], PlanningRunner]
    chat_runner: Callable[[], PlanningChatRunner]
    invocation: Callable[[], PlanningInvocation]
    timeout: Callable[[], int]
    sdk_available: Callable[[], bool]
    repository: Callable[[], Path]
    configured_agents: Callable[[], tuple[AgentConfig, ...]]
    routing: Callable[[], RoutingConfig]
    registered_models: Callable[[], tuple[str, ...]]
    execution_agents: Callable[[], tuple[AgentConfig, ...]]

    def build_plan(
        self, state: RunState, document: str, *, clarification_context: str = "", source_index: PlanningSourceIndex | None = None,
        preview_id: str = "",
    ) -> Plan:
        purpose = "planning_preview" if preview_id else "planning"
        with self.policy_scope.scope(state, purpose=purpose):
            return self.plan_runner().run(
                state, document, clarification_context=clarification_context, source_index=source_index, preview_id=preview_id
            )

    def chat_turn(
        self, state: RunState, agent: AgentConfig, message: str, *, persist_state: Callable[[RunState], None] | None = None
    ) -> str:
        with self.policy_scope.scope(state, purpose="chat"):
            return self.chat_runner().run(state, agent, message, persist_state=persist_state)

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
    ) -> str:
        invocation = self.invocation()
        return invocation.invoke(
            state, agent, prompt, prompt_path, log_path, timeout_seconds=timeout_seconds, claude_session_id=claude_session_id,
            resume_claude_session=resume_claude_session, persist_state=persist_state, sdk_conversation_id=sdk_conversation_id,
            usage_purpose=usage_purpose, effort_context=self.context.get(), default_timeout=self.timeout(),
            sdk_available=self.sdk_available(),
        )


    def validate_plan(
        self,
        output: str,
        *,
        source_root: Path | None,
        source_index: PlanningSourceIndex | None,
        required_instruction_paths: set[str],
        execution_agents: tuple[AgentConfig, ...],
        planning_mode: PlanningMode,
        require_directory_task_draft: bool,
        previous_tasks: list[WorkTask] | None = None,
        sequential: bool = False,
        greenfield_bootstrap: bool = False,
        greenfield_initial: bool = False,
        greenfield_feature: bool = False,
    ) -> Plan:
        return validated_planning_plan(
            output, repo=self.repository(), agents=self.configured_agents(), routing=self.routing(),
            additional_models=lambda: {"nvidia": tuple(self.registered_models())},
            effort_mode=lambda: self.context.get()[2].mode if self.context.get() else None,
            source_root=source_root, source_index=source_index, required_instruction_paths=required_instruction_paths,
            execution_agents=execution_agents, planning_mode=planning_mode, require_directory_task_draft=require_directory_task_draft,
            previous_tasks=previous_tasks, sequential=sequential, greenfield_bootstrap=greenfield_bootstrap,
            greenfield_initial=greenfield_initial, greenfield_feature=greenfield_feature,
        )

    def cache_key(self, state: RunState, agent: AgentConfig, prompt: str) -> str:
        sdk_profile = ProviderRunner.codex_profile(agent, "planning")
        context = self.context.get()
        policy = context[2] if context is not None and context[0] == state.id else None
        return planning_cache_key(
            state, agent, prompt, sdk_profile=sdk_profile, policy=policy,
            review_command=lambda: agent_command(agent, "review"),
        )

    def chat_prompt(self, message: str, *, continuation: bool, document: str, conversation_context: str, sequential: bool = False) -> str:
        catalog = execution_profile_guidance(
            self.execution_agents(), sequential=sequential, balance_providers=self.routing().balance_providers,
        )
        return render_planning_chat_prompt(
            message, continuation=continuation, document=document, conversation_context=conversation_context, catalog=catalog,
            repository_root=self.repository().resolve().as_posix() if not continuation else "",
        )
