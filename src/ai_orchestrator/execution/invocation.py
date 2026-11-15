"""Worker tool leases and usage receipts around a caller-owned transport."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import Callable, Generic, Protocol, TypeVar

from ..codex_sdk import CodexSdkExecutionProfile, CodexSdkProgress
from ..config import AgentConfig
from ..errors import PipelineError, ProviderTimeoutError
from ..execution_control import ExecutionStopped
from ..usage import UsageContext, UsageObservation, UsageRecord, usage_now
from ..worker_mcp import WorkerMcpError, WorkerMcpServer, check_mcp_connection, configure_claude_mcp, worker_mcp_lease
from .provider_runner import ProviderStopSignal

StopSignal = TypeVar("StopSignal", bound=ProviderStopSignal)
TransportStopSignal = TypeVar("TransportStopSignal", bound=ProviderStopSignal, contravariant=True)


class ProviderTransport(Protocol[TransportStopSignal]):
    def __call__(
        self,
        *,
        agent: AgentConfig,
        command_template: tuple[str, ...],
        replacements: dict[str, str],
        cwd: Path,
        prompt: str,
        prompt_path: str,
        log_path: Path,
        action: str,
        task_id: str,
        timeout_seconds: float | None = None,
        model: str = "",
        reasoning_effort: str = "",
        progress_callback: Callable[[CodexSdkProgress], None] | None = None,
        profile_callback: Callable[[CodexSdkExecutionProfile], None] | None = None,
        sdk_conversation_id: str = "",
        attempt_id: str = "",
        invocation_id: str = "",
        cancel_signal: TransportStopSignal | None = None,
        usage_callback: Callable[[UsageObservation], None] | None = None,
        retry_callback: Callable[[str | None], None] | None = None,
    ) -> str:
        ...


class FinishUsage(Protocol):
    def __call__(self, run_id: str, invocation_id: str, outcome: str, *, structured: bool) -> None: ...


@dataclass(frozen=True, slots=True)
class InvocationUsageRecords:
    begin_usage: Callable[[str, UsageRecord], None]
    update_usage_model: Callable[[str, str, str], None]
    observe_usage: Callable[[str, str, UsageObservation], None]
    finish_usage: FinishUsage


@dataclass(frozen=True, slots=True)
class ProviderInvocation(Generic[StopSignal]):
    repo: Path
    servers: tuple[WorkerMcpServer, ...]
    records: InvocationUsageRecords
    transport: ProviderTransport[StopSignal]

    def invoke(
        self,
        *,
        agent: AgentConfig,
        command_template: tuple[str, ...],
        replacements: dict[str, str],
        cwd: Path,
        prompt: str,
        prompt_path: str,
        log_path: Path,
        action: str,
        task_id: str,
        timeout_seconds: float | None = None,
        model: str = "",
        reasoning_effort: str = "",
        progress_callback: Callable[[CodexSdkProgress], None] | None = None,
        profile_callback: Callable[[CodexSdkExecutionProfile], None] | None = None,
        sdk_conversation_id: str = "",
        attempt_id: str = "",
        invocation_id: str = "",
        cancel_signal: StopSignal | None = None,
        usage_context: UsageContext | None = None,
    ) -> str:
        base_invoke = partial(
            self.transport, agent=agent, command_template=command_template, replacements=replacements, cwd=cwd,
            prompt=prompt, prompt_path=prompt_path, log_path=log_path, action=action, task_id=task_id, timeout_seconds=timeout_seconds,
            model=model, reasoning_effort=reasoning_effort, progress_callback=progress_callback,
            sdk_conversation_id=sdk_conversation_id, attempt_id=attempt_id, cancel_signal=cancel_signal,
        )
        servers = tuple(server for server in self.servers if server.enabled) if action in {"execute", "revise"} else ()
        if servers and agent.provider_id not in {"codex", "claude"}:
            raise PipelineError("연결한 작업 도구는 현재 Codex·Claude 작업 AI에서 사용할 수 있습니다.")

        def invoke(*, profile_callback: Callable[[CodexSdkExecutionProfile], None] | None = None,
                   usage_callback: Callable[[UsageObservation], None] | None = None, invocation_id: str = "",
                   retry_callback: Callable[[str | None], None] | None = None) -> str:
            waited = False

            def waiting_for_tool() -> None:
                nonlocal waited
                waited = True
                if progress_callback is not None:
                    progress_callback(CodexSdkProgress(
                        "waiting_for_tool", "다른 작업이 도구를 사용하고 있어요.", attempt_id=attempt_id,
                        invocation_id=invocation_id, activity_changed=False, evidence_kind="resource_wait",
                    ))

            try:
                with worker_mcp_lease(servers, cancel_signal=cancel_signal, on_wait=waiting_for_tool):
                    if waited and progress_callback is not None:
                        progress_callback(CodexSdkProgress(
                            "preparing_task", attempt_id=attempt_id, invocation_id=invocation_id,
                            activity_changed=False, evidence_kind="local_phase",
                        ))
                    if servers and agent.provider_id == "claude":
                        configure_claude_mcp(list(command_template), servers, cwd, self.repo)
                        for server in servers:
                            checked = check_mcp_connection(server, cwd, self.repo)
                            if checked["status"] != "connected":
                                raise WorkerMcpError(str(checked["message"]))
                    return base_invoke(profile_callback=profile_callback, usage_callback=usage_callback,
                                       invocation_id=invocation_id, retry_callback=retry_callback)
            except WorkerMcpError as exc:
                raise PipelineError(str(exc)) from exc

        if usage_context is None:
            return invoke(profile_callback=profile_callback, invocation_id=invocation_id)
        invocation_id = invocation_id or str(uuid.uuid4())
        record = UsageRecord(
            invocation_id=invocation_id, purpose=usage_context.purpose, provider=agent.provider_id,
            model_requested=model, created_at=usage_now(), execution_request_id=usage_context.execution_request_id,
            operation_request_id=usage_context.operation_request_id, policy_id=usage_context.policy_id,
            mode=usage_context.mode, task_id=task_id, attempt_id=attempt_id,
        )
        self.records.begin_usage(usage_context.run_id, record)
        active_usage_id = invocation_id

        def report_profile(profile: CodexSdkExecutionProfile) -> None:
            self.records.update_usage_model(usage_context.run_id, active_usage_id, profile.model)
            if profile_callback is not None:
                profile_callback(profile)

        def report_usage(observation: UsageObservation) -> None:
            self.records.observe_usage(usage_context.run_id, active_usage_id, observation)

        def report_retry(next_invocation_id: str | None) -> None:
            nonlocal active_usage_id
            if active_usage_id:
                self.records.finish_usage(usage_context.run_id, active_usage_id, "failed", structured=True)
                active_usage_id = ""
            if next_invocation_id:
                active_usage_id = next_invocation_id
                self.records.begin_usage(usage_context.run_id, replace(record, invocation_id=active_usage_id, created_at=usage_now()))

        outcome = "failed"
        try:
            result = invoke(profile_callback=report_profile, usage_callback=report_usage, invocation_id=invocation_id, retry_callback=report_retry)
            outcome = "completed"
            return result
        except ExecutionStopped:
            outcome = "cancelled"
            raise
        except ProviderTimeoutError:
            outcome = "interrupted"
            raise
        finally:
            if active_usage_id:
                self.records.finish_usage(usage_context.run_id, active_usage_id, outcome, structured=agent.provider_id in {"codex", "nvidia"})
