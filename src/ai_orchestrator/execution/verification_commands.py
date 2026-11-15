"""VerificationCommands with explicit feature and persistence dependencies."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, ContextManager, Mapping, Sequence
from ..config import ExecutionConfig
from ..errors import PipelineError
from ..execution import VerificationCommandError, VerificationRunner
from ..execution_control import CancellationSignal
from ..git import GitError, GitWorkspace, LOCAL_GIT_TIMEOUT_SECONDS, run_command
from ..models import RunState, Stage, TaskStatus, WorkTask
from ..persistence.execution_records import VerificationCommandsRecords
from .. import git as git_runtime


@dataclass
class VerificationCommands:
    records: VerificationCommandsRecords
    read_git: Callable[[], GitWorkspace]
    execution_settings: Callable[[], ExecutionConfig]
    read_dotnet_executable: Callable[[], str]

    @staticmethod
    def verification_resume_stage(state: RunState) -> Stage:
        if all(task.status == TaskStatus.MERGED for task in state.tasks):
            return Stage.MERGED
        return Stage.READY_TO_MERGE


    def ensure_verification_head(self, cwd: Path, expected_head: str) -> None:
        current = self.read_git().head(cwd, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        if current != expected_head:
            raise PipelineError(f"HEAD changed during verification (expected {expected_head}, found {current}); run verification again")


    def preflight_task_environment(self, state: RunState, task: WorkTask) -> None:
        log_path = self.records.run_dir(state.id) / "logs" / f"{task.id}-environment.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        diagnostics: list[str] = []

        def write_diagnostic(value: str) -> None:
            diagnostics.append(value)
            log_path.write_text("\n\n".join(diagnostics), encoding="utf-8")

        commands = [*task.verify_commands, *self.execution_settings().verify_commands]
        checked: set[str] = set()
        for command in commands:
            if VerificationRunner.is_dotnet_command(command) and command[0] not in checked:
                self.prepare_verification_command(command, Path(task.worktree), write_diagnostic)
                checked.add(command[0])


    def prepare_verification_command(
        self, command: list[str] | tuple[str, ...], cwd: Path, write_diagnostic: Callable[[str], None]
    ) -> list[str] | tuple[str, ...]:
        if not VerificationRunner.is_dotnet_command(command):
            return command
        diagnostic = git_runtime.diagnose_dotnet(self.read_dotnet_executable() or command[0], cwd)
        write_diagnostic(diagnostic.log)
        if diagnostic.error:
            raise PipelineError(diagnostic.error)
        return (diagnostic.executable, *command[1:])


    @staticmethod
    def execute_verification_command(
        command: Sequence[str], cwd: Path, *, timeout_seconds: float,
        cancel_signal: CancellationSignal | None, environment_overrides: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        try:
            return run_command(
                command, cwd, check=False, non_interactive=True, timeout_seconds=timeout_seconds,
                cancel_signal=cancel_signal, environment_overrides=environment_overrides,
            )
        except GitError as exc:
            raise VerificationCommandError(str(exc)) from exc
