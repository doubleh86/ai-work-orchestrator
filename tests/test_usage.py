from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import errno
import json
import multiprocessing
import os
import uuid
from unittest.mock import patch

import pytest

from ai_orchestrator.models import RunState, Stage
from ai_orchestrator.store import RunLockedError, StateStore
from ai_orchestrator.usage import CodexUsageTracker, TokenCounts, UsageObservation, UsageRecord, usage_now, usage_summary


def record(**kwargs: object) -> UsageRecord:
    return UsageRecord(str(uuid.uuid4()), "execute", "codex", "gpt-6.1-sol", usage_now(), **kwargs)


def observation(revision: int, counts: TokenCounts = TokenCounts(10, 2, 12), **kwargs: object) -> UsageObservation:
    return UsageObservation(revision, counts, observed_at=usage_now(),
                            source_kind=kwargs.pop("source_kind", "turn_total"), missing_reason="", **kwargs)


def store(root: Path) -> StateStore:
    result = StateStore(root)
    result.save(RunState("group", "plan.md", "digest", str(root), "main", Stage.PLANNED))
    return result


def payload(total: TokenCounts, *, turn_id: str = "turn") -> object:
    return SimpleNamespace(thread_id="thread", turn_id=turn_id, token_usage=SimpleNamespace(
        total=total, last=TokenCounts(999, 999, 1998),
    ))


def test_cumulative_turn_delta_ignores_last_and_does_not_add_overlapping_counters() -> None:
    observed = []
    first = CodexUsageTracker(thread_id="thread", turn_id="turn", epoch=str(uuid.uuid4()),
                             baseline=TokenCounts(0, 0, 0, 0, 0, 0), callback=observed.append)
    first.receive(payload(TokenCounts(100, 20, 120, 60, 0, 15)))
    first.receive(payload(TokenCounts(100, 20, 120, 60, 0, 15)))
    first.finish(True)
    second = CodexUsageTracker(thread_id="thread", turn_id="turn", epoch=first.epoch,
                              baseline=first.next_baseline(True), callback=observed.append)
    second.receive(payload(TokenCounts(300, 50, 350, 100, 0, 40)))
    second.finish(True)
    assert observed[-1].counts == TokenCounts(200, 30, 230, 40, 0, 25)
    assert usage_summary([record().observe(observed[2]), record().observe(observed[-1])])["total_tokens"] == 350


@pytest.mark.parametrize("kind", ["missing", "reset", "intervening", "invalid"])
def test_uncertain_cumulative_boundaries_are_unavailable(kind: str) -> None:
    observed = []
    tracker = CodexUsageTracker(thread_id="thread", turn_id="turn", epoch=str(uuid.uuid4()),
                               baseline=TokenCounts(100, 20, 120), callback=observed.append)
    if kind == "reset":
        tracker.receive(payload(TokenCounts(50, 10, 60)))
    elif kind == "intervening":
        tracker.receive(payload(TokenCounts(200, 30, 230), turn_id="another-turn"))
        tracker.receive(payload(TokenCounts(300, 40, 340)))
    elif kind == "invalid":
        tracker.receive(payload(SimpleNamespace(input_tokens=True)))
    tracker.finish(True)
    assert not observed[-1].counts.has_report
    assert tracker.next_baseline(True) is None


def test_missing_baseline_can_be_reestablished_without_attributing_unknown_history() -> None:
    observed = []
    tracker = CodexUsageTracker(thread_id="thread", turn_id="turn", epoch=str(uuid.uuid4()), baseline=None, callback=observed.append)
    tracker.receive(payload(TokenCounts(300, 40, 340)))
    tracker.finish(True)
    assert observed[-1].missing_reason == "baseline_missing"
    assert observed[-1].counts.total_tokens is None
    assert tracker.next_baseline(True) == TokenCounts(300, 40, 340)


def test_zero_partial_and_reported_total_mismatch_are_distinct() -> None:
    complete = record(outcome="completed").observe(observation(1, TokenCounts(0, 0, 0), finalized=True))
    unavailable = record(outcome="failed")
    partial = record().observe(observation(1, TokenCounts(10, 2, 17), finalized=True))
    assert complete.coverage == "complete"
    assert partial.coverage == "partial"
    assert usage_summary([complete])["total_tokens"] == 0
    assert usage_summary([unavailable])["total_tokens"] is None
    summary = usage_summary([complete, unavailable, partial])
    assert summary["coverage"] == "partial"
    assert summary["total_tokens"] == 17
    assert summary["complete_call_count"] == 1


def test_upserts_do_not_double_count_or_overwrite_failed_outcome(tmp_path: Path) -> None:
    ledger = store(tmp_path)
    row = record()
    ledger.begin_usage("group", row)
    report = observation(1)
    ledger.observe_usage("group", row.invocation_id, report)
    ledger.observe_usage("group", row.invocation_id, report)
    ledger.finish_usage("group", row.invocation_id, "interrupted", structured=True)
    ledger.observe_usage("group", row.invocation_id, observation(2, TokenCounts(20, 4, 24), finalized=True))
    ledger.observe_usage("group", row.invocation_id, report)
    result = ledger.usage_snapshot("group")
    assert result["summary"]["total_tokens"] == 24
    assert result["summary"]["call_count"] == 1
    assert result["records"][0]["outcome"] == "interrupted"
    with pytest.raises(ValueError, match="conflicting"):
        ledger.observe_usage("group", row.invocation_id, observation(2, TokenCounts(21, 4, 25), finalized=True))


def test_task_usage_aggregates_entire_ledger_and_separates_attempts_and_purposes(tmp_path: Path) -> None:
    ledger = store(tmp_path)
    fixtures = [
        ("one", "first", "execute", 12, "gpt-6.1-sol"),
        ("one", "first", "review", 7, "review-model"),
        ("one", "retry", "execute", 20, "new-model"),
        ("two", "", "execute", 0, ""),
        ("", "", "chat", 100, "gpt-6.1-sol"),
    ]
    for task_id, attempt_id, purpose, total, model in fixtures:
        row = replace(record(task_id=task_id, attempt_id=attempt_id), purpose=purpose, model_effective=model)
        ledger.begin_usage("group", row)
        report = observation(1, TokenCounts(total, 0, total), finalized=True)
        ledger.observe_usage("group", row.invocation_id, report)
        ledger.observe_usage("group", row.invocation_id, report)
        ledger.finish_usage("group", row.invocation_id, "completed", structured=True)
    missing = record(task_id="one", attempt_id="retry")
    ledger.begin_usage("group", missing)
    first = ledger.usage_snapshot("group", limit=1)
    second = ledger.usage_snapshot("group", cursor=first["next_cursor"], limit=1)
    assert len(first["records"]) == 1
    assert first["task_summaries"] == second["task_summaries"]
    tasks = {item["task_id"]: item for item in first["task_summaries"]}
    assert set(tasks) == {"one", "two"}
    assert tasks["one"]["total_tokens"] == 39
    assert tasks["one"]["call_count"] == 4
    assert tasks["one"]["coverage"] == "partial"
    attempts = {item["attempt_id"]: item for item in tasks["one"]["attempts"]}
    assert attempts["first"]["total_tokens"] == 19
    assert attempts["retry"]["total_tokens"] == 20
    assert {item["key"]: item["total_tokens"] for item in attempts["first"]["by_purpose"]} == {"execute": 12, "review": 7}
    assert {item["model_effective"] for item in attempts["first"]["profiles"]} == {"gpt-6.1-sol", "review-model"}
    assert {item["model_effective"] for item in attempts["retry"]["profiles"]} == {"new-model", ""}
    assert tasks["two"]["total_tokens"] == 0
    assert tasks["two"]["attempts"][0]["attempt_id"] == ""


def test_provider_turn_deduplication_and_identifier_immutability(tmp_path: Path) -> None:
    ledger = store(tmp_path)
    one, two = record(), record()
    ledger.begin_usage("group", one)
    ledger.begin_usage("group", two)
    report = observation(1, thread_id="thread", turn_id="turn", usage_epoch=str(uuid.uuid4()), source_kind="thread_delta")
    ledger.observe_usage("group", one.invocation_id, report)
    with pytest.raises(ValueError, match="another usage invocation"):
        ledger.observe_usage("group", two.invocation_id, report)
    with pytest.raises(ValueError, match="cannot change"):
        ledger.observe_usage("group", one.invocation_id, replace(report, source_revision=2, turn_id="other"))


def test_parallel_writes_and_pagination_keep_full_aggregates(tmp_path: Path) -> None:
    ledger = store(tmp_path)
    execution = str(uuid.uuid4())
    rows = [record(execution_request_id=execution, mode="economy") for _ in range(8)]
    def write(row: UsageRecord) -> None:
        ledger.begin_usage("group", row)
        ledger.observe_usage("group", row.invocation_id, observation(1, finalized=True))
        ledger.finish_usage("group", row.invocation_id, "completed", structured=True)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(write, rows))
    legacy = replace(record(), purpose="chat")
    ledger.begin_usage("group", legacy)
    first = ledger.usage_snapshot("group", limit=3)
    second = ledger.usage_snapshot("group", cursor=first["next_cursor"], limit=3)
    assert first["summary"] == second["summary"]
    assert first["summary"]["total_tokens"] == 96
    assert first["execution_summary"]["call_count"] == 8
    assert first["by_mode"][0]["key"] == "economy"
    assert not ({row["invocation_id"] for row in first["records"]} & {row["invocation_id"] for row in second["records"]})


@pytest.mark.parametrize("windows_code", [5, 32, 33, None])
def test_usage_creation_retries_transient_windows_errors_and_saves_once(tmp_path: Path, windows_code: int | None) -> None:
    if windows_code is None and os.name != "nt":
        pytest.skip("Windows CRT EACCES without winerror")
    ledger = store(tmp_path)
    path = tmp_path / "usage-locks" / "group.lock"
    original_open = os.open
    attempts = 0
    error = PermissionError(errno.EACCES, "lock name temporarily unavailable", str(path))
    if windows_code is not None:
        error.winerror = windows_code

    def create(target: Path, flags: int, mode: int) -> int:
        nonlocal attempts
        if target == path:
            attempts += 1
            assert flags & os.O_EXCL
            if attempts <= 2:
                raise error
        return original_open(target, flags, mode)

    row = record()
    with patch("ai_orchestrator.store.os.open", side_effect=create), patch("ai_orchestrator.store.time.sleep") as sleep:
        ledger.begin_usage("group", row)
    assert attempts == 3
    assert sleep.call_count == 2
    ledger.observe_usage("group", row.invocation_id, observation(1, finalized=True))
    ledger.finish_usage("group", row.invocation_id, "completed", structured=True)
    summary = ledger.usage_snapshot("group")["summary"]
    assert summary["call_count"] == 1
    assert summary["total_tokens"] == 12
    assert not path.exists()


@pytest.mark.parametrize("busy_first", [False, True])
@pytest.mark.parametrize("windows_code", [5, None])
def test_usage_creation_permission_timeout_shares_busy_deadline_and_preserves_owner(
    tmp_path: Path, busy_first: bool, windows_code: int | None,
) -> None:
    if windows_code is None and os.name != "nt":
        pytest.skip("Windows CRT EACCES without winerror")
    ledger = store(tmp_path)
    path = tmp_path / "usage-locks" / "group.lock"
    error = PermissionError(errno.EACCES, "permanent access denied", str(path))
    if windows_code is not None:
        error.winerror = windows_code
    elapsed = 0.0
    attempts = 0

    def advance(delay: float) -> None:
        nonlocal elapsed
        elapsed += delay

    def denied(*_args: object) -> int:
        nonlocal attempts
        attempts += 1
        if busy_first and attempts <= 2:
            raise FileExistsError(errno.EEXIST, "already locked", str(path))
        raise error

    with ledger.usage_lock("group"):
        owner = path.read_bytes()
        with (patch("ai_orchestrator.store.os.open", side_effect=denied),
              patch("ai_orchestrator.store.time.monotonic", side_effect=lambda: elapsed),
              patch("ai_orchestrator.store.time.sleep", side_effect=advance)):
            with pytest.raises(PermissionError) as caught:
                ledger.begin_usage("group", record())
        assert caught.value is error
        assert elapsed == pytest.approx(5)
        assert path.read_bytes() == owner
        assert not ledger.usage_dir("group").exists()
    assert not path.exists()


def test_usage_busy_timeout_does_not_remove_live_owner(tmp_path: Path) -> None:
    ledger = store(tmp_path)
    path = tmp_path / "usage-locks" / "group.lock"
    elapsed = 0.0

    def advance(delay: float) -> None:
        nonlocal elapsed
        elapsed += delay

    with ledger.usage_lock("group"):
        owner = path.read_bytes()
        with (patch("ai_orchestrator.store.time.monotonic", side_effect=lambda: elapsed),
              patch("ai_orchestrator.store.time.sleep", side_effect=advance)):
            with pytest.raises(RunLockedError, match="operation=usage"):
                ledger.begin_usage("group", record())
        assert 5 <= elapsed <= 5.02
        assert path.read_bytes() == owner
        assert not ledger.usage_dir("group").exists()


@pytest.mark.parametrize("error_number, windows_code", [(errno.EPERM, None), (errno.ENOSPC, None), (errno.EACCES, 87)])
def test_usage_creation_does_not_retry_unrelated_errors(tmp_path: Path, error_number: int, windows_code: int | None) -> None:
    ledger = store(tmp_path)
    error = OSError(error_number, "not a transient Windows sharing error")
    if windows_code is not None:
        error.winerror = windows_code
    with patch("ai_orchestrator.store.os.open", side_effect=error) as create, patch("ai_orchestrator.store.time.sleep") as sleep:
        with pytest.raises(OSError) as caught:
            ledger.begin_usage("group", record())
    assert caught.value is error
    assert create.call_count == 1
    sleep.assert_not_called()
    assert not ledger.usage_dir("group").exists()


@pytest.mark.skipif(os.name == "nt", reason="EACCES retries without winerror are Windows only")
def test_usage_creation_does_not_retry_posix_access_denied(tmp_path: Path) -> None:
    ledger = store(tmp_path)
    error = PermissionError(errno.EACCES, "access denied")
    with patch("ai_orchestrator.store.os.open", side_effect=error) as create, patch("ai_orchestrator.store.time.sleep") as sleep:
        with pytest.raises(PermissionError) as caught:
            ledger.begin_usage("group", record())
    assert caught.value is error
    assert create.call_count == 1
    sleep.assert_not_called()


@pytest.mark.parametrize("phase", ["metadata", "record"])
def test_usage_creation_retry_does_not_repeat_metadata_or_record_writes(tmp_path: Path, phase: str) -> None:
    ledger = store(tmp_path)
    error = PermissionError(errno.EACCES, "write access denied")
    error.winerror = 5
    target = "ai_orchestrator.store.os.fsync" if phase == "metadata" else "ai_orchestrator.store.StateStore._write_json_atomic"
    with patch(target, side_effect=error) as write, patch("ai_orchestrator.store.time.sleep") as sleep:
        with pytest.raises(PermissionError) as caught:
            ledger.begin_usage("group", record())
    assert caught.value is error
    assert write.call_count == 1
    sleep.assert_not_called()
    assert not (tmp_path / "usage-locks" / "group.lock").exists()
    assert not list(ledger.usage_dir("group").glob("*.json"))


@pytest.mark.parametrize("method", ["lock", "planning_chat_lock", "project_git_lock", "effort_policy_lock", "execution_control_lock"])
def test_usage_retry_does_not_change_other_lock_acquisition(tmp_path: Path, method: str) -> None:
    ledger = store(tmp_path)
    error = PermissionError(errno.EACCES, "access denied")
    error.winerror = 5
    args = ("group", "test") if method == "lock" else ("test",) if method == "project_git_lock" else ("group",)
    with patch("ai_orchestrator.store.os.open", side_effect=error) as create, patch("ai_orchestrator.store.time.sleep") as sleep:
        with pytest.raises(PermissionError) as caught:
            with getattr(ledger, method)(*args):
                pytest.fail("must not enter a lock without exclusive creation")
    assert caught.value is error
    assert create.call_count == 1
    sleep.assert_not_called()


def _write_usage_in_process(root: Path, execution: str) -> str:
    ledger = StateStore(root)
    row = record(execution_request_id=execution)
    ledger.begin_usage("group", row)
    ledger.observe_usage("group", row.invocation_id, observation(1, finalized=True))
    snapshot = ledger.usage_snapshot("group")
    rows = [UsageRecord.from_dict(raw) for raw in snapshot["records"]]
    assert snapshot["summary"]["call_count"] == len(rows)
    assert snapshot["summary"]["total_tokens"] == sum(item.counts.total_tokens or 0 for item in rows)
    ledger.finish_usage("group", row.invocation_id, "completed", structured=True)
    return row.invocation_id


def test_parallel_processes_store_and_query_consistent_usage(tmp_path: Path) -> None:
    ledger = store(tmp_path)
    execution = str(uuid.uuid4())
    with ProcessPoolExecutor(max_workers=3, mp_context=multiprocessing.get_context("spawn")) as executor:
        futures = [executor.submit(_write_usage_in_process, tmp_path, execution) for _ in range(6)]
        identifiers = [future.result(timeout=20) for future in futures]
    snapshot = ledger.usage_snapshot("group")
    assert {row["invocation_id"] for row in snapshot["records"]} == set(identifiers)
    assert snapshot["summary"]["call_count"] == snapshot["summary"]["complete_call_count"] == 6
    assert snapshot["summary"]["total_tokens"] == 72
    assert not (tmp_path / "usage-locks" / "group.lock").exists()


def test_corruption_and_unsafe_query_inputs_do_not_become_empty_results(tmp_path: Path) -> None:
    ledger = store(tmp_path)
    for kwargs in ({"limit": True}, {"limit": 201}, {"cursor": "../state"}, {"execution_request_id": "../state"}):
        with pytest.raises(ValueError):
            ledger.usage_snapshot("group", **kwargs)
    row = record()
    ledger.begin_usage("group", row)
    path = ledger.usage_dir("group") / f"{row.invocation_id}.json"
    raw = row.to_dict()
    raw["total_tokens"] = -1
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid usage record"):
        ledger.usage_snapshot("group")


def test_current_execution_with_no_ai_call_does_not_show_previous_execution_usage(tmp_path: Path) -> None:
    ledger = store(tmp_path)
    prior, active = str(uuid.uuid4()), str(uuid.uuid4())
    row = record(execution_request_id=prior)
    ledger.begin_usage("group", row)
    ledger.observe_usage("group", row.invocation_id, observation(1, finalized=True))
    state = ledger.load("group")
    state.active_execution_request_id = active
    ledger.save(state)
    snapshot = ledger.usage_snapshot("group")
    assert snapshot["summary"]["total_tokens"] == 12
    assert snapshot["execution_request_id"] == active
    assert snapshot["execution_is_active"] is True
    assert snapshot["execution_summary"]["total_tokens"] is None
    assert snapshot["execution_summary"]["call_count"] == 0
    assert active in snapshot["execution_requests"]
    selected = ledger.usage_snapshot("group", execution_request_id=prior)
    assert selected["execution_is_active"] is False
    assert selected["execution_summary"]["total_tokens"] == 12


def test_deleted_run_is_not_recreated_by_late_usage(tmp_path: Path) -> None:
    ledger = store(tmp_path)
    row = record()
    ledger.begin_usage("group", row)
    ledger.state_path("group").unlink()
    with pytest.raises(ValueError, match="unknown run"):
        ledger.observe_usage("group", row.invocation_id, observation(1))
    assert not ledger.state_path("group").exists()
