"""Own Run step state and verification receipts within caller scopes."""

from __future__ import annotations

import os
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, ContextManager, Iterator

from ..errors import PipelineError, VerificationInputsChanged
from ..execution_control import ExecutionStopped
from ..git import GitError
from ..models import ConflictResolutionStatus, ExecutionControlRecord, RunState, RunStep, Stage, VerificationAttempt, utc_now
from .lifecycle import StoredStopSignal


@dataclass(frozen=True, slots=True)
class RunStepRecords:
    control_lock: Callable[[str], ContextManager[object]]
    load_control: Callable[[str], ExecutionControlRecord | None]
    save_control: Callable[[ExecutionControlRecord], None]
    save_state: Callable[[RunState], None]


@dataclass(frozen=True, slots=True)
class RunStepLifecycle:
    records: RunStepRecords
    command_timeout: Callable[[], int]
    total_timeout: Callable[[], int]
    stop_signal: Callable[[RunState], StoredStopSignal | None]
    record_checkpoint: Callable[[RunState, str], None]
    confirm_stopped: Callable[[str, str], None]
    record_group_result: Callable[[RunState], None]

    @contextmanager
    def step(self, state: RunState, step: RunStep) -> Iterator[None]:
        attempt = None
        if step == RunStep.VERIFY:
            if state.verification_attempts and state.verification_attempts[-1].status == "running":
                previous = state.verification_attempts[-1]
                previous.status = "interrupted"
                previous.finished_at = utc_now()
                previous.error = "previous verification did not finish; retry started"
            attempt = VerificationAttempt(
                command_timeout_seconds=(
                    state.integration_verify_command_timeout_seconds
                    or self.command_timeout()
                ),
                total_timeout_seconds=(
                    state.integration_verify_total_timeout_seconds
                    or self.total_timeout()
                ),
            )
            state.verification_attempts.append(attempt)
            if (
                state.integration_conflict is not None
                and state.integration_conflict.resolution_status == ConflictResolutionStatus.APPLIED
            ):
                state.link_recovery_verification(state.integration_conflict.id, attempt.id)
            with self.records.control_lock(state.id):
                control = self.records.load_control(state.id)
                if control is not None and control.owner_pid == os.getpid() and control.phase == "running":
                    control.scope = "verification"
                    control.attempt_id = attempt.id
                    control.invocation_id = attempt.id
                    self.records.save_control(control)
        state.begin_step(step)
        self.records.save_state(state)
        try:
            yield
        except ExecutionStopped as exc:
            if attempt is not None:
                attempt.status = "interrupted"
                attempt.finished_at = utc_now()
                attempt.stop_reason = "user_requested"
                attempt.error = "사용자가 검증을 중지했습니다."
            state.active_step = None
            state.failed_step = None
            state.failure_message = ""
            state.update_verification_progress("stopped", "사용자가 검증을 중지했습니다.", current=state.verification_progress_current)
            state.add_event("verification", "integration verification stopped by user")
            self.records.save_state(state)
            request_id = exc.request_id
            if not request_id:
                signal = self.stop_signal(state)
                if signal is not None and signal.is_set():
                    request_id = signal.request_id
            if request_id:
                self.record_checkpoint(state, request_id)
                self.confirm_stopped(state.id, request_id)
            raise ExecutionStopped(str(exc), request_id=request_id) from exc
        except VerificationInputsChanged as exc:
            if attempt is not None:
                attempt.status = "stale"
                attempt.finished_at = utc_now()
                attempt.error = str(exc)
            state.active_step = None
            state.failed_step = None
            state.failure_message = ""
            state.verified_task_heads = {}
            state.verified_main_head = ""
            state.verified_integration_head = ""
            state.pushed_work_branch_head = ""
            state.update_verification_progress("stale", str(exc), current=state.verification_progress_current)
            state.transition(Stage.READY_TO_MERGE, "integration verification inputs changed; verification required")
            self.records.save_state(state)
            raise
        except (GitError, PipelineError, OSError, subprocess.SubprocessError) as exc:
            if attempt is not None:
                attempt.status = "failed"
                attempt.finished_at = utc_now()
                attempt.error = str(exc)
            if state.failed_step != step or not state.failure_message:
                state.fail_step(step, f"{step.value} failed: {exc}")
            self.records.save_state(state)
            raise
        else:
            if attempt is not None:
                attempt.status = "failed" if state.stage == Stage.FAILED else "succeeded"
                attempt.finished_at = utc_now()
                attempt.error = state.failure_message if state.stage == Stage.FAILED else ""
            if state.stage != Stage.FAILED:
                state.complete_step(step)
            if (
                step == RunStep.VERIFY and attempt is not None and attempt.status == "succeeded"
                and state.verified_main_head and state.verified_integration_head
            ):
                self.record_group_result(state)
            self.records.save_state(state)
