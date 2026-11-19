"""Provider invocation and owned process lifecycle, without Pipeline state."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol

from ..claude_credentials import claude_environment, redact_claude_output
from ..codex_sdk import CodexSdkError, CodexSdkExecutionProfile, CodexSdkManager, CodexSdkProgress, CodexSdkTimeout, CodexSdkTurnRequest
from ..config import AgentConfig
from ..execution_control import CancellationSignal, ExecutionStopped
from ..nvidia_agent import (
    NVIDIA_SETUP, NvidiaAgentError, NvidiaCompletionError, nvidia_environment, nvidia_key_configured, parse_nvidia_output, redact_nvidia_output,
)
from ..process_environment import runtime_environment
from ..provider_executable import resolve_provider_executable
from ..usage import UsageObservation
from ..windows_paths import process_working_directory
from ..worker_mcp import WorkerMcpServer, configure_claude_mcp, redact_mcp_output, secret_values
from .provider_commands import configure_claude_tools

CODEX_INPUT_LIMIT_CHARACTERS = 1_048_576
AGENT_TERMINATION_TIMEOUT_SECONDS = 10
AGENT_OUTPUT_DRAIN_TIMEOUT_SECONDS = 5


class ProviderRunError(RuntimeError):
    pass


class ProviderInputLimitError(ProviderRunError):
    pass


class ProviderTimedOut(ProviderRunError):
    pass


class ProviderRequestLimited(ProviderRunError):
    pass


class ProviderUnavailable(ProviderRunError):
    pass


class ProviderStopSignal(CancellationSignal, Protocol):
    request_id: str


@dataclass(frozen=True, slots=True)
class ProviderRuntimeOptions:
    repo: Path
    agent_timeout_seconds: float
    mcp_servers: tuple[WorkerMcpServer, ...] = ()
    state_root: Path | None = None


class ProviderRunner:
    """Run one request using explicit settings and caller-owned dependencies."""

    def __init__(
        self, options: ProviderRuntimeOptions, *, codex_sdk: CodexSdkManager | None = None, claude_api_key: str = "", nvidia_api_key: str = "",
        nvidia_model_api_keys: Mapping[str, str] | None = None,
        resolve_executable: Callable[[str], str | None] | None = None,
        terminate_process: Callable[[subprocess.Popen[str]], None] | None = None,
    ) -> None:
        self.options = options
        self.repo = options.repo
        self._codex_sdk = codex_sdk
        self._claude_api_key = claude_api_key
        self._nvidia_api_key = nvidia_api_key
        self._nvidia_model_api_keys = dict(nvidia_model_api_keys) if nvidia_model_api_keys is not None else {}
        self._resolve_executable = resolve_executable if resolve_executable is not None else resolve_provider_executable
        self._terminate_agent_process = terminate_process if terminate_process is not None else self.terminate_process

    def run(
        self,
        *,
        agent: AgentConfig,
        command_template: tuple[str, ...],
        replacements: dict[str, str],
        cwd: Path,
        prompt: str,
        prompt_path: str,
        log_path: Path,
        action: str,
        task_id: str,
        timeout_seconds: float | None = None,
        model: str = "",
        reasoning_effort: str = "",
        progress_callback: Callable[[CodexSdkProgress], None] | None = None,
        profile_callback: Callable[[CodexSdkExecutionProfile], None] | None = None,
        sdk_conversation_id: str = "",
        attempt_id: str = "",
        invocation_id: str = "",
        cancel_signal: ProviderStopSignal | None = None,
        usage_callback: Callable[[UsageObservation], None] | None = None,
        retry_callback: Callable[[str | None], None] | None = None,
    ) -> str:
        servers = tuple(server for server in self.options.mcp_servers if server.enabled) if action in {"execute", "revise"} else ()
        mcp_redactions = secret_values(servers)
        if servers:
            prompt += (
                "\n\n## Connected worker tools\n"
                + "Available MCP connections: " + ", ".join(server.id for server in servers)
                + f". The approved local workspace is {cwd.resolve()}. Use tools only for this Task's approved scope. "
                "Before changing a local editor/project through MCP, inspect its project path and instance and confirm it matches this workspace. "
                "If the target cannot be confirmed, report the missing connection instead of editing another project or Main. "
                "Remote tool actions must also stay within the approved project and Task. "
                "MCP access does not grant merge, push or deployment approval."
            )
        if agent.provider_id == "codex" and len(prompt) > CODEX_INPUT_LIMIT_CHARACTERS:
            raise ProviderInputLimitError(f"Codex input exceeds the maximum length of {CODEX_INPUT_LIMIT_CHARACTERS} characters: {len(prompt)}")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        timeout = self.options.agent_timeout_seconds if timeout_seconds is None else timeout_seconds
        private_state = (self.options.state_root or self.repo / ".ai-orchestrator").resolve()
        planning_source = replacements.get("{planning_source}", "") if action == "planning" else ""
        if planning_source:
            source = Path(planning_source).resolve()
            if source.is_relative_to(private_state) or private_state.is_relative_to(source):
                raise ProviderRunError("실행 기록 폴더를 포함하지 않는 기획 자료 경로를 선택해 주세요.")
        if agent.provider_id == "codex":
            if self._codex_sdk is None:
                raise ProviderRunError(f"agent {agent.id} requires the openai-codex SDK")
            sdk_profile = self.codex_profile(agent, action)
            if sdk_profile is None:  # pragma: no cover - provider checked above
                raise AssertionError(agent.provider_id)
            sandbox_mode, approval_mode = sdk_profile
            try:
                return self._codex_sdk.run_turn(
                    CodexSdkTurnRequest(
                        cwd=cwd,
                        prompt=prompt,
                        log_path=log_path,
                        model=model,
                        reasoning_effort=reasoning_effort,
                        sandbox_mode=sandbox_mode,
                        approval_mode=approval_mode,
                        timeout_seconds=timeout,
                        conversation_id=sdk_conversation_id,
                        attempt_id=attempt_id,
                        invocation_id=invocation_id or str(uuid.uuid4()),
                        cancel_signal=cancel_signal,
                        progress_callback=progress_callback,
                        profile_callback=profile_callback,
                        usage_callback=usage_callback,
                        retry_callback=retry_callback,
                        mcp_servers=servers,
                        project_root=self.repo if servers else None,
                        planning_state_root=private_state if action == "planning" else None,
                        planning_source_root=Path(planning_source) if planning_source else None,
                    )
                )
            except CodexSdkTimeout as exc:
                raise ProviderTimedOut(f"agent {agent.id} timed out after {timeout:g} seconds; see {log_path}") from exc
            except CodexSdkError as exc:
                if exc.request_limit:
                    message = ("AI 사용 한도에 도달했습니다. AI 사용 한도와 갱신 시점을 확인한 뒤 다시 시도해 주세요."
                               if exc.request_limit == "usage" else "AI 요청이 제한되었습니다. 잠시 후 다시 시도해 주세요.")
                    raise ProviderRequestLimited(f"{message} agent {agent.id} Codex SDK failed: {exc}; see {log_path}") from exc
                if exc.service_unavailable:
                    message = ("선택한 AI 모델이 혼잡합니다." if exc.model_capacity else "AI 서버가 일시적으로 응답하지 않습니다.")
                    raise ProviderUnavailable(
                        f"{message} 잠시 후 명시적으로 다시 시도하세요. agent {agent.id} Codex SDK failed: {exc}; see {log_path}"
                    ) from exc
                raise ProviderRunError(f"agent {agent.id} Codex SDK failed: {exc}; see {log_path}") from exc
        command = []
        for part in command_template:
            expanded = part
            for token, value in replacements.items():
                expanded = expanded.replace(token, value)
            command.append(expanded)
        executable = self._resolve_executable(command[0]) if command else ""
        if not executable:
            if agent.provider_id == "nvidia":
                raise ProviderRunError(NVIDIA_SETUP)
            missing = command[0] if command else agent.id
            raise ProviderRunError(f"provider executable not found for {agent.id}: {missing}")
        command[0] = executable
        if agent.provider_id == "claude":
            environment = claude_environment(self._claude_api_key)
        else:
            environment = runtime_environment(extra=("NVIDIA_API_KEY",) if agent.provider_id == "nvidia" else ())
        environment.update(
            {
                "AI_ORCHESTRATOR_RUN_ID": replacements["{run_id}"],
                "AI_ORCHESTRATOR_TASK_ID": task_id,
                "AI_ORCHESTRATOR_PROMPT": prompt_path,
                "AI_ORCHESTRATOR_PROVIDER": agent.provider_id,
                "AI_ORCHESTRATOR_ACTION": action,
                "PYTHONIOENCODING": "utf-8",
            }
        )
        if agent.provider_id == "nvidia":
            api_key = self._nvidia_model_api_keys.get((model or agent.model).strip(), self._nvidia_api_key)
            if not nvidia_key_configured(environment, api_key=api_key):
                raise ProviderRunError(NVIDIA_SETUP)
            environment = nvidia_environment(environment, model=model or agent.model, action=action, api_key=api_key)
        elif agent.provider_id == "claude":
            work = cwd.resolve()
            protected = f"./{private_state.relative_to(work).as_posix()}" if private_state.is_relative_to(work) else ""
            configure_claude_tools(
                command, action, worker_mcp=bool(servers), planning_source=planning_source, private_state_path=protected,
            )
            if servers:
                environment.update(configure_claude_mcp(command, servers, cwd, self.repo))
        process_options: dict[str, object] = {}
        if os.name == "nt":
            process_options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            process_options["start_new_session"] = True
        with process_working_directory(cwd) as process_cwd:
            if agent.provider_id == "nvidia":
                directory = cwd.resolve() if process_cwd == cwd else process_cwd
                command.extend(("--dir", str(directory)))
            process = subprocess.Popen(
                command,
                cwd=process_cwd,
                text=True,
                encoding="utf-8",
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=environment,
                **process_options,
            )
            try:
                if cancel_signal is None:
                    output, _ = process.communicate(input=prompt, timeout=timeout)
                else:
                    deadline = time.monotonic() + timeout
                    input_value: str | None = prompt
                    while True:
                        if cancel_signal.is_set():
                            self._terminate_agent_process(process)
                            try:
                                output, _ = process.communicate(timeout=AGENT_OUTPUT_DRAIN_TIMEOUT_SECONDS)
                            except subprocess.TimeoutExpired:
                                self.close_process_streams(process)
                                output = ""
                            output = output or ""
                            output += "\n[ai-orchestrator] stopped by user request\n"
                            if agent.provider_id == "nvidia":
                                output = redact_nvidia_output(output, environment)
                            elif agent.provider_id == "claude":
                                output = redact_claude_output(output, self._claude_api_key)
                            output = redact_mcp_output(output, mcp_redactions)
                            log_path.write_text(output, encoding="utf-8")
                            raise ExecutionStopped("사용자 요청에 따라 에이전트 실행을 중지했습니다.", request_id=cancel_signal.request_id)
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise subprocess.TimeoutExpired(command, timeout)
                        try:
                            output, _ = process.communicate(input=input_value, timeout=min(0.25, remaining))
                            break
                        except subprocess.TimeoutExpired:
                            input_value = None
                            continue
            except subprocess.TimeoutExpired as exc:
                output = self.timeout_expired_output(exc)
                self._terminate_agent_process(process)
                try:
                    drained_output, _ = process.communicate(timeout=AGENT_OUTPUT_DRAIN_TIMEOUT_SECONDS)
                    if drained_output:
                        output = drained_output
                except subprocess.TimeoutExpired as drain_exc:
                    drained_output = self.timeout_expired_output(drain_exc)
                    if drained_output:
                        output = drained_output
                    self.close_process_streams(process)
                output = output or ""
                output += f"\n[ai-orchestrator] timed out after {timeout:g} seconds\n"
                if agent.provider_id == "nvidia":
                    output = redact_nvidia_output(output, environment)
                elif agent.provider_id == "claude":
                    output = redact_claude_output(output, self._claude_api_key)
                output = redact_mcp_output(output, mcp_redactions)
                log_path.write_text(output, encoding="utf-8")
                raise ProviderTimedOut(f"agent {agent.id} timed out after {timeout:g} seconds; see {log_path}")
        output = output or ""
        if agent.provider_id == "nvidia":
            output = redact_nvidia_output(output, environment)
        elif agent.provider_id == "claude":
            output = redact_claude_output(output, self._claude_api_key)
        output = redact_mcp_output(output, mcp_redactions)
        log_path.write_text(output, encoding="utf-8")
        if process.returncode != 0:
            if agent.provider_id == "nvidia":
                raise self.nvidia_failure(output, log_path)
            raise ProviderRunError(self.failure_message(
                agent, process.returncode, output, log_path, api_key_auth=bool(environment.get("ANTHROPIC_API_KEY"))
            ))
        if agent.provider_id == "nvidia":
            try:
                answer, observation = parse_nvidia_output(output)
            except NvidiaAgentError as exc:
                log_path.write_text(f"{output}\n[ai-orchestrator] {exc}\n", encoding="utf-8")
                if isinstance(exc, NvidiaCompletionError):
                    raise ProviderRunError(f"{exc}; see {log_path}") from exc
                raise self.nvidia_failure(str(exc), log_path) from exc
            if observation is not None and usage_callback is not None:
                usage_callback(observation)
            return answer
        return output

    @staticmethod
    def nvidia_failure(output: str, log_path: Path) -> ProviderRunError:
        normalized = output.casefold()
        if "429" in normalized or "rate limit" in normalized or "too many requests" in normalized:
            return ProviderRequestLimited(f"NVIDIA 요청이 제한되었습니다. 잠시 후 다시 시도해 주세요; see {log_path}")
        if "503" in normalized or "at capacity" in normalized or "service unavailable" in normalized:
            return ProviderUnavailable(f"NVIDIA 모델이 혼잡하거나 서버가 일시적으로 응답하지 않습니다; see {log_path}")
        return ProviderRunError(f"NVIDIA 에이전트 실행이 완료되지 않았습니다. 실패 로그를 확인해 주세요; see {log_path}")

    @staticmethod
    def failure_message(
        agent: AgentConfig, returncode: int, output: str, log_path: Path, *, api_key_auth: bool = False
    ) -> str:
        normalized_output = output.casefold()
        if agent.provider_id == "claude" and api_key_auth and re.search(
            r"\b(?:invalid (?:x-)?api[ -]key|authentication_error|failed to authenticate|not logged in)\b", normalized_output
        ):
            return f"Claude API 인증에 실패했습니다. 작업 AI의 Claude에서 API 키를 확인하고 다시 시도하세요; see {log_path}"
        if agent.provider_id == "claude" and re.search(r"(?m)^[ \t]*(?:error:[ \t]*)?not logged in\b", normalized_output):
            return (
                "Claude 로그인이 필요합니다. AI 연결에서 Claude 로그인 후 연결을 다시 확인하고 "
                f"요청을 재시도하세요; see {log_path}"
            )
        if agent.provider_id == "claude" and (
            "oauth access token has expired" in normalized_output
            or "failed to authenticate" in normalized_output
        ):
            return (
                "Claude 로그인이 만료되었거나 인증에 실패했습니다. "
                "터미널에서 `claude auth login`으로 다시 로그인한 뒤 "
                f"요청을 재시도하세요; see {log_path}"
            )
        return f"agent {agent.id} exited with {returncode}; see {log_path}"

    @staticmethod
    def codex_profile(agent: AgentConfig, action: str) -> tuple[str, str] | None:
        if agent.provider_id != "codex":
            return None
        if action == "planning":
            return "read-only", "deny-all"
        if action == "review":
            return agent.review_sandbox_mode, agent.review_approval_mode
        return agent.sandbox_mode, agent.approval_mode

    @staticmethod
    def terminate_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=AGENT_TERMINATION_TIMEOUT_SECONDS,
                )
            except (subprocess.TimeoutExpired, OSError):
                pass
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                return
        if process.poll() is None:
            try:
                process.kill()
            except (OSError, ValueError):
                pass

    @staticmethod
    def timeout_expired_output(exc: subprocess.TimeoutExpired) -> str:
        output = exc.output or ""
        if isinstance(output, bytes):
            return output.decode("utf-8", errors="replace")
        return output

    @staticmethod
    def close_process_streams(process: subprocess.Popen[str]) -> None:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is None:
                continue
            try:
                stream.close()
            except (OSError, ValueError):
                pass
