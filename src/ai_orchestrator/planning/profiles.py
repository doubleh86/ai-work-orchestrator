"""Planning profile metadata and automatic reasoning through narrow ports."""

from __future__ import annotations

from ..models import PlanningMode

from dataclasses import dataclass
from typing import Callable

from ..config import AgentConfig
from ..effort_policy import resolve_reasoning_profile
from ..errors import PipelineError
from ..model_selection import automatic_claude_profile
from ..models import EffortMode, ProfileSource, RunState


@dataclass(frozen=True, slots=True)
class PlanningProfiles:
    default_agent_id: Callable[[], str]
    read_agent: Callable[[str], AgentConfig | None]
    available_agent: Callable[[str, str], AgentConfig]
    selected_mode: Callable[[str], EffortMode | None]
    normalize_agent_id: Callable[[str], str]
    normalize_model: Callable[[str], str]
    normalize_effort: Callable[[str], str]
    validate_effort: Callable[[AgentConfig, str, str], None]

    def configure(
        self, state: RunState, *, planning_agent_id: str | None, planning_model: str | None,
        planning_reasoning_effort: str | None,
    ) -> AgentConfig:
        if not (state.planning_agent_id or self.default_agent_id()):
            raise PipelineError("planning conversation requires a configured planning agent")
        previous_agent_id = state.planning_agent_id
        previous_provider_id = state.planning_provider_id
        previous_model = state.planning_model
        if planning_agent_id is not None or planning_model is not None or planning_reasoning_effort is not None:
            state.planning_profile_source = ProfileSource.MANUAL
            state.planning_effort_baseline_reasoning = None
        if planning_agent_id is not None:
            selected_agent_id = self.normalize_agent_id(planning_agent_id)
            if not selected_agent_id:
                raise PipelineError("planning agent must not be empty")
            selected_agent = self.available_agent(selected_agent_id, "review")
            state.planning_agent_id = selected_agent.id
            state.planning_provider_id = selected_agent.provider_id
        if planning_model is not None:
            state.planning_model = self.normalize_model(planning_model)
        if planning_reasoning_effort is not None:
            state.planning_reasoning_effort = self.normalize_effort(planning_reasoning_effort)
        active_agent = self.available_agent(state.planning_agent_id or self.default_agent_id(), "review")
        state.planning_agent_id = active_agent.id
        state.planning_provider_id = active_agent.provider_id
        if state.planning_claude_session_id and (
            previous_agent_id != state.planning_agent_id
            or previous_provider_id != state.planning_provider_id
            or previous_model != state.planning_model
        ):
            state.planning_claude_session_id = ""
            state.add_event("planning", "Claude planning chat session cleared after profile change")
        self.validate_effort(active_agent, state.planning_reasoning_effort, state.planning_model or active_agent.model)
        return active_agent

    def pin_automatic(self, state: RunState) -> None:
        agent = self.read_agent(state.planning_agent_id or self.default_agent_id())
        if (agent is None or agent.provider_id not in {"codex", "claude"}
                or state.planning_profile_source in {ProfileSource.MANUAL, ProfileSource.LEGACY}):
            return
        if agent.provider_id == "claude" and not automatic_claude_profile(state.planning_profile_source, state.planning_model or agent.model):
            return
        mode = self.selected_mode(state.id) or EffortMode.BALANCED
        decision = resolve_reasoning_profile(
            mode=mode, provider_id=agent.provider_id, model=state.planning_model or agent.model,
            reasoning_effort=state.planning_reasoning_effort, profile_source=state.planning_profile_source,
            baseline_reasoning_effort=state.planning_effort_baseline_reasoning, purpose="planning",
        )
        if decision.unsupported_effects:
            raise PipelineError("automatic Planning model requires its original profile baseline")
        if state.planning_profile_source != ProfileSource.MODE:
            state.planning_effort_baseline_reasoning = state.planning_reasoning_effort
        state.planning_model = decision.model
        state.planning_reasoning_effort = decision.reasoning_effort
        state.planning_profile_source = decision.profile_source


def normalize_planning_mode(mode: PlanningMode | str) -> PlanningMode:
    try:
        return PlanningMode(mode)
    except ValueError as exc:
        raise PipelineError(f"unsupported planning mode: {mode}") from exc
