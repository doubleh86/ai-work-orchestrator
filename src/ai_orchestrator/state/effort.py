from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime

from .common import (
    EffortMode,
    ProfileSource,
    utc_now,
)


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
