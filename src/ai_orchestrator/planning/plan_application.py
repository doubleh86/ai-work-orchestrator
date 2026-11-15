"""Apply plan content and receipts without final Run authority."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..document_index import PlanningSourceIndex
from ..errors import PipelineError
from ..models import BootstrapSpec, PlanningApplyRequest, PlanningApplyStatus, RunState, TechStackDecisionStatus, WorkTask, utc_now
from .contracts import Plan
from .features import FeaturePlanningBaseline, feature_plan_tasks
from .task_apply import TaskChangeAssistantMessage, TaskChangePlanBuilder


@dataclass(frozen=True, slots=True)
class PlanContentApplication:
    snapshot_sources: Callable[[RunState, Path, Plan], None]
    review_required: Callable[[], bool]
    replace_decision: Callable[[RunState, Plan], None]
    build_bootstrap: Callable[[RunState, WorkTask], BootstrapSpec]

    def apply(self, state: RunState, plan: Plan) -> None:
        source_root = Path(state.spec_path).expanduser().resolve() if state.spec_path.strip() else None
        if source_root is not None and source_root.is_dir() and plan.source_paths:
            self.snapshot_sources(state, source_root, plan)
        state.server_work = plan.server_work
        state.summary = plan.summary
        previous_profiles = {
            task.id: (
                (task.agent_id, task.provider_id, task.model, task.reasoning_effort),
                task.profile_source, task.effort_baseline_reasoning, task.review_policy_added,
            )
            for task in state.tasks
        }
        for task in plan.tasks:
            previous = previous_profiles.get(task.id)
            if previous is not None and previous[0] == (task.agent_id, task.provider_id, task.model, task.reasoning_effort):
                task.profile_source = previous[1]
                task.effort_baseline_reasoning = previous[2]
                if task.reviewer_agent_id and not self.review_required():
                    task.review_policy_added = previous[3]
        state.tasks = plan.tasks
        state.refresh_task_readiness()
        state.planning_questions = plan.questions
        if state.repository_intent == "new_project":
            decision = state.current_tech_stack_decision()
            questions_before_choice = plan.questions and not plan.tasks and (
                decision is None or decision.status != TechStackDecisionStatus.CONFIRMED
            )
            if plan.tech_stack_options or questions_before_choice:
                self.replace_decision(state, plan)
                state.bootstrap_spec = None
                state.greenfield_phase = "questions_required" if plan.questions else "options_ready"
            else:
                if len(plan.tasks) != 1 or plan.tasks[0].id != "project-bootstrap":
                    raise PipelineError("신규 프로젝트의 다음 계획은 project-bootstrap Task 하나여야 합니다.")
                state.bootstrap_spec = self.build_bootstrap(state, plan.tasks[0])
                state.greenfield_phase = "bootstrap_ready"


@dataclass(frozen=True, slots=True)
class ConversationPlanApplication:
    build_plan: TaskChangePlanBuilder
    clarification_context: Callable[[RunState], str]
    source_index: Callable[[RunState], PlanningSourceIndex | None]
    apply_plan: Callable[[RunState, Plan], RunState]
    task_draft: Callable[[WorkTask], dict[str, object]]
    save_state: Callable[[RunState], None]
    save_chat: Callable[[RunState], None]

    def apply(
        self, state: RunState, *, apply_request: PlanningApplyRequest | None,
        original_drafts: dict[str, dict[str, object]],
    ) -> RunState:
        document = Path(state.spec_snapshot_path).read_text(encoding="utf-8")
        clarification_context = self.clarification_context(state)
        source_index = self.source_index(state)
        plan = self.build_plan(
            state,
            document,
            clarification_context=(
                apply_request.context_snapshot
                if apply_request is not None and apply_request.context_snapshot
                else clarification_context
            ),
            source_index=source_index,
        )
        if apply_request is not None and apply_request.tech_stack_revision and not apply_request.answer_message:
            if plan.tech_stack_options or len(plan.tasks) != 1 or plan.tasks[0].id != "project-bootstrap":
                raise PipelineError("확정한 기술 구성을 유지한 기본 구조 계획이 필요합니다. 구성 결정은 보존됩니다.")
        updated = self.apply_plan(state, plan)
        if apply_request is not None:
            final_drafts = {task.id: self.task_draft(task) for task in updated.tasks}
            apply_request.status = PlanningApplyStatus.SUCCEEDED
            apply_request.completed_at = utc_now()
            apply_request.added_tasks = len(final_drafts.keys() - original_drafts.keys())
            apply_request.updated_tasks = sum(
                original_drafts[task_id] != final_drafts[task_id]
                for task_id in original_drafts.keys() & final_drafts.keys()
            )
            apply_request.unchanged_tasks = len(final_drafts) - apply_request.added_tasks - apply_request.updated_tasks
            self.save_state(updated)
            self.save_chat(updated)
        return updated


@dataclass(frozen=True, slots=True)
class FeaturePlanApplication:
    write_plan: Callable[[RunState, Plan], None]
    append_assistant: TaskChangeAssistantMessage

    def apply(self, state: RunState, plan: Plan, baseline: FeaturePlanningBaseline) -> None:
        state.tasks = feature_plan_tasks(plan, baseline)
        state.server_work = plan.server_work
        state.summary = plan.summary
        state.planning_questions = []
        state.refresh_task_readiness()
        state.revise_plan()
        self.write_plan(
            state,
            Plan(
                summary=state.summary,
                server_work=state.server_work,
                tasks=state.tasks,
                source_paths=plan.source_paths,
                instruction_paths=plan.instruction_paths,
            ),
        )
        self.append_assistant(
            state,
            "기본 구조 검증을 통과해 같은 기술 결정으로 기능 Task를 만들었습니다. 계획을 확인하고 확정해 주세요.",
            counts_as_discussion=False,
        )
