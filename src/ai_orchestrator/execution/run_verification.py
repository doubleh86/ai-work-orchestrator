"""Run verification commands and persist evidence through owner ports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Generic, Protocol, Sequence, TypeVar

from ..errors import PipelineError
from ..execution_control import CancellationSignal
from ..git import LOCAL_GIT_TIMEOUT_SECONDS
from ..models import RunState, WorkTask
from .verification_runner import (
    VerificationCommandError, VerificationCommandExecutor, VerificationRunError, VerificationRunner, VerificationRuntimeOptions,
)

StopSignal = TypeVar("StopSignal", bound=CancellationSignal)


class VerificationFailureRecorder(Protocol):
    def __call__(self, state: RunState, command: tuple[str, ...], phase: str, *, command_failed: bool) -> None: ...


@dataclass(frozen=True, slots=True)
class RunVerificationRecords:
    run_directory: Callable[[str], Path]
    save_state: Callable[[RunState], None]


@dataclass(frozen=True, slots=True)
class RunVerificationCommands(Generic[StopSignal]):
    records: RunVerificationRecords
    total_timeout: Callable[[], int]
    command_timeout: Callable[[], int]
    stop_signal: Callable[[RunState], StopSignal | None]
    prepare_command: Callable[[tuple[str, ...], Path, Callable[[str], None]], Sequence[str]]
    execute_command: VerificationCommandExecutor
    raise_if_stopped: Callable[[StopSignal | None], None]
    ensure_head: Callable[[Path, str], None]
    record_failure: VerificationFailureRecorder

    def run(self, state: RunState, cwd: Path, commands: tuple[tuple[str, ...], ...], *, expected_head: str = "") -> None:
        log_dir = self.records.run_directory(state.id) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        attempt = state.verification_attempts[-1] if state.verification_attempts else None
        log_path = log_dir / "verify.log"
        if attempt is not None:
            log_path = log_dir / f"verify-attempt-{len(state.verification_attempts)}.log"
            attempt.log_path = str(log_path)
            self.records.save_state(state)
        elapsed_preparation = 0.0
        if state.verification_started_at:
            try:
                elapsed_preparation = max(
                    0.0,
                    (datetime.now(timezone.utc) - datetime.fromisoformat(state.verification_started_at)).total_seconds(),
                )
            except ValueError:
                elapsed_preparation = 0.0
        options = VerificationRuntimeOptions(
            cwd=cwd, log_path=log_path,
            total_timeout_seconds=(state.integration_verify_total_timeout_seconds
                                   or self.total_timeout()),
            command_timeout_seconds=(state.integration_verify_command_timeout_seconds
                                     or self.command_timeout()),
            git_timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS, elapsed_preparation_seconds=elapsed_preparation,
        )
        cancel_signal = self.stop_signal(state)

        def prepare_command(command: tuple[str, ...], cwd: Path, write_diagnostic: Callable[[str], None]) -> Sequence[str]:
            try:
                return self.prepare_command(command, cwd, write_diagnostic)
            except PipelineError:
                self.record_failure(state, command, "command_environment", command_failed=False)
                raise

        def report_progress(phase: str, command: tuple[str, ...], current: int, total: int) -> None:
            if attempt is not None:
                attempt.current_command = list(command)
            state.update_verification_progress(phase, " ".join(command), current=current, total=total)
            self.records.save_state(state)

        def record_passed(command: tuple[str, ...]) -> None:
            if attempt is not None:
                attempt.passed_commands.append(list(command))
                self.records.save_state(state)

        runner = VerificationRunner(
            options, execute_command=self.execute_command, prepare_command=prepare_command,
            check_stopped=lambda: self.raise_if_stopped(cancel_signal),
            ensure_head=(lambda: self.ensure_head(cwd, expected_head)) if expected_head else None,
            progress_callback=report_progress, passed_callback=record_passed,
        )
        try:
            runner.run(commands, cancel_signal=cancel_signal)
        except VerificationRunError as exc:
            if exc.phase:
                self.record_failure(state, exc.command, exc.phase, command_failed=exc.command_failed)
            cause = exc.__cause__
            if isinstance(cause, VerificationCommandError) and cause.__cause__ is not None:
                cause = cause.__cause__
            raise PipelineError(str(exc)) from cause


def is_orchestrator_managed_verification_command(command: tuple[str, ...]) -> bool:
    if not command:
        return False
    executable = Path(command[0]).name.casefold()
    return executable in {"git", "git.exe"} and any(argument.casefold() == "worktree" for argument in command[1:])


def integration_verification_command_selection(
    state: RunState, configured_commands: tuple[tuple[str, ...], ...], *,
    managed_command: Callable[[tuple[str, ...]], bool],
) -> tuple[tuple[tuple[str, ...], ...], tuple[tuple[str, ...], ...]]:
    if configured_commands:
        candidates = configured_commands
    else:
        unique_commands: list[tuple[str, ...]] = []
        seen: set[tuple[str, ...]] = set()
        for task in state.tasks:
            for command in task.verify_commands:
                selected = tuple(command)
                if selected in seen:
                    continue
                seen.add(selected)
                unique_commands.append(selected)
        candidates = tuple(unique_commands)
    commands: list[tuple[str, ...]] = []
    excluded: list[tuple[str, ...]] = []
    for command in candidates:
        if managed_command(command):
            excluded.append(command)
        else:
            commands.append(command)
    return tuple(commands), tuple(excluded)


@dataclass(frozen=True, slots=True)
class VerificationFailureEvidence:
    has_project_commands: Callable[[], bool]
    commit_queue_tasks: Callable[[RunState], list[WorkTask]]
    save_state: Callable[[RunState], None]

    def record(self, state: RunState, command: tuple[str, ...], phase: str, *, command_failed: bool) -> None:
        if not state.verification_attempts:
            return
        attempt = state.verification_attempts[-1]
        attempt.failure_phase = phase
        attempt.failed_command = list(command)
        attempt.candidate_task_ids = []
        if not command_failed:
            attempt.attribution_reason = (
                "다른 프로세스의 빌드 파일 잠금으로 실패해 특정 Task의 소스 오류로 귀속하지 않았습니다."
                if phase == "file_lock" else "명령 실행 환경 또는 의존성 준비가 실패해 특정 Task 원인으로 귀속하지 않았습니다."
            )
            self.save_state(state)
            return
        queue_tasks = self.commit_queue_tasks(state)
        if self.has_project_commands():
            attempt.candidate_task_ids = [task.id for task in queue_tasks]
            attempt.attribution_reason = "프로젝트 공통 검증 명령이 실패해 Commit Queue 전체를 관련 후보로 기록했습니다."
        else:
            owners = [task.id for task in queue_tasks if list(command) in task.verify_commands]
            attempt.candidate_task_ids = owners or [task.id for task in queue_tasks]
            if len(owners) == 1:
                attempt.attribution_reason = (
                    f"검증 명령을 선언한 Task는 {owners[0]} 하나지만 통합 결과의 단일 원인으로 확정하지 않았습니다."
                )
            elif owners:
                attempt.attribution_reason = "여러 Task가 같은 검증 명령을 선언해 해당 Task들을 관련 후보로 기록했습니다."
            else:
                attempt.attribution_reason = "검증 명령 출처를 단일 Task로 연결할 수 없어 Commit Queue 전체를 관련 후보로 기록했습니다."
        self.save_state(state)
