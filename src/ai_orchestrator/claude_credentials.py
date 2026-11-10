"""Request-local Claude API credentials and child-process isolation."""

from __future__ import annotations

import os
import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Mapping

_request_key: ContextVar[str | None] = ContextVar("claude_api_key", default=None)


@contextmanager
def claude_credential_scope(value: object) -> Iterator[None]:
    if value is not None and (
        not isinstance(value, str) or not value.strip() or len(value) > 4096
        or re.search(r"[^\x21-\x7e]", value.strip()) or re.search(r"[\0\r\n]", value)
    ):
        raise ValueError("Invalid Claude credential")
    token = _request_key.set(value.strip() if isinstance(value, str) else None)
    try:
        yield
    finally:
        _request_key.reset(token)


def current_claude_api_key() -> str | None:
    return _request_key.get()


def claude_environment(api_key: str | None, environment: Mapping[str, str] | None = None) -> dict[str, str]:
    selected = dict(os.environ if environment is None else environment)
    if api_key is not None:
        # An explicitly registered Anthropic key must not go to an inherited gateway.
        for name in ("ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_CUSTOM_HEADERS",
                     "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"):
            selected.pop(name, None)
        selected["ANTHROPIC_API_KEY"] = api_key
    return selected


def redact_claude_output(text: str, api_key: str | None) -> str:
    key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY", "")
    return text.replace(key, "[REDACTED]") if key else text
