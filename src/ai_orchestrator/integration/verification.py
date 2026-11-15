"""Build and verify integration candidates under caller-owned run locks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..errors import PipelineError, VerificationInputsChanged
from ..git import GitError, GitWorkspace, LOCAL_GIT_TIMEOUT_SECONDS
from ..models import ConflictResolutionStatus, IntegrationConflict, IntegrationConflictFile, RunState, TaskStatus, WorkTask


@dataclass(frozen=True, slots=True)
class VerifiedCandidate:
    main_head: str
    integration_head: str
    task_heads: dict[str, str]


@dataclass(frozen=True, slots=True)
class CandidateVerification:
    git: GitWorkspace
    repo: Path
    save_state: Callable[[RunState], None]
    ensure_workspace_ready: Callable[[], None]
    commit_queue_tasks: Callable[[RunState], list[WorkTask]]
    verification_worktree: Callable[[RunState], Path]
    integration_branch: Callable[[str], str]
    run_verification: Callable[[RunState, Path, tuple[tuple[str, ...], ...]], str]
    shared_boundary: Callable[[RunState], tuple[str, Path]]
    ensure_clean: Callable[[Path], None]
    conflict_fingerprint: Callable[[str, str, list[IntegrationConflictFile]], str]

    def isolated(self, state: RunState, commands: tuple[tuple[str, ...], ...]) -> VerifiedCandidate:
        state.update_verification_progress("checking_main", "Main 작업공간과 현재 commit을 확인하고 있습니다.", total=len(commands))
        self.save_state(state)
        self.ensure_workspace_ready()
        if not all(task.status == TaskStatus.COMPLETED for task in state.tasks):
            raise PipelineError("pre-merge verification requires completed tasks")
        main_head = self.git.head(self.repo, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        queue_tasks = self.commit_queue_tasks(state)
        task_heads: dict[str, str] = {}
        attempt = state.verification_attempts[-1]
        attempt.main_head = main_head
        attempt.task_heads = task_heads
        attempt.commit_queue_task_ids = [task.id for task in queue_tasks]
        for index, task in enumerate(queue_tasks, start=1):
            state.update_verification_progress("checking_task_branches", task.title or task.id, current=index, total=len(state.tasks))
            self.save_state(state)
            task_heads[task.id] = self.git.branch_head(task.branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        worktree = self.verification_worktree(state)
        integration_branch = self.integration_branch(state.id)
        reusable_repair_head = ""
        if (
            state.verification_repair_head
            and state.verification_repair_main_head == main_head
            and state.verification_repair_task_heads == task_heads
            and self.git.branch_exists(integration_branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            and self.git.branch_head(integration_branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            == state.verification_repair_head
        ):
            reusable_repair_head = state.verification_repair_head
        state.update_verification_progress("preparing_worktree", "검증 전용 detached worktree를 만들고 있습니다.", current=0, total=len(state.tasks))
        self.save_state(state)
        self.git.prepare_detached_worktree(
            worktree,
            reusable_repair_head or main_head,
            non_interactive=True,
            timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
        )
        integration_head = ""
        try:
            if not reusable_repair_head:
                for index, task in enumerate(queue_tasks, start=1):
                    state.update_verification_progress("integrating_tasks", task.title or task.id, current=index, total=len(state.tasks))
                    self.save_state(state)
                    try:
                        self.git.merge_into(
                            worktree,
                            task_heads[task.id],
                            f"verify({state.id}): integrate {task.id}",
                            non_interactive=True,
                            timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
                        )
                    except GitError as exc:
                        attempt.failed_task_id = task.id
                        attempt.failure_phase = "integration_merge"
                        attempt.candidate_task_ids = [task.id]
                        attempt.attribution_reason = "Task commit을 통합하는 Git merge가 해당 Task에서 직접 실패했습니다."
                        self.git.abort_merge(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
                        raise PipelineError(f"verification integration failed at {task.id}: {exc}") from exc
                    attempt.last_integrated_task_id = task.id
                    self.save_state(state)
                candidate_head = self.git.head(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
                self.git.update_branch(integration_branch, candidate_head, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
                state.verification_repair_head = candidate_head
                state.verification_repair_main_head = main_head
                state.verification_repair_task_heads = dict(task_heads)
                self.save_state(state)
            integration_head = self.run_verification(state, worktree, commands)
            state.update_verification_progress("finalizing", "검증 결과와 통합 commit을 저장하고 있습니다.", current=len(commands), total=len(commands))
            self.save_state(state)
            self.git.update_branch(
                integration_branch, integration_head, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
            )
            self.ensure_inputs_current(state, main_head, task_heads)
        finally:
            self.git.discard_detached_worktree(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        return VerifiedCandidate(main_head, integration_head, task_heads)

    def shared(self, state: RunState, commands: tuple[tuple[str, ...], ...]) -> VerifiedCandidate:
        state.update_verification_progress("checking_main", "Main과 공유 작업 branch 상태를 확인하고 있습니다.", total=len(commands))
        self.save_state(state)
        self.ensure_workspace_ready()
        if not all(task.status == TaskStatus.COMPLETED for task in state.tasks):
            raise PipelineError("shared workspace verification requires completed tasks")
        branch, worktree = self.shared_boundary(state)
        registered = {item.path: item for item in self.git.list_worktrees(non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)}
        entry = registered.get(worktree)
        if entry is None or entry.branch != branch:
            raise PipelineError("shared run worktree is not registered on its expected branch")
        self.ensure_clean(worktree)
        main_head = self.git.head(self.repo, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        work_head = self.git.head(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        attempt = state.verification_attempts[-1]
        attempt.main_head = main_head
        attempt.task_heads = {task.id: task.completed_commit for task in state.tasks}
        attempt.commit_queue_task_ids = [task.id for task in self.commit_queue_tasks(state)]
        self.save_state(state)
        if not self.git.contains_branch(worktree, state.main_branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS):
            state.update_verification_progress("syncing_main", "최신 로컬 Main을 공유 작업 branch에 통합하고 있습니다.", total=len(commands))
            self.save_state(state)
            try:
                self.git.merge_into(
                    worktree,
                    main_head,
                    f"merge({state.id}): synchronize main before verification",
                    non_interactive=True,
                    timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
                )
            except GitError as exc:
                entries = self.git.unmerged_entries(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
                if not entries:
                    self.git.abort_merge(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
                    raise PipelineError(f"shared run could not integrate latest main: {exc}") from exc
                files = [
                    IntegrationConflictFile(
                        path=item.path,
                        kind=item.kind,
                        base_blob=item.base_blob,
                        work_blob=item.work_blob,
                        main_blob=item.main_blob,
                        base_mode=item.base_mode,
                        work_mode=item.work_mode,
                        main_mode=item.main_mode,
                        binary=item.binary,
                        supported=item.supported,
                    )
                    for item in entries
                ]
                fingerprint = self.conflict_fingerprint(main_head, work_head, files)
                conflict = IntegrationConflict(
                    id=f"conflict-{fingerprint[:16]}",
                    verification_attempt_id=attempt.id,
                    main_head=main_head,
                    work_head=work_head,
                    merge_base_heads=self.git.merge_base(
                        worktree, work_head, main_head, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
                    ),
                    files=files,
                    fingerprint=fingerprint,
                )
                recovery_task = state.register_integration_conflict(conflict)
                conflict = recovery_task.conflict
                self.save_state(state)
                try:
                    self.git.abort_merge_checked(
                        worktree, work_head, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
                    )
                    conflict.abort_status = "verified"
                except GitError as abort_exc:
                    conflict.abort_status = "failed"
                    conflict.abort_error = str(abort_exc)
                    conflict.resolution_status = ConflictResolutionStatus.WORKSPACE_RECOVERY_REQUIRED
                    conflict.error = f"merge failed: {exc}; abort failed: {abort_exc}"
                    self.save_state(state)
                    raise PipelineError(f"최신 Main 충돌 뒤 작업공간 복구를 확인하지 못했습니다: {abort_exc}") from exc
                state.add_event("integration_conflict", f"latest main conflict captured: {conflict.id}")
                self.save_state(state)
                raise PipelineError(f"최신 Main과 {len(files)}개 파일이 충돌했습니다. Operations에서 AI 해결안을 검토하세요.") from exc
        integration_head = self.run_verification(state, worktree, commands)
        self.ensure_clean(worktree)
        state.update_verification_progress("finalizing", "검증한 공유 작업 commit을 저장하고 있습니다.", current=len(commands), total=len(commands))
        self.save_state(state)
        current_main = self.git.branch_head(state.main_branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        current_work = self.git.head(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        if current_main != main_head or current_work != integration_head:
            raise VerificationInputsChanged(
                "검증 중 Main 또는 공유 작업 결과가 변경되었습니다. 완료한 Task는 보존되며 최신 Main 기준 재검증이 필요합니다."
            )
        return VerifiedCandidate(main_head, integration_head, {task.id: task.completed_commit or integration_head for task in state.tasks})

    def ensure_inputs_current(
        self, state: RunState, main_head: str, task_heads: dict[str, str]
    ) -> None:
        current_main = self.git.branch_head(state.main_branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        changed_tasks = [
            task.id
            for task in state.tasks
            if self.git.branch_head(task.branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            != task_heads.get(task.id)
        ]
        if current_main != main_head or changed_tasks:
            suffix = f" 변경된 Task: {', '.join(changed_tasks)}." if changed_tasks else ""
            raise VerificationInputsChanged(
                "검증 중 Main 또는 작업 결과가 변경되었습니다. 완료한 Task는 보존되며 최신 Main 기준 재검증이 필요합니다."
                + suffix
            )
