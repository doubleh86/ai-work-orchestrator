"""IntegrationCommands with explicit phase and persistence dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from ..config import ExecutionConfig, ProjectConfig
from ..errors import ApprovalRequired as ApprovalRequired, PipelineError
from ..execution import ExecutionControlService
from ..execution.operation_lifecycle import RunStepLifecycle
from ..execution_control import ExecutionStopped
from ..git import GitError, GitWorkspace, LOCAL_GIT_TIMEOUT_SECONDS
from ..integration import MainChangeService, conflict_request_id, integration_branch_name, require_integration_conflict, uses_shared_workspace
from ..integration.conflict_flow import ConflictFlow
from ..integration.conflict_verification import ConflictResolutionVerification, ConflictVerificationRecords
from ..integration.main_apply_flow import MainApplyFlow
from ..integration.main_preflight import IsolatedMainApplyPreflight
from ..integration.verification_flow import VerificationFlow
from ..integration.workspace_access import WorkspaceAccess
from ..integration.workspace_flows import WorkspaceFlows
from ..models import (
    MainChangeDiff,
    MainChangeSnapshot,
    MainMutationResult,
    RepositoryUpdate,
    RunExecutionSituation,
    RunLockState,
    RunLockStatus,
    RunState,
    RunStep,
    Stage,
)
from ..orchestration.control import RunControlCommands
from ..orchestration.queries import RunQueries
from ..persistence.errors import RunLockedError
from ..persistence.integration_records import IntegrationCommandsRecords
from ..persistence.run_lookup import RunLookup
from ..planning.apply_requests import normalize_planning_apply_request_id
from ..planning.lifecycle import PlanningLifecycle
from ..queries.control import RunControlQueries


@dataclass
class IntegrationCommands:
    records: IntegrationCommandsRecords
    main_changes_service: Callable[[], MainChangeService]
    project_settings: Callable[[], ProjectConfig]
    read_git: Callable[[], GitWorkspace]
    read_repo: Callable[[], Path]
    state_root: Callable[[], Path]
    main: MainApplyFlow
    runs: RunQueries
    workspaces: WorkspaceFlows
    controls: RunControlQueries
    verification: VerificationFlow
    steps: RunStepLifecycle
    workspace: WorkspaceAccess
    control: ExecutionControlService
    planning_lifecycle: PlanningLifecycle
    run_control: RunControlCommands
    conflicts: ConflictFlow
    lookup: RunLookup
    execution_settings: Callable[[], ExecutionConfig]

    def update_main(self, *, approved: bool = False) -> RepositoryUpdate:
        if not approved:
            raise ApprovalRequired("main update requires explicit approval")
        with self.records.project_git_lock("update-main"):
            (before_commit, after_commit) = self.read_git().update_main_ff_only(
                self.project_settings().remote,
                ignored_untracked_roots=(self.state_root(),),
            )
            snapshot = self.main_changes_service().snapshot(remote_checked=True)
        return RepositoryUpdate(
            repo_path=str(self.read_repo()),
            branch=self.project_settings().main_branch,
            remote=self.project_settings().remote,
            before_commit=before_commit,
            after_commit=after_commit,
            remaining_change_count=len(snapshot.changes),
            sync=snapshot.sync,
        )


    def main_changes(self, *, refresh_remote: bool = False) -> MainChangeSnapshot:
        with self.records.project_git_lock("inspect-main-changes"):
            remote_error = ""
            if refresh_remote:
                try:
                    self.read_git().refresh_main_remote(self.project_settings().remote)
                except GitError as exc:
                    remote_error = MainChangeService.safe_remote_error(exc)
            return self.main_changes_service().snapshot(remote_checked=refresh_remote, remote_error=remote_error)


    def main_change_diff(self, snapshot_id: str, path: str, mode: str) -> MainChangeDiff:
        with self.records.project_git_lock("inspect-main-change-diff"):
            return self.main_changes_service().diff(snapshot_id, path, mode)


    def commit_main_changes(
        self, snapshot_id: str, selections: list[tuple[str, str]], message: str, *, approved: bool = False
    ) -> MainMutationResult:
        if not approved:
            raise ApprovalRequired("Main change commit requires explicit approval")
        with self.records.project_git_lock("commit-main-changes"):
            return self.main_changes_service().commit(snapshot_id, selections, message)


    def push_main_commits(self, snapshot_id: str, *, approved: bool = False) -> MainMutationResult:
        if not approved:
            raise ApprovalRequired("Main push requires explicit approval")
        with self.records.project_git_lock("push-main-commits"):
            return self.main_changes_service().push(snapshot_id)


    def commit_and_push_main_changes(
        self,
        snapshot_id: str,
        selections: list[tuple[str, str]],
        message: str,
        *,
        approved: bool = False,
    ) -> MainMutationResult:
        if not approved:
            raise ApprovalRequired("Main change commit and push requires explicit approval")
        with self.records.project_git_lock("commit-and-push-main-changes"):
            return self.main_changes_service().commit_and_push(snapshot_id, selections, message)


    def preview_main_apply(self, run_id: str) -> dict[str, object]:
        state, execution, integration = self.runs.status_with_controls(run_id)
        review = self.main.main_apply_review(state, integration)
        if execution.lock_state != RunLockState.UNLOCKED or execution.situation == RunExecutionSituation.STATUS_UNKNOWN:
            review.update(review_id="", can_apply=False, reason=execution.reason, reason_code="execution_lock")
        return review


    def apply_reviewed_main(self, run_id: str, *, request_id: str, review_id: str, approved: bool) -> tuple[RunState, str]:
        if not review_id:
            raise PipelineError("Main 반영 미리보기가 필요합니다.")
        request_id = normalize_planning_apply_request_id(request_id)
        state = self.merge(run_id, approved=approved, request_id=request_id, review_id=review_id)
        operation = self.records.load_operation(run_id, request_id)
        if operation is None or operation.status != "succeeded" or not operation.target_head:
            raise PipelineError("로컬 Main 반영 기록을 확인하지 못했습니다.")
        return state, operation.target_head


    def merge(self, run_id: str, *, approved: bool, request_id: str = "", review_id: str = "") -> RunState:
        if not approved:
            raise ApprovalRequired("merge requires --approve")
        with self.records.project_git_lock("merge"):
            with self.records.lock(run_id, "merge"):
                state = self.records.load(run_id)
                if self.main.completed_operation_replay(state, "merge", request_id, review_id=review_id):
                    return state
                if review_id:
                    integration = self.controls.integration_control(state, RunLockStatus(run_id, RunLockState.UNLOCKED))
                    if self.main.main_apply_review(state, integration)["review_id"] != review_id:
                        raise PipelineError("Main 반영 대상이나 검증 상태가 바뀌었습니다. 미리보기를 다시 확인해 주세요.")
                if uses_shared_workspace(state):
                    return self.main.merge_shared_run(state, request_id, review_id=review_id)
                IsolatedMainApplyPreflight(
                    git=self.read_git(), repo=self.read_repo(), integration_branch=integration_branch_name,
                    invalidate=self.verification.invalidate_integration_verification, ensure_main_ready=self.workspaces.ensure_main_worktree_ready,
                ).validate(state, run_id)
                operation = self.main.claim_git_operation(state, "merge", request_id, "applying_main", review_id=review_id)
                try:
                    with self.steps.step(state, RunStep.MERGE):
                        return self.main.merge_isolated(state, operation)
                except Exception as exc:
                    self.main.fail_git_operation(operation, exc)
                    raise


    def recover_main_apply(
        self, run_id: str, *, approved: bool, request_id: str = "", expected_repo: str = "", expected_commit: str = "",
    ) -> RunState:
        if not approved:
            raise ApprovalRequired("interrupted Main apply recovery requires --approve")
        state = self.records.load(run_id)
        source = self.records.latest_operation(run_id, "merge")
        remote_configured = self.read_git().remote_configured(self.project_settings().remote)
        if (
            (expected_repo and expected_repo != state.repo_path)
            or (expected_commit and (source is None or expected_commit != source.target_head))
        ):
            raise PipelineError("복구 승인 창의 저장소 또는 검증 commit이 현재 기록과 달라 복구하지 않았습니다.")
        if self.main.completed_operation_replay(state, "recover_main_apply", request_id):
            return state
        if source is None or not self.main.main_apply_recovery_ready(
            state, source, self.records.inspect_lock(run_id), remote_configured
        ):
            raise PipelineError(
                "중단된 Main 반영의 ref·index·작업 폴더가 검증 commit과 일치하지 않아 "
                "복구 승인을 적용하지 않았습니다."
            )

        self.records.clear_stale_project_git_lock(expected_operation="merge")
        with self.records.project_git_lock("recover-main-apply"):
            run_lock = self.records.inspect_lock(run_id)
            if run_lock.state == RunLockState.STALE and run_lock.operation == "merge":
                self.records.clear_stale_lock(run_id)
            elif run_lock.state != RunLockState.UNLOCKED:
                raise RunLockedError("중단된 Main 반영의 실행 잠금이 변경되어 복구를 중단했습니다.")
            with self.records.lock(run_id, "recover-main-apply"):
                state = self.records.load(run_id)
                source = self.records.latest_operation(run_id, "merge")
                if (
                    (expected_repo and expected_repo != state.repo_path)
                    or (expected_commit and (source is None or expected_commit != source.target_head))
                ):
                    raise PipelineError("복구 승인 중 저장소 또는 검증 commit 기록이 변경되었습니다.")
                if source is None or not self.main.main_apply_recovery_ready(
                    state, source, self.records.inspect_lock(run_id), remote_configured, require_stale_locks=False
                ):
                    raise PipelineError("복구 승인 중 Main ref·index·작업 폴더 또는 검증 기록이 변경되었습니다.")
                operation = self.main.claim_git_operation(state, "recover_main_apply", request_id, "confirming_main")
                try:
                    source.update("main_applied", status="interrupted", error="interrupted local Main apply confirmed by approved recovery")
                    source.result_commit = source.target_head
                    self.records.save_operation(source)
                    if uses_shared_workspace(state):
                        if remote_configured:
                            state.add_event("merge", "interrupted local Main apply confirmed; separate Main Push approval is required")
                            self.records.save(state)
                        else:
                            state = self.main.finish_shared_main_apply(state, source, remote_configured=False)
                            state.complete_step(RunStep.MERGE)
                            self.records.save(state)
                    else:
                        state = self.main.finish_isolated_main_apply(state, source)
                        state.complete_step(RunStep.MERGE)
                        self.records.save(state)
                    operation.result_commit = source.target_head
                    operation.update("main_apply_recovered", status="succeeded")
                    self.records.save_operation(operation)
                    return state
                except Exception as exc:
                    self.main.fail_git_operation(operation, exc)
                    raise


    def retry_main_push(self, run_id: str, *, approved: bool, request_id: str = "") -> RunState:
        if not approved:
            raise ApprovalRequired("Main Push retry requires --approve")
        with self.records.project_git_lock("retry-main-push"), self.records.lock(run_id, "retry-main-push"):
            state = self.records.load(run_id)
            if self.main.completed_operation_replay(state, "retry_main_push", request_id):
                return state
            source = self.workspace.shared_main_push_recovery_source(state)
            if source is None:
                raise PipelineError("Main Push 재시도에 필요한 공유 그룹의 부분 반영 기록이 없습니다.")
            if not self.read_git().remote_configured(self.project_settings().remote):
                raise PipelineError("Main Push 재시도에는 설정된 원격 저장소가 필요합니다.")
            if state.main_branch != self.read_git().main_branch:
                raise PipelineError("기록된 Main branch와 현재 설정이 다릅니다. Main Push를 자동 재시도하지 않았습니다.")
            branch, _ = self.workspace.shared_workspace_boundary(state)
            if self.read_git().branch_head(branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS) != source.target_head:
                raise PipelineError("검증된 작업 branch가 변경되었습니다. Main Push를 자동 재시도하지 않았습니다.")
            self.read_git().ensure_main_branch(non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            current_main = self.read_git().head(self.read_repo(), non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            if current_main != source.target_head:
                raise PipelineError("Main이 검증된 commit에서 변경되었습니다. Main Push를 자동 재시도하지 않았습니다.")
            remote_main = self.read_git().remote_branch_head(self.project_settings().remote, state.main_branch)
            if remote_main not in {source.expected_main_head, source.target_head}:
                raise PipelineError("원격 Main이 이전 반영 이후 변경되었습니다. Main Push를 자동 재시도하지 않았습니다.")
            previous_retry = self.records.latest_operation(state.id, "retry_main_push")
            operation = self.main.claim_git_operation(state, "retry_main_push", request_id, "checking_remote")
            operation.scope = "main"
            self.records.save_operation(operation)
            if source.status == "running":
                source.update(source.phase, status="interrupted", error="Main Push recovery started after interrupted merge")
                self.records.save_operation(source)
            if previous_retry is not None and previous_retry.request_id != operation.request_id and previous_retry.status == "running":
                previous_retry.update(previous_retry.phase, status="interrupted", error="a newer Main Push recovery started")
                self.records.save_operation(previous_retry)
            try:
                with self.steps.step(state, RunStep.PUSH):
                    if remote_main != source.target_head:
                        operation.update("pushing")
                        self.records.save_operation(operation)
                        self.read_git().push(self.project_settings().remote)
                    self.main.confirm_push(state, operation, scope="main", branch=state.main_branch, local_commit=source.target_head)
                    return self.main.finish_shared_main_apply(state, operation, remote_configured=True)
            except Exception as exc:
                self.main.fail_git_operation(operation, exc)
                raise


    def result_artifact_info(self, run_id: str) -> dict[str, object]:
        from ..result_artifacts import ResultArtifact, inspect_result

        state = self.records.load(run_id)
        try:
            worktree, reference, scope = self.workspaces.result_workspace(state)
        except PipelineError as exc:
            return {"status": "unavailable", "can_launch": False, "reason": str(exc)}
        raw = self.records.load_result_artifact(run_id)
        if raw is None:
            return {"status": "not_configured", "can_launch": False, "reference_commit": reference, "verification_scope": scope,
                    "reason": "AI에게 실행할 결과물 준비를 요청해 주세요."}
        artifact = ResultArtifact.from_dict(raw)
        if artifact.reference_commit != reference:
            return {"status": "changed", "can_launch": False, "reason": "새로 검증한 결과물을 등록해 주세요."}
        return {**inspect_result(worktree, artifact), "verification_scope": scope}


    def register_result_artifact(self, run_id: str, *, kind: str, relative_path: str, expected_commit: str) -> dict[str, object]:
        from ..result_artifacts import ResultArtifact, artifact_digest, artifact_path

        with self.records.lock(run_id, "register_result"):
            state = self.records.load(run_id)
            worktree, reference, _ = self.workspaces.result_workspace(state)
            if expected_commit != reference:
                raise PipelineError("등록하려던 결과 버전이 바뀌었습니다. 검증 결과를 다시 확인해 주세요.")
            path = artifact_path(worktree, kind, relative_path)
            artifact = ResultArtifact(kind, relative_path, expected_commit, artifact_digest(path))
            self.records.save_result_artifact(run_id, artifact.to_dict())
            return self.result_artifact_info(run_id)


    def launch_result_artifact(self, run_id: str, *, expected_digest: str, device_id: str = "") -> dict[str, object]:
        from ..result_artifacts import ResultArtifact, launch_result

        with self.records.lock(run_id, "launch_result"):
            state = self.records.load(run_id)
            worktree, reference, _ = self.workspaces.result_workspace(state)
            raw = self.records.load_result_artifact(run_id)
            if raw is None:
                raise PipelineError("실행할 결과물이 아직 등록되지 않았습니다.")
            artifact = ResultArtifact.from_dict(raw)
            if artifact.reference_commit != reference:
                raise PipelineError("새로 검증한 결과물을 등록해 주세요.")
            return launch_result(worktree, artifact, expected_digest=expected_digest, device_id=device_id)


    def verify(self, run_id: str) -> RunState:
        with self.records.lock(run_id, "verify"):
            with self.control.owned_session(run_id, "verification"):
                try:
                    verified = self.verification.verify_locked(run_id)
                    if verified.greenfield_phase == "feature_planning_ready":
                        with self.records.planning_chat_lock(run_id):
                            return self.planning_lifecycle.generate_features(verified, suppress_errors=True)
                    return verified
                except ExecutionStopped:
                    return self.records.load(run_id)


    def verify_and_repair(self, run_id: str, *, request_id: str, chat_message: str = "", parent_request_id: str = "") -> RunState:
        with self.run_control.chat_control_child(run_id, parent_request_id, request_id, "verifying"):
            return self.run_control.verify_and_repair(run_id, request_id=request_id, chat_message=chat_message, parent_request_id=parent_request_id)


    def prepare_conflict_resolution(
        self,
        run_id: str,
        *,
        conflict_id: str,
        fingerprint: str,
        request_id: str,
        agent_id: str = "",
        model: str = "",
        reasoning_effort: str = "",
    ) -> dict[str, object]:
        normalized_request_id = conflict_request_id(request_id)
        with self.records.lock(run_id, "conflict-resolution-prepare"):
            state = self.records.load(run_id)
            conflict = require_integration_conflict(state, conflict_id=conflict_id, fingerprint=fingerprint)
            return self.conflicts.service().prepare(
                state, conflict, run_id=run_id, normalized_request_id=normalized_request_id,
                agent_id=agent_id, model=model, reasoning_effort=reasoning_effort,
            )


    def apply_conflict_resolution(
        self,
        run_id: str,
        *,
        conflict_id: str,
        candidate_id: str,
        candidate_revision: int,
        fingerprint: str,
        request_id: str,
        approved: bool,
    ) -> RunState:
        if not approved:
            raise ApprovalRequired("conflict resolution apply requires explicit approval")
        normalized_request_id = conflict_request_id(request_id)
        with self.records.lock(run_id, "conflict-resolution-apply"):
            state = self.records.load(run_id)
            conflict = require_integration_conflict(state, conflict_id=conflict_id, fingerprint=fingerprint)
            applied = self.conflicts.service().apply_candidate(
                state, conflict, candidate_id=candidate_id, candidate_revision=candidate_revision,
                normalized_request_id=normalized_request_id,
            )
            if applied is None:
                return state
            operation, candidate_worktree = applied
        return ConflictResolutionVerification(
            git=self.read_git(), verify=self.verify,
            records=ConflictVerificationRecords(self.records.load, self.records.save, self.records.save_operation, self.records.lock),
        ).finish(state, run_id=run_id, conflict_id=conflict_id, operation=operation, candidate_worktree=candidate_worktree)


    def push(self, run_id: str, *, approved: bool, request_id: str = "") -> RunState:
        if not approved:
            raise ApprovalRequired("push requires --approve")
        with self.records.project_git_lock("push"), self.records.lock(run_id, "push"):
            state = self.records.load(run_id)
            if not self.read_git().remote_configured(self.project_settings().remote):
                raise PipelineError("remote repository is not configured; local Main apply is available without Push")
            if self.main.completed_operation_replay(state, "push", request_id):
                return state
            if uses_shared_workspace(state):
                branch, branch_head = self.main.push_preflight().shared(state, run_id)
                operation = self.main.claim_git_operation(state, "push", request_id, "pushing")
                try:
                    with self.steps.step(state, RunStep.PUSH):
                        self.read_git().push_branch(self.project_settings().remote, branch)
                        self.main.confirm_push(
                            state,
                            operation,
                            scope="work_branch",
                            branch=branch,
                            local_commit=branch_head,
                        )
                        state.pushed_work_branch_head = branch_head
                        state.transition(Stage.WORK_BRANCH_PUSHED, "verified shared work branch pushed")
                        self.records.save(state)
                        operation.update("pushed", status="succeeded")
                        self.records.save_operation(operation)
                        return state
                except Exception as exc:
                    self.main.fail_git_operation(operation, exc)
                    raise
            self.main.push_preflight().isolated(state, run_id)
            operation = self.main.claim_git_operation(state, "push", request_id, "pushing")
            try:
                with self.steps.step(state, RunStep.PUSH):
                    return self.main.push_main(state, operation)
            except Exception as exc:
                self.main.fail_git_operation(operation, exc)
                raise


    def deploy(self, run_id: str, *, approved: bool) -> RunState:
        if not approved:
            raise ApprovalRequired("deploy requires --approve")
        with self.records.lock(run_id, "deploy"):
            allowed_stages = {Stage.PUSHED}
            if not self.read_git().remote_configured(self.project_settings().remote):
                allowed_stages.add(Stage.MERGED)
            state = self.lookup.at(run_id, allowed_stages)
            if not self.execution_settings().deploy_command:
                raise PipelineError("no execution.deploy_command configured")
            with self.steps.step(state, RunStep.DEPLOY):
                return self.main.deploy_command(state)


    def integration_conflict(self, run_id: str, *, conflict_id: str = "", file_path: str = "", recovery_task_id: str = "") -> dict[str, object]:
        return self.conflicts.view(run_id, conflict_id=conflict_id, file_path=file_path, recovery_task_id=recovery_task_id)
