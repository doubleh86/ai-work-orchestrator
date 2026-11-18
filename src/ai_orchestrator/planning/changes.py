"""Validate and combine plan changes under caller-owned transactions."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable, Protocol, Sequence

from ..config import AgentConfig, RoutingConfig
from ..errors import PipelineError
from ..models import (
    EffortMode, PlanningApplyRequest, PlanningApplyStatus, ProfileSource, ReviewStatus,
    RunState, RunStep, Stage, TaskAction, TaskStatus, WorkTask,
)
from .assignment import assign_plan_agents, select_agent_for_provider
from .contracts import PLAN_MARKER, Plan, PlanningError
from .protocol import parse_structured_plan
from .validation import validate_task_graph, validate_user_checks


RESULT_REVISION_PROPOSAL_MARKER = "AI_RESULT_REVISION_PROPOSAL:"


class DraftReviewerCompatibility(Protocol):
    def __call__(self, task: WorkTask, reviewer: AgentConfig, *, policy_added: bool) -> bool: ...


@dataclass(frozen=True, slots=True)
class PlanDraftValidator:
    plan_paths: Callable[[RunState], tuple[list[str], list[str]]]
    read_execution_agents: Callable[[], tuple[AgentConfig, ...]]
    protected_bootstrap: Callable[[RunState], WorkTask | None]
    read_agents: Callable[[], tuple[AgentConfig, ...]]
    read_routing: Callable[[], RoutingConfig]
    registered_models: Callable[[], tuple[str, ...]]
    selected_mode: Callable[[str], EffortMode | None]
    shared_workspace: Callable[[RunState], bool]
    available_agent: Callable[[str, str], AgentConfig]
    reviewer_compatible: DraftReviewerCompatibility

    def validate(
        self, state: RunState, task_drafts: list[dict[str, object]], *, initial_effort_mode: EffortMode | None = None,
        execution_agents: tuple[AgentConfig, ...] | None = None,
    ) -> Plan:
        source_paths, instruction_paths = self.plan_paths(state)
        summary = state.summary.strip() or f"Task {len(task_drafts)}개 계획"
        payload = {
            "summary": summary,
            "server_work": state.server_work,
            "source_paths": source_paths,
            "instruction_paths": instruction_paths,
            "tasks": task_drafts,
            "questions": [],
        }
        try:
            plan = parse_structured_plan(
                f"{PLAN_MARKER} " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")), require_korean_questions=True
            )
            validate_user_checks(plan.tasks, state.user_check_plan)
            if execution_agents is None:
                execution_agents = self.read_execution_agents()
            protected_bootstrap = self.protected_bootstrap(state)
            assignable_plan = plan
            if protected_bootstrap is not None:
                assignable_plan = Plan(
                    summary=plan.summary,
                    server_work=plan.server_work,
                    tasks=[task for task in plan.tasks if task.id != protected_bootstrap.id],
                    questions=plan.questions,
                    source_paths=plan.source_paths,
                    instruction_paths=plan.instruction_paths,
                )
            existing = {task.id: task for task in state.tasks}
            preserved_profile_ids: set[str] = set()
            for task in assignable_plan.tasks:
                previous = existing.get(task.id)
                selected = (task.provider_id, task.model, task.reasoning_effort)
                unchanged = previous is not None and selected == (previous.provider_id, previous.model, previous.reasoning_effort)
                preserve = unchanged and previous.profile_source in {ProfileSource.MANUAL, ProfileSource.LEGACY}
                if preserve:
                    preserved_profile_ids.add(task.id)
                elif unchanged and task.provider_id == "codex" and previous.profile_source == ProfileSource.MODE:
                    # An existing automatic profile is a result, not a new recommendation.
                    task.model = ""
                    task.reasoning_effort = previous.effort_baseline_reasoning or ""
                if preserve or (not unchanged and any(selected)):
                    task.profile_source = ProfileSource.MANUAL
                    task.agent_id = (previous.agent_id if previous and previous.provider_id == task.provider_id
                                     else select_agent_for_provider(task, execution_agents, task.provider_id, purpose="execution").id)
            assign_plan_agents(
                assignable_plan,
                self.read_agents(),
                self.read_routing(),
                execution_agent_ids={agent.id for agent in execution_agents},
                additional_models={"nvidia": self.registered_models()},
                effort_mode=initial_effort_mode or self.selected_mode(state.id),
                sequential=self.shared_workspace(state),
                preserved_profile_ids=frozenset(preserved_profile_ids),
            )
            drafts = {str(draft.get("id", "")).strip(): draft for draft in task_drafts}
            for task in plan.tasks:
                previous = existing.get(task.id)
                draft = drafts[task.id]
                selected = (
                    str(draft.get("provider_id") or "").strip().casefold(),
                    str(draft.get("model") or "").strip(),
                    str(draft.get("reasoning_effort") or "").strip().casefold(),
                )
                if previous is None:
                    if any(selected):
                        task.profile_source = ProfileSource.MANUAL
                elif selected == (previous.provider_id, previous.model, previous.reasoning_effort):
                    task.profile_source = previous.profile_source
                    task.effort_baseline_reasoning = previous.effort_baseline_reasoning
                else:
                    task.profile_source = ProfileSource.MANUAL
                if task.profile_source == ProfileSource.MANUAL:
                    task.effort_baseline_reasoning = None
                    task.model_selection_reason = ""
                if previous is not None and previous.reviewer_agent_id and not self.read_routing().review_required:
                    reviewer = self.available_agent(previous.reviewer_agent_id, "review")
                    if not self.reviewer_compatible(task, reviewer, policy_added=previous.review_policy_added):
                        raise PipelineError(f"reviewer must use a different provider for task {task.id}")
                    if not (set(task.capabilities) & set(reviewer.capabilities) or "general" in reviewer.capabilities):
                        raise PipelineError(f"reviewer lacks required capability for task {task.id}")
                    task.reviewer_agent_id = reviewer.id
                    task.reviewer_provider_id = reviewer.provider_id
                    task.reviewer_model = reviewer.model
                    task.review_policy_added = previous.review_policy_added
                    task.review_status = ReviewStatus.PENDING
        except PlanningError as exc:
            raise PipelineError(f"invalid task plan: {exc}") from exc
        if not state.summary.strip():
            state.summary = summary
        return plan


@dataclass(frozen=True, slots=True)
class PendingTaskPlan:
    tasks: list[WorkTask]
    prepared_task_ids: set[str]


def merge_pending_task_plan(
    state: RunState, plan: Plan, original_tasks: Sequence[WorkTask], *,
    task_editable: Callable[[RunState, WorkTask], bool], task_draft: Callable[[WorkTask], dict[str, object]],
) -> PendingTaskPlan:
    if plan.questions:
        raise PlanningError("추가 확인이 필요합니다: " + " / ".join(plan.questions))
    proposals = {task.id: task for task in plan.tasks}
    protected_ids = {task.id for task in original_tasks if not task_editable(state, task)}
    if not protected_ids <= proposals.keys():
        raise PlanningError("기존 Task ID를 삭제하거나 변경할 수 없습니다.")
    prepared_task_ids = {
        task.id for task in original_tasks if task_editable(state, task)
    }
    merged = []
    for original in original_tasks:
        if original.id not in proposals:
            continue
        task = deepcopy(original)
        proposal = proposals.pop(task.id)
        if task_editable(state, task):
            profile_changed = (
                task.agent_id, task.provider_id, task.model, task.reasoning_effort
            ) != (proposal.agent_id, proposal.provider_id, proposal.model, proposal.reasoning_effort)
            changed = task_draft(task) != task_draft(proposal)
            for field in (
                "title",
                "description",
                "capabilities",
                "dependencies",
                "is_prerequisite",
                "acceptance_criteria",
                "expected_paths",
                "forbidden_paths",
                "verify_commands",
                "risk_level",
                "agent_id",
                "provider_id",
                "model",
                "reasoning_effort",
                "reviewer_agent_id",
                "reviewer_provider_id",
                "reviewer_model",
                "routing_reason",
                "routing_confidence",
            ):
                setattr(task, field, deepcopy(getattr(proposal, field)))
            if profile_changed:
                task.profile_source = ProfileSource.ROUTING
            if changed and task.status == TaskStatus.FAILED:
                task.failed_action = TaskAction.EXECUTE
        merged.append(task)
    prepared_task_ids.update(proposals)
    merged.extend(proposals.values())
    prepared_task_ids.intersection_update(task.id for task in merged)
    protected = {task.id: deepcopy(task) for task in original_tasks if not task_editable(state, task)}
    ordered = validate_task_graph(merged)
    validate_user_checks(ordered, state.user_check_plan)
    return PendingTaskPlan([protected.get(task.id, task) for task in ordered], prepared_task_ids)


@dataclass(frozen=True, slots=True)
class PlanningApplyRequests:
    append_user: Callable[[RunState, str], None]
    clarification_context: Callable[[RunState], str]

    def create(
        self,
        state: RunState,
        request_id: str,
        expected_revision: int,
        conversation_revision: int,
        *,
        status: PlanningApplyStatus,
        answer_message: str = "",
        tech_stack_revision: int | None = None,
    ) -> PlanningApplyRequest:
        if state.plan_revision != expected_revision:
            raise PipelineError(
                f"계획이 변경되었습니다. 현재 revision {state.plan_revision}을 확인한 뒤 다시 반영해 주세요."
            )
        if state.planning_conversation_revision != conversation_revision:
            raise PipelineError(
                "Planning 대화가 변경되었습니다. 최신 대화를 확인한 뒤 다시 반영해 주세요."
            )
        same_revision = next(
            (
                request
                for request in reversed(state.planning_apply_requests)
                if request.conversation_revision == conversation_revision
                and request.status in {PlanningApplyStatus.QUEUED, PlanningApplyStatus.APPLYING, PlanningApplyStatus.SUCCEEDED}
            ),
            None,
        )
        if same_revision is not None and not answer_message:
            return same_revision
        if conversation_revision <= state.planning_applied_conversation_revision and not answer_message:
            raise PipelineError("Task에 반영할 새 Planning 대화 내용이 없습니다.")
        if answer_message:
            self.append_user(state, answer_message)
        request = PlanningApplyRequest(
            request_id=request_id,
            conversation_revision=conversation_revision,
            plan_revision=expected_revision,
            context_snapshot=self.clarification_context(state),
            status=status,
            answer_message=answer_message,
            answer_conversation_revision=state.planning_conversation_revision,
            tech_stack_revision=tech_stack_revision or 0,
        )
        state.planning_apply_requests.append(request)
        return request


def parse_result_revision_proposal(
    state: RunState, output: str, *, available_paths: Callable[[Sequence[WorkTask]], set[str]]
) -> dict[str, object]:
    matches = [line[len(RESULT_REVISION_PROPOSAL_MARKER):].strip() for line in output.splitlines()
               if line.startswith(RESULT_REVISION_PROPOSAL_MARKER)]
    if len(matches) != 1:
        raise PipelineError("AI 수정 제안 응답 형식이 올바르지 않습니다.")
    try:
        raw = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        raise PipelineError("AI 수정 제안 JSON을 해석할 수 없습니다.") from exc
    if not isinstance(raw, dict):
        raise PipelineError("AI 수정 제안 형식이 올바르지 않습니다.")
    summary, reason, question = (raw.get(key, "") for key in ("summary", "reason", "question"))
    task_ids, paths = raw.get("task_ids"), raw.get("paths")
    if not all(isinstance(value, str) and len(value) <= limit for value, limit in ((summary, 1200), (reason, 1200), (question, 500))):
        raise PipelineError("AI 수정 제안 설명 길이나 형식이 올바르지 않습니다.")
    if not isinstance(task_ids, list) or not isinstance(paths, list) or any(not isinstance(value, str) for value in [*task_ids, *paths]):
        raise PipelineError("AI 수정 제안 대상 형식이 올바르지 않습니다.")
    task_ids = list(dict.fromkeys(task_ids))
    paths = list(dict.fromkeys(paths))
    task_by_id = {task.id: task for task in state.tasks}
    if any(task_id not in task_by_id for task_id in task_ids):
        raise PipelineError("AI가 원본 결과에 없는 Task를 제안했습니다.")
    selected = [task_by_id[task_id] for task_id in task_ids]
    if any(path not in available_paths(selected) for path in paths):
        raise PipelineError("AI가 원본 결과에 없는 변경 파일을 제안했습니다.")
    if question:
        return {"status": "needs_clarification", "summary": summary, "reason": reason,
                "task_ids": [], "paths": [], "question": question, "next_action": ""}
    if not summary or not reason or not selected:
        raise PipelineError("AI가 수정 대상과 근거를 확정하지 못했습니다. 요청을 구체화해 다시 시도해 주세요.")
    if state.stage == Stage.FAILED and state.failed_step == RunStep.AGENT_EXECUTION:
        if len(selected) != 1 or selected[0].status != TaskStatus.FAILED:
            raise PipelineError("실패한 그룹에서는 실패 Task 한 개를 특정해야 합니다.")
        next_action = "retry_task"
    elif state.stage == Stage.FAILED:
        next_action = "recovery"
    elif state.archive is None and state.stage in {Stage.PLANNED, Stage.EXECUTING, Stage.READY_TO_MERGE}:
        next_action = "same_group_plan"
    else:
        next_action = "linked_group"
    return {"status": "ready", "summary": summary, "reason": reason,
            "task_ids": task_ids, "paths": paths, "question": "", "next_action": next_action}
