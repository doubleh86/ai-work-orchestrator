"""Task recovery attempts with caller-owned policy, scope and cancellation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, ContextManager

from ..errors import PipelineError
from ..models import RunState, TaskAction, TaskStatus, WorkTask
from .errors import TaskVerificationFailure
from .recovery import automatic_recovery_decision
from .task_attempts import TaskAttemptInvocation
from .task_prompts import render_automatic_correction_prompt


@dataclass(frozen=True, slots=True)
class TaskRecoveryRunner:
    recovery_limit: int
    run_attempt: TaskAttemptInvocation
    failure_fingerprint: Callable[[TaskVerificationFailure], str]
    stop_check: Callable[[RunState, WorkTask], Callable[[], None]]
    ensure_verification_head: Callable[[Path, str], None]
    validate_scope: Callable[[WorkTask, RunState], list[str] | None]
    ensure_clean: Callable[[Path], None]
    promote_model: Callable[[RunState, WorkTask, TaskVerificationFailure], None]
    state_lock: ContextManager[object]
    save_state: Callable[[RunState], None]

    def run(self, state: RunState, task: WorkTask, resume_action: TaskAction = TaskAction.EXECUTE) -> None:
        original_prompt = Path(task.prompt_path).read_text(encoding="utf-8") if resume_action != TaskAction.VERIFY else None
        failures: dict[str, tuple[str, str]] = {}
        repair_prompt = original_prompt
        repairs = 0
        environment_retries = 0
        verification_environment: dict[str, str] | None = None
        implementation_action_start = len(task.action_results) if resume_action == TaskAction.EXECUTE else 0
        for recovery_index in range(self.recovery_limit + 1):
            try:
                self.run_attempt(
                    state, task, resume_action, prompt=repair_prompt, repair_index=repairs,
                    verification_environment=verification_environment, implementation_action_start=implementation_action_start,
                )
                return
            except TaskVerificationFailure as exc:
                fingerprint = self.failure_fingerprint(exc)
                verification_context = (task.action_results[-1].baseline_commit, task.action_results[-1].verification_context_digest)
                decision = automatic_recovery_decision(
                    exc.command, exc.output, recovery_index=recovery_index, recovery_limit=self.recovery_limit,
                    environment_retries=environment_retries, same_failure=failures.get(fingerprint) == verification_context,
                )
                if decision.action == "retry_verification":
                    self.stop_check(state, task)()
                    self.ensure_verification_head(Path(task.worktree), task.action_results[-1].baseline_commit)
                    self.validate_scope(task, state)
                    self.ensure_clean(Path(task.worktree))
                    verification_environment = {
                        "DOTNET_CLI_USE_MSBUILD_SERVER": "0", "MSBUILDUSESERVER": "0", "MSBUILDDISABLENODEREUSE": "1",
                    }
                    environment_retries += 1
                    with self.state_lock:
                        task.status = TaskStatus.RUNNING
                        task.error = ""
                        state.add_event(
                            "task_repair",
                            f"{task.id} 검증만 자동 재시도 · {recovery_index + 1}/{self.recovery_limit} · MSBuild 서버/노드 재사용 안 함",
                        )
                        self.save_state(state)
                    resume_action = TaskAction.VERIFY
                    continue
                reason = decision.reason
                if reason:
                    with self.state_lock:
                        state.add_event("task_repair", f"{task.id} 자동 수정 중단: {reason}")
                        state.add_event("task_repair_handoff", f"{task.id}:{task.last_attempt_id}")
                        self.save_state(state)
                    raise PipelineError(f"{reason} {exc}") from exc
                self.stop_check(state, task)()
                verification = task.action_results[-1]
                self.ensure_verification_head(Path(task.worktree), verification.baseline_commit)
                self.validate_scope(task, state)
                self.promote_model(state, task, exc)
                repeated_failure = fingerprint in failures
                failures[fingerprint] = verification_context
                if original_prompt is None:
                    original_prompt = Path(task.prompt_path).read_text(encoding="utf-8")
                repairs += 1
                repair_prompt = render_automatic_correction_prompt(
                    original_prompt, repair_index=repairs, recovery_limit=self.recovery_limit,
                    failure_message=str(exc), verification_log=str(exc.log_path), command_output=exc.output, repeated_failure=repeated_failure,
                )
                with self.state_lock:
                    task.status = TaskStatus.RUNNING
                    task.error = ""
                    state.add_event(
                        "task_repair", f"{task.id} 검증 실패를 자동 수정합니다 · {recovery_index + 1}/{self.recovery_limit}"
                    )
                    self.save_state(state)
                resume_action = TaskAction.EXECUTE
