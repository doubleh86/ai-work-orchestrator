"""Typed provider call endpoints using caller-owned resource factories."""

from __future__ import annotations

from ..errors import ProviderCapacityError
from .provider_runner import ProviderInputLimitError
from ..errors import ProviderInputTooLarge
from ..errors import ProviderRequestLimitError
from .provider_runner import ProviderRequestLimited
from .provider_runner import ProviderTimedOut
from ..errors import ProviderTimeoutError
from .provider_runner import ProviderUnavailable

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Generic, TypeVar

from ..codex_sdk import CodexSdkExecutionProfile, CodexSdkProgress
from ..config import AgentConfig
from ..errors import PipelineError
from ..usage import UsageContext, UsageObservation
from .invocation import ProviderInvocation
from .provider_runner import ProviderRunError, ProviderRunner, ProviderStopSignal

StopSignal = TypeVar("StopSignal", bound=ProviderStopSignal)


@dataclass
class ProviderRuntime(Generic[StopSignal]):
    invocation: Callable[[], ProviderInvocation[StopSignal]]
    runner: Callable[[], ProviderRunner]
    translate_error: Callable[[ProviderRunError], PipelineError]

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
        invocation = self.invocation()
        return invocation.invoke(
            agent=agent, command_template=command_template, replacements=replacements, cwd=cwd, prompt=prompt,
            prompt_path=prompt_path, log_path=log_path, action=action, task_id=task_id, timeout_seconds=timeout_seconds,
            model=model, reasoning_effort=reasoning_effort, progress_callback=progress_callback, profile_callback=profile_callback,
            sdk_conversation_id=sdk_conversation_id, attempt_id=attempt_id, invocation_id=invocation_id,
            cancel_signal=cancel_signal, usage_context=usage_context,
        )

    def run(
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
        usage_callback: Callable[[UsageObservation], None] | None = None,
        retry_callback: Callable[[str | None], None] | None = None,
    ) -> str:
        runner = self.runner()
        try:
            return runner.run(
                agent=agent,
                command_template=command_template,
                replacements=replacements,
                cwd=cwd,
                prompt=prompt,
                prompt_path=prompt_path,
                log_path=log_path,
                action=action,
                task_id=task_id,
                timeout_seconds=timeout_seconds,
                model=model,
                reasoning_effort=reasoning_effort,
                progress_callback=progress_callback,
                profile_callback=profile_callback,
                sdk_conversation_id=sdk_conversation_id,
                attempt_id=attempt_id,
                invocation_id=invocation_id,
                cancel_signal=cancel_signal,
                usage_callback=usage_callback,
                retry_callback=retry_callback,
            )
        except ProviderRunError as exc:
            raise self.translate_error(exc) from exc.__cause__


def translate_provider_error(error: ProviderRunError) -> PipelineError:
    for source, target in (
        (ProviderInputLimitError, ProviderInputTooLarge), (ProviderTimedOut, ProviderTimeoutError),
        (ProviderRequestLimited, ProviderRequestLimitError), (ProviderUnavailable, ProviderCapacityError),
    ):
        if isinstance(error, source):
            return target(str(error))
    return PipelineError(str(error))
