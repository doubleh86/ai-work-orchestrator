from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_orchestrator.codex_sdk import CodexSdkError, CodexSdkManager
from ai_orchestrator.usage import TokenCounts
from test_codex_sdk import FakeCodex, FakeTurnHandle, _enum, _notification, request


def usage(turn_id: str, counts: TokenCounts) -> object:
    return _notification("thread/tokenUsage/updated", thread_id="sdk-thread", turn_id=turn_id,
                         token_usage=SimpleNamespace(total=counts, last=TokenCounts(999, 999, 1998)))


def test_manager_keeps_baseline_per_actual_thread_and_emits_final_observation(tmp_path: Path) -> None:
    handle = FakeTurnHandle(events=[usage("turn-1", TokenCounts(100, 20, 120, 30, 0, 10))])
    handle.thread_id = "sdk-thread"
    client = FakeCodex(handle)
    manager = CodexSdkManager(lambda: client)
    observed = []
    turn_request = replace(request(tmp_path, conversation_id="planning:group"), usage_callback=observed.append)
    assert manager.run_turn(turn_request) == "structured plan"
    assert observed[-1].counts.total_tokens == 120
    assert observed[-1].finalized
    handle.id = "turn-2"
    handle.events = [usage("turn-2", TokenCounts(300, 50, 350, 70, 0, 25))]
    manager.run_turn(replace(turn_request, invocation_id="second"))
    assert len(client.thread_start_calls) == 1
    assert observed[-1].counts == TokenCounts(200, 30, 230, 40, 0, 15)
    assert observed[-1].turn_id == "turn-2"
    manager.close()


def test_manager_does_not_assign_usage_after_an_unreported_turn(tmp_path: Path) -> None:
    handle = FakeTurnHandle()
    handle.thread_id = "sdk-thread"
    client = FakeCodex(handle)
    manager = CodexSdkManager(lambda: client)
    observed = []
    turn_request = replace(request(tmp_path, conversation_id="chat:group"), usage_callback=observed.append)
    manager.run_turn(turn_request)
    assert observed[-1].counts.total_tokens is None
    handle.id = "turn-2"
    handle.events = [usage("turn-2", TokenCounts(300, 50, 350))]
    manager.run_turn(turn_request)
    assert observed[-1].missing_reason == "baseline_missing"
    handle.id = "turn-3"
    handle.events = [usage("turn-3", TokenCounts(500, 80, 580))]
    manager.run_turn(turn_request)
    assert observed[-1].counts == TokenCounts(200, 30, 230)
    manager.close()


@pytest.mark.parametrize("terminal", [True, False])
def test_failed_or_incomplete_sdk_turn_keeps_reported_usage(tmp_path: Path, terminal: bool) -> None:
    class BrokenHandle(FakeTurnHandle):
        def stream(self):
            yield usage(self.id, TokenCounts(20, 4, 24))
            if not terminal:
                raise RuntimeError("stream disconnected")
            yield _notification("turn/completed", turn=SimpleNamespace(
                id=self.id, status=_enum("failed"), error=SimpleNamespace(message="provider failed"),
            ))
    handle = BrokenHandle()
    handle.thread_id = "sdk-thread"
    client = FakeCodex(handle)
    manager = CodexSdkManager(lambda: client)
    observed = []
    with pytest.raises(CodexSdkError):
        manager.run_turn(replace(request(tmp_path), usage_callback=observed.append))
    assert observed[-1].counts.total_tokens == 24
    assert observed[-1].finalized == terminal
    manager.close()
