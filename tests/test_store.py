import hashlib
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ai_orchestrator.code_style import CodeStyleTaskEvidence
from ai_orchestrator.models import (
    ArchiveCleanupStatus,
    OperationRecord,
    PlanningApplyRequest,
    PlanningApplyStatus,
    PlanningMessage,
    PlanningMessageRole,
    ProfileSource,
    RunLockState,
    RunLockStatus,
    RunState,
    RunArchive,
    Stage,
    TaskActionResult,
    TaskStatus,
    WorkTask,
)
from ai_orchestrator.progress import ProgressObservation
from ai_orchestrator.store import PlanningCacheError, PlanningChatSidecarError, RunLockedError, StateStore


class StateStoreTest(unittest.TestCase):
    def test_archive_snapshot_accepts_json_encoded_task_code_style_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            state = RunState("completed", "plan.md", "digest", "repo", "main", stage=Stage.PUSHED)
            state.tasks.append(
                WorkTask(
                    "task-1", "Implement", ["python"],
                    action_results=[TaskActionResult(
                        action="execute",
                        code_style_evidence=CodeStyleTaskEvidence(
                            changed_paths=("src/main.py",), applicable_rules=(), checks=(), rules_changed=False,
                            rule_changes=(), diagnostics=(), created_at="2026-09-23T00:00:00+00:00",
                        ),
                    )],
                )
            )
            store.save(state)

            snapshot, digest = store.save_archive_snapshot(state)

            saved = json.loads(snapshot.read_text(encoding="utf-8"))
            self.assertEqual(saved["state"]["tasks"][0]["action_results"][0]["code_style_evidence"]["changed_paths"], ["src/main.py"])
            self.assertEqual(digest, hashlib.sha256(snapshot.read_bytes()).hexdigest())

    def test_archive_snapshot_rejects_saved_payload_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            state = RunState("completed", "plan.md", "digest", "repo", "main", stage=Stage.PUSHED)
            store.save(state)

            def write_wrong_run(target: Path, payload: dict[str, object]) -> None:
                target.write_text(json.dumps({**payload, "run_id": "other"}), encoding="utf-8")

            with patch.object(store, "_write_json_atomic", side_effect=write_wrong_run):
                with self.assertRaisesRegex(OSError, "보관 snapshot 검증에 실패했습니다"):
                    store.save_archive_snapshot(state)

    def test_archive_snapshot_and_list_scopes_preserve_completed_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            active = RunState("active", "plan.md", "digest", "repo", "main", summary="active", stage=Stage.PLANNED)
            archived = RunState("archived", "plan.md", "digest", "repo", "main", summary="archived", stage=Stage.PUSHED)
            store.save(active)
            store.save(archived)
            snapshot, digest = store.save_archive_snapshot(archived)
            archived.archive = RunArchive(
                archived_at="2026-09-14T00:00:00+00:00",
                source_revision=archived.updated_at,
                snapshot_path=str(snapshot),
                manifest_path=str(store.archive_manifest_path(archived.id)),
                summary_path=str(store.archive_summary_path(archived.id)),
                fingerprint=digest,
                cleanup_status=ArchiveCleanupStatus.COMPLETED,
            )
            store.save(archived)

            self.assertTrue(snapshot.is_file())
            self.assertEqual([item.id for item in store.list_run_summaries("active")], ["active"])
            self.assertEqual([item.id for item in store.list_run_summaries("archived")], ["archived"])
            self.assertEqual(store.list_run_summaries("archived")[0].cleanup_status, "completed")

    def test_operation_record_claim_is_atomic_and_round_trips_updates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            record = OperationRecord(
                request_id="43aa358f-e93d-44fe-a98f-e53fcb926992",
                run_id="run-1",
                action="merge",
                digest="digest",
                phase="applying_main",
            )
            claimed, created = store.claim_operation(record)
            repeated, repeated_created = store.claim_operation(record)
            self.assertTrue(created)
            self.assertIs(claimed, record)
            self.assertFalse(repeated_created)
            self.assertEqual(repeated.digest, "digest")
            self.assertIsNone(repeated.progress_observation)
            record.progress_observation = ProgressObservation(
                attempt_id=record.request_id, invocation_id="invocation-1", phase="reading_documents",
                last_event_received_at="2026-09-25T00:00:05+00:00",
                last_activity_changed_at="2026-09-25T00:00:00+00:00",
            )
            record.update("main_applied", status="succeeded")
            store.save_operation(record)
            restored = store.load_operation(record.run_id, record.request_id)
            self.assertIsNotNone(restored)
            assert restored is not None
            self.assertEqual((restored.phase, restored.status), ("main_applied", "succeeded"))
            self.assertEqual(restored.progress_observation, record.progress_observation)

    def test_operation_result_and_latest_record_are_bounded_to_valid_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            first = OperationRecord(
                request_id="43aa358f-e93d-44fe-a98f-e53fcb926992",
                run_id="run-1",
                action="recovery_preview",
                digest="first",
                phase="checking_failure",
            )
            second = OperationRecord(
                request_id="fdb2e403-6141-4cec-868f-723be1c33d5e",
                run_id="run-1",
                action="recovery_preview",
                digest="second",
                phase="preview_ready",
                created_at="2099-01-01T00:00:00+00:00",
            )
            store.claim_operation(first)
            store.claim_operation(second)
            second.result_ref = store.save_operation_result(second.run_id, second.request_id, {"fingerprint": "plan"})
            second.update("preview_ready", status="succeeded")
            store.save_operation(second)

            latest = store.latest_operation("run-1", "recovery_preview")

            self.assertIsNotNone(latest)
            assert latest is not None
            self.assertEqual(latest.request_id, second.request_id)
            self.assertEqual(store.load_operation_result(latest), {"fingerprint": "plan"})
            self.assertEqual([record.request_id for record in store.recent_operations("run-1", "recovery_preview", limit=1)],
                             [second.request_id])
            self.assertEqual([record.request_id for record in store.recent_operations("run-1", "recovery_preview")],
                             [second.request_id, first.request_id])
            self.assertEqual(store.recent_operations("another-run", "recovery_preview"), [])
            self.assertEqual(store.recent_operations("run-1", "another-action"), [])
            with self.assertRaises(ValueError):
                store.recent_operations("run-1", "recovery_preview", limit=0)
            with self.assertRaises(ValueError):
                store.operation_result_path("run-1", "../outside")

    def test_latest_operation_uses_creation_order_within_the_same_second(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            newest = OperationRecord(
                request_id="00000000-0000-4000-8000-000000000001", run_id="run-1",
                action="merge", digest="new", phase="cleanup_completed",
            )
            self.assertRegex(newest.created_at, r"\.\d{6}\+00:00$")
            self.assertGreaterEqual(newest.updated_at, newest.created_at)
            older = OperationRecord(
                request_id="ffffffff-ffff-4fff-8fff-ffffffffffff", run_id="run-1",
                action="merge", digest="old", phase="pushing",
                created_at=newest.created_at.split(".", 1)[0] + "+00:00",
            )
            store.claim_operation(older)
            store.claim_operation(newest)

            latest = store.latest_operation("run-1", "merge")

            self.assertIsNotNone(latest)
            assert latest is not None
            self.assertEqual(latest.request_id, newest.request_id)
            self.assertEqual(latest.phase, "cleanup_completed")

    def test_project_git_lock_is_exclusive_and_released(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            with store.project_git_lock("first"):
                self.assertTrue(store.project_git_lock_path().is_file())
                with self.assertRaisesRegex(RunLockedError, "project Git"):
                    with store.project_git_lock("second"):
                        pass
            self.assertFalse(store.project_git_lock_path().exists())

    def test_project_git_lock_clear_requires_confirmed_stale_merge_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            path = store.project_git_lock_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "token": "original", "pid": 999999, "host": socket.gethostname(),
                "operation": "merge", "acquired_at": "2026-09-25T00:00:00+00:00",
            }) + "\n", encoding="utf-8")

            with patch.object(StateStore, "_pid_is_alive", return_value=False):
                self.assertEqual(store.inspect_project_git_lock().state, RunLockState.STALE)
                with self.assertRaisesRegex(RunLockedError, "not safe to clear"):
                    store.clear_stale_project_git_lock(expected_operation="push")
                self.assertTrue(path.exists())
                self.assertEqual(store.clear_stale_project_git_lock(expected_operation="merge").state, RunLockState.UNLOCKED)
            self.assertFalse(path.exists())
            with store.project_git_lock("merge"):
                with self.assertRaisesRegex(RunLockedError, "not safe to clear"):
                    store.clear_stale_project_git_lock(expected_operation="merge")

    def test_state_and_chat_retry_transient_windows_replacement_errors(self) -> None:
        for chat in (False, True):
            for code in (5, 32, 33):
                with self.subTest(chat=chat, code=code), tempfile.TemporaryDirectory() as directory:
                    store = StateStore(Path(directory))
                    state = RunState(id="run-1", spec_path="plan", spec_digest="abc", repo_path="repo", main_branch="main", stage=Stage.EXECUTING)
                    save = store.save_planning_chat if chat else store.save
                    save(state)
                    target = store.planning_chat_path(state.id) if chat else store.state_path(state.id)
                    before = target.read_text(encoding="utf-8")
                    state.planning_messages.append(PlanningMessage(PlanningMessageRole.USER, "new message"))
                    original_replace = Path.replace
                    attempts = []

                    def replace(temporary, destination):
                        attempts.append(temporary)
                        self.assertEqual(target.read_text(encoding="utf-8"), before)
                        if len(attempts) < 3:
                            error = PermissionError("file temporarily locked")
                            error.winerror = code
                            raise error
                        return original_replace(temporary, destination)

                    with patch.object(Path, "replace", new=replace), patch("ai_orchestrator.store.time.sleep") as sleep:
                        save(state)
                    self.assertEqual(len(attempts), 3)
                    self.assertEqual(sleep.call_count, 2)
                    self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["planning_messages"][0]["text"], "new message")
                    self.assertEqual(list(target.parent.glob("*.tmp")), [])

    def test_failed_replacement_preserves_target_and_recoverable_payload(self) -> None:
        for windows in (False, True):
            with self.subTest(windows=windows), tempfile.TemporaryDirectory() as directory:
                store = StateStore(Path(directory))
                state = RunState(id="run-1", spec_path="plan", spec_digest="abc", repo_path="repo", main_branch="main", stage=Stage.EXECUTING)
                store.save_planning_chat(state)
                target = store.planning_chat_path(state.id)
                before = target.read_text(encoding="utf-8")
                state.planning_messages.append(PlanningMessage(PlanningMessageRole.USER, "preserved message"))
                error = PermissionError("permanent access denied")
                if windows:
                    error.winerror = 5
                with patch.object(Path, "replace", side_effect=error) as replace, patch("ai_orchestrator.store.time.sleep") as sleep:
                    with self.assertRaisesRegex(OSError, "임시 파일에 보존") as caught:
                        store.save_planning_chat(state)
                self.assertIs(caught.exception.__cause__, error)
                self.assertEqual(replace.call_count, 6 if windows else 1)
                self.assertEqual(sleep.call_count, 5 if windows else 0)
                self.assertEqual(target.read_text(encoding="utf-8"), before)
                pending = list(target.parent.glob("*.tmp"))
                self.assertEqual(len(pending), 1)
                self.assertIn(str(pending[0]), str(caught.exception))
                self.assertEqual(json.loads(pending[0].read_text(encoding="utf-8"))["planning_messages"][0]["text"], "preserved message")

    @unittest.skipUnless(os.name == "nt", "Windows file sharing semantics")
    def test_windows_reader_lock_is_retried_until_handle_closes(self) -> None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            state = RunState(id="run-1", spec_path="plan", spec_digest="abc", repo_path="repo", main_branch="main", stage=Stage.EXECUTING)
            store.save_planning_chat(state)
            target = store.planning_chat_path(state.id)
            # READ/WRITE sharing deliberately excludes
            # FILE_SHARE_DELETE.
            handle = kernel32.CreateFileW(str(target), 0x80000000, 3, None, 3, 0, None)
            self.assertNotEqual(handle, wintypes.HANDLE(-1).value)

            def release(_delay):
                nonlocal handle
                if handle is not None:
                    self.assertTrue(kernel32.CloseHandle(handle))
                    handle = None

            try:
                state.planning_messages.append(PlanningMessage(PlanningMessageRole.USER, "saved after reader closed"))
                with patch("ai_orchestrator.store.time.sleep", side_effect=release) as sleep:
                    store.save_planning_chat(state)
                self.assertGreaterEqual(sleep.call_count, 1)
                self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["planning_messages"][0]["text"], "saved after reader closed")
            finally:
                release(0)

    def test_planning_result_cache_round_trip_and_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            key = "a" * 64

            self.assertIsNone(store.load_planning_result(key))
            path = store.save_planning_result(key, 'AI_PLAN_RESULT: {"tasks":[]}')

            self.assertEqual(store.load_planning_result(key), 'AI_PLAN_RESULT: {"tasks":[]}')
            self.assertEqual(list(path.parent.glob("*.tmp")), [])
            path.write_text("not-json", encoding="utf-8")
            with self.assertRaisesRegex(PlanningCacheError, "invalid planning result cache"):
                store.load_planning_result(key)
            with self.assertRaisesRegex(PlanningCacheError, "invalid.*key"):
                store.planning_cache_path("outside")

    def test_save_replaces_state_without_leaving_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            state = RunState(id="run-1", spec_path="plan.md", spec_digest="abc", repo_path="repo", main_branch="main", stage=Stage.RECEIVED)
            store.save(state)
            state.transition(Stage.PLANNED, "planned")

            store.save(state)
            restored = store.load(state.id)

            self.assertEqual(restored.stage, Stage.PLANNED)
            self.assertFalse(store.state_path(state.id).with_suffix(".tmp").exists())

    def test_unknown_run_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            with self.assertRaisesRegex(ValueError, "unknown run"):
                store.load("missing")

    def test_planning_chat_sidecar_overlays_live_run_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            state = RunState(
                id="run-1", spec_path="plan.md", spec_digest="abc", repo_path="repo", main_branch="main",
                stage=Stage.EXECUTING, planning_profile_source=ProfileSource.ROUTING,
            )
            store.save(state)
            state.planning_messages.append(PlanningMessage(role=PlanningMessageRole.USER, text="실행 상태를 설명해줘."))
            state.planning_follow_up_requests.append("후속 Task로 저장해줘.")
            state.planning_conversation_revision = 3
            state.planning_profile_source = ProfileSource.MANUAL
            state.planning_applied_conversation_revision = 1
            state.planning_apply_requests.append(
                PlanningApplyRequest(
                    request_id="apply-queued",
                    conversation_revision=3,
                    plan_revision=2,
                    context_snapshot="saved conversation",
                    status=PlanningApplyStatus.QUEUED,
                )
            )
            state.add_event("planning", "execution planning chat message received")

            with store.lock(state.id, "execute"):
                with store.planning_chat_lock(state.id):
                    store.save_planning_chat(state)

            restored = store.load(state.id)
            self.assertEqual(restored.planning_messages[-1].text, "실행 상태를 설명해줘.")
            self.assertEqual(restored.planning_follow_up_requests, ["후속 Task로 저장해줘."])
            self.assertEqual(restored.planning_conversation_revision, 3)
            self.assertEqual(restored.planning_profile_source, ProfileSource.MANUAL)
            self.assertEqual(restored.planning_applied_conversation_revision, 1)
            self.assertEqual(restored.planning_apply_requests[0].request_id, "apply-queued")
            self.assertEqual(restored.planning_apply_requests[0].status, PlanningApplyStatus.QUEUED)
            self.assertTrue(any(event.message == "execution planning chat message received" for event in restored.events))
            sidecar_path = store.planning_chat_path(state.id)
            old_sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            old_sidecar.pop("planning_profile_source")
            sidecar_path.write_text(json.dumps(old_sidecar), encoding="utf-8")
            self.assertEqual(store.load(state.id).planning_profile_source, ProfileSource.ROUTING)
            old_sidecar["planning_effort_baseline_reasoning"] = 3
            sidecar_path.write_text(json.dumps(old_sidecar), encoding="utf-8")
            with self.assertRaises(PlanningChatSidecarError):
                store.load(state.id)

    def test_older_planning_sidecar_cannot_erase_a_later_saved_choice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            state = RunState(id="choice", spec_path="plan.md", spec_digest="abc", repo_path="repo", main_branch="main", stage=Stage.PLANNED)
            state.planning_messages.append(PlanningMessage(role=PlanningMessageRole.USER, text="메모 앱"))
            state.planning_conversation_revision = 1
            store.save(state)
            store.save_planning_chat(state)
            state.planning_messages.append(PlanningMessage(role=PlanningMessageRole.USER, text="추천 구성으로 진행"))
            state.planning_conversation_revision = 2
            store.save(state)
            restored = store.load(state.id)
            self.assertEqual(restored.planning_conversation_revision, 2)
            self.assertEqual(restored.planning_messages[-1].text, "추천 구성으로 진행")

    def test_corrupt_planning_chat_sidecar_is_not_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            state = RunState(id="run-1", spec_path="plan.md", spec_digest="abc", repo_path="repo", main_branch="main", stage=Stage.EXECUTING)
            store.save(state)
            store.planning_chat_path(state.id).write_text("not-json\n", encoding="utf-8")

            with self.assertRaises(PlanningChatSidecarError):
                store.load(state.id)

    def test_run_summaries_omit_full_task_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            state = RunState(
                id="run-1",
                spec_path="plan.md",
                spec_digest="abc",
                repo_path="repo",
                main_branch="main",
                stage=Stage.EXECUTING,
                summary="작업 그룹",
                tasks=[
                    WorkTask(id="done", title="완료", capabilities=["backend"], status=TaskStatus.COMPLETED),
                    WorkTask(id="pending", title="대기", capabilities=["backend"]),
                ],
            )
            store.save(state)

            with patch.object(RunState, "from_dict", side_effect=AssertionError("full RunState parsing is not allowed")):
                summaries = store.list_run_summaries()

            self.assertEqual(len(summaries), 1)
            self.assertEqual(summaries[0].id, state.id)
            self.assertEqual(summaries[0].summary, "작업 그룹")
            self.assertEqual(summaries[0].task_count, 2)
            self.assertEqual(summaries[0].completed_task_count, 1)

    def test_delete_removes_only_exact_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            state = RunState(id="run-1", spec_path="plan.md", spec_digest="abc", repo_path="repo", main_branch="main", stage=Stage.PLANNED)
            store.save(state)
            sibling = store.run_dir("run-2")
            sibling.mkdir(parents=True)
            (sibling / "keep.txt").write_text("keep", encoding="utf-8")

            store.delete(state.id)

            self.assertFalse(store.run_dir(state.id).exists())
            self.assertTrue((sibling / "keep.txt").is_file())
            with self.assertRaisesRegex(ValueError, "invalid run id"):
                store.delete("../outside")

    def test_corrupt_state_is_not_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            path = store.state_path("broken")
            path.parent.mkdir(parents=True)
            path.write_text("not-json\n", encoding="utf-8")

            with self.assertRaises(json.JSONDecodeError):
                store.load("broken")

    def test_run_lock_blocks_duplicate_and_releases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))

            with store.lock("run-1", "execute"):
                metadata = json.loads(store.lock_path("run-1").read_text(encoding="utf-8"))
                self.assertEqual(metadata["operation"], "execute")
                with self.assertRaisesRegex(RunLockedError, "operation=execute"):
                    with store.lock("run-1", "merge"):
                        self.fail("duplicate lock was acquired")

            self.assertFalse(store.lock_path("run-1").exists())

    def test_run_lock_releases_after_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))

            with self.assertRaisesRegex(RuntimeError, "boom"):
                with store.lock("run-1", "execute"):
                    raise RuntimeError("boom")

            self.assertFalse(store.lock_path("run-1").exists())

    def test_planning_chat_lock_recovers_only_stale_local_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            path = store.planning_chat_lock_path("run-1")
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "token": "stale-token",
                        "pid": 999999,
                        "host": socket.gethostname(),
                        "operation": "planning-chat",
                        "acquired_at": "2026-09-02T00:00:00+00:00",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            with patch.object(StateStore, "_pid_is_alive", return_value=False):
                with store.planning_chat_lock("run-1"):
                    current = json.loads(path.read_text(encoding="utf-8"))
                    self.assertNotEqual(current["token"], "stale-token")

            self.assertFalse(path.exists())

    def test_inspect_reports_current_process_lock_as_active(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))

            with store.lock("run-1", "execute"):
                status = store.inspect_lock("run-1")

            self.assertEqual(status.state, RunLockState.ACTIVE)
            self.assertEqual(status.pid, os.getpid())
            self.assertEqual(status.operation, "execute")

    def test_clear_removes_only_confirmed_stale_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            self._write_lock(store, "run-1")

            with patch.object(StateStore, "_pid_is_alive", return_value=False):
                status = store.inspect_lock("run-1")
                cleared = store.clear_stale_lock("run-1")

            self.assertEqual(status.state, RunLockState.STALE)
            self.assertEqual(cleared.state, RunLockState.UNLOCKED)
            self.assertFalse(store.lock_path("run-1").exists())

    def test_clear_is_idempotent_when_lock_is_already_unlocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))

            cleared = store.clear_stale_lock("run-1")

            self.assertEqual(cleared.state, RunLockState.UNLOCKED)

    def test_clear_is_idempotent_when_stale_lock_disappears_during_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            stale = RunLockStatus(
                run_id="run-1",
                state=RunLockState.STALE,
                operation="execute",
                pid=999999,
                host=socket.gethostname(),
                acquired_at="2026-08-25T00:00:00+00:00",
                reason="owner process is not running",
            )
            unlocked = RunLockStatus(run_id="run-1", state=RunLockState.UNLOCKED, reason="no run lock exists")

            with (
                patch.object(store, "inspect_lock", side_effect=[stale, unlocked]),
                patch.object(store, "_read_lock", side_effect=[{"token": "old"}, {}]),
            ):
                cleared = store.clear_stale_lock("run-1")

            self.assertEqual(cleared.state, RunLockState.UNLOCKED)

    def test_clear_refuses_active_other_host_and_malformed_locks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            with store.lock("active", "execute"):
                with self.assertRaisesRegex(RunLockedError, "active"):
                    store.clear_stale_lock("active")

            self._write_lock(store, "remote", host="another-host")
            remote = store.inspect_lock("remote")
            self.assertEqual(remote.state, RunLockState.UNVERIFIABLE)
            with self.assertRaisesRegex(RunLockedError, "unverifiable"):
                store.clear_stale_lock("remote")

            malformed_path = store.lock_path("malformed")
            malformed_path.parent.mkdir(parents=True)
            malformed_path.write_text("{}\n", encoding="utf-8")
            malformed = store.inspect_lock("malformed")
            self.assertEqual(malformed.state, RunLockState.MALFORMED)
            with self.assertRaisesRegex(RunLockedError, "malformed"):
                store.clear_stale_lock("malformed")

    def test_clear_refuses_lock_when_token_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(Path(directory))
            self._write_lock(store, "run-1", token="old")
            stale = RunLockStatus(
                run_id="run-1",
                state=RunLockState.STALE,
                operation="execute",
                pid=999999,
                host=socket.gethostname(),
                acquired_at="2026-08-25T00:00:00+00:00",
                reason="owner process is not running",
            )

            with (
                patch.object(store, "inspect_lock", side_effect=[stale, stale]),
                patch.object(store, "_read_lock", side_effect=[{"token": "old"}, {"token": "new"}]),
            ):
                with self.assertRaisesRegex(RunLockedError, "changed"):
                    store.clear_stale_lock("run-1")

            self.assertTrue(store.lock_path("run-1").exists())

    @staticmethod
    def _write_lock(store: StateStore, run_id: str, *, host: str | None = None, token: str = "token") -> None:
        path = store.lock_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "token": token,
                    "pid": 999999,
                    "host": host or socket.gethostname(),
                    "operation": "execute",
                    "acquired_at": "2026-08-25T00:00:00+00:00",
                }
            )
            + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
