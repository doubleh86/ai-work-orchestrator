from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

from ..execution_control import CancellationSignal


DOTNET_BUILD_OUTPUT_ACCESS_ERROR = (
    ".NET 빌드 산출물 쓰기 접근이 거부되었습니다. 빌드 프로세스의 권한과 산출물 접근 상태를 확인한 뒤 "
    "같은 검증을 다시 실행하세요. 이 오류에는 코드 자동 수정을 진행하지 않습니다."
)
INTEGRATION_VERIFICATION_COMMAND_TIMEOUT_SECONDS = 600


@dataclass(frozen=True, slots=True)
class VerificationRuntimeOptions:
    cwd: Path
    log_path: Path
    total_timeout_seconds: int
    command_timeout_seconds: int
    git_timeout_seconds: float
    elapsed_preparation_seconds: float = 0.0


class VerificationCommandError(RuntimeError):
    """Command adapter failure, retaining its original cause."""


class VerificationRunError(RuntimeError):
    """Verification failure with evidence for the workflow owner."""

    def __init__(self, message: str, *, command: tuple[str, ...] = (), phase: str = "", command_failed: bool = False) -> None:
        super().__init__(message)
        self.command = command
        self.phase = phase
        self.command_failed = command_failed


class VerificationCommandExecutor(Protocol):
    def __call__(
        self, command: Sequence[str], cwd: Path, *, timeout_seconds: float,
        cancel_signal: CancellationSignal | None, environment_overrides: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]: ...


class VerificationRunner:
    """Run commands and collect evidence without owning workflow state."""

    def __init__(
        self, options: VerificationRuntimeOptions, *, execute_command: VerificationCommandExecutor,
        prepare_command: Callable[[tuple[str, ...], Path, Callable[[str], None]], Sequence[str]],
        check_stopped: Callable[[], None], ensure_head: Callable[[], None] | None,
        progress_callback: Callable[[str, tuple[str, ...], int, int], None],
        passed_callback: Callable[[tuple[str, ...]], None],
    ) -> None:
        self.options = options
        self._execute_command = execute_command
        self._prepare_command = prepare_command
        self._check_stopped = check_stopped
        self._ensure_head = ensure_head
        self._progress_callback = progress_callback
        self._passed_callback = passed_callback

    def run(self, commands: tuple[tuple[str, ...], ...], *, cancel_signal: CancellationSignal | None = None) -> None:
        options = self.options
        output: list[str] = []
        deadline = time.monotonic() + max(0.0, options.total_timeout_seconds - options.elapsed_preparation_seconds)
        self._check_stopped()

        def write_log() -> None:
            content = "\n".join(output)
            options.log_path.write_text(content, encoding="utf-8")
            if options.log_path.name != "verify.log":
                options.log_path.with_name("verify.log").write_text(content, encoding="utf-8")

        def remaining_timeout() -> float:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise VerificationRunError(f"통합 검증 전체 제한시간을 초과했습니다: {options.total_timeout_seconds}초")
            return min(float(options.command_timeout_seconds), remaining)

        def write_diagnostic(message: str) -> None:
            output.append(message)
            write_log()

        for command in self.npm_dependency_restore_commands(options.cwd, commands):
            self._check_stopped()
            rendered = " ".join(command)
            self._progress_callback("preparing_dependencies", command, 0, len(commands))
            try:
                result = self._execute_command(
                    command, options.cwd, timeout_seconds=remaining_timeout(), cancel_signal=cancel_signal,
                )
                self._check_stopped()
            except VerificationCommandError as exc:
                output.append(f"$ {rendered}\n{exc}")
                write_log()
                if "timed out after" in str(exc):
                    message = f"통합 검증 의존성 복원이 제한시간을 초과했습니다: {rendered} ({options.command_timeout_seconds}초)"
                else:
                    message = f"통합 검증 의존성을 복원하지 못했습니다: {rendered}: {exc}"
                raise VerificationRunError(message, command=command, phase="dependency_restore") from exc
            output.append(f"$ {rendered}\n{result.stdout}")
            write_log()
            if result.returncode != 0:
                raise VerificationRunError(f"통합 검증 의존성 복원에 실패했습니다: {rendered}", command=command, phase="dependency_restore")
            if self._ensure_head is not None:
                self._ensure_head()
        for index, command in enumerate(commands, start=1):
            self._check_stopped()
            rendered = " ".join(command)
            self._progress_callback("running_command", command, index, len(commands))
            timeout_seconds = min(self.command_timeout(command, options.git_timeout_seconds), remaining_timeout())
            try:
                selected_command = self._prepare_command(command, options.cwd, write_diagnostic)
                environment = None
                if self.is_dotnet_command(command) and len(command) > 1 and command[1].casefold() in {"restore", "build", "test"}:
                    environment = {
                        "DOTNET_CLI_USE_MSBUILD_SERVER": "0", "MSBUILDUSESERVER": "0", "MSBUILDDISABLENODEREUSE": "1",
                    }
                    write_diagnostic("통합 .NET 검증: 이번 명령에서 MSBuild 서버·노드를 재사용하지 않습니다.")
                result = self._execute_command(
                    selected_command, options.cwd, timeout_seconds=timeout_seconds, cancel_signal=cancel_signal,
                    environment_overrides=environment,
                )
                self._check_stopped()
            except VerificationCommandError as exc:
                output.append(f"$ {rendered}\n{exc}")
                write_log()
                if "timed out after" in str(exc):
                    message = f"통합 검증 명령이 제한시간을 초과했습니다: {rendered} ({timeout_seconds}초)"
                else:
                    message = f"통합 검증 명령을 실행하지 못했습니다: {rendered}: {exc}"
                raise VerificationRunError(message, command=command, phase="command_execution") from exc
            command_output = result.stdout or ""
            if result.stderr:
                command_output += f"\n{result.stderr}"
            output.append(f"$ {rendered}\n{command_output}")
            write_log()
            if result.returncode != 0:
                if self.build_output_access_denied(command, command_output):
                    raise VerificationRunError(
                        f"{DOTNET_BUILD_OUTPUT_ACCESS_ERROR} 명령: {rendered}", command=command, phase="command_environment",
                    )
                if self.output_file_locked(command, command_output):
                    raise VerificationRunError(
                        "실행 중인 앱이 빌드 출력 파일을 사용하고 있어 검증을 완료하지 못했습니다. "
                        "해당 앱/서버를 종료한 뒤 최종 검증을 다시 실행하세요. 이 실패에는 코드 자동 수정을 진행하지 않습니다.",
                        command=command, phase="file_lock",
                    )
                raise VerificationRunError(
                    f"통합 검증 명령이 실패했습니다: {rendered}", command=command, phase="verification_command", command_failed=True,
                )
            if self._ensure_head is not None:
                self._ensure_head()
            self._passed_callback(command)
        write_log()

    @staticmethod
    def command_timeout(command: tuple[str, ...], git_timeout_seconds: float) -> float:
        executable = Path(command[0]).name.casefold() if command else ""
        return git_timeout_seconds if executable in {"git", "git.exe"} else INTEGRATION_VERIFICATION_COMMAND_TIMEOUT_SECONDS

    @staticmethod
    def npm_verification_command(cwd: Path, command: tuple[str, ...]) -> tuple[Path, str, str] | None:
        if not command:
            return None
        executable = Path(command[0]).name.casefold()
        if executable not in {"npm", "npm.cmd", "npm.exe"}:
            return None
        prefix = ""
        action = ""
        for index, argument in enumerate(command[1:], start=1):
            normalized = argument.casefold()
            if normalized == "--prefix" and index + 1 < len(command):
                prefix = command[index + 1]
                continue
            if normalized.startswith("--prefix="):
                prefix = argument.split("=", maxsplit=1)[1]
                continue
            if not action and normalized in {"ci", "install", "run", "run-script"}:
                action = normalized
        if not action:
            return None
        package_dir = Path(prefix) if prefix else Path()
        if not package_dir.is_absolute():
            package_dir = cwd / package_dir
        resolved_cwd = cwd.resolve()
        resolved_package_dir = package_dir.resolve()
        try:
            resolved_package_dir.relative_to(resolved_cwd)
        except ValueError:
            return None
        return resolved_package_dir, prefix, action

    @classmethod
    def npm_dependency_restore_commands(cls, cwd: Path, commands: tuple[tuple[str, ...], ...]) -> tuple[tuple[str, ...], ...]:
        parsed_commands = [(command, parsed) for command in commands if (parsed := cls.npm_verification_command(cwd, command)) is not None]
        explicitly_restored = {parsed[0] for _, parsed in parsed_commands if parsed[2] in {"ci", "install"}}
        restore_commands: list[tuple[str, ...]] = []
        selected_packages: set[Path] = set()
        for command, parsed in parsed_commands:
            package_dir, prefix, action = parsed
            if action not in {"run", "run-script"}:
                continue
            if package_dir in explicitly_restored or package_dir in selected_packages:
                continue
            if (package_dir / "node_modules").is_dir():
                continue
            if not (package_dir / "package-lock.json").is_file():
                continue
            restore_command = [command[0]]
            if prefix:
                restore_command.extend(("--prefix", prefix))
            restore_command.append("ci")
            restore_commands.append(tuple(restore_command))
            selected_packages.add(package_dir)
        return tuple(restore_commands)

    @staticmethod
    def is_dotnet_command(command: Sequence[str]) -> bool:
        return bool(command) and Path(command[0]).name.casefold() in {"dotnet", "dotnet.exe"}

    @classmethod
    def output_file_locked(cls, command: tuple[str, ...], output: str) -> bool:
        if not cls.is_dotnet_command(command):
            return False
        for line in output.splitlines():
            if not re.search(r"\b(?:error|오류)\s+MSB302[17]\b", line, re.IGNORECASE):
                continue
            lowered = line.casefold()
            if "used by another process" in lowered or "file is locked by" in lowered:
                return True
            if re.search(r"다른\s*프로세스.{0,100}사용\s*중|파일.{0,100}잠겨", line):
                return True
        return False

    @classmethod
    def build_output_access_denied(cls, command: Sequence[str], output: str) -> bool:
        if not cls.is_dotnet_command(command):
            return False
        for line in output.splitlines():
            if not re.search(r"\b(?:error|warning|오류|경고)\s+MSB(?:4018|3101)\b", line, re.IGNORECASE):
                continue
            if not re.search(r"(?:^|[\s'\"/\\])(?:obj|bin)[/\\]", line, re.IGNORECASE):
                continue
            if re.search(
                r"UnauthorizedAccessException|access is denied|access to the path.+is denied|permission denied|액세스.{0,100}거부",
                line, re.IGNORECASE,
            ):
                return True
        return False
