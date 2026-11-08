from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from .code_style import CodeStyleSnapshot, CodeStyleTaskEvidence
from .progress import ProgressObservation


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _operation_created_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


CURRENT_STATE_SCHEMA_VERSION = 39
LEGACY_STATE_SCHEMA_VERSION = 1


class Stage(StrEnum):
    RECEIVED = "received"
    REVIEWED = "reviewed"
    NEEDS_CLARIFICATION = "needs_clarification"
    PLANNED = "planned"
    EXECUTING = "executing"
    READY_TO_MERGE = "ready_to_merge"
    VERIFIED = "verified"
    WORK_BRANCH_PUSHED = "work_branch_pushed"
    MERGED = "merged"
    PUSHED = "pushed"
    DEPLOYED = "deployed"
    FAILED = "failed"


class RunStep(StrEnum):
    PLANNING = "planning"
    TASK_PREPARATION = "task_preparation"
    AGENT_EXECUTION = "agent_execution"
    MANUAL_COMPLETION = "manual_completion"
    MERGE = "merge"
    VERIFY = "verify"
    PUSH = "push"
    DEPLOY = "deploy"


class PlanningMessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class PlanningMode(StrEnum):
    DIRECTED = "directed"
    AUTO = "auto"


class EffortMode(StrEnum):
    ECONOMY = "economy"
    BALANCED = "balanced"
    FOCUSED = "focused"


class ProfileSource(StrEnum):
    MANUAL = "manual"
    MODE = "mode"
    ROUTING = "routing"
    LEGACY = "legacy"


def _effort_baseline(value: object) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError("effort baseline reasoning must be a string or null")
    return value


def _review_policy_added(value: object) -> bool:
    if type(value) is not bool:
        raise ValueError("review policy added must be a boolean")
    return value


def _model_escalation_index(value: object) -> int:
    if type(value) is not int or value < -1:
        raise ValueError("model escalation result index must be an integer >= -1")
    return value


EFFORT_POLICY_SCHEMA_VERSION = 2


class EffortPolicyRevisionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class EffortProfileSnapshot:
    agent_id: str
    provider_id: str
    model: str
    reasoning_effort: str
    profile_source: ProfileSource

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: object) -> EffortProfileSnapshot:
        if not isinstance(raw, dict) or raw.keys() != {"agent_id", "provider_id", "model", "reasoning_effort", "profile_source"}:
            raise ValueError("invalid effort policy profile snapshot")
        if not all(isinstance(raw[key], str) for key in ("agent_id", "provider_id", "model", "reasoning_effort")):
            raise ValueError("invalid effort policy profile value")
        if not raw["agent_id"].strip() or not raw["provider_id"].strip():
            raise ValueError("effort policy profile requires agent and provider")
        if not isinstance(raw["profile_source"], str):
            raise ValueError("invalid effort profile source")
        return cls(raw["agent_id"], raw["provider_id"], raw["model"], raw["reasoning_effort"], ProfileSource(raw["profile_source"]))


@dataclass(frozen=True, slots=True)
class EffortReviewSnapshot:
    task_id: str
    required: bool
    optional: bool
    reason: str
    reviewer_agent_id: str
    policy_added: bool
    replaces_existing_review: bool
    reviewer_provider_id: str = ""
    reviewer_model: str = ""

    def to_dict(self, *, policy_version: int = 2) -> dict[str, object]:
        payload = asdict(self)
        if policy_version == 1:
            payload.pop("reviewer_provider_id")
            payload.pop("reviewer_model")
        return payload

    @classmethod
    def from_dict(cls, raw: object, *, policy_version: int = 2) -> EffortReviewSnapshot:
        expected = {"task_id", "required", "optional", "reason", "reviewer_agent_id", "policy_added", "replaces_existing_review"}
        if policy_version >= 2:
            expected.update({"reviewer_provider_id", "reviewer_model"})
        if not isinstance(raw, dict) or raw.keys() != expected:
            raise ValueError("invalid effort review snapshot")
        if not all(type(raw[key]) is bool for key in ("required", "optional", "policy_added", "replaces_existing_review")):
            raise ValueError("invalid effort review flags")
        if not all(isinstance(raw[key], str) for key in ("task_id", "reason", "reviewer_agent_id")):
            raise ValueError("invalid effort review value")
        if policy_version >= 2:
            if not all(isinstance(raw[key], str) for key in ("reviewer_provider_id", "reviewer_model")):
                raise ValueError("invalid effort reviewer profile")
            if bool(raw["reviewer_agent_id"]) != bool(raw["reviewer_provider_id"]):
                raise ValueError("effort reviewer provider must match reviewer selection")
        if not raw["task_id"].strip() or not raw["reason"].strip() or (raw["required"] and raw["optional"]):
            raise ValueError("invalid effort review decision")
        return cls(**raw)


@dataclass(frozen=True, slots=True)
class ResolvedEffortPolicy:
    policy_id: str
    policy_version: int
    mode: EffortMode
    scope: str
    plan_revision: int
    planning_profile: EffortProfileSnapshot | None
    task_profiles: tuple[tuple[str, EffortProfileSnapshot], ...]
    review_decisions: tuple[EffortReviewSnapshot, ...]
    manual_exception_ids: tuple[str, ...]
    unsupported_effects: tuple[str, ...]
    resolved_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "mode": self.mode.value,
            "scope": self.scope,
            "plan_revision": self.plan_revision,
            "planning_profile": self.planning_profile.to_dict() if self.planning_profile is not None else None,
            "task_profiles": {task_id: profile.to_dict() for task_id, profile in self.task_profiles},
            "review_decisions": [decision.to_dict(policy_version=self.policy_version) for decision in self.review_decisions],
            "manual_exception_ids": list(self.manual_exception_ids),
            "unsupported_effects": list(self.unsupported_effects),
            "resolved_at": self.resolved_at,
        }

    @classmethod
    def from_dict(cls, raw: object) -> ResolvedEffortPolicy:
        expected = {
            "policy_id", "policy_version", "mode", "scope", "plan_revision", "planning_profile", "task_profiles",
            "review_decisions", "manual_exception_ids", "unsupported_effects", "resolved_at",
        }
        if not isinstance(raw, dict) or raw.keys() != expected:
            raise ValueError("invalid resolved effort policy")
        policy_id = _effort_request_id(raw["policy_id"])
        if type(raw["policy_version"]) is not int or raw["policy_version"] not in {1, 2, 3}:
            raise ValueError("unsupported effort policy version")
        policy_version = raw["policy_version"]
        mode = _effort_mode(raw["mode"])
        if mode is None or not isinstance(raw["scope"], str) or raw["scope"] not in {"planning", "execution"}:
            raise ValueError("invalid resolved effort policy mode or scope")
        plan_revision = _effort_revision(raw["plan_revision"])
        planning = EffortProfileSnapshot.from_dict(raw["planning_profile"]) if raw["planning_profile"] is not None else None
        profiles = raw["task_profiles"]
        reviews = raw["review_decisions"]
        if not isinstance(profiles, dict) or not all(isinstance(key, str) and key.strip() for key in profiles):
            raise ValueError("invalid effort task profiles")
        if not isinstance(reviews, list):
            raise ValueError("invalid effort review decisions")
        parsed_reviews = tuple(EffortReviewSnapshot.from_dict(item, policy_version=policy_version) for item in reviews)
        if len({item.task_id for item in parsed_reviews}) != len(parsed_reviews):
            raise ValueError("duplicate effort review task")
        exceptions = _effort_string_list(raw["manual_exception_ids"], "manual exception IDs")
        unsupported = _effort_string_list(raw["unsupported_effects"], "unsupported effects")
        resolved_at = _effort_timestamp(raw["resolved_at"])
        return cls(
            policy_id, policy_version, mode, raw["scope"], plan_revision, planning,
            tuple((key, EffortProfileSnapshot.from_dict(value)) for key, value in profiles.items()),
            parsed_reviews, exceptions, unsupported, resolved_at,
        )


@dataclass(frozen=True, slots=True)
class EffortExecutionBinding:
    execution_request_id: str
    policy_id: str
    policy_revision: int
    plan_revision: int
    reservation_request_id: str
    created_at: str
    updated_at: str
    status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "plan_revision": self.plan_revision,
            "reservation_request_id": self.reservation_request_id or None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, request_id: object, raw: object) -> EffortExecutionBinding:
        if not isinstance(raw, dict) or raw.keys() != {
            "policy_id", "policy_revision", "plan_revision", "reservation_request_id", "created_at", "updated_at", "status"
        }:
            raise ValueError("invalid effort execution binding")
        normalized_request_id = _effort_request_id(request_id)
        policy_id = _effort_request_id(raw["policy_id"])
        policy_revision = _effort_revision(raw["policy_revision"])
        revision = _effort_revision(raw["plan_revision"])
        reservation = _effort_request_id(raw["reservation_request_id"]) if raw["reservation_request_id"] is not None else ""
        created_at = _effort_timestamp(raw["created_at"])
        updated_at = _effort_timestamp(raw["updated_at"])
        if not isinstance(raw["status"], str) or raw["status"] not in {"prepared", "started", "finished", "abandoned"}:
            raise ValueError("invalid effort execution binding status")
        return cls(normalized_request_id, policy_id, policy_revision, revision, reservation, created_at, updated_at, raw["status"])


@dataclass(frozen=True, slots=True)
class EffortPlanningBinding:
    planning_request_id: str
    policy_id: str
    policy_revision: int
    plan_revision: int
    purpose: str
    created_at: str
    updated_at: str
    started_at: str = ""
    status: str = "prepared"

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload.pop("planning_request_id")
        return payload

    @classmethod
    def from_dict(cls, request_id: object, raw: object) -> EffortPlanningBinding:
        expected = {"policy_id", "policy_revision", "plan_revision", "purpose", "created_at", "updated_at", "started_at", "status"}
        if not isinstance(raw, dict) or raw.keys() != expected:
            raise ValueError("invalid effort Planning binding")
        if not isinstance(raw["purpose"], str) or raw["purpose"] not in {"planning", "chat", "planning_preview", "recovery_planning"}:
            raise ValueError("invalid effort Planning purpose")
        if not isinstance(raw["status"], str) or raw["status"] not in {"prepared", "started", "finished", "failed"}:
            raise ValueError("invalid effort Planning status")
        started = _effort_timestamp(raw["started_at"]) if raw["started_at"] else ""
        if not isinstance(raw["started_at"], str) or (raw["status"] == "prepared" and started) or (raw["status"] == "started" and not started):
            raise ValueError("invalid effort Planning start record")
        return cls(
            _effort_request_id(request_id), _effort_request_id(raw["policy_id"]), _effort_revision(raw["policy_revision"]),
            _effort_revision(raw["plan_revision"]), raw["purpose"], _effort_timestamp(raw["created_at"]),
            _effort_timestamp(raw["updated_at"]), started, raw["status"],
        )


@dataclass(frozen=True, slots=True)
class EffortPolicyView:
    revision: int = 0
    selected_mode: EffortMode | None = None
    pending_execution_mode: EffortMode | None = None
    pending_request_id: str = ""


@dataclass(frozen=True, slots=True)
class EffortPolicyMutationReceipt:
    request_id: str
    action: str
    mode: EffortMode | None
    expected_revision: int
    result: EffortPolicyView

    def to_dict(self) -> dict[str, object]:
        return {
            "request_id": self.request_id,
            "action": self.action,
            "mode": self.mode.value if self.mode is not None else None,
            "expected_revision": self.expected_revision,
            "result": {
                "revision": self.result.revision,
                "selected_mode": self.result.selected_mode.value if self.result.selected_mode is not None else None,
                "pending_execution_mode": self.result.pending_execution_mode.value if self.result.pending_execution_mode is not None else None,
                "pending_request_id": self.result.pending_request_id or None,
            },
        }

    @classmethod
    def from_dict(cls, raw: object) -> EffortPolicyMutationReceipt:
        if not isinstance(raw, dict):
            raise ValueError("effort policy mutation receipt must be an object")
        request_id = _effort_request_id(raw.get("request_id"))
        action = raw.get("action")
        if not isinstance(action, str) or action not in {"select", "reserve", "cancel", "consume"}:
            raise ValueError("invalid effort policy mutation action")
        mode = _effort_mode(raw.get("mode"))
        if (action == "cancel") != (mode is None):
            raise ValueError("invalid effort policy mutation mode")
        expected_revision = _effort_revision(raw.get("expected_revision"))
        result_raw = raw.get("result")
        if not isinstance(result_raw, dict) or result_raw.keys() != {
            "revision", "selected_mode", "pending_execution_mode", "pending_request_id"
        }:
            raise ValueError("effort policy mutation result must be an object")
        result = _effort_view_from_dict(result_raw)
        if result.revision != expected_revision + 1:
            raise ValueError("effort policy mutation result revision mismatch")
        return cls(request_id, action, mode, expected_revision, result)


@dataclass(frozen=True, slots=True)
class EffortPolicyState:
    revision: int = 0
    selected_mode: EffortMode | None = None
    pending_execution_mode: EffortMode | None = None
    pending_request_id: str = ""
    mutation_receipts: tuple[EffortPolicyMutationReceipt, ...] = ()
    prepared_policies: tuple[ResolvedEffortPolicy, ...] = ()
    execution_bindings: tuple[EffortExecutionBinding, ...] = ()
    planning_bindings: tuple[EffortPlanningBinding, ...] = ()

    def view(self) -> EffortPolicyView:
        return EffortPolicyView(self.revision, self.selected_mode, self.pending_execution_mode, self.pending_request_id)

    def recovery_mode(self, plan_revision: int) -> EffortMode | None:
        for binding in reversed(self.execution_bindings):
            if binding.status == "finished" and binding.plan_revision == plan_revision:
                policy = self.policy(binding.policy_id)
                if policy is None:
                    raise ValueError("completed effort execution policy snapshot is missing")
                return policy.mode
        return self.selected_mode

    def set_mode(self, mode: EffortMode | str, *, target: str, expected_revision: int, request_id: str) -> tuple[EffortPolicyState, EffortPolicyView]:
        selected = _effort_mode(mode)
        if selected is None or not isinstance(target, str) or target not in {"planning", "next_execution"}:
            raise ValueError("invalid effort policy selection")
        action = "select" if target == "planning" else "reserve"
        normalized_request_id = _effort_request_id(request_id)
        revision = _effort_revision(expected_revision)
        replay = self._replay(normalized_request_id, action, selected, revision)
        if replay is not None:
            return self, replay
        self._check_revision(revision)
        if action == "select":
            updated = replace(self, revision=self.revision + 1, selected_mode=selected)
        else:
            updated = replace(
                self, revision=self.revision + 1, pending_execution_mode=selected, pending_request_id=normalized_request_id
            )
        result = updated.view()
        receipt = EffortPolicyMutationReceipt(normalized_request_id, action, selected, revision, result)
        return replace(updated, mutation_receipts=(*self.mutation_receipts, receipt)), result

    def cancel_reservation(self, *, expected_revision: int, request_id: str) -> tuple[EffortPolicyState, EffortPolicyView]:
        normalized_request_id = _effort_request_id(request_id)
        revision = _effort_revision(expected_revision)
        replay = self._replay(normalized_request_id, "cancel", None, revision)
        if replay is not None:
            return self, replay
        self._check_revision(revision)
        if self.pending_execution_mode is None:
            raise ValueError("no effort mode reservation to cancel")
        updated = replace(self, revision=self.revision + 1, pending_execution_mode=None, pending_request_id="")
        result = updated.view()
        receipt = EffortPolicyMutationReceipt(normalized_request_id, "cancel", None, revision, result)
        return replace(updated, mutation_receipts=(*self.mutation_receipts, receipt)), result

    def prepare_execution(
        self, policy: ResolvedEffortPolicy, *, execution_request_id: str, expected_revision: int, preserve_reservation: bool = False
    ) -> tuple[EffortPolicyState, EffortExecutionBinding]:
        request_id = _effort_request_id(execution_request_id)
        validated = ResolvedEffortPolicy.from_dict(policy.to_dict())
        if validated.scope != "execution":
            raise ValueError("execution binding requires an execution policy")
        existing = self.binding(request_id)
        if existing is not None:
            saved = self.policy(existing.policy_id)
            if saved == validated and existing.plan_revision == validated.plan_revision and existing.policy_revision == expected_revision:
                return self, existing
            raise ValueError("execution requestId was used for a different effort policy binding")
        self._check_revision(_effort_revision(expected_revision))
        if any(item.request_id == request_id for item in self.mutation_receipts):
            raise ValueError("execution requestId conflicts with an effort policy mutation")
        if any(item.planning_request_id == request_id for item in self.planning_bindings):
            raise ValueError("execution requestId conflicts with a Planning request")
        active = [item for item in self.execution_bindings if item.status in {"prepared", "started"}]
        if active:
            raise ValueError(f"unfinished effort execution binding: {active[0].execution_request_id}")
        chosen = self.recovery_mode(validated.plan_revision) if preserve_reservation else self.pending_execution_mode or self.selected_mode
        if chosen is None or validated.mode != chosen:
            raise ValueError("effort policy snapshot does not match selected or reserved mode")
        if self.policy(validated.policy_id) is not None:
            raise ValueError("effort policy ID is already prepared")
        now = utc_now()
        binding = EffortExecutionBinding(
            request_id, validated.policy_id, self.revision, validated.plan_revision,
            "" if preserve_reservation else self.pending_request_id, now, now, "prepared"
        )
        return replace(
            self, prepared_policies=(*self.prepared_policies, validated), execution_bindings=(*self.execution_bindings, binding)
        ), binding

    def start_execution(self, request_id: str) -> tuple[EffortPolicyState, EffortExecutionBinding]:
        binding = self._require_binding(request_id)
        if binding.status == "started":
            return self, binding
        if binding.status != "prepared":
            raise ValueError(f"effort execution binding is {binding.status}, not prepared")
        updated = self
        if binding.reservation_request_id and binding.reservation_request_id == self.pending_request_id:
            policy = self.policy(binding.policy_id)
            if policy is None:
                raise ValueError("execution binding policy snapshot is missing")
            updated = self._consume_reservation(binding.execution_request_id, policy.mode)
        started = replace(binding, status="started", updated_at=utc_now())
        return updated._replace_binding(started), started

    def finish_execution(self, request_id: str) -> tuple[EffortPolicyState, EffortExecutionBinding]:
        binding = self._require_binding(request_id)
        if binding.status == "finished":
            return self, binding
        if binding.status != "started":
            raise ValueError(f"effort execution binding is {binding.status}, not started")
        finished = replace(binding, status="finished", updated_at=utc_now())
        return self._replace_binding(finished), finished

    def abandon_execution(self, request_id: str) -> tuple[EffortPolicyState, EffortExecutionBinding]:
        binding = self._require_binding(request_id)
        if binding.status == "abandoned":
            return self, binding
        if binding.status != "prepared":
            raise ValueError(f"effort execution binding is {binding.status}, not prepared")
        abandoned = replace(binding, status="abandoned", updated_at=utc_now())
        return self._replace_binding(abandoned), abandoned

    def policy(self, policy_id: str) -> ResolvedEffortPolicy | None:
        return next((item for item in self.prepared_policies if item.policy_id == policy_id), None)

    def binding(self, request_id: str) -> EffortExecutionBinding | None:
        normalized = _effort_request_id(request_id)
        return next((item for item in self.execution_bindings if item.execution_request_id == normalized), None)

    def _require_binding(self, request_id: str) -> EffortExecutionBinding:
        binding = self.binding(_effort_request_id(request_id))
        if binding is None:
            raise ValueError("unknown effort execution binding")
        return binding

    def _replace_binding(self, binding: EffortExecutionBinding) -> EffortPolicyState:
        return replace(self, execution_bindings=tuple(
            binding if item.execution_request_id == binding.execution_request_id else item for item in self.execution_bindings
        ))

    def _consume_reservation(self, request_id: str, mode: EffortMode) -> EffortPolicyState:
        if self.pending_execution_mode != mode or not self.pending_request_id:
            raise ValueError("effort reservation no longer matches the prepared policy")
        if any(item.request_id == request_id for item in self.mutation_receipts):
            raise ValueError("execution requestId conflicts with an effort policy mutation")
        updated = replace(self, revision=self.revision + 1, pending_execution_mode=None, pending_request_id="")
        receipt = EffortPolicyMutationReceipt(request_id, "consume", mode, self.revision, updated.view())
        return replace(updated, mutation_receipts=(*self.mutation_receipts, receipt))

    def prepare_planning(
        self, policy: ResolvedEffortPolicy, *, request_id: str, expected_revision: int, purpose: str
    ) -> tuple[EffortPolicyState, EffortPlanningBinding]:
        normalized_id = _effort_request_id(request_id)
        validated = ResolvedEffortPolicy.from_dict(policy.to_dict())
        if validated.scope != "planning" or validated.planning_profile is None or validated.task_profiles or validated.review_decisions:
            raise ValueError("Planning binding requires a Planning-only policy")
        if purpose not in {"planning", "chat", "planning_preview", "recovery_planning"}:
            raise ValueError("invalid effort Planning purpose")
        existing = self.planning_binding(normalized_id)
        if existing is not None:
            if (self.policy(existing.policy_id), existing.policy_revision, existing.purpose) == (validated, expected_revision, purpose):
                return self, existing
            raise ValueError("Planning requestId was used for a different effort policy")
        self._check_revision(_effort_revision(expected_revision))
        if any(item.request_id == normalized_id for item in self.mutation_receipts) or self.binding(normalized_id) is not None:
            raise ValueError("Planning requestId conflicts with an existing effort request")
        if self.selected_mode is None or validated.mode != self.selected_mode:
            raise ValueError("Planning policy snapshot does not match the selected mode")
        if self.policy(validated.policy_id) is not None:
            raise ValueError("effort policy ID is already prepared")
        now = utc_now()
        binding = EffortPlanningBinding(normalized_id, validated.policy_id, self.revision, validated.plan_revision, purpose, now, now)
        return replace(
            self, prepared_policies=(*self.prepared_policies, validated), planning_bindings=(*self.planning_bindings, binding)
        ), binding

    def planning_binding(self, request_id: str) -> EffortPlanningBinding | None:
        normalized_id = _effort_request_id(request_id)
        return next((item for item in self.planning_bindings if item.planning_request_id == normalized_id), None)

    def start_planning(self, request_id: str) -> tuple[EffortPolicyState, EffortPlanningBinding]:
        binding = self.planning_binding(request_id)
        if binding is None:
            raise ValueError("unknown effort Planning request")
        if binding.status == "started":
            return self, binding
        if binding.status != "prepared":
            raise ValueError("effort Planning request is no longer prepared")
        now = utc_now()
        started = replace(binding, status="started", started_at=now, updated_at=now)
        return self._replace_planning_binding(started), started

    def finish_planning(self, request_id: str, *, failed: bool = False) -> tuple[EffortPolicyState, EffortPlanningBinding]:
        binding = self.planning_binding(request_id)
        if binding is None:
            raise ValueError("unknown effort Planning request")
        status = "failed" if failed else "finished"
        if binding.status == status:
            return self, binding
        if binding.status not in {"prepared", "started"}:
            raise ValueError("effort Planning request is already terminal")
        finished = replace(binding, status=status, updated_at=utc_now())
        return self._replace_planning_binding(finished), finished

    def _replace_planning_binding(self, binding: EffortPlanningBinding) -> EffortPolicyState:
        return replace(self, planning_bindings=tuple(
            binding if item.planning_request_id == binding.planning_request_id else item for item in self.planning_bindings
        ))

    def _replay(self, request_id: str, action: str, mode: EffortMode | None, expected_revision: int) -> EffortPolicyView | None:
        if any(item.planning_request_id == request_id for item in self.planning_bindings):
            raise ValueError("requestId conflicts with an effort Planning request")
        for receipt in self.mutation_receipts:
            if receipt.request_id != request_id:
                continue
            if (receipt.action, receipt.mode, receipt.expected_revision) != (action, mode, expected_revision):
                raise ValueError("requestId was used for a different effort policy change")
            return receipt.result
        return None

    def _check_revision(self, expected_revision: int) -> None:
        if self.revision != expected_revision:
            raise EffortPolicyRevisionError(f"effort policy revision mismatch: expected {expected_revision}, actual {self.revision}")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": EFFORT_POLICY_SCHEMA_VERSION,
            "revision": self.revision,
            "selected_mode": self.selected_mode.value if self.selected_mode is not None else None,
            "pending_execution_mode": self.pending_execution_mode.value if self.pending_execution_mode is not None else None,
            "pending_request_id": self.pending_request_id or None,
            "prepared_policies": {policy.policy_id: policy.to_dict() for policy in self.prepared_policies},
            "execution_bindings": {binding.execution_request_id: binding.to_dict() for binding in self.execution_bindings},
            "planning_bindings": {binding.planning_request_id: binding.to_dict() for binding in self.planning_bindings},
            "mutation_receipts": [receipt.to_dict() for receipt in self.mutation_receipts],
        }

    @classmethod
    def from_dict(cls, raw: object) -> EffortPolicyState:
        if not isinstance(raw, dict):
            raise ValueError("effort policy sidecar must be an object")
        expected_keys = {
            "schema_version", "revision", "selected_mode", "pending_execution_mode", "pending_request_id",
            "prepared_policies", "execution_bindings", "mutation_receipts",
        }
        version = raw.get("schema_version")
        if type(version) is not int or version not in {1, EFFORT_POLICY_SCHEMA_VERSION}:
            raise ValueError("unsupported effort policy sidecar schema")
        if version == 2:
            expected_keys.add("planning_bindings")
        if raw.keys() != expected_keys:
            raise ValueError("unsupported effort policy sidecar schema")
        policies_raw = raw["prepared_policies"]
        bindings_raw = raw["execution_bindings"]
        if not isinstance(policies_raw, dict) or not isinstance(bindings_raw, dict):
            raise ValueError("effort policy snapshots and bindings must be objects")
        policies = tuple(ResolvedEffortPolicy.from_dict(item) for item in policies_raw.values())
        if any(key != policy.policy_id for key, policy in zip(policies_raw, policies)):
            raise ValueError("effort policy snapshot ID mismatch")
        bindings = tuple(EffortExecutionBinding.from_dict(key, item) for key, item in bindings_raw.items())
        planning_raw = raw["planning_bindings"] if version == 2 else {}
        if not isinstance(planning_raw, dict):
            raise ValueError("effort Planning bindings must be an object")
        planning_bindings = tuple(EffortPlanningBinding.from_dict(key, item) for key, item in planning_raw.items())
        receipts_raw = raw["mutation_receipts"]
        if not isinstance(receipts_raw, list):
            raise ValueError("effort policy mutation receipts must be an array")
        receipts = tuple(EffortPolicyMutationReceipt.from_dict(item) for item in receipts_raw)
        view = _effort_view_from_dict(raw)
        policy_by_id = {policy.policy_id: policy for policy in policies}
        other_ids = {item.execution_request_id for item in bindings} | {item.request_id for item in receipts}
        for binding in planning_bindings:
            policy = policy_by_id.get(binding.policy_id)
            if (policy is None or policy.scope != "planning" or policy.plan_revision != binding.plan_revision
                    or policy.planning_profile is None or policy.task_profiles or policy.review_decisions):
                raise ValueError("effort Planning binding has no matching policy snapshot")
            if binding.policy_revision > view.revision or binding.planning_request_id in other_ids:
                raise ValueError("effort Planning binding revision or request ID is inconsistent")
        for binding in bindings:
            policy = policy_by_id.get(binding.policy_id)
            if policy is None or policy.scope != "execution" or policy.plan_revision != binding.plan_revision:
                raise ValueError("effort execution binding has no matching policy snapshot")
            if binding.policy_revision > view.revision:
                raise ValueError("effort execution binding policy revision is newer than the sidecar")
            consumed = any(receipt.action == "consume" and receipt.request_id == binding.execution_request_id for receipt in receipts)
            if consumed and (not binding.reservation_request_id or binding.status not in {"started", "finished"}):
                raise ValueError("effort execution binding consumption status mismatch")
        consumed_ids = {receipt.request_id for receipt in receipts if receipt.action == "consume"}
        if consumed_ids - {binding.execution_request_id for binding in bindings}:
            raise ValueError("effort reservation consumption has no execution binding")
        if sum(binding.status in {"prepared", "started"} for binding in bindings) > 1:
            raise ValueError("multiple unfinished effort execution bindings")
        rebuilt = cls()
        for receipt in receipts:
            if receipt.action == "consume":
                rebuilt = rebuilt._consume_reservation(receipt.request_id, receipt.mode)
                result = rebuilt.view()
            elif receipt.action == "cancel":
                rebuilt, result = rebuilt.cancel_reservation(
                    expected_revision=receipt.expected_revision, request_id=receipt.request_id
                )
            else:
                rebuilt, result = rebuilt.set_mode(
                    receipt.mode, target="planning" if receipt.action == "select" else "next_execution",
                    expected_revision=receipt.expected_revision, request_id=receipt.request_id,
                )
            if result != receipt.result:
                raise ValueError("effort policy mutation receipt result mismatch")
        if rebuilt.view() != view or rebuilt.mutation_receipts != receipts:
            raise ValueError("effort policy sidecar state does not match its mutation receipts")
        return replace(rebuilt, prepared_policies=policies, execution_bindings=bindings, planning_bindings=planning_bindings)


def _effort_revision(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("effort policy revision must be a non-negative integer")
    return value


def _effort_timestamp(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("effort policy timestamp must be an ISO datetime")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("effort policy timestamp must be an ISO datetime") from exc
    if parsed.tzinfo is None:
        raise ValueError("effort policy timestamp must include a timezone")
    return value


def _effort_string_list(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"invalid effort policy {name}")
    if len(value) != len(set(value)):
        raise ValueError(f"duplicate effort policy {name}")
    return tuple(value)


def _effort_request_id(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("effort policy requestId must be a UUID")
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ValueError("effort policy requestId must be a UUID") from exc


def _effort_mode(value: object) -> EffortMode | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("effort mode must be a string or null")
    try:
        return EffortMode(value)
    except ValueError as exc:
        raise ValueError(f"invalid effort mode: {value}") from exc


def _effort_view_from_dict(raw: dict[str, object]) -> EffortPolicyView:
    revision = _effort_revision(raw.get("revision"))
    selected_mode = _effort_mode(raw.get("selected_mode"))
    pending_execution_mode = _effort_mode(raw.get("pending_execution_mode"))
    pending_request_id_raw = raw.get("pending_request_id")
    pending_request_id = _effort_request_id(pending_request_id_raw) if pending_request_id_raw is not None else ""
    if (pending_execution_mode is None) != (not pending_request_id):
        raise ValueError("effort policy reservation mode and requestId must agree")
    return EffortPolicyView(revision, selected_mode, pending_execution_mode, pending_request_id)


class RepositoryMaturityKind(StrEnum):
    EXISTING_CODE = "existing_code"
    DOCS_ONLY = "docs_only"
    AMBIGUOUS = "ambiguous"


class TechStackDecisionStatus(StrEnum):
    QUESTIONS_REQUIRED = "questions_required"
    OPTIONS_READY = "options_ready"
    CONFIRMED = "confirmed"
    SUPERSEDED = "superseded"


@dataclass(slots=True)
class RepositoryMaturityEvidence:
    relative_path: str
    evidence_kind: str
    stack_hints: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RepositoryMaturityAssessment:
    kind: RepositoryMaturityKind
    evidence: list[RepositoryMaturityEvidence] = field(default_factory=list)
    ignored_roots: list[str] = field(default_factory=list)
    detected_application_roots: list[str] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    inspected_file_count: int = 0
    truncated: bool = False


@dataclass(slots=True)
class TechStackComponents:
    languages: list[str] = field(default_factory=list)
    runtimes: list[str] = field(default_factory=list)
    application_frameworks: list[str] = field(default_factory=list)
    ui_frameworks: list[str] = field(default_factory=list)
    persistence: list[str] = field(default_factory=list)
    package_and_build_tools: list[str] = field(default_factory=list)
    test_tools: list[str] = field(default_factory=list)
    style_and_analysis: list[str] = field(default_factory=list)
    packaging_and_deployment: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TechStackOption:
    option_id: str
    label: str
    recommendation_rank: int
    components: TechStackComponents
    version_policy: list[str] = field(default_factory=list)
    requirement_fit: list[str] = field(default_factory=list)
    tradeoffs: list[str] = field(default_factory=list)
    unresolved_constraints: list[str] = field(default_factory=list)
    required_external_dependencies: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TechStackDecision:
    decision_id: str
    revision: int
    status: TechStackDecisionStatus
    project_root: str
    requirement_sources: list[str]
    answers: list[str]
    options: list[TechStackOption]
    selected_option_id: str = ""
    confirmed_at: str = ""
    confirmed_by: str = ""
    created_at: str = field(default_factory=utc_now)

    def selection_questions_only(self, questions: list[str]) -> bool:
        """Recognize explicit candidate-choice questions conservatively."""
        if not questions or not self.options:
            return False
        names = {option.label for option in self.options}
        for option in self.options:
            for name in option.components.languages + option.components.runtimes:
                names.add(name)
                names.add(name.removesuffix(" LTS"))
        subjects = "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True) if name)
        subject = rf"(?:{subjects})(?:\s*(?:와|과|및|[·,/+])\s*(?:{subjects}))*"
        patterns = [
            r"(?:추천한|추천된|제안한|제안된) (?:기술 )?(?:구성|후보|기술 스택)(?:을|를) (?:선택|확정)할까요[?？]?",
            rf"(?:추천한|추천된|제안한|제안된) {subject}(?: 구성)?(?:을|를) (?:선택|확정)할까요[?？]?",
            rf"(?:(?:빈 프로젝트의 )?설치·빌드·테스트를 검증할 )?기술 구성으로 (?:추천한|제안한) {subject}(?:을|를) 선택할까요[?？]?",
            r"(?:어떤|어느) (?:기술 구성|기술 스택|후보)(?:을|를) 선택하시겠습니까[?？]?",
            r"(?:Would you like to|Shall we) (?:select|confirm) the recommended (?:stack|option)\?",
        ]
        return all(any(re.fullmatch(pattern, question.strip(), re.IGNORECASE) for pattern in patterns) for question in questions)


@dataclass(slots=True)
class BootstrapPathState:
    relative_path: str
    entry_kind: str
    content_digest: str = ""


@dataclass(slots=True)
class BootstrapAgentInstructions:
    mode: str
    path: str = "AGENTS.md"
    template_version: str = "1"
    rendered_content: str = ""
    content_digest: str = ""
    task_path_injected: bool = False
    task_acceptance_injected: bool = False


@dataclass(slots=True)
class BootstrapSpec:
    decision_id: str
    decision_revision: int
    target_root: str
    planned_paths: list[str]
    steps: list[str]
    required_tools: list[str]
    verify_commands: list[list[str]]
    excluded_external_actions: list[str]
    path_snapshot: list[BootstrapPathState]
    digest: str
    agent_instructions: BootstrapAgentInstructions | None = None
    verified_integration_head: str = ""
    verified_at: str = ""
    feature_plan_attempts: int = 0
    feature_plan_error: str = ""
    created_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class PlanningMessage:
    role: PlanningMessageRole
    text: str
    at: str = field(default_factory=utc_now)


class PlanningApplyStatus(StrEnum):
    QUEUED = "queued"
    APPLYING = "applying"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(slots=True)
class PlanningApplyRequest:
    request_id: str
    conversation_revision: int
    plan_revision: int
    context_snapshot: str
    status: PlanningApplyStatus = PlanningApplyStatus.QUEUED
    created_at: str = field(default_factory=utc_now)
    completed_at: str = ""
    added_tasks: int = 0
    updated_tasks: int = 0
    excluded_tasks: int = 0
    unchanged_tasks: int = 0
    error_code: str = ""
    error: str = ""
    answer_message: str = ""
    answer_conversation_revision: int = 0
    tech_stack_revision: int = 0


class DirectionChangeStatus(StrEnum):
    RECEIVED = "received"
    QUEUED = "queued"
    REVIEWING = "reviewing"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    APPLIED = "applied"
    BLOCKED = "blocked"


@dataclass(slots=True)
class DirectionChangeRequest:
    request_id: str
    text: str
    task_id: str
    task_title: str
    status: DirectionChangeStatus = DirectionChangeStatus.RECEIVED
    next_step: str = ""
    preview_id: str = ""
    error: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    REVIEWING = "reviewing"
    REVISING = "revising"
    WAITING = "waiting"
    DEFERRED = "deferred"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    MERGED = "merged"


class TaskReadiness(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"
    ACTIVE = "active"
    DONE = "done"
    FAILED = "failed"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TaskAction(StrEnum):
    EXECUTE = "execute"
    REVIEW = "review"
    REVISE = "revise"
    VERIFY = "verify"


class ReviewStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    RUNNING = "running"
    CHANGES_REQUESTED = "changes_requested"
    APPROVED = "approved"
    FAILED = "failed"


class RunLockState(StrEnum):
    UNLOCKED = "unlocked"
    ACTIVE = "active"
    STALE = "stale"
    UNVERIFIABLE = "unverifiable"
    MALFORMED = "malformed"


class RunExecutionSituation(StrEnum):
    READY = "ready"
    RUNNING = "running"
    PREPARING = "preparing"
    RESUMABLE = "resumable"
    WAITING_USER_CHECK = "waiting_user_check"
    ATTENTION_REQUIRED = "attention_required"
    TASKS_COMPLETE = "tasks_complete"
    STATUS_UNKNOWN = "status_unknown"
    UNAVAILABLE = "unavailable"


class RunExecutionAction(StrEnum):
    EXECUTE = "execute"
    RESUME = "resume"
    NONE = "none"


class IntegrationStatus(StrEnum):
    NOT_READY = "not_ready"
    NEEDS_VERIFICATION = "needs_verification"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    STALE = "stale"
    CONFLICT = "conflict"
    APPLY_BLOCKED = "apply_blocked"
    MAIN_PUSH_PENDING = "main_push_pending"
    APPLIED = "applied"
    UNKNOWN = "unknown"


class WorkspaceState(StrEnum):
    NOT_PREPARED = "not_prepared"
    ACTIVE = "active"
    STALE = "stale"
    CLEANED = "cleaned"
    UNSAFE = "unsafe"


class ExecutionWorkspaceMode(StrEnum):
    ISOLATED = "isolated"
    SHARED = "shared"


class WorkspaceLocationSource(StrEnum):
    PROJECT_DEFAULT = "project_default"
    CUSTOM_LEGACY = "custom_legacy"
    LEGACY_RECORD = "legacy_record"


class ConflictResolutionStatus(StrEnum):
    UNRESOLVED = "unresolved"
    GENERATING = "generating"
    CANDIDATE_READY = "candidate_ready"
    APPLYING = "applying"
    APPLIED = "applied"
    NEEDS_DECISION = "needs_decision"
    FAILED = "failed"
    STALE = "stale"
    INTERRUPTED = "interrupted"
    WORKSPACE_RECOVERY_REQUIRED = "workspace_recovery_required"


class ArchiveCleanupStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class WorkspaceLocation:
    root: str
    source: WorkspaceLocationSource
    layout_version: int = 2
    notice_code: str = ""


@dataclass(frozen=True, slots=True)
class IntegrationConflictFile:
    path: str
    kind: str
    base_blob: str = ""
    work_blob: str = ""
    main_blob: str = ""
    base_mode: str = ""
    work_mode: str = ""
    main_mode: str = ""
    binary: bool = False
    supported: bool = True


@dataclass(slots=True)
class ConflictResolutionCandidate:
    id: str
    request_id: str
    revision: int = 1
    status: str = "generating"
    worktree: str = ""
    commit: str = ""
    changed_paths: list[str] = field(default_factory=list)
    content_digest: str = ""
    summary: str = ""
    error: str = ""
    created_at: str = field(default_factory=utc_now)
    applied_at: str = ""
    apply_request_id: str = ""


@dataclass(slots=True)
class IntegrationConflict:
    id: str
    verification_attempt_id: str
    main_head: str
    work_head: str
    merge_base_heads: list[str]
    files: list[IntegrationConflictFile]
    fingerprint: str
    detected_at: str = field(default_factory=utc_now)
    abort_status: str = "pending"
    abort_error: str = ""
    resolution_status: ConflictResolutionStatus = ConflictResolutionStatus.UNRESOLVED
    candidate: ConflictResolutionCandidate | None = None
    error: str = ""


@dataclass(slots=True)
class RecoveryTask:
    id: str
    kind: str
    source_key: str
    conflict: IntegrationConflict
    title: str = "최신 Main 통합 충돌 해결"
    operation_request_ids: list[str] = field(default_factory=list)
    verification_attempt_ids: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    superseded_by: str = ""


@dataclass(slots=True)
class ArchiveCleanupTarget:
    id: str
    recorded_path: str
    expected_head: str
    status: str = "pending"
    error: str = ""
    archive_ref: str = ""


@dataclass(slots=True)
class RunArchive:
    archived_at: str
    source_revision: str
    snapshot_path: str
    manifest_path: str
    summary_path: str
    fingerprint: str
    cleanup_status: ArchiveCleanupStatus = ArchiveCleanupStatus.PENDING
    cleanup_request_id: str = ""
    cleanup_targets: list[ArchiveCleanupTarget] = field(default_factory=list)


@dataclass(slots=True)
class Event:
    at: str
    kind: str
    message: str


@dataclass(slots=True)
class UserNotificationEvent:
    event_id: str
    source_key: str
    project_key: str
    run_id: str
    run_title: str
    target_kind: str
    target_id: str
    kind: str
    occurred_at: str
    summary_code: str
    request_id: str = ""
    verification_attempt_id: str = ""
    related_targets: list[str] = field(default_factory=list)
    os_eligible: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ResultFileChange:
    path: str
    change: str


@dataclass(slots=True)
class TaskResultRecord:
    baseline_commit: str
    result_commit: str
    captured_at: str
    files_state: str = "unavailable"
    files: list[ResultFileChange] = field(default_factory=list)
    error: str = ""
    self_report: str = ""
    verification_status: str = "unverified"
    passed_commands: list[list[str]] = field(default_factory=list)
    manual_verification_note: str = ""


@dataclass(slots=True)
class GroupResultRecord:
    verification_attempt_id: str
    main_commit: str
    result_commit: str
    captured_at: str
    files_state: str = "unavailable"
    files: list[ResultFileChange] = field(default_factory=list)
    error: str = ""


@dataclass(slots=True)
class TaskActionResult:
    action: str
    attempt_id: str = ""
    invocation_id: str = ""
    status: str = "running"
    started_at: str = field(default_factory=utc_now)
    finished_at: str = ""
    worker_response: str = ""
    baseline_commit: str = ""
    result_commit: str = ""
    changed_paths: list[str] = field(default_factory=list)
    passed_commands: list[list[str]] = field(default_factory=list)
    code_style_evidence: CodeStyleTaskEvidence | None = None
    review_verdict: str = ""
    review_findings: list[str] = field(default_factory=list)
    error: str = ""
    verification_context_digest: str = ""
    verification_failure_kind: str = ""
    verification_context_inputs: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class VerificationAttempt:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = "running"
    started_at: str = field(default_factory=utc_now)
    finished_at: str = ""
    main_head: str = ""
    task_heads: dict[str, str] = field(default_factory=dict)
    integration_head: str = ""
    phase: str = "preparing"
    current_command: list[str] = field(default_factory=list)
    passed_commands: list[list[str]] = field(default_factory=list)
    commit_queue_task_ids: list[str] = field(default_factory=list)
    last_integrated_task_id: str = ""
    failed_task_id: str = ""
    failure_phase: str = ""
    failed_command: list[str] = field(default_factory=list)
    candidate_task_ids: list[str] = field(default_factory=list)
    attribution_reason: str = ""
    log_path: str = ""
    error: str = ""
    stop_reason: str = ""
    command_timeout_seconds: int = 0
    total_timeout_seconds: int = 0
    repair_count: int = 0


@dataclass(frozen=True, slots=True)
class PushReceipt:
    scope: str
    remote: str
    branch: str
    local_commit: str
    remote_commit: str
    operation_request_id: str = ""
    pushed_at: str = field(default_factory=utc_now)


@dataclass(slots=True)
class OperationRecord:
    request_id: str
    run_id: str
    action: str
    digest: str
    phase: str
    status: str = "running"
    expected_main_head: str = ""
    target_head: str = ""
    error: str = ""
    error_code: str = ""
    finished_at: str = ""
    result_revision: int = 0
    result_commit: str = ""
    result_ref: str = ""
    resume_request_id: str = ""
    created_at: str = field(default_factory=_operation_created_at)
    updated_at: str = field(default_factory=_operation_created_at)
    execution_id: str = ""
    task_id: str = ""
    attempt_id: str = ""
    invocation_id: str = ""
    scope: str = ""
    reason: str = ""
    accepted_at: str = ""
    checkpoint_ref: str = ""
    progress_observation: ProgressObservation | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> OperationRecord:
        payload = dict(raw)
        observation = payload.get("progress_observation")
        if isinstance(observation, dict):
            payload["progress_observation"] = ProgressObservation(**observation)
        elif observation is not None:
            raise TypeError("progress_observation must be an object or null")
        return cls(**payload)

    def update(self, phase: str, *, status: str | None = None, error: str = "", error_code: str = "") -> None:
        self.phase = phase
        if status is not None:
            self.status = status
        self.error = error
        self.error_code = error_code
        self.updated_at = _operation_created_at()
        if status in {"succeeded", "failed", "partial", "interrupted"}:
            self.finished_at = self.updated_at

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExecutionControlRecord:
    run_id: str
    execution_id: str
    scope: str
    owner_pid: int
    phase: str = "running"
    dispatch_paused: bool = False
    task_id: str = ""
    task_title: str = ""
    action: str = ""
    attempt_id: str = ""
    invocation_id: str = ""
    stop_request_id: str = ""
    active_targets: dict[str, dict[str, str]] = field(default_factory=dict)
    started_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class WorkTask:
    id: str
    title: str
    capabilities: list[str]
    description: str = ""
    acceptance_criteria: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    expected_paths: list[str] = field(default_factory=list)
    forbidden_paths: list[str] = field(default_factory=list)
    verify_commands: list[list[str]] = field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    readiness: TaskReadiness = TaskReadiness.READY
    blocked_by: list[str] = field(default_factory=list)
    agent_id: str = ""
    provider_id: str = ""
    model: str = ""
    reasoning_effort: str = ""
    profile_source: ProfileSource = ProfileSource.LEGACY
    effort_baseline_reasoning: str | None = None
    effective_model: str = ""
    effective_reasoning_effort: str = ""
    reviewer_agent_id: str = ""
    reviewer_provider_id: str = ""
    reviewer_model: str = ""
    review_policy_added: bool = False
    routing_reason: str = ""
    routing_confidence: float = 0.0
    model_selection_reason: str = ""
    model_escalation_policy_id: str = ""
    model_escalation_result_index: int = -1
    status: TaskStatus = TaskStatus.PENDING
    review_status: ReviewStatus = ReviewStatus.NOT_REQUIRED
    review_cycles: int = 0
    review_summary: str = ""
    review_findings: list[str] = field(default_factory=list)
    last_review_commit: str = ""
    branch: str = ""
    worktree: str = ""
    started_commit: str = ""
    completed_commit: str = ""
    prompt_path: str = ""
    log_path: str = ""
    error: str = ""
    active_action: TaskAction | None = None
    failed_action: TaskAction | None = None
    attempt_count: int = 0
    last_attempt_id: str = ""
    last_attempt_started_at: str = ""
    last_attempt_finished_at: str = ""
    active_invocation_id: str = ""
    stop_request_id: str = ""
    stopped_at: str = ""
    progress_phase: str = ""
    progress_detail: str = ""
    progress_updated_at: str = ""
    progress_observation: ProgressObservation | None = None
    is_prerequisite: bool = False
    conflict_dependencies: list[str] = field(default_factory=list)
    conflict_group: list[str] = field(default_factory=list)
    action_results: list[TaskActionResult] = field(default_factory=list)
    result_history: list[TaskResultRecord] = field(default_factory=list)
    implementation_notes: list[str] = field(default_factory=list)

    @property
    def execution_dependencies(self) -> list[str]:
        return list(dict.fromkeys([*self.dependencies, *self.conflict_dependencies]))

    def begin_action(self, action: TaskAction, *, count_attempt: bool = True, attempt_id: str = "", invocation_id: str = "") -> None:
        self.active_action = action
        self.failed_action = None
        if count_attempt:
            self.attempt_count += 1
        self.last_attempt_id = attempt_id
        self.active_invocation_id = invocation_id
        self.stop_request_id = ""
        self.stopped_at = ""
        self.last_attempt_started_at = utc_now()
        self.last_attempt_finished_at = ""
        self.error = ""
        self.clear_progress()
        if action in {TaskAction.EXECUTE, TaskAction.REVISE}:
            self.clear_effective_profile()

    def set_effective_profile(self, model: str, reasoning_effort: str) -> None:
        self.effective_model = model
        self.effective_reasoning_effort = reasoning_effort

    def clear_effective_profile(self) -> None:
        self.effective_model = ""
        self.effective_reasoning_effort = ""

    def update_progress(self, phase: str, detail: str = "") -> None:
        self.progress_phase = phase
        self.progress_detail = detail
        self.progress_updated_at = utc_now()

    def clear_progress(self, *, reset_observation: bool = True) -> None:
        self.progress_phase = ""
        self.progress_detail = ""
        self.progress_updated_at = ""
        if reset_observation:
            self.progress_observation = None

    def complete_action(self, action: TaskAction) -> None:
        if self.active_action == action:
            self.active_action = None
        self.failed_action = None
        self.last_attempt_finished_at = utc_now()
        self.active_invocation_id = ""
        self.clear_progress(reset_observation=False)

    def fail_action(self, action: TaskAction, message: str) -> None:
        self.active_action = None
        self.failed_action = action
        self.last_attempt_finished_at = utc_now()
        self.active_invocation_id = ""
        self.error = message
        self.clear_progress(reset_observation=False)

    def stop_action(self, action: TaskAction, request_id: str) -> None:
        self.active_action = None
        self.failed_action = action
        self.status = TaskStatus.STOPPED
        self.stop_request_id = request_id
        self.stopped_at = utc_now()
        self.last_attempt_finished_at = self.stopped_at
        self.active_invocation_id = ""
        self.error = ""
        self.clear_progress(reset_observation=False)


class UserCheckOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    DEFERRED = "deferred"


@dataclass(frozen=True, slots=True)
class UserCheck:
    id: str
    title: str
    instructions: str
    acceptance_criteria: tuple[str, ...]
    after_task_id: str = ""
    blocks_task_ids: tuple[str, ...] = ()
    required_for_integration: bool = False


@dataclass(frozen=True, slots=True)
class UserCheckResult:
    reference_commit: str
    outcome: UserCheckOutcome
    note: str
    recorded_at: str


@dataclass(slots=True)
class RunState:
    id: str
    spec_path: str
    spec_digest: str
    repo_path: str
    main_branch: str
    stage: Stage
    spec_snapshot_path: str = ""
    server_work: bool = False
    summary: str = ""
    tasks: list[WorkTask] = field(default_factory=list)
    planning_questions: list[str] = field(default_factory=list)
    planning_agent_id: str = ""
    planning_provider_id: str = ""
    planning_model: str = ""
    planning_reasoning_effort: str = ""
    planning_profile_source: ProfileSource = ProfileSource.LEGACY
    planning_effort_baseline_reasoning: str | None = None
    planning_claude_session_id: str = ""
    planning_mode: PlanningMode = PlanningMode.AUTO
    planning_request: str = ""
    revision_source_run_id: str = ""
    revision_request_id: str = ""
    revision_request_text: str = ""
    revision_source_task_ids: list[str] = field(default_factory=list)
    revision_source_paths: list[str] = field(default_factory=list)
    planning_attempts: int = 0
    structured_plan_path: str = ""
    clarification_paths: list[str] = field(default_factory=list)
    planning_messages: list[PlanningMessage] = field(default_factory=list)
    planning_follow_up_requests: list[str] = field(default_factory=list)
    planning_conversation_revision: int = 0
    planning_applied_conversation_revision: int = 0
    planning_apply_requests: list[PlanningApplyRequest] = field(default_factory=list)
    direction_change_requests: list[DirectionChangeRequest] = field(default_factory=list)
    repository_maturity: RepositoryMaturityAssessment | None = None
    code_style_snapshot: CodeStyleSnapshot | None = None
    repository_intent: str = ""
    greenfield_phase: str = ""
    tech_stack_decisions: list[TechStackDecision] = field(default_factory=list)
    bootstrap_spec: BootstrapSpec | None = None
    plan_revision: int = 0
    plan_approved_revision: int = 0
    active_policy_id: str = ""
    active_execution_request_id: str = ""
    events: list[Event] = field(default_factory=list)
    notification_events: list[UserNotificationEvent] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    schema_version: int = CURRENT_STATE_SCHEMA_VERSION
    workspace_mode: ExecutionWorkspaceMode = ExecutionWorkspaceMode.ISOLATED
    workspace_location: WorkspaceLocation | None = None
    execution_branch: str = ""
    execution_worktree: str = ""
    base_commit: str = ""
    verified_task_heads: dict[str, str] = field(default_factory=dict)
    verified_main_head: str = ""
    verified_integration_head: str = ""
    pushed_work_branch_head: str = ""
    push_receipts: list[PushReceipt] = field(default_factory=list)
    verification_progress_phase: str = ""
    verification_progress_detail: str = ""
    verification_progress_current: int = 0
    verification_progress_total: int = 0
    verification_started_at: str = ""
    verification_progress_updated_at: str = ""
    active_step: RunStep | None = None
    failed_step: RunStep | None = None
    failure_message: str = ""
    verification_attempts: list[VerificationAttempt] = field(default_factory=list)
    group_result_history: list[GroupResultRecord] = field(default_factory=list)
    integration_conflict: IntegrationConflict | None = None
    recovery_tasks: list[RecoveryTask] = field(default_factory=list)
    archive: RunArchive | None = None
    verification_policy_version: int = 1
    task_verify_command_timeout_seconds: int = 0
    task_verify_total_timeout_seconds: int = 0
    integration_verify_command_timeout_seconds: int = 0
    integration_verify_total_timeout_seconds: int = 0
    verification_repair_limit: int = 2
    verification_repair_count: int = 0
    verification_repair_head: str = ""
    verification_repair_main_head: str = ""
    verification_repair_task_heads: dict[str, str] = field(default_factory=dict)
    external_plan_digest: str = ""
    user_check_plan: list[UserCheck] = field(default_factory=list)
    user_check_results: dict[str, list[UserCheckResult]] = field(default_factory=dict)

    @property
    def plan_is_approved(self) -> bool:
        return self.plan_revision == 0 or self.plan_approved_revision == self.plan_revision

    def revise_plan(self) -> None:
        self.plan_revision = max(1, self.plan_revision + 1)
        self.plan_approved_revision = 0

    def approve_plan(self) -> None:
        if self.plan_revision > 0:
            self.plan_approved_revision = self.plan_revision

    def current_tech_stack_decision(self) -> TechStackDecision | None:
        return next(
            (decision for decision in reversed(self.tech_stack_decisions) if decision.status != TechStackDecisionStatus.SUPERSEDED),
            None,
        )

    def tech_stack_confirmation_allowed(self) -> bool:
        decision = self.current_tech_stack_decision()
        if self.repository_intent != "new_project" or self.stage not in {Stage.NEEDS_CLARIFICATION, Stage.PLANNED} or decision is None:
            return False
        return decision.status == TechStackDecisionStatus.OPTIONS_READY or (
            decision.status == TechStackDecisionStatus.QUESTIONS_REQUIRED and decision.selection_questions_only(self.planning_questions)
        )

    def add_event(self, kind: str, message: str) -> None:
        self.updated_at = utc_now()
        self.events.append(Event(at=self.updated_at, kind=kind, message=message))

    def register_integration_conflict(self, conflict: IntegrationConflict) -> RecoveryTask:
        source_key = _conflict_source_key(conflict)
        existing = next(
            (
                task
                for task in self.recovery_tasks
                if task.kind == "conflict_resolution" and task.source_key == source_key
            ),
            None,
        )
        if existing is not None:
            if conflict.verification_attempt_id and conflict.verification_attempt_id not in existing.verification_attempt_ids:
                existing.verification_attempt_ids.append(conflict.verification_attempt_id)
            self.integration_conflict = existing.conflict
            return existing
        recovery_id = f"recovery-{conflict.fingerprint[:16] or conflict.id.removeprefix('conflict-')}"
        if any(task.id == recovery_id for task in self.recovery_tasks):
            recovery_id = f"{recovery_id}-{len(self.recovery_tasks) + 1}"
        for task in self.recovery_tasks:
            if not task.superseded_by and task.conflict.resolution_status != ConflictResolutionStatus.APPLIED:
                task.superseded_by = recovery_id
        recovery = RecoveryTask(
            id=recovery_id,
            kind="conflict_resolution",
            source_key=source_key,
            conflict=conflict,
            verification_attempt_ids=([conflict.verification_attempt_id] if conflict.verification_attempt_id else []),
        )
        self.recovery_tasks.append(recovery)
        self.integration_conflict = recovery.conflict
        return recovery

    def recovery_task_for_conflict(self, conflict_id: str) -> RecoveryTask | None:
        return next((task for task in self.recovery_tasks if task.conflict.id == conflict_id), None)

    def link_recovery_operation(self, conflict_id: str, request_id: str) -> None:
        task = self.recovery_task_for_conflict(conflict_id)
        if task is not None and request_id not in task.operation_request_ids:
            task.operation_request_ids.append(request_id)

    def link_recovery_verification(self, conflict_id: str, attempt_id: str) -> None:
        task = self.recovery_task_for_conflict(conflict_id)
        if task is not None and attempt_id and attempt_id not in task.verification_attempt_ids:
            task.verification_attempt_ids.append(attempt_id)

    def transition(self, stage: Stage, message: str) -> None:
        self.stage = stage
        self.add_event("stage", message)

    def begin_step(self, step: RunStep) -> None:
        self.active_step = step
        self.failed_step = None
        self.failure_message = ""
        self.add_event("step", f"{step.value} started")

    def begin_verification(self, total: int) -> None:
        started_at = utc_now()
        self.verification_progress_phase = "preparing"
        self.verification_progress_detail = ""
        self.verification_progress_current = 0
        self.verification_progress_total = total
        self.verification_started_at = started_at
        self.verification_progress_updated_at = started_at

    def update_verification_progress(self, phase: str, detail: str = "", *, current: int = 0, total: int | None = None) -> None:
        self.verification_progress_phase = phase
        if self.verification_attempts and self.verification_attempts[-1].status == "running":
            self.verification_attempts[-1].phase = phase
        self.verification_progress_detail = detail
        self.verification_progress_current = current
        if total is not None:
            self.verification_progress_total = total
        self.verification_progress_updated_at = utc_now()

    def complete_step(self, step: RunStep) -> None:
        if self.active_step == step:
            self.active_step = None
        if step == RunStep.VERIFY:
            self.update_verification_progress("completed", current=self.verification_progress_total)
        self.add_event("step", f"{step.value} completed")

    def fail_step(self, step: RunStep, message: str) -> None:
        self.active_step = None
        self.failed_step = step
        self.failure_message = message
        if step == RunStep.VERIFY:
            self.update_verification_progress("failed", message, current=self.verification_progress_current)
        self.transition(Stage.FAILED, message)

    def resume_to(self, stage: Stage, message: str) -> None:
        self.active_step = None
        self.failed_step = None
        self.failure_message = ""
        self.transition(stage, message)

    def user_check_reference(self, check: UserCheck) -> str:
        if not check.after_task_id:
            return self.base_commit
        task = next((task for task in self.tasks if task.id == check.after_task_id), None)
        if task is None or task.status not in {TaskStatus.COMPLETED, TaskStatus.MERGED}:
            return ""
        return task.completed_commit

    def current_user_check_result(self, check: UserCheck) -> UserCheckResult | None:
        reference = self.user_check_reference(check)
        if not reference:
            return None
        return next((result for result in reversed(self.user_check_results.get(check.id, [])) if result.reference_commit == reference), None)

    def unresolved_user_checks(self) -> list[UserCheck]:
        return [check for check in self.user_check_plan
                if (result := self.current_user_check_result(check)) is None or result.outcome != UserCheckOutcome.PASSED]

    def integration_user_checks_pending(self) -> bool:
        return any(check.required_for_integration for check in self.unresolved_user_checks())

    def user_check_blocked_task_ids(self) -> set[str]:
        blocked = {task_id for check in self.unresolved_user_checks() for task_id in check.blocks_task_ids}
        while blocked:
            dependents = {task.id for task in self.tasks if blocked.intersection(task.execution_dependencies)} - blocked
            if not dependents:
                break
            blocked.update(dependents)
        return blocked

    def refresh_task_readiness(self) -> None:
        statuses = {task.id: task.status for task in self.tasks}
        satisfied = {TaskStatus.COMPLETED, TaskStatus.MERGED}
        check_blockers: dict[str, list[str]] = {}
        for check in self.unresolved_user_checks():
            for task_id in check.blocks_task_ids:
                check_blockers.setdefault(task_id, []).append(check.id)
        for task in self.tasks:
            if task.status in satisfied:
                task.readiness = TaskReadiness.DONE
                task.blocked_by = []
                continue
            if task.status in {TaskStatus.FAILED, TaskStatus.STOPPED}:
                task.readiness = TaskReadiness.FAILED
                task.blocked_by = []
                continue
            if task.status in {TaskStatus.RUNNING, TaskStatus.REVIEWING, TaskStatus.REVISING}:
                task.readiness = TaskReadiness.ACTIVE
                task.blocked_by = []
                continue
            task.blocked_by = [dependency for dependency in task.execution_dependencies if statuses.get(dependency) not in satisfied]
            task.blocked_by.extend(check_blockers.get(task.id, ()))
            task.readiness = TaskReadiness.BLOCKED if task.blocked_by or task.status == TaskStatus.DEFERRED else TaskReadiness.READY

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["code_style_snapshot"] = self.code_style_snapshot.to_dict() if self.code_style_snapshot else None
        payload["tech_stack_confirmation_allowed"] = self.tech_stack_confirmation_allowed()
        return payload

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RunState":
        conflict_raw = raw.get("integration_conflict")
        integration_conflict = _integration_conflict_from_dict(conflict_raw) if isinstance(conflict_raw, dict) else None
        recovery_tasks = []
        for item in raw.get("recovery_tasks", []):
            if not isinstance(item, dict) or not isinstance(item.get("conflict"), dict):
                continue
            recovery_tasks.append(
                RecoveryTask(
                    id=str(item.get("id", "")),
                    kind=str(item.get("kind", "conflict_resolution")),
                    source_key=str(item.get("source_key", "")),
                    conflict=_integration_conflict_from_dict(item["conflict"]),
                    title=str(item.get("title", "최신 Main 통합 충돌 해결")),
                    operation_request_ids=[str(value) for value in item.get("operation_request_ids", [])],
                    verification_attempt_ids=[str(value) for value in item.get("verification_attempt_ids", [])],
                    created_at=str(item.get("created_at", "")),
                    superseded_by=str(item.get("superseded_by", "")),
                )
            )
        if integration_conflict is not None:
            matching = next((task for task in recovery_tasks if task.conflict.id == integration_conflict.id), None)
            if matching is None:
                matching = RecoveryTask(
                    id=f"recovery-{integration_conflict.fingerprint[:16] or integration_conflict.id.removeprefix('conflict-')}",
                    kind="conflict_resolution",
                    source_key=_conflict_source_key(integration_conflict),
                    conflict=integration_conflict,
                    verification_attempt_ids=([integration_conflict.verification_attempt_id] if integration_conflict.verification_attempt_id else []),
                    created_at=integration_conflict.detected_at,
                )
                recovery_tasks.append(matching)
            integration_conflict = matching.conflict
        state = cls(
            id=raw["id"],
            spec_path=raw["spec_path"],
            spec_digest=raw["spec_digest"],
            repo_path=raw["repo_path"],
            main_branch=raw["main_branch"],
            stage=Stage(raw["stage"]),
            schema_version=int(raw.get("schema_version", LEGACY_STATE_SCHEMA_VERSION)),
            workspace_mode=ExecutionWorkspaceMode(raw.get("workspace_mode", ExecutionWorkspaceMode.ISOLATED.value)),
            workspace_location=(
                WorkspaceLocation(
                    root=str(raw["workspace_location"]["root"]),
                    source=WorkspaceLocationSource(raw["workspace_location"]["source"]),
                    layout_version=int(raw["workspace_location"].get("layout_version", 2)),
                    notice_code=str(raw["workspace_location"].get("notice_code", "")),
                )
                if isinstance(raw.get("workspace_location"), dict) and raw["workspace_location"].get("root")
                else None
            ),
            execution_branch=raw.get("execution_branch", ""),
            execution_worktree=raw.get("execution_worktree", ""),
            base_commit=raw.get("base_commit", ""),
            verified_task_heads={str(task_id): str(commit) for task_id, commit in raw.get("verified_task_heads", {}).items()},
            verified_main_head=raw.get("verified_main_head", ""),
            verified_integration_head=raw.get("verified_integration_head", ""),
            pushed_work_branch_head=raw.get("pushed_work_branch_head", ""),
            push_receipts=[
                PushReceipt(
                    scope=str(item.get("scope", "")),
                    remote=str(item.get("remote", "")),
                    branch=str(item.get("branch", "")),
                    local_commit=str(item.get("local_commit", "")),
                    remote_commit=str(item.get("remote_commit", "")),
                    operation_request_id=str(item.get("operation_request_id", "")),
                    pushed_at=str(item.get("pushed_at", "")),
                )
                for item in raw.get("push_receipts", [])
                if isinstance(item, dict)
            ],
            verification_attempts=[VerificationAttempt(**item) for item in raw.get("verification_attempts", [])],
            group_result_history=[_group_result_from_dict(item) for item in raw.get("group_result_history", [])],
            integration_conflict=integration_conflict,
            recovery_tasks=recovery_tasks,
            archive=(
                RunArchive(
                    archived_at=str(raw["archive"].get("archived_at", "")),
                    source_revision=str(raw["archive"].get("source_revision", "")),
                    snapshot_path=str(raw["archive"].get("snapshot_path", "")),
                    manifest_path=str(raw["archive"].get("manifest_path", "")),
                    summary_path=str(raw["archive"].get("summary_path", "")),
                    fingerprint=str(raw["archive"].get("fingerprint", "")),
                    cleanup_status=ArchiveCleanupStatus(
                        raw["archive"].get("cleanup_status", ArchiveCleanupStatus.PENDING.value)
                    ),
                    cleanup_request_id=str(raw["archive"].get("cleanup_request_id", "")),
                    cleanup_targets=[
                        ArchiveCleanupTarget(
                            id=str(item.get("id", "")),
                            recorded_path=str(item.get("recorded_path", "")),
                            expected_head=str(item.get("expected_head", "")),
                            status=str(item.get("status", "pending")),
                            error=str(item.get("error", "")),
                            archive_ref=str(item.get("archive_ref", "")),
                        )
                        for item in raw["archive"].get("cleanup_targets", [])
                        if isinstance(item, dict)
                    ],
                )
                if isinstance(raw.get("archive"), dict)
                else None
            ),
            verification_policy_version=int(raw.get("verification_policy_version", 1)),
            task_verify_command_timeout_seconds=int(raw.get("task_verify_command_timeout_seconds", 0)),
            task_verify_total_timeout_seconds=int(raw.get("task_verify_total_timeout_seconds", 0)),
            integration_verify_command_timeout_seconds=int(raw.get("integration_verify_command_timeout_seconds", 0)),
            integration_verify_total_timeout_seconds=int(raw.get("integration_verify_total_timeout_seconds", 0)),
            verification_repair_limit=int(raw.get("verification_repair_limit", 2)),
            verification_repair_count=int(raw.get("verification_repair_count", 0)),
            verification_repair_head=str(raw.get("verification_repair_head", "")),
            verification_repair_main_head=str(raw.get("verification_repair_main_head", "")),
            verification_repair_task_heads={
                str(key): str(value)
                for key, value in dict(raw.get("verification_repair_task_heads") or {}).items()
            },
            verification_progress_phase=raw.get("verification_progress_phase", ""),
            verification_progress_detail=raw.get("verification_progress_detail", ""),
            verification_progress_current=int(raw.get("verification_progress_current", 0)),
            verification_progress_total=int(raw.get("verification_progress_total", 0)),
            verification_started_at=raw.get("verification_started_at", ""),
            verification_progress_updated_at=raw.get("verification_progress_updated_at", ""),
            active_step=(RunStep(raw["active_step"]) if raw.get("active_step") else None),
            failed_step=(RunStep(raw["failed_step"]) if raw.get("failed_step") else None),
            failure_message=raw.get("failure_message", ""),
            spec_snapshot_path=raw.get("spec_snapshot_path", ""),
            server_work=raw.get("server_work", False),
            summary=raw.get("summary", ""),
            planning_questions=list(raw.get("planning_questions", [])),
            planning_agent_id=raw.get("planning_agent_id", ""),
            planning_provider_id=raw.get("planning_provider_id", ""),
            planning_model=raw.get("planning_model", ""),
            planning_reasoning_effort=raw.get("planning_reasoning_effort", ""),
            planning_profile_source=ProfileSource(raw.get("planning_profile_source", ProfileSource.LEGACY.value)),
            planning_effort_baseline_reasoning=_effort_baseline(raw.get("planning_effort_baseline_reasoning")),
            active_policy_id=raw.get("active_policy_id", ""),
            active_execution_request_id=raw.get("active_execution_request_id", ""),
            planning_claude_session_id=raw.get("planning_claude_session_id", ""),
            planning_mode=PlanningMode(raw.get("planning_mode", PlanningMode.AUTO.value)),
            planning_request=raw.get("planning_request", ""),
            external_plan_digest=str(raw.get("external_plan_digest") or ""),
            user_check_plan=[UserCheck(
                id=item["id"], title=item["title"], instructions=item["instructions"],
                acceptance_criteria=tuple(item["acceptance_criteria"]), after_task_id=item.get("after_task_id", ""),
                blocks_task_ids=tuple(item.get("blocks_task_ids", ())), required_for_integration=item.get("required_for_integration", False),
            ) for item in raw.get("user_check_plan", [])],
            user_check_results={check_id: [UserCheckResult(
                item["reference_commit"], UserCheckOutcome(item["outcome"]), item["note"], item["recorded_at"],
            ) for item in results] for check_id, results in raw.get("user_check_results", {}).items()},
            revision_source_run_id=str(raw.get("revision_source_run_id", "")),
            revision_request_id=str(raw.get("revision_request_id", "")),
            revision_request_text=str(raw.get("revision_request_text", "")),
            revision_source_task_ids=[str(value) for value in raw.get("revision_source_task_ids", [])],
            revision_source_paths=[str(value) for value in raw.get("revision_source_paths", [])],
            planning_attempts=int(raw.get("planning_attempts", 0)),
            structured_plan_path=raw.get("structured_plan_path", ""),
            clarification_paths=list(raw.get("clarification_paths", [])),
            planning_messages=[
                PlanningMessage(role=PlanningMessageRole(item["role"]), text=item["text"], at=item.get("at", ""))
                for item in raw.get("planning_messages", [])
            ],
            planning_follow_up_requests=[str(item) for item in raw.get("planning_follow_up_requests", []) if str(item).strip()],
            planning_conversation_revision=int(raw.get("planning_conversation_revision", len(raw.get("planning_messages", [])))),
            planning_applied_conversation_revision=int(raw.get("planning_applied_conversation_revision", 0)),
            planning_apply_requests=[
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
            ],
            direction_change_requests=[
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
            ],
            repository_maturity=(
                RepositoryMaturityAssessment(
                    kind=RepositoryMaturityKind(raw["repository_maturity"].get("kind", RepositoryMaturityKind.AMBIGUOUS.value)),
                    evidence=[
                        RepositoryMaturityEvidence(
                            relative_path=str(item.get("relative_path", "")),
                            evidence_kind=str(item.get("evidence_kind", "unknown")),
                            stack_hints=[str(value) for value in item.get("stack_hints", [])],
                        )
                        for item in raw["repository_maturity"].get("evidence", [])
                        if isinstance(item, dict)
                    ],
                    ignored_roots=[str(value) for value in raw["repository_maturity"].get("ignored_roots", [])],
                    detected_application_roots=[
                        str(value) for value in raw["repository_maturity"].get("detected_application_roots", [])
                    ],
                    diagnostics=[str(value) for value in raw["repository_maturity"].get("diagnostics", [])],
                    inspected_file_count=int(raw["repository_maturity"].get("inspected_file_count", 0)),
                    truncated=bool(raw["repository_maturity"].get("truncated", False)),
                )
                if isinstance(raw.get("repository_maturity"), dict)
                else None
            ),
            code_style_snapshot=CodeStyleSnapshot.from_dict(raw.get("code_style_snapshot")),
            repository_intent=str(raw.get("repository_intent", "")),
            greenfield_phase=str(raw.get("greenfield_phase", "")),
            tech_stack_decisions=[
                TechStackDecision(
                    decision_id=str(item.get("decision_id", "")),
                    revision=int(item.get("revision", 0)),
                    status=TechStackDecisionStatus(item.get("status", TechStackDecisionStatus.QUESTIONS_REQUIRED.value)),
                    project_root=str(item.get("project_root", "")),
                    requirement_sources=[str(value) for value in item.get("requirement_sources", [])],
                    answers=[str(value) for value in item.get("answers", [])],
                    options=[
                        TechStackOption(
                            option_id=str(option.get("option_id", "")),
                            label=str(option.get("label", "")),
                            recommendation_rank=int(option.get("recommendation_rank", 0)),
                            components=TechStackComponents(
                                languages=[str(value) for value in option.get("components", {}).get("languages", [])],
                                runtimes=[str(value) for value in option.get("components", {}).get("runtimes", [])],
                                application_frameworks=[
                                    str(value) for value in option.get("components", {}).get("application_frameworks", [])
                                ],
                                ui_frameworks=[str(value) for value in option.get("components", {}).get("ui_frameworks", [])],
                                persistence=[str(value) for value in option.get("components", {}).get("persistence", [])],
                                package_and_build_tools=[
                                    str(value) for value in option.get("components", {}).get("package_and_build_tools", [])
                                ],
                                test_tools=[str(value) for value in option.get("components", {}).get("test_tools", [])],
                                style_and_analysis=[str(value) for value in option.get("components", {}).get("style_and_analysis", [])],
                                packaging_and_deployment=[
                                    str(value) for value in option.get("components", {}).get("packaging_and_deployment", [])
                                ],
                            ),
                            version_policy=[str(value) for value in option.get("version_policy", [])],
                            requirement_fit=[str(value) for value in option.get("requirement_fit", [])],
                            tradeoffs=[str(value) for value in option.get("tradeoffs", [])],
                            unresolved_constraints=[str(value) for value in option.get("unresolved_constraints", [])],
                            required_external_dependencies=[
                                str(value) for value in option.get("required_external_dependencies", [])
                            ],
                        )
                        for option in item.get("options", [])
                        if isinstance(option, dict) and isinstance(option.get("components"), dict)
                    ],
                    selected_option_id=str(item.get("selected_option_id", "")),
                    confirmed_at=str(item.get("confirmed_at", "")),
                    confirmed_by=str(item.get("confirmed_by", "")),
                    created_at=str(item.get("created_at", "")),
                )
                for item in raw.get("tech_stack_decisions", [])
                if isinstance(item, dict)
            ],
            bootstrap_spec=(
                BootstrapSpec(
                    decision_id=str(raw["bootstrap_spec"].get("decision_id", "")),
                    decision_revision=int(raw["bootstrap_spec"].get("decision_revision", 0)),
                    target_root=str(raw["bootstrap_spec"].get("target_root", "")),
                    planned_paths=[str(value) for value in raw["bootstrap_spec"].get("planned_paths", [])],
                    steps=[str(value) for value in raw["bootstrap_spec"].get("steps", [])],
                    required_tools=[str(value) for value in raw["bootstrap_spec"].get("required_tools", [])],
                    verify_commands=[list(command) for command in raw["bootstrap_spec"].get("verify_commands", [])],
                    excluded_external_actions=[
                        str(value) for value in raw["bootstrap_spec"].get("excluded_external_actions", [])
                    ],
                    path_snapshot=[
                        BootstrapPathState(
                            relative_path=str(item.get("relative_path", "")),
                            entry_kind=str(item.get("entry_kind", "")),
                            content_digest=str(item.get("content_digest", "")),
                        )
                        for item in raw["bootstrap_spec"].get("path_snapshot", [])
                        if isinstance(item, dict)
                    ],
                    digest=str(raw["bootstrap_spec"].get("digest", "")),
                    agent_instructions=(
                        BootstrapAgentInstructions(
                            mode=str(raw["bootstrap_spec"]["agent_instructions"].get("mode", "preserve_existing")),
                            path=str(raw["bootstrap_spec"]["agent_instructions"].get("path", "AGENTS.md")),
                            template_version=str(raw["bootstrap_spec"]["agent_instructions"].get("template_version", "1")),
                            rendered_content=str(raw["bootstrap_spec"]["agent_instructions"].get("rendered_content", "")),
                            content_digest=str(raw["bootstrap_spec"]["agent_instructions"].get("content_digest", "")),
                            task_path_injected=bool(raw["bootstrap_spec"]["agent_instructions"].get("task_path_injected", False)),
                            task_acceptance_injected=bool(
                                raw["bootstrap_spec"]["agent_instructions"].get("task_acceptance_injected", False)
                            ),
                        )
                        if isinstance(raw["bootstrap_spec"].get("agent_instructions"), dict)
                        else None
                    ),
                    verified_integration_head=str(raw["bootstrap_spec"].get("verified_integration_head", "")),
                    verified_at=str(raw["bootstrap_spec"].get("verified_at", "")),
                    feature_plan_attempts=int(raw["bootstrap_spec"].get("feature_plan_attempts", 0)),
                    feature_plan_error=str(raw["bootstrap_spec"].get("feature_plan_error", "")),
                    created_at=str(raw["bootstrap_spec"].get("created_at", "")),
                )
                if isinstance(raw.get("bootstrap_spec"), dict)
                else None
            ),
            plan_revision=int(raw.get("plan_revision", 0)),
            plan_approved_revision=int(raw.get("plan_approved_revision", 0)),
            tasks=[
                WorkTask(
                    id=item["id"],
                    title=item["title"],
                    capabilities=list(item.get("capabilities", [])),
                    description=item.get("description", ""),
                    implementation_notes=list(item.get("implementation_notes", [])),
                    acceptance_criteria=list(item.get("acceptance_criteria", [])),
                    dependencies=list(item.get("dependencies", [])),
                    is_prerequisite=item.get("is_prerequisite", False),
                    conflict_dependencies=list(item.get("conflict_dependencies", [])),
                    conflict_group=list(item.get("conflict_group", [])),
                    action_results=[_task_action_result_from_dict(result) for result in item.get("action_results", [])],
                    result_history=[_task_result_from_dict(result) for result in item.get("result_history", [])],
                    expected_paths=list(item.get("expected_paths", [])),
                    forbidden_paths=list(item.get("forbidden_paths", [])),
                    verify_commands=[list(command) for command in item.get("verify_commands", [])],
                    risk_level=RiskLevel(item.get("risk_level", RiskLevel.MEDIUM)),
                    readiness=TaskReadiness(item.get("readiness", TaskReadiness.READY)),
                    blocked_by=list(item.get("blocked_by", [])),
                    agent_id=item.get("agent_id", ""),
                    provider_id=item.get("provider_id", ""),
                    model=item.get("model", ""),
                    reasoning_effort=item.get("reasoning_effort", ""),
                    profile_source=ProfileSource(item.get("profile_source", ProfileSource.LEGACY.value)),
                    effort_baseline_reasoning=_effort_baseline(item.get("effort_baseline_reasoning")),
                    effective_model=item.get("effective_model", ""),
                    effective_reasoning_effort=item.get("effective_reasoning_effort", ""),
                    reviewer_agent_id=item.get("reviewer_agent_id", ""),
                    reviewer_provider_id=item.get("reviewer_provider_id", ""),
                    reviewer_model=item.get("reviewer_model", ""),
                    review_policy_added=_review_policy_added(item.get("review_policy_added", False)),
                    routing_reason=item.get("routing_reason", ""),
                    routing_confidence=float(item.get("routing_confidence", 0.0)),
                    model_selection_reason=item.get("model_selection_reason", ""),
                    model_escalation_policy_id=item.get("model_escalation_policy_id", ""),
                    model_escalation_result_index=_model_escalation_index(item.get("model_escalation_result_index", -1)),
                    status=TaskStatus(item.get("status", TaskStatus.PENDING)),
                    review_status=ReviewStatus(item.get("review_status", ReviewStatus.NOT_REQUIRED)),
                    review_cycles=int(item.get("review_cycles", 0)),
                    review_summary=item.get("review_summary", ""),
                    review_findings=list(item.get("review_findings", [])),
                    last_review_commit=item.get("last_review_commit", ""),
                    branch=item.get("branch", ""),
                    worktree=item.get("worktree", ""),
                    started_commit=item.get("started_commit", ""),
                    completed_commit=item.get("completed_commit", ""),
                    prompt_path=item.get("prompt_path", ""),
                    log_path=item.get("log_path", ""),
                    error=item.get("error", ""),
                    active_action=(TaskAction(item["active_action"]) if item.get("active_action") else None),
                    failed_action=(TaskAction(item["failed_action"]) if item.get("failed_action") else None),
                    attempt_count=int(item.get("attempt_count", 0)),
                    last_attempt_id=item.get("last_attempt_id", ""),
                    last_attempt_started_at=item.get("last_attempt_started_at", ""),
                    last_attempt_finished_at=item.get("last_attempt_finished_at", ""),
                    active_invocation_id=item.get("active_invocation_id", ""),
                    stop_request_id=item.get("stop_request_id", ""),
                    stopped_at=item.get("stopped_at", ""),
                    progress_phase=item.get("progress_phase", ""),
                    progress_detail=item.get("progress_detail", ""),
                    progress_updated_at=item.get("progress_updated_at", ""),
                    progress_observation=(ProgressObservation(**item["progress_observation"]) if isinstance(item.get("progress_observation"), dict) else None),
                )
                for item in raw.get("tasks", [])
            ],
            events=[Event(**item) for item in raw.get("events", [])],
            notification_events=[UserNotificationEvent(**item) for item in raw.get("notification_events", [])],
            created_at=raw.get("created_at", utc_now()),
            updated_at=raw.get("updated_at", utc_now()),
        )
        state.refresh_task_readiness()
        return state


def _conflict_source_key(conflict: IntegrationConflict) -> str:
    return f"{conflict.work_head}:{conflict.main_head}:{conflict.fingerprint}"


def _integration_conflict_from_dict(raw: dict[str, Any]) -> IntegrationConflict:
    candidate_raw = raw.get("candidate")
    return IntegrationConflict(
        id=str(raw["id"]),
        verification_attempt_id=str(raw.get("verification_attempt_id", "")),
        main_head=str(raw.get("main_head", "")),
        work_head=str(raw.get("work_head", "")),
        merge_base_heads=[str(value) for value in raw.get("merge_base_heads", [])],
        files=[IntegrationConflictFile(**item) for item in raw.get("files", [])],
        fingerprint=str(raw.get("fingerprint", "")),
        detected_at=str(raw.get("detected_at", "")),
        abort_status=str(raw.get("abort_status", "pending")),
        abort_error=str(raw.get("abort_error", "")),
        resolution_status=ConflictResolutionStatus(raw.get("resolution_status", ConflictResolutionStatus.UNRESOLVED.value)),
        candidate=(ConflictResolutionCandidate(**candidate_raw) if isinstance(candidate_raw, dict) else None),
        error=str(raw.get("error", "")),
    )


def _task_action_result_from_dict(raw: dict[str, Any]) -> TaskActionResult:
    values = dict(raw)
    values["code_style_evidence"] = CodeStyleTaskEvidence.from_dict(raw.get("code_style_evidence"))
    return TaskActionResult(**values)


def _result_files_from_dict(raw: dict[str, Any]) -> list[ResultFileChange]:
    return [ResultFileChange(path=str(item["path"]), change=str(item["change"])) for item in raw.get("files", [])]


def _task_result_from_dict(raw: dict[str, Any]) -> TaskResultRecord:
    return TaskResultRecord(
        baseline_commit=str(raw.get("baseline_commit", "")), result_commit=str(raw.get("result_commit", "")),
        captured_at=str(raw.get("captured_at", "")), files_state=str(raw.get("files_state", "unavailable")),
        files=_result_files_from_dict(raw), error=str(raw.get("error", "")), self_report=str(raw.get("self_report", "")),
        verification_status=str(raw.get("verification_status", "unverified")),
        passed_commands=[list(command) for command in raw.get("passed_commands", [])],
        manual_verification_note=str(raw.get("manual_verification_note") or ""),
    )


def _group_result_from_dict(raw: dict[str, Any]) -> GroupResultRecord:
    return GroupResultRecord(
        verification_attempt_id=str(raw.get("verification_attempt_id", "")), main_commit=str(raw.get("main_commit", "")),
        result_commit=str(raw.get("result_commit", "")), captured_at=str(raw.get("captured_at", "")),
        files_state=str(raw.get("files_state", "unavailable")), files=_result_files_from_dict(raw),
        error=str(raw.get("error", "")),
    )


@dataclass(frozen=True, slots=True)
class RunSummary:
    id: str
    summary: str
    stage: Stage
    updated_at: str
    created_at: str
    task_count: int
    completed_task_count: int
    archived: bool = False
    archived_at: str = ""
    cleanup_status: str = ""
    failed_task_count: int = 0
    waiting_task_count: int = 0
    plan_is_approved: bool = True
    attention_reasons: tuple[str, ...] = ()
    execution_situation: str = "unavailable"
    pipeline_complete: bool = False
    checked_at: str = ""

    @classmethod
    def from_state(
        cls,
        state: RunState,
        *,
        attention_reasons: tuple[str, ...] = (),
        execution_situation: str = "unavailable",
        pipeline_complete: bool = False,
        checked_at: str = "",
    ) -> "RunSummary":
        completed = {TaskStatus.COMPLETED, TaskStatus.MERGED}
        return cls(
            id=state.id,
            summary=state.summary,
            stage=state.stage,
            updated_at=state.updated_at,
            created_at=state.created_at,
            task_count=len(state.tasks),
            completed_task_count=sum(task.status in completed for task in state.tasks),
            archived=state.archive is not None,
            archived_at=state.archive.archived_at if state.archive else "",
            cleanup_status=state.archive.cleanup_status.value if state.archive else "",
            failed_task_count=sum(task.status == TaskStatus.FAILED for task in state.tasks),
            waiting_task_count=sum(task.status == TaskStatus.WAITING for task in state.tasks),
            plan_is_approved=state.plan_is_approved,
            attention_reasons=attention_reasons,
            execution_situation=execution_situation,
            pipeline_complete=pipeline_complete,
            checked_at=checked_at,
        )

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "RunSummary":
        tasks = raw.get("tasks", [])
        if not isinstance(tasks, list):
            raise ValueError("run tasks must be an array")
        completed_values = {TaskStatus.COMPLETED.value, TaskStatus.MERGED.value}
        return cls(
            id=str(raw["id"]),
            summary=str(raw.get("summary", "")),
            stage=Stage(raw["stage"]),
            updated_at=str(raw.get("updated_at", "")),
            created_at=str(raw.get("created_at", "")),
            task_count=len(tasks),
            completed_task_count=sum(isinstance(task, dict) and task.get("status") in completed_values for task in tasks),
            archived=isinstance(raw.get("archive"), dict),
            archived_at=str(raw.get("archive", {}).get("archived_at", "")) if isinstance(raw.get("archive"), dict) else "",
            cleanup_status=str(raw.get("archive", {}).get("cleanup_status", "")) if isinstance(raw.get("archive"), dict) else "",
            failed_task_count=sum(isinstance(task, dict) and task.get("status") == TaskStatus.FAILED.value for task in tasks),
            waiting_task_count=sum(isinstance(task, dict) and task.get("status") == TaskStatus.WAITING.value for task in tasks),
            plan_is_approved=(
                int(raw.get("plan_revision", 0)) == 0
                or int(raw.get("plan_approved_revision", 0)) == int(raw.get("plan_revision", 0))
            ),
        )


@dataclass(frozen=True, slots=True)
class ProviderChoice:
    provider_id: str
    agent_id: str
    model: str = ""
    is_default: bool = False
    max_tasks: int = 1


@dataclass(frozen=True, slots=True)
class RepositoryUpdate:
    repo_path: str
    branch: str
    remote: str
    before_commit: str
    after_commit: str
    remaining_change_count: int = 0
    sync: MainSyncStatus | None = None

    @property
    def changed(self) -> bool:
        return self.before_commit != self.after_commit


@dataclass(frozen=True, slots=True)
class MainChangeItem:
    path: str
    status: str
    staged: bool
    unstaged: bool
    staged_status: str = ""
    unstaged_status: str = ""
    original_path: str = ""


@dataclass(frozen=True, slots=True)
class MainSyncStatus:
    local_head: str
    remote_head: str
    remote: str
    target_branch: str
    relation: str
    ahead: int | None
    behind: int | None
    checked_at: str = ""
    error: str = ""


@dataclass(frozen=True, slots=True)
class MainChangeSnapshot:
    snapshot_id: str
    repo_path: str
    branch: str
    expected_branch: str
    changes: tuple[MainChangeItem, ...]
    excluded_count: int
    sync: MainSyncStatus
    blocked_reason: str = ""


@dataclass(frozen=True, slots=True)
class MainChangeDiff:
    snapshot_id: str
    path: str
    mode: str
    content: str
    binary: bool = False
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class MainMutationResult:
    phase: str
    commit: str
    commit_created: bool
    pushed: bool
    remaining_change_count: int
    snapshot: MainChangeSnapshot
    error: str = ""


@dataclass(frozen=True, slots=True)
class RunDeletion:
    run_id: str
    summary: str
    task_count: int
    worktree_count: int
    branch_count: int


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    id: str
    available: bool
    executable: str
    agent_ids: tuple[str, ...]
    authenticated: bool | None = None
    auth_method: str = ""
    auth_label: str = ""


@dataclass(frozen=True, slots=True)
class RunLockStatus:
    run_id: str
    state: RunLockState
    operation: str = ""
    pid: int | None = None
    host: str = ""
    acquired_at: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RunExecutionControl:
    situation: RunExecutionSituation
    action: RunExecutionAction
    reason: str
    lock_state: RunLockState
    operation: str = ""
    active_task_id: str = ""
    active_task_title: str = ""
    execution_id: str = ""
    active_attempt_id: str = ""
    active_invocation_id: str = ""
    can_stop: bool = False
    stop_scope: str = ""
    stop_request_id: str = ""
    stop_phase: str = ""
    dispatch_paused: bool = False
    checked_at: str = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class IntegrationControl:
    status: IntegrationStatus
    reason: str
    reason_code: str
    can_verify: bool
    can_apply_main: bool
    main_dirty: bool | None = None
    verified_main_head: str = ""
    current_main_head: str = ""
    verified_integration_head: str = ""
    current_integration_head: str = ""
    remote_configured: bool = False
    can_recover_main_apply: bool = False
    checked_at: str = field(default_factory=utc_now)


@dataclass(frozen=True, slots=True)
class WorkspaceStatus:
    run_id: str
    task_id: str
    state: WorkspaceState
    run_stage: str
    task_status: str
    branch: str
    worktree: str
    worktree_exists: bool
    worktree_registered: bool
    worktree_clean: bool | None
    branch_exists: bool
    branch_merged: bool | None
    cleanup_safe: bool
    reason: str
