"""Task execute/review/revise/verify resumption and bounded review cycles."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from ..errors import PipelineError
from ..git_contracts import LOCAL_GIT_TIMEOUT_SECONDS
from ..models import ReviewStatus, RunState, TaskAction, TaskStatus, WorkTask
from .task_prompts import render_task_attempt_prompt

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..git import GitWorkspace


class TaskAttemptInvocation(Protocol):
    def __call__(
        self, state: RunState, task: WorkTask, resume_action: TaskAction, *, prompt: str | None,
        repair_index: int, verification_environment: dict[str, str] | None, implementation_action_start: int,
    ) -> None: ...


class TaskExecutionInvocation(Protocol):
    def __call__(
        self, state: RunState, task: WorkTask, prompt: str, log_path: Path, commit_message: str, action: TaskAction,
        *, implementation_action_start: int | None = None,
    ) -> None: ...


class TaskVerificationInvocation(Protocol):
    def __call__(self, state: RunState, task: WorkTask, *, environment_overrides: dict[str, str] | None = None) -> None: ...


@dataclass(frozen=True, slots=True)
class TaskAttemptRunner:
    git: GitWorkspace
    run_directory: Callable[[str], Path]
    execute: TaskExecutionInvocation
    verify: TaskVerificationInvocation
    review_cycles: Callable[[RunState, WorkTask, str, int], None]
    revision_prompt: Callable[[WorkTask, str, dict[str, object], int], str]
    retry_instruction: Callable[[str, str], str]
    record_result: Callable[[WorkTask], None]

    def run(
        self, state: RunState, task: WorkTask, resume_action: TaskAction, *, prompt: str | None = None, repair_index: int = 0,
        verification_environment: dict[str, str] | None = None, implementation_action_start: int | None = None,
    ) -> None:
        verification_options = {"environment_overrides": verification_environment} if verification_environment else {}
        if resume_action == TaskAction.VERIFY:
            self.verify(state, task, **verification_options)
        else:
            prompt = prompt if prompt is not None else Path(task.prompt_path).read_text(encoding="utf-8")
            retry_instruction = self.retry_instruction(state.id, task.id) if resume_action == TaskAction.EXECUTE else ""
            prompt = render_task_attempt_prompt(
                prompt, implementation_notes=task.implementation_notes, retry_instruction=retry_instruction,
                stopped=bool(task.stop_request_id and task.action_results and task.action_results[-1].status == "interrupted"),
            )
            next_review_cycle = 1
            if resume_action == TaskAction.EXECUTE:
                task.status = TaskStatus.RUNNING
                if repair_index:
                    artifact = f"{task.id}-auto-repair-{repair_index}-{uuid.uuid4().hex[:12]}"
                    prompt_path = self.run_directory(state.id) / "prompts" / f"{artifact}.md"
                    prompt_path.parent.mkdir(parents=True, exist_ok=True)
                    prompt_path.write_text(prompt, encoding="utf-8")
                    logs = self.run_directory(state.id) / "logs"
                    for previous in logs.glob(f"{task.id}-*"):
                        if previous.is_file() and re.fullmatch(rf"{re.escape(task.id)}-(?:review|revision)-\d+\.(?:log|json)", previous.name):
                            suffix = previous.name[len(task.id) + 1:]
                            (logs / f"{artifact}-previous-{suffix}").write_bytes(previous.read_bytes())
                    task.log_path = str(logs / f"{artifact}.log")
                message = f"fix({task.id}): repair verification {repair_index}" if repair_index else f"feat({task.id}): {task.title}"
                self.execute(
                    state, task, prompt, Path(task.log_path), message, TaskAction.EXECUTE, implementation_action_start=implementation_action_start
                )
            elif resume_action == TaskAction.REVIEW:
                if not task.reviewer_agent_id:
                    raise PipelineError(f"task {task.id} has no reviewer to resume")
                next_review_cycle = task.review_cycles + 1
            elif resume_action == TaskAction.REVISE:
                if not task.reviewer_agent_id or task.review_cycles < 1:
                    raise PipelineError(f"task {task.id} has no review revision to resume")
                review = {
                    "verdict": "changes_requested",
                    "summary": task.review_summary,
                    "findings": task.review_findings,
                }
                task.status = TaskStatus.REVISING
                revision_log = self.run_directory(state.id) / "logs" / f"{task.id}-revision-{task.review_cycles}.log"
                self.execute(
                    state,
                    task,
                    self.revision_prompt(task, prompt, review, task.review_cycles),
                    revision_log,
                    f"fix({task.id}): address review {task.review_cycles}",
                    TaskAction.REVISE,
                )
                next_review_cycle = task.review_cycles + 1

            if not task.reviewer_agent_id:
                task.review_status = ReviewStatus.NOT_REQUIRED
            else:
                self.review_cycles(state, task, prompt, next_review_cycle)
            self.verify(state, task, **verification_options)
        task.completed_commit = self.git.head(Path(task.worktree), non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        self.record_result(task)


@dataclass(frozen=True, slots=True)
class TaskReviewCycles:
    max_cycles: int
    git: GitWorkspace
    review: Callable[[RunState, WorkTask, int], dict[str, object]]
    record_review: Callable[[WorkTask, dict[str, object], int, str], None]
    save_progress: Callable[[RunState], None]
    revision_prompt: Callable[[WorkTask, str, dict[str, object], int], str]
    run_directory: Callable[[str], Path]
    execute: TaskExecutionInvocation

    def run(self, state: RunState, task: WorkTask, original_prompt: str, start_cycle: int) -> None:
        maximum = self.max_cycles
        if start_cycle > maximum:
            raise PipelineError(f"task {task.id} reached the review cycle limit")
        for cycle in range(start_cycle, maximum + 1):
            task.status = TaskStatus.REVIEWING
            task.review_status = ReviewStatus.RUNNING
            head = self.git.head(Path(task.worktree), non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            review = self.review(state, task, cycle)
            self.record_review(task, review, cycle, head)
            self.save_progress(state)
            if review["verdict"] == "approved":
                return
            if cycle >= maximum:
                raise PipelineError(f"task {task.id} review was not approved after {cycle} cycles")
            task.status = TaskStatus.REVISING
            revision_prompt = self.revision_prompt(task, original_prompt, review, cycle)
            revision_log = self.run_directory(state.id) / "logs" / f"{task.id}-revision-{cycle}.log"
            self.execute(state, task, revision_prompt, revision_log, f"fix({task.id}): address review {cycle}", TaskAction.REVISE)
