from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal, Mapping, Sequence

from ..execution_control import CancellationSignal
from .verification_runner import VerificationCommandError, VerificationCommandExecutor, VerificationRunner


@dataclass(frozen=True, slots=True)
class TaskVerificationRuntimeOptions:
    task_id: str
    cwd: Path
    log_path: Path
    attempt_log_path: Path
    command_timeout_seconds: int
    total_timeout_seconds: int
    deadline: float
    environment_overrides: tuple[tuple[str, str], ...] = ()


class TaskVerificationFailed(RuntimeError):
    def __init__(self, task_id: str, command: Sequence[str], output: str, log_path: Path) -> None:
        super().__init__(f"task verification command failed for {task_id}: {' '.join(command)}")
        self.command = tuple(command)
        self.output = output
        self.log_path = log_path


class TaskVerificationTimedOut(RuntimeError):
    def __init__(
        self, task_id: str, command: Sequence[str], timeout_seconds: float, *, repeated: bool = False, total: bool = False,
    ) -> None:
        reason = ("같은 검증 조건에서 시간 초과가 반복됐습니다. 지연되는 테스트를 확인하기 전에는 다시 실행하지 않습니다."
                  if repeated else "테스트의 최종 결과를 확인하지 못했습니다.")
        super().__init__(f"Task 검증 시간 초과 · 완료 여부 미확인: {task_id} · {' '.join(command)} ({timeout_seconds:g}초). {reason}")
        self.command = tuple(command)
        self.timeout_seconds = timeout_seconds
        self.repeated = repeated
        self.total = total


class TaskVerificationRunner:
    """Collect task verification evidence; the caller owns state and recovery."""

    def __init__(
        self, options: TaskVerificationRuntimeOptions, *, execute_command: VerificationCommandExecutor,
        prepare_command: Callable[[tuple[str, ...], Path, Callable[[str], None]], Sequence[str]],
        check_stopped: Callable[[], None], timestamp: Callable[[], str],
        progress_callback: Callable[[str, Sequence[str], int, int], None],
        prepared_callback: Callable[[tuple[str, ...], Sequence[str], Mapping[str, str] | None], bool],
        failure_callback: Callable[[tuple[str, ...], Literal["unavailable", "command_failed"]], None],
        passed_callback: Callable[[tuple[str, ...]], None],
    ) -> None:
        self.options = options
        self._execute_command = execute_command
        self._prepare_command = prepare_command
        self._check_stopped = check_stopped
        self._timestamp = timestamp
        self._progress_callback = progress_callback
        self._prepared_callback = prepared_callback
        self._failure_callback = failure_callback
        self._passed_callback = passed_callback

    def run(
        self, commands: tuple[tuple[str, ...], ...], *, cancel_signal: CancellationSignal | None = None,
        total_timeout_repeated: bool = False,
    ) -> None:
        options = self.options
        environment = dict(options.environment_overrides) if options.environment_overrides else None
        output: list[str] = []
        if environment:
            output.append("[자동 복구: .NET 검증 자식 프로세스 환경]\n" + json.dumps(environment, ensure_ascii=False, sort_keys=True))

        def write_log() -> None:
            options.log_path.write_text("\n".join(output), encoding="utf-8")

        def write_diagnostic(message: str) -> None:
            output.append(message)
            write_log()

        def timeout_error(seconds: float, command: Sequence[str], *, repeated: bool = False, total: bool = False) -> TaskVerificationTimedOut:
            error = TaskVerificationTimedOut(options.task_id, command, seconds, repeated=repeated, total=total)
            write_diagnostic(str(error))
            options.attempt_log_path.write_text("\n".join(output), encoding="utf-8")
            return error

        if total_timeout_repeated:
            raise timeout_error(options.total_timeout_seconds, commands[0], repeated=True, total=True)
        for index, command in enumerate(commands, start=1):
            self._check_stopped()
            remaining = options.deadline - time.monotonic()
            if remaining <= 0:
                raise timeout_error(options.total_timeout_seconds, command, total=True)
            self._progress_callback("preparing_verification", command, index, len(commands))
            output.append(f"[{self._timestamp()}] $ {' '.join(command)}")
            write_log()
            try:
                selected_command = self._prepare_command(command, options.cwd, write_diagnostic)
                command_environment = environment if VerificationRunner.is_dotnet_command(command) else None
                if self._prepared_callback(command, selected_command, command_environment):
                    raise timeout_error(options.command_timeout_seconds, command, repeated=True)
                remaining = options.deadline - time.monotonic()
                if remaining <= 0:
                    raise timeout_error(options.total_timeout_seconds, command, total=True)
                self._progress_callback("verifying_command", selected_command, index, len(commands))
                result = self._execute_command(
                    selected_command, options.cwd, timeout_seconds=min(float(options.command_timeout_seconds), remaining),
                    cancel_signal=cancel_signal, environment_overrides=command_environment,
                )
                self._check_stopped()
            except (VerificationCommandError, OSError) as exc:
                output[-1] += f"\n{exc}"
                write_log()
                self._failure_callback(command, "unavailable")
                if isinstance(exc, VerificationCommandError) and str(exc).startswith("command timed out after "):
                    raise timeout_error(min(float(options.command_timeout_seconds), remaining), command) from exc
                raise
            output[-1] += f"\n{result.stdout}\n[{self._timestamp()}] exit code: {result.returncode}"
            write_log()
            if result.returncode != 0:
                self._failure_callback(command, "command_failed")
                options.attempt_log_path.write_text("\n".join(output), encoding="utf-8")
                raise TaskVerificationFailed(options.task_id, command, result.stdout, options.attempt_log_path)
            if time.monotonic() > options.deadline:
                raise timeout_error(options.total_timeout_seconds, command, total=True)
            self._progress_callback("checking_verification_result", command, index, len(commands))
            self._passed_callback(command)
