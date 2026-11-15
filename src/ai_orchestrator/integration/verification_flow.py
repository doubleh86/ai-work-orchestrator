"""VerificationFlow with explicit feature and persistence dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, ContextManager
from ..config import AgentConfig, ExecutionConfig
from ..errors import PipelineError
from ..execution import ExecutionControlService, VerificationRepairRunner, commit_queue_tasks, verification_failure_is_repairable
from ..execution.lifecycle import StoredStopSignal, raise_if_stopped
from ..execution.operation_lifecycle import RunStepLifecycle
from ..execution.provider_choices import ProviderAvailability
from ..execution.provider_commands import agent_command, command_with_model
from ..execution.provider_runtime import ProviderRuntime
from ..execution.run_verification import (
    RunVerificationCommands,
    RunVerificationRecords,
    VerificationFailureEvidence,
    integration_verification_command_selection,
    is_orchestrator_managed_verification_command,
)
from ..execution.stop_ports import StopSignalFactory
from ..execution.task_workflows import TaskWorkflows
from ..execution.verification_commands import VerificationCommands
from ..execution_control import ExecutionStopped
from ..git import GitWorkspace, LOCAL_GIT_TIMEOUT_SECONDS
from ..integration import CandidateVerification, integration_branch_name, integration_conflict_fingerprint, uses_shared_workspace
from ..integration.verification_repair import VerificationRepairWorkspace
from ..integration.workspace_access import WorkspaceAccess
from ..models import RunState, RunStep, Stage, utc_now
from ..persistence.execution_records import VerificationFlowRecords
from ..persistence.run_lookup import RunLookup
from ..planning.lifecycle import PlanningLifecycle


@dataclass
class VerificationFlow:
    records: VerificationFlowRecords
    planning_lifecycle: PlanningLifecycle
    control: ExecutionControlService
    verification_commands: VerificationCommands
    availability: ProviderAvailability
    workspace: WorkspaceAccess
    provider: ProviderRuntime[StoredStopSignal]
    stop_signal: StopSignalFactory
    tasks: TaskWorkflows
    agents_settings: Callable[[], tuple[AgentConfig, ...]]
    read_git: Callable[[], GitWorkspace]
    ensure_verification: Callable[[RunState], None]
    lookup: RunLookup
    steps: RunStepLifecycle
    execution_settings: Callable[[], ExecutionConfig]
    read_repo: Callable[[], Path]

    def finish_verification_repair(self, run_id: str, verified: RunState) -> RunState:
        if verified.greenfield_phase == "feature_planning_ready":
            with self.records.planning_chat_lock(run_id):
                return self.planning_lifecycle.generate_features(verified, suppress_errors=True)
        return verified


    def restore_verification_repair_stop(self, run_id: str, stop_error: ExecutionStopped) -> RunState:
        state = self.records.load(run_id)
        if state.stage == Stage.FAILED and state.failed_step == RunStep.VERIFY:
            target = self.verification_commands.verification_resume_stage(state)
            state.resume_to(target, f"verification repair stopped; restored to {target.value}")
        state.active_step = None
        state.failed_step = None
        state.failure_message = ""
        state.update_verification_progress(
            "stopped",
            "사용자가 검증 자동 수정을 중지했습니다.",
            current=state.verification_progress_current,
        )
        state.add_event("verification", "verification repair stopped by user")
        self.records.save(state)
        stop_request_id = stop_error.request_id
        if stop_request_id:
            self.control.record_checkpoint(state, stop_request_id)
            self.control.confirm_stopped(state.id, stop_request_id)
        return state


    @staticmethod
    def verification_failure_is_repairable(error: Exception) -> bool:
        return verification_failure_is_repairable(str(error))


    def repair_verification_failure(self, state: RunState, error: Exception, repair_index: int) -> None:
        repair = VerificationRepairRunner(
            available=lambda agent: self.availability.is_available(agent, "execute"),
            run_directory=self.records.run_dir,
            save_state=self.records.save,
            stop_signal=lambda state: self.stop_signal(state, scope="verification"),
            check_stopped=raise_if_stopped,
            command=lambda agent, model: command_with_model(agent, agent_command(agent, "execute"), model),
            invoke=self.provider.invoke,
        )
        agent = repair.select_agent(self.agents_settings(), state.planning_agent_id)
        VerificationRepairWorkspace(
            git=self.read_git(), save_state=self.records.save, uses_shared=uses_shared_workspace,
            integration_branch=integration_branch_name, worktree_root=self.workspace.run_worktree_root,
            shared_boundary=self.workspace.shared_workspace_boundary, ensure_clean=self.workspace.ensure_worktree_clean,
            validate_scope=self.tasks.validate_task_change_scope, propose=repair.propose,
        ).repair(state, agent, error, repair_index)


    def verify_locked(self, run_id: str) -> RunState:
        state = self.lookup.at(
            run_id,
            {Stage.READY_TO_MERGE, Stage.VERIFIED, Stage.WORK_BRANCH_PUSHED, Stage.MERGED, Stage.FAILED},
        )
        if state.integration_user_checks_pending():
            raise PipelineError("통합에 필요한 사용자 확인을 먼저 통과로 기록해 주세요.")
        self.ensure_verification(state)
        if state.stage == Stage.FAILED:
            if state.failed_step != RunStep.VERIFY:
                failed_step = state.failed_step.value if state.failed_step else "unknown"
                raise PipelineError(f"통합 검증 재시도는 검증 실패 상태에서만 가능합니다: {failed_step}")
            target = self.verification_commands.verification_resume_stage(state)
            state.resume_to(target, f"verify failure restored to {target.value} for retry")
            self.records.save(state)
        if state.stage in {Stage.VERIFIED, Stage.WORK_BRANCH_PUSHED}:
            self.invalidate_integration_verification(state, "latest Main integration verification requested")
        commands, excluded_commands = self.integration_verification_command_selection(state)
        for command in excluded_commands:
            state.add_event("verification", f"오케스트레이터가 관리하는 worktree 명령을 통합 검증에서 제외했습니다: {' '.join(command)}")
        if excluded_commands:
            self.records.save(state)
        if not commands:
            if excluded_commands:
                raise PipelineError("통합 검증에 실행할 수 있는 명령이 없습니다. git worktree 명령은 오케스트레이터가 관리하므로 검증 명령에서 제외됩니다.")
            raise PipelineError("통합 검증 명령이 설정되거나 계획되지 않았습니다.")
        if state.stage == Stage.MERGED and state.verified_task_heads:
            raise PipelineError("run already passed pre-merge verification")
        with self.steps.step(state, RunStep.VERIFY):
            if state.greenfield_phase in {"bootstrap_ready", "bootstrap_running"}:
                state.greenfield_phase = "bootstrap_verifying"
            state.begin_verification(len(commands))
            self.records.save(state)
            if not self.execution_settings().verify_commands:
                state.add_event(
                    "verification", f"execution.verify_commands not configured; using {len(commands)} unique task verification commands"
                )
                self.records.save(state)
            if state.stage == Stage.READY_TO_MERGE:
                if uses_shared_workspace(state):
                    return self.verify_shared_workspace(state, commands)
                return self.verify_before_merge(state, commands)
            return self.verify_legacy_merged_run(state, commands)


    def integration_verification_command_selection(self, state: RunState) -> tuple[tuple[tuple[str, ...], ...], tuple[tuple[str, ...], ...]]:
        return integration_verification_command_selection(
            state, self.execution_settings().verify_commands, managed_command=is_orchestrator_managed_verification_command,
        )


    def record_verification_failure(
        self,
        state: RunState,
        command: tuple[str, ...],
        phase: str,
        *,
        command_failed: bool,
    ) -> None:
        VerificationFailureEvidence(
            has_project_commands=lambda: bool(self.execution_settings().verify_commands),
            commit_queue_tasks=commit_queue_tasks, save_state=self.records.save,
        ).record(state, command, phase, command_failed=command_failed)


    def candidate_verification(self) -> CandidateVerification:
        return CandidateVerification(
            git=self.read_git(), repo=self.read_repo(), save_state=self.records.save,
            ensure_workspace_ready=self.workspace.ensure_execution_workspace_ready, commit_queue_tasks=commit_queue_tasks,
            verification_worktree=self.workspace.verification_worktree_path, integration_branch=integration_branch_name,
            run_verification=self.run_pinned_verification, shared_boundary=self.workspace.shared_workspace_boundary,
            ensure_clean=self.workspace.ensure_worktree_clean, conflict_fingerprint=integration_conflict_fingerprint,
        )


    def verify_before_merge(self, state: RunState, commands: tuple[tuple[str, ...], ...]) -> RunState:
        candidate = self.candidate_verification().isolated(state, commands)
        task_heads = candidate.task_heads
        main_head = candidate.main_head
        integration_head = candidate.integration_head
        state.verified_task_heads = task_heads
        state.verified_main_head = main_head
        state.verified_integration_head = integration_head
        state.verification_repair_head = integration_head
        self.complete_greenfield_bootstrap(state)
        state.transition(Stage.VERIFIED, "latest main integration commit verified")
        self.records.save(state)
        return state


    def verify_shared_workspace(self, state: RunState, commands: tuple[tuple[str, ...], ...]) -> RunState:
        candidate = self.candidate_verification().shared(state, commands)
        main_head = candidate.main_head
        integration_head = candidate.integration_head
        state.verified_task_heads = candidate.task_heads
        state.verified_main_head = main_head
        state.verified_integration_head = integration_head
        state.pushed_work_branch_head = ""
        self.complete_greenfield_bootstrap(state)
        state.transition(Stage.VERIFIED, "shared run workspace commit verified")
        self.records.save(state)
        return state


    def invalidate_integration_verification(self, state: RunState, message: str) -> None:
        state.verified_task_heads = {}
        state.verified_main_head = ""
        state.verified_integration_head = ""
        state.pushed_work_branch_head = ""
        state.verification_repair_head = ""
        state.verification_repair_main_head = ""
        state.verification_repair_task_heads = {}
        state.transition(Stage.READY_TO_MERGE, message)
        self.records.save(state)


    def verify_legacy_merged_run(self, state: RunState, commands: tuple[tuple[str, ...], ...]) -> RunState:
        attempt = state.verification_attempts[-1]
        attempt.main_head = self.read_git().head(self.read_repo(), non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        attempt.task_heads = {task.id: task.completed_commit for task in state.tasks}
        attempt.commit_queue_task_ids = [task.id for task in commit_queue_tasks(state)]
        self.run_pinned_verification(state, self.read_repo(), commands)
        state.update_verification_progress("finalizing", "검증 결과를 저장하고 있습니다.", current=len(commands), total=len(commands))
        self.records.save(state)
        self.complete_greenfield_bootstrap(state)
        state.transition(Stage.VERIFIED, "verification commands passed")
        self.records.save(state)
        return state


    @staticmethod
    def complete_greenfield_bootstrap(state: RunState) -> None:
        if state.repository_intent != "new_project" or state.greenfield_phase != "bootstrap_verifying":
            return
        if state.bootstrap_spec is None:
            raise PipelineError("검증된 기본 구조를 기록할 BootstrapSpec이 없습니다.")
        integration_head = state.verified_integration_head
        if not integration_head and state.verification_attempts:
            integration_head = state.verification_attempts[-1].integration_head
        if not integration_head:
            raise PipelineError("검증된 기본 구조 commit을 확인할 수 없습니다.")
        state.bootstrap_spec.verified_integration_head = integration_head
        state.bootstrap_spec.verified_at = utc_now()
        state.bootstrap_spec.feature_plan_error = ""
        state.greenfield_phase = "feature_planning_ready"
        state.add_event("planning", "project bootstrap baseline verified; feature Planning is ready")


    def run_pinned_verification(self, state: RunState, cwd: Path, commands: tuple[tuple[str, ...], ...]) -> str:
        self.workspace.ensure_worktree_clean(cwd)
        head = self.read_git().head(cwd, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        state.verification_attempts[-1].integration_head = head
        self.records.save(state)
        self.run_verification_commands(state, cwd, commands, expected_head=head)
        self.verification_commands.ensure_verification_head(cwd, head)
        self.workspace.ensure_worktree_clean(cwd)
        return head


    def run_verification_commands(self, state: RunState, cwd: Path, commands: tuple[tuple[str, ...], ...], *, expected_head: str = "") -> None:
        RunVerificationCommands(
            records=RunVerificationRecords(self.records.run_dir, self.records.save),
            total_timeout=lambda: self.execution_settings().integration_verify_total_timeout_seconds,
            command_timeout=lambda: self.execution_settings().integration_verify_command_timeout_seconds,
            stop_signal=lambda current: self.stop_signal(current, scope="verification"),
            prepare_command=self.verification_commands.prepare_verification_command,
            execute_command=self.verification_commands.execute_verification_command,
            raise_if_stopped=raise_if_stopped, ensure_head=self.verification_commands.ensure_verification_head,
            record_failure=self.record_verification_failure,
        ).run(
            state,
            cwd,
            commands,
            expected_head=expected_head,
        )
