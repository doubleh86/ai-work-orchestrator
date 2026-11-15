"""Build provider choices with availability and account lookups."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..account_usage import AccountUsage, quota_exhausted
from ..config import AgentConfig
from ..errors import PipelineError
from ..nvidia_agent import NVIDIA_SETUP
from ..models import ProviderChoice, ProviderStatus, WorkTask
from ..planning import PlanningError, select_agent_for_provider

NEW_SELECTION_EXCLUDED_PROVIDER_IDS: frozenset[str] = frozenset()


def connected_provider_ids(
    provider_ids: set[str], *, read_statuses: Callable[[str], list[ProviderStatus]],
) -> set[str]:
    connected = set()
    for provider_id in sorted(provider_ids):
        if provider_id not in {"codex", "claude", "nvidia"}:
            connected.add(provider_id)
            continue
        status = read_statuses(provider_id)[0]
        if status.available and (provider_id not in {"codex", "claude"} or status.authenticated is True):
            connected.add(provider_id)
    return connected


@dataclass(frozen=True, slots=True)
class ConnectedProviderQueries:
    read_statuses: Callable[[str], list[ProviderStatus]]

    def ids(self, provider_ids: set[str]) -> set[str]:
        return connected_provider_ids(provider_ids, read_statuses=self.read_statuses)


@dataclass(frozen=True, slots=True)
class ProviderAvailability:
    """Check readiness using caller-owned SDK and credential probes."""

    read_agent: Callable[[str], AgentConfig | None]
    sdk_ready: Callable[[], bool]
    nvidia_ready: Callable[[], bool]
    command: Callable[[AgentConfig, str], tuple[str, ...]]
    resolve_executable: Callable[[str], str]

    def is_selectable(self, agent: AgentConfig, action: str) -> bool:
        return agent.provider_id not in NEW_SELECTION_EXCLUDED_PROVIDER_IDS and self.is_available(agent, action)

    def reviewer_compatible(self, task: WorkTask, reviewer: AgentConfig, *, policy_added: bool) -> bool:
        worker = self.read_agent(task.agent_id)
        provider = task.provider_id or (worker.provider_id if worker is not None else "")
        return reviewer.provider_id != provider or (policy_added and reviewer.provider_id == "codex")

    def is_available(self, agent: AgentConfig, action: str) -> bool:
        if agent.provider_id == "codex":
            return self.sdk_ready()
        if agent.provider_id == "nvidia" and (
            action == "planning" or not self.nvidia_ready()
        ):
            return False
        command = self.command(agent, action)
        return bool(command and self.resolve_executable(command[0]))

    def require(self, agent_id: str, action: str) -> AgentConfig:
        agent = self.read_agent(agent_id)
        if agent is None:
            raise PipelineError(f"unknown agent: {agent_id}")
        if agent.provider_id == "codex":
            if not self.sdk_ready():
                raise PipelineError(f"agent requires the openai-codex SDK: {agent_id}")
            return agent
        if agent.provider_id == "nvidia" and not self.nvidia_ready():
            raise PipelineError(NVIDIA_SETUP)
        command = self.command(agent, action)
        if not command:
            raise PipelineError(f"agent has no {action} command: {agent_id}")
        executable = self.resolve_executable(command[0])
        if not executable:
            if agent.provider_id == "nvidia":
                raise PipelineError(NVIDIA_SETUP)
            raise PipelineError(f"provider executable not found for {agent_id}: {command[0]}")
        return agent


@dataclass(frozen=True, slots=True)
class ProviderChoiceQueries:
    read_agents: Callable[[], tuple[AgentConfig, ...]]
    balance_providers: Callable[[], bool]
    is_available: Callable[[AgentConfig, str], bool]
    is_selectable: Callable[[AgentConfig, str], bool]
    connected_providers: Callable[[set[str]], set[str]]
    read_usage: Callable[[str], AccountUsage]

    def execution_choices(self, capabilities: list[str]) -> list[ProviderChoice]:
        requested = set(capabilities)
        agents = tuple(
            agent for agent in self.read_agents()
            if self.is_selectable(agent, "execute") and (requested & set(agent.capabilities) or "general" in agent.capabilities)
        )
        connected_providers = self.connected_providers({agent.provider_id for agent in agents})
        choices = [
            ProviderChoice(provider_id=agent.provider_id, agent_id=agent.id, model=agent.model, max_tasks=agent.max_tasks)
            for agent in agents if agent.provider_id in connected_providers
        ]
        choices.sort(key=lambda choice: (choice.provider_id, choice.agent_id))
        return choices

    def choices(self, capabilities: list[str], *, action: str, default_agent_id: str = "") -> list[ProviderChoice]:
        agents = tuple(
            agent for agent in self.read_agents()
            if not ("planning" in capabilities and agent.provider_id == "nvidia") and self.is_selectable(agent, action)
        )
        connected_providers = self.connected_providers({agent.provider_id for agent in agents})
        available_agents = tuple(agent for agent in agents if agent.provider_id in connected_providers)
        providers = sorted({agent.provider_id for agent in available_agents})
        task = WorkTask(id="provider-choice", title="provider choice", capabilities=capabilities)
        default_agent = next((agent for agent in available_agents if agent.id == default_agent_id), None)
        choices: list[ProviderChoice] = []
        for provider_id in providers:
            if (
                default_agent is not None
                and default_agent.provider_id == provider_id
                and (set(capabilities) & set(default_agent.capabilities) or "general" in default_agent.capabilities)
            ):
                agent = default_agent
            else:
                try:
                    agent = select_agent_for_provider(task, available_agents, provider_id, purpose=action)
                except PlanningError:
                    continue
            choices.append(
                ProviderChoice(
                    provider_id=provider_id, agent_id=agent.id, model=agent.model, is_default=agent.id == default_agent_id, max_tasks=agent.max_tasks
                )
            )
        choices.sort(key=lambda choice: (not choice.is_default, choice.provider_id, choice.agent_id))
        return choices

    def planning_execution_agents(self) -> tuple[AgentConfig, ...]:
        agents = tuple(agent for agent in self.read_agents() if self.is_available(agent, "execute"))
        if self.balance_providers():
            connected = self.connected_providers({agent.provider_id for agent in agents})
            agents = tuple(
                agent for agent in agents if agent.provider_id in connected
                and not quota_exhausted(self.read_usage(agent.provider_id))
            )
        # Preserve commandless custom profiles for the legacy manual workflow.
        manual_agents = tuple(
            agent for agent in self.read_agents() if agent.provider_id == "custom" and not agent.command and not agent.manual_only
        )
        return (*agents, *manual_agents)
