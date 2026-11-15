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
from pathlib import Path
from typing import Callable, Iterator

from .usage import UsageObservation, UsageRecord

from .persistence.atomic import write_json_atomic, write_text_atomic
from .persistence.errors import PlanningCacheError, PlanningChatSidecarError, RunLockedError
from .persistence.planning import (
    PLANNING_RESULT_CACHE_SCHEMA_VERSION, PLANNING_CHAT_SIDECAR_SCHEMA_VERSION,
    PlanningResultCache, apply_planning_chat, planning_chat_payload,
)
from .persistence.notifications import NotificationEventRepository
from .persistence.usage import UsageLedger

from .models import (
    EffortExecutionBinding,
    EffortProfileSnapshot,
    EffortPlanningBinding,
    EffortPolicyState,
    EffortPolicyView,
    ExecutionControlRecord,
    OperationRecord,
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

ARCHIVE_MANIFEST_SCHEMA_VERSION = 1


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
            if "quota_fallback" in item:
                selected = EffortProfileSnapshot.from_dict(item["quota_fallback"])
                if ("applied_policy_id" not in item or selected.profile_source not in {ProfileSource.MODE, ProfileSource.ROUTING}
                        or not isinstance(item.get("quota_exhausted_provider"), str)
                        or not isinstance(item.get("quota_model_selection_reason"), str)
                        or "quota_baseline_reasoning" not in item
                        or item["quota_baseline_reasoning"] is not None and not isinstance(item["quota_baseline_reasoning"], str)
                        or item["selection"] != {"agent_id": selected.agent_id, "model": selected.model,
                                                 "reasoning_effort": selected.reasoning_effort}):
                    raise ValueError(f"invalid quota fallback profile: {path}")
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

    def _notification_event_repository(self) -> NotificationEventRepository:
        return NotificationEventRepository(self._validate_effort_run_id, self.run_dir, self._write_json_atomic)

    def save_notification_event(self, event: UserNotificationEvent) -> None:
        return self._notification_event_repository().save(event)

    def load_notification_events(self, run_id: str) -> list[UserNotificationEvent]:
        return self._notification_event_repository().load(run_id)

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

    def _usage_ledger(self, run_id: str) -> UsageLedger:
        return UsageLedger(
            directory=lambda: self.usage_dir(run_id), read_state=lambda: self.load(run_id),
            acquire_lock=lambda: self.usage_lock(run_id), write_json=self._write_json_atomic,
        )

    def begin_usage(self, run_id: str, record: UsageRecord) -> None:
        return self._usage_ledger(run_id).begin(record)

    def observe_usage(self, run_id: str, invocation_id: str, observation: UsageObservation) -> None:
        return self._usage_ledger(run_id).observe(invocation_id, observation)

    def finish_usage(self, run_id: str, invocation_id: str, outcome: str, *, structured: bool) -> None:
        return self._usage_ledger(run_id).finish(invocation_id, outcome, structured=structured)

    def update_usage_model(self, run_id: str, invocation_id: str, model: str) -> None:
        return self._usage_ledger(run_id).update_model(invocation_id, model)

    def usage_snapshot(self, run_id: str, *, execution_request_id: str = "", cursor: str = "", limit: int = 50) -> dict[str, object]:
        return self._usage_ledger(run_id).snapshot(execution_request_id=execution_request_id, cursor=cursor, limit=limit)

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
        return PlanningResultCache(self.root / "planning-cache").path(key)

    def load_planning_result(self, key: str) -> str | None:
        return PlanningResultCache(self.root / "planning-cache").load(key)

    def save_planning_result(self, key: str, output: str) -> Path:
        return PlanningResultCache(self.root / "planning-cache").save(key, output)

    def load_result_artifact(self, run_id: str) -> dict[str, object] | None:
        path = self.run_dir(run_id) / "result-artifact.json"
        if not path.exists():
            return None
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("결과물 기록을 확인하지 못했습니다.")
        return raw

    def save_result_artifact(self, run_id: str, payload: dict[str, object]) -> None:
        self._write_json_atomic(self.run_dir(run_id) / "result-artifact.json", payload)

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

    def initialize_effort_mode(self, state: RunState, mode: str, *, recover_unpublished: bool = False) -> None:
        with self.effort_policy_lock(state.id):
            path = self.effort_policy_path(state.id)
            if self.state_path(state.id).exists() or (path.exists() and not recover_unpublished):
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
        payload = planning_chat_payload(state)
        target = self.archived_planning_chat_path(state.id) if state.archive else self.planning_chat_path(state.id)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._write_json_atomic(target, payload)

    _write_json_atomic = staticmethod(write_json_atomic)

    _write_text_atomic = staticmethod(write_text_atomic)

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
        apply_planning_chat(path, state)

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
