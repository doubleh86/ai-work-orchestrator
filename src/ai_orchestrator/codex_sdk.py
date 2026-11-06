from __future__ import annotations

import json
import math
import os
import platform
import random
import re
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from .app_paths import application_config_root
from .execution_control import CancellationSignal, ExecutionStopped
from .usage import CodexUsageTracker, TokenCounts, UsageObservation

if TYPE_CHECKING:
    from openai_codex import ApprovalMode, Codex, Sandbox, Thread as CodexThread, TurnHandle, TurnResult
    from openai_codex.types import Notification, ThreadItem, ThreadTokenUsage, Turn

from . import __version__


class CodexSdkError(RuntimeError):
    def __init__(self, message: str, *, error_info: object = None, additional_details: str | None = None) -> None:
        super().__init__(message)
        self.error_info = _json_value(error_info)
        self.additional_details = additional_details
        details = f"{message}\n{additional_details or ''}\n{json.dumps(self.error_info)}"
        usage_limit = bool(re.search(
            r"\b(?:usageLimitExceeded|usage_limit_exceeded|insufficient_quota|credit_balance_exhausted|"
            r"organization_spend_limit_exceeded|project_spend_limit_exceeded|organization_usage_limit_exceeded)\b"
            r"|\byou(?:'ve| have) (?:hit|reached) your usage limit\b|\byou exceeded your current quota\b", details, re.IGNORECASE,
        ))
        limited_http = isinstance(self.error_info, dict) and any(
            isinstance(value, dict) and value.get("httpStatusCode") == 429
            for kind, value in self.error_info.items()
            if kind in {"httpConnectionFailed", "responseStreamConnectionFailed", "responseStreamDisconnected", "responseTooManyFailedAttempts"}
        )
        rate_limit = limited_http or bool(re.search(
            r"\b(?:rateLimitExceeded|rate_limit_exceeded|rate_limit_error|slow_down)\b"
            r"|\brate limit (?:reached|exceeded)\b|\b(?:last status:\s*|HTTP(?:/\d(?:\.\d)?)?\s+)429\b"
            r"|\b429\s+Too Many Requests\b", details, re.IGNORECASE,
        ))
        self.request_limit = "usage" if usage_limit else "rate" if rate_limit else ""
        overload_http = isinstance(self.error_info, dict) and any(
            isinstance(value, dict) and value.get("httpStatusCode") == 503
            for kind, value in self.error_info.items()
            if kind in {"httpConnectionFailed", "responseStreamConnectionFailed", "responseStreamDisconnected", "responseTooManyFailedAttempts"}
        )
        self.model_capacity = (
            "selected model is at capacity. please try a different model." in message.casefold()
            or self.error_info in ("serverOverloaded", "server_overloaded")
            or overload_http and bool(re.search(r'"code"\s*:\s*"server_is_overloaded"', f"{message}\n{additional_details or ''}"))
        )
        self.service_unavailable = not self.request_limit and (overload_http or self.model_capacity or bool(re.search(
            r"\b(?:last status:\s*|HTTP(?:/\d(?:\.\d)?)?\s+)503\b|\b503\s+Service Unavailable\b", details, re.IGNORECASE,
        )))
        self.retry_after_seconds = _retry_after_seconds(self.error_info, additional_details)
        self.retry_safe = False


class CodexSdkTimeout(CodexSdkError):
    pass


_LOGIN_CANCEL_CONFIRM_TIMEOUT_SECONDS = 10.0
_PROVIDER_RETRY_DELAYS = (5.0, 15.0, 30.0, 60.0)
_PROVIDER_RETRY_WAIT_BUDGET = 300.0


def _auth_failure(error: BaseException, default_code: str, default_message: str) -> tuple[str, str]:
    """Return fixed diagnostic copy without SDK messages or credential payloads."""
    chain: list[BaseException] = []
    current: BaseException | None = error
    while current is not None and len(chain) < 8 and all(current is not previous for previous in chain):
        chain.append(current)
        current = current.__cause__ or current.__context__
    if any(isinstance(item, PermissionError) or getattr(item, "winerror", None) == 5 or getattr(item, "errno", None) in {1, 13}
           or re.search(r"access is denied|permission denied|액세스가 거부|접근이 거부", str(item), re.IGNORECASE) for item in chain):
        return "auth_permission_denied", "Codex 인증 실행에 필요한 파일이나 폴더에 접근할 수 없습니다. 앱 실행 권한과 보안 프로그램의 차단 여부를 확인해 주세요."
    if any(isinstance(item, FileNotFoundError) for item in chain):
        return "auth_runtime_missing", "Codex 실행 파일을 찾지 못했습니다. 작업 PC에 Codex CLI를 설치하고 앱을 다시 열어 주세요."
    if any(isinstance(item, TimeoutError) or re.search(r"timed? out|timeout", str(item), re.IGNORECASE) for item in chain):
        return "auth_request_timeout", "Codex 인증 요청의 응답 시간이 초과되었습니다. 네트워크와 실행 상태를 확인한 뒤 다시 시도해 주세요."
    if any(type(item).__name__ in {"ValidationError", "ParseError", "InvalidParamsError", "MethodNotFoundError"}
           or str(item) == "invalid Codex account display metadata" for item in chain):
        return "auth_response_incompatible", "Codex 인증 응답 형식이 앱과 맞지 않습니다. Python SDK와 앱의 호환 상태를 확인해 주세요."
    if any(type(item).__name__ == "TransportClosedError" or isinstance(item, (BrokenPipeError, ConnectionError)) for item in chain):
        return "auth_transport_closed", "Codex 인증 프로세스와의 연결이 끊겼습니다. 다시 로그인해 주세요. 계속되면 앱 실행 환경을 확인해 주세요."
    return default_code, default_message


def _retry_after_seconds(error_info: object, additional_details: str | None) -> float | None:
    values: list[object] = []

    def collect(value: object) -> None:
        if not isinstance(value, dict):
            return
        for key, item in value.items():
            if str(key).casefold().replace("_", "-") == "retry-after":
                values.append(item)
            elif isinstance(item, dict):
                collect(item)

    collect(error_info)
    if additional_details:
        try:
            collect(json.loads(additional_details))
        except (ValueError, TypeError):
            pass
        values.extend(re.findall(r"(?im)^Retry-After:\s*([^\r\n]+)", additional_details))
    delays: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            continue
        try:
            delay = float(value)
        except ValueError:
            try:
                date = parsedate_to_datetime(str(value))
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                delay = (date - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError, OverflowError):
                continue
        if math.isfinite(delay) and delay >= 0:
            delays.append(delay)
    return max(delays) if delays else None


@dataclass(frozen=True, slots=True)
class CodexSdkAccountStatus:
    authenticated: bool
    auth_method: str
    label: str
    account_email: str = field(default="", repr=False)
    plan_type: str = field(default="", repr=False)


@dataclass(frozen=True, slots=True)
class CodexSdkLoginState:
    status: str
    attempt_id: str = ""
    method: str = ""
    started_at: str = ""
    auth_method: str = "none"
    auth_label: str = "로그인 필요"
    auth_url: str = ""
    user_code: str = ""
    error_code: str = ""
    message: str = ""
    account_email: str = field(default="", repr=False)
    plan_type: str = field(default="", repr=False)


@dataclass(frozen=True, slots=True)
class CodexSdkProgress:
    phase: str
    detail: str = ""
    attempt_id: str = ""
    invocation_id: str = ""
    turn_id: str = ""
    item_id: str = ""
    received_at: str = ""
    event_seq: int = 0
    activity_changed: bool = True
    evidence_kind: str = "activity_change"
    log_report: bool = True


@dataclass(frozen=True, slots=True)
class CodexSdkExecutionProfile:
    model: str
    reasoning_effort: str
    model_automatic: bool
    reasoning_effort_automatic: bool


@dataclass(frozen=True, slots=True)
class CodexSdkTurnRequest:
    cwd: Path
    prompt: str
    log_path: Path
    model: str = ""
    reasoning_effort: str = ""
    sandbox_mode: str = "read-only"
    approval_mode: str = "deny-all"
    timeout_seconds: float = 600
    conversation_id: str = ""
    attempt_id: str = ""
    invocation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    cancel_signal: CancellationSignal | None = field(default=None, compare=False, repr=False)
    progress_callback: Callable[[CodexSdkProgress], None] | None = field(default=None, compare=False, repr=False)
    profile_callback: Callable[[CodexSdkExecutionProfile], None] | None = field(default=None, compare=False, repr=False)
    usage_callback: Callable[[UsageObservation], None] | None = field(default=None, compare=False, repr=False)
    retry_callback: Callable[[str | None], None] | None = field(default=None, compare=False, repr=False)


@dataclass(slots=True)
class _TurnOperation:
    completed: threading.Event = field(default_factory=threading.Event)
    cancelled: threading.Event = field(default_factory=threading.Event)
    state_lock: threading.Lock = field(default_factory=threading.Lock)
    log_lock: threading.Lock = field(default_factory=threading.Lock)
    client: Codex | None = None
    handle: TurnHandle | None = None
    result: str = ""
    error: CodexSdkError | None = None
    last_activity_at: float = field(default_factory=time.monotonic)
    retry_until: float = 0.0

    def set_client(self, client: Codex) -> None:
        with self.state_lock:
            self.client = client

    def set_handle(self, handle: TurnHandle | None) -> None:
        with self.state_lock:
            self.handle = handle

    def current_client_and_handle(self) -> tuple[Codex | None, TurnHandle | None]:
        with self.state_lock:
            return self.client, self.handle

    def mark_activity(self) -> None:
        with self.state_lock:
            self.last_activity_at = time.monotonic()

    def remaining_idle_seconds(self, timeout_seconds: float) -> float:
        with self.state_lock:
            if self.retry_until:
                return max(0.0, self.retry_until - time.monotonic()) + timeout_seconds
            return timeout_seconds - (time.monotonic() - self.last_activity_at)


@dataclass(slots=True)
class _LoginOperation:
    attempt_id: str
    request_id: str
    method: str
    started_at: str
    client: Codex
    handle: object
    auth_url: str
    user_code: str = ""
    status: str = "waiting"
    auth_method: str = "none"
    auth_label: str = "로그인 필요"
    error_code: str = ""
    message: str = ""
    cancel_requested: bool = False
    account_email: str = field(default="", repr=False)
    plan_type: str = field(default="", repr=False)


@dataclass(slots=True)
class _SdkConversation:
    client: Codex
    thread: CodexThread
    cwd: str
    model: str
    reasoning_effort: str
    execution_profile: CodexSdkExecutionProfile
    sandbox_mode: str
    approval_mode: str
    turn_lock: threading.Lock = field(default_factory=threading.Lock)
    usage_total: TokenCounts | None = field(default_factory=lambda: TokenCounts(0, 0, 0, 0, 0, 0))
    usage_epoch: str = field(default_factory=lambda: str(uuid.uuid4()))

    def matches(self, *, cwd: Path, model: str, sandbox_mode: str, approval_mode: str, reasoning_effort: str | None = None) -> bool:
        return (
            self.cwd == str(cwd.resolve())
            and self.model == model
            and (reasoning_effort is None or self.reasoning_effort == reasoning_effort)
            and self.sandbox_mode == sandbox_mode
            and self.approval_mode == approval_mode
        )


class CodexSdkManager:
    def __init__(self, client_factory: Callable[[], Codex] | None = None) -> None:
        self._client_factory = client_factory or _new_client
        self._idle_clients: list[Codex] = []
        self._active_clients: set[Codex] = set()
        self._conversations: dict[str, _SdkConversation] = {}
        self._conversation_lock = threading.Lock()
        self._login_lock = threading.Lock()
        self._login_operation: _LoginOperation | None = None
        self._api_key_login_result: tuple[str, CodexSdkLoginState] | None = None
        self._lock = threading.Lock()
        self._closed = False

    def account_status(self) -> CodexSdkAccountStatus:
        client = self._acquire_client()
        healthy = False
        try:
            response = client.account(refresh_token=False)
            status = _account_status(response)
            healthy = True
            return status
        except Exception as exc:
            raise CodexSdkError("failed to read Codex SDK account status") from exc
        finally:
            if healthy:
                self._release_client(client)
            else:
                self._discard_client(client)

    def login_status(self) -> CodexSdkLoginState:
        with self._login_lock:
            operation = self._login_operation
            if operation is not None and operation.status in {"waiting", "cancelling"}:
                return self._login_snapshot(operation)
        try:
            account = self.account_status()
        except CodexSdkError as error:
            if operation is not None and operation.status in {"failed", "cancelled"}:
                return self._login_snapshot(operation)
            code, message = _auth_failure(error, "account_status_failed", "Codex 연결 상태를 확인하지 못했습니다.")
            return CodexSdkLoginState(status="status_error", error_code=code, message=message)
        if account.authenticated:
            if operation is not None:
                with self._login_lock:
                    if self._login_operation is operation:
                        operation.status = "connected"
                        operation.auth_method = account.auth_method
                        operation.auth_label = account.label
                        operation.account_email = account.account_email
                        operation.plan_type = account.plan_type
                        operation.error_code = ""
                        operation.message = "Codex 연결이 완료됐습니다."
                        operation.auth_url = ""
                        operation.user_code = ""
            return CodexSdkLoginState(
                status="connected",
                auth_method=account.auth_method,
                auth_label=account.label,
                message="Codex 연결이 완료됐습니다.",
                account_email=account.account_email,
                plan_type=account.plan_type,
            )
        if operation is not None and operation.status in {"failed", "cancelled", "unknown"}:
            return self._login_snapshot(operation)
        return CodexSdkLoginState(status="signed_out")

    def start_login(self, method: str, request_id: str) -> CodexSdkLoginState:
        if method not in {"browser", "device_code"}:
            raise ValueError("Codex login method must be browser or device_code")
        normalized_request_id = request_id.strip()
        if (
            not normalized_request_id
            or len(normalized_request_id) > 128
            or any(marker in normalized_request_id for marker in ("\x00", "\n", "\r"))
        ):
            raise ValueError("Codex login request ID must be a non-empty single-line value")
        with self._login_lock:
            current = self._login_operation
            if current is not None and (
                (current.request_id == normalized_request_id and current.status != "connected")
                or current.status in {"waiting", "cancelling", "unknown"}
            ):
                return self._login_snapshot(current)
            preflight_failed = False
            try:
                account = self.account_status()
            except CodexSdkError:
                account = None
                preflight_failed = True
            if account is not None and account.authenticated and account.auth_method != "api_key":
                return CodexSdkLoginState(
                    status="connected",
                    auth_method=account.auth_method,
                    auth_label=account.label,
                    message="이미 Codex에 연결되어 있습니다.",
                    account_email=account.account_email,
                    plan_type=account.plan_type,
                )
            try:
                client = self._new_dedicated_client()
            except CodexSdkError as error:
                code, message = _auth_failure(error, "runtime_start_failed", "Codex 실행 구성을 시작하지 못했습니다.")
                return CodexSdkLoginState(status="runtime_error", error_code=code, message=message)
            try:
                handle = client.login_chatgpt() if method == "browser" else client.login_chatgpt_device_code()
                auth_url = str(getattr(handle, "auth_url" if method == "browser" else "verification_url", ""))
                user_code = str(getattr(handle, "user_code", "")) if method == "device_code" else ""
                if not auth_url or "\n" in auth_url or "\r" in auth_url:
                    raise RuntimeError("login response did not include a valid URL")
                if method == "device_code" and (not user_code or any(marker in user_code for marker in ("\x00", "\n", "\r"))):
                    raise RuntimeError("device-code response did not include a valid code")
            except Exception as error:
                _close_quietly(client)
                code, message = _auth_failure(error, "login_start_failed", "Codex 로그인을 시작하지 못했습니다.")
                return CodexSdkLoginState(status="failed", method=method, error_code=code, message=message)
            operation = _LoginOperation(
                attempt_id=str(uuid.uuid4()),
                request_id=normalized_request_id,
                method=method,
                started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                client=client,
                handle=handle,
                auth_url=auth_url,
                user_code=user_code,
                message="기존 연결 상태를 확인하지 못해 새 인증 연결로 로그인을 시작했습니다. 브라우저에서 인증을 완료해 주세요." if preflight_failed else "",
            )
            self._login_operation = operation
            worker = threading.Thread(
                target=self._wait_for_login,
                args=(operation,),
                name="codex-sdk-login",
                daemon=True,
            )
            worker.start()
            return self._login_snapshot(operation)

    def login_api_key(self, api_key: str, request_id: str) -> CodexSdkLoginState:
        if not isinstance(api_key, str) or not api_key.strip() or len(api_key) > 4096 or any(c in api_key for c in ("\x00", "\n", "\r")) or any(
            ord(character) < 33 or ord(character) > 126 for character in api_key.strip()
        ):
            raise ValueError("OpenAI API 키를 공백 없는 한 줄로 입력해 주세요.")
        if not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 128 or any(
            marker in request_id for marker in ("\x00", "\n", "\r")
        ):
            raise ValueError("Codex login request ID must be a non-empty single-line value")
        with self._login_lock:
            if self._api_key_login_result is not None and self._api_key_login_result[0] == request_id.strip():
                return self._api_key_login_result[1]
            current = self._login_operation
            if current is not None and current.status in {"waiting", "cancelling", "unknown"}:
                return replace(self._login_snapshot(current), message="진행 중인 Codex 로그인을 완료하거나 취소한 뒤 API 키를 연결해 주세요.")
            client = None
            try:
                client = self._new_dedicated_client()
                client.login_api_key(api_key.strip())
                account = _account_status(client.account(refresh_token=False))
                if not account.authenticated or account.auth_method != "api_key":
                    state = CodexSdkLoginState(
                        status="failed", error_code="api_key_not_connected", message="API 키 방식의 Codex 연결을 확인하지 못했습니다.",
                    )
                else:
                    state = CodexSdkLoginState(
                        status="connected", auth_method=account.auth_method, auth_label=account.label,
                        message="API 키가 Codex에 등록됐습니다. 실제 인증과 모델 접근은 작업 실행 시 확인합니다.",
                    )
            except Exception as error:
                code, message = _auth_failure(error, "api_key_login_failed", "Codex API 키를 연결하지 못했습니다. 연결 상태를 다시 확인해 주세요.")
                state = CodexSdkLoginState(status="failed", error_code=code, message=message)
            finally:
                if client is not None:
                    _close_quietly(client)
                    self.discard_idle_clients()
            self._login_operation = None
            self._api_key_login_result = (request_id.strip(), state)
            return state

    def login_attempt(self, attempt_id: str) -> CodexSdkLoginState:
        normalized = attempt_id.strip()
        if not normalized or len(normalized) > 128 or any(marker in normalized for marker in ("\x00", "\n", "\r")):
            raise CodexSdkError("Codex 로그인 시도 식별자가 올바르지 않습니다.")
        with self._login_lock:
            operation = self._login_operation
            if operation is None or operation.attempt_id != normalized:
                raise CodexSdkError("Codex 로그인 시도를 찾을 수 없습니다. 연결 상태를 다시 확인하세요.")
            if operation.status != "connected":
                return self._login_snapshot(operation)
            method, started_at = operation.method, operation.started_at
        return replace(self.login_status(), attempt_id=normalized, method=method, started_at=started_at)

    def cancel_login(self, attempt_id: str) -> CodexSdkLoginState:
        normalized = attempt_id.strip()
        if not normalized or len(normalized) > 128 or any(marker in normalized for marker in ("\x00", "\n", "\r")):
            raise CodexSdkError("Codex 로그인 시도 식별자가 올바르지 않습니다.")
        with self._login_lock:
            operation = self._login_operation
            if operation is None or operation.attempt_id != normalized:
                raise CodexSdkError("Codex 로그인 시도를 찾을 수 없습니다. 연결 상태를 다시 확인하세요.")
            if operation.status not in {"waiting", "cancelling"}:
                return self._login_snapshot(operation)
            operation.cancel_requested = True
            operation.status = "cancelling"
            handle = operation.handle
        try:
            getattr(handle, "cancel")()
        except Exception:
            with self._login_lock:
                if self._login_operation is operation and operation.status == "cancelling":
                    operation.status = "unknown"
                    operation.error_code = "cancel_unconfirmed"
                    operation.message = "로그인 취소 완료를 확인하지 못했습니다. 연결 상태를 다시 확인하세요."
        else:
            threading.Thread(
                target=self._watch_login_cancellation,
                args=(operation,),
                name="codex-sdk-login-cancel",
                daemon=True,
            ).start()
        with self._login_lock:
            return self._login_snapshot(operation)

    def run_turn(self, request: CodexSdkTurnRequest) -> str:
        if request.timeout_seconds <= 0:
            raise ValueError("Codex SDK timeout must be greater than zero")
        if request.conversation_id and (
            request.conversation_id != request.conversation_id.strip() or any(marker in request.conversation_id for marker in ("\x00", "\n", "\r"))
        ):
            raise ValueError("Codex SDK conversation ID must be a single-line value")
        operation = _TurnOperation()
        self._start_log(operation, request)
        worker = threading.Thread(target=self._run_operation, args=(operation, request), name="codex-sdk-turn", daemon=True)
        worker.start()
        stopped = False
        stop_requested_at = 0.0
        while not operation.completed.is_set():
            if request.cancel_signal is not None and request.cancel_signal.is_set():
                if not stopped:
                    stopped = True
                    stop_requested_at = time.monotonic()
                    operation.cancelled.set()
                    client, handle = operation.current_client_and_handle()
                    if handle is not None:
                        threading.Thread(target=_interrupt_quietly, args=(handle,), name="codex-sdk-user-interrupt", daemon=True).start()
                    if client is not None:
                        if request.conversation_id:
                            self._discard_conversation(request.conversation_id, client)
                        else:
                            self._discard_client(client)
                elif time.monotonic() - stop_requested_at >= 5:
                    raise CodexSdkError("Codex SDK 중지 요청 뒤 실행 종료를 확인하지 못했습니다.")
                operation.completed.wait(timeout=0.1)
                continue
            remaining = operation.remaining_idle_seconds(request.timeout_seconds)
            if remaining <= 0:
                break
            operation.completed.wait(timeout=min(remaining, 0.25))
        stopped = stopped or (operation.cancelled.is_set() and request.cancel_signal is not None and request.cancel_signal.is_set())
        if stopped and operation.completed.is_set():
            self._append_log(operation, request.log_path, {"transport": "codex-sdk", "event": "turn-stopped", "reason": "user_requested"})
            raise ExecutionStopped("사용자 요청에 따라 Codex 실행을 중지했습니다.")
        if not operation.completed.is_set():
            operation.cancelled.set()
            client, handle = operation.current_client_and_handle()
            if handle is not None:
                threading.Thread(target=_interrupt_quietly, args=(handle,), name="codex-sdk-interrupt", daemon=True).start()
            if client is not None:
                if request.conversation_id:
                    self._discard_conversation(request.conversation_id, client)
                else:
                    self._discard_client(client)
            error = CodexSdkTimeout(f"Codex SDK turn timed out after {request.timeout_seconds:g}s without activity")
            self._append_log(
                operation,
                request.log_path,
                {
                    "transport": "codex-sdk",
                    "event": "turn-timeout",
                    "timeout_kind": "inactivity",
                    "timeout_seconds": request.timeout_seconds,
                    "error": str(error),
                },
            )
            raise error
        if operation.error is not None:
            raise operation.error
        if not operation.result.strip():
            raise CodexSdkError("Codex SDK turn completed without a final agent message")
        return operation.result

    def close_conversation(self, conversation_id: str) -> None:
        normalized = conversation_id.strip()
        if not normalized:
            return
        with self._conversation_lock:
            conversation = self._conversations.pop(normalized, None)
        if conversation is not None:
            self._release_client(conversation.client)

    def discard_idle_clients(self) -> None:
        with self._lock:
            clients = tuple(self._idle_clients)
            self._idle_clients.clear()
        for client in clients:
            _close_quietly(client)

    def has_conversation(self, conversation_id: str, *, cwd: Path, model: str, sandbox_mode: str, approval_mode: str) -> bool:
        normalized = conversation_id.strip()
        if not normalized:
            return False
        with self._conversation_lock:
            conversation = self._conversations.get(normalized)
            return conversation is not None and conversation.matches(cwd=cwd, model=model, sandbox_mode=sandbox_mode, approval_mode=approval_mode)

    def close(self) -> None:
        with self._login_lock:
            login_operation = self._login_operation
            self._login_operation = None
            self._api_key_login_result = None
        if login_operation is not None:
            if login_operation.status in {"waiting", "cancelling", "unknown"}:
                try:
                    getattr(login_operation.handle, "cancel")()
                except Exception:
                    pass
            _close_quietly(login_operation.client)
        with self._conversation_lock:
            self._conversations.clear()
        with self._lock:
            if self._closed:
                return
            self._closed = True
            clients = tuple((*self._idle_clients, *self._active_clients))
            self._idle_clients.clear()
            self._active_clients.clear()
        for client in clients:
            _close_quietly(client)

    def _new_dedicated_client(self) -> Codex:
        from openai_codex import CodexError

        with self._lock:
            if self._closed:
                raise CodexSdkError("Codex SDK manager is closed")
        try:
            client = self._client_factory()
        except (CodexError, OSError, RuntimeError) as exc:
            raise CodexSdkError("failed to start Codex SDK runtime") from exc
        with self._lock:
            if self._closed:
                _close_quietly(client)
                raise CodexSdkError("Codex SDK manager is closed")
        return client

    def _wait_for_login(self, operation: _LoginOperation) -> None:
        reading_account = False
        try:
            completed = getattr(operation.handle, "wait")()
            success = bool(getattr(completed, "success", False))
            reading_account = True
            response = operation.client.account(refresh_token=False)
            account = _account_status(response)
            with self._login_lock:
                if self._login_operation is not operation:
                    return
                if operation.status == "unknown":
                    return
                if account.authenticated:
                    operation.status = "connected"
                    operation.auth_method = account.auth_method
                    operation.auth_label = account.label
                    operation.account_email = account.account_email
                    operation.plan_type = account.plan_type
                    operation.message = "Codex 연결이 완료됐습니다."
                    operation.error_code = ""
                elif operation.cancel_requested:
                    operation.status = "cancelled"
                    operation.message = "Codex 로그인을 취소했습니다."
                    operation.error_code = ""
                elif success:
                    operation.status = "failed"
                    operation.error_code = "account_not_connected"
                    operation.message = "로그인은 완료됐지만 Codex 연결 상태를 확인하지 못했습니다."
                else:
                    operation.status = "failed"
                    operation.error_code = "login_failed"
                    operation.message = "Codex 로그인에 실패했습니다. 다시 시도하세요."
                operation.auth_url = ""
                operation.user_code = ""
        except Exception as error:
            with self._login_lock:
                if self._login_operation is not operation:
                    return
                if operation.status == "unknown":
                    return
                operation.status = "cancelled" if operation.cancel_requested else "failed"
                if operation.cancel_requested:
                    operation.error_code, operation.message = "", "Codex 로그인을 취소했습니다."
                else:
                    operation.error_code, operation.message = _auth_failure(
                        error, "account_status_failed" if reading_account else "login_failed",
                        "브라우저 인증 응답을 받았지만 계정 연결을 확인하지 못했습니다. 연결 다시 확인을 눌러 주세요."
                        if reading_account else "Codex 로그인 완료를 확인하지 못했습니다. 다시 시도하세요.",
                    )
                operation.auth_url = ""
                operation.user_code = ""
        finally:
            _close_quietly(operation.client)

    def _watch_login_cancellation(self, operation: _LoginOperation) -> None:
        time.sleep(_LOGIN_CANCEL_CONFIRM_TIMEOUT_SECONDS)
        close_client = False
        with self._login_lock:
            if self._login_operation is operation and operation.status == "cancelling":
                operation.status = "unknown"
                operation.error_code = "cancel_unconfirmed"
                operation.message = "로그인 취소 완료를 확인하지 못했습니다. 연결 상태를 다시 확인하세요."
                operation.auth_url = ""
                operation.user_code = ""
                close_client = True
        if close_client:
            _close_quietly(operation.client)

    @staticmethod
    def _login_snapshot(operation: _LoginOperation) -> CodexSdkLoginState:
        return CodexSdkLoginState(
            status=operation.status,
            attempt_id=operation.attempt_id,
            method=operation.method,
            started_at=operation.started_at,
            auth_method=operation.auth_method,
            auth_label=operation.auth_label,
            auth_url=operation.auth_url,
            user_code=operation.user_code,
            error_code=operation.error_code,
            message=operation.message,
            account_email=operation.account_email if operation.status == "connected" else "",
            plan_type=operation.plan_type if operation.status == "connected" else "",
        )

    def _run_operation(self, operation: _TurnOperation, request: CodexSdkTurnRequest) -> None:
        client: Codex | None = None
        conversation: _SdkConversation | None = None
        healthy = False
        try:
            sandbox = _sandbox(request.sandbox_mode)
            approval = _approval_mode(request.approval_mode)
            if request.conversation_id:
                conversation = self._conversation_for(request, approval, sandbox)
                client = conversation.client
                thread = conversation.thread
                execution_profile = conversation.execution_profile
            else:
                client = self._acquire_client()
                execution_profile = _resolve_execution_profile(client, request)
                thread = client.thread_start(
                    approval_mode=approval,
                    cwd=str(request.cwd.resolve()),
                    ephemeral=True,
                    model=execution_profile.model,
                    sandbox=sandbox,
                    service_name="ai_work_orchestrator",
                )
            operation.set_client(client)
            if operation.cancelled.is_set():
                return
            turn_lock = conversation.turn_lock if conversation is not None else threading.Lock()
            with turn_lock:
                result = self._run_turn_with_backoff(operation, request, thread, conversation, execution_profile, approval, sandbox)
            final_response = result.final_response or ""
            if not final_response.strip():
                raise CodexSdkError("Codex SDK turn completed without a final agent message")
            operation.result = final_response
            healthy = True
            self._append_log(
                operation,
                request.log_path,
                {
                    "transport": "codex-sdk",
                    "event": "turn-completed",
                    "effective_model": execution_profile.model,
                    "effective_reasoning_effort": (execution_profile.reasoning_effort),
                    "turn_id": result.id,
                    "status": _json_value(result.status),
                    "duration_ms": result.duration_ms,
                    "usage": _json_value(result.usage),
                    "item_count": len(result.items),
                    "item_counts": _thread_item_counts(result.items),
                    "final_response": final_response,
                },
            )
        except Exception as exc:
            if not operation.cancelled.is_set():
                error = exc if isinstance(exc, CodexSdkError) else CodexSdkError(
                    f"Codex SDK turn failed: {exc}", error_info=getattr(exc, "data", None)
                )
                if error is not exc:
                    error.__cause__ = exc
                operation.error = error
                self._append_log(operation, request.log_path, {
                    "transport": "codex-sdk", "event": "turn-failed", "error": str(error),
                    "codex_error_info": error.error_info, "additional_details": error.additional_details,
                })
        finally:
            operation.completed.set()
            if client is not None:
                if request.conversation_id:
                    if not healthy or operation.cancelled.is_set():
                        self._discard_conversation(request.conversation_id, client)
                elif healthy and not operation.cancelled.is_set():
                    self._release_client(client)
                else:
                    self._discard_client(client)

    def _run_turn_with_backoff(
        self, operation: _TurnOperation, request: CodexSdkTurnRequest, thread: CodexThread,
        conversation: _SdkConversation | None, profile: CodexSdkExecutionProfile, approval: ApprovalMode, sandbox: Sandbox,
    ) -> TurnResult:
        from openai_codex import CodexError
        from openai_codex.types import ReasoningEffort

        waited = 0.0
        epoch = conversation.usage_epoch if conversation is not None else str(uuid.uuid4())
        baseline = conversation.usage_total if conversation is not None else TokenCounts(0, 0, 0, 0, 0, 0)
        for retry_index in range(len(_PROVIDER_RETRY_DELAYS) + 1):
            if operation.cancelled.is_set():
                raise ExecutionStopped("사용자 요청에 따라 Codex 실행을 중지했습니다.")
            handle: TurnHandle | None = None
            operation.set_handle(None)
            try:
                self._record_execution_profile(operation, request, profile)
                handle = thread.turn(
                    request.prompt, approval_mode=approval, cwd=str(request.cwd.resolve()),
                    effort=ReasoningEffort(profile.reasoning_effort), model=profile.model, sandbox=sandbox,
                )
                operation.set_handle(handle)
                tracker = CodexUsageTracker(
                    thread_id=str(getattr(handle, "thread_id", "") or getattr(thread, "id", "")), turn_id=handle.id,
                    epoch=epoch, baseline=baseline, callback=request.usage_callback,
                )
                if operation.cancelled.is_set():
                    _interrupt_quietly(handle)
                    raise ExecutionStopped("사용자 요청에 따라 Codex 실행을 중지했습니다.")
                try:
                    return _collect_turn_result(
                        handle, lambda progress: self._record_progress(operation, request, progress), operation.mark_activity,
                        attempt_id=request.attempt_id, invocation_id=request.invocation_id, usage_tracker=tracker,
                        diagnostic_callback=lambda diagnostic: self._append_log(operation, request.log_path, diagnostic),
                    )
                finally:
                    baseline = tracker.next_baseline(tracker.terminal_received)
                    if conversation is not None:
                        conversation.usage_total = baseline
            except ExecutionStopped:
                raise
            except (CodexSdkError, CodexError) as exc:
                error = exc if isinstance(exc, CodexSdkError) else CodexSdkError(str(exc), error_info=getattr(exc, "data", None))
                if error is not exc:
                    error.__cause__ = exc
                if handle is None:
                    error.retry_safe = True
                if not error.service_unavailable or not error.retry_safe or retry_index >= len(_PROVIDER_RETRY_DELAYS):
                    raise error
                delay = max(_PROVIDER_RETRY_DELAYS[retry_index], error.retry_after_seconds or 0.0) + random.uniform(0.0, 5.0)
                if waited + delay > _PROVIDER_RETRY_WAIT_BUDGET:
                    raise error
                if request.retry_callback is not None:
                    request.retry_callback(None)
                self._append_log(operation, request.log_path, {
                    "transport": "codex-sdk", "event": "provider-retry-scheduled", "error": str(error),
                    "codex_error_info": error.error_info, "additional_details": error.additional_details,
                    "retry_index": retry_index + 1, "delay_seconds": delay,
                })
                operation.set_handle(None)
                if not self._wait_for_retry(operation, request, delay, retry_index + 1):
                    raise ExecutionStopped("사용자 요청에 따라 Codex 실행을 중지했습니다.")
                waited += delay
                request = replace(request, invocation_id=str(uuid.uuid4()))
                if request.retry_callback is not None:
                    request.retry_callback(request.invocation_id)
        raise AssertionError("provider retry loop exhausted without a result")

    def _wait_for_retry(self, operation: _TurnOperation, request: CodexSdkTurnRequest, delay: float, retry_index: int) -> bool:
        with operation.state_lock:
            operation.retry_until = time.monotonic() + delay
        try:
            self._record_progress(operation, request, CodexSdkProgress(
                "provider_retry_wait", json.dumps({
                    "retry_at": (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat(),
                    "retry_index": retry_index, "max_retries": len(_PROVIDER_RETRY_DELAYS),
                }), attempt_id=request.attempt_id, invocation_id=request.invocation_id,
                received_at=datetime.now(timezone.utc).isoformat(), activity_changed=False, evidence_kind="retry_wait",
            ))
            while not operation.cancelled.is_set():
                if request.cancel_signal is not None and request.cancel_signal.is_set():
                    operation.cancelled.set()
                    return False
                remaining = operation.retry_until - time.monotonic()
                if remaining <= 0:
                    return True
                operation.cancelled.wait(min(remaining, 0.25))
            return False
        finally:
            with operation.state_lock:
                operation.retry_until = 0.0
                operation.last_activity_at = time.monotonic()

    def _conversation_for(self, request: CodexSdkTurnRequest, approval: ApprovalMode, sandbox: Sandbox) -> _SdkConversation:
        with self._conversation_lock:
            existing = self._conversations.get(request.conversation_id)
            if existing is not None and existing.matches(
                cwd=request.cwd,
                model=request.model,
                sandbox_mode=request.sandbox_mode,
                approval_mode=request.approval_mode,
                reasoning_effort=request.reasoning_effort,
            ):
                return existing
            if existing is not None:
                self._conversations.pop(request.conversation_id, None)
                self._release_client(existing.client)
            client = self._acquire_client()
            try:
                execution_profile = _resolve_execution_profile(client, request)
                thread = client.thread_start(
                    approval_mode=approval,
                    cwd=str(request.cwd.resolve()),
                    ephemeral=True,
                    model=execution_profile.model,
                    sandbox=sandbox,
                    service_name="ai_work_orchestrator",
                )
            except Exception:
                self._discard_client(client)
                raise
            conversation = _SdkConversation(
                client=client,
                thread=thread,
                cwd=str(request.cwd.resolve()),
                model=request.model,
                reasoning_effort=request.reasoning_effort,
                execution_profile=execution_profile,
                sandbox_mode=request.sandbox_mode,
                approval_mode=request.approval_mode,
            )
            self._conversations[request.conversation_id] = conversation
            return conversation

    def _discard_conversation(self, conversation_id: str, client: Codex) -> None:
        with self._conversation_lock:
            current = self._conversations.get(conversation_id)
            if current is not None and current.client is client:
                self._conversations.pop(conversation_id, None)
        self._discard_client(client)

    def _record_progress(self, operation: _TurnOperation, request: CodexSdkTurnRequest, progress: CodexSdkProgress) -> None:
        if progress.log_report:
            self._append_log(
                operation,
                request.log_path,
                {
                    "schema_version": 1,
                    "transport": "codex-sdk",
                    "event": "turn-progress",
                    "attempt_id": request.attempt_id,
                    "invocation_id": request.invocation_id,
                    "event_seq": progress.event_seq,
                    "turn_id": progress.turn_id,
                    "item_id": progress.item_id,
                    "phase": progress.phase,
                    "detail": progress.detail,
                    "evidence_kind": progress.evidence_kind,
                    "received_at": progress.received_at,
                },
            )
        if request.progress_callback is not None:
            request.progress_callback(progress)

    def _record_execution_profile(self, operation: _TurnOperation, request: CodexSdkTurnRequest, profile: CodexSdkExecutionProfile) -> None:
        self._append_log(
            operation,
            request.log_path,
            {
                "transport": "codex-sdk",
                "event": "execution-profile",
                "requested_model": request.model,
                "requested_reasoning_effort": request.reasoning_effort,
                "effective_model": profile.model,
                "effective_reasoning_effort": profile.reasoning_effort,
                "model_automatic": profile.model_automatic,
                "reasoning_effort_automatic": (profile.reasoning_effort_automatic),
            },
        )
        if request.profile_callback is not None:
            request.profile_callback(profile)

    def _acquire_client(self) -> Codex:
        from openai_codex import CodexError

        with self._lock:
            if self._closed:
                raise CodexSdkError("Codex SDK manager is closed")
            if self._idle_clients:
                client = self._idle_clients.pop()
                self._active_clients.add(client)
                return client
        try:
            client = self._client_factory()
        except (CodexError, OSError, RuntimeError) as exc:
            raise CodexSdkError(f"failed to start Codex SDK runtime: {exc}") from exc
        with self._lock:
            if self._closed:
                _close_quietly(client)
                raise CodexSdkError("Codex SDK manager is closed")
            self._active_clients.add(client)
        return client

    def _release_client(self, client: Codex) -> None:
        close_client = False
        with self._lock:
            if client not in self._active_clients:
                return
            self._active_clients.remove(client)
            if self._closed:
                close_client = True
            else:
                self._idle_clients.append(client)
        if close_client:
            _close_quietly(client)

    def _discard_client(self, client: Codex) -> None:
        with self._lock:
            should_close = client in self._active_clients or any(candidate is client for candidate in self._idle_clients)
            self._active_clients.discard(client)
            self._idle_clients = [candidate for candidate in self._idle_clients if candidate is not client]
        if should_close:
            _close_quietly(client)

    def _start_log(self, operation: _TurnOperation, request: CodexSdkTurnRequest) -> None:
        request.log_path.parent.mkdir(parents=True, exist_ok=True)
        with operation.log_lock:
            request.log_path.write_text(
                json.dumps(
                    {
                        "transport": "codex-sdk",
                        "event": "turn-request",
                        "runtime": "installed-cli" if _uses_external_codex() else "sdk-pinned",
                        "cwd": str(request.cwd.resolve()),
                        "model": request.model,
                        "reasoning_effort": request.reasoning_effort,
                        "sandbox": request.sandbox_mode,
                        "approval": request.approval_mode,
                        "timeout_kind": "inactivity",
                        "timeout_seconds": request.timeout_seconds,
                        "conversation_id": request.conversation_id,
                        "prompt_characters": len(request.prompt),
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

    @staticmethod
    def _append_log(operation: _TurnOperation, log_path: Path, payload: dict[str, object]) -> None:
        with operation.log_lock:
            with log_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **payload}, ensure_ascii=False))
                stream.write("\n")


def _resolve_execution_profile(client: Codex, request: CodexSdkTurnRequest) -> CodexSdkExecutionProfile:
    model_automatic = not bool(request.model)
    reasoning_automatic = not bool(request.reasoning_effort)
    if not model_automatic and not reasoning_automatic:
        return CodexSdkExecutionProfile(
            model=request.model, reasoning_effort=request.reasoning_effort, model_automatic=False, reasoning_effort_automatic=False
        )

    try:
        models = client.models().data
    except Exception as exc:
        raise CodexSdkError("failed to read the Codex SDK model catalog") from exc

    if model_automatic:
        matching_models = [model for model in models if "gpt-6.1-sol" in {model.id, model.model}]
        if len(matching_models) != 1:
            raise CodexSdkError("자동 선택에 필요한 gpt-6.1-sol을 사용할 수 없습니다. 모델 연결 상태를 확인해 주세요.")
        selected_model = matching_models[0]
    else:
        selected_model = next((model for model in models if request.model in {model.id, model.model}), None)
        if selected_model is None:
            raise CodexSdkError(f"Codex 모델 목록에서 {request.model!r}의 기본 추론 강도를 확인할 수 없습니다. 추론 강도를 low, medium 등으로 직접 선택해 주세요.")

    effective_model = request.model or selected_model.model
    raw_default_effort = _enum_value(selected_model.default_reasoning_effort)
    default_effort = raw_default_effort if isinstance(raw_default_effort, str) else ""
    effective_effort = request.reasoning_effort or default_effort
    if not effective_model or not effective_effort:
        raise CodexSdkError("Codex SDK model catalog returned an incomplete execution profile")
    return CodexSdkExecutionProfile(
        model=effective_model, reasoning_effort=effective_effort, model_automatic=model_automatic, reasoning_effort_automatic=reasoning_automatic
    )


def _uses_external_codex() -> bool:
    return bool(getattr(sys, "frozen", False) or os.environ.get("AI_ORCHESTRATOR_CODEX", "").strip())


def installed_codex_executable() -> str:
    windows = sys.platform == "win32"
    name = "codex.exe" if windows else "codex"
    override = os.environ.get("AI_ORCHESTRATOR_CODEX", "").strip()
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_absolute() and (not windows or candidate.suffix.lower() == ".exe") and candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
        raise FileNotFoundError("AI_ORCHESTRATOR_CODEX에 설치된 Codex 실행 파일의 전체 경로를 지정해 주세요.")

    roots = [Path(part.strip('"')) for part in os.environ.get("PATH", "").split(os.pathsep) if part]
    if windows:
        local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        roaming = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        roots.extend((local / "Programs/OpenAI/Codex/bin", roaming / "npm"))
    else:
        roots.extend((Path.home() / ".local/bin", Path("/opt/homebrew/bin"), Path("/usr/local/bin")))

    for root in dict.fromkeys(roots):
        if not root.is_absolute():
            continue
        candidate = root / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
        if windows:
            npm = root / "node_modules/@openai/codex"
            arm = platform.machine().lower() in {"arm64", "aarch64"}
            arch, target = ("arm64", "aarch64") if arm else ("x64", "x86_64")
            vendor = f"vendor/{target}-pc-windows-msvc/bin/{name}"
            for package in (npm / f"node_modules/@openai/codex-win32-{arch}", npm.parent / f"codex-win32-{arch}", npm):
                candidate = package / vendor
                if candidate.is_file():
                    return str(candidate)
    raise FileNotFoundError("작업 PC에 Codex CLI를 설치해 주세요.")


def _new_client() -> Codex:
    from openai_codex import Codex, CodexConfig

    codex_bin = installed_codex_executable() if _uses_external_codex() else None
    codex_home = application_config_root() / "codex"
    if codex_home.is_symlink():
        raise CodexSdkError("앱 전용 Codex 저장소에 심볼릭 링크를 사용할 수 없습니다.")
    codex_home.mkdir(mode=0o700, parents=True, exist_ok=True)
    overrides = ('cli_auth_credentials_store="file"',)
    if sys.platform == "win32":
        # The isolated home has no desktop sandbox defaults. Prefer native
        # isolation so read-only commands do not require escalation.
        overrides += ('features.prefer_mxc=true',)
    return Codex(CodexConfig(
        codex_bin=codex_bin,
        client_name="ai_work_orchestrator", client_title="AI Work Orchestrator", client_version=__version__,
        config_overrides=overrides,
        env={"CODEX_HOME": str(codex_home), "CODEX_SQLITE_HOME": str(codex_home),
             "OPENAI_API_KEY": "", "CODEX_API_KEY": "", "CODEX_ACCESS_TOKEN": ""},
    ))


def _account_status(response: object) -> CodexSdkAccountStatus:
    account = getattr(response, "account", None)
    requires_openai_auth = bool(getattr(response, "requires_openai_auth", True))
    if account is None:
        if requires_openai_auth:
            return CodexSdkAccountStatus(authenticated=False, auth_method="none", label="로그인 필요")
        return CodexSdkAccountStatus(authenticated=True, auth_method="external", label="외부 Provider 인증")

    account_value = getattr(account, "root", account)
    account_type = getattr(account_value, "type", "")
    if account_type == "chatgpt":
        return CodexSdkAccountStatus(
            authenticated=True, auth_method="chatgpt", label="ChatGPT 구독 로그인",
            account_email=_account_display_value(getattr(account_value, "email", None), 320),
            plan_type=_account_display_value(_enum_value(getattr(account_value, "plan_type", None)), 128),
        )
    if account_type == "apiKey":
        return CodexSdkAccountStatus(authenticated=True, auth_method="api_key", label="API 키 · 사용량 과금")
    if account_type == "amazonBedrock":
        return CodexSdkAccountStatus(authenticated=True, auth_method="external", label="Amazon Bedrock 인증")
    return CodexSdkAccountStatus(authenticated=True, auth_method="unknown", label="로그인됨")


def _account_display_value(value: object, limit: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > limit or any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise CodexSdkError("invalid Codex account display metadata")
    return value.strip()


def _sandbox(mode: str) -> Sandbox:
    from openai_codex import Sandbox

    mapping = {
        "read-only": Sandbox.read_only,
        "workspace-write": Sandbox.workspace_write,
        "danger-full-access": Sandbox.full_access,
    }
    try:
        return mapping[mode]
    except KeyError as exc:
        raise CodexSdkError(f"unsupported Codex sandbox mode: {mode}") from exc


def _approval_mode(mode: str) -> ApprovalMode:
    from openai_codex import ApprovalMode

    mapping = {"deny-all": ApprovalMode.deny_all, "auto-review": ApprovalMode.auto_review}
    try:
        return mapping[mode]
    except KeyError as exc:
        raise CodexSdkError(f"unsupported Codex approval mode: {mode}") from exc


def _interrupt_quietly(handle: TurnHandle) -> None:
    from openai_codex import CodexError

    try:
        handle.interrupt()
    except (CodexError, OSError, RuntimeError):
        return


def _close_quietly(client: Codex) -> None:
    from openai_codex import CodexError

    try:
        client.close()
    except (CodexError, OSError, RuntimeError):
        return


def _collect_turn_result(
    handle: TurnHandle,
    progress_callback: Callable[[CodexSdkProgress], None],
    activity_callback: Callable[[], None],
    *,
    attempt_id: str = "",
    invocation_id: str = "",
    usage_tracker: CodexUsageTracker | None = None,
    diagnostic_callback: Callable[[dict[str, object]], None] | None = None,
) -> TurnResult:
    from openai_codex import TurnResult

    completed_turn: Turn | None = None
    items: list[ThreadItem] = []
    usage: ThreadTokenUsage | None = None
    previous_progress: CodexSdkProgress | None = None
    event_seq = 0
    last_progress_at = 0.0
    previous_item_id = ""
    retry_safe = True

    try:
        for event in handle.stream():
            if event.method == "error":
                if diagnostic_callback is not None:
                    diagnostic_callback({
                        "transport": "codex-sdk", "event": "turn-error",
                        "turn_id": str(getattr(event.payload, "turn_id", "") or handle.id),
                        "will_retry": getattr(event.payload, "will_retry", None),
                        "error": _json_value(getattr(event.payload, "error", None)),
                    })
                continue
            item = _thread_item(getattr(event.payload, "item", None))
            if item is not None and getattr(item, "type", "") not in {"userMessage", "reasoning", "plan", "agentMessage"}:
                retry_safe = False
            if event.method.startswith("item/") and any(token in event.method for token in (
                "commandExecution", "fileChange", "mcpToolCall", "dynamicToolCall", "collabAgent", "subAgent",
            )):
                retry_safe = False
            activity_callback()
            progress = _progress_from_notification(event)
            current_progress = progress or previous_progress
            if current_progress is not None:
                event_seq += 1
                payload = event.payload
                item = _thread_item(getattr(payload, "item", None))
                raw_item_id = str(getattr(item, "id", "") or "")
                item_id = raw_item_id or previous_item_id
                changed = (progress is not None and progress != previous_progress) or bool(raw_item_id and raw_item_id != previous_item_id)
                now = time.monotonic()
                log_report = changed or now - last_progress_at >= 5
                if log_report:
                    last_progress_at = now
                progress_callback(
                    CodexSdkProgress(
                        phase=current_progress.phase,
                        detail=current_progress.detail,
                        attempt_id=attempt_id,
                        invocation_id=invocation_id,
                        turn_id=str(getattr(payload, "turn_id", "") or handle.id),
                        item_id=item_id,
                        received_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        event_seq=event_seq,
                        activity_changed=changed,
                        evidence_kind="activity_change" if changed else "provider_event",
                        log_report=log_report,
                    )
                )
                if progress is not None:
                    previous_progress = progress
                if raw_item_id:
                    previous_item_id = raw_item_id

            payload = event.payload
            if event.method == "item/completed" and (getattr(payload, "turn_id", "") == handle.id):
                item = getattr(payload, "item", None)
                if item is not None:
                    items.append(item)
                continue
            if event.method == "thread/tokenUsage/updated":
                if usage_tracker is not None:
                    usage_tracker.receive(payload)
                if getattr(payload, "turn_id", "") == handle.id:
                    usage = getattr(payload, "token_usage", None)
                continue
            if event.method == "turn/completed":
                turn = getattr(payload, "turn", None)
                if turn is not None and turn.id == handle.id:
                    completed_turn = turn
    finally:
        if usage_tracker is not None:
            usage_tracker.finish(completed_turn is not None)

    if completed_turn is None:
        raise CodexSdkError("Codex SDK turn completed event was not received")
    if _enum_value(completed_turn.status) == "failed":
        error = completed_turn.error
        failure = CodexSdkError(
            error.message if error is not None else "Codex SDK turn failed",
            error_info=getattr(error, "codex_error_info", None), additional_details=getattr(error, "additional_details", None),
        )
        final_items = getattr(completed_turn, "items", ()) or ()
        failure.retry_safe = retry_safe and all(
            getattr(_thread_item(item), "type", "") in {"userMessage", "reasoning", "plan", "agentMessage"}
            for item in final_items
        )
        raise failure

    return TurnResult(
        id=completed_turn.id,
        status=completed_turn.status,
        error=completed_turn.error,
        started_at=completed_turn.started_at,
        completed_at=completed_turn.completed_at,
        duration_ms=completed_turn.duration_ms,
        final_response=_final_agent_response(items),
        items=items,
        usage=usage,
    )


def _progress_from_notification(event: Notification) -> CodexSdkProgress | None:
    if event.method == "turn/started":
        return CodexSdkProgress("turn_started")
    if event.method == "turn/plan/updated":
        plan = getattr(event.payload, "plan", ())
        completed = sum(_enum_value(getattr(step, "status", "")) == "completed" for step in plan)
        count = f"계획 단계 {completed}/{len(plan)} 완료"
        active_step = next((step for step in plan if _enum_value(getattr(step, "status", "")) == "inProgress"), None)
        if active_step is None:
            return CodexSdkProgress("organizing_plan", count)
        detail = _safe_progress_detail(f"{count} · {getattr(active_step, 'step', '')}")
        return CodexSdkProgress("plan_step", detail)
    if event.method == "item/completed":
        item = _thread_item(getattr(event.payload, "item", None))
        item_type = getattr(item, "type", "")
        if item_type == "commandExecution":
            code = getattr(item, "exit_code", None)
            status = _enum_value(getattr(item, "status", ""))
            result = f"종료 코드 {code}" if isinstance(code, int) else ("실패" if status in {"failed", "declined"} else "종료 코드 미제공")
            return CodexSdkProgress("command_finished", f"{_command_progress_detail(getattr(item, 'command', ''))} · {result}")
        if item_type == "fileChange":
            status = _enum_value(getattr(item, "status", ""))
            result = "적용 완료" if status == "completed" else "적용 실패" if status in {"failed", "declined"} else "결과 상태 미제공"
            return CodexSdkProgress("changes_finished", result)
    if event.method != "item/started":
        if event.method == "turn/completed":
            return CodexSdkProgress("response_received")
        return None

    item = _thread_item(getattr(event.payload, "item", None))
    item_type = getattr(item, "type", "")
    if item_type == "reasoning":
        return CodexSdkProgress("analyzing_request")
    if item_type == "plan":
        return CodexSdkProgress("organizing_plan")
    if item_type == "commandExecution":
        return CodexSdkProgress(_command_progress_phase(getattr(item, "command", "")), _command_progress_detail(getattr(item, "command", "")))
    if item_type == "fileChange":
        return CodexSdkProgress("applying_changes")
    if item_type in {"mcpToolCall", "dynamicToolCall"}:
        return CodexSdkProgress("calling_tool")
    if item_type == "webSearch":
        return CodexSdkProgress("searching_web")
    if item_type == "imageView":
        return CodexSdkProgress("inspecting_image")
    if item_type == "contextCompaction":
        return CodexSdkProgress("compacting_context")
    if item_type in {"collabAgentToolCall", "subAgentActivity"}:
        return CodexSdkProgress("coordinating_agents")
    if item_type == "agentMessage":
        return CodexSdkProgress("writing_response")
    return None


def _command_progress_detail(command: object) -> str:
    # Only emit known command names, never provider-supplied arguments
    # or output.
    normalized = str(command).casefold()
    for pattern, label in (
        (r"\bdotnet(?:\.exe)?[\s\"']+test\b", "dotnet test"),
        (r"\bdotnet(?:\.exe)?[\s\"']+build\b", "dotnet build"),
        (r"\bdotnet(?:\.exe)?[\s\"']+restore\b", "dotnet restore"),
        (r"\bpytest\b", "pytest"),
        (r"\bnpm(?:\.cmd)?[\s\"']+(?:run\s+)?test\b", "npm test"),
        (r"\bnpm(?:\.cmd)?[\s\"']+run\s+build\b", "npm run build"),
        (r"\brg\s", "rg 파일 검색"),
        (r"\bgit\s+diff\b", "git diff"),
        (r"\bgit\s+status\b", "git status"),
        (r"\bget-content\b", "Get-Content 파일 확인"),
    ):
        if re.search(pattern, normalized):
            return label
    return "명령 세부 인자 생략"


def _command_progress_phase(command: object) -> str:
    normalized = str(command).casefold()
    if any(token in normalized for token in ("rg ", "ripgrep", "findstr")):
        return "searching_files"
    if any(token in normalized for token in ("get-content", "type ", "sed ", "head ", "tail ")):
        return "reading_documents"
    if any(token in normalized for token in ("git status", "git log", "git diff", "git ls-files")):
        return "checking_repository"
    if any(token in normalized for token in ("python ", "python3 ", "py -")):
        return "analyzing_project"
    return "running_command"


def _final_agent_response(items: list[ThreadItem]) -> str | None:
    unknown_phase_response: str | None = None
    for item in reversed(items):
        value = _thread_item(item)
        if getattr(value, "type", "") != "agentMessage":
            continue
        text = str(getattr(value, "text", ""))
        phase = getattr(value, "phase", None)
        if _enum_value(phase) == "final_answer":
            return text
        if phase is None and unknown_phase_response is None:
            unknown_phase_response = text
    return unknown_phase_response


def _thread_item(item: object) -> object:
    return getattr(item, "root", item)


def _thread_item_counts(items: list[ThreadItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for raw_item in items:
        item = _thread_item(raw_item)
        item_type = str(getattr(item, "type", "unknown") or "unknown")
        counts[item_type] = counts.get(item_type, 0) + 1
    return counts


def _safe_progress_detail(value: object) -> str:
    normalized = " ".join(str(value).replace("\x00", " ").split())
    if len(normalized) <= 160:
        return normalized
    return normalized[:159].rstrip() + "…"


def _enum_value(value: object) -> object:
    return getattr(value, "value", value)


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _json_value(model_dump(mode="json", by_alias=True))
    return str(value)
