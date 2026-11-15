from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Callable, ContextManager

from ..models import RunState
from ..usage import UsageObservation, UsageRecord, task_usage_summaries, usage_groups, usage_id, usage_now, usage_summary


@dataclass(frozen=True, slots=True)
class UsageLedger:
    directory: Callable[[], Path]
    read_state: Callable[[], RunState]
    acquire_lock: Callable[[], ContextManager[None]]
    write_json: Callable[[Path, dict[str, object]], None]

    def records(self) -> list[UsageRecord]:
        self.read_state()  # Do not recreate a deleted or unknown run from a late SDK callback.
        records = []
        for path in self.directory().glob("*.json"):
            if path.name == "manifest.json":
                continue
            try:
                usage_id(path.stem)
                record = UsageRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
                if record.invocation_id != path.stem:
                    raise ValueError("usage file ID differs from its record")
            except (OSError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid usage record: {path.name}: {exc}") from exc
            records.append(record)
        identifiers = [(row.provider, row.thread_id, row.turn_id) for row in records if row.thread_id and row.turn_id]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("duplicate provider turn in usage ledger")
        return sorted(records, key=lambda row: (row.created_at, row.invocation_id), reverse=True)

    def begin(self, record: UsageRecord) -> None:
        with self.acquire_lock():
            rows = self.records()
            existing = next((row for row in rows if row.invocation_id == record.invocation_id), None)
            if existing is not None:
                if existing != record:
                    raise ValueError("usage invocation already registered with different metadata")
                return
            directory = self.directory()
            directory.mkdir(parents=True, exist_ok=True)
            manifest = directory / "manifest.json"
            if not manifest.exists():
                self.write_json(manifest, {"schema_version": 1, "recording_started_at": usage_now()})
            self.write_json(directory / f"{record.invocation_id}.json", record.to_dict())

    def observe(self, invocation_id: str, observation: UsageObservation) -> None:
        usage_id(invocation_id)
        with self.acquire_lock():
            rows = self.records()
            current = next((row for row in rows if row.invocation_id == invocation_id), None)
            if current is None:
                raise ValueError("unknown usage invocation")
            if observation.source_revision < current.source_revision:
                return
            updated = current.observe(observation)
            if observation.source_revision == current.source_revision:
                if updated != current:
                    raise ValueError("usage source revision has conflicting values")
                return
            if current.finalized and not observation.finalized:
                raise ValueError("usage finalization cannot regress")
            if current.thread_id and (current.thread_id, current.turn_id, current.usage_epoch) != (
                    updated.thread_id, updated.turn_id, updated.usage_epoch):
                raise ValueError("usage provider identifiers cannot change")
            if updated.thread_id and updated.turn_id and any(
                (row.provider, row.thread_id, row.turn_id) == (updated.provider, updated.thread_id, updated.turn_id)
                for row in rows if row.invocation_id != invocation_id
            ):
                raise ValueError("provider turn already belongs to another usage invocation")
            self.write_json(self.directory() / f"{invocation_id}.json", updated.to_dict())

    def finish(self, invocation_id: str, outcome: str, *, structured: bool) -> None:
        self.update(invocation_id, lambda row: replace(
            row, outcome=outcome, finalized=row.finalized or not structured,
            missing_reason="provider_not_reported" if row.missing_reason == "usage_pending" else row.missing_reason,
        ))

    def update_model(self, invocation_id: str, model: str) -> None:
        self.update(invocation_id, lambda row: replace(row, model_effective=model))

    def update(self, invocation_id: str, update: Callable[[UsageRecord], UsageRecord]) -> None:
        usage_id(invocation_id)
        with self.acquire_lock():
            current = next((row for row in self.records() if row.invocation_id == invocation_id), None)
            if current is None:
                raise ValueError("unknown usage invocation")
            self.write_json(self.directory() / f"{invocation_id}.json", update(current).to_dict())

    def snapshot(self, *, execution_request_id: str = "", cursor: str = "", limit: int = 50) -> dict[str, object]:
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("usage limit must be an integer between 1 and 200")
        if execution_request_id:
            usage_id(execution_request_id)
        if cursor:
            usage_id(cursor)
        with self.acquire_lock():
            rows = self.records()
            active_execution = self.read_state().active_execution_request_id
            if active_execution:
                usage_id(active_execution)
            manifest = self.directory() / "manifest.json"
            started_at = ""
            if manifest.exists():
                try:
                    raw = json.loads(manifest.read_text(encoding="utf-8"))
                    if (not isinstance(raw, dict) or raw.keys() != {"schema_version", "recording_started_at"}
                            or type(raw["schema_version"]) is not int or raw["schema_version"] != 1
                            or not isinstance(raw["recording_started_at"], str)
                            or datetime.fromisoformat(raw["recording_started_at"]).tzinfo is None):
                        raise ValueError("invalid recording manifest")
                    started_at = raw["recording_started_at"]
                except (OSError, TypeError, ValueError) as exc:
                    raise ValueError("invalid usage recording manifest") from exc
            elif rows:
                raise ValueError("usage recording manifest is missing")
            request_ids = list(dict.fromkeys(row.execution_request_id for row in rows if row.execution_request_id))
            if active_execution and active_execution not in request_ids:
                request_ids.insert(0, active_execution)
            selected_id = execution_request_id or active_execution or next(iter(request_ids), "")
            execution_rows = [row for row in rows if selected_id and row.execution_request_id == selected_id]
            filtered = execution_rows if execution_request_id else rows
            start = 0
            if cursor:
                position = next((index for index, row in enumerate(filtered) if row.invocation_id == cursor), None)
                if position is None:
                    raise ValueError("unknown usage cursor in this execution scope")
                start = position + 1
            page = filtered[start:start + limit]
            return {
                "history_scope": "recorded_calls", "recording_started_at": started_at,
                "summary": usage_summary(rows), "by_mode": usage_groups(rows, "mode"), "by_purpose": usage_groups(rows, "purpose"),
                "task_summaries": task_usage_summaries(rows),
                "execution_request_id": selected_id, "execution_requests": request_ids, "execution_summary": usage_summary(execution_rows),
                "execution_is_active": bool(selected_id and selected_id == active_execution),
                "records": [row.to_dict() for row in page],
                "next_cursor": page[-1].invocation_id if page and start + len(page) < len(filtered) else "",
            }
