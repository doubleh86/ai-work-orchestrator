from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal, Mapping, Sequence

from .verification_runner import DOTNET_BUILD_OUTPUT_ACCESS_ERROR, VerificationRunner


@dataclass(frozen=True, slots=True)
class AutomaticRecoveryDecision:
    action: Literal["repair", "retry_verification", "stop"]
    reason: str = ""


def automatic_recovery_decision(
    command: Sequence[str], output: str, *, recovery_index: int, recovery_limit: int,
    environment_retries: int, same_failure: bool,
) -> AutomaticRecoveryDecision:
    if VerificationRunner.output_file_locked(tuple(command), output):
        return AutomaticRecoveryDecision("stop", "출력 파일이 사용 중입니다. 해당 앱을 종료한 뒤 다시 검증하세요.")
    if VerificationRunner.build_output_access_denied(command, output):
        if environment_retries == 0 and recovery_index < recovery_limit:
            return AutomaticRecoveryDecision("retry_verification")
        return AutomaticRecoveryDecision(
            "stop", f"{DOTNET_BUILD_OUTPUT_ACCESS_ERROR} 변경한 자식 환경에서도 같은 접근 오류가 계속됩니다. "
            "동일 환경의 검증을 반복하지 않고 파일 접근 원인 확인을 기다립니다.",
        )
    if recovery_index >= recovery_limit:
        return AutomaticRecoveryDecision(
            "stop", f"자동 복구 {recovery_limit}회 이후에도 검증을 통과하지 못했습니다. 실패 근거와 작업 범위를 확인하세요.",
        )
    if same_failure:
        return AutomaticRecoveryDecision("stop", "코드 변경 없이 같은 검증 실패가 반복됐습니다. 실패 근거와 작업 범위를 확인하세요.")
    return AutomaticRecoveryDecision("repair")


def verification_failure_is_repairable(message: str) -> bool:
    message = message.casefold()
    if "검증 명령이 실패했습니다:" not in message:
        return False
    environment_markers = (
        "sdk 환경", "의존성 복원", "permission denied", "access is denied", "액세스가 거부", "timed out", "제한시간", "not found",
    )
    return not any(marker in message for marker in environment_markers)


def verification_failure_fingerprint(command: Sequence[str], output: str) -> str:
    lines: list[str] = []
    for line in output.splitlines():
        if re.match(r"^\s*(?:Time Elapsed|경과 시간|총 시간|Total time)\s*:\s*[\d:.,\s]+(?:분|초|ms|s|m|minutes?|seconds?)?\s*$",
                    line, re.IGNORECASE):
            continue
        line = re.sub(r"^\s*\[xUnit\.net [\d:.]+\]\s*", "[xUnit.net] ", line)
        line = re.sub(r"^\s*\[\d{4}-\d{2}-\d{2}T[^\]]+\]\s*", "[time] ", line)
        if re.match(r"^\s*(?:통과|실패|Passed|Failed)\s", line):
            line = re.sub(r"\s+\[(?:<\s*)?\d+(?:[.,]\d+)?\s*(?:ms|s|m)\]$", " [duration]", line)
        lines.append(line.rstrip())
    value = [command, "\n".join(lines).strip()]
    return hashlib.sha256(json.dumps(value, ensure_ascii=False).encode("utf-8")).hexdigest()


def verification_timed_out(
    message: str, *, latest_status: str = "", latest_failure_kind: str = "", latest_error: str = "",
) -> bool:
    prefixes = ("command timed out after ", "Task 검증 시간 초과", "Task 검증 전체 제한시간을 초과했습니다:")
    if message.startswith(prefixes):
        return True
    return latest_status == "failed" and (latest_failure_kind == "timeout" or latest_error.startswith(prefixes))


def recovery_timeout_limits(
    current: tuple[int, int], configured: tuple[int, int], minimum: tuple[int, int],
) -> tuple[int, int]:
    command_timeout = max(current[0], configured[0], minimum[0])
    total_timeout = max(current[1], configured[1], minimum[1], command_timeout)
    return command_timeout, total_timeout


def timeout_retry_context(
    *, head: str, commands: tuple[tuple[str, ...], ...], current_limits: tuple[int, int], proposed_limits: tuple[int, int],
    tool: str, failed_digests: tuple[str, ...], latest_inputs: Mapping[str, object], can_execute: bool,
) -> dict[str, object]:
    command_list = [list(command) for command in commands]
    current, proposed = list(current_limits), list(proposed_limits)
    contexts: list[object] = [["task_total", head, command_list, proposed[0], proposed[1], None, tool]]
    for command in command_list:
        selected: object = [tool or command[0], *command[1:]] if VerificationRunner.is_dotnet_command(command) else command
        if latest_inputs.get("tool") == tool and latest_inputs.get("command") == command:
            selected = latest_inputs.get("selected_command") or selected
        contexts.append([head, command_list, command, selected, proposed[0], proposed[1], None])
    digests = {hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest() for value in contexts}
    same = any(digest in digests for digest in failed_digests)
    values = {"head": head, "commands": command_list, "limits": proposed, "tool": tool,
              "environment": hashlib.sha256(json.dumps(None).encode()).hexdigest()}
    changed = [name for name, value in values.items() if name in latest_inputs and latest_inputs[name] != value]
    return {
        "kind": "diagnose" if same else "verify_with_timeout_adjustment" if current != proposed else "verify",
        "can_execute": can_execute and not same,
        "reason_code": "same_timeout_context" if same else "" if can_execute else "unavailable",
        "history_known": bool(latest_inputs) or same, "changed_factors": changed,
        "fingerprint": hashlib.sha256(json.dumps([head, command_list, current, proposed, sorted(digests)]).encode()).hexdigest(),
    }
