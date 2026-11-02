import json
import threading
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from openai_codex.types import TurnError

from ai_orchestrator.codex_sdk import CodexSdkError, CodexSdkManager, _retry_after_seconds
from ai_orchestrator.execution_control import ExecutionStopped
from ai_orchestrator.progress import advance_progress_observation
from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, ProjectConfig
from ai_orchestrator.models import RunState, Stage
from ai_orchestrator.pipeline import Pipeline, UsageContext
from ai_orchestrator.usage import TokenCounts
from test_codex_sdk import FakeClientFactory, FakeCodex, FakeTurnHandle, _enum, _notification, _thread_item, request


class FailedHandle(FakeTurnHandle):
    def __init__(self, *, message="upstream unavailable", info=None, details=None, events=(), final_items=()):
        super().__init__()
        self.failure = TurnError.model_validate({
            "message": message, "codexErrorInfo": info or {"httpConnectionFailed": {"httpStatusCode": 503}},
            "additionalDetails": details,
        })
        self.events = list(events)
        self.final_items = final_items

    def stream(self):
        yield from self.events
        yield _notification("turn/completed", turn=SimpleNamespace(
            id=self.id, status=_enum("failed"), error=self.failure, items=self.final_items,
        ))


class SequenceThread:
    def __init__(self, handles):
        self.handles = handles
        self.turn_calls = []

    def turn(self, prompt, **kwargs):
        self.turn_calls.append((prompt, kwargs))
        handle = self.handles[len(self.turn_calls) - 1]
        handle.id = f"turn-{len(self.turn_calls)}"
        return handle


def manager_for(handles):
    client = FakeCodex()
    client.thread = SequenceThread(handles)
    return CodexSdkManager(client_factory=FakeClientFactory([client])), client


def test_final_503_retries_four_times_with_increasing_delay_jitter_and_original_error(tmp_path):
    manager, client = manager_for([FailedHandle()] * 5)
    with patch("ai_orchestrator.codex_sdk.random.uniform", return_value=2.5), patch.object(manager, "_wait_for_retry", return_value=True) as wait:
        with pytest.raises(CodexSdkError, match="upstream unavailable") as caught:
            manager.run_turn(request(tmp_path))
    assert [call.args[2] for call in wait.call_args_list] == [7.5, 17.5, 32.5, 62.5]
    assert [call.args[3] for call in wait.call_args_list] == [1, 2, 3, 4]
    assert len(client.thread.turn_calls) == 5 and len(client.thread_start_calls) == 1
    assert caught.value.service_unavailable and caught.value.error_info["httpConnectionFailed"]["httpStatusCode"] == 503
    records = [json.loads(line) for line in (tmp_path / "planning.log").read_text().splitlines()]
    assert len([row for row in records if row["event"] == "provider-retry-scheduled"]) == 4
    assert records[-1]["event"] == "turn-failed"
    manager.close()


def test_capacity_retries_same_conversation_prompt_model_and_reports_profile_for_each_call(tmp_path):
    manager, client = manager_for([FailedHandle(info="serverOverloaded"), FakeTurnHandle()])
    profiles = []
    with patch.object(manager, "_wait_for_retry", return_value=True):
        assert manager.run_turn(request(tmp_path, conversation_id="planning:group", profile_callback=profiles.append)) == "structured plan"
    assert len(client.thread_start_calls) == 1
    assert client.thread.turn_calls[0] == client.thread.turn_calls[1]
    assert len(profiles) == 2
    assert manager.has_conversation("planning:group", cwd=tmp_path, model="gpt-test", sandbox_mode="read-only", approval_mode="deny-all")
    manager.close()


@pytest.mark.parametrize("item_type", ["commandExecution", "fileChange", "mcpToolCall", "dynamicToolCall", "collabAgentToolCall", "unknown"])
@pytest.mark.parametrize("in_final_result", [False, True])
def test_started_actions_or_unrecognized_actions_are_never_replayed(tmp_path, item_type, in_final_result):
    item = _thread_item(item_type)
    handle = FailedHandle(final_items=[item] if in_final_result else [], events=[] if in_final_result else [
        _notification("item/started", item=item, turn_id="turn-1"),
    ])
    manager, client = manager_for([handle])
    with patch.object(manager, "_wait_for_retry") as wait, pytest.raises(CodexSdkError):
        manager.run_turn(request(tmp_path, sandbox="workspace-write", approval="auto-review"))
    wait.assert_not_called()
    assert len(client.thread.turn_calls) == 1
    manager.close()


@pytest.mark.parametrize("message,info", [
    ("rate limited", "rateLimitExceeded"), ("quota exhausted", "usageLimitExceeded"),
    ("login required", "unauthorized"), ("invalid schema", "badRequest"),
])
def test_non_transient_failures_are_not_automatically_retried(tmp_path, message, info):
    manager, client = manager_for([FailedHandle(message=message, info=info)])
    with patch.object(manager, "_wait_for_retry") as wait, pytest.raises(CodexSdkError):
        manager.run_turn(request(tmp_path))
    wait.assert_not_called()
    assert len(client.thread.turn_calls) == 1
    manager.close()


def test_stream_failure_without_terminal_result_is_not_replayed(tmp_path):
    manager, client = manager_for([FakeTurnHandle(error=CodexSdkError("HTTP 503"))])
    with patch.object(manager, "_wait_for_retry") as wait, pytest.raises(CodexSdkError):
        manager.run_turn(request(tmp_path))
    wait.assert_not_called()
    assert len(client.thread.turn_calls) == 1
    manager.close()


def test_sdk_intermediate_retry_does_not_create_another_turn(tmp_path):
    event = _notification("error", turn_id="turn-1", will_retry=True, error=TurnError(message="HTTP 503"))
    manager, client = manager_for([FakeTurnHandle(events=[event, event])])
    with patch.object(manager, "_wait_for_retry") as wait:
        assert manager.run_turn(request(tmp_path)) == "structured plan"
    wait.assert_not_called()
    assert len(client.thread.turn_calls) == 1
    manager.close()


def test_retry_after_is_a_minimum_delay_and_long_delays_do_not_retry_early(tmp_path):
    manager, client = manager_for([FailedHandle(details='{"headers":{"Retry-After":"120"}}'), FakeTurnHandle()])
    with patch("ai_orchestrator.codex_sdk.random.uniform", return_value=1.0), patch.object(manager, "_wait_for_retry", return_value=True) as wait:
        assert manager.run_turn(request(tmp_path)) == "structured plan"
    assert wait.call_args.args[2] == 121.0
    manager.close()
    manager, client = manager_for([FailedHandle(details='Retry-After: 301')])
    with patch.object(manager, "_wait_for_retry") as wait, pytest.raises(CodexSdkError):
        manager.run_turn(request(tmp_path))
    wait.assert_not_called()
    assert len(client.thread.turn_calls) == 1
    manager.close()


def test_retry_after_http_date_and_invalid_values():
    future = datetime.now(timezone.utc) + timedelta(seconds=45)
    delay = _retry_after_seconds({"headers": {"Retry-After": format_datetime(future, usegmt=True)}}, None)
    assert 43 <= delay <= 45
    for value in (True, -1, "NaN", "infinity", "invalid", []):
        assert _retry_after_seconds({"headers": {"Retry-After": value}}, None) is None


def test_intentional_wait_does_not_expire_inactivity_timeout_or_claim_activity(tmp_path):
    manager, client = manager_for([FailedHandle(), FakeTurnHandle()])
    progress = []
    with (patch("ai_orchestrator.codex_sdk._PROVIDER_RETRY_DELAYS", (0.12, 0.12, 0.12, 0.12)),
          patch("ai_orchestrator.codex_sdk.random.uniform", return_value=0)):
        assert manager.run_turn(request(tmp_path, timeout=0.06, progress_callback=progress.append)) == "structured plan"
    waiting = next(item for item in progress if item.phase == "provider_retry_wait")
    assert not waiting.activity_changed and waiting.evidence_kind == "retry_wait"
    assert json.loads(waiting.detail)["retry_index"] == 1
    assert len(client.thread.turn_calls) == 2
    manager.close()


def test_user_stop_during_wait_prevents_the_next_turn(tmp_path):
    manager, client = manager_for([FailedHandle()])
    cancelled = threading.Event()
    def progress(value):
        if value.phase == "provider_retry_wait":
            cancelled.set()
    with pytest.raises(ExecutionStopped):
        manager.run_turn(request(tmp_path, cancel_signal=cancelled, progress_callback=progress))
    assert len(client.thread.turn_calls) == 1
    manager.close()


def test_wait_progress_preserves_previous_actual_activity():
    arguments = dict(attempt_id="task:1:execute", invocation_id="inv", turn_id="turn-1", event_seq=1)
    current = advance_progress_observation(None, **arguments, phase="analyzing_request", detail="", received_at="old",
                                           activity_changed=True, evidence_kind="activity_change")
    waiting = advance_progress_observation(current, **arguments, phase="provider_retry_wait", detail="scheduled", received_at="new",
                                           activity_changed=False, evidence_kind="retry_wait")
    assert waiting.last_activity_changed_at == "old" and waiting.activity_seq == current.activity_seq
    assert waiting.last_event_received_at == "new" and waiting.evidence_kind == "retry_wait"


@pytest.mark.parametrize("cancel_wait", [False, True])
def test_pipeline_records_each_actual_retry_call_and_preserves_failed_usage(tmp_path, cancel_wait):
    def tokens(turn, total):
        return _notification("thread/tokenUsage/updated", thread_id="thread", turn_id=turn,
                             token_usage=SimpleNamespace(total=total))
    manager, client = manager_for([
        FailedHandle(events=[tokens("turn-1", TokenCounts(100, 20, 120))]),
        FakeTurnHandle(events=[tokens("turn-2", TokenCounts(160, 40, 200))]),
    ])
    client.thread.id = "thread"
    agent = AgentConfig("codex", ("general",), (), provider_id="codex", model="gpt-test")
    pipeline = Pipeline(Config(path=tmp_path / "config.toml", project=ProjectConfig(repo=tmp_path), agents=(agent,),
                               execution=ExecutionConfig()), codex_sdk=manager)
    pipeline.store.save(RunState("group", "plan.md", "digest", str(tmp_path), "main", Stage.PLANNED))
    cancelled = threading.Event()
    def progress(value):
        if cancel_wait and value.phase == "provider_retry_wait":
            cancelled.set()
    def invoke():
        return pipeline._invoke_provider_command(
            agent=agent,command_template=(),replacements={},cwd=tmp_path,prompt="return a plan",prompt_path="",
            log_path=tmp_path / "planning.log",action="planning",task_id="planning",model="gpt-test",reasoning_effort="medium",
            usage_context=UsageContext("group", "planning"),cancel_signal=cancelled,progress_callback=progress,
        )
    if cancel_wait:
        with pytest.raises(ExecutionStopped):
            invoke()
    else:
        with patch.object(manager, "_wait_for_retry", return_value=True):
            assert invoke() == "structured plan"
    snapshot = pipeline.store.usage_snapshot("group")
    records = snapshot["records"]
    assert len(records) == (1 if cancel_wait else 2)
    assert len({row["invocation_id"] for row in records}) == len(records)
    assert {row["outcome"]: row["total_tokens"] for row in records} == ({"failed":120} if cancel_wait else {"failed":120,"completed":80})
    assert snapshot["summary"]["total_tokens"] == (120 if cancel_wait else 200)
    assert all(row["model_effective"] == "gpt-test" for row in records)
    manager.close()
