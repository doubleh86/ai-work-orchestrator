"""Compose provider factories over the existing per-Pipeline resources."""

from __future__ import annotations

from typing import TYPE_CHECKING
from .execution import ProviderInvocation, InvocationUsageRecords, ProviderRunner, ProviderRuntimeOptions
from .execution.lifecycle import StoredStopSignal
from .execution.provider_connection import ProviderConnectionProbes
from .execution.provider_runtime import ProviderRuntime, translate_provider_error


if TYPE_CHECKING:
    from .pipeline_bootstrap import PipelineResources


def build_provider_runtime(resources: PipelineResources, probes: ProviderConnectionProbes) -> ProviderRuntime[StoredStopSignal]:
    def runner() -> ProviderRunner:
        return ProviderRunner(
            ProviderRuntimeOptions(
                resources.repo, resources.config.execution.agent_timeout_seconds, resources.config.worker_mcp_servers, resources.store.root,
            ),
            codex_sdk=resources.codex_sdk, claude_api_key=resources.claude_api_key, nvidia_api_key=resources.nvidia_api_key,
            nvidia_model_api_keys=resources.nvidia_model_api_keys, resolve_executable=lambda value: probes.resolve_executable(value),
            terminate_process=ProviderRunner.terminate_process,
        )

    def invocation() -> ProviderInvocation[StoredStopSignal]:
        return ProviderInvocation(
            resources.repo, resources.config.worker_mcp_servers,
            InvocationUsageRecords(resources.store.begin_usage, resources.store.update_usage_model,
                                   resources.store.observe_usage, resources.store.finish_usage),
            runtime.run,
        )

    runtime: ProviderRuntime[StoredStopSignal] = ProviderRuntime(invocation, runner, translate_provider_error)
    return runtime
