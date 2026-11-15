"""Task verification budgets, progress, context and failure evidence."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, ContextManager, Mapping, Sequence

from ..codex_sdk import CodexSdkProgress
from ..execution_control import CancellationSignal
from ..git_contracts import GitError
from ..models import RunState, TaskAction, TaskStatus, WorkTask, utc_now
from .errors import TaskVerificationFailure, TaskVerificationTimeout
from .task_evidence import TaskStyleEvidence
from .task_verification import TaskVerificationFailed, TaskVerificationRunner, TaskVerificationRuntimeOptions, TaskVerificationTimedOut
from .verification_runner import VerificationCommandError, VerificationCommandExecutor


@dataclass(frozen=True, slots=True)
class TaskCancellation:
    signal: CancellationSignal | None
    check: Callable[[], None]


@dataclass(frozen=True, slots=True)
class TaskVerificationService:
    default_total_timeout: Callable[[], int]
    default_command_timeout: Callable[[], int]
    dotnet_executable: Callable[[], str]
    state_lock: ContextManager[object]
    save_state: Callable[[RunState], None]
    save_progress: Callable[[RunState], None]
    run_directory: Callable[[str], Path]
    cancellation: Callable[[RunState, WorkTask], TaskCancellation]
    ensure_clean: Callable[[Path], None]
    ensure_head: Callable[[Path, str], None]
    validate_scope: Callable[[WorkTask, RunState], list[str] | None]
    record_progress: Callable[[RunState, WorkTask, CodexSdkProgress], None]
    refresh_style: TaskStyleEvidence
    prepare_command: Callable[[Sequence[str], Path, Callable[[str], None]], Sequence[str]]
    execute_command: VerificationCommandExecutor

    def run(self, state: RunState, task: WorkTask, *, environment_overrides: dict[str, str] | None = None) -> None:
        commands = task.verify_commands
        with self.state_lock:
            task.status = TaskStatus.RUNNING
            state.add_event("verification", f"{task.id} task verification started")
            state.refresh_task_readiness()
            self.save_state(state)

        if not commands:
            with self.state_lock:
                state.add_event("verification", f"{task.id} task verification skipped: no commands")
                self.save_state(state)
            return

        worktree = Path(task.worktree)
        total_timeout = state.task_verify_total_timeout_seconds or self.default_total_timeout()
        command_timeout = state.task_verify_command_timeout_seconds or self.default_command_timeout()
        deadline = time.monotonic() + total_timeout
        cancellation = self.cancellation(state, task)
        cancellation.check()
        self.ensure_clean(worktree)
        log_path = self.run_directory(state.id) / "logs" / f"{task.id}-verify.log"
        action_result = task.action_results[-1]
        action_result.verification_context_inputs = {
            "head": action_result.baseline_commit, "commands": commands, "limits": [command_timeout, total_timeout],
            "environment": hashlib.sha256(json.dumps(environment_overrides, sort_keys=True).encode()).hexdigest(),
            "tool": self.dotnet_executable(),
        }
        total_context = ["task_total", action_result.baseline_commit, commands, command_timeout, total_timeout,
                         environment_overrides, self.dotnet_executable()]
        total_digest = hashlib.sha256(json.dumps(total_context, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

        def report_progress(phase: str, command: Sequence[str], current: int, total: int) -> None:
            detail = "결과와 변경 범위 확인" if phase == "checking_verification_result" else " ".join(command)
            self.record_progress(state, task, CodexSdkProgress(phase, f"{current}/{total} · {detail}"))

        def record_prepared(command: tuple[str, ...], selected: Sequence[str], environment: Mapping[str, str] | None) -> bool:
            context = [action_result.baseline_commit, commands, command, selected, command_timeout, total_timeout, environment]
            digest = hashlib.sha256(json.dumps(context, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
            action_result.verification_context_digest = digest
            action_result.verification_context_inputs.update(command=list(command), selected_command=list(selected))
            action_result.verification_failure_kind = ""
            return any(item is not action_result and item.action == TaskAction.VERIFY.value and item.status == "failed"
                       and item.verification_failure_kind == "timeout" and item.verification_context_digest == digest
                       for item in task.action_results)

        def record_failure(command: tuple[str, ...], kind: str) -> None:
            if kind == "command_failed":
                action_result.verification_failure_kind = "command_failed"
                self.refresh_style(state, task, action_result, failed_command=command)
            else:
                self.refresh_style(state, task, action_result, unavailable_command=command)
            self.save_progress(state)

        def record_passed(command: tuple[str, ...]) -> None:
            self.ensure_head(worktree, action_result.baseline_commit)
            action_result.passed_commands.append(list(command))
            self.refresh_style(state, task, action_result)
            self.save_progress(state)

        def prepare_command(command: tuple[str, ...], cwd: Path, diagnostic: Callable[[str], None]) -> Sequence[str]:
            try:
                return self.prepare_command(command, cwd, diagnostic)
            except GitError as exc:
                raise VerificationCommandError(str(exc)) from exc

        runner = TaskVerificationRunner(
            TaskVerificationRuntimeOptions(
                task.id, worktree, log_path, log_path.with_name(f"{task.id}-verify-{task.last_attempt_id}.log"),
                command_timeout, total_timeout, deadline, tuple((environment_overrides or {}).items()),
            ),
            execute_command=self.execute_command, prepare_command=prepare_command,
            check_stopped=cancellation.check, timestamp=utc_now,
            progress_callback=report_progress, prepared_callback=record_prepared,
            failure_callback=record_failure, passed_callback=record_passed,
        )
        total_timeout_repeated = any(
            item is not action_result and item.action == TaskAction.VERIFY.value and item.status == "failed"
            and item.verification_failure_kind == "timeout" and item.verification_context_digest == total_digest
            for item in task.action_results
        )
        try:
            runner.run(
                tuple(tuple(command) for command in commands),
                cancel_signal=cancellation.signal, total_timeout_repeated=total_timeout_repeated,
            )
        except TaskVerificationTimedOut as exc:
            action_result.verification_failure_kind = "timeout"
            if exc.total:
                action_result.verification_context_digest = total_digest
            self.save_progress(state)
            cause = exc.__cause__
            if isinstance(cause, VerificationCommandError) and cause.__cause__ is not None:
                cause = cause.__cause__
            raise TaskVerificationTimeout(task.id, exc.command, exc.timeout_seconds, repeated=exc.repeated) from cause
        except TaskVerificationFailed as exc:
            raise TaskVerificationFailure(task.id, exc.command, exc.output, exc.log_path) from exc.__cause__
        except VerificationCommandError as exc:
            if exc.__cause__ is not None:
                raise exc.__cause__ from exc.__cause__.__cause__
            raise
        self.validate_scope(task, state)
        self.ensure_clean(worktree)
        with self.state_lock:
            state.add_event("verification", f"{task.id} task verification passed")
            self.save_state(state)
