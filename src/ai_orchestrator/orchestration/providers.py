"""Provider selection and connection queries through explicit ports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..account_usage import AccountUsage
from ..models import ProviderChoice, ProviderStatus
from ..execution.provider_choices import ProviderChoiceQueries, ConnectedProviderQueries
from ..execution.provider_status import ProviderStatusQueries
from ..execution import provider_connection


@dataclass(frozen=True, slots=True)
class ProviderQueries:
    choices: ProviderChoiceQueries
    status_queries: Callable[[], ProviderStatusQueries]
    default_planning_agent_id: Callable[[], str]
    connections: ConnectedProviderQueries

    def planning_provider_choices(self) -> list[ProviderChoice]:
        return self.choices.choices(["planning"], action="review", default_agent_id=self.default_planning_agent_id())

    def execution_provider_choices(self, capabilities: list[str]) -> list[ProviderChoice]:
        return self.choices.execution_choices(capabilities)

    def provider_statuses(self, provider_id: str = "") -> list[ProviderStatus]:
        return self.status_queries().statuses(provider_id)

    def connected_provider_ids(self, provider_ids: set[str]) -> set[str]:
        return self.connections.ids(provider_ids)

    @staticmethod
    def account_usage(provider: str, *, claude_api_key: str | None = None) -> AccountUsage:
        return provider_connection.account_usage(provider, claude_api_key=claude_api_key)

    @staticmethod
    def claude_connection_status() -> dict[str, object]:
        return provider_connection.claude_connection_status()
