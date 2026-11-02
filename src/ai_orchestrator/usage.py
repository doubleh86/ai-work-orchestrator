from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime, timezone
from typing import Callable, Iterable
import uuid


TOKEN_FIELDS = ("input_tokens", "output_tokens", "total_tokens", "cached_input_tokens", "cache_write_input_tokens", "reasoning_output_tokens")
USAGE_PURPOSES = {"planning", "chat", "execute", "review", "revise", "recovery_planning", "conflict_resolution",
                  "verification_repair", "result_revision"}


def usage_id(value: object) -> str:
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("invalid usage request ID")
    return value


def _timestamp(value: object) -> str:
    if not isinstance(value, str) or datetime.fromisoformat(value).tzinfo is None:
        raise ValueError("invalid usage timestamp")
    return value


def usage_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@dataclass(frozen=True, slots=True)
class TokenCounts:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_write_input_tokens: int | None = None
    reasoning_output_tokens: int | None = None

    def __post_init__(self) -> None:
        if any(value is not None and (type(value) is not int or value < 0) for value in asdict(self).values()):
            raise ValueError("usage counters must be non-negative integers or null")

    @classmethod
    def from_provider(cls, raw: object) -> TokenCounts:
        aliases = ("inputTokens", "outputTokens", "totalTokens", "cachedInputTokens", "cacheWriteInputTokens", "reasoningOutputTokens")
        values = []
        for name, alias in zip(TOKEN_FIELDS, aliases):
            values.append(raw.get(name, raw.get(alias)) if isinstance(raw, dict) else getattr(raw, name, None))
        return cls(*values)

    def delta(self, baseline: TokenCounts) -> TokenCounts:
        values = []
        for name in TOKEN_FIELDS:
            end, start = getattr(self, name), getattr(baseline, name)
            values.append(end - start if end is not None and start is not None else None)
        return TokenCounts(*values)

    @property
    def has_report(self) -> bool:
        return any(getattr(self, name) is not None for name in TOKEN_FIELDS)

    @property
    def total_mismatch(self) -> bool:
        return (self.input_tokens is not None and self.output_tokens is not None and self.total_tokens is not None
                and self.input_tokens + self.output_tokens != self.total_tokens)


@dataclass(frozen=True, slots=True)
class UsageObservation:
    source_revision: int
    counts: TokenCounts = TokenCounts()
    thread_id: str = ""
    turn_id: str = ""
    usage_epoch: str = ""
    source_kind: str = "unavailable"
    missing_reason: str = "provider_not_reported"
    observed_at: str = ""
    finalized: bool = False

    def __post_init__(self) -> None:
        if type(self.source_revision) is not int or self.source_revision < 1:
            raise ValueError("invalid usage source revision")
        if (not isinstance(self.source_kind, str) or self.source_kind not in {"unavailable", "thread_delta", "turn_total"}
                or type(self.finalized) is not bool or not isinstance(self.counts, TokenCounts)):
            raise ValueError("invalid usage observation")
        _timestamp(self.observed_at)
        for value in (self.thread_id, self.turn_id, self.usage_epoch, self.missing_reason):
            if not isinstance(value, str) or any(marker in value for marker in ("\x00", "\n", "\r")):
                raise ValueError("invalid usage observation metadata")
        if self.usage_epoch:
            usage_id(self.usage_epoch)
        if self.source_kind == "thread_delta" and not (self.thread_id and self.turn_id and self.usage_epoch):
            raise ValueError("thread delta requires provider identifiers")


@dataclass(frozen=True, slots=True)
class UsageContext:
    run_id: str
    purpose: str
    execution_request_id: str = ""
    operation_request_id: str = ""
    policy_id: str = ""
    mode: str | None = None


@dataclass(frozen=True, slots=True)
class UsageRecord:
    invocation_id: str
    purpose: str
    provider: str
    model_requested: str
    created_at: str
    execution_request_id: str = ""
    operation_request_id: str = ""
    task_id: str = ""
    attempt_id: str = ""
    model_effective: str = ""
    policy_id: str = ""
    mode: str | None = None
    thread_id: str = ""
    turn_id: str = ""
    usage_epoch: str = ""
    source_revision: int = 0
    counts: TokenCounts = TokenCounts()
    source_kind: str = "unavailable"
    missing_reason: str = "usage_pending"
    observed_at: str = ""
    outcome: str = "running"
    finalized: bool = False

    def __post_init__(self) -> None:
        usage_id(self.invocation_id)
        for value in (self.execution_request_id, self.operation_request_id, self.policy_id, self.usage_epoch):
            if not isinstance(value, str):
                raise ValueError("invalid usage request metadata")
            if value:
                usage_id(value)
        if (not isinstance(self.purpose, str) or self.purpose not in USAGE_PURPOSES
                or (self.mode is not None and (not isinstance(self.mode, str) or self.mode not in {"economy", "balanced", "focused"}))):
            raise ValueError("invalid usage purpose or mode")
        if not isinstance(self.outcome, str) or self.outcome not in {"running", "completed", "failed", "cancelled", "interrupted"}:
            raise ValueError("invalid usage outcome")
        if type(self.source_revision) is not int or self.source_revision < 0 or type(self.finalized) is not bool:
            raise ValueError("invalid usage record revision or finalization")
        if (not isinstance(self.counts, TokenCounts) or not isinstance(self.source_kind, str)
                or self.source_kind not in {"unavailable", "thread_delta", "turn_total"}):
            raise ValueError("invalid usage counters or source")
        for name in ("provider", "model_requested", "model_effective", "task_id", "attempt_id", "thread_id", "turn_id", "missing_reason"):
            value = getattr(self, name)
            if not isinstance(value, str) or any(marker in value for marker in ("\x00", "\n", "\r")):
                raise ValueError("invalid usage metadata")
        if not self.provider or (self.source_kind == "thread_delta" and not (self.thread_id and self.turn_id and self.usage_epoch)):
            raise ValueError("usage source requires provider identifiers")
        _timestamp(self.created_at)
        if self.observed_at:
            _timestamp(self.observed_at)

    @property
    def coverage(self) -> str:
        if not self.counts.has_report:
            return "unavailable"
        if (self.finalized and not self.missing_reason and not self.counts.total_mismatch
                and all(getattr(self.counts, name) is not None for name in TOKEN_FIELDS[:3])):
            return "complete"
        return "partial"

    def observe(self, observation: UsageObservation) -> UsageRecord:
        return replace(
            self, source_revision=observation.source_revision, counts=observation.counts, thread_id=observation.thread_id,
            turn_id=observation.turn_id, usage_epoch=observation.usage_epoch, source_kind=observation.source_kind,
            missing_reason=observation.missing_reason, observed_at=observation.observed_at, finalized=observation.finalized,
        )

    def to_dict(self) -> dict[str, object]:
        raw = asdict(self)
        raw.pop("counts")
        return {"schema_version": 1, **raw, **asdict(self.counts), "coverage": self.coverage}

    @classmethod
    def from_dict(cls, raw: object) -> UsageRecord:
        names = {item.name for item in fields(cls)} - {"counts"}
        if not isinstance(raw, dict) or type(raw.get("schema_version")) is not int or raw["schema_version"] != 1:
            raise ValueError("unsupported usage record schema")
        if raw.keys() != names | set(TOKEN_FIELDS) | {"schema_version", "coverage"}:
            raise ValueError("invalid usage record fields")
        counts = TokenCounts(**{name: raw[name] for name in TOKEN_FIELDS})
        record = cls(**{name: raw[name] for name in names}, counts=counts)
        if raw["coverage"] != record.coverage:
            raise ValueError("usage coverage differs from reported counters")
        return record


def usage_summary(records: Iterable[UsageRecord]) -> dict[str, object]:
    rows = tuple(records)
    totals = {}
    coverage = {}
    for name in TOKEN_FIELDS:
        values = [getattr(row.counts, name) for row in rows if getattr(row.counts, name) is not None]
        totals[name] = sum(values) if values else None
        coverage[name] = len(values)
    reported = sum(row.counts.has_report for row in rows)
    complete = sum(row.coverage == "complete" and row.outcome != "running" for row in rows)
    return {
        **totals, "field_coverage": coverage, "call_count": len(rows), "reported_call_count": reported,
        "complete_call_count": complete, "running_call_count": sum(row.outcome == "running" for row in rows),
        "coverage": "complete" if rows and complete == len(rows) else "partial" if reported else "unavailable",
        "latest_observed_at": max((row.observed_at for row in rows), default=""),
    }


def usage_groups(records: Iterable[UsageRecord], attribute: str) -> list[dict[str, object]]:
    groups: dict[str, list[UsageRecord]] = {}
    for record in records:
        groups.setdefault(getattr(record, attribute) or "legacy", []).append(record)
    return [{"key": key, **usage_summary(rows)} for key, rows in sorted(groups.items())]


def task_usage_summaries(records: Iterable[UsageRecord]) -> list[dict[str, object]]:
    """Summarize complete Task scopes before invocation records are paginated."""
    tasks: dict[str, list[UsageRecord]] = {}
    for record in records:
        if record.task_id:
            tasks.setdefault(record.task_id, []).append(record)
    result = []
    for task_id, rows in tasks.items():
        attempts: dict[str, list[UsageRecord]] = {}
        for row in rows:
            attempts.setdefault(row.attempt_id, []).append(row)
        result.append({
            "task_id": task_id, **usage_summary(rows), "by_purpose": usage_groups(rows, "purpose"),
            "attempts": [{
                "attempt_id": attempt_id, **usage_summary(attempt_rows), "by_purpose": usage_groups(attempt_rows, "purpose"),
                "profiles": [{"provider": provider, "model_requested": requested, "model_effective": effective}
                             for provider, requested, effective in dict.fromkeys(
                                 (row.provider, row.model_requested, row.model_effective) for row in attempt_rows)],
            } for attempt_id, attempt_rows in attempts.items()],
        })
    return result


class CodexUsageTracker:
    """Attribute thread totals only across a verified, uninterrupted turn boundary."""

    def __init__(self, *, thread_id: str, turn_id: str, epoch: str, baseline: TokenCounts | None,
                 callback: Callable[[UsageObservation], None] | None = None) -> None:
        self.thread_id = thread_id
        self.turn_id = turn_id
        self.epoch = epoch
        self.baseline = baseline
        self.callback = callback
        self.revision = 0
        self.end_total: TokenCounts | None = None
        self.counts = TokenCounts()
        self.reason = "provider_not_reported"
        self.invalid_boundary = False
        self.terminal_received = False

    def receive(self, payload: object) -> None:
        if getattr(payload, "thread_id", "") != self.thread_id or not self.thread_id:
            return
        if getattr(payload, "turn_id", "") != self.turn_id:
            self.invalid_boundary = True
            self.counts = TokenCounts()
            self.reason = "intervening_turn"
            self._emit(False)
            return
        try:
            total = TokenCounts.from_provider(getattr(getattr(payload, "token_usage", None), "total", None))
            if not total.has_report:
                raise ValueError("missing thread total")
            if self.end_total is not None:
                total.delta(self.end_total)
            self.end_total = total
            if self.invalid_boundary:
                return
            if self.baseline is None:
                self.reason = "baseline_missing"
            else:
                self.counts = total.delta(self.baseline)
                self.reason = "provider_total_mismatch" if self.counts.total_mismatch else ""
        except (TypeError, ValueError):
            self.invalid_boundary = True
            self.end_total = None
            self.counts = TokenCounts()
            self.reason = "invalid_cumulative_total"
        self._emit(False)

    def finish(self, terminal_received: bool) -> None:
        self.terminal_received = terminal_received
        self._emit(terminal_received)

    def next_baseline(self, terminal_received: bool) -> TokenCounts | None:
        if terminal_received and not self.invalid_boundary and self.end_total is not None and not self.end_total.total_mismatch:
            return self.end_total
        return None

    def _emit(self, finalized: bool) -> None:
        self.revision += 1
        if self.callback is not None:
            self.callback(UsageObservation(
                source_revision=self.revision, counts=self.counts, thread_id=self.thread_id, turn_id=self.turn_id,
                usage_epoch=self.epoch, source_kind="thread_delta" if self.counts.has_report else "unavailable",
                missing_reason=self.reason, observed_at=usage_now(), finalized=finalized,
            ))
