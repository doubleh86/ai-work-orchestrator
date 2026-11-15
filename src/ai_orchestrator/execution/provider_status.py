"""Compose provider status from safe probes owned by the caller."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..codex_sdk import CodexSdkAccountStatus, CodexSdkError
from ..config import AgentConfig
from ..errors import PipelineError
from ..models import ProviderStatus


@dataclass(frozen=True, slots=True)
class ProviderStatusQueries:
    read_agents: Callable[[], tuple[AgentConfig, ...]]
    read_codex_account: Callable[[], CodexSdkAccountStatus] | None
    probe_executable: Callable[[AgentConfig], str]
    nvidia_configured: Callable[[], bool]
    nvidia_app_key: Callable[[], bool]
    read_claude_auth: Callable[[str], tuple[bool | None, str, str]]

    def statuses(self, provider_id: str = "") -> list[ProviderStatus]:
        providers: dict[str, list[AgentConfig]] = {}
        for agent in self.read_agents():
            providers.setdefault(agent.provider_id, []).append(agent)
        if provider_id and provider_id not in providers:
            raise PipelineError(f"unknown provider: {provider_id}")

        statuses: list[ProviderStatus] = []
        selected_ids = [provider_id] if provider_id else sorted(providers)
        for selected_id in selected_ids:
            agents = providers[selected_id]
            resolved: list[str] = []
            available = True
            codex_account: CodexSdkAccountStatus | None = None
            codex_auth_error = False
            authenticated: bool | None = None
            auth_method = ""
            auth_label = ""
            if selected_id == "codex":
                if self.read_codex_account is None:
                    codex_auth_error = True
                else:
                    try:
                        codex_account = self.read_codex_account()
                    except CodexSdkError:
                        codex_auth_error = True
            for agent in agents:
                if agent.provider_id == "codex":
                    if self.read_codex_account is None:
                        available = False
                    else:
                        resolved.append("openai-codex SDK")
                        if codex_auth_error or not (codex_account and codex_account.authenticated):
                            available = False
                    continue
                executable = self.probe_executable(agent)
                if not executable:
                    available = False
                else:
                    resolved.append(executable)
            if selected_id == "codex":
                authenticated = codex_account.authenticated if codex_account is not None else False
                auth_method = codex_account.auth_method if codex_account is not None else "error"
                auth_label = (
                    codex_account.label if codex_account is not None else "인증 확인 실패" if self.read_codex_account is not None else "SDK 사용 불가"
                )
            elif selected_id == "nvidia":
                configured = self.nvidia_configured()
                authenticated = None if configured else False
                auth_method = "app_key" if self.nvidia_app_key() else "environment" if configured else "none"
                if not resolved:
                    auth_label = "OpenCode CLI 설치 필요"
                elif not configured:
                    auth_label = "NVIDIA API 키 등록 필요"
                else:
                    auth_label = "시험 실행 준비됨 · API 연결 미검증"
                available = available and configured
            elif selected_id == "claude":
                if resolved:
                    authenticated, auth_method, auth_label = self.read_claude_auth(resolved[0])
                else:
                    auth_method = "error"
                    auth_label = "Claude CLI 사용 불가"
                if authenticated is not True:
                    available = False
            statuses.append(
                ProviderStatus(
                    id=selected_id,
                    available=available,
                    executable=resolved[0] if resolved else "",
                    agent_ids=tuple(agent.id for agent in agents),
                    authenticated=authenticated,
                    auth_method=auth_method,
                    auth_label=auth_label,
                )
            )
        return statuses
