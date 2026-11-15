from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from .layout import WorkspaceLayout, shared_run_branch_name, uses_shared_workspace, workspace_is_integrated
from ..errors import PipelineError
from ..git import GitError, GitWorkspace, GitWorktree, LOCAL_GIT_TIMEOUT_SECONDS
from ..models import (
    RunLockState,
    RunLockStatus,
    RunState,
    Stage,
    TaskStatus,
    WorkTask,
    WorkspaceState,
    WorkspaceStatus,
)


WORKSPACE_STATUS_TIMEOUT_SECONDS = 30


@dataclass(frozen=True, slots=True)
class WorkspaceInspector:
    git: GitWorkspace
    layout: WorkspaceLayout

    def ensure_clean(self, worktree: Path, *, timeout_seconds: float = LOCAL_GIT_TIMEOUT_SECONDS) -> None:
        self.git.ensure_worktree_clean(
            worktree,
            ignored_untracked_roots=self.layout.managed_state_roots(worktree),
            non_interactive=True,
            timeout_seconds=timeout_seconds,
        )

    def is_clean(self, worktree: Path, *, non_interactive: bool = False, timeout_seconds: float | None = None) -> bool:
        return not self.git.has_worktree_uncommitted_changes(
            worktree,
            ignored_untracked_roots=self.layout.managed_state_roots(worktree),
            non_interactive=non_interactive,
            timeout_seconds=timeout_seconds,
        )

    def status(
        self,
        state: RunState,
        task: WorkTask,
        registered: dict[Path, GitWorktree],
        *,
        require_unlocked: bool = True,
        non_interactive: bool = False,
        deadline: float | None = None,
        inspect_lock: Callable[[], RunLockStatus],
    ) -> WorkspaceStatus:
        def remaining_timeout() -> float | None:
            if deadline is None:
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GitError(f"workspace status check timed out after {WORKSPACE_STATUS_TIMEOUT_SECONDS}s")
            return remaining

        if uses_shared_workspace(state):
            expected_branch = shared_run_branch_name(state.id)
            expected_worktree = self.layout.shared_path(state).resolve()
            branch = state.execution_branch or task.branch or expected_branch
            configured_worktree = state.execution_worktree or task.worktree
        else:
            expected_branch = f"ai/{state.id}/{task.id}"
            expected_worktree = (self.layout.run_root(state) / task.id).resolve()
            branch = task.branch or expected_branch
            configured_worktree = task.worktree
        worktree = Path(configured_worktree).expanduser().resolve() if configured_worktree else expected_worktree
        entry = registered.get(worktree)
        worktree_exists = worktree.exists()
        worktree_registered = entry is not None
        branch_exists = self.git.branch_exists(branch, non_interactive=non_interactive, timeout_seconds=remaining_timeout())
        worktree_clean: bool | None = None
        branch_merged: bool | None = None
        if worktree_exists and worktree_registered:
            worktree_clean = self.is_clean(
                worktree, non_interactive=non_interactive, timeout_seconds=remaining_timeout()
            )
        if branch_exists:
            branch_merged = self.git.branch_is_merged(branch, non_interactive=non_interactive, timeout_seconds=remaining_timeout())

        common = {
            "run_id": state.id,
            "task_id": task.id,
            "run_stage": state.stage.value,
            "task_status": task.status.value,
            "branch": branch,
            "worktree": str(worktree),
            "worktree_exists": worktree_exists,
            "worktree_registered": worktree_registered,
            "worktree_clean": worktree_clean,
            "branch_exists": branch_exists,
            "branch_merged": branch_merged,
        }
        if branch != expected_branch or worktree != expected_worktree:
            return WorkspaceStatus(
                state=WorkspaceState.UNSAFE, cleanup_safe=False, reason="workspace does not match its deterministic boundary", **common
            )
        if worktree_exists and not worktree_registered:
            return WorkspaceStatus(state=WorkspaceState.UNSAFE, cleanup_safe=False, reason="worktree path exists but Git does not own it", **common)
        if entry is not None and entry.branch != branch:
            return WorkspaceStatus(
                state=WorkspaceState.UNSAFE, cleanup_safe=False, reason="registered worktree points to a different branch", **common
            )
        artifacts_exist = worktree_exists or worktree_registered or branch_exists
        if not artifacts_exist:
            prepared = bool(task.branch or task.worktree or state.execution_branch or state.execution_worktree)
            return WorkspaceStatus(
                state=(WorkspaceState.CLEANED if prepared and task.status == TaskStatus.MERGED else WorkspaceState.NOT_PREPARED),
                cleanup_safe=False,
                reason=(
                    "workspace artifacts were already removed"
                    if prepared and task.status == TaskStatus.MERGED
                    else "task workspace has not been prepared"
                ),
                **common,
            )
        if require_unlocked:
            lock = inspect_lock()
            if lock.state != RunLockState.UNLOCKED:
                return WorkspaceStatus(
                    state=WorkspaceState.ACTIVE, cleanup_safe=False, reason=(f"run lock is {lock.state.value}: {lock.reason}"), **common
                )
        if not workspace_is_integrated(state, task):
            return WorkspaceStatus(
                state=WorkspaceState.ACTIVE, cleanup_safe=False, reason="workspace has not reached a safely integrated run stage", **common
            )
        if worktree_clean is False:
            return WorkspaceStatus(state=WorkspaceState.UNSAFE, cleanup_safe=False, reason="worktree contains uncommitted changes", **common)
        if worktree_registered and not branch_exists:
            return WorkspaceStatus(state=WorkspaceState.UNSAFE, cleanup_safe=False, reason="registered worktree branch is missing", **common)
        if branch_exists and branch_merged is not True:
            return WorkspaceStatus(state=WorkspaceState.UNSAFE, cleanup_safe=False, reason="workspace branch is not contained in main", **common)
        return WorkspaceStatus(state=WorkspaceState.STALE, cleanup_safe=True, reason="merged workspace can be removed safely", **common)

    def result_workspace(self, state: RunState) -> tuple[Path, str, str]:
        if state.archive:
            raise PipelineError("보관한 작업의 실행 공간은 다시 사용할 수 없습니다.")
        _, worktree = self.layout.shared_boundary(state)
        if not worktree.is_dir():
            raise PipelineError("결과 작업공간이 아직 없거나 정리됐습니다.")
        head = self.git.head(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        if state.stage in {Stage.VERIFIED, Stage.WORK_BRANCH_PUSHED, Stage.MERGED, Stage.PUSHED, Stage.DEPLOYED}:
            if not state.verified_integration_head or head != state.verified_integration_head:
                raise PipelineError("검증한 결과가 변경됐습니다. 다시 검증해 주세요.")
            scope = "integration"
        elif state.stage in {Stage.EXECUTING, Stage.READY_TO_MERGE} and state.plan_is_approved and any(
            task.status in {TaskStatus.COMPLETED, TaskStatus.MERGED} and task.completed_commit == head for task in state.tasks
        ):
            scope = "task"
        else:
            raise PipelineError("실행할 개별 작업의 검증 또는 통합 검증을 먼저 완료해 주세요.")
        if not self.is_clean(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS):
            raise PipelineError("변경사항이 남아 있어 아직 실행할 수 없어요. 작업을 마무리하고 다시 검증해 주세요.")
        return worktree, head, scope


class WorkspaceStatusReader(Protocol):
    def __call__(
        self, state: RunState, task: WorkTask, registered: dict[Path, GitWorktree], *, non_interactive: bool, deadline: float,
    ) -> WorkspaceStatus: ...


@dataclass(frozen=True, slots=True)
class WorkspaceStatusQueries:
    ensure_repository: Callable[[float], None]
    load_run: Callable[[str], RunState]
    list_runs: Callable[[], list[RunState]]
    registered_worktrees: Callable[[float], list[GitWorktree]]
    uses_shared: Callable[[RunState], bool]
    task_status: WorkspaceStatusReader

    def statuses(self, run_id: str = "") -> list[WorkspaceStatus]:
        deadline = time.monotonic() + WORKSPACE_STATUS_TIMEOUT_SECONDS

        def remaining_timeout() -> float:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise GitError(f"workspace status check timed out after {WORKSPACE_STATUS_TIMEOUT_SECONDS}s")
            return remaining

        self.ensure_repository(remaining_timeout())
        states = [self.load_run(run_id)] if run_id else self.list_runs()
        registered = {worktree.path: worktree for worktree in self.registered_worktrees(remaining_timeout())}
        targets: list[tuple[RunState, WorkTask]] = []
        for state in states:
            if self.uses_shared(state):
                if state.tasks:
                    targets.append((state, state.tasks[0]))
                continue
            targets.extend((state, task) for task in state.tasks)
        if not targets:
            return []
        with ThreadPoolExecutor(max_workers=min(4, len(targets)), thread_name_prefix="workspace-status") as pool:
            futures = [
                pool.submit(self.task_status, state, task, registered, non_interactive=True, deadline=deadline) for state, task in targets
            ]
            return [future.result() for future in futures]
