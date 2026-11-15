"""Validate and record one automatic model escalation with caller state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, ContextManager

from ..model_selection import CODEX_LUNA_MODEL, CODEX_SOL_MODEL, CODEX_TERRA_MODEL
from ..models import EffortPolicyState, EffortProfileSnapshot, ProfileSource, ResolvedEffortPolicy, RunState, TaskAction, WorkTask
from .errors import TaskVerificationFailure


def automatic_model_escalation_matches(task: WorkTask, expected: EffortProfileSnapshot, policy: ResolvedEffortPolicy) -> bool:
    index = task.model_escalation_result_index
    if not (policy.policy_version >= 3 and task.model_escalation_policy_id == policy.policy_id
            and type(index) is int and 0 <= index < len(task.action_results)):
        return False
    evidence = task.action_results[index]
    return bool(
        expected.provider_id == "codex" and expected.model in {CODEX_LUNA_MODEL, CODEX_TERRA_MODEL}
        and expected.profile_source == ProfileSource.MODE
        and (task.agent_id, task.provider_id, task.model, task.reasoning_effort, task.profile_source)
        == (expected.agent_id, "codex", CODEX_SOL_MODEL, "high", ProfileSource.MODE)
        and evidence.action == TaskAction.VERIFY and evidence.status == "failed"
        and evidence.verification_failure_kind == "command_failed"
    )


@dataclass(frozen=True, slots=True)
class AutomaticModelEscalation:
    load_policy: Callable[[str], EffortPolicyState]
    load_profiles: Callable[[str], dict[str, dict[str, object]]]
    quota_matches: Callable[[WorkTask, EffortProfileSnapshot, ResolvedEffortPolicy, dict[str, object]], bool]
    state_lock: ContextManager[object]
    save_state: Callable[[RunState], None]

    def promote(self, state: RunState, task: WorkTask, failure: TaskVerificationFailure) -> None:
        if (task.provider_id != "codex" or task.model not in {CODEX_LUNA_MODEL, CODEX_TERRA_MODEL} or task.profile_source != ProfileSource.MODE
                or task.model_escalation_result_index >= 0 or not state.active_policy_id):
            return
        environment_errors = (
            ".net sdk", "no sdks were found", "global.json", "msb4236", "nu1301", "permission denied",
            "access is denied", "connection refused", "name resolution", "network is unreachable",
        )
        if any(marker in failure.output.casefold() for marker in environment_errors):
            return
        saved = self.load_policy(state.id)
        policy = saved.policy(state.active_policy_id)
        binding = saved.binding(state.active_execution_request_id)
        if policy is None or binding is None or binding.status != "started" or binding.policy_id != policy.policy_id:
            return
        expected = dict(policy.task_profiles).get(task.id)
        if expected is None:
            return
        receipt = self.load_profiles(state.id).get(f"{task.id}@{policy.policy_id}", {})
        if self.quota_matches(task, expected, policy, receipt):
            expected = EffortProfileSnapshot.from_dict(receipt["quota_fallback"])
        with self.state_lock:
            previous = (task.model, task.reasoning_effort, task.model_escalation_policy_id, task.model_escalation_result_index)
            task.model, task.reasoning_effort = CODEX_SOL_MODEL, "high"
            task.model_escalation_policy_id = policy.policy_id
            task.model_escalation_result_index = len(task.action_results) - 1
            if not automatic_model_escalation_matches(task, expected, policy):
                task.model, task.reasoning_effort, task.model_escalation_policy_id, task.model_escalation_result_index = previous
                return
            source_label = "6.1 Terra" if previous[0] == CODEX_TERRA_MODEL else "Luna"
            task.model_selection_reason = f"코드 검증 실패 수정 · {source_label}에서 6.1 Sol로 1회 승격"
            state.add_event("model_selection", f"{task.id}: {task.model_selection_reason}")
            self.save_state(state)
