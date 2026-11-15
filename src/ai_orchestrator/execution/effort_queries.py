"""Read effort controls and previews with caller lookups."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable, Protocol

from ..config import AgentConfig
from ..effort_policy import EffortModePreview
from ..errors import PipelineError
from ..models import EffortMode, EffortPolicyState, ResolvedEffortPolicy, RunLockState, RunLockStatus, RunState, RunStep, Stage, TaskStatus
from .profiles import ReviewerCompatibility


class EffortPolicyLoader(Protocol):
    def __call__(self, run_id: str, *, archived_chat: bool = False) -> EffortPolicyState: ...


class EffortPreviewQuery(Protocol):
    def __call__(self, run_id: str, mode: EffortMode | str, *, expected_revision: int) -> EffortModePreview: ...


@dataclass(frozen=True, slots=True)
class EffortQueryRecords:
    load_state: Callable[[str], RunState]
    load_policy: EffortPolicyLoader
    inspect_lock: Callable[[str], RunLockStatus]
    inspect_chat_lock: Callable[[str], RunLockStatus]
    has_archived_policy: Callable[[str], bool]


def effort_state_key(state: RunState) -> tuple[object, ...]:
    return (
        state.stage, state.plan_revision, state.plan_approved_revision, state.active_step, state.failed_step,
        state.active_policy_id, state.active_execution_request_id,
        bool(state.archive), tuple((task.id, task.status) for task in state.tasks),
    )


def effort_reservation_allowed(state: RunState) -> bool:
    return not state.archive and (
        state.stage in {Stage.PLANNED, Stage.EXECUTING}
        or (state.stage == Stage.FAILED and state.failed_step == RunStep.AGENT_EXECUTION)
    )


@dataclass(frozen=True, slots=True)
class EffortQueries:
    records: EffortQueryRecords
    build_preview: EffortPreviewQuery
    read_agents: Callable[[], tuple[AgentConfig, ...]]
    is_selectable: Callable[[AgentConfig, str], bool]
    connected_providers: Callable[[set[str]], set[str]]
    reviewer_compatible: ReviewerCompatibility

    def control(self, run_id: str, *, expected_state: RunState | None = None) -> dict[str, object]:
        state = self.records.load_state(run_id)
        policy = self.records.load_policy(run_id)
        current_policy: ResolvedEffortPolicy | None = None
        binding_status = ""
        if state.active_policy_id or state.active_execution_request_id:
            if not state.active_policy_id or not state.active_execution_request_id:
                raise PipelineError("effort execution policy reference is inconsistent")
            binding = policy.binding(state.active_execution_request_id)
            if binding is None or binding.policy_id != state.active_policy_id:
                raise PipelineError("effort execution policy reference is inconsistent")
            current_policy = policy.policy(binding.policy_id)
            if current_policy is None:
                raise PipelineError("effort execution policy snapshot is missing")
            binding_status = binding.status
        mode = policy.pending_execution_mode or policy.selected_mode
        preview = self.build_preview(run_id, mode, expected_revision=policy.revision) if mode else None
        lock = self.records.inspect_lock(run_id)
        chat_lock = self.records.inspect_chat_lock(run_id)
        latest = self.records.load_state(run_id)
        consistent = effort_state_key(state) == effort_state_key(latest)
        if expected_state is not None:
            consistent = consistent and effort_state_key(state) == effort_state_key(expected_state)
        editable = (
            consistent and not state.archive and state.stage == Stage.PLANNED
            and all(task.status == TaskStatus.PENDING for task in state.tasks)
            and lock.state == RunLockState.UNLOCKED and chat_lock.state == RunLockState.UNLOCKED
        )
        planning_history = (
            self.records.load_policy(run_id, archived_chat=True)
            if state.archive is not None and self.records.has_archived_policy(run_id) else policy
        )
        planning_binding = planning_history.planning_bindings[-1] if planning_history.planning_bindings else None
        planning_policy = planning_history.policy(planning_binding.policy_id) if planning_binding is not None else None
        return {
            "policy_revision": policy.revision, "plan_revision": state.plan_revision, "stage": state.stage.value,
            "selected_mode": policy.selected_mode.value if policy.selected_mode else None,
            "pending_execution_mode": policy.pending_execution_mode.value if policy.pending_execution_mode else None,
            "pending_request_id": policy.pending_request_id,
            "last_mutation": asdict(policy.mutation_receipts[-1]) if policy.mutation_receipts else None,
            "current_policy": current_policy.to_dict() if current_policy is not None else None,
            "current_binding_status": binding_status,
            "planning_policy": planning_policy.to_dict() if planning_policy is not None else None,
            "planning_request_status": planning_binding.status if planning_binding is not None else "",
            "planning_request_started_at": planning_binding.started_at if planning_binding is not None else "",
            "requires_plan_review": bool(preview and preview.requires_plan_review),
            "manual_exception_count": len(preview.manual_exception_ids) if preview else 0,
            "can_select_plan": editable, "can_apply_plan": editable,
            "can_reserve": consistent and effort_reservation_allowed(state),
            "can_cancel_reservation": consistent and not state.archive and policy.pending_execution_mode is not None,
            "consistent": consistent,
            "reason": "" if consistent else "작업 그룹 상태가 변경되었습니다. 다시 조회한 뒤 변경하세요.",
        }

    def desktop_preview(self, run_id: str, mode: str, *, expected_revision: int) -> dict[str, object]:
        preview = self.build_preview(run_id, mode, expected_revision=expected_revision)
        state = self.records.load_state(run_id)
        if state.plan_revision != preview.plan_revision:
            raise PipelineError("plan revision changed while previewing the effort mode")
        payload = asdict(preview)
        rows = []
        tasks = {task.id: task for task in state.tasks}
        review_agents = tuple(
            agent for agent in self.read_agents() if self.is_selectable(agent, "review")
        ) if any(item.review.policy_added for item in preview.tasks) else ()
        connected_providers = self.connected_providers({agent.provider_id for agent in review_agents})
        for item in preview.tasks:
            task = tasks[item.task_id]
            options = [
                {"agent_id": agent.id, "provider_id": agent.provider_id, "model": agent.model}
                for agent in review_agents
                if agent.provider_id in connected_providers
                and self.reviewer_compatible(task, agent, policy_added=True)
                and (set(task.capabilities) & set(agent.capabilities) or "general" in agent.capabilities)
            ] if item.review.policy_added else []
            rows.append({**asdict(item), "reviewer_options": options})
        payload["tasks"] = rows
        payload["can_apply"] = not any(
            effect.endswith((":mode_profile_baseline_missing", ":reviewer_unavailable")) for effect in preview.unsupported_effects
        ) and not any(item.review.requires_reviewer and not item.review.policy_added for item in preview.tasks) and all(
            not item.review.policy_added or row["reviewer_options"] for item, row in zip(preview.tasks, rows, strict=True)
        )
        return payload
