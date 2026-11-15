from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..models import UserNotificationEvent


@dataclass(frozen=True, slots=True)
class NotificationEventRepository:
    validate_run_id: Callable[[str], None]
    run_directory: Callable[[str], Path]
    write_json: Callable[[Path, dict[str, object]], None]

    def save(self, event: UserNotificationEvent) -> None:
        self.validate_run_id(event.run_id)
        if not re.fullmatch(r"[0-9a-f]{64}", event.event_id):
            raise ValueError("invalid notification event ID")
        target = self.run_directory(event.run_id) / "notifications" / f"{event.event_id[:16]}.json"
        if target.exists():
            saved = self.read(target, event.run_id)
            if (saved.event_id, saved.source_key, saved.project_key) != (event.event_id, event.source_key, event.project_key):
                raise ValueError("notification event ID refers to different evidence")
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        self.write_json(target, {"schema_version": 1, "event": event.to_dict()})

    def load(self, run_id: str) -> list[UserNotificationEvent]:
        self.validate_run_id(run_id)
        root = self.run_directory(run_id) / "notifications"
        if not root.exists():
            return []
        events = [self.read(path, run_id) for path in root.iterdir() if path.suffix == ".json"]
        return sorted(events, key=lambda event: (event.occurred_at, event.event_id))

    @staticmethod
    def read(path: Path, run_id: str) -> UserNotificationEvent:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("schema_version") != 1 or not isinstance(raw.get("event"), dict):
            raise ValueError(f"invalid notification event: {path}")
        try:
            event = UserNotificationEvent(**raw["event"])
        except TypeError as exc:
            raise ValueError(f"invalid notification event: {path}") from exc
        fields = event.to_dict()
        if (not isinstance(event.event_id, str) or not re.fullmatch(r"[0-9a-f]{64}", event.event_id)
                or event.run_id != run_id or event.event_id[:16] != path.stem
                or any(not isinstance(value, str) for name, value in fields.items() if name not in {"related_targets", "os_eligible"})
                or not isinstance(event.os_eligible, bool) or not isinstance(event.related_targets, list)
                or any(not isinstance(value, str) for value in event.related_targets)):
            raise ValueError(f"invalid notification event: {path}")
        return event
