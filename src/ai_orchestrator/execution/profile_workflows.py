"""ExecutionProfiles with explicit feature and persistence dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, ContextManager
from ..account_usage import AccountUsageCache
from ..config import AgentConfig, RoutingConfig
from ..errors import PipelineError
from ..execution import (
    AutomaticModelEscalation,
    QuotaFallbackService,
    TaskProfileRecords,
    TaskProfileService,
    TaskProfileValidator,
    TaskVerificationFailure,
    automatic_model_escalation_matches,
    normalize_agent_id,
    normalize_model,
    normalize_reasoning_effort,
    quota_fallback_matches,
)
from ..execution.provider_choices import ConnectedProviderQueries, ProviderAvailability
from ..integration import uses_shared_workspace
from ..model_selection import CODEX_SOL_MODEL
from ..models import EffortProfileSnapshot, ProfileSource, ResolvedEffortPolicy, RunLockState, RunState, Stage, WorkTask
from ..persistence.execution_records import ExecutionProfilesRecords
from ..persistence.run_lookup import RunLookup, find_task
from ..planner import PlanningError, assign_task_agent_overrides
from ..planning.plan_files import PlanFiles


@dataclass
class ExecutionProfiles:
    records: ExecutionProfilesRecords
    availability: ProviderAvailability
    registered_models: Callable[[], tuple[str, ...]]
    read_agents: Callable[[], dict[str, AgentConfig]]
    agents_settings: Callable[[], tuple[AgentConfig, ...]]
    files: PlanFiles
    lookup: RunLookup
    usage: AccountUsageCache
    connections: ConnectedProviderQueries
    routing_settings: Callable[[], RoutingConfig]
    state_lock: ContextManager[object]

    def validator(self) -> TaskProfileValidator:
        return TaskProfileValidator(
            agents=self.read_agents(), configured_agents=self.agents_settings(),
            registered_models=lambda: tuple(self.registered_models()),
            available_agent=self.availability.require, is_selectable=self.availability.is_selectable,
            reviewer_compatible=self.availability.reviewer_compatible,
        )


    def service(self) -> TaskProfileService:
        return TaskProfileService(
            agents=self.read_agents(),
            records=TaskProfileRecords(
                load_requests=self.records.load_task_execution_profiles,
                save_requests=self.records.save_task_execution_profiles,
                save_state=self.records.save,
                load_policy=self.records.load_effort_policy,
            ),
            validate=self.validated_next_execution_profile,
            find_task=find_task,
            refresh_plan=self.files.refresh_tasks,
        )


    def save_task_execution_profile_locked(
        self, state: RunState, task_id: str, *, agent_id: str, model: str, reasoning_effort: str, expected_profile: dict[str, str]
    ) -> RunState:
        return self.service().save(
                state, task_id, agent_id=agent_id, model=model, reasoning_effort=reasoning_effort, expected_profile=expected_profile,
            )


    def validated_next_execution_profile(
        self, state: RunState, task: WorkTask, agent_id: str, model: str, reasoning_effort: str
    ) -> WorkTask:
        return self.validator().validate_next(state, task, agent_id, model, reasoning_effort)


    def queue_task_execution_profile(
        self, run_id: str, task_id: str, *, agent_id: str, model: str, reasoning_effort: str, expected_profile: dict[str, str]
    ) -> RunState | None:
        execution_operations = {"execute", "resume", "retry-task", "execute-task"}
        lock = self.records.inspect_lock(run_id)
        if lock.state != RunLockState.ACTIVE or lock.operation not in execution_operations:
            return None
        with self.records.planning_chat_lock(run_id):
            lock = self.records.inspect_lock(run_id)
            if lock.state != RunLockState.ACTIVE or lock.operation not in execution_operations:
                return None
            if self.records.load(run_id).stage != Stage.EXECUTING:
                return None
            state = self.lookup.at(run_id, {Stage.EXECUTING})
            return self.service().queue(
                run_id, state, task_id, agent_id=agent_id, model=model, reasoning_effort=reasoning_effort, expected_profile=expected_profile,
            )


    def apply_queued_execution_profiles(self, state: RunState) -> bool:
        return self.service().apply_queued(state)


    def quota(self) -> QuotaFallbackService:
        return QuotaFallbackService(
            agents=self.read_agents(), configured_agents=self.agents_settings(), routing=self.routing_settings(),
            records=TaskProfileRecords(
                load_requests=self.records.load_task_execution_profiles,
                save_requests=self.records.save_task_execution_profiles,
                save_state=self.records.save,
                load_policy=self.records.load_effort_policy,
            ),
            read_usage=self.usage.read, is_selectable=self.availability.is_selectable,
            connected_providers=self.connections.ids, reviewer_compatible=self.availability.reviewer_compatible,
            shared_workspace=uses_shared_workspace, refresh_plan=self.files.refresh_tasks,
        )


    def quota_fallback_matches(self, task: WorkTask, expected: EffortProfileSnapshot, policy: ResolvedEffortPolicy,
                                receipt: dict[str, object]) -> bool:
        return quota_fallback_matches(task, expected, policy, receipt, escalation_matches=automatic_model_escalation_matches)


    def apply_quota_fallbacks(self, state: RunState, ready: list[WorkTask]) -> None:
        self.quota().apply(state, ready)


    def apply_task_agent_overrides(self, state: RunState, overrides: dict[str, str]) -> None:
        normalized = {task_id.strip(): normalize_agent_id(agent_id) for task_id, agent_id in overrides.items()}
        if any(not task_id for task_id in normalized):
            raise PipelineError("task id in provider override must not be empty")
        if any(not agent_id for agent_id in normalized.values()):
            raise PipelineError("task provider override must not be empty")
        for agent_id in normalized.values():
            self.availability.require(agent_id, "execute")
        try:
            assign_task_agent_overrides(
                state.tasks,
                self.agents_settings(),
                self.routing_settings(),
                normalized,
                sequential=uses_shared_workspace(state),
                locked_task_ids=({task.id for task in state.tasks if task.id not in normalized} if state.stage != Stage.PLANNED else None),
            )
        except PlanningError as exc:
            raise PipelineError(str(exc)) from exc
        for task in state.tasks:
            if task.reviewer_agent_id:
                self.availability.require(task.reviewer_agent_id, "review")
        for task_id, agent_id in sorted(normalized.items()):
            find_task(state, task_id).profile_source = ProfileSource.MANUAL
            agent = self.read_agents()[agent_id]
            state.add_event(
                "routing",
                f"{task_id} execution provider selected: {agent.provider_id}/{agent.id}" + (f" model {agent.model}" if agent.model else ""),
            )
        self.records.save(state)


    def validate_task_reasoning_overrides(
        self, state: RunState, overrides: dict[str, str], agent_overrides: dict[str, str], model_overrides: dict[str, str] | None = None
    ) -> None:
        return self.validator().validate_reasoning_overrides(state, overrides, agent_overrides, model_overrides)


    def validate_task_model_overrides(self, state: RunState, overrides: dict[str, str], agent_overrides: dict[str, str]) -> None:
        return self.validator().validate_model_overrides(state, overrides, agent_overrides)


    def apply_task_model_overrides(self, state: RunState, overrides: dict[str, str]) -> None:
        tasks = {task.id: task for task in state.tasks}
        for task_id, raw_model in sorted(overrides.items()):
            model = normalize_model(raw_model)
            task = tasks[task_id]
            if not model and task.provider_id == "codex":
                model = CODEX_SOL_MODEL
            task.model = model
            task.model_selection_reason = ""
            task.profile_source = ProfileSource.MANUAL
            state.add_event("routing", f"{task_id} execution model selected: {model or 'provider default'}")
        self.records.save(state)


    def apply_task_reasoning_overrides(self, state: RunState, overrides: dict[str, str]) -> None:
        tasks = {task.id: task for task in state.tasks}
        for task_id, raw_effort in sorted(overrides.items()):
            effort = normalize_reasoning_effort(raw_effort)
            task = tasks[task_id]
            task.reasoning_effort = effort
            task.profile_source = ProfileSource.MANUAL
            state.add_event("routing", f"{task_id} execution reasoning selected: {effort or 'provider default'}")
        self.records.save(state)


    def promote_automatic_model(self, state: RunState, task: WorkTask, failure: TaskVerificationFailure) -> None:
        AutomaticModelEscalation(
            load_policy=self.records.load_effort_policy,
            load_profiles=self.records.load_task_execution_profiles,
            quota_matches=self.quota_fallback_matches,
            state_lock=self.state_lock,
            save_state=self.records.save,
        ).promote(state, task, failure)
