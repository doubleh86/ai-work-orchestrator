"""Account quota summaries for the desktop, separate from recorded task tokens."""

from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from tempfile import TemporaryDirectory
from typing import Callable, Literal

from .provider_executable import resolve_provider_executable


@dataclass(frozen=True, slots=True)
class QuotaWindow:
    used_percent: float
    resets_at: int | None = None
    reset_label: str = ""


@dataclass(frozen=True, slots=True)
class AccountUsage:
    status: Literal["available", "unavailable", "signed_out", "api_key", "not_installed", "error"]
    five_hour: QuotaWindow | None = None
    weekly: QuotaWindow | None = None


def quota_exhausted(usage: AccountUsage, *, now: float | None = None) -> bool:
    """Only an unexpired provider-reported quota can exclude a provider."""
    checked_at = time.time() if now is None else now
    return usage.status == "available" and any(
        window is not None and window.used_percent >= 100 and (window.resets_at is None or window.resets_at > checked_at)
        for window in (usage.five_hour, usage.weekly)
    )


class AccountUsageCache:
    """A short-lived cache owned by one credential-scoped Pipeline instance."""

    def __init__(self, reader: Callable[[str], AccountUsage] | None, *, ttl: float = 30):
        self._reader = reader
        self._ttl = ttl
        self._entries: dict[str, tuple[float, AccountUsage]] = {}

    def read(self, provider: str) -> AccountUsage:
        if self._reader is None or provider not in {"codex", "claude"}:
            return AccountUsage("unavailable")
        monotonic = time.monotonic()
        cached = self._entries.get(provider)
        if cached is not None and cached[0] > monotonic:
            return cached[1]
        usage = self._reader(provider)
        now = time.time()
        duration = self._ttl
        for window in (usage.five_hour, usage.weekly):
            if window is not None and window.resets_at is not None:
                duration = min(duration, max(0, window.resets_at - now))
        self._entries[provider] = (time.monotonic() + duration, usage)
        return usage


def codex_quota_summary(payload: dict[str, object]) -> AccountUsage:
    buckets = payload.get("rateLimitsByLimitId")
    base = buckets.get("codex") if isinstance(buckets, dict) else None
    if not isinstance(base, dict):
        legacy = payload.get("rateLimits")
        base = legacy if isinstance(legacy, dict) and legacy.get("limitId") in (None, "codex") else {}
    windows: dict[int, QuotaWindow] = {}
    for name in ("primary", "secondary"):
        window = base.get(name)
        if not isinstance(window, dict):
            continue
        duration, used, reset = (window.get(field) for field in ("windowDurationMins", "usedPercent", "resetsAt"))
        if type(duration) is int and duration in (300, 10080) and type(used) in (int, float) and 0 <= used <= 100:
            windows[duration] = QuotaWindow(used, reset if type(reset) is int and 0 < reset <= 253402300799 else None)
    return AccountUsage("available" if windows else "unavailable", windows.get(300), windows.get(10080))


_CLAUDE_QUOTA_LINE = re.compile(
    r"^Current (?P<window>session|week(?: \(all models\))?):\s*"
    r"(?P<used>[0-9]{1,3}(?:\.[0-9]+)?)% used"
    r"(?:\s+·\s+resets\s+(?P<reset>[\w .,:/()+-]{1,100}))?\s*$",
    re.MULTILINE | re.IGNORECASE,
)


def claude_quota_summary(payload: object) -> AccountUsage:
    if not isinstance(payload, dict) or payload.get("type") != "result" or payload.get("subtype") != "success":
        return AccountUsage("error")
    usage = payload.get("usage")
    result = payload.get("result")
    if (payload.get("total_cost_usd") != 0 or not isinstance(usage, dict) or not isinstance(result, str)
            or any(usage.get(field, 0) != 0 for field in (
                "input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
            ))):
        return AccountUsage("error")
    windows: dict[str, QuotaWindow] = {}
    for line in _CLAUDE_QUOTA_LINE.finditer(result):
        used = float(line["used"])
        if used <= 100:
            windows[line["window"].split()[0].lower()] = QuotaWindow(used, reset_label=(line["reset"] or "").strip())
    return AccountUsage("available" if windows else "unavailable", windows.get("session"), windows.get("week"))


def read_claude_quota(connection: dict[str, object]) -> AccountUsage:
    if not connection.get("installed"):
        return AccountUsage("not_installed")
    if connection.get("authenticated") is not True:
        return AccountUsage("signed_out" if connection.get("authenticated") is False else "error")
    if connection.get("auth_method") == "api_key":
        return AccountUsage("api_key")
    if connection.get("auth_method") != "claude_subscription":
        return AccountUsage("unavailable")
    executable = resolve_provider_executable("claude")
    if not executable:
        return AccountUsage("not_installed")
    try:
        with TemporaryDirectory(prefix="orchestrator-claude-usage-") as directory:
            result = subprocess.run(
                [executable, "-p", "--output-format", "json", "--max-turns", "0", "--tools", "",
                 "--setting-sources", "", "--strict-mcp-config", "--settings", '{"disableAllHooks":true}',
                 "--no-session-persistence", "/usage"],
                cwd=directory, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=12, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        return claude_quota_summary(json.loads(result.stdout)) if result.returncode == 0 else AccountUsage("error")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return AccountUsage("error")
