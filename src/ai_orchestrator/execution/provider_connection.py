"""Read provider installation, authentication and account usage."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Callable

from ..account_usage import AccountUsage, read_claude_quota
from ..claude_credentials import claude_environment, current_claude_api_key
from ..codex_sdk import read_codex_quota
from ..config import AgentConfig
from ..errors import PipelineError
from ..models import ProviderStatus
from ..provider_executable import resolve_provider_executable, selected_claude_executable
from .provider_commands import agent_command
from .claude_connection import claude_connection_details, unknown_claude_connection

PROVIDER_AUTH_STATUS_TIMEOUT_SECONDS = 5


@dataclass(slots=True)
class ProviderConnectionProbes:
    resolve_executable: Callable[[str], str]
    claude_auth: Callable[[str, str | None], tuple[bool | None, str, str]]

    def executable(self, agent: AgentConfig) -> str:
        return provider_status_executable(agent, resolve=self.resolve_executable)


def provider_status_executable(agent: AgentConfig, *, resolve: Callable[[str], str] | None = None) -> str:
    command = agent_command(agent, "execute") or agent.review_command
    return (resolve if resolve is not None else resolve_provider_executable)(command[0]) if command else ""

def read_claude_connection(executable: str, api_key: str | None = None) -> dict[str, object]:
    try:
        result = subprocess.run(
            [executable, "auth", "status", "--json"],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PROVIDER_AUTH_STATUS_TIMEOUT_SECONDS,
            env=claude_environment(api_key),
        )
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, OSError, subprocess.TimeoutExpired, TypeError):
        return unknown_claude_connection()
    return claude_connection_details(payload, result.returncode, app_key=api_key is not None)

def claude_auth_status(executable: str, api_key: str | None = None) -> tuple[bool | None, str, str]:
    status = read_claude_connection(executable, api_key)
    authenticated = status["authenticated"]
    return authenticated if isinstance(authenticated, bool) else None, str(status["auth_method"]), str(status["message"])

def account_usage(provider: str, *, claude_api_key: str | None = None) -> AccountUsage:
    if provider == "codex":
        return read_codex_quota()
    if provider == "claude":
        executable = resolve_provider_executable("claude")
        if not executable:
            return AccountUsage("not_installed")
        return read_claude_quota(read_claude_connection(executable, claude_api_key))
    return AccountUsage("unavailable")

def claude_connection_status() -> dict[str, object]:
    selected = selected_claude_executable()
    executable = resolve_provider_executable("claude")
    if not executable:
        return {"installed": False, "authenticated": False, "auth_method": "none",
                "message": "선택한 Claude 실행 파일을 사용할 수 없습니다" if selected else "Claude CLI 설치 필요",
                "account_email": "", "plan_type": "", "selected_executable": selected}
    return {**read_claude_connection(executable, current_claude_api_key()), "selected_executable": selected}



def ensure_planning_provider_ready(agent: AgentConfig, *, read_statuses: Callable[[str], list[ProviderStatus]], api_key: str | None) -> None:
        if agent.provider_id not in {"claude", "codex"}:
            return
        status = read_statuses(agent.provider_id)[0]
        if status.available:
            return
        if agent.provider_id == "claude":
            if api_key is not None and status.executable:
                raise PipelineError("Claude API 키 인증 상태를 확인할 수 없습니다. 작업 AI의 Claude에서 키를 확인하고 연결을 다시 확인하세요.")
            if status.auth_method == "none":
                raise PipelineError("Claude 로그인이 필요합니다. 터미널에서 `claude auth login`을 실행한 뒤 인증 상태를 새로고침하세요.")
            raise PipelineError("Claude 인증 상태를 확인할 수 없습니다. 터미널에서 `claude auth status`를 확인한 뒤 다시 시도하세요.")
        if status.auth_method == "none":
            raise PipelineError("Codex SDK 로그인이 필요합니다.")
        raise PipelineError("Codex SDK 인증 상태를 확인할 수 없습니다.")
