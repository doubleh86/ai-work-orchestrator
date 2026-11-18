"""Prepare verification repairs without owning Git or final run transitions."""

from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, Sequence

from ..codex_sdk import CodexSdkProgress
from ..config import AgentConfig
from ..errors import PipelineError
from ..execution_control import CancellationSignal, ExecutionStopped
from ..git_contracts import GitError
from ..codex_model_preferences import codex_model_order
from ..models import OperationRecord, RunState, VerificationAttempt, WorkTask
from ..usage import UsageContext


class RepairProviderInvocation(Protocol):
    def __call__(
        self, *, agent: AgentConfig, command_template: tuple[str, ...], replacements: dict[str, str],
        cwd: Path, prompt: str, prompt_path: str, log_path: Path, action: str, task_id: str,
        model: str, reasoning_effort: str, attempt_id: str, usage_context: UsageContext, invocation_id: str,
        cancel_signal: CancellationSignal | None, progress_callback: Callable[[CodexSdkProgress], None],
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class VerificationRepairProposal:
    task: WorkTask
    attempt: VerificationAttempt | None


@dataclass(frozen=True, slots=True)
class VerificationRepairRunner:
    available: Callable[[AgentConfig], bool]
    run_directory: Callable[[str], Path]
    save_state: Callable[[RunState], None]
    stop_signal: Callable[[RunState], CancellationSignal | None]
    check_stopped: Callable[[CancellationSignal | None], None]
    command: Callable[[AgentConfig, str], tuple[str, ...]]
    invoke: RepairProviderInvocation

    def select_agent(self, agents: Sequence[AgentConfig], planning_agent_id: str) -> AgentConfig:
        available = [agent for agent in agents if self.available(agent)]
        agent = next((item for item in available if item.id == planning_agent_id), None)
        agent = agent or next((item for item in available if "general" in item.capabilities), None)
        agent = agent or (available[0] if available else None)
        if agent is None:
            raise PipelineError("검증 실패를 수정할 수 있는 실행 Agent가 없습니다.")
        return agent

    def propose(
        self, state: RunState, agent: AgentConfig, worktree: Path, before: str, error: Exception, repair_index: int,
    ) -> VerificationRepairProposal:
        expected_paths = sorted({path for task in state.tasks for path in task.expected_paths})
        forbidden_paths = sorted({path for task in state.tasks for path in task.forbidden_paths})
        attempt = state.verification_attempts[-1] if state.verification_attempts else None
        log_excerpt = ""
        if attempt and attempt.log_path and Path(attempt.log_path).is_file():
            log_excerpt = Path(attempt.log_path).read_text(encoding="utf-8", errors="replace")[-16000:]
        scope_lines = "\n".join(f"- {path}" for path in expected_paths) or "- Existing project source and test files needed for this failure"
        prompt = f"""# Verification failure repair

Run: {state.id}
Repair attempt: {repair_index}/{state.verification_repair_limit}
Candidate commit: {before}
Failure: {error}

Allowed paths from the completed Tasks:
{scope_lines}

Inspect the failed command output and make the smallest source or test correction that preserves the documented behavior.
Do not disable, skip, weaken, or delete tests. Do not change verification commands or configuration to hide the failure.
Do not run git add, git commit, git reset, git clean, merge, rebase, or change refs. Preserve all existing completed work.
Run the failed related check when useful; the orchestrator will run the official full verification again.

Verification log tail:
```text
{log_excerpt}
```
"""
        prompt_path = self.run_directory(state.id) / "prompts" / f"verification-repair-{repair_index}.md"
        log_path = self.run_directory(state.id) / "logs" / f"verification-repair-{repair_index}.log"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt, encoding="utf-8")
        cancel_signal = self.stop_signal(state)
        state.update_verification_progress(
            "repairing",
            f"검증 실패 수정 중 · {repair_index}/{state.verification_repair_limit}",
            current=repair_index,
            total=state.verification_repair_limit,
        )
        self.save_state(state)

        def report(progress: CodexSdkProgress) -> None:
            state.update_verification_progress(
                "repairing",
                f"{repair_index}/{state.verification_repair_limit} · {progress.detail or progress.phase}",
                current=repair_index,
                total=state.verification_repair_limit,
            )
            self.save_state(state)

        repair_model = codex_model_order()[0] if agent.provider_id == "codex" else agent.model
        command_template = self.command(agent, repair_model)
        self.invoke(
            agent=agent,
            command_template=command_template,
            replacements={
                "{worktree}": str(worktree),
                "{prompt}": str(prompt_path),
                "{task_id}": "verification-repair",
                "{run_id}": state.id,
            },
            cwd=worktree,
            prompt=prompt,
            prompt_path=str(prompt_path),
            log_path=log_path,
            action="execute",
            task_id="verification-repair",
            model=repair_model,
            reasoning_effort="",
            attempt_id=f"verification-repair-{repair_index}",
            usage_context=UsageContext(state.id, "verification_repair"),
            invocation_id=str(uuid.uuid4()),
            cancel_signal=cancel_signal,
            progress_callback=report,
        )
        self.check_stopped(cancel_signal)
        scope_task = WorkTask(
            id="verification-repair",
            title="검증 실패 수정",
            capabilities=["general"],
            worktree=str(worktree),
            started_commit=before,
            expected_paths=expected_paths,
            forbidden_paths=forbidden_paths,
        )
        return VerificationRepairProposal(scope_task, attempt)


@dataclass(frozen=True, slots=True)
class VerificationRepairRecords:
    load_run: Callable[[str], RunState]
    claim: Callable[[OperationRecord], tuple[OperationRecord, bool]]
    save_state: Callable[[RunState], None]
    save_operation: Callable[[OperationRecord], None]


@dataclass(frozen=True, slots=True)
class VerificationRepairWorkflow:
    records: VerificationRepairRecords
    default_limit: Callable[[], int]
    record_chat: Callable[[str, str, str], RunState]
    ensure_policy: Callable[[RunState], None]
    verify: Callable[[str], RunState]
    failure_is_repairable: Callable[[Exception], bool]
    repair: Callable[[RunState, Exception, int], None]
    finish: Callable[[str, RunState], RunState]
    interrupt_repair: Callable[[str, ExecutionStopped], RunState]

    def run(
        self, run_id: str, normalized_request_id: str, chat_message: str, *, max_repairs: int | None = None,
    ) -> RunState:
        initial = self.records.load_run(run_id)
        digest = hashlib.sha256(
            json.dumps(
                {
                    "run_id": run_id,
                    "base_commit": initial.base_commit,
                    "repair_limit": initial.verification_repair_limit or self.default_limit(),
                    **({"chat_message": chat_message} if chat_message else {}),
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        operation = OperationRecord(
            request_id=normalized_request_id,
            run_id=run_id,
            action="verify_and_repair",
            digest=digest,
            phase="verifying",
            scope="verification",
        )
        existing, created = self.records.claim(operation)
        if not created:
            if existing.action != operation.action or existing.digest != digest:
                raise PipelineError("requestId가 다른 검증·자동 수정 요청에 사용되었습니다.")
            return self.records.load_run(run_id)
        state = self.record_chat(run_id, chat_message, "최종 검증과 자동 수정을 시작합니다.") if chat_message else initial
        self.ensure_policy(state)
        repair_limit = min(state.verification_repair_limit, max_repairs) if max_repairs is not None else state.verification_repair_limit
        state.verification_repair_count = 0
        self.records.save_state(state)
        while True:
            try:
                operation.update("verifying")
                self.records.save_operation(operation)
                verified = self.verify(run_id)
                operation.result_commit = verified.verified_integration_head
                operation.update("verified", status="succeeded")
                self.records.save_operation(operation)
                return self.finish(run_id, verified)
            except ExecutionStopped as exc:
                operation.update("interrupted", status="interrupted", error=str(exc), error_code="user_stopped")
                self.records.save_operation(operation)
                return self.records.load_run(run_id)
            except (GitError, PipelineError, OSError, subprocess.SubprocessError) as exc:
                state = self.records.load_run(run_id)
                if not self.failure_is_repairable(exc):
                    operation.update("failed", status="failed", error=str(exc), error_code="verification_not_repairable")
                    self.records.save_operation(operation)
                    raise
                if state.verification_repair_count >= repair_limit:
                    operation.update("repair_limit_reached", status="failed", error=str(exc), error_code="repair_limit_reached")
                    self.records.save_operation(operation)
                    raise PipelineError(
                        f"검증 자동 수정 한도 {repair_limit}회에 도달했습니다. 마지막 오류: {exc}"
                    ) from exc
                repair_index = state.verification_repair_count + 1
                operation.update("repairing")
                self.records.save_operation(operation)
                try:
                    self.repair(state, exc, repair_index)
                except ExecutionStopped as stop_error:
                    state = self.interrupt_repair(run_id, stop_error)
                    operation.update(
                        "interrupted",
                        status="interrupted",
                        error=str(stop_error),
                        error_code="user_stopped",
                    )
                    self.records.save_operation(operation)
                    return state
                except (GitError, PipelineError, OSError, subprocess.SubprocessError) as repair_error:
                    operation.update(
                        "repair_failed",
                        status="failed",
                        error=str(repair_error),
                        error_code="repair_failed",
                    )
                    self.records.save_operation(operation)
                    raise
                state.verification_repair_count = repair_index
                if state.verification_attempts:
                    state.verification_attempts[-1].repair_count = repair_index
                state.add_event("verification", f"verification repair {repair_index}/{state.verification_repair_limit} completed")
                self.records.save_state(state)
