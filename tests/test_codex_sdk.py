from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Callable
from unittest.mock import patch

from openai_codex.types import TurnError

import pytest

from ai_orchestrator.codex_sdk import (
    CodexSdkAccountStatus,
    CodexSdkError,
    CodexSdkExecutionProfile,
    CodexSdkManager,
    CodexSdkProgress,
    CodexSdkTimeout,
    CodexSdkTurnRequest,
    _collect_turn_result,
)
from ai_orchestrator.execution_control import ExecutionStopped


class FakeTurnHandle:
    def __init__(
        self,
        response: str = "structured plan",
        *,
        error: Exception | None = None,
        blocked: bool = False,
        events: list[object] | None = None,
        event_delay_seconds: float = 0,
    ) -> None:
        self.id = "turn-1"
        self.response = response
        self.error = error
        self.blocked = blocked
        self.events = events or []
        self.event_delay_seconds = event_delay_seconds
        self.started = threading.Event()
        self.released = threading.Event()
        self.interrupt_count = 0

    def stream(self):
        self.started.set()
        if self.blocked:
            self.released.wait(timeout=2)
        if self.error is not None:
            raise self.error
        for event in self.events:
            if self.event_delay_seconds:
                time.sleep(self.event_delay_seconds)
            yield event
        agent_item = _thread_item("agentMessage", text=self.response, phase=_enum("final_answer"))
        yield _notification("item/started", item=agent_item, turn_id=self.id)
        yield _notification("item/completed", item=agent_item, turn_id=self.id)
        yield _notification(
            "turn/completed", turn=SimpleNamespace(id=self.id, status=_enum("completed"), error=None, started_at=1, completed_at=2, duration_ms=12)
        )

    def interrupt(self) -> None:
        self.interrupt_count += 1
        self.released.set()


class FakeLoginHandle:
    def __init__(
        self,
        *,
        device_code: bool = False,
        blocked: bool = True,
        error: Exception | None = None,
        release_on_cancel: bool = True,
    ) -> None:
        self.login_id = "sdk-login-id"
        self.auth_url = "https://auth.openai.com/oauth/authorize?secret=hidden"
        self.verification_url = "https://auth.openai.com/codex/device"
        self.user_code = "ABCD-EFGH" if device_code else ""
        self.blocked = blocked
        self.error = error
        self.release_on_cancel = release_on_cancel
        self.started = threading.Event()
        self.released = threading.Event()
        self.cancel_count = 0

    def wait(self) -> object:
        self.started.set()
        if self.blocked:
            self.released.wait(timeout=2)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(success=not self.cancel_count, error=None)

    def cancel(self) -> object:
        self.cancel_count += 1
        if self.release_on_cancel:
            self.released.set()
        return SimpleNamespace(status=_enum("cancelled"))


class FakeThread:
    def __init__(self, handle: FakeTurnHandle) -> None:
        self.handle = handle
        self.turn_calls: list[tuple[object, dict[str, object]]] = []

    def turn(self, prompt: object, **kwargs: object) -> FakeTurnHandle:
        self.turn_calls.append((prompt, kwargs))
        return self.handle


class FakeCodex:
    def __init__(self, handle: FakeTurnHandle | None = None, *, login_handle: FakeLoginHandle | None = None) -> None:
        self.handle = handle or FakeTurnHandle()
        self.thread = FakeThread(self.handle)
        self.thread_start_calls: list[dict[str, object]] = []
        self.account_calls: list[bool] = []
        self.account_response = _account_response("chatgpt")
        self.account_error: Exception | None = None
        self.models_calls = 0
        self.models_response = SimpleNamespace(data=[_model("gpt-5.6-luna", default=True), _model("gpt-6.1-sol")])
        self.close_count = 0
        self.login_handle = login_handle or FakeLoginHandle(blocked=False)
        self.browser_login_count = 0
        self.device_login_count = 0
        self.api_key_login_count = 0

    def login_api_key(self, api_key: str) -> None:
        assert api_key == "sk-fixture-only"
        self.api_key_login_count += 1
        self.account_response = _account_response("apiKey")

    def thread_start(self, **kwargs: object) -> FakeThread:
        self.thread_start_calls.append(kwargs)
        return self.thread

    def account(self, *, refresh_token: bool = False) -> object:
        self.account_calls.append(refresh_token)
        if self.account_error is not None:
            raise self.account_error
        return self.account_response

    def models(self) -> object:
        self.models_calls += 1
        return self.models_response

    def login_chatgpt(self) -> FakeLoginHandle:
        self.browser_login_count += 1
        return self.login_handle

    def login_chatgpt_device_code(self) -> FakeLoginHandle:
        self.device_login_count += 1
        return self.login_handle

    def close(self) -> None:
        self.close_count += 1
        self.handle.released.set()


class FakeClientFactory:
    def __init__(self, clients: list[FakeCodex]) -> None:
        self.clients = clients
        self.call_count = 0

    def __call__(self) -> FakeCodex:
        client = self.clients[self.call_count]
        self.call_count += 1
        return client


def request(
    tmp_path: Path,
    *,
    timeout: float = 2,
    sandbox: str = "read-only",
    approval: str = "deny-all",
    model: str = "gpt-test",
    reasoning_effort: str = "medium",
    conversation_id: str = "",
    progress_callback: Callable[[CodexSdkProgress], None] | None = None,
    profile_callback: Callable[[CodexSdkExecutionProfile], None] | None = None,
    cancel_signal: object | None = None,
) -> CodexSdkTurnRequest:
    return CodexSdkTurnRequest(
        cwd=tmp_path,
        prompt="return a plan",
        log_path=tmp_path / "planning.log",
        model=model,
        reasoning_effort=reasoning_effort,
        sandbox_mode=sandbox,
        approval_mode=approval,
        timeout_seconds=timeout,
        conversation_id=conversation_id,
        progress_callback=progress_callback,
        profile_callback=profile_callback,
        cancel_signal=cancel_signal,
    )


def _enum(value: str) -> SimpleNamespace:
    return SimpleNamespace(value=value)


def _model(model: str, *, default: bool = False, reasoning_effort: str = "high") -> SimpleNamespace:
    return SimpleNamespace(id=model, model=model, is_default=default, default_reasoning_effort=_enum(reasoning_effort))


def _thread_item(item_type: str, **values: object) -> SimpleNamespace:
    return SimpleNamespace(root=SimpleNamespace(type=item_type, **values))


def _notification(method: str, **values: object) -> SimpleNamespace:
    return SimpleNamespace(method=method, payload=SimpleNamespace(**values))


def _account_response(
    account_type: str | None, *, requires_openai_auth: bool = True, email: object = "private@example.com", plan_type: object = "plus",
) -> SimpleNamespace:
    account = None
    if account_type is not None:
        account = SimpleNamespace(root=SimpleNamespace(type=account_type, email=email, plan_type=plan_type))
    return SimpleNamespace(account=account, requires_openai_auth=requires_openai_auth)


@pytest.mark.parametrize(
    ("account_type", "expected"),
    [
        ("chatgpt", CodexSdkAccountStatus(True, "chatgpt", "ChatGPT 구독 로그인", "private@example.com", "plus")),
        ("apiKey", CodexSdkAccountStatus(True, "api_key", "API 키 · 사용량 과금")),
        ("amazonBedrock", CodexSdkAccountStatus(True, "external", "Amazon Bedrock 인증")),
    ],
)
def test_manager_reports_account_authentication_method(account_type: str, expected: CodexSdkAccountStatus) -> None:
    client = FakeCodex()
    client.account_response = _account_response(account_type)
    manager = CodexSdkManager(client_factory=FakeClientFactory([client]))  # type: ignore[arg-type]

    assert manager.account_status() == expected
    manager.close()

    assert client.account_calls == [False]
    assert "private@example.com" not in expected.label
    assert client.close_count == 1


def test_manager_reports_login_required_and_external_provider() -> None:
    signed_out = FakeCodex()
    external = FakeCodex()
    signed_out.account_response = _account_response(None)
    external.account_response = _account_response(None, requires_openai_auth=False)
    signed_out_manager = CodexSdkManager(client_factory=FakeClientFactory([signed_out]))  # type: ignore[arg-type]
    external_manager = CodexSdkManager(client_factory=FakeClientFactory([external]))  # type: ignore[arg-type]

    assert signed_out_manager.account_status() == CodexSdkAccountStatus(False, "none", "로그인 필요")
    assert external_manager.account_status() == CodexSdkAccountStatus(True, "external", "외부 Provider 인증")
    signed_out_manager.close()
    external_manager.close()


def test_manager_discards_client_when_account_status_fails() -> None:
    client = FakeCodex()
    client.account_error = RuntimeError("account read failed")
    manager = CodexSdkManager(client_factory=FakeClientFactory([client]))  # type: ignore[arg-type]

    with pytest.raises(CodexSdkError, match="account status"):
        manager.account_status()

    assert client.close_count == 1


def test_manager_reuses_sdk_client_and_maps_turn_options(tmp_path: Path) -> None:
    client = FakeCodex()
    factory = FakeClientFactory([client])
    manager = CodexSdkManager(client_factory=factory)  # type: ignore[arg-type]

    assert manager.run_turn(request(tmp_path)) == "structured plan"
    assert manager.run_turn(request(tmp_path)) == "structured plan"
    manager.close()

    assert factory.call_count == 1
    assert client.models_calls == 0
    assert client.close_count == 1
    assert len(client.thread_start_calls) == 2
    thread_start = client.thread_start_calls[0]
    assert thread_start["cwd"] == str(tmp_path.resolve())
    assert thread_start["ephemeral"] is True
    assert thread_start["model"] == "gpt-test"
    assert thread_start["sandbox"].value == "read-only"  # type: ignore[union-attr]
    assert thread_start["approval_mode"].value == "deny_all"  # type: ignore[union-attr]
    prompt, turn_options = client.thread.turn_calls[0]
    assert prompt == "return a plan"
    assert turn_options["effort"].value == "medium"  # type: ignore[union-attr]
    assert '"transport": "codex-sdk"' in (tmp_path / "planning.log").read_text(encoding="utf-8")


@pytest.mark.parametrize("conversation_id", ["", "planning:astra"])
def test_manager_passes_explicit_astra_profile_without_catalog_entry(tmp_path: Path, conversation_id: str) -> None:
    client = FakeCodex()
    profiles: list[CodexSdkExecutionProfile] = []
    manager = CodexSdkManager(client_factory=FakeClientFactory([client]))  # type: ignore[arg-type]

    try:
        result = manager.run_turn(
            request(tmp_path, model="gpt-6-astra", reasoning_effort="medium", conversation_id=conversation_id, profile_callback=profiles.append)
        )
    finally:
        manager.close()

    assert result == "structured plan"
    assert client.models_calls == 0
    assert client.thread_start_calls[0]["model"] == "gpt-6-astra"
    _, turn_options = client.thread.turn_calls[0]
    assert turn_options["model"] == "gpt-6-astra"
    assert turn_options["effort"].value == "medium"  # type: ignore[union-attr]
    assert profiles == [
        CodexSdkExecutionProfile(model="gpt-6-astra", reasoning_effort="medium", model_automatic=False, reasoning_effort_automatic=False)
    ]


def test_manager_requires_explicit_effort_for_model_missing_from_catalog(tmp_path: Path) -> None:
    client = FakeCodex()
    manager = CodexSdkManager(client_factory=FakeClientFactory([client]))  # type: ignore[arg-type]

    try:
        with pytest.raises(CodexSdkError, match="추론 강도를.*직접 선택"):
            manager.run_turn(request(tmp_path, model="gpt-6-astra", reasoning_effort=""))
    finally:
        manager.close()

    assert client.models_calls == 1
    assert client.thread_start_calls == []


def test_manager_does_not_fallback_when_astra_execution_fails(tmp_path: Path) -> None:
    client = FakeCodex(FakeTurnHandle(error=RuntimeError("model unavailable")))
    manager = CodexSdkManager(client_factory=FakeClientFactory([client]))  # type: ignore[arg-type]

    try:
        with pytest.raises(CodexSdkError, match="model unavailable"):
            manager.run_turn(request(tmp_path, model="gpt-6-astra"))
    finally:
        manager.close()

    assert len(client.thread_start_calls) == 1
    assert client.thread_start_calls[0]["model"] == "gpt-6-astra"
    assert client.models_calls == 0


def test_manager_resolves_and_reports_automatic_execution_profile(tmp_path: Path) -> None:
    client = FakeCodex()
    profiles: list[CodexSdkExecutionProfile] = []
    manager = CodexSdkManager(client_factory=FakeClientFactory([client]))  # type: ignore[arg-type]

    result = manager.run_turn(request(tmp_path, model="", reasoning_effort="", profile_callback=profiles.append))
    manager.close()

    assert result == "structured plan"
    assert client.models_calls == 1
    assert client.thread_start_calls[0]["model"] == "gpt-6.1-sol"
    _, turn_options = client.thread.turn_calls[0]
    assert turn_options["model"] == "gpt-6.1-sol"
    assert turn_options["effort"].value == "high"  # type: ignore[union-attr]
    assert profiles == [
        CodexSdkExecutionProfile(model="gpt-6.1-sol", reasoning_effort="high", model_automatic=True, reasoning_effort_automatic=True)
    ]
    log = (tmp_path / "planning.log").read_text(encoding="utf-8")
    assert '"event": "execution-profile"' in log
    assert '"effective_model": "gpt-6.1-sol"' in log


@pytest.mark.parametrize("effort", ["", "low", "ultra"])
def test_manual_terra_reaches_sdk_with_catalog_default_or_explicit_effort(tmp_path: Path, effort: str) -> None:
    client = FakeCodex()
    client.models_response = SimpleNamespace(data=[_model("gpt-6.1-sol", default=True), _model("gpt-6.1-terra", reasoning_effort="low")])
    profiles: list[CodexSdkExecutionProfile] = []
    manager = CodexSdkManager(client_factory=FakeClientFactory([client]))  # type: ignore[arg-type]
    try:
        result = manager.run_turn(request(tmp_path, model="gpt-6.1-terra", reasoning_effort=effort, profile_callback=profiles.append))
        assert result == "structured plan"
    finally:
        manager.close()
    assert client.thread_start_calls[0]["model"] == "gpt-6.1-terra"
    _, options = client.thread.turn_calls[0]
    assert options["model"] == "gpt-6.1-terra"
    assert options["effort"].value == (effort or "low")  # type: ignore[union-attr]
    assert profiles == [CodexSdkExecutionProfile("gpt-6.1-terra", effort or "low", False, not bool(effort))]


def test_automatic_model_cannot_fall_back_to_a_legacy_sdk_default(tmp_path: Path) -> None:
    client = FakeCodex()
    client.models_response = SimpleNamespace(data=[_model("gpt-5.6-luna", default=True)])
    manager = CodexSdkManager(client_factory=FakeClientFactory([client]))  # type: ignore[arg-type]
    try:
        with pytest.raises(CodexSdkError, match="gpt-6.1-sol"):
            manager.run_turn(request(tmp_path, model="", reasoning_effort=""))
        assert client.thread_start_calls == []
    finally:
        manager.close()


def test_manager_continues_and_closes_named_conversation(tmp_path: Path) -> None:
    client = FakeCodex()
    manager = CodexSdkManager(client_factory=FakeClientFactory([client]))  # type: ignore[arg-type]

    first = request(tmp_path, conversation_id="planning:run-1")
    second = request(tmp_path, conversation_id="planning:run-1")
    assert not manager.has_conversation("planning:run-1", cwd=tmp_path, model="gpt-test", sandbox_mode="read-only", approval_mode="deny-all")
    assert manager.run_turn(first) == "structured plan"
    assert manager.has_conversation("planning:run-1", cwd=tmp_path, model="gpt-test", sandbox_mode="read-only", approval_mode="deny-all")
    assert not manager.has_conversation("planning:run-1", cwd=tmp_path, model="gpt-other", sandbox_mode="read-only", approval_mode="deny-all")
    assert manager.run_turn(second) == "structured plan"

    assert len(client.thread_start_calls) == 1
    assert len(client.thread.turn_calls) == 2
    manager.close_conversation("planning:run-1")
    manager.close()

    assert client.close_count == 1


def test_manager_resolves_automatic_profile_once_for_named_conversation(tmp_path: Path) -> None:
    client = FakeCodex()
    profiles: list[CodexSdkExecutionProfile] = []
    manager = CodexSdkManager(client_factory=FakeClientFactory([client]))  # type: ignore[arg-type]

    for _ in range(2):
        assert (
            manager.run_turn(
                request(tmp_path, model="", reasoning_effort="", conversation_id="planning:auto-profile", profile_callback=profiles.append)
            )
            == "structured plan"
        )
    manager.close_conversation("planning:auto-profile")
    manager.close()

    assert client.models_calls == 1
    assert len(client.thread_start_calls) == 1
    assert [profile.model for profile in profiles] == ["gpt-6.1-sol", "gpt-6.1-sol"]


def test_manager_restarts_named_conversation_when_model_changes(tmp_path: Path) -> None:
    client = FakeCodex()
    manager = CodexSdkManager(client_factory=FakeClientFactory([client]))  # type: ignore[arg-type]

    assert manager.run_turn(request(tmp_path, model="gpt-first", conversation_id="planning:run-profile")) == "structured plan"
    assert manager.run_turn(request(tmp_path, model="gpt-second", conversation_id="planning:run-profile")) == "structured plan"

    assert len(client.thread_start_calls) == 2
    assert client.thread_start_calls[0]["model"] == "gpt-first"
    assert client.thread_start_calls[1]["model"] == "gpt-second"
    manager.close_conversation("planning:run-profile")
    manager.close()


def test_sdk_uses_its_pinned_runtime_without_binary_override(tmp_path: Path) -> None:
    client = FakeCodex()
    with patch("openai_codex.Codex", return_value=client) as constructor:
        manager = CodexSdkManager()
        assert manager.run_turn(request(tmp_path)) == "structured plan"
        manager.close()

    sdk_config = constructor.call_args.args[0]
    assert sdk_config.codex_bin is None
    log = (tmp_path / "planning.log").read_text(encoding="utf-8")
    assert '"runtime": "sdk-pinned"' in log
    assert '"codex_bin"' not in log


def test_workspace_write_and_auto_review_are_preserved(tmp_path: Path) -> None:
    client = FakeCodex()
    manager = CodexSdkManager(client_factory=FakeClientFactory([client]))  # type: ignore[arg-type]

    manager.run_turn(request(tmp_path, sandbox="workspace-write", approval="auto-review"))
    manager.close()

    options = client.thread_start_calls[0]
    assert options["sandbox"].value == "workspace-write"  # type: ignore[union-attr]
    assert options["approval_mode"].value == "auto_review"  # type: ignore[union-attr]


def test_progress_stream_is_summarized_deduplicated_and_sanitized(tmp_path: Path) -> None:
    reasoning = _notification("item/started", item=_thread_item("reasoning"), turn_id="turn-1")
    long_step = "기획 문서의 관련 규약을 확인합니다.\n" + "범위 확인 " * 40
    events = [
        _notification("turn/started", turn=SimpleNamespace(id="turn-1")),
        reasoning,
        reasoning,
        _notification("item/started", item=_thread_item("commandExecution", command="rg -n password-sensitive-value ."), turn_id="turn-1"),
        _notification("turn/plan/updated", turn_id="turn-1", plan=[SimpleNamespace(status=_enum("inProgress"), step=long_step)]),
    ]
    client = FakeCodex(FakeTurnHandle(events=events))
    manager = CodexSdkManager(client_factory=FakeClientFactory([client]))  # type: ignore[arg-type]
    progress: list[CodexSdkProgress] = []

    assert manager.run_turn(request(tmp_path, progress_callback=progress.append)) == "structured plan"
    manager.close()

    phases = [item.phase for item in progress if item.activity_changed]
    assert phases == ["turn_started", "analyzing_request", "searching_files", "plan_step", "writing_response", "response_received"]
    plan_progress = next(item for item in progress if item.phase == "plan_step")
    assert len(plan_progress.detail) <= 160
    assert "\n" not in plan_progress.detail
    log = (tmp_path / "planning.log").read_text(encoding="utf-8")
    assert '"event": "turn-progress"' in log
    assert "password-sensitive-value" not in log


def test_progress_reports_completed_commands_and_plan_counts_without_arguments(tmp_path: Path) -> None:
    events = [
        _notification("item/started", turn_id="turn-1", item=_thread_item("commandExecution", command="dotnet test --password secret-value")),
        _notification(
            "item/completed", turn_id="turn-1", item=_thread_item("commandExecution", command="dotnet test --password secret-value", exit_code=1)
        ),
        _notification("item/completed", turn_id="turn-1", item=_thread_item("fileChange", status=_enum("failed"))),
        _notification(
            "turn/plan/updated",
            turn_id="turn-1",
            plan=[
                SimpleNamespace(status=_enum("completed"), step="조사"),
                SimpleNamespace(status=_enum("inProgress"), step="구현"),
            ],
        ),
    ]
    progress: list[CodexSdkProgress] = []
    manager = CodexSdkManager(client_factory=FakeClientFactory([FakeCodex(FakeTurnHandle(events=events))]))
    try:
        manager.run_turn(request(tmp_path, progress_callback=progress.append))
    finally:
        manager.close()
    reports = {(item.phase, item.detail) for item in progress}
    assert ("running_command", "dotnet test") in reports
    assert ("command_finished", "dotnet test · 종료 코드 1") in reports
    assert ("changes_finished", "적용 실패") in reports
    assert ("plan_step", "계획 단계 1/2 완료 · 구현") in reports
    log = (tmp_path / "planning.log").read_text(encoding="utf-8")
    assert "secret-value" not in log
    reports = [json.loads(line) for line in log.splitlines() if '"event": "turn-progress"' in line]
    assert reports and all(report.get("at") for report in reports)


def test_same_phase_events_are_observed_without_marking_every_delta_as_activity() -> None:
    handle = FakeTurnHandle(
        events=[
            _notification("item/started", item=_thread_item("reasoning")),
            _notification("item/reasoning/textDelta", delta="private reasoning"),
            _notification("item/reasoning/textDelta", delta="private reasoning"),
        ]
    )
    progress: list[CodexSdkProgress] = []
    _collect_turn_result(handle, progress.append, lambda: None, attempt_id="task:1:execute", invocation_id="invocation-1")
    analyzing = [item for item in progress if item.phase == "analyzing_request"]
    assert len(analyzing) == 3
    assert [item.activity_changed for item in analyzing] == [True, False, False]
    assert [item.event_seq for item in analyzing] == [1, 2, 3]
    assert all(item.invocation_id == "invocation-1" for item in analyzing)
    assert all("private reasoning" not in item.detail for item in progress)


def test_same_progress_for_a_new_item_is_an_activity_change() -> None:
    handle = FakeTurnHandle(
        events=[
            _notification("item/started", item=_thread_item("commandExecution", id="command-1", command="dotnet test")),
            _notification("item/started", item=_thread_item("commandExecution", id="command-2", command="dotnet test")),
        ]
    )
    progress: list[CodexSdkProgress] = []

    _collect_turn_result(handle, progress.append, lambda: None, invocation_id="invocation-1")

    commands = [item for item in progress if item.phase == "running_command"]
    assert [item.item_id for item in commands] == ["command-1", "command-2"]
    assert [item.activity_changed for item in commands] == [True, True]


def test_completed_turn_log_summarizes_large_sdk_items(tmp_path: Path) -> None:
    large_command = _notification("item/completed", item=_thread_item("commandExecution", aggregatedOutput="x" * 500_000), turn_id="turn-1")
    client = FakeCodex(FakeTurnHandle(events=[large_command]))
    manager = CodexSdkManager(client_factory=FakeClientFactory([client]))  # type: ignore[arg-type]

    assert manager.run_turn(request(tmp_path)) == "structured plan"
    manager.close()

    log_path = tmp_path / "planning.log"
    completed = next(json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if '"event": "turn-completed"' in line)
    assert log_path.stat().st_size < 10_000
    assert completed["item_count"] == 2
    assert completed["item_counts"] == {"commandExecution": 1, "agentMessage": 1}
    assert completed["final_response"] == "structured plan"
    assert "items" not in completed


def test_turn_failure_is_not_reported_as_success(tmp_path: Path) -> None:
    client = FakeCodex(FakeTurnHandle(error=RuntimeError("model failed")))
    manager = CodexSdkManager(client_factory=FakeClientFactory([client]))  # type: ignore[arg-type]

    with pytest.raises(CodexSdkError, match="model failed"):
        manager.run_turn(request(tmp_path))
    manager.close()

    assert '"event": "turn-failed"' in (tmp_path / "planning.log").read_text(encoding="utf-8")


@pytest.mark.parametrize(("message", "info", "capacity"), [
    ("Selected model is at capacity. Please try a different model.", None, True),
    ("upstream unavailable", "serverOverloaded", True),
    ("upstream unavailable", {"httpConnectionFailed": {"httpStatusCode": 503}}, False),
    ('upstream {"error":{"code":"server_is_overloaded"}}', {"httpConnectionFailed": {"httpStatusCode": 503}}, True),
    ('upstream {"error":{"code":"insufficient_quota"}}', {"httpConnectionFailed": {"httpStatusCode": 503}}, False),
    ('upstream {"error":{"code":"server_is_overloaded"}}', {"httpConnectionFailed": {"httpStatusCode": 500}}, False),
    ("not enough codex agent capacity", None, False),
    ("quota reached", "usageLimitExceeded", False),
    ("login required", "unauthorized", False),
    ("invalid schema", "badRequest", False),
])
def test_final_sdk_failure_preserves_metadata_and_only_classifies_model_capacity(message: str, info: object, capacity: bool) -> None:
    failure = TurnError.model_validate({"message": message, "codexErrorInfo": info, "additionalDetails": "upstream detail"})
    event = _notification("turn/completed", turn=SimpleNamespace(id="turn-1", status=_enum("failed"), error=failure))
    handle = SimpleNamespace(id="turn-1", stream=lambda: iter([event]))
    with pytest.raises(CodexSdkError) as caught:
        _collect_turn_result(handle, lambda _: None, lambda: None)
    assert str(caught.value) == message
    assert caught.value.model_capacity is capacity
    assert caught.value.error_info == info
    assert caught.value.additional_details == "upstream detail"


@pytest.mark.parametrize("message", [
    "Selected model is at capacity. Please try a different model.",
    "exceeded retry limit, last status: 429 Too Many Requests",
    "usageLimitExceeded",
])
def test_retry_error_is_diagnostic_only_until_terminal_status_and_real_activity(message: str) -> None:
    retry = _notification(
        "error", turn_id="turn-1", will_retry=True, error=TurnError(message=message)
    )
    client = FakeTurnHandle(events=[_notification("turn/started"), retry, retry])
    activity: list[bool] = []
    progress: list[CodexSdkProgress] = []
    diagnostics: list[dict[str, object]] = []
    result = _collect_turn_result(client, progress.append, lambda: activity.append(True), diagnostic_callback=diagnostics.append)
    assert result.final_response == "structured plan"
    assert len(activity) == 4  # start, final message start/completion, terminal completion
    assert len(diagnostics) == 2
    assert all(event["will_retry"] is True and event["event"] == "turn-error" for event in diagnostics)
    assert [item.phase for item in progress] == ["turn_started", "writing_response", "writing_response", "response_received"]


@pytest.mark.parametrize(("message", "info", "details", "expected"), [
    ("exceeded retry limit, last status: 429 Too Many Requests", None, None, "rate"),
    ("upstream failed", "rateLimitExceeded", None, "rate"),
    ("upstream failed", {"responseTooManyFailedAttempts": {"httpStatusCode": 429}}, None, "rate"),
    ("upstream failed", {"httpConnectionFailed": {"httpStatusCode": 429}}, None, "rate"),
    ("HTTP/1.1 429", None, None, "rate"),
    ("upstream failed", None, '{"error":{"code":"slow_down"}}', "rate"),
    ("Rate limit reached for requests", None, None, "rate"),
    ("exceeded retry limit, last status: 429 Too Many Requests", "usageLimitExceeded", None, "usage"),
    ("HTTP 429", None, '{"error":{"type":"insufficient_quota"}}', "usage"),
    ("upstream failed", None, '{"error":{"code":"credit_balance_exhausted"}}', "usage"),
    ("upstream failed", None, '{"error":{"code":"organization_spend_limit_exceeded"}}', "usage"),
    ("upstream failed", None, '{"error":{"code":"project_spend_limit_exceeded"}}', "usage"),
    ("upstream failed", None, '{"error":{"code":"organization_usage_limit_exceeded"}}', "usage"),
    ("You've hit your usage limit", None, None, "usage"),
    ("You exceeded your current quota", None, None, "usage"),
    ("HTTP 503", {"httpConnectionFailed": {"httpStatusCode": 503}}, None, ""),
    ("unauthorized", "unauthorized", None, ""),
    ("schema invalid at line 429", "badRequest", None, ""),
    ("exceeded retry limit, last status: 500", None, None, ""),
    ("HTTP 4290", None, None, ""),
    ("not enough codex agent capacity", None, None, ""),
    ("session budget reached", "sessionBudgetExceeded", None, ""),
])
def test_terminal_request_limits_keep_original_evidence(message: str, info: object, details: str | None, expected: str) -> None:
    failure = TurnError.model_validate({"message": message, "codexErrorInfo": info, "additionalDetails": details})
    event = _notification("turn/completed", turn=SimpleNamespace(id="turn-1", status=_enum("failed"), error=failure))
    handle = SimpleNamespace(id="turn-1", stream=lambda: iter([event]))
    with pytest.raises(CodexSdkError) as caught:
        _collect_turn_result(handle, lambda _: None, lambda: None)
    assert caught.value.request_limit == expected
    assert str(caught.value) == message
    assert caught.value.error_info == info
    assert caught.value.additional_details == details


def test_error_notifications_cannot_keep_an_idle_turn_alive(tmp_path: Path) -> None:
    retry = _notification(
        "error", turn_id="turn-1", will_retry=True, error=TurnError(message="Selected model is at capacity. Please try a different model.")
    )
    handle = FakeTurnHandle(events=[retry] * 12, event_delay_seconds=0.02)
    client = FakeCodex(handle)
    manager = CodexSdkManager(client_factory=FakeClientFactory([client]))  # type: ignore[arg-type]
    with pytest.raises(CodexSdkTimeout):
        manager.run_turn(request(tmp_path, timeout=0.08))
    manager.close()
    assert handle.interrupt_count == 1
    records = [json.loads(line) for line in (tmp_path / "planning.log").read_text(encoding="utf-8").splitlines()]
    assert any(record.get("event") == "turn-error" and record["will_retry"] for record in records)
    assert not any(record.get("event") == "turn-completed" for record in records)


def test_final_failure_log_preserves_structured_error_and_additional_details(tmp_path: Path) -> None:
    failure = TurnError.model_validate({"message": "upstream overloaded", "codexErrorInfo": "serverOverloaded", "additionalDetails": "server detail"})
    event = _notification("turn/completed", turn=SimpleNamespace(id="turn-1", status=_enum("failed"), error=failure))
    handle = FakeTurnHandle()
    handle.stream = lambda: iter([event])
    manager = CodexSdkManager(client_factory=FakeClientFactory([FakeCodex(handle)]))  # type: ignore[arg-type]
    with patch.object(manager, "_wait_for_retry", return_value=True), pytest.raises(CodexSdkError) as caught:
        manager.run_turn(request(tmp_path))
    manager.close()
    assert caught.value.model_capacity
    records = [json.loads(line) for line in (tmp_path / "planning.log").read_text(encoding="utf-8").splitlines()]
    failed = next(record for record in records if record.get("event") == "turn-failed")
    assert failed["error"] == "upstream overloaded"
    assert failed["codex_error_info"] == "serverOverloaded"
    assert failed["additional_details"] == "server detail"


def test_sdk_transport_failure_keeps_original_exception_cause(tmp_path: Path) -> None:
    source = RuntimeError("transport closed")
    manager = CodexSdkManager(client_factory=FakeClientFactory([FakeCodex(FakeTurnHandle(error=source))]))  # type: ignore[arg-type]
    with pytest.raises(CodexSdkError) as caught:
        manager.run_turn(request(tmp_path))
    manager.close()
    assert caught.value.__cause__ is source


def test_turn_timeout_interrupts_and_discards_client(tmp_path: Path) -> None:
    first_handle = FakeTurnHandle(blocked=True)
    first = FakeCodex(first_handle)
    second = FakeCodex()
    factory = FakeClientFactory([first, second])
    manager = CodexSdkManager(client_factory=factory)  # type: ignore[arg-type]

    with pytest.raises(CodexSdkTimeout, match="timed out"):
        manager.run_turn(request(tmp_path, timeout=0.05, conversation_id="planning:run-timeout"))
    assert first_handle.released.wait(timeout=1)
    assert first_handle.interrupt_count == 1
    assert first.close_count == 1
    assert '"timeout_kind": "inactivity"' in (tmp_path / "planning.log").read_text(encoding="utf-8")

    assert manager.run_turn(request(tmp_path, conversation_id="planning:run-timeout")) == "structured plan"
    manager.close_conversation("planning:run-timeout")
    manager.close()
    assert factory.call_count == 2


def test_user_stop_interrupts_only_the_owned_sdk_turn(tmp_path: Path) -> None:
    handle = FakeTurnHandle(blocked=True)
    client = FakeCodex(handle)
    manager = CodexSdkManager(client_factory=FakeClientFactory([client]))  # type: ignore[arg-type]
    signal = threading.Event()
    worker = threading.Thread(target=lambda: (handle.started.wait(timeout=1), signal.set()))
    worker.start()

    with pytest.raises(ExecutionStopped, match="중지"):
        manager.run_turn(request(tmp_path, cancel_signal=signal))

    worker.join(timeout=1)
    assert handle.interrupt_count == 1
    assert client.close_count == 1
    assert '"event": "turn-stopped"' in (tmp_path / "planning.log").read_text(encoding="utf-8")


def test_account_display_uses_public_sdk_types_and_drops_previous_account_on_refresh_failure() -> None:
    from openai_codex.types import GetAccountResponse

    client = FakeCodex()
    client.account_response = GetAccountResponse.model_validate({
        "account": {"type": "chatgpt", "email": "fixture-account@example.invalid", "planType": "pro"}, "requiresOpenaiAuth": True,
    })
    manager = CodexSdkManager(client_factory=FakeClientFactory([client]))  # type: ignore[arg-type]
    first = manager.login_status()
    assert (first.account_email, first.plan_type, first.auth_method) == ("fixture-account@example.invalid", "pro", "chatgpt")
    assert first.account_email not in repr(first)
    client.account_response = _account_response("chatgpt", email="next-account@example.invalid", plan_type="plus")
    assert manager.login_status().account_email == "next-account@example.invalid"
    for account_type in ("apiKey", "amazonBedrock", None):
        client.account_response = _account_response(account_type)
        state = manager.login_status()
        assert state.account_email == "" and state.plan_type == ""
    client.account_response = _account_response("chatgpt", email=None, plan_type=None)
    missing = manager.login_status()
    assert missing.status == "connected" and missing.account_email == "" and missing.plan_type == ""
    client.account_error = RuntimeError("account failure must not be displayed")
    failed = manager.login_status()
    assert failed.status == "status_error" and failed.account_email == "" and failed.plan_type == ""
    assert "account failure" not in failed.message
    manager.close()


def test_api_key_login_switches_subscription_and_discards_stale_status_client() -> None:
    old, login, fresh = FakeCodex(), FakeCodex(), FakeCodex()
    fresh.account_response = _account_response("apiKey")
    factory = FakeClientFactory([old, login, fresh])
    manager = CodexSdkManager(client_factory=factory)  # type: ignore[arg-type]
    assert manager.login_status().auth_method == "chatgpt"
    state = manager.login_api_key(" sk-fixture-only ", "key-request")
    assert (state.status, state.auth_method, state.account_email, state.plan_type) == ("connected", "api_key", "", "")
    assert "실제 인증" in state.message
    assert "sk-fixture-only" not in repr(state) and "sk-fixture-only" not in repr(manager.__dict__)
    assert old.close_count == 1 and login.close_count == 1
    assert login.api_key_login_count == 1
    assert manager.login_api_key("sk-fixture-only", "key-request") == state
    assert factory.call_count == 2 and login.api_key_login_count == 1
    assert manager.login_status().auth_method == "api_key"
    manager.close()
    assert manager._api_key_login_result is None


@pytest.mark.parametrize("value", ["", "  ", "sk-fixture\nprivate", "sk-fixture\r", "\x00private", "sk private", "키", "s" * 4097])
def test_api_key_login_rejects_invalid_input_without_starting_runtime(value: str) -> None:
    factory = FakeClientFactory([])
    manager = CodexSdkManager(client_factory=factory)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="한 줄"):
        manager.login_api_key(value, "key-request")
    assert factory.call_count == 0
    manager.close()


@pytest.mark.parametrize("value", ["", "id\nprivate", "x" * 129])
def test_api_key_login_rejects_invalid_request_id(value: str) -> None:
    manager = CodexSdkManager(client_factory=FakeClientFactory([]))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="request ID"):
        manager.login_api_key("sk-fixture-only", value)
    manager.close()


@pytest.mark.parametrize("phase", ["runtime", "login", "account", "wrong_method"])
def test_api_key_login_failures_remain_failure_without_secret_payload(phase: str) -> None:
    client = FakeCodex()
    error = RuntimeError("sk-fixture-only credential payload")
    with patch.object(client, "login_api_key", side_effect=error if phase == "login" else None):
        if phase == "account":
            client.account_error = error
        factory = FakeClientFactory([client])
        manager = CodexSdkManager(client_factory=factory)  # type: ignore[arg-type]
        with patch.object(manager, "_new_dedicated_client", side_effect=error if phase == "runtime" else None, return_value=client):
            state = manager.login_api_key("sk-fixture-only", "key-request")
        assert state.status == "failed" and state.error_code
        assert state.account_email == "" and state.plan_type == ""
        assert "sk-fixture-only" not in repr(state) and "credential payload" not in repr(state)
        assert client.close_count == (0 if phase == "runtime" else 1)
        manager.close()


def test_api_key_login_does_not_overlap_pending_browser_login() -> None:
    status, login = FakeCodex(), FakeCodex(login_handle=FakeLoginHandle())
    status.account_response = _account_response(None)
    factory = FakeClientFactory([status, login])
    manager = CodexSdkManager(client_factory=factory)  # type: ignore[arg-type]
    try:
        started = manager.start_login("browser", "browser-request")
        state = manager.login_api_key("sk-fixture-only", "key-request")
        assert state.attempt_id == started.attempt_id and state.status == "waiting"
        assert "완료하거나 취소" in state.message
        assert login.api_key_login_count == 0 and factory.call_count == 2
    finally:
        manager.close()


def test_browser_login_can_replace_api_key_authentication() -> None:
    status, login = FakeCodex(), FakeCodex(login_handle=FakeLoginHandle())
    status.account_response = _account_response("apiKey")
    manager = CodexSdkManager(client_factory=FakeClientFactory([status, login]))  # type: ignore[arg-type]
    try:
        state = manager.start_login("browser", "switch-to-chatgpt")
        assert state.status == "waiting" and state.auth_method == "none"
        assert login.browser_login_count == 1
    finally:
        manager.close()


@pytest.mark.parametrize("field,value", [("email", 3), ("email", "not-safe\n@example.invalid"), ("plan_type", ["pro"])])
def test_malformed_account_metadata_fails_without_exposing_values(field: str, value: object) -> None:
    client = FakeCodex()
    client.account_response = _account_response("chatgpt", **{field: value})
    manager = CodexSdkManager(client_factory=FakeClientFactory([client]))  # type: ignore[arg-type]
    state = manager.login_status()
    assert state.status == "status_error"
    assert state.error_code == "auth_response_incompatible"
    assert state.account_email == "" and state.plan_type == ""
    manager.close()


def test_discard_idle_clients_closes_only_clients_without_active_conversations(tmp_path: Path) -> None:
    conversation_client = FakeCodex()
    idle_client = FakeCodex()
    manager = CodexSdkManager(
        client_factory=FakeClientFactory([conversation_client, idle_client])  # type: ignore[arg-type]
    )
    assert manager.run_turn(request(tmp_path, conversation_id="planning:run-1")) == "structured plan"
    assert manager.run_turn(request(tmp_path)) == "structured plan"

    manager.discard_idle_clients()

    assert idle_client.close_count == 1
    assert conversation_client.close_count == 0
    assert manager.has_conversation(
        "planning:run-1",
        cwd=tmp_path,
        model="gpt-test",
        sandbox_mode="read-only",
        approval_mode="deny-all",
    )
    manager.close()
    assert conversation_client.close_count == 1


def test_manager_browser_login_is_idempotent_and_confirms_account() -> None:
    status_client = FakeCodex()
    status_client.account_response = _account_response(None)
    handle = FakeLoginHandle()
    login_client = FakeCodex(login_handle=handle)
    login_client.account_response = _account_response("chatgpt")
    manager = CodexSdkManager(client_factory=FakeClientFactory([status_client, login_client]))  # type: ignore[arg-type]

    started = manager.start_login("browser", "request-1")
    duplicate = manager.start_login("browser", "request-1")

    assert started.status == "waiting"
    assert started.attempt_id == duplicate.attempt_id
    assert started.auth_url.startswith("https://auth.openai.com/")
    assert login_client.browser_login_count == 1
    assert handle.started.wait(timeout=1)
    status_client.account_response = login_client.account_response
    handle.released.set()
    for _ in range(100):
        completed = manager.login_attempt(started.attempt_id)
        if completed.status == "connected":
            break
        time.sleep(0.01)
    assert completed.status == "connected"
    assert completed.auth_url == ""
    assert completed.user_code == ""
    assert (completed.account_email, completed.plan_type) == ("private@example.com", "plus")
    status_client.account_response = _account_response("chatgpt", email="new-after-login@example.invalid", plan_type="pro")
    assert manager.login_attempt(started.attempt_id).account_email == "new-after-login@example.invalid"
    status_client.account_response = _account_response("apiKey")
    changed = manager.login_attempt(started.attempt_id)
    assert changed.auth_method == "api_key" and changed.account_email == "" and changed.plan_type == ""
    assert "hidden" not in completed.message
    manager.close()


@pytest.mark.parametrize("method", ["browser", "device_code"])
def test_explicit_login_starts_on_fresh_client_after_account_preflight_failure(method: str) -> None:
    from openai_codex import TransportClosedError

    stale = FakeCodex()
    stale.account_error = TransportClosedError("closed auth transport with private-value")
    handle = FakeLoginHandle(device_code=method == "device_code")
    login = FakeCodex(login_handle=handle)
    factory = FakeClientFactory([stale, login, FakeCodex()])
    manager = CodexSdkManager(client_factory=factory)  # type: ignore[arg-type]
    try:
        started = manager.start_login(method, "request-recovery")
        assert started.status == "waiting"
        assert "새 인증 연결" in started.message
        assert "private-value" not in started.message
        assert stale.close_count == 1
        assert factory.call_count == 2
        assert manager.start_login(method, "request-recovery").attempt_id == started.attempt_id
        assert manager.start_login(method, "another-click").attempt_id == started.attempt_id
        assert login.browser_login_count + login.device_login_count == 1
        handle.released.set()
        for _ in range(100):
            completed = manager.login_attempt(started.attempt_id)
            if completed.status == "connected":
                break
            time.sleep(0.01)
        assert completed.status == "connected"
        assert completed.auth_url == "" and completed.user_code == ""
    finally:
        handle.released.set()
        manager.close()


@pytest.mark.parametrize("error,code", [
    (PermissionError("private-value"), "auth_permission_denied"),
    (FileNotFoundError("private-value"), "auth_runtime_missing"),
    (TimeoutError("private-value"), "auth_request_timeout"),
    (ConnectionError("private-value"), "auth_transport_closed"),
])
def test_auth_status_preserves_failure_category_without_exception_payload(error: Exception, code: str) -> None:
    client = FakeCodex()
    client.account_error = error
    manager = CodexSdkManager(client_factory=FakeClientFactory([client]))  # type: ignore[arg-type]
    try:
        state = manager.login_status()
        assert state.status == "status_error" and state.error_code == code
        assert "private-value" not in state.message
        assert state.account_email == "" and state.plan_type == ""
    finally:
        manager.close()


def test_new_login_runtime_failure_is_classified_after_failed_preflight_without_opening_login() -> None:
    from openai_codex import TransportClosedError

    stale = FakeCodex()
    stale.account_error = RuntimeError("private preflight failure")
    factory_calls = 0

    def factory():
        nonlocal factory_calls
        factory_calls += 1
        if factory_calls == 1:
            return stale
        raise TransportClosedError("Codex process closed stdout: 액세스가 거부되었습니다 private-value")

    manager = CodexSdkManager(client_factory=factory)  # type: ignore[arg-type]
    try:
        state = manager.start_login("browser", "runtime-failed")
        assert state.status == "runtime_error" and state.error_code == "auth_permission_denied"
        assert "접근할 수 없습니다" in state.message
        assert "private" not in state.message and state.auth_url == ""
        assert stale.browser_login_count == 0
    finally:
        manager.close()


@pytest.mark.parametrize("method", ["browser", "device_code"])
def test_login_start_failure_after_failed_preflight_closes_client_and_preserves_safe_cause(method: str) -> None:
    stale = FakeCodex()
    stale.account_error = RuntimeError("private preflight failure")
    login = FakeCodex()
    manager = CodexSdkManager(client_factory=FakeClientFactory([stale, login]))  # type: ignore[arg-type]
    login_method = "login_chatgpt" if method == "browser" else "login_chatgpt_device_code"
    try:
        with patch.object(login, login_method, side_effect=TimeoutError("private login payload")) as start:
            state = manager.start_login(method, "start-failed")
        start.assert_called_once()
        assert state.status == "failed" and state.error_code == "auth_request_timeout"
        assert state.method == method and state.attempt_id == "" and state.auth_url == ""
        assert "private" not in state.message
        assert login.close_count == 1
    finally:
        manager.close()


def test_login_finish_distinguishes_account_confirmation_failure_from_browser_failure() -> None:
    status = FakeCodex()
    status.account_response = _account_response(None)
    handle = FakeLoginHandle()
    login = FakeCodex(login_handle=handle)
    login.account_error = RuntimeError("private account read failure")
    manager = CodexSdkManager(client_factory=FakeClientFactory([status, login]))  # type: ignore[arg-type]
    try:
        started = manager.start_login("browser", "confirmation-failed")
        handle.released.set()
        for _ in range(100):
            completed = manager.login_attempt(started.attempt_id)
            if completed.status == "failed":
                break
            time.sleep(0.01)
        assert completed.error_code == "account_status_failed"
        assert "계정 연결을 확인하지 못했습니다" in completed.message
        assert "private" not in completed.message
        assert completed.auth_url == "" and completed.user_code == ""
    finally:
        handle.released.set()
        manager.close()


def test_manager_device_login_can_be_cancelled_without_logging_out() -> None:
    status_client = FakeCodex()
    status_client.account_response = _account_response(None)
    handle = FakeLoginHandle(device_code=True)
    login_client = FakeCodex(login_handle=handle)
    login_client.account_response = _account_response(None)
    manager = CodexSdkManager(client_factory=FakeClientFactory([status_client, login_client]))  # type: ignore[arg-type]

    started = manager.start_login("device_code", "request-device")
    cancelling = manager.cancel_login(started.attempt_id)

    assert started.user_code == "ABCD-EFGH"
    assert cancelling.status in {"cancelling", "cancelled"}
    for _ in range(100):
        completed = manager.login_attempt(started.attempt_id)
        if completed.status == "cancelled":
            break
        time.sleep(0.01)
    assert completed.status == "cancelled"
    assert handle.cancel_count == 1
    assert login_client.device_login_count == 1
    assert completed.user_code == ""
    manager.close()


def test_manager_marks_unconfirmed_login_cancellation_unknown() -> None:
    status_client = FakeCodex()
    status_client.account_response = _account_response(None)
    handle = FakeLoginHandle(release_on_cancel=False)
    login_client = FakeCodex(login_handle=handle)
    manager = CodexSdkManager(client_factory=FakeClientFactory([status_client, login_client]))  # type: ignore[arg-type]

    started = manager.start_login("browser", "request-cancel-timeout")
    with patch("ai_orchestrator.codex_sdk._LOGIN_CANCEL_CONFIRM_TIMEOUT_SECONDS", 0.01):
        manager.cancel_login(started.attempt_id)
        for _ in range(100):
            unknown = manager.login_attempt(started.attempt_id)
            if unknown.status == "unknown":
                break
            time.sleep(0.01)

    assert unknown.status == "unknown"
    assert unknown.error_code == "cancel_unconfirmed"
    assert unknown.auth_url == ""
    assert manager.login_status().status == "unknown"
    manager.close()


def test_manager_closes_active_login_client_and_hides_sdk_failure() -> None:
    status_client = FakeCodex()
    status_client.account_response = _account_response(None)
    handle = FakeLoginHandle(error=RuntimeError("https://auth.openai.com/?token=private"))
    login_client = FakeCodex(login_handle=handle)
    manager = CodexSdkManager(client_factory=FakeClientFactory([status_client, login_client]))  # type: ignore[arg-type]

    started = manager.start_login("browser", "request-failure")
    handle.released.set()
    for _ in range(100):
        failed = manager.login_attempt(started.attempt_id)
        if failed.status == "failed":
            break
        time.sleep(0.01)
    assert failed.status == "failed"
    assert "private" not in failed.message
    assert failed.error_code == "login_failed"
    manager.close()
    assert login_client.close_count >= 1


def test_stream_activity_extends_timeout_until_turn_completes(tmp_path: Path) -> None:
    heartbeat = _notification("item/agentMessage/delta", turn_id="turn-1", item_id="message-1", delta="partial")
    handle = FakeTurnHandle(events=[heartbeat, heartbeat, heartbeat, heartbeat], event_delay_seconds=0.04)
    client = FakeCodex(handle)
    manager = CodexSdkManager(client_factory=FakeClientFactory([client]))  # type: ignore[arg-type]

    assert manager.run_turn(request(tmp_path, timeout=0.1)) == "structured plan"
    manager.close()

    assert handle.interrupt_count == 0


def test_concurrent_turns_use_separate_clients(tmp_path: Path) -> None:
    first_handle = FakeTurnHandle(response="first", blocked=True)
    second_handle = FakeTurnHandle(response="second", blocked=True)
    first = FakeCodex(first_handle)
    second = FakeCodex(second_handle)
    factory = FakeClientFactory([first, second])
    manager = CodexSdkManager(client_factory=factory)  # type: ignore[arg-type]
    results: list[str] = []

    first_worker = threading.Thread(target=lambda: results.append(manager.run_turn(request(tmp_path))))
    second_worker = threading.Thread(target=lambda: results.append(manager.run_turn(request(tmp_path))))
    first_worker.start()
    assert first_handle.started.wait(timeout=1)
    second_worker.start()
    assert second_handle.started.wait(timeout=1)
    first_handle.released.set()
    second_handle.released.set()
    first_worker.join(timeout=1)
    second_worker.join(timeout=1)
    manager.close()

    assert sorted(results) == ["first", "second"]
    assert factory.call_count == 2
