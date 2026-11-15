"""Apply planning outcomes with the existing rollback and Run receipts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from .ai import PlanningAI
from .messages import PlanningMessages
from .plan_files import PlanFiles
from ..codex_sdk import CodexSdkManager
from ..document_index import DocumentIndexError as DocumentIndexError
from ..errors import PipelineError
from ..execution import TaskExecutionPreparation
from ..execution.preparation import advance_completed_tasks
from ..models import PlanningApplyRequest, PlanningApplyStatus, RunState, RunStep, Stage, TaskStatus, utc_now
from ..planner import Plan, PlanningError, structured_plan_dict
from .conversation import planning_conversation_id, planning_response_text, task_plan_draft
from .features import feature_planning_baseline, feature_planning_context
from .plan_application import ConversationPlanApplication, FeaturePlanApplication, PlanContentApplication
from .profiles import PlanningProfiles
from .source_indexes import PlanningSourceIndexes
from .task_apply import PendingTaskChanges, pending_task_change_snapshot


@dataclass
class PlanningLifecycle:
    run_directory: Callable[[str], Path]
    save_state: Callable[[RunState], None]
    save_chat: Callable[[RunState], None]
    ai: PlanningAI
    messages: PlanningMessages
    profiles: PlanningProfiles
    files: PlanFiles
    source_indexes: Callable[[], PlanningSourceIndexes]
    content: Callable[[], PlanContentApplication]
    pending: Callable[[], PendingTaskChanges]
    conversation: Callable[[], ConversationPlanApplication]
    feature_application: Callable[[], FeaturePlanApplication]
    task_preparation: Callable[[], TaskExecutionPreparation]
    sdk: Callable[[], CodexSdkManager | None]

    def apply_plan(self, state: RunState, plan: Plan) -> RunState:
        self.content().apply(state, plan)
        self.profiles.pin_automatic(state)
        state.revise_plan()
        result_path = self.run_directory(state.id) / "plan.json"
        result_path.write_text(json.dumps(structured_plan_dict(plan), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        state.structured_plan_path = str(result_path)
        self.messages.append_assistant(state, planning_response_text(plan), counts_as_discussion=False)
        state.planning_applied_conversation_revision = state.planning_conversation_revision
        state.complete_step(RunStep.PLANNING)
        if plan.questions:
            state.transition(Stage.NEEDS_CLARIFICATION, f"planning requires {len(plan.questions)} clarification answers")
        elif plan.tech_stack_options:
            state.transition(Stage.NEEDS_CLARIFICATION, "planning requires a technology stack decision")
        else:
            state.transition(Stage.PLANNED, "tasks decomposed and agents selected")
        self.save_state(state)
        return state

    def apply_pending(
        self, state: RunState, *, apply_request: PlanningApplyRequest | None = None, prepared_plan: Plan | None = None,
        preparation_task_ids: set[str] | None = None,
    ) -> RunState:
        """Apply queued decisions while holding the run and Planning chat locks."""
        changes = self.pending()
        snapshot = pending_task_change_snapshot(state)
        apply_request = changes.begin(state, apply_request)
        try:
            prepared = changes.prepare(state, snapshot.tasks, apply_request=apply_request, prepared_plan=prepared_plan)
            plan, merged_plan = prepared.plan, prepared.merged_plan
            state.tasks = merged_plan.tasks
            prepared_task_ids = merged_plan.prepared_task_ids
            if state.stage == Stage.READY_TO_MERGE and any(task.status == TaskStatus.PENDING for task in state.tasks):
                state.transition(Stage.EXECUTING, "same-group tasks added for execution")
            elif state.stage == Stage.EXECUTING:
                advance_completed_tasks(state)
            elif state.stage == Stage.FAILED and any(task.status in {TaskStatus.PENDING, TaskStatus.FAILED} for task in state.tasks):
                # Keep the failure and its history, but resume through
                # the changed Tasks.
                state.failed_step = RunStep.AGENT_EXECUTION
            state.refresh_task_readiness()
            self.task_preparation().prepare(state, task_ids=prepared_task_ids if preparation_task_ids is None else
                                prepared_task_ids & preparation_task_ids, persist=False)
            self.files.write_result(
                state,
                Plan(
                    summary=state.summary,
                    server_work=state.server_work,
                    tasks=state.tasks,
                    source_paths=plan.source_paths,
                    instruction_paths=plan.instruction_paths,
                ),
            )
            return changes.complete(state, snapshot.tasks, apply_request)
        except (PlanningError, PipelineError, OSError) as exc:
            state.tasks = snapshot.tasks
            state.stage = snapshot.stage
            state.failed_step = snapshot.failed_step
            state.planning_follow_up_requests = snapshot.follow_up_requests
            changes.record_failure(state, apply_request, exc)
            raise

    def apply_conversation(
        self,
        state: RunState,
        *,
        event_message: str,
        apply_request: PlanningApplyRequest | None = None,
    ) -> RunState:
        original_drafts = {task.id: task_plan_draft(task) for task in state.tasks}
        if apply_request is not None:
            apply_request.status = PlanningApplyStatus.APPLYING
        state.begin_step(RunStep.PLANNING)
        state.add_event("planning", event_message)
        self.save_state(state)
        if apply_request is not None:
            self.save_chat(state)

        try:
            return self.conversation().apply(state, apply_request=apply_request, original_drafts=original_drafts)
        except (PlanningError, PipelineError, DocumentIndexError, OSError) as exc:
            if apply_request is not None:
                apply_request.status = PlanningApplyStatus.FAILED
                apply_request.completed_at = utc_now()
                apply_request.error_code = "planning_apply_failed"
                apply_request.error = str(exc)
            state.fail_step(RunStep.PLANNING, f"planning failed: {exc}")
            self.save_state(state)
            self.save_chat(state)
            raise

    def generate_features(self, state: RunState, *, suppress_errors: bool) -> RunState:
        baseline = feature_planning_baseline(state)
        spec = baseline.spec
        spec.feature_plan_attempts += 1
        spec.feature_plan_error = ""
        state.greenfield_phase = "feature_planning"
        state.begin_step(RunStep.PLANNING)
        state.add_event(
            "planning",
            f"feature Planning started from verified bootstrap {spec.verified_integration_head}",
        )
        self.save_state(state)
        if self.sdk() is not None:
            self.sdk().close_conversation(planning_conversation_id(state))
        state.planning_claude_session_id = ""
        context = feature_planning_context(baseline)
        try:
            plan = self.ai.build_plan(
                state,
                Path(state.spec_snapshot_path).read_text(encoding="utf-8"),
                clarification_context=context,
                source_index=self.source_indexes().snapshot(state),
            )
            self.feature_application().apply(state, plan, baseline)
            state.complete_step(RunStep.PLANNING)
            state.greenfield_phase = "feature_plan_ready"
            state.transition(Stage.PLANNED, "feature tasks generated from verified bootstrap baseline")
            state.add_event(
                "planning",
                f"feature plan revision {state.plan_revision} generated from decision revision {spec.decision_revision}",
            )
            self.save_state(state)
            self.save_chat(state)
            return state
        except Exception as exc:
            state.active_step = None
            state.stage = Stage.VERIFIED
            state.greenfield_phase = "feature_planning_ready"
            spec.feature_plan_error = str(exc)
            state.add_event("planning", f"feature Planning failed and can be retried: {exc}")
            self.messages.append_assistant(
                state,
                f"기본 구조 검증은 완료됐지만 기능 계획 생성에 실패했습니다. 다시 시도할 수 있습니다.\n\n{exc}",
                counts_as_discussion=False,
            )
            self.save_state(state)
            self.save_chat(state)
            if suppress_errors:
                return state
            if isinstance(exc, (PipelineError, PlanningError)):
                raise
            raise PipelineError(f"기능 계획 생성에 실패했습니다: {exc}") from exc
