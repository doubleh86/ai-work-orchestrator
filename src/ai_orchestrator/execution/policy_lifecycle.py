"""ExecutionPolicyLifecycle with explicit feature and persistence dependencies."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Callable, ContextManager
from ..config import AgentConfig, PlanningConfig
from ..effort_policy import EffortModePreview
from ..errors import PipelineError
from ..execution import ExecutionPolicyValidator, automatic_model_escalation_matches, build_execution_policy_snapshot
from ..execution.effort_previews import EffortPreviewQueries
from ..execution.policy_snapshot import ExecutionPolicyPreflight
from ..execution.profile_workflows import ExecutionProfiles
from ..execution.provider_choices import ProviderAvailability
from ..models import ResolvedEffortPolicy, RunState
from ..persistence.execution_records import ExecutionPolicyLifecycleRecords


@dataclass
class ExecutionPolicyLifecycle:
    records: ExecutionPolicyLifecycleRecords
    availability: ProviderAvailability
    previews: EffortPreviewQueries
    read_agents: Callable[[], dict[str, AgentConfig]]
    planning_settings: Callable[[], PlanningConfig]
    profiles: ExecutionProfiles

    def begin_effort_execution(
        self, state: RunState, *, agent_overrides: dict[str, str] | None,
        model_overrides: dict[str, str] | None, reasoning_effort_overrides: dict[str, str] | None,
        recover_saved_profiles: bool = False,
        check_blocked_task_ids: frozenset[str] = frozenset(),
    ) -> str:
        saved_policy = self.records.load_effort_policy(state.id)
        active = [binding for binding in saved_policy.execution_bindings if binding.status in {"prepared", "started"}]
        if len(active) > 1 or bool(state.active_policy_id) != bool(state.active_execution_request_id):
            raise PipelineError("effort execution binding and RunState references are inconsistent")
        if active:
            binding = active[0]
            expected = (binding.policy_id, binding.execution_request_id)
            actual = (state.active_policy_id, state.active_execution_request_id)
            if actual not in {("", ""), expected}:
                raise PipelineError("effort execution binding and RunState references are inconsistent")
            if binding.status == "started":
                if actual != expected:
                    raise PipelineError("started effort execution binding has no RunState reference")
                policy = saved_policy.policy(binding.policy_id)
                if policy is None:
                    raise PipelineError("started effort execution policy snapshot is missing")
                self.validate_effort_execution_snapshot(state, policy)
                return binding.execution_request_id
            if actual == expected:
                state.active_policy_id = ""
                state.active_execution_request_id = ""
                self.records.save(state)
            self.records.abandon_effort_execution(state.id, binding.execution_request_id)
            saved_policy = self.records.load_effort_policy(state.id)
        elif state.active_execution_request_id:
            binding = saved_policy.binding(state.active_execution_request_id)
            if binding is None or binding.policy_id != state.active_policy_id or binding.status != "finished":
                raise PipelineError("RunState references a missing or unfinished effort execution binding")
            state.active_policy_id = ""
            state.active_execution_request_id = ""
            self.records.save(state)

        preview = ExecutionPolicyPreflight(
            read_agents=lambda: self.read_agents(), require_confirmed_plan=self.require_confirmed_plan,
            saved_preview=self.previews.build_preview, current_preview=self.previews.preview_effort_mode,
            available_agent=self.availability.require, reviewer_compatible=self.availability.reviewer_compatible,
        ).prepare(
            state, saved_policy, agent_overrides=agent_overrides, model_overrides=model_overrides,
            reasoning_effort_overrides=reasoning_effort_overrides, recover_saved_profiles=recover_saved_profiles,
            check_blocked_task_ids=check_blocked_task_ids,
        )
        if preview is None:
            return ""
        policy = self.resolved_execution_policy(state, preview)
        execution_request_id = str(uuid.uuid4())
        try:
            self.records.prepare_effort_execution(
                state.id, policy, execution_request_id=execution_request_id, expected_revision=saved_policy.revision,
                preserve_reservation=recover_saved_profiles,
            )
            state.active_policy_id = policy.policy_id
            state.active_execution_request_id = execution_request_id
            self.records.save(state)
            self.records.start_effort_execution(state.id, execution_request_id)
        except ValueError as exc:
            raise PipelineError(f"effort execution policy could not start: {exc}") from exc
        return execution_request_id


    def resolved_execution_policy(self, state: RunState, preview: EffortModePreview) -> ResolvedEffortPolicy:
        return build_execution_policy_snapshot(
            state, preview, agents=self.read_agents(), default_planning_agent_id=self.planning_settings().agent_id,
        )


    def validate_effort_execution_snapshot(self, state: RunState, policy: ResolvedEffortPolicy) -> None:
        ExecutionPolicyValidator(
            agents=self.read_agents(),
            load_profiles=self.records.load_task_execution_profiles,
            escalation_matches=automatic_model_escalation_matches,
            quota_matches=self.profiles.quota_fallback_matches,
        ).validate(state, policy)


    def finish_effort_execution_binding(self, state: RunState) -> RunState:
        binding_request_id = state.active_execution_request_id
        if binding_request_id:
            self.records.finish_effort_execution(state.id, binding_request_id)
            saved = self.records.load(state.id)
            if saved.active_execution_request_id != binding_request_id:
                raise PipelineError("completed execution no longer references its effort policy binding")
            saved.active_policy_id = ""
            saved.active_execution_request_id = ""
            self.records.save(saved)
            return saved
        return state


    @staticmethod
    def require_confirmed_plan(state: RunState) -> None:
        if not state.plan_is_approved:
            raise PipelineError("task plan must be reviewed and confirmed before execution")


    @staticmethod
    def require_confirmed_profiles(
        state: RunState, agent_overrides: dict[str, str], model_overrides: dict[str, str], reasoning_effort_overrides: dict[str, str]
    ) -> None:
        if state.plan_revision == 0:
            return
        tasks = {task.id: task for task in state.tasks}
        changed = {task_id for task_id, agent_id in agent_overrides.items() if task_id not in tasks or agent_id != tasks[task_id].agent_id}
        changed.update(task_id for task_id, model in model_overrides.items() if task_id not in tasks or model != tasks[task_id].model)
        changed.update(
            task_id for task_id, effort in reasoning_effort_overrides.items() if task_id not in tasks or effort != tasks[task_id].reasoning_effort
        )
        if changed:
            raise PipelineError(
                "execution profile changed after plan confirmation; save and " "confirm the plan again: " + ", ".join(sorted(changed))
            )
