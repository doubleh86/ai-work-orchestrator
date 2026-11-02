from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import socket
import time
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

from .usage import UsageObservation, UsageRecord, task_usage_summaries, usage_groups, usage_id, usage_now, usage_summary

from .models import (
    DirectionChangeRequest,
    DirectionChangeStatus,
    EffortExecutionBinding,
    EffortProfileSnapshot,
    EffortPlanningBinding,
    EffortPolicyState,
    EffortPolicyView,
    Event,
    ExecutionControlRecord,
    OperationRecord,
    PlanningApplyRequest,
    PlanningApplyStatus,
    PlanningMessage,
    PlanningMessageRole,
    ProfileSource,
    RunLockState,
    RunLockStatus,
    RunState,
    RunStep,
    RunSummary,
    UserNotificationEvent,
    Stage,
    ResolvedEffortPolicy,
    utc_now,
)

PLANNING_RESULT_CACHE_SCHEMA_VERSION = 1
PLANNING_CHAT_SIDECAR_SCHEMA_VERSION = 1
ARCHIVE_MANIFEST_SCHEMA_VERSION = 1


class RunLockedError(RuntimeError):
    pass


class PlanningCacheError(ValueError):
    pass


class PlanningChatSidecarError(ValueError):
    pass


class StateStore:
    def __init__(self, root: Path, notification_sync: Callable[[RunState], None] | None = None):
        self.root = root
        self.notification_sync = notification_sync

    def run_dir(self, run_id: str) -> Path:
        return self.root / "runs" / run_id

    def state_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "state.json"

    def lock_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "run.lock"

    def planning_chat_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "planning-chat.json"

    def archived_planning_chat_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "archived-planning-chat.json"

    def planning_chat_lock_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "planning-chat.lock"

    def task_execution_profiles_path(self, run_id: str) -> Path:
        self._validate_effort_run_id(run_id)
        return self.run_dir(run_id) / "task-execution-profiles.json"

    def load_task_execution_profiles(self, run_id: str) -> dict[str, dict[str, object]]:
        path = self.task_execution_profiles_path(run_id)
        if not path.exists():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("schema_version") != 1 or not isinstance(raw.get("profiles"), dict):
            raise ValueError(f"invalid next execution profiles: {path}")
        profiles = raw["profiles"]
        for task_id, item in profiles.items():
            if (not isinstance(task_id, str) or not task_id or not isinstance(item, dict)
                    or type(item.get("plan_revision")) is not int or not isinstance(item.get("saved_at"), str)
                    or not isinstance(item.get("expected"), dict) or not isinstance(item.get("selection"), dict)):
                raise ValueError(f"invalid next execution profile: {path}")
            if (set(item["expected"]) != {"agent_id", "model", "reasoning_effort", "last_attempt_id", "status"}
                    or set(item["selection"]) != {"agent_id", "model", "reasoning_effort"}
                    or any(not isinstance(value, str) for value in (*item["expected"].values(), *item["selection"].values()))):
                raise ValueError(f"invalid next execution profile fields: {path}")
            if "applied_policy_id" in item:
                if not isinstance(item["applied_policy_id"], str):
                    raise ValueError(f"invalid next execution policy reference: {path}")
                if item["applied_policy_id"]:
                    EffortProfileSnapshot.from_dict(item.get("policy_baseline"))
        return profiles

    def save_task_execution_profiles(self, run_id: str, profiles: dict[str, dict[str, object]]) -> None:
        target = self.task_execution_profiles_path(run_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(target, {"schema_version": 1, "profiles": profiles})

    def planning_apply_preview_path(self, run_id: str) -> Path:
        self._validate_effort_run_id(run_id)
        return self.run_dir(run_id) / "planning-apply-preview.json"

    def load_planning_apply_preview(self, run_id: str) -> dict[str, object] | None:
        path = self.planning_apply_preview_path(run_id)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid Planning apply preview: {path}: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError(f"invalid Planning apply preview: {path}")
        return payload

    def save_planning_apply_preview(self, run_id: str, payload: dict[str, object]) -> None:
        target = self.planning_apply_preview_path(run_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(target, {"schema_version": 1, **payload})

    def planning_preview_progress(self, run_id: str) -> dict[str, object] | None:
        path = self.planning_apply_preview_path(run_id).with_name("planning-preview-progress.json")
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(raw, dict) or raw.get("schema_version") != 1
                or raw.get("phase") not in {"generating", "comparing", "ready", "failed"}
                or not isinstance(raw.get("request_id"), str) or not isinstance(raw.get("owner_pid"), int)
                or not all(isinstance(raw.get(key), str) for key in ("started_at", "updated_at", "fingerprint", "error"))):
            raise ValueError(f"invalid Planning preview progress: {path}")
        return raw

    def save_planning_preview_progress(self, run_id: str, progress: dict[str, object]) -> None:
        path = self.planning_apply_preview_path(run_id).with_name("planning-preview-progress.json")
        self._write_json_atomic(path, {"schema_version": 1, **progress})

    def revision_requests_path(self, run_id: str) -> Path:
        self._validate_effort_run_id(run_id)
        return self.root / "result-revisions" / f"{run_id}.json"

    def revision_requests_lock_path(self, run_id: str) -> Path:
        self._validate_effort_run_id(run_id)
        return self.root / "result-revisions" / f"{run_id}.lock"

    @contextmanager
    def revision_requests_lock(self, run_id: str) -> Iterator[None]:
        with self._file_lock(self.revision_requests_lock_path(run_id), run_id, "revision-request", recover_stale=True):
            yield

    def load_revision_requests(self, run_id: str) -> list[dict[str, object]]:
        path = self.revision_requests_path(run_id)
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("schema_version") != 1 or not isinstance(raw.get("requests"), list):
            raise ValueError(f"invalid revision requests: {path}")
        requests = raw["requests"]
        if any(not isinstance(item, dict) for item in requests):
            raise ValueError(f"invalid revision requests: {path}")
        return requests

    def save_revision_requests(self, run_id: str, requests: list[dict[str, object]]) -> None:
        target = self.revision_requests_path(run_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(target, {"schema_version": 1, "requests": requests})

    def save_notification_event(self, event: UserNotificationEvent) -> None:
        self._validate_effort_run_id(event.run_id)
        if not re.fullmatch(r"[0-9a-f]{64}", event.event_id):
            raise ValueError("invalid notification event ID")
        target = self.run_dir(event.run_id) / "notifications" / f"{event.event_id[:16]}.json"
        if target.exists():
            saved = self._read_notification_event(target, event.run_id)
            if (saved.event_id, saved.source_key, saved.project_key) != (event.event_id, event.source_key, event.project_key):
                raise ValueError("notification event ID refers to different evidence")
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(target, {"schema_version": 1, "event": event.to_dict()})

    def load_notification_events(self, run_id: str) -> list[UserNotificationEvent]:
        self._validate_effort_run_id(run_id)
        root = self.run_dir(run_id) / "notifications"
        if not root.exists():
            return []
        events = [self._read_notification_event(path, run_id) for path in root.iterdir() if path.suffix == ".json"]
        return sorted(events, key=lambda event: (event.occurred_at, event.event_id))

    @staticmethod
    def _read_notification_event(path: Path, run_id: str) -> UserNotificationEvent:
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

    def revision_proposals_path(self, run_id: str) -> Path:
        self._validate_effort_run_id(run_id)
        return self.root / "result-revisions" / f"{run_id}-proposals.json"

    @contextmanager
    def revision_proposals_lock(self, run_id: str) -> Iterator[None]:
        path = self.revision_proposals_path(run_id).with_suffix(".lock")
        with self._file_lock(path, run_id, "revision-proposal", recover_stale=True):
            yield

    def load_revision_proposals(self, run_id: str) -> list[dict[str, object]]:
        path = self.revision_proposals_path(run_id)
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("schema_version") != 1 or not isinstance(raw.get("proposals"), list):
            raise ValueError(f"invalid revision proposals: {path}")
        proposals = raw["proposals"]
        if any(not isinstance(item, dict) for item in proposals):
            raise ValueError(f"invalid revision proposals: {path}")
        return proposals

    def save_revision_proposals(self, run_id: str, proposals: list[dict[str, object]]) -> None:
        target = self.revision_proposals_path(run_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(target, {"schema_version": 1, "proposals": proposals})

    def effort_policy_path(self, run_id: str, *, archived_chat: bool = False) -> Path:
        self._validate_effort_run_id(run_id)
        return self.run_dir(run_id) / ("archived-effort-policy.json" if archived_chat else "effort-policy.json")

    def usage_dir(self, run_id: str) -> Path:
        self._validate_effort_run_id(run_id)
        return self.run_dir(run_id) / "usage"

    @contextmanager
    def usage_lock(self, run_id: str) -> Iterator[None]:
        self._validate_effort_run_id(run_id)
        deadline = time.monotonic() + 5
        path = self.root / "usage-locks" / f"{run_id}.lock"
        recover_attempted = False
        while True:
            metadata = self._read_lock(path) if path.exists() else {}
            recover = bool(metadata and metadata.get("pid") != os.getpid() and not recover_attempted)
            recover_attempted = recover_attempted or recover
            lock = self._file_lock(path, run_id, "usage", recover_stale=recover, retry_release=True, retry_acquire_until=deadline)
            try:
                lock.__enter__()
                break
            except RunLockedError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)
        try:
            yield
        finally:
            lock.__exit__(None, None, None)

    def _usage_records(self, run_id: str) -> list[UsageRecord]:
        self.load(run_id)  # Do not recreate a deleted or unknown run from a late SDK callback.
        records = []
        for path in self.usage_dir(run_id).glob("*.json"):
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

    def begin_usage(self, run_id: str, record: UsageRecord) -> None:
        with self.usage_lock(run_id):
            rows = self._usage_records(run_id)
            existing = next((row for row in rows if row.invocation_id == record.invocation_id), None)
            if existing is not None:
                if existing != record:
                    raise ValueError("usage invocation already registered with different metadata")
                return
            directory = self.usage_dir(run_id)
            directory.mkdir(parents=True, exist_ok=True)
            manifest = directory / "manifest.json"
            if not manifest.exists():
                self._write_json_atomic(manifest, {"schema_version": 1, "recording_started_at": usage_now()})
            self._write_json_atomic(directory / f"{record.invocation_id}.json", record.to_dict())

    def observe_usage(self, run_id: str, invocation_id: str, observation: UsageObservation) -> None:
        usage_id(invocation_id)
        with self.usage_lock(run_id):
            rows = self._usage_records(run_id)
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
            self._write_json_atomic(self.usage_dir(run_id) / f"{invocation_id}.json", updated.to_dict())

    def finish_usage(self, run_id: str, invocation_id: str, outcome: str, *, structured: bool) -> None:
        self._update_usage(run_id, invocation_id, lambda row: replace(
            row, outcome=outcome, finalized=row.finalized or not structured,
            missing_reason="provider_not_reported" if row.missing_reason == "usage_pending" else row.missing_reason,
        ))

    def update_usage_model(self, run_id: str, invocation_id: str, model: str) -> None:
        self._update_usage(run_id, invocation_id, lambda row: replace(row, model_effective=model))

    def _update_usage(self, run_id: str, invocation_id: str, update: Callable[[UsageRecord], UsageRecord]) -> None:
        usage_id(invocation_id)
        with self.usage_lock(run_id):
            current = next((row for row in self._usage_records(run_id) if row.invocation_id == invocation_id), None)
            if current is None:
                raise ValueError("unknown usage invocation")
            self._write_json_atomic(self.usage_dir(run_id) / f"{invocation_id}.json", update(current).to_dict())

    def usage_snapshot(self, run_id: str, *, execution_request_id: str = "", cursor: str = "", limit: int = 50) -> dict[str, object]:
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("usage limit must be an integer between 1 and 200")
        if execution_request_id:
            usage_id(execution_request_id)
        if cursor:
            usage_id(cursor)
        with self.usage_lock(run_id):
            rows = self._usage_records(run_id)
            active_execution = self.load(run_id).active_execution_request_id
            if active_execution:
                usage_id(active_execution)
            manifest = self.usage_dir(run_id) / "manifest.json"
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

    def effort_policy_lock_path(self, run_id: str) -> Path:
        self._validate_effort_run_id(run_id)
        return self.root / "effort-policy-locks" / f"{run_id}.lock"

    @staticmethod
    def _validate_effort_run_id(run_id: str) -> None:
        if not isinstance(run_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", run_id) is None:
            raise ValueError(f"invalid effort policy run id: {run_id}")

    def project_git_lock_path(self) -> Path:
        return self.root / "project-git.lock"

    def main_change_snapshot_path(self, snapshot_id: str) -> Path:
        if len(snapshot_id) != 64 or any(character not in "0123456789abcdef" for character in snapshot_id):
            raise ValueError("invalid Main change snapshot ID")
        return self.root / "main-change-snapshots" / f"{snapshot_id}.json"

    def save_main_change_snapshot(self, snapshot_id: str, payload: dict[str, object]) -> Path:
        target = self.main_change_snapshot_path(snapshot_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(target, payload)
        return target

    def load_main_change_snapshot(self, snapshot_id: str) -> dict[str, object] | None:
        target = self.main_change_snapshot_path(snapshot_id)
        if not target.exists():
            return None
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid Main change snapshot: {target}: {exc}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"Main change snapshot must be an object: {target}")
        return payload

    def operation_path(self, run_id: str, request_id: str) -> Path:
        try:
            normalized = str(uuid.UUID(request_id))
        except (ValueError, AttributeError) as exc:
            raise ValueError("requestId must be a UUID") from exc
        return self.run_dir(run_id) / "operations" / f"{normalized}.json"

    def operation_result_path(self, run_id: str, request_id: str) -> Path:
        operation = self.operation_path(run_id, request_id)
        return operation.with_name(f"{operation.stem}.result.json")

    def execution_control_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "execution-control.json"

    def execution_control_lock_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "execution-control.lock"

    def archive_snapshot_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "archive-snapshot.json"

    def archive_manifest_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "archive-manifest.json"

    def archive_summary_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "summary.md"

    def planning_cache_path(self, key: str) -> Path:
        if len(key) != 64 or any(character not in "0123456789abcdef" for character in key):
            raise PlanningCacheError(f"invalid planning cache key: {key}")
        return self.root / "planning-cache" / f"{key}.json"

    def load_planning_result(self, key: str) -> str | None:
        path = self.planning_cache_path(key)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PlanningCacheError(f"invalid planning result cache: {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise PlanningCacheError(f"planning result cache must be an object: {path}")
        if raw.get("schema_version") != PLANNING_RESULT_CACHE_SCHEMA_VERSION:
            raise PlanningCacheError(f"unsupported planning result cache schema: {raw.get('schema_version')}")
        if raw.get("key") != key:
            raise PlanningCacheError(f"planning result cache key mismatch: {path}")
        output = raw.get("output")
        if not isinstance(output, str) or not output.strip():
            raise PlanningCacheError(f"planning result cache output must be a non-empty string: {path}")
        return output

    def save_planning_result(self, key: str, output: str) -> Path:
        if not isinstance(output, str) or not output.strip():
            raise PlanningCacheError("planning result cache output must be a non-empty string")
        path = self.planning_cache_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps({"schema_version": PLANNING_RESULT_CACHE_SCHEMA_VERSION, "key": key, "output": output}, ensure_ascii=False, indent=2)
                + "\n",
                encoding="utf-8",
            )
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return path

    def load_operation(self, run_id: str, request_id: str) -> OperationRecord | None:
        path = self.operation_path(run_id, request_id)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return OperationRecord.from_dict(raw)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid operation record: {path}: {exc}") from exc

    def claim_operation(self, record: OperationRecord) -> tuple[OperationRecord, bool]:
        path = self.operation_path(record.run_id, record.request_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            existing = self.load_operation(record.run_id, record.request_id)
            if existing is None:
                raise ValueError(f"operation record disappeared while claiming: {record.request_id}")
            return existing, False
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(record.to_dict(), handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        return record, True

    def save_operation(self, record: OperationRecord) -> None:
        path = self.operation_path(record.run_id, record.request_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(path, record.to_dict())

    def latest_operation(self, run_id: str, action: str) -> OperationRecord | None:
        return next(iter(self.recent_operations(run_id, action, limit=1)), None)

    def recent_operations(self, run_id: str, action: str, *, limit: int = 16) -> list[OperationRecord]:
        """같은 Run과 행동의 최근 기록을 생성 순서의 역순으로 반환한다."""
        if limit < 1:
            raise ValueError("operation 조회 수는 양수여야 합니다.")
        operation_dir = self.run_dir(run_id) / "operations"
        if not operation_dir.is_dir():
            return []
        records = [
            record
            for path in operation_dir.glob("*.json")
            if not path.name.endswith(".result.json")
            and (record := self.load_operation(run_id, path.stem)) is not None
            and record.action == action
        ]
        return sorted(records, key=lambda record: (record.created_at, record.request_id), reverse=True)[:limit]

    def save_operation_result(self, run_id: str, request_id: str, result: dict[str, object]) -> str:
        path = self.operation_result_path(run_id, request_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(path, result)
        return path.name

    def load_operation_result(self, record: OperationRecord) -> dict[str, object] | None:
        if not record.result_ref:
            return None
        path = self.operation_result_path(record.run_id, record.request_id)
        if record.result_ref != path.name:
            raise ValueError(f"invalid operation result reference: {record.result_ref}")
        if not path.is_file():
            raise ValueError(f"operation result is missing: {record.request_id}")
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid operation result: {path}: {exc}") from exc
        if not isinstance(result, dict):
            raise ValueError(f"operation result must be an object: {path}")
        return result

    def load_execution_control(self, run_id: str) -> ExecutionControlRecord | None:
        path = self.execution_control_path(run_id)
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return ExecutionControlRecord(**raw)
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"invalid execution control record: {path}: {exc}") from exc

    def save_execution_control(self, record: ExecutionControlRecord) -> None:
        record.updated_at = utc_now()
        path = self.execution_control_path(record.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(path, record.to_dict())

    def load_effort_policy(self, run_id: str, *, archived_chat: bool = False) -> EffortPolicyState:
        path = self.effort_policy_path(run_id, archived_chat=archived_chat)
        if not self.state_path(run_id).is_file():
            raise ValueError(f"unknown run: {run_id}")
        if not path.exists():
            if archived_chat:
                selected = self.load_effort_policy(run_id).selected_mode
                if selected is not None:
                    initial, _ = EffortPolicyState().set_mode(
                        selected, target="planning", expected_revision=0,
                        request_id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"archived-chat:{run_id}")),
                    )
                    return initial
            return EffortPolicyState()
        try:
            return EffortPolicyState.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"invalid effort policy sidecar: {path}: {exc}") from exc

    def initialize_effort_mode(self, state: RunState, mode: str) -> None:
        with self.effort_policy_lock(state.id):
            path = self.effort_policy_path(state.id)
            if self.state_path(state.id).exists() or path.exists():
                raise ValueError("cannot initialize effort mode for an existing run")
            policy, _ = EffortPolicyState().set_mode(mode, target="planning", expected_revision=0, request_id=str(uuid.uuid4()))
            path.parent.mkdir(parents=True, exist_ok=True)
            self._write_json_atomic(path, policy.to_dict())
            self.save(state)

    def prepare_effort_planning(
        self, run_id: str, policy: ResolvedEffortPolicy, *, request_id: str, expected_revision: int, purpose: str,
        archived_chat: bool = False,
    ) -> EffortPlanningBinding:
        with self.effort_policy_lock(run_id):
            current = self.load_effort_policy(run_id, archived_chat=archived_chat)
            updated, binding = current.prepare_planning(policy, request_id=request_id, expected_revision=expected_revision, purpose=purpose)
            if updated is not current:
                self._write_json_atomic(self.effort_policy_path(run_id, archived_chat=archived_chat), updated.to_dict())
            return binding

    def start_effort_planning(self, run_id: str, request_id: str, *, archived_chat: bool = False) -> EffortPlanningBinding:
        with self.effort_policy_lock(run_id):
            current = self.load_effort_policy(run_id, archived_chat=archived_chat)
            updated, binding = current.start_planning(request_id)
            if updated is not current:
                self._write_json_atomic(self.effort_policy_path(run_id, archived_chat=archived_chat), updated.to_dict())
            return binding

    def finish_effort_planning(
        self, run_id: str, request_id: str, *, failed: bool = False, archived_chat: bool = False,
    ) -> EffortPlanningBinding:
        with self.effort_policy_lock(run_id):
            current = self.load_effort_policy(run_id, archived_chat=archived_chat)
            updated, binding = current.finish_planning(request_id, failed=failed)
            if updated is not current:
                self._write_json_atomic(self.effort_policy_path(run_id, archived_chat=archived_chat), updated.to_dict())
            return binding

    def set_effort_mode(
        self, run_id: str, mode: str, *, target: str, expected_revision: int, request_id: str, expected_stage: Stage | None = None
    ) -> EffortPolicyView:
        with self.effort_policy_lock(run_id):
            self._check_effort_mutation_stage(run_id, expected_stage)
            current = self.load_effort_policy(run_id)
            updated, result = current.set_mode(mode, target=target, expected_revision=expected_revision, request_id=request_id)
            if updated is not current:
                self._write_json_atomic(self.effort_policy_path(run_id), updated.to_dict())
            return result

    def cancel_effort_reservation(
        self, run_id: str, *, expected_revision: int, request_id: str, expected_stage: Stage | None = None
    ) -> EffortPolicyView:
        with self.effort_policy_lock(run_id):
            self._check_effort_mutation_stage(run_id, expected_stage)
            current = self.load_effort_policy(run_id)
            updated, result = current.cancel_reservation(expected_revision=expected_revision, request_id=request_id)
            if updated is not current:
                self._write_json_atomic(self.effort_policy_path(run_id), updated.to_dict())
            return result

    def _check_effort_mutation_stage(self, run_id: str, expected_stage: Stage | None) -> None:
        if expected_stage is None:
            return
        state = self.load(run_id)
        if state.archive or state.stage != expected_stage:
            raise ValueError("effort policy target stage changed; refresh the work group before saving")

    def prepare_effort_execution(
        self, run_id: str, policy: ResolvedEffortPolicy, *, execution_request_id: str, expected_revision: int,
        preserve_reservation: bool = False,
    ) -> EffortExecutionBinding:
        with self.effort_policy_lock(run_id):
            current = self.load_effort_policy(run_id)
            run = self.load(run_id)
            if not run.plan_is_approved or run.plan_revision != policy.plan_revision:
                raise ValueError("effort policy snapshot does not match the approved plan revision")
            if preserve_reservation and (run.archive or not (
                run.stage == Stage.EXECUTING or run.stage == Stage.FAILED and run.failed_step == RunStep.AGENT_EXECUTION
            )):
                raise ValueError("saved effort profiles can only recover an existing task execution")
            updated, binding = current.prepare_execution(
                policy, execution_request_id=execution_request_id, expected_revision=expected_revision,
                preserve_reservation=preserve_reservation,
            )
            if updated is not current:
                self._write_json_atomic(self.effort_policy_path(run_id), updated.to_dict())
            return binding

    def start_effort_execution(self, run_id: str, execution_request_id: str) -> EffortExecutionBinding:
        with self.effort_policy_lock(run_id):
            current = self.load_effort_policy(run_id)
            binding = current.binding(execution_request_id)
            if binding is None:
                raise ValueError("unknown effort execution binding")
            run = self.load(run_id)
            if (run.active_policy_id, run.active_execution_request_id) != (binding.policy_id, binding.execution_request_id):
                raise ValueError("RunState does not reference the prepared effort execution binding")
            if not run.plan_is_approved or run.plan_revision != binding.plan_revision:
                raise ValueError("effort execution binding does not match the approved plan revision")
            updated, started = current.start_execution(execution_request_id)
            if updated is not current:
                self._write_json_atomic(self.effort_policy_path(run_id), updated.to_dict())
            return started

    def finish_effort_execution(self, run_id: str, execution_request_id: str) -> EffortExecutionBinding:
        with self.effort_policy_lock(run_id):
            current = self.load_effort_policy(run_id)
            updated, finished = current.finish_execution(execution_request_id)
            if updated is not current:
                self._write_json_atomic(self.effort_policy_path(run_id), updated.to_dict())
            return finished

    def abandon_effort_execution(self, run_id: str, execution_request_id: str) -> EffortExecutionBinding:
        with self.effort_policy_lock(run_id):
            current = self.load_effort_policy(run_id)
            run = self.load(run_id)
            if run.active_execution_request_id == execution_request_id:
                raise ValueError("RunState still references the prepared effort execution binding")
            updated, abandoned = current.abandon_execution(execution_request_id)
            if updated is not current:
                self._write_json_atomic(self.effort_policy_path(run_id), updated.to_dict())
            return abandoned

    @contextmanager
    def effort_policy_lock(self, run_id: str) -> Iterator[None]:
        path = self.effort_policy_lock_path(run_id)
        deadline: float | None = None
        while True:
            lock = self._file_lock(path, run_id, "effort-policy", recover_stale=True, retry_acquire_until=deadline)
            try:
                lock.__enter__()
                break
            except RunLockedError:
                status = self._inspect_lock_path(path, run_id)
                local_writer = status.state == RunLockState.ACTIVE and status.operation == "effort-policy"
                if not (local_writer or status.state == RunLockState.UNLOCKED):
                    raise
                now = time.monotonic()
                if deadline is None:
                    deadline = now + 2
                if now >= deadline:
                    raise
                time.sleep(0.01)
        try:
            yield
        finally:
            lock.__exit__(None, None, None)

    @contextmanager
    def execution_control_lock(self, run_id: str) -> Iterator[None]:
        with self._file_lock(self.execution_control_lock_path(run_id), run_id, "execution-control", recover_stale=True):
            yield

    @contextmanager
    def lock(self, run_id: str, operation: str) -> Iterator[None]:
        with self._file_lock(self.lock_path(run_id), run_id, operation):
            yield

    @contextmanager
    def planning_chat_lock(self, run_id: str, operation: str = "planning-chat") -> Iterator[None]:
        with self._file_lock(self.planning_chat_lock_path(run_id), run_id, operation, recover_stale=True):
            yield

    @contextmanager
    def request_control_lock(self, run_id: str) -> Iterator[None]:
        with self._file_lock(self.run_dir(run_id) / "request-control.lock", run_id, "request-control", recover_stale=True):
            yield

    @contextmanager
    def project_git_lock(self, operation: str) -> Iterator[None]:
        with self._file_lock(self.project_git_lock_path(), "project-git", operation):
            yield

    @contextmanager
    def _file_lock(
        self, path: Path, run_id: str, operation: str, *, recover_stale: bool = False,
        retry_release: bool = False, retry_acquire_until: float | None = None,
    ) -> Iterator[None]:
        path.parent.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        metadata = {
            "token": token,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "operation": operation,
            "acquired_at": utc_now(),
        }
        try:
            descriptor = self._create_lock_file(path, retry_acquire_until)
        except FileExistsError as exc:
            if recover_stale and self._remove_stale_local_lock(path):
                descriptor = self._create_lock_file(path, retry_acquire_until)
            else:
                current = self._read_lock(path)
                details = ", ".join(f"{key}={current.get(key, 'unknown')}" for key in ("operation", "pid", "host", "acquired_at"))
                if run_id == "project-git":
                    raise RunLockedError(f"project Git is already locked ({details}); wait for the current Main operation to finish") from exc
                raise RunLockedError(f"run {run_id} is already locked ({details}); inspect it with 'ai-orchestrator lock status {run_id}'") from exc

        written = False
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(metadata, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            written = True
            yield
        finally:
            for attempt in range(6 if retry_release else 1):
                try:
                    if not written or self._read_lock(path).get("token") == token:
                        path.unlink(missing_ok=True)
                    break
                except OSError as exc:
                    if retry_release and getattr(exc, "winerror", None) in {5, 32, 33} and attempt < 5:
                        time.sleep(0.01 * (attempt + 1))
                        continue
                    raise

    @staticmethod
    def _create_lock_file(path: Path, retry_until: float | None) -> int:
        while True:
            try:
                return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except OSError as exc:
                windows_error = getattr(exc, "winerror", None)
                # The Windows CRT can return EACCES without a winerror.
                retryable = windows_error in {5, 32, 33} or (
                    os.name == "nt" and windows_error is None and exc.errno == errno.EACCES
                )
                if retry_until is None or not retryable:
                    raise
                remaining = retry_until - time.monotonic()
                if remaining <= 0:
                    raise
                time.sleep(min(0.01, remaining))

    def inspect_lock(self, run_id: str) -> RunLockStatus:
        return self._inspect_lock_path(self.lock_path(run_id), run_id)

    def inspect_planning_chat_lock(self, run_id: str) -> RunLockStatus:
        return self._inspect_lock_path(self.planning_chat_lock_path(run_id), run_id)

    def inspect_project_git_lock(self) -> RunLockStatus:
        return self._inspect_lock_path(self.project_git_lock_path(), "project-git")

    def _inspect_lock_path(self, path: Path, run_id: str) -> RunLockStatus:
        if not path.exists():
            return RunLockStatus(run_id=run_id, state=RunLockState.UNLOCKED, reason="no run lock exists")
        metadata = self._read_lock(path)
        if not metadata and not path.exists():
            return RunLockStatus(run_id=run_id, state=RunLockState.UNLOCKED, reason="no run lock exists")
        invalid = self._invalid_lock_fields(metadata)
        if invalid:
            return RunLockStatus(run_id=run_id, state=RunLockState.MALFORMED, reason=f"invalid lock metadata: {', '.join(invalid)}")

        pid = int(metadata["pid"])
        host = str(metadata["host"])
        common = {
            "run_id": run_id,
            "operation": str(metadata["operation"]),
            "pid": pid,
            "host": host,
            "acquired_at": str(metadata["acquired_at"]),
        }
        current_host = socket.gethostname()
        if host != current_host:
            return RunLockStatus(state=RunLockState.UNVERIFIABLE, reason=f"lock belongs to another host: {host}", **common)
        alive = self._pid_is_alive(pid)
        if alive is True:
            return RunLockStatus(state=RunLockState.ACTIVE, reason=f"owner process {pid} is running", **common)
        if alive is False:
            return RunLockStatus(state=RunLockState.STALE, reason=f"owner process {pid} is not running", **common)
        return RunLockStatus(state=RunLockState.UNVERIFIABLE, reason=f"could not verify owner process {pid}", **common)

    def clear_stale_project_git_lock(self, *, expected_operation: str) -> RunLockStatus:
        status = self.inspect_project_git_lock()
        if status.state == RunLockState.UNLOCKED:
            return status
        if status.state != RunLockState.STALE or status.operation != expected_operation:
            raise RunLockedError(f"project Git lock is not safe to clear: {status.state.value} ({status.reason})")
        if not self._remove_stale_local_lock(self.project_git_lock_path(), expected_operation=expected_operation):
            raise RunLockedError("project Git lock changed while it was being inspected")
        return self.inspect_project_git_lock()

    def clear_stale_lock(self, run_id: str) -> RunLockStatus:
        path = self.lock_path(run_id)
        status = self.inspect_lock(run_id)
        if status.state == RunLockState.UNLOCKED:
            return status
        if status.state != RunLockState.STALE:
            raise RunLockedError(f"run {run_id} lock is not safe to clear: {status.state.value} ({status.reason})")
        expected = self._read_lock(path).get("token")
        current_status = self.inspect_lock(run_id)
        current = self._read_lock(path)
        if current_status.state == RunLockState.UNLOCKED and not current:
            return current_status
        if (
            current_status.state != RunLockState.STALE
            or not expected
            or current.get("token") != expected
        ):
            raise RunLockedError(f"run {run_id} lock changed while it was being inspected")
        path.unlink(missing_ok=True)
        return self.inspect_lock(run_id)

    @staticmethod
    def _invalid_lock_fields(metadata: dict[str, object]) -> list[str]:
        invalid: list[str] = []
        for field_name in ("token", "host", "operation", "acquired_at"):
            value = metadata.get(field_name)
            if not isinstance(value, str) or not value.strip():
                invalid.append(field_name)
        pid = metadata.get("pid")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid < 1:
            invalid.append("pid")
        return invalid

    @staticmethod
    def _pid_is_alive(pid: int) -> bool | None:
        if os.name == "nt":
            return StateStore._windows_pid_is_alive(pid)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError as exc:
            if exc.errno == errno.ESRCH:
                return False
            return None
        return True

    def _remove_stale_local_lock(self, path: Path, *, expected_operation: str | None = None) -> bool:
        metadata = self._read_lock(path)
        token = metadata.get("token")
        pid = metadata.get("pid")
        if (
            not isinstance(token, str)
            or not token
            or (expected_operation is not None and metadata.get("operation") != expected_operation)
            or metadata.get("host") != socket.gethostname()
            or isinstance(pid, bool)
            or not isinstance(pid, int)
            or pid < 1
            or self._pid_is_alive(pid) is not False
        ):
            return False
        current = self._read_lock(path)
        if current.get("token") != token or (expected_operation is not None and current.get("operation") != expected_operation):
            return False
        try:
            path.unlink()
        except FileNotFoundError:
            return True
        return True

    @staticmethod
    def _windows_pid_is_alive(pid: int) -> bool | None:
        import ctypes
        from ctypes import wintypes

        process_query_limited_information = 0x1000
        error_access_denied = 5
        error_invalid_parameter = 87
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        error = ctypes.get_last_error()
        if error == error_invalid_parameter:
            return False
        if error == error_access_denied:
            return True
        return None

    @staticmethod
    def _read_lock(path: Path) -> dict[str, object]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def save(self, state: RunState) -> None:
        if self.notification_sync is not None:
            self.notification_sync(state)
        run_dir = self.run_dir(state.id)
        run_dir.mkdir(parents=True, exist_ok=True)
        target = self.state_path(state.id)
        self._write_json_atomic(target, state.to_dict())

    def save_archive_snapshot(self, state: RunState) -> tuple[Path, str]:
        target = self.archive_snapshot_path(state.id)
        payload = {"schema_version": state.schema_version, "run_id": state.id, "state": state.to_dict()}
        expected = json.loads(json.dumps(payload, ensure_ascii=False))
        self._write_json_atomic(target, payload)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        restored = json.loads(target.read_text(encoding="utf-8"))
        if restored != expected:
            raise OSError(f"보관 snapshot 검증에 실패했습니다: {target}")
        return target, digest

    def save_archive_summary(self, run_id: str, content: str) -> Path:
        target = self.archive_summary_path(run_id)
        self._write_text_atomic(target, content.rstrip() + "\n")
        if target.read_text(encoding="utf-8") != content.rstrip() + "\n":
            raise OSError(f"보관 요약 검증에 실패했습니다: {target}")
        return target

    def save_archive_manifest(self, run_id: str, payload: dict[str, object]) -> tuple[Path, str]:
        target = self.archive_manifest_path(run_id)
        self._write_json_atomic(target, payload)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        restored = json.loads(target.read_text(encoding="utf-8"))
        if restored != payload:
            raise OSError(f"보관 manifest 검증에 실패했습니다: {target}")
        return target, digest

    def archive_preserved_files(
        self, run_id: str, *, excluded_operation_request_ids: tuple[str, ...] = ()
    ) -> list[dict[str, object]]:
        run_dir = self.run_dir(run_id).resolve()
        excluded = {
            "state.json",
            "run.lock",
            "planning-chat.lock",
            "execution-control.lock",
            "archive-manifest.json",
        }
        files: list[dict[str, object]] = []
        for path in sorted(run_dir.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(run_dir).as_posix()
            if relative in excluded or any(
                relative == f"operations/{request_id}.json" for request_id in excluded_operation_request_ids
            ):
                continue
            content = path.read_bytes()
            files.append({"path": relative, "size": len(content), "sha256": hashlib.sha256(content).hexdigest()})
        return files

    def save_planning_chat(self, state: RunState) -> None:
        raw = state.to_dict()
        target = self.archived_planning_chat_path(state.id) if state.archive else self.planning_chat_path(state.id)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": PLANNING_CHAT_SIDECAR_SCHEMA_VERSION,
            "planning_messages": raw["planning_messages"],
            "clarification_paths": raw["clarification_paths"],
            "planning_attempts": raw["planning_attempts"],
            "planning_agent_id": raw["planning_agent_id"],
            "planning_provider_id": raw["planning_provider_id"],
            "planning_model": raw["planning_model"],
            "planning_reasoning_effort": raw["planning_reasoning_effort"],
            "planning_profile_source": raw["planning_profile_source"],
            "planning_effort_baseline_reasoning": raw["planning_effort_baseline_reasoning"],
            "planning_claude_session_id": raw["planning_claude_session_id"],
            "planning_follow_up_requests": raw["planning_follow_up_requests"],
            "planning_conversation_revision": raw["planning_conversation_revision"],
            "planning_applied_conversation_revision": raw["planning_applied_conversation_revision"],
            "planning_apply_requests": raw["planning_apply_requests"],
            "direction_change_requests": raw["direction_change_requests"],
            "events": [event for event in raw["events"] if event["kind"] in {"planning", "planning_progress"}],
            "updated_at": raw["updated_at"],
        }
        self._write_json_atomic(target, payload)

    @staticmethod
    def _write_json_atomic(target: Path, payload: dict[str, object]) -> None:
        content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(content, encoding="utf-8")
        except OSError:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass  # Preserve the original write error.
            raise
        delays = (0.05, 0.1, 0.2, 0.4, 0.8)
        for attempt in range(len(delays) + 1):
            try:
                temporary.replace(target)
                return
            except OSError as exc:
                if getattr(exc, "winerror", None) in {5, 32, 33} and attempt < len(delays):
                    time.sleep(delays[attempt])
                    continue
                raise OSError(f"상태 파일 저장 실패: {target}. 기존 파일을 삭제하지 않았습니다. 저장하려던 내용은 임시 파일에 보존했습니다: {temporary}. 원인: {exc}") from exc

    @staticmethod
    def _write_text_atomic(target: Path, content: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporary.write_text(content, encoding="utf-8")
        except OSError:
            temporary.unlink(missing_ok=True)
            raise
        delays = (0.05, 0.1, 0.2, 0.4, 0.8)
        for attempt in range(len(delays) + 1):
            try:
                temporary.replace(target)
                return
            except OSError as exc:
                if getattr(exc, "winerror", None) in {5, 32, 33} and attempt < len(delays):
                    time.sleep(delays[attempt])
                    continue
                raise OSError(
                    f"보관 요약 저장 실패: {target}. 기존 파일을 삭제하지 않았습니다. "
                    f"저장하려던 내용은 임시 파일에 보존했습니다: {temporary}. 원인: {exc}"
                ) from exc

    def load(self, run_id: str) -> RunState:
        path = self.state_path(run_id)
        try:
            state = RunState.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except FileNotFoundError as exc:
            raise ValueError(f"unknown run: {run_id}") from exc
        self._apply_planning_chat(state)
        return state

    def _apply_planning_chat(self, state: RunState) -> None:
        path = self.planning_chat_path(state.id)
        if state.archive and self.archived_planning_chat_path(state.id).exists():
            path = self.archived_planning_chat_path(state.id)
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PlanningChatSidecarError(f"invalid planning chat sidecar: {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise PlanningChatSidecarError(f"planning chat sidecar must be an object: {path}")
        if raw.get("schema_version") != PLANNING_CHAT_SIDECAR_SCHEMA_VERSION:
            raise PlanningChatSidecarError(f"unsupported planning chat sidecar schema: {raw.get('schema_version')}")
        try:
            sidecar_revision = int(raw.get("planning_conversation_revision", len(raw.get("planning_messages", []))))
            if sidecar_revision < state.planning_conversation_revision:
                return
            state.planning_messages = [
                PlanningMessage(role=PlanningMessageRole(item["role"]), text=str(item["text"]), at=str(item.get("at", "")))
                for item in raw.get("planning_messages", [])
            ]
            state.clarification_paths = [str(item) for item in raw.get("clarification_paths", [])]
            state.planning_attempts = int(raw.get("planning_attempts", state.planning_attempts))
            for name in ("planning_agent_id", "planning_provider_id", "planning_model", "planning_reasoning_effort", "planning_claude_session_id"):
                setattr(state, name, str(raw.get(name, getattr(state, name))))
            state.planning_profile_source = ProfileSource(raw.get("planning_profile_source", state.planning_profile_source))
            baseline_reasoning = raw.get(
                "planning_effort_baseline_reasoning", state.planning_effort_baseline_reasoning
            )
            if baseline_reasoning is not None and not isinstance(baseline_reasoning, str):
                raise ValueError("planning effort baseline reasoning must be a string or null")
            state.planning_effort_baseline_reasoning = baseline_reasoning
            state.planning_follow_up_requests = [str(item) for item in raw.get("planning_follow_up_requests", []) if str(item).strip()]
            state.planning_conversation_revision = int(
                raw.get("planning_conversation_revision", len(state.planning_messages))
            )
            state.planning_applied_conversation_revision = int(raw.get("planning_applied_conversation_revision", 0))
            state.planning_apply_requests = [
                PlanningApplyRequest(
                    request_id=str(item["request_id"]),
                    conversation_revision=int(item.get("conversation_revision", 0)),
                    plan_revision=int(item.get("plan_revision", 0)),
                    context_snapshot=str(item.get("context_snapshot", "")),
                    answer_message=str(item.get("answer_message", "")),
                    answer_conversation_revision=int(item.get("answer_conversation_revision", 0)),
                    tech_stack_revision=int(item.get("tech_stack_revision", 0)),
                    status=PlanningApplyStatus(item.get("status", PlanningApplyStatus.QUEUED.value)),
                    created_at=str(item.get("created_at", "")),
                    completed_at=str(item.get("completed_at", "")),
                    added_tasks=int(item.get("added_tasks", 0)),
                    updated_tasks=int(item.get("updated_tasks", 0)),
                    excluded_tasks=int(item.get("excluded_tasks", 0)),
                    unchanged_tasks=int(item.get("unchanged_tasks", 0)),
                    error_code=str(item.get("error_code", "")),
                    error=str(item.get("error", "")),
                )
                for item in raw.get("planning_apply_requests", [])
                if isinstance(item, dict) and str(item.get("request_id", "")).strip()
            ]
            state.direction_change_requests = [
                DirectionChangeRequest(
                    request_id=str(item["request_id"]), text=str(item["text"]),
                    task_id=str(item.get("task_id", "")), task_title=str(item.get("task_title", "")),
                    status=DirectionChangeStatus(item.get("status", DirectionChangeStatus.RECEIVED.value)),
                    next_step=str(item.get("next_step", "")), preview_id=str(item.get("preview_id", "")),
                    error=str(item.get("error", "")), created_at=str(item.get("created_at", "")),
                    updated_at=str(item.get("updated_at", "")),
                )
                for item in raw.get("direction_change_requests", [])
                if isinstance(item, dict) and str(item.get("request_id", "")).strip()
            ]
            known_events = {(event.at, event.kind, event.message) for event in state.events}
            for item in raw.get("events", []):
                event = Event(at=str(item["at"]), kind=str(item["kind"]), message=str(item["message"]))
                identity = (event.at, event.kind, event.message)
                if identity not in known_events:
                    state.events.append(event)
                    known_events.add(identity)
            state.events.sort(key=lambda event: event.at)
            state.updated_at = max(state.updated_at, str(raw.get("updated_at", state.updated_at)))
        except (KeyError, TypeError, ValueError) as exc:
            raise PlanningChatSidecarError(f"invalid planning chat sidecar payload: {path}: {exc}") from exc

    def list_runs(self) -> list[RunState]:
        runs_dir = self.root / "runs"
        if not runs_dir.exists():
            return []
        states = [self.load(path.parent.name) for path in runs_dir.glob("*/state.json")]
        return sorted(states, key=lambda item: item.created_at, reverse=True)

    def list_run_summaries(self, scope: str = "all") -> list[RunSummary]:
        if scope not in {"active", "archived", "all"}:
            raise ValueError(f"unsupported run list scope: {scope}")
        runs_dir = self.root / "runs"
        if not runs_dir.exists():
            return []
        summaries = [RunSummary.from_dict(json.loads(path.read_text(encoding="utf-8"))) for path in runs_dir.glob("*/state.json")]
        if scope == "active":
            summaries = [summary for summary in summaries if not summary.archived]
        elif scope == "archived":
            summaries = [summary for summary in summaries if summary.archived]
        return sorted(summaries, key=lambda item: item.archived_at if item.archived else item.created_at, reverse=True)

    def delete(self, run_id: str) -> None:
        runs_root = (self.root / "runs").resolve()
        target = self.run_dir(run_id).resolve()
        if target.parent != runs_root:
            raise ValueError(f"invalid run id: {run_id}")
        with self.effort_policy_lock(run_id):
            if not target.is_dir():
                raise ValueError(f"unknown run: {run_id}")
            shutil.rmtree(target)
