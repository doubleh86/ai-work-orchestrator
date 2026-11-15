from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..models import (
    DirectionChangeRequest, DirectionChangeStatus, Event, PlanningApplyRequest, PlanningApplyStatus,
    PlanningMessage, PlanningMessageRole, ProfileSource, RunState,
)
from .errors import PlanningCacheError, PlanningChatSidecarError

PLANNING_RESULT_CACHE_SCHEMA_VERSION = 1
PLANNING_CHAT_SIDECAR_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class PlanningResultCache:
    directory: Path

    def path(self, key: str) -> Path:
        if len(key) != 64 or any(character not in "0123456789abcdef" for character in key):
            raise PlanningCacheError(f"invalid planning cache key: {key}")
        return self.directory / f"{key}.json"

    def load(self, key: str) -> str | None:
        path = self.path(key)
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

    def save(self, key: str, output: str) -> Path:
        if not isinstance(output, str) or not output.strip():
            raise PlanningCacheError("planning result cache output must be a non-empty string")
        path = self.path(key)
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


def planning_chat_payload(state: RunState) -> dict[str, object]:
    raw = state.to_dict()
    return {
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


def apply_planning_chat(path: Path, state: RunState) -> None:
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
