"""Execute, review and verify actions inside caller-owned action contexts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, ContextManager, Mapping, Protocol

from ..config import AgentConfig
from ..errors import PipelineError
from ..git_contracts import LOCAL_GIT_TIMEOUT_SECONDS
from ..models import RunState, TaskAction, WorkTask
from ..task_scope_review import task_scope_report
from .task_evidence import TaskStyleEvidence
from .task_attempts import TaskVerificationInvocation

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..git import GitWorkspace


class TaskActionContext(Protocol):
    def __call__(
        self, state: RunState, task: WorkTask, action: TaskAction, *, count_attempt: bool = True,
    ) -> ContextManager[None]: ...


class TaskReviewPrompt(Protocol):
    def __call__(self, state: RunState, task: WorkTask, cycle: int, *, manual_verification: bool = False) -> str: ...


class RecordedImplementation(Protocol):
    def __call__(self, task: WorkTask, head: str, *, action_start: int = 0) -> bool: ...


@dataclass(frozen=True, slots=True)
class TaskActionRunner:
    git: GitWorkspace
    agents: Mapping[str, AgentConfig]
    auto_commit: bool
    run_directory: Callable[[str], Path]
    action_context: TaskActionContext
    stop_check: Callable[[RunState, WorkTask], Callable[[], None]]
    prepare_prompt: Callable[[str, WorkTask], str]
    validate_scope: Callable[[WorkTask, RunState], list[str] | None]
    ensure_clean: Callable[[Path], None]
    save_progress: Callable[[RunState], None]
    refresh_style: TaskStyleEvidence
    invoke: Callable[[RunState, WorkTask, AgentConfig, str, Path, TaskAction], str]
    scope_digest: Callable[[WorkTask], str]
    recorded_implementation: RecordedImplementation
    state_lock: ContextManager[object]
    save_state: Callable[[RunState], None]
    review_prompt: TaskReviewPrompt
    parse_review: Callable[[str], dict[str, object]]
    perform_verification: TaskVerificationInvocation

    def execute(
        self, state: RunState, task: WorkTask, prompt: str, log_path: Path, commit_message: str, action: TaskAction,
        *, implementation_action_start: int | None = None,
    ) -> None:
        with self.action_context(state, task, action):
            worktree = Path(task.worktree)
            execution_prompt = self.prepare_prompt(prompt, task)
            before = self.git.head(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            action_result = task.action_results[-1]
            check_stopped = self.stop_check(state, task)
            check_stopped()
            action_result.baseline_commit = before
            self.save_progress(state)
            action_result.worker_response = self.invoke(state, task, self.agents[task.agent_id], execution_prompt, log_path, action)
            check_stopped()
            action_result.changed_paths = self.git.task_changed_paths(
                worktree, before, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
            )
            self.refresh_style(state, task, action_result)
            action_result.result_commit = self.git.head(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            self.validate_scope(task, state)
            check_stopped()
            try:
                review = task_scope_report(action_result.worker_response,
                                           legacy=before == action_result.result_commit and not action_result.changed_paths)
            except ValueError as exc:
                raise PipelineError(f"에이전트의 범위 확인 보고를 읽지 못했습니다: {exc}") from exc
            if review is not None:
                raise PipelineError(review.error(self.scope_digest(task)))
            if self.auto_commit:
                self.git.commit_all(worktree, commit_message, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            check_stopped()
            self.validate_scope(task, state)
            after = self.git.head(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            if before == after:
                if (action != TaskAction.EXECUTE or implementation_action_start is None
                        or not self.recorded_implementation(task, after, action_start=implementation_action_start)):
                    raise PipelineError(f"agent {task.agent_id} produced no commit for {task.id}")
                self.ensure_clean(worktree)
                with self.state_lock:
                    state.add_event("task_repair", f"{task.id} 기존 구현 commit을 보존하고 리뷰·검증을 계속합니다 · {after}")
                    self.save_state(state)
            action_result.result_commit = after

    def review(self, state: RunState, task: WorkTask, cycle: int, *, manual_verification: bool = False) -> dict[str, object]:
        with self.action_context(state, task, TaskAction.REVIEW):
            worktree = Path(task.worktree)
            check_stopped = self.stop_check(state, task)
            check_stopped()
            self.validate_scope(task, state)
            self.ensure_clean(worktree)
            before = self.git.head(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            prompt = self.review_prompt(state, task, cycle, manual_verification=manual_verification)
            log_path = self.run_directory(state.id) / "logs" / f"{task.id}-review-{cycle}.log"
            output = self.invoke(state, task, self.agents[task.reviewer_agent_id], prompt, log_path, TaskAction.REVIEW)
            check_stopped()
            after = self.git.head(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            if before != after:
                raise PipelineError(f"reviewer {task.reviewer_agent_id} changed HEAD for {task.id}")
            self.ensure_clean(worktree)
            review = self.parse_review(output)
            action_result = task.action_results[-1]
            action_result.baseline_commit = before
            action_result.result_commit = after
            action_result.review_verdict = str(review["verdict"])
            action_result.review_findings = list(review["findings"])
            result_path = log_path.with_suffix(".json")
            result_path.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return review

    def verify(self, state: RunState, task: WorkTask, *, environment_overrides: dict[str, str] | None = None) -> None:
        with self.action_context(state, task, TaskAction.VERIFY, count_attempt=False):
            result = task.action_results[-1]
            result.baseline_commit = self.git.head(Path(task.worktree), non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            scope_paths = self.validate_scope(task, state)
            result.changed_paths = scope_paths if scope_paths is not None else self.git.task_changed_paths(
                Path(task.worktree), task.started_commit or result.baseline_commit, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
            )
            self.refresh_style(state, task, result)
            options = {"environment_overrides": environment_overrides} if environment_overrides else {}
            self.perform_verification(state, task, **options)
            self.validate_scope(task, state)
            result.result_commit = self.git.head(Path(task.worktree), non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
