"""Read-only control decisions within caller-owned chat scopes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Callable, ContextManager, Protocol

from ..config import AgentConfig
from ..models import IntegrationControl, OperationRecord, ResolvedEffortPolicy, RunExecutionControl, RunState, WorkTask
from ..project_chat import MAX_REPAIRS, decision_prompt, parse_decision
from ..scope_consent import ScopeConsent, parse_scope_consent, scope_consent_prompt
from .apply_requests import PlanningApplyProfile

if TYPE_CHECKING:
    from ..task_scope_review import TaskScopeReview


class ControlEffortScope(Protocol):
    def __call__(self, state: RunState, *, purpose: str) -> ContextManager[ResolvedEffortPolicy | None]: ...


class ControlAgentInvocation(Protocol):
    def __call__(
        self, state: RunState, agent: AgentConfig, prompt: str, prompt_path: Path, log_path: Path, *,
        persist_state: Callable[[RunState], None], usage_purpose: str, sdk_conversation_id: str,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class ProjectDecisionContext:
    actions: Callable[[RunState, RunExecutionControl, IntegrationControl, int], list[str]]
    scope_proposal: Callable[[RunState, str], dict[str, object] | None]
    load_operation: Callable[[str, str], OperationRecord | None]
    task_draft: Callable[[WorkTask], dict[str, object]]
    scope_digest: Callable[[WorkTask], str]
    scope_review: Callable[[WorkTask], TaskScopeReview | None]

    def build(
        self, state: RunState, run_id: str, request_id: str, record: OperationRecord,
        control: RunExecutionControl, integration: IntegrationControl, expected: dict[str, object],
    ) -> dict[str, object]:
        return {
            "user_request": record.payload["message"], "goal": state.summary,
            "focused_task": expected.get("taskId", ""), "stage": state.stage.value,
            "execution": asdict(control), "integration": asdict(integration),
            "available_actions": self.actions(state, control, integration, record.payload["repairs"]),
            "remaining_repairs": MAX_REPAIRS - record.payload["repairs"],
            "scope_proposal": self.scope_proposal(state, str(expected.get("taskId", ""))),
            "scope_consent": self.load_operation(run_id, request_id).payload.get("scope_consent"),
            "tasks": [{**self.task_draft(task), "status": task.status.value,
                       "error": (review.error(self.scope_digest(task))
                                 if (review := self.scope_review(task)) else task.error),
                       "implementation_notes": task.implementation_notes} for task in state.tasks],
            "recent_conversation": [{"role": item.role.value, "text": item.text[-4000:]} for item in state.planning_messages[-8:]],
            "actual_tool_results": record.payload["history"],
        }


@dataclass(frozen=True, slots=True)
class ControlPlanningInvocation:
    run_directory: Callable[[str], Path]
    save_chat: Callable[[RunState], None]
    configure_profile: PlanningApplyProfile
    effort_scope: ControlEffortScope
    invoke: ControlAgentInvocation

    def project(
        self, state: RunState, run_id: str, request_id: str, record: OperationRecord,
        control: RunExecutionControl, integration: IntegrationControl, expected: dict[str, object],
        *, context_builder: ProjectDecisionContext,
    ) -> dict[str, object]:
        profile = record.payload.get("profile", {})
        agent = self.configure_profile(state, planning_agent_id=profile.get("planningAgentId"),
            planning_model=profile.get("planningModel"), planning_reasoning_effort=profile.get("planningReasoningEffort"))
        agent = replace(agent, review_sandbox_mode="read-only", review_approval_mode="deny-all")
        context = context_builder.build(state, run_id, request_id, record, control, integration, expected)
        prompt = decision_prompt(context)
        prompt_path = self.run_directory(run_id) / "prompts" / f"project-chat-{record.payload['step_id']}.md"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt, encoding="utf-8")
        self.save_chat(state)
        with self.effort_scope(state, purpose="chat"):
            output = self.invoke(state, agent, prompt, prompt_path,
                self.run_directory(run_id) / "logs" / f"project-chat-{record.payload['step_id']}.log",
                persist_state=self.save_chat, usage_purpose="chat",
                sdk_conversation_id=f"project-chat:{run_id}:{record.payload['step_id']}")
        decision = parse_decision(output)
        return decision

    def scope_consent(
        self, state: RunState, run_id: str, record: OperationRecord,
        candidate: dict[str, object], proposal: dict[str, object], message: str,
    ) -> ScopeConsent:
        profile = record.payload.get("profile", {})
        agent = self.configure_profile(state, planning_agent_id=profile.get("planningAgentId"),
            planning_model=profile.get("planningModel"), planning_reasoning_effort=profile.get("planningReasoningEffort"))
        agent = replace(agent, review_sandbox_mode="read-only", review_approval_mode="deny-all")
        prompt = scope_consent_prompt(message, proposal, previous_response=str(candidate.get("previous_response", "")))
        prompt_path = self.run_directory(run_id) / "prompts" / f"scope-consent-{record.payload['step_id']}.md"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt, encoding="utf-8")
        with self.effort_scope(state, purpose="chat"):
            output = self.invoke(state, agent, prompt, prompt_path,
                self.run_directory(run_id) / "logs" / f"scope-consent-{record.payload['step_id']}.log",
                persist_state=self.save_chat, usage_purpose="chat",
                sdk_conversation_id=f"scope-consent:{run_id}:{record.payload['step_id']}")
        consent = parse_scope_consent(output, proposal=proposal, message=message)
        return consent
