"""TaskWorkflows with explicit feature and persistence dependencies."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, ContextManager, Iterator
from ..code_style import render_code_style_snapshot, render_task_code_style_evidence
from ..codex_sdk import CodexSdkExecutionProfile, CodexSdkProgress
from ..config import (
    AgentConfig,
    DEFAULT_TASK_VERIFY_COMMAND_TIMEOUT_SECONDS,
    DEFAULT_TASK_VERIFY_TOTAL_TIMEOUT_SECONDS,
    ExecutionConfig,
    RoutingConfig,
)
from ..errors import PipelineError
from ..execution import (
    ExecutionControlService,
    ReviewProtocolError,
    ReviewRequest,
    TASK_WORKTREE_CONTRACT,
    TaskActionRunner,
    TaskActivityRecorder,
    TaskAttemptRunner,
    TaskCancellation,
    TaskRecoveryRunner,
    TaskRetryGuidance,
    TaskReviewCycles,
    TaskScopeInspector,
    TaskVerificationFailure,
    TaskVerificationService,
    TaskWorkspacePreparation,
    collect_interrupted_tasks,
    committed_result_files,
    mark_task_interrupted,
    parse_review,
    ready_tasks,
    record_task_result,
    recovery_timeout_limits,
    refresh_task_code_style_evidence,
    render_review_prompt,
    render_revision_prompt,
    scope_contract_digest,
    task_scope_review,
    validate_reasoning_effort,
    verification_failure_fingerprint,
    with_effort_mode_guidance,
    with_project_dotnet_guidance,
    with_task_execution_efficiency_guidance,
    with_task_worktree_contract,
)
from ..execution.lifecycle import StoredStopSignal, raise_if_stopped
from ..execution.manual_tasks import ManualTaskCompletion, ManualWorkspaceInspector
from ..execution.policy_lifecycle import ExecutionPolicyLifecycle
from ..execution.preparation import advance_completed_tasks
from ..execution.profile_workflows import ExecutionProfiles
from ..execution.provider_commands import agent_command, command_with_model, command_with_reasoning_effort
from ..execution.provider_runtime import ProviderRuntime
from ..execution.stop_ports import StopSignalFactory
from ..execution.task_invocation import TaskInvocation
from ..execution.verification_commands import VerificationCommands
from ..git import GitError, GitWorkspace, LOCAL_GIT_TIMEOUT_SECONDS
from ..integration import uses_shared_workspace
from ..integration.workspace_access import WorkspaceAccess
from ..models import EffortMode, ResultFileChange, ReviewStatus, RunState, RunStep, Stage, TaskAction, TaskStatus, WorkTask
from ..persistence.execution_records import TaskWorkflowsRecords
from ..persistence.run_lookup import find_task
from ..task_scope_review import SCOPE_REVIEW_GUIDANCE, TaskScopeReview


TASK_AUTOMATIC_RECOVERY_LIMIT = 3


@dataclass
class TaskWorkflows:
    records: TaskWorkflowsRecords
    control: ExecutionControlService
    state_lock: ContextManager[object]
    stop_signal: StopSignalFactory
    execution_settings: Callable[[], ExecutionConfig]
    read_git: Callable[[], GitWorkspace]
    workspace: WorkspaceAccess
    read_agents: Callable[[], dict[str, AgentConfig]]
    routing_settings: Callable[[], RoutingConfig]
    verification_commands: VerificationCommands
    read_dotnet_executable: Callable[[], str]
    profiles: ExecutionProfiles
    retry_guidance: TaskRetryGuidance
    provider: ProviderRuntime[StoredStopSignal]
    policy: ExecutionPolicyLifecycle

    def activity(self) -> TaskActivityRecorder:
        return TaskActivityRecorder(
            state_lock=self.state_lock,
            save_state=self.records.save,
            set_active=self.control.set_active_task,
            clear_active=self.control.clear_active_task,
            stop_signal=self.stop_signal,
            record_checkpoint=self.control.record_checkpoint,
        )


    def extend_task_timeout_for_recovery(self, state: RunState) -> None:
        command_timeout, total_timeout = recovery_timeout_limits(
            (state.task_verify_command_timeout_seconds, state.task_verify_total_timeout_seconds),
            (self.execution_settings().task_verify_command_timeout_seconds, self.execution_settings().task_verify_total_timeout_seconds),
            (DEFAULT_TASK_VERIFY_COMMAND_TIMEOUT_SECONDS, DEFAULT_TASK_VERIFY_TOTAL_TIMEOUT_SECONDS),
        )
        if (state.task_verify_command_timeout_seconds, state.task_verify_total_timeout_seconds) == (command_timeout, total_timeout):
            return
        state.task_verify_command_timeout_seconds = command_timeout
        state.task_verify_total_timeout_seconds = total_timeout
        state.add_event("verification", f"명시적 시간 초과 복구: Task 검증 한도 변경 · 명령 {command_timeout}초 · 전체 {total_timeout}초")


    def merge_task_dependencies(self, state: RunState, task: WorkTask) -> None:
        TaskWorkspacePreparation(self.read_git(), uses_shared_workspace, find_task).merge_dependencies(state, task)


    def record_task_start_commit(self, task: WorkTask) -> None:
        TaskWorkspacePreparation(self.read_git(), uses_shared_workspace, find_task).record_start_commit(task)


    def clean_manual_workspace(self, state: RunState, task: WorkTask) -> tuple[Path, str]:
        return ManualWorkspaceInspector(
            git=self.read_git(), workspace_ready=self.workspace.ensure_execution_workspace_ready,
            uses_shared=uses_shared_workspace, shared_boundary=self.workspace.shared_workspace_boundary,
            worktree_root=self.workspace.run_worktree_root, is_clean=self.workspace.worktree_is_clean,
        ).inspect(
            state,
            task,
        )


    @staticmethod
    def require_manual_task_version(state: RunState, task: WorkTask, expected_commit: str, expected_revision: int) -> None:
        if state.plan_revision != expected_revision or not expected_commit or task.started_commit != expected_commit:
            raise PipelineError("작업 계획 또는 검증 기준 커밋이 바뀌었습니다. 최신 작업을 다시 확인해 주세요.")


    def require_waiting_manual_workspace(self, state: RunState, task: WorkTask) -> None:
        if (state.stage != Stage.EXECUTING or task.status != TaskStatus.WAITING or state.active_step
                or any(item.active_action or item.status in {TaskStatus.RUNNING, TaskStatus.REVIEWING, TaskStatus.REVISING}
                       for item in state.tasks)):
            raise PipelineError("수동 대기 중인 작업의 최신 상태를 확인해 주세요.")
        if uses_shared_workspace(state) and any(item.id != task.id and item.status == TaskStatus.WAITING for item in state.tasks):
            raise PipelineError("공유 작업공간의 수동 작업이 둘 이상입니다. 최신 작업 상태를 확인해 주세요.")
        execution = self.records.load_execution_control(state.id)
        if execution and execution.phase in {"running", "stopping", "confirmation_required"}:
            raise PipelineError("현재 실행의 종료를 확인한 뒤 수동 작업을 진행해 주세요.")
        state.refresh_task_readiness()
        if task.blocked_by:
            raise PipelineError("선행 작업을 완료한 뒤 수동 작업을 진행해 주세요.")
        _, head = self.clean_manual_workspace(state, task)
        if head != task.started_commit:
            raise PipelineError("작업공간 커밋이 검증 기준과 다릅니다. 현재 상태와 검증 대상을 다시 확인해 주세요.")


    def check_manual_review(self, task: WorkTask, head: str, *, manual_verification: bool = False) -> None:
        if not task.reviewer_agent_id:
            return
        if task.reviewer_agent_id not in self.read_agents():
            raise PipelineError("계획에 지정된 리뷰 AI를 확인할 수 없습니다. 실행 설정을 다시 확인해 주세요.")
        if manual_verification and task.review_status == ReviewStatus.APPROVED:
            # The verification retry runs a new review with the current task criteria.
            return
        if task.last_review_commit and head == task.last_review_commit:
            raise PipelineError(f"task {task.id} has no new commit since the last review")
        if task.review_cycles >= self.routing_settings().max_review_cycles:
            raise PipelineError(f"task {task.id} reached the review cycle limit")


    def complete_task(self, state: RunState, task: WorkTask, *, manual_verification_note: str = "") -> RunState:
        worktree = Path(task.worktree)
        if task.reviewer_agent_id:
            head = self.read_git().head(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            task.status = TaskStatus.REVIEWING
            task.review_status = ReviewStatus.RUNNING
            cycle = task.review_cycles + 1
            try:
                options = {"manual_verification": True} if manual_verification_note else {}
                review = self.run_review(state, task, cycle, **options)
            except (GitError, PipelineError) as exc:
                task.status = TaskStatus.FAILED
                task.review_status = ReviewStatus.FAILED
                task.error = str(exc)
                state.fail_step(RunStep.MANUAL_COMPLETION, f"{task.id} manual review failed: {exc}")
                self.records.save(state)
                raise
            self.record_review(task, review, cycle, head)
            if review["verdict"] == "changes_requested":
                task.status = TaskStatus.WAITING
                if cycle >= self.routing_settings().max_review_cycles:
                    task.status = TaskStatus.FAILED
                    task.review_status = ReviewStatus.FAILED
                    state.fail_step(RunStep.MANUAL_COMPLETION, f"{task.id} review limit reached")
                else:
                    state.add_event("review", f"{task.id} changes requested")
                state.refresh_task_readiness()
                self.records.save(state)
                return state

        ManualTaskCompletion(
            git=self.read_git(), save_state=self.records.save, verify_task=self.run_task_verification,
            ensure_clean=self.workspace.ensure_worktree_clean, ensure_head=self.verification_commands.ensure_verification_head,
            record_result=self.record_task_result,
        ).complete(
            state,
            task,
            worktree,
            manual_verification_note=manual_verification_note,
        )
        try:
            self.activate_manual_tasks(state)
        except (GitError, PipelineError, OSError) as exc:
            if not manual_verification_note:
                raise
            state.fail_step(RunStep.AGENT_EXECUTION, f"수동 검증을 기록했습니다. 다음 작업 준비에 실패했습니다. {exc}")
            self.records.save(state)
            return state
        advance_completed_tasks(state)
        self.records.save(state)
        return state


    def activate_manual_tasks(self, state: RunState) -> None:
        pending = [task for task in state.tasks if task.status == TaskStatus.PENDING]
        ready = ready_tasks(state, pending)
        if uses_shared_workspace(state):
            ready = ready[:1]
        for task in ready:
            self.merge_task_dependencies(state, task)
            self.record_task_start_commit(task)
            task.status = TaskStatus.WAITING
            state.add_event("execution", f"{task.id} is ready for manual handoff")


    @contextmanager
    def task_action(self, state: RunState, task: WorkTask, action: TaskAction, *, count_attempt: bool = True) -> Iterator[None]:
        with self.activity().action(state, task, action, count_attempt=count_attempt):
            yield


    def save_task_progress(self, state: RunState) -> None:
        self.activity().save_progress(state)


    def record_task_progress(self, state: RunState, task: WorkTask, progress: CodexSdkProgress) -> None:
        self.activity().record_progress(state, task, progress)


    def record_task_execution_profile(self, state: RunState, task: WorkTask, profile: CodexSdkExecutionProfile) -> None:
        self.activity().record_execution_profile(state, task, profile)


    def collect_interrupted_tasks(self, state: RunState) -> list[WorkTask]:
        return collect_interrupted_tasks(state)


    def restore_legacy_no_commit_retry_action(self, state: RunState, task: WorkTask) -> None:
        if review := self.task_scope_review(task):
            raise PipelineError(review.error(scope_contract_digest(task)))
        if (
            task.failed_action != TaskAction.EXECUTE
            or not task.error.endswith(f"produced no commit for {task.id}")
            or not state.base_commit
            or not task.worktree
        ):
            return
        subjects = self.read_git().commit_subjects_since(
            Path(task.worktree), state.base_commit, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
        )
        task_prefixes = (f"feat({task.id}):", f"fix({task.id}):")
        if not any(subject.startswith(task_prefixes) for subject in subjects):
            return
        if task.reviewer_agent_id and task.review_status != ReviewStatus.APPROVED:
            task.failed_action = TaskAction.REVIEW
        else:
            task.failed_action = TaskAction.VERIFY
        state.add_event("task", f"{task.id} existing implementation commit restored at {task.failed_action.value}")


    def mark_task_interrupted(self, task: WorkTask) -> None:
        return mark_task_interrupted(task)


    def with_project_dotnet_guidance(self, prompt: str, task: WorkTask) -> str:
        return with_project_dotnet_guidance(prompt, task.verify_commands, self.read_dotnet_executable())


    def committed_result_files(self, baseline: str, result: str) -> tuple[str, list[ResultFileChange], str]:
        return committed_result_files(self.read_git(), baseline, result)


    def record_task_result(self, task: WorkTask, *, manual_verification_note: str = "") -> None:
        record_task_result(task, read_commit_files=self.committed_result_files, manual_verification_note=manual_verification_note)


    @staticmethod
    def task_verification_failure_fingerprint(error: TaskVerificationFailure) -> str:
        return verification_failure_fingerprint(error.command, error.output)


    def task_stop_check(self, state: RunState, task: WorkTask) -> Callable[[], None]:
        signal = self.stop_signal(state, task)
        return lambda: raise_if_stopped(signal)


    def recovery(self) -> TaskRecoveryRunner:
        return TaskRecoveryRunner(
            TASK_AUTOMATIC_RECOVERY_LIMIT,
            self.run_task_attempt,
            self.task_verification_failure_fingerprint,
            self.task_stop_check,
            self.verification_commands.ensure_verification_head,
            self.validate_task_change_scope,
            self.workspace.ensure_worktree_clean,
            self.profiles.promote_automatic_model,
            self.state_lock,
            self.records.save,
        )


    def run_task(self, state: RunState, task: WorkTask, resume_action: TaskAction = TaskAction.EXECUTE) -> None:
        if review := self.task_scope_review(task):
            raise PipelineError(review.error(scope_contract_digest(task)))
        self.recovery().run(state, task, resume_action)


    def run_task_attempt(
        self, state: RunState, task: WorkTask, resume_action: TaskAction, *, prompt: str | None = None, repair_index: int = 0,
        verification_environment: dict[str, str] | None = None, implementation_action_start: int | None = None,
    ) -> None:
        TaskAttemptRunner(
            self.read_git(), self.records.run_dir, self.run_executor, self.run_task_verification,
            self.run_review_cycles, self.revision_prompt, self.result_revision_retry_instruction, self.record_task_result,
        ).run(
            state, task, resume_action, prompt=prompt, repair_index=repair_index,
            verification_environment=verification_environment, implementation_action_start=implementation_action_start,
        )


    def retry(self) -> TaskRetryGuidance:
        return self.retry_guidance


    def result_revision_retry_instruction(self, run_id: str, task_id: str) -> str:
        return self.retry().instruction(run_id, task_id)


    def scope_inspector(self) -> TaskScopeInspector:
        return TaskScopeInspector(self.read_git(), self.records.run_dir, uses_shared_workspace)


    def task_cancellation(self, state: RunState, task: WorkTask) -> TaskCancellation:
        signal = self.stop_signal(state, task)
        return TaskCancellation(signal, lambda: raise_if_stopped(signal))


    def task_execution_prompt(self, prompt: str, task: WorkTask) -> str:
        execution_prompt = self.with_project_dotnet_guidance(prompt, task)
        execution_prompt = with_task_execution_efficiency_guidance(execution_prompt)
        execution_prompt += "\n\n## Scope review reporting\n\n" + SCOPE_REVIEW_GUIDANCE + "\n"
        execution_prompt = with_task_worktree_contract(execution_prompt)
        return execution_prompt


    def actions(self) -> TaskActionRunner:
        return TaskActionRunner(
            self.read_git(), self.read_agents(), self.execution_settings().auto_commit, self.records.run_dir,
            self.task_action, self.task_stop_check, self.task_execution_prompt, self.validate_task_change_scope,
            self.workspace.ensure_worktree_clean, self.save_task_progress, refresh_task_code_style_evidence,
            self.invoke_agent, scope_contract_digest, self.task_has_recorded_implementation,
            self.state_lock, self.records.save, self.review_prompt, self.parse_review, self.perform_task_verification,
        )


    def verification(self) -> TaskVerificationService:
        return TaskVerificationService(
            lambda: self.execution_settings().task_verify_total_timeout_seconds,
            lambda: self.execution_settings().task_verify_command_timeout_seconds,
            lambda: self.read_dotnet_executable(),
            self.state_lock, self.records.save, self.save_task_progress, self.records.run_dir,
            self.task_cancellation, self.workspace.ensure_worktree_clean, self.verification_commands.ensure_verification_head,
            self.validate_task_change_scope, self.record_task_progress, refresh_task_code_style_evidence,
            self.verification_commands.prepare_verification_command, self.verification_commands.execute_verification_command,
        )


    def run_task_verification(self, state: RunState, task: WorkTask, *, environment_overrides: dict[str, str] | None = None) -> None:
        self.actions().verify(state, task, environment_overrides=environment_overrides)


    def validate_task_change_scope(self, task: WorkTask, state: RunState | None = None) -> list[str] | None:
        return self.scope_inspector().validate(task, state)


    def perform_task_verification(self, state: RunState, task: WorkTask, *, environment_overrides: dict[str, str] | None = None) -> None:
        self.verification().run(state, task, environment_overrides=environment_overrides)


    def run_review_cycles(self, state: RunState, task: WorkTask, original_prompt: str, start_cycle: int) -> None:
        TaskReviewCycles(
            self.routing_settings().max_review_cycles, self.read_git(), self.run_review, self.record_review,
            self.save_task_progress, self.revision_prompt, self.records.run_dir, self.run_executor,
        ).run(state, task, original_prompt, start_cycle)


    def run_executor(
        self, state: RunState, task: WorkTask, prompt: str, log_path: Path, commit_message: str, action: TaskAction,
        *, implementation_action_start: int | None = None,
    ) -> None:
        self.actions().execute(
            state, task, prompt, log_path, commit_message, action, implementation_action_start=implementation_action_start,
        )


    def task_scope_review(self, task: WorkTask) -> TaskScopeReview | None:
        return task_scope_review(task)


    def task_has_recorded_implementation(self, task: WorkTask, head: str, *, action_start: int = 0) -> bool:
        return self.scope_inspector().has_recorded_implementation(task, head, action_start=action_start)


    def run_review(self, state: RunState, task: WorkTask, cycle: int, *, manual_verification: bool = False) -> dict[str, object]:
        return self.actions().review(state, task, cycle, manual_verification=manual_verification)


    @staticmethod
    def with_effort_mode_guidance(prompt: str, mode: EffortMode) -> str:
        return with_effort_mode_guidance(prompt, mode.value)


    def invoke_agent(self, state: RunState, task: WorkTask, agent: AgentConfig, prompt: str, log_path: Path, action: TaskAction) -> str:
        return TaskInvocation(
            read_agents=lambda: self.read_agents(), load_policy=self.records.load_effort_policy,
            validate_snapshot=self.policy.validate_effort_execution_snapshot, guidance=self.with_effort_mode_guidance,
            agent_command=agent_command, with_model=command_with_model, with_reasoning=self.command_with_reasoning_effort,
            stop_signal=self.stop_signal, record_progress=self.record_task_progress,
            record_profile=self.record_task_execution_profile, invoke=self.provider.invoke,
        ).run(state, task, agent, prompt, log_path, action)


    @staticmethod
    def command_with_reasoning_effort(agent: AgentConfig, command_template: tuple[str, ...], effort: str, model: str = "") -> tuple[str, ...]:
        return command_with_reasoning_effort(
            agent, command_template, effort, model, validate_effort=validate_reasoning_effort,
        )


    def review_prompt(self, state: RunState, task: WorkTask, cycle: int, *, manual_verification: bool = False) -> str:
        changed_path_evidence = next(
            (result.code_style_evidence for result in reversed(task.action_results) if result.code_style_evidence is not None),
            None,
        )
        return render_review_prompt(ReviewRequest(
            run_id=state.id, task_id=task.id, cycle=cycle, title=task.title, capabilities=tuple(task.capabilities),
            risk_level=task.risk_level.value, expected_paths=tuple(task.expected_paths), forbidden_paths=tuple(task.forbidden_paths),
            verify_commands=tuple(tuple(command) for command in task.verify_commands), acceptance_criteria=tuple(task.acceptance_criteria),
            main_branch=state.main_branch, code_style_snapshot=render_code_style_snapshot(state.code_style_snapshot),
            changed_path_evidence=render_task_code_style_evidence(changed_path_evidence), worktree_contract=TASK_WORKTREE_CONTRACT,
            manual_verification=manual_verification,
        ))


    @staticmethod
    def revision_prompt(task: WorkTask, original_prompt: str, review: dict[str, object], cycle: int) -> str:
        return render_revision_prompt(original_prompt, review, cycle, worktree_contract=TASK_WORKTREE_CONTRACT)


    @staticmethod
    def parse_review(output: str) -> dict[str, object]:
        try:
            return parse_review(output)
        except ReviewProtocolError as exc:
            raise PipelineError(str(exc)) from exc.__cause__


    @staticmethod
    def record_review(task: WorkTask, review: dict[str, object], cycle: int, commit: str) -> None:
        task.review_cycles = cycle
        task.review_summary = str(review["summary"])
        task.review_findings = list(review["findings"])
        task.last_review_commit = commit
        task.review_status = ReviewStatus.APPROVED if review["verdict"] == "approved" else ReviewStatus.CHANGES_REQUESTED
