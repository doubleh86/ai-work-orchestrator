"""ExecutionFlow with explicit feature and persistence dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, ContextManager
from ..config import AgentConfig, ExecutionConfig
from ..errors import PipelineError, ProviderRequestLimitError
from ..execution import (
    DispatchRecords,
    ExecutionControlService,
    TaskBatchExecutor,
    TaskDispatcher,
    TaskExecutionPreparation,
    deferred_execution_task_ids,
    infer_task_action,
    ready_tasks,
    scope_contract_digest,
    validate_task_profile_override_targets,
    waiting_for_user_checks,
)
from ..execution.operation_lifecycle import RunStepLifecycle
from ..execution.policy_lifecycle import ExecutionPolicyLifecycle
from ..execution.preparation import advance_completed_tasks
from ..execution.profile_workflows import ExecutionProfiles
from ..execution.provider_choices import ProviderAvailability
from ..execution.startup import ExecutionStartup
from ..execution.task_workflows import TaskWorkflows
from ..execution.verification_commands import VerificationCommands
from ..integration import uses_shared_workspace
from ..integration.workspace_access import WorkspaceAccess
from ..models import DirectionChangeStatus, PlanningApplyStatus, RunState, RunStep, Stage, TaskAction, TaskReadiness, TaskStatus, WorkTask, utc_now
from ..persistence.errors import RunLockedError
from ..persistence.execution_records import ExecutionFlowRecords
from ..persistence.run_lookup import RunLookup, find_task
from ..planning.bootstrap import BootstrapPlanner


@dataclass
class ExecutionFlow:
    records: ExecutionFlowRecords
    tasks: TaskWorkflows
    workspace: WorkspaceAccess
    verification_commands: VerificationCommands
    lookup: RunLookup
    profiles: ExecutionProfiles
    policy: ExecutionPolicyLifecycle
    availability: ProviderAvailability
    read_agents: Callable[[], dict[str, AgentConfig]]
    ensure_verification: Callable[[RunState], None]
    preparation: Callable[[], TaskExecutionPreparation]
    steps: RunStepLifecycle
    bootstrap: Callable[[], BootstrapPlanner]
    control: ExecutionControlService
    state_lock: ContextManager[object]
    execution_settings: Callable[[], ExecutionConfig]

    def apply_queued_changes_after_batch(self, state: RunState) -> RunState | None:
        latest = self.records.load(state.id)
        if not latest.planning_follow_up_requests and not latest.direction_change_requests:
            return None
        with self.records.planning_chat_lock(state.id):
            current = self.records.load(state.id)
            paused = self.pause_for_direction_change(current)
            if paused is not None:
                return paused
            if not current.planning_follow_up_requests:
                return None
            for request in current.planning_apply_requests:
                if request.status == PlanningApplyStatus.QUEUED:
                    request.status = PlanningApplyStatus.FAILED
                    request.completed_at = utc_now()
                    request.error_code = "preview_required"
                    request.error = "실행이 끝났습니다. Task 변경 미리보기를 확인한 뒤 반영해 주세요."
            current.add_event("planning", "Planning 변경은 실행 후 미리보기 확인 대기")
            self.records.save_planning_chat(current)
            return None


    def pause_for_direction_change(self, state: RunState) -> RunState | None:
        """Pause at a dispatch boundary while the caller holds the Planning chat lock."""
        pending = [item for item in state.direction_change_requests if item.status != DirectionChangeStatus.APPLIED]
        if not pending:
            return None
        for item in pending:
            item.status = DirectionChangeStatus.QUEUED
            item.preview_id = ""
            item.next_step = "다음 Task 시작 전 변경 미리보기 확인"
            item.updated_at = utc_now()
        failures = [task for task in state.tasks if task.status == TaskStatus.FAILED]
        if failures:
            state.fail_step(RunStep.AGENT_EXECUTION, "; ".join(f"{task.id}: {task.error}" for task in failures))
        else:
            state.complete_step(RunStep.AGENT_EXECUTION)
        state.add_event("planning", "direction change awaits preview before next Task")
        self.records.save(state)
        self.records.save_planning_chat(state)
        return state


    def resume(self, run_id: str, *, manual: bool) -> RunState:
        state = self.records.load(run_id)
        if state.stage == Stage.PLANNED:
            return self.execute(state, manual=manual)
        if state.stage == Stage.EXECUTING:
            interrupted = self.tasks.collect_interrupted_tasks(state)
            if interrupted:
                state.fail_step(RunStep.AGENT_EXECUTION, "interrupted agent tasks collected: " + ", ".join(task.id for task in interrupted))
                self.records.save(state)
            stopped = [task for task in state.tasks if task.status == TaskStatus.STOPPED]
            if stopped:
                for task in stopped:
                    task.status = TaskStatus.PENDING
                    task.error = ""
                state.refresh_task_readiness()
                state.add_event("execution", "stopped tasks queued from preserved work: " + ", ".join(task.id for task in stopped))
                self.records.save(state)
            return self.execute(state, manual=manual, recover_saved_profiles=True)
        if state.stage != Stage.FAILED or state.failed_step is None:
            raise PipelineError(f"run {run_id} at '{state.stage.value}' has no resumable failure")
        if self.workspace.shared_main_push_recovery_source(state) is not None:
            raise PipelineError("로컬 Main이 이미 반영됐습니다. 일반 재개 대신 별도 승인된 Main Push 재시도를 사용하세요.")
        if state.failed_step == RunStep.AGENT_EXECUTION:
            return self.execute(state, manual=manual, recover_saved_profiles=True)
        if state.failed_step == RunStep.MANUAL_COMPLETION:
            failed = [task for task in state.tasks if task.status == TaskStatus.FAILED]
            if not failed:
                raise PipelineError("manual completion failure has no failed task")
            for task in failed:
                task.status = TaskStatus.WAITING
                task.active_action = None
            state.refresh_task_readiness()
            state.resume_to(Stage.EXECUTING, "manual completion failure restored to waiting tasks")
            self.records.save(state)
            return state
        resumable_stages = {
            RunStep.VERIFY: self.verification_commands.verification_resume_stage(state),
            RunStep.PUSH: (Stage.VERIFIED if uses_shared_workspace(state) else Stage.MERGED),
            RunStep.MERGE: (Stage.WORK_BRANCH_PUSHED if uses_shared_workspace(state) else None),
            RunStep.DEPLOY: Stage.PUSHED,
        }
        target = resumable_stages.get(state.failed_step)
        if target is not None:
            failed_step = state.failed_step.value
            state.resume_to(target, f"{failed_step} failure restored to {target.value}")
            self.records.save(state)
            return state
        raise PipelineError(f"cannot safely resume failure at {state.failed_step.value}")


    def execute_task_locked(
        self,
        run_id: str,
        task_id: str,
        *,
        manual: bool,
        agent_overrides: dict[str, str] | None,
        model_overrides: dict[str, str] | None,
        reasoning_effort_overrides: dict[str, str] | None,
    ) -> RunState:
        state = self.lookup.at(run_id, {Stage.PLANNED, Stage.EXECUTING})
        task = find_task(state, task_id)
        state.refresh_task_readiness()
        if task.status != TaskStatus.PENDING:
            raise PipelineError(f"task {task_id} is not pending")
        if task.readiness != TaskReadiness.READY:
            blocked = ", ".join(task.blocked_by) or "unknown dependencies"
            raise PipelineError(f"task {task_id} is blocked by incomplete dependencies: {blocked}")
        if uses_shared_workspace(state):
            active = next(
                (
                    item
                    for item in state.tasks
                    if item.id != task.id and item.status in {TaskStatus.RUNNING, TaskStatus.REVIEWING, TaskStatus.REVISING, TaskStatus.WAITING}
                ),
                None,
            )
            if active is not None:
                raise PipelineError(f"shared run workspace is already assigned to task {active.id}")
            first_ready = next(iter(ready_tasks(state, [item for item in state.tasks if item.status == TaskStatus.PENDING])), None)
            if first_ready is not None and first_ready.id != task.id:
                raise PipelineError(f"shared run workspace executes ready tasks in plan order; next task is {first_ready.id}")
        return self.execute(
            state,
            manual=manual,
            selected_task_ids={task_id},
            agent_overrides=agent_overrides,
            model_overrides=model_overrides,
            reasoning_effort_overrides=reasoning_effort_overrides,
        )


    def execute(
        self,
        state: RunState,
        *,
        manual: bool,
        selected_task_ids: set[str] | None = None,
        retry_selected: bool = False,
        agent_overrides: dict[str, str] | None = None,
        model_overrides: dict[str, str] | None = None,
        reasoning_effort_overrides: dict[str, str] | None = None,
        recover_saved_profiles: bool = False,
    ) -> RunState:
        check_blocked = state.user_check_blocked_task_ids()
        excluded_task_ids = deferred_execution_task_ids(state) | check_blocked
        recovering_check_run = bool(state.user_check_plan and state.active_execution_request_id)
        if state.user_check_plan and state.stage == Stage.PLANNED:
            self.policy.require_confirmed_plan(state)
        if selected_task_ids and selected_task_ids.intersection(check_blocked):
            raise PipelineError("선택한 작업에 필요한 사용자 확인을 먼저 통과로 기록해 주세요.")
        if not recovering_check_run and state.stage in {Stage.PLANNED, Stage.EXECUTING} and self.waiting_for_user_checks(state):
            return state
        if (
            excluded_task_ids and not recovering_check_run
            and not any(
                task.id not in excluded_task_ids and task.status not in {TaskStatus.COMPLETED, TaskStatus.MERGED}
                for task in state.tasks
            )
        ):
            return state
        for task in state.tasks:
            if task.id not in excluded_task_ids and (selected_task_ids is None or task.id in selected_task_ids):
                if review := self.tasks.task_scope_review(task):
                    raise PipelineError(review.error(scope_contract_digest(task)))
        self.policy.begin_effort_execution(
            state, agent_overrides=agent_overrides, model_overrides=model_overrides,
            reasoning_effort_overrides=reasoning_effort_overrides,
            recover_saved_profiles=recover_saved_profiles,
            check_blocked_task_ids=frozenset(check_blocked),
        )
        try:
            result = self.execute_with_bound_policy(
                state,
                manual=manual,
                excluded_task_ids=excluded_task_ids,
                selected_task_ids=selected_task_ids,
                retry_selected=retry_selected,
                agent_overrides=agent_overrides,
                model_overrides=model_overrides,
                reasoning_effort_overrides=reasoning_effort_overrides,
            )
        except ProviderRequestLimitError:
            # No new task is dispatched when quota preflight blocks. Release the
            # binding so the user can choose another AI before resuming.
            self.policy.finish_effort_execution_binding(self.records.load(state.id))
            raise
        pending_profiles = self.records.load_task_execution_profiles(result.id)
        if any("applied_policy_id" not in request for request in pending_profiles.values()):
            try:
                with self.records.planning_chat_lock(result.id):
                    self.profiles.apply_queued_execution_profiles(result)
            except RunLockedError:
                result.add_event("routing", "대기 모델 선택을 보존했습니다. Planning 대화가 끝난 뒤 다음 Task 시작 시 적용합니다.")
                self.records.save(result)
        return self.policy.finish_effort_execution_binding(result)


    def prepare_task_for_dispatch(self, state: RunState, task: WorkTask) -> None:
        self.tasks.merge_task_dependencies(state, task)
        self.tasks.record_task_start_commit(task)
        self.verification_commands.preflight_task_environment(state, task)


    def task_dispatcher(self) -> TaskDispatcher:
        return TaskDispatcher(
            DispatchRecords(self.records.load, self.records.save, self.records.planning_chat_lock),
            self.read_agents(), ready_tasks, uses_shared_workspace, self.availability.is_available,
            self.profiles.apply_queued_execution_profiles, self.pause_for_direction_change, self.profiles.apply_quota_fallbacks,
            self.prepare_task_for_dispatch, self.run_task_batch, self.apply_queued_changes_after_batch,
            advance_completed_tasks,
        )


    def execute_with_bound_policy(
        self,
        state: RunState,
        *,
        manual: bool,
        excluded_task_ids: set[str],
        selected_task_ids: set[str] | None = None,
        retry_selected: bool = False,
        agent_overrides: dict[str, str] | None = None,
        model_overrides: dict[str, str] | None = None,
        reasoning_effort_overrides: dict[str, str] | None = None,
    ) -> RunState:
        self.ensure_verification(state)
        if state.stage == Stage.PLANNED:
            self.policy.require_confirmed_plan(state)
            self.bootstrap().verify_current(state)
        self.policy.require_confirmed_profiles(state, agent_overrides or {}, model_overrides or {}, reasoning_effort_overrides or {})
        self.workspace.ensure_execution_workspace_ready()
        startup = ExecutionStartup(
            save_state=self.records.save, prepare_tasks=self.preparation().prepare, validate_targets=validate_task_profile_override_targets,
            validate_models=self.profiles.validate_task_model_overrides, validate_effort=self.profiles.validate_task_reasoning_overrides,
            apply_agents=self.profiles.apply_task_agent_overrides, apply_models=self.profiles.apply_task_model_overrides,
            apply_effort=self.profiles.apply_task_reasoning_overrides, restore_legacy=self.tasks.restore_legacy_no_commit_retry_action,
        )
        startup.prepare_inputs(
            state, agent_overrides=agent_overrides, model_overrides=model_overrides, reasoning_effort_overrides=reasoning_effort_overrides,
        )
        queued = startup.queue_retry(state, selected_task_ids=selected_task_ids, retry_selected=retry_selected)
        if queued is not None:
            if queued.resume_run:
                state.resume_to(Stage.EXECUTING, queued.message)
            else:
                state.add_event("task", queued.message)
            self.records.save(state)
        if state.stage == Stage.PLANNED:
            with self.steps.step(state, RunStep.TASK_PREPARATION):
                self.preparation().prepare(state)
            if state.greenfield_phase == "bootstrap_ready":
                state.greenfield_phase = "bootstrap_running"
            state.transition(Stage.EXECUTING, "agent work started")
            self.records.save(state)

        return self.task_dispatcher().run(
            state, manual=manual, excluded_task_ids=excluded_task_ids, selected_task_ids=selected_task_ids,
        )


    def run_task_batch(self, state: RunState, tasks: list[WorkTask], resume_actions: dict[str, TaskAction]) -> None:
        TaskBatchExecutor(
            self.execution_settings().max_parallel, uses_shared_workspace, self.tasks.run_task, self.state_lock,
            self.control.confirm_stopped, infer_task_action, self.records.save,
        ).run(state, tasks, resume_actions)


    def waiting_for_user_checks(self, state: RunState) -> bool:
        return waiting_for_user_checks(state)
