from copy import deepcopy

import pytest

from ai_orchestrator.execution import automatic_recovery_decision, timeout_retry_context, verification_timed_out


LOCKED_OUTPUT = 'error MSB3027: The file is locked by: Example (123)'
ACCESS_DENIED = "error MSB4018: Access to the path 'obj/Debug/cache' is denied."


@pytest.mark.parametrize(("output", "index", "environment_retries", "same", "action", "reason"), [
    (LOCKED_OUTPUT + "\n" + ACCESS_DENIED, 3, 0, True, "stop", "출력 파일이 사용 중"),
    (ACCESS_DENIED, 0, 0, True, "retry_verification", ""),
    (ACCESS_DENIED, 1, 1, False, "stop", ".NET 빌드 산출물 쓰기 접근이 거부"),
    (ACCESS_DENIED, 3, 0, False, "stop", ".NET 빌드 산출물 쓰기 접근이 거부"),
    ("assert mismatch", 3, 0, True, "stop", "자동 복구 3회"),
    ("assert mismatch", 1, 0, True, "stop", "코드 변경 없이 같은 검증 실패"),
    ("assert mismatch", 0, 0, False, "repair", ""),
])
def test_automatic_recovery_keeps_failure_priority_and_bounds(output, index, environment_retries, same, action, reason):
    decision = automatic_recovery_decision(
        ("dotnet", "test"), output, recovery_index=index, recovery_limit=3, environment_retries=environment_retries, same_failure=same,
    )
    assert decision.action == action
    if reason:
        assert decision.reason.startswith(reason)
    else:
        assert decision.reason == ""


def test_timeout_retry_context_recognizes_saved_executable_and_preserves_legacy_fingerprint():
    inputs = {"head": "a" * 40, "tool": "dotnet", "command": ["dotnet", "test"], "selected_command": ["C:/sdk/dotnet.exe", "test"]}
    preserved = deepcopy(inputs)
    params = dict(
        commands=(("dotnet", "test"),), current_limits=(900, 1800), proposed_limits=(900, 1800), tool="dotnet", can_execute=True,
        failed_digests=("cb1adae02b6886ce4287d4da187515d64c2ea263e22abe277c4c69a81a6f742f",), latest_inputs=inputs,
    )
    same = timeout_retry_context(head="a" * 40, **params)
    assert same["kind"] == "diagnose" and not same["can_execute"] and same["reason_code"] == "same_timeout_context"
    assert same["fingerprint"] == "e30e8fc1a4d2d23331bbfb55105497412f20dd7cb1fd1316136a8538939aae1e"
    assert same["history_known"] and same["changed_factors"] == []
    changed = timeout_retry_context(head="b" * 40, **params)
    assert changed["kind"] == "verify" and changed["can_execute"] and changed["changed_factors"] == ["head"]
    assert changed["fingerprint"] != same["fingerprint"] and inputs == preserved


@pytest.mark.parametrize(("message", "status", "kind", "error", "expected"), [
    ("Task 검증 시간 초과", "succeeded", "", "", True),
    ("", "failed", "timeout", "", True),
    ("", "failed", "", "command timed out after 900s", True),
    ("", "succeeded", "timeout", "command timed out after 900s", False),
    ("", "failed", "command_failed", "test failed", False),
])
def test_timeout_classification_keeps_legacy_error_and_action_evidence(message, status, kind, error, expected):
    assert verification_timed_out(message, latest_status=status, latest_failure_kind=kind, latest_error=error) is expected
