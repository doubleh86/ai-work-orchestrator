"""Task policy and invocation inputs through a caller-owned provider."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Generic, Mapping, Protocol, TypeVar

from ..codex_sdk import CodexSdkExecutionProfile, CodexSdkProgress
from ..config import AgentConfig
from ..errors import PipelineError
from ..execution_control import CancellationSignal
from ..models import EffortMode, EffortPolicyState, ResolvedEffortPolicy, RunState, TaskAction, WorkTask
from ..usage import UsageContext

StopSignal = TypeVar("StopSignal", bound=CancellationSignal)
InvocationStopSignal = TypeVar("InvocationStopSignal", bound=CancellationSignal, contravariant=True)


class TaskProviderInvocation(Protocol[InvocationStopSignal]):
    def __call__(
        self, *, agent: AgentConfig, command_template: tuple[str, ...], replacements: dict[str, str],
        cwd: Path, prompt: str, prompt_path: str, log_path: Path, action: str, usage_context: UsageContext,
        task_id: str, model: str, reasoning_effort: str, attempt_id: str, invocation_id: str,
        cancel_signal: InvocationStopSignal | None, progress_callback: Callable[[CodexSdkProgress], None],
        profile_callback: Callable[[CodexSdkExecutionProfile], None] | None,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class TaskInvocation(Generic[StopSignal]):
    read_agents: Callable[[], Mapping[str, AgentConfig]]
    load_policy: Callable[[str], EffortPolicyState]
    validate_snapshot: Callable[[RunState, ResolvedEffortPolicy], None]
    guidance: Callable[[str, EffortMode], str]
    agent_command: Callable[[AgentConfig, str], tuple[str, ...]]
    with_model: Callable[[AgentConfig, tuple[str, ...], str], tuple[str, ...]]
    with_reasoning: Callable[[AgentConfig, tuple[str, ...], str, str], tuple[str, ...]]
    stop_signal: Callable[[RunState, WorkTask], StopSignal | None]
    record_progress: Callable[[RunState, WorkTask, CodexSdkProgress], None]
    record_profile: Callable[[RunState, WorkTask, CodexSdkExecutionProfile], None]
    invoke: TaskProviderInvocation[StopSignal]

    def prepare_policy(
        self, state: RunState, task: WorkTask, agent: AgentConfig, prompt: str, action: TaskAction,
    ) -> tuple[ResolvedEffortPolicy | None, str]:
        policy = None
        if state.active_policy_id or state.active_execution_request_id:
            if not state.active_policy_id or not state.active_execution_request_id:
                raise PipelineError("effort execution references are incomplete before AI invocation")
            saved_policy = self.load_policy(state.id)
            binding = saved_policy.binding(state.active_execution_request_id)
            if binding is None or binding.status != "started" or binding.policy_id != state.active_policy_id:
                raise PipelineError("effort execution policy was not started before AI invocation")
            policy = saved_policy.policy(binding.policy_id)
            if policy is None:
                raise PipelineError("started effort execution policy snapshot is missing")
            self.validate_snapshot(state, policy)
            expected_agent_id = task.reviewer_agent_id if action == TaskAction.REVIEW else task.agent_id
            if agent.id != expected_agent_id:
                raise PipelineError(f"started effort policy agent differs for task {task.id}")
            configured = self.read_agents().get(agent.id)
            if configured is None or configured.provider_id != agent.provider_id or configured.model != agent.model:
                raise PipelineError(f"started effort policy invocation runtime differs for task {task.id}")
            prompt = self.guidance(prompt, policy.mode)
        return policy, prompt

    def run(self, state: RunState, task: WorkTask, agent: AgentConfig, prompt: str, log_path: Path, action: TaskAction) -> str:
        policy, prompt = self.prepare_policy(state, task, agent, prompt, action)
        command_template = self.agent_command(agent, action.value)
        if action != TaskAction.REVIEW:
            command_template = self.with_model(agent, command_template, task.model)
            command_template = self.with_reasoning(agent, command_template, task.reasoning_effort, task.model)
        replacements = {
            "{worktree}": task.worktree,
            "{prompt}": task.prompt_path,
            "{task_id}": task.id,
            "{run_id}": state.id,
        }
        return self.invoke(
            agent=agent,
            command_template=command_template,
            replacements=replacements,
            cwd=Path(task.worktree),
            prompt=prompt,
            prompt_path=task.prompt_path,
            log_path=log_path,
            action=action.value,
            usage_context=UsageContext(
                state.id, action.value, execution_request_id=state.active_execution_request_id,
                policy_id=policy.policy_id if policy else "", mode=policy.mode.value if policy else None,
            ),
            task_id=task.id,
            model=agent.model if action == TaskAction.REVIEW else task.model,
            reasoning_effort="" if action == TaskAction.REVIEW else task.reasoning_effort,
            attempt_id=task.last_attempt_id or f"{task.id}:{task.attempt_count}:{action.value}",
            invocation_id=task.active_invocation_id,
            cancel_signal=self.stop_signal(state, task),
            progress_callback=lambda progress: self.record_progress(state, task, progress),
            profile_callback=((lambda profile: self.record_profile(state, task, profile)) if action != TaskAction.REVIEW else None),
        )
