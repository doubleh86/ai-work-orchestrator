from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..errors import PipelineError
from ..models import RunState, UserNotificationEvent
from .events import notification_events_for_state


@dataclass(frozen=True, slots=True)
class NotificationCollector:
    project_key: Callable[[], str]
    deployment_configured: Callable[[], bool]
    read_runs: Callable[[], list[RunState]]
    load_events: Callable[[str], list[UserNotificationEvent]]

    def page(self, *, after_cursor: str = "", limit: int = 100) -> dict[str, object]:
        if limit < 1 or limit > 500:
            raise PipelineError("notification limit must be between 1 and 500")
        project_key = self.project_key()
        deployment_configured = self.deployment_configured()
        by_source: dict[str, UserNotificationEvent] = {}
        for state in self.read_runs():
            for event in [
                *state.notification_events,
                *self.load_events(state.id),
                *notification_events_for_state(
                    state,
                    project_key=project_key,
                    deployment_configured=deployment_configured,
                ),
            ]:
                by_source[event.source_key] = event
        events = sorted(by_source.values(), key=lambda event: (event.occurred_at, event.event_id))
        start = 0
        if after_cursor:
            start = next((index + 1 for index, event in enumerate(events) if event.event_id == after_cursor), 0)
        selected = events[start : start + limit]
        next_cursor = selected[-1].event_id if selected else after_cursor
        return {
            "items": [event.to_dict() for event in selected],
            "next_cursor": next_cursor,
            "has_more": start + len(selected) < len(events),
        }
