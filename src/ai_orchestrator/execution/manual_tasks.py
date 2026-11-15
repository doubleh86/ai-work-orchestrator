"""Manual Task workspace checks, deferral and completion evidence."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from ..errors import PipelineError
from ..git import GitError, GitWorkspace, LOCAL_GIT_TIMEOUT_SECONDS
from ..models import DirectionChangeStatus, ExecutionControlRecord, RunState, TaskAction, TaskStatus, WorkTask


class ManualWorkspaceCleanCheck(Protocol):
    def __call__(self, worktree: Path, *, non_interactive: bool, timeout_seconds: float) -> bool: ...


class ManualTaskResultRecorder(Protocol):
    def __call__(self, task: WorkTask, *, manual_verification_note: str) -> None: ...


@dataclass(frozen=True, slots=True)
class ManualWorkspaceInspector:
    git: GitWorkspace
    workspace_ready: Callable[[], None]
    uses_shared: Callable[[RunState], bool]
    shared_boundary: Callable[[RunState], tuple[str, Path]]
    worktree_root: Callable[[RunState], Path]
    is_clean: ManualWorkspaceCleanCheck

    def inspect(self, state: RunState, task: WorkTask) -> tuple[Path, str]:
        self.workspace_ready()
        if self.uses_shared(state):
            branch, worktree = self.shared_boundary(state)
        else:
            branch = f"ai/{state.id}/{task.id}"
            worktree = (self.worktree_root(state) / task.id).resolve()
            if task.branch != branch or not task.worktree or Path(task.worktree).resolve() != worktree:
                raise PipelineError("지정된 작업공간의 경로와 브랜치를 확인할 수 없습니다.")
        registered = self.git.list_worktrees(non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        if not task.worktree or not any(item.path == worktree and item.branch == branch for item in registered):
            raise PipelineError("작업공간의 Git 등록과 브랜치를 확인할 수 없습니다.")
        if not self.is_clean(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS):
            raise PipelineError("작업공간에 아직 커밋하지 않은 변경이 있습니다. 변경을 확인한 뒤 다시 시도해 주세요.")
        return worktree, self.git.head(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)


@dataclass(frozen=True, slots=True)
class ManualTaskDeferral:
    git: GitWorkspace
    uses_shared: Callable[[RunState], bool]
    find_task: Callable[[RunState, str], WorkTask]
    load_control: Callable[[str], ExecutionControlRecord | None]
    clean_workspace: Callable[[RunState, WorkTask], tuple[Path, str]]
    activate_tasks: Callable[[RunState], None]
    merge_dependencies: Callable[[RunState, WorkTask], None]
    save_state: Callable[[RunState], None]

    def set_deferred(self, state: RunState, run_id: str, task_id: str, *, deferred: bool) -> RunState:
        task = self.find_task(state, task_id)
        expected = TaskStatus.WAITING if deferred else TaskStatus.DEFERRED
        target = TaskStatus.DEFERRED if deferred else TaskStatus.WAITING
        if not self.uses_shared(state):
            raise PipelineError("공유 작업공간을 쓰는 작업 그룹에서 수동 검증을 보류할 수 있습니다.")
        if task.status == target:
            return state
        if task.status != expected or state.active_step or any(item.active_action for item in state.tasks):
            raise PipelineError("수동 작업 상태가 바뀌었습니다. 작업 상세에서 최신 상태를 확인해 주세요.")
        execution = self.load_control(run_id)
        if execution and execution.phase in {"running", "stopping", "confirmation_required"}:
            raise PipelineError("현재 실행의 종료를 확인한 뒤 수동 작업을 변경해 주세요.")
        owner = next((item for item in state.tasks if item.id != task_id and item.status in {
            TaskStatus.WAITING, TaskStatus.RUNNING, TaskStatus.REVIEWING, TaskStatus.REVISING,
        }), None)
        if owner is not None:
            raise PipelineError(f"‘{owner.title}’ 작업이 공유 작업공간을 사용 중입니다.")
        worktree, head = self.clean_workspace(state, task)
        baseline = task.started_commit
        if not baseline:
            raise PipelineError("수동 작업의 시작 커밋을 확인할 수 없습니다.")
        if deferred:
            if head != baseline:
                raise PipelineError("수동 작업이 시작된 뒤 커밋이 바뀌었습니다. 변경 기록을 확인해 주세요.")
            task.status = target
            state.add_event("task", f"{task.id} manual verification deferred at {baseline}")
            if all(item.status == DirectionChangeStatus.APPLIED for item in state.direction_change_requests):
                self.activate_tasks(state)
        else:
            self.merge_dependencies(state, task)
            if not self.git.contains_branch(
                worktree, baseline, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
            ):
                raise PipelineError("현재 작업공간에서 보류 당시 커밋을 찾을 수 없습니다.")
            task.status = target
            task.started_commit = head
            state.add_event("task", f"{task.id} manual verification resumed at {head} (deferred at {baseline})")
        state.refresh_task_readiness()
        self.save_state(state)
        return state


@dataclass(frozen=True, slots=True)
class ManualTaskCompletion:
    git: GitWorkspace
    save_state: Callable[[RunState], None]
    verify_task: Callable[[RunState, WorkTask], None]
    ensure_clean: Callable[[Path], None]
    ensure_head: Callable[[Path, str], None]
    record_result: ManualTaskResultRecorder

    def complete(self, state: RunState, task: WorkTask, worktree: Path, *, manual_verification_note: str) -> None:
        try:
            self.verify_task(state, task)
            if manual_verification_note:
                self.ensure_clean(worktree)
                self.ensure_head(worktree, task.started_commit)
        except (GitError, PipelineError, OSError) as exc:
            task.status = TaskStatus.FAILED
            task.failed_action = task.failed_action or TaskAction.VERIFY
            task.error = str(exc)
            state.refresh_task_readiness()
            self.save_state(state)
            raise

        task.status = TaskStatus.COMPLETED
        task.completed_commit = task.started_commit if manual_verification_note else self.git.head(
            worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
        )
        self.record_result(task, manual_verification_note=manual_verification_note)
        task.active_action = None
        task.failed_action = None
        task.error = ""
        message = "manual verification recorded" if manual_verification_note else "manually completed and reviewed"
        state.add_event("task", f"{task.id} {message}")
