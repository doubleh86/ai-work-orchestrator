import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from ai_orchestrator.models import (
    EffortMode,
    EffortPolicyState,
    EffortPolicyRevisionError,
    EffortProfileSnapshot,
    EffortReviewSnapshot,
    ProfileSource,
    ResolvedEffortPolicy,
    RunState,
    Stage,
    utc_now,
)
from ai_orchestrator.store import RunLockedError, StateStore


class EffortPolicyStoreTest(unittest.TestCase):
    def test_policy_lock_does_not_remove_a_live_owner_after_bounded_wait(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            with store.effort_policy_lock("run-1"):
                original = store.effort_policy_lock_path("run-1").read_bytes()
                with patch("ai_orchestrator.store.time.monotonic", side_effect=[0, 3]):
                    with self.assertRaisesRegex(RunLockedError, "operation=effort-policy"):
                        with store.effort_policy_lock("run-1"):
                            self.fail("active policy owner must remain locked")
                self.assertEqual(store.effort_policy_lock_path("run-1").read_bytes(), original)

    def test_policy_lock_does_not_wait_or_delete_foreign_unknown_or_malformed_owners(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            with store.effort_policy_lock("run-1"):
                path = store.effort_policy_lock_path("run-1")
                original = path.read_text(encoding="utf-8")
                for variant in ("foreign", "unknown", "malformed"):
                    with self.subTest(variant=variant):
                        metadata = json.loads(original)
                        if variant == "foreign": metadata["host"] = "other-host"
                        if variant == "malformed": metadata.pop("pid")
                        path.write_text(json.dumps(metadata), encoding="utf-8")
                        expected = path.read_bytes()
                        with (patch.object(store, "_pid_is_alive", return_value=None if variant == "unknown" else True),
                              patch("ai_orchestrator.store.time.sleep") as sleep):
                            with self.assertRaises(RunLockedError):
                                with store.effort_policy_lock("run-1"):
                                    self.fail("unverified owner must remain locked")
                            sleep.assert_not_called()
                        self.assertEqual(path.read_bytes(), expected)
                path.write_text(original, encoding="utf-8")

    def test_policy_lock_does_not_replay_a_failing_write_body(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            calls = []
            with self.assertRaisesRegex(RunLockedError, "body failure"):
                with store.effort_policy_lock("run-1"):
                    calls.append("write")
                    raise RunLockedError("body failure")
            self.assertEqual(calls, ["write"])
            self.assertFalse(store.effort_policy_lock_path("run-1").exists())

    POLICY_ID = "d7cb92b0-6f87-464a-9b8a-36837143fa65"
    EXECUTION_ID = "98e6dc75-b5ea-4aa3-bc91-54e986b45b15"
    RESERVATION_ID = "74dc4c4f-38d1-47c8-b91b-0c0b40d7e527"

    def _store(self, root: Path) -> StateStore:
        store = StateStore(root)
        store.save(RunState("run-1", "plan.md", "digest", "repo", "main", stage=Stage.PLANNED))
        return store

    def _policy(self, *, mode: EffortMode = EffortMode.FOCUSED) -> ResolvedEffortPolicy:
        profile = EffortProfileSnapshot("worker", "codex", "gpt-6-sol", "high", ProfileSource.MODE)
        return ResolvedEffortPolicy(
            policy_id=self.POLICY_ID,
            policy_version=1,
            mode=mode,
            scope="execution",
            plan_revision=0,
            planning_profile=None,
            task_profiles=(("t01", profile),),
            review_decisions=(EffortReviewSnapshot("t01", False, True, "focused_code_change_review", "reviewer", True, False),),
            manual_exception_ids=(),
            unsupported_effects=(),
            resolved_at=utc_now(),
        )

    def test_new_snapshot_records_reviewer_profile_and_reads_v1(self) -> None:
        legacy = self._policy()
        self.assertEqual(ResolvedEffortPolicy.from_dict(legacy.to_dict()), legacy)
        review = replace(
            legacy.review_decisions[0], reviewer_provider_id="local-review", reviewer_model="review-model"
        )
        current = replace(legacy, policy_version=2, review_decisions=(review,))
        restored = ResolvedEffortPolicy.from_dict(current.to_dict())
        self.assertEqual(restored, current)
        self.assertEqual(restored.review_decisions[0].reviewer_provider_id, "local-review")
        broken = current.to_dict()
        broken["review_decisions"][0].pop("reviewer_provider_id")
        with self.assertRaisesRegex(ValueError, "invalid effort review snapshot"):
            ResolvedEffortPolicy.from_dict(broken)

    def test_legacy_run_has_no_mode_or_sidecar_until_explicit_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))

            state = store.load_effort_policy("run-1")

            self.assertEqual(state.revision, 0)
            self.assertIsNone(state.selected_mode)
            self.assertIsNone(state.pending_execution_mode)
            self.assertFalse(store.effort_policy_path("run-1").exists())
            legacy_run = store.load("run-1").to_dict()
            legacy_run["schema_version"] = 33
            legacy_run.pop("active_policy_id")
            legacy_run.pop("active_execution_request_id")
            restored = RunState.from_dict(legacy_run)
            self.assertEqual((restored.active_policy_id, restored.active_execution_request_id), ("", ""))

    def test_selection_reservation_cancel_and_restart_preserve_each_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = self._store(root)
            select_id = "78d417f6-920c-442f-a177-ea3111d04119"
            reserve_id = "74dc4c4f-38d1-47c8-b91b-0c0b40d7e527"
            cancel_id = "5a60dbe1-5a92-41d4-a8e6-94a912639870"

            selected = store.set_effort_mode("run-1", "balanced", target="planning", expected_revision=0, request_id=select_id)
            reserved = store.set_effort_mode("run-1", "focused", target="next_execution", expected_revision=1, request_id=reserve_id)
            restarted = StateStore(root)
            self.assertEqual(restarted.load_effort_policy("run-1").view(), reserved)
            self.assertEqual((reserved.selected_mode, reserved.pending_execution_mode), (EffortMode.BALANCED, EffortMode.FOCUSED))
            self.assertEqual(reserved.pending_request_id, reserve_id)

            cancelled = restarted.cancel_effort_reservation("run-1", expected_revision=2, request_id=cancel_id)
            self.assertEqual((cancelled.revision, cancelled.selected_mode, cancelled.pending_execution_mode), (3, EffortMode.BALANCED, None))
            self.assertEqual(restarted.load_effort_policy("run-1").view(), cancelled)
            self.assertEqual(
                restarted.set_effort_mode("run-1", "balanced", target="planning", expected_revision=0, request_id=select_id), selected
            )
            self.assertEqual(restarted.cancel_effort_reservation("run-1", expected_revision=2, request_id=cancel_id), cancelled)
            self.assertEqual(restarted.load_effort_policy("run-1").revision, 3)

    def test_stale_revision_and_request_reuse_leave_saved_state_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            request_id = "bf3b214e-4980-4122-8e69-59cde2ca7550"
            store.set_effort_mode("run-1", "economy", target="planning", expected_revision=0, request_id=request_id)
            original = store.effort_policy_path("run-1").read_bytes()

            with self.assertRaises(EffortPolicyRevisionError):
                store.set_effort_mode(
                    "run-1", "focused", target="planning", expected_revision=0,
                    request_id="0f096b7c-fdbc-4b44-abf4-8e0094af67b8",
                )
            with self.assertRaisesRegex(ValueError, "different effort policy change"):
                store.set_effort_mode("run-1", "focused", target="planning", expected_revision=0, request_id=request_id)
            with self.assertRaisesRegex(ValueError, "no effort mode reservation"):
                store.cancel_effort_reservation(
                    "run-1", expected_revision=1, request_id="c01e79d2-d579-4283-8962-913b2b7a172a"
                )
            self.assertEqual(store.effort_policy_path("run-1").read_bytes(), original)

    def test_reservation_does_not_wait_for_long_run_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            with store.lock("run-1", "fixture-execution"):
                result = store.set_effort_mode(
                    "run-1", "focused", target="next_execution", expected_revision=0,
                    request_id="293b37db-145d-444c-8240-29e4afbd4929",
                )
            self.assertEqual(result.pending_execution_mode, EffortMode.FOCUSED)
            self.assertEqual(store.load_effort_policy("run-1").view(), result)

    def test_corrupt_or_unsupported_sidecar_is_not_treated_as_legacy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            request_id = "c375f42f-990d-45db-9d7c-adb27c0bb50a"
            store.set_effort_mode("run-1", "balanced", target="planning", expected_revision=0, request_id=request_id)
            path = store.effort_policy_path("run-1")
            valid = json.loads(path.read_text(encoding="utf-8"))
            for payload in (
                {**valid, "schema_version": 3},
                {**valid, "revision": 2},
                {**valid, "prepared_policies": {"unexpected": {}}},
                {**valid, "mutation_receipts": []},
            ):
                with self.subTest(payload=payload):
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "invalid effort policy sidecar"):
                        store.load_effort_policy("run-1")
            path.write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid effort policy sidecar"):
                store.load_effort_policy("run-1")

    def test_write_failure_preserves_previous_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            request_id = "43f9f3ee-a476-4e64-8536-e42750518eb6"
            store.set_effort_mode("run-1", "balanced", target="planning", expected_revision=0, request_id=request_id)
            original = store.effort_policy_path("run-1").read_bytes()
            with patch.object(store, "_write_json_atomic", side_effect=OSError("fixture write failure")):
                with self.assertRaisesRegex(OSError, "fixture write failure"):
                    store.set_effort_mode(
                        "run-1", "focused", target="next_execution", expected_revision=1,
                        request_id="ba52009a-1d2c-4f30-9285-69aec05f1a26",
                    )
            self.assertEqual(store.effort_policy_path("run-1").read_bytes(), original)

    def test_policy_lock_coordinates_delete_without_recreating_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            with store.effort_policy_lock("run-1"):
                with self.assertRaises(RunLockedError):
                    store.delete("run-1")
            self.assertTrue(store.state_path("run-1").exists())

            store.delete("run-1")
            self.assertFalse(store.run_dir("run-1").exists())
            with self.assertRaisesRegex(ValueError, "unknown run"):
                store.set_effort_mode(
                    "run-1", "balanced", target="planning", expected_revision=0,
                    request_id="f3b23557-b062-4e96-984d-c2af8b311921",
                )
            self.assertFalse(store.run_dir("run-1").exists())

    def test_invalid_run_id_does_not_escape_store_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            with self.assertRaisesRegex(ValueError, "invalid effort policy run id"):
                store.effort_policy_path("../outside")
            with self.assertRaisesRegex(ValueError, "invalid effort policy run id"):
                store.effort_policy_lock_path("../outside")

    def test_execution_binding_requires_saved_run_reference_before_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = self._store(root)
            store.set_effort_mode("run-1", "focused", target="planning", expected_revision=0, request_id=self.RESERVATION_ID)
            policy = self._policy()
            prepared = store.prepare_effort_execution(
                "run-1", policy, execution_request_id=self.EXECUTION_ID, expected_revision=1
            )
            self.assertEqual(prepared.status, "prepared")
            self.assertEqual(
                StateStore(root).prepare_effort_execution(
                    "run-1", policy, execution_request_id=self.EXECUTION_ID, expected_revision=1
                ), prepared
            )
            with self.assertRaisesRegex(ValueError, "different effort policy binding"):
                store.prepare_effort_execution(
                    "run-1", policy, execution_request_id=self.EXECUTION_ID, expected_revision=0
                )
            with self.assertRaisesRegex(ValueError, "RunState does not reference"):
                store.start_effort_execution("run-1", self.EXECUTION_ID)
            self.assertEqual(store.load_effort_policy("run-1").binding(self.EXECUTION_ID).status, "prepared")

            run = store.load("run-1")
            run.active_policy_id = policy.policy_id
            run.active_execution_request_id = self.EXECUTION_ID
            store.save(run)
            self.assertEqual(StateStore(root).load("run-1").active_policy_id, policy.policy_id)
            self.assertEqual(StateStore(root).load("run-1").active_execution_request_id, self.EXECUTION_ID)
            started = StateStore(root).start_effort_execution("run-1", self.EXECUTION_ID)
            self.assertEqual(started.status, "started")
            self.assertEqual(store.start_effort_execution("run-1", self.EXECUTION_ID), started)
            self.assertEqual(store.load_effort_policy("run-1").revision, 1)
            self.assertEqual(store.finish_effort_execution("run-1", self.EXECUTION_ID).status, "finished")
            self.assertEqual(StateStore(root).finish_effort_execution("run-1", self.EXECUTION_ID).status, "finished")

    def test_start_consumes_only_the_prepared_reservation_and_preserves_new_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = self._store(root)
            store.set_effort_mode("run-1", "focused", target="next_execution", expected_revision=0, request_id=self.RESERVATION_ID)
            policy = self._policy()
            prepared = store.prepare_effort_execution(
                "run-1", policy, execution_request_id=self.EXECUTION_ID, expected_revision=1
            )
            self.assertEqual(prepared.reservation_request_id, self.RESERVATION_ID)
            newer_id = "a68d9e58-b0e3-4406-870a-1cb9f37b6f40"
            store.set_effort_mode("run-1", "economy", target="next_execution", expected_revision=1, request_id=newer_id)
            run = store.load("run-1")
            run.active_policy_id = policy.policy_id
            run.active_execution_request_id = self.EXECUTION_ID
            store.save(run)

            store.start_effort_execution("run-1", self.EXECUTION_ID)
            restored = StateStore(root).load_effort_policy("run-1")
            self.assertEqual(restored.pending_execution_mode, EffortMode.ECONOMY)
            self.assertEqual(restored.pending_request_id, newer_id)
            self.assertEqual(restored.revision, 2)
            self.assertEqual(restored.binding(self.EXECUTION_ID).status, "started")

    def test_saved_profile_recovery_preserves_reservation_through_prepare_start_finish_and_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = self._store(root)
            store.set_effort_mode("run-1", "balanced", target="planning", expected_revision=0, request_id=self.RESERVATION_ID)
            store.set_effort_mode("run-1", "focused", target="next_execution", expected_revision=1, request_id=self.EXECUTION_ID)
            before = store.load_effort_policy("run-1").view()
            policy = self._policy(mode=EffortMode.BALANCED)
            recovery_id = "e8b4b2c3-6453-4d3f-bf29-d64ac045360b"
            with self.assertRaisesRegex(ValueError, "existing task execution"):
                store.prepare_effort_execution(
                    "run-1", policy, execution_request_id=recovery_id, expected_revision=2, preserve_reservation=True,
                )
            run = store.load("run-1")
            run.stage = Stage.EXECUTING
            store.save(run)
            binding = store.prepare_effort_execution(
                "run-1", policy, execution_request_id=recovery_id, expected_revision=2, preserve_reservation=True,
            )
            self.assertEqual(binding.reservation_request_id, "")
            run.active_policy_id, run.active_execution_request_id = policy.policy_id, recovery_id
            store.save(run)
            StateStore(root).start_effort_execution("run-1", recovery_id)
            store.finish_effort_execution("run-1", recovery_id)
            restored = StateStore(root).load_effort_policy("run-1")
            self.assertEqual(restored.view(), before)
            self.assertEqual(restored.binding(recovery_id).status, "finished")

    def test_recovery_reuses_the_last_applied_mode_when_a_previous_reservation_was_consumed(self) -> None:
        state, _ = EffortPolicyState().set_mode("balanced", target="planning", expected_revision=0, request_id=self.RESERVATION_ID)
        state, _ = state.set_mode("focused", target="next_execution", expected_revision=1, request_id=self.EXECUTION_ID)
        previous = self._policy()
        request_id = "e8b4b2c3-6453-4d3f-bf29-d64ac045360b"
        state, _ = state.prepare_execution(previous, execution_request_id=request_id, expected_revision=2)
        state, _ = state.start_execution(request_id)
        state, _ = state.finish_execution(request_id)
        state, _ = state.set_mode(
            "economy", target="next_execution", expected_revision=3, request_id="1956190d-c14b-4322-9345-b489e57fc91f",
        )
        before = state.view()
        recovered = replace(previous, policy_id="a375ec26-72d6-4bd2-841a-03d99f1ac220")
        state, binding = state.prepare_execution(
            recovered, execution_request_id="35035651-f5dc-4372-aa24-9c88809c1af6", expected_revision=4, preserve_reservation=True,
        )
        state, _ = state.start_execution(binding.execution_request_id)
        restored = EffortPolicyState.from_dict(state.to_dict())
        self.assertEqual(restored.view(), before)
        self.assertEqual(restored.policy(binding.policy_id).mode, EffortMode.FOCUSED)
        self.assertEqual(binding.reservation_request_id, "")

    def test_start_consumes_matching_reservation_and_replays_mutation_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = self._store(root)
            store.set_effort_mode("run-1", "focused", target="next_execution", expected_revision=0, request_id=self.RESERVATION_ID)
            policy = self._policy()
            store.prepare_effort_execution("run-1", policy, execution_request_id=self.EXECUTION_ID, expected_revision=1)
            run = store.load("run-1")
            run.active_policy_id = policy.policy_id
            run.active_execution_request_id = self.EXECUTION_ID
            store.save(run)

            started = store.start_effort_execution("run-1", self.EXECUTION_ID.upper())
            self.assertEqual(started.status, "started")
            restored = StateStore(root).load_effort_policy("run-1")
            self.assertIsNone(restored.pending_execution_mode)
            self.assertEqual(restored.revision, 2)
            self.assertEqual(restored.mutation_receipts[-1].action, "consume")
            self.assertEqual(
                store.set_effort_mode("run-1", "focused", target="next_execution", expected_revision=0, request_id=self.RESERVATION_ID).revision,
                1,
            )

    def test_abandon_prepared_binding_preserves_reservation_and_started_cannot_be_abandoned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            store.set_effort_mode("run-1", "focused", target="next_execution", expected_revision=0, request_id=self.RESERVATION_ID)
            policy = self._policy()
            store.prepare_effort_execution("run-1", policy, execution_request_id=self.EXECUTION_ID, expected_revision=1)
            self.assertEqual(store.abandon_effort_execution("run-1", self.EXECUTION_ID).status, "abandoned")
            self.assertEqual(store.load_effort_policy("run-1").pending_request_id, self.RESERVATION_ID)
            with self.assertRaisesRegex(ValueError, "RunState does not reference"):
                store.start_effort_execution("run-1", self.EXECUTION_ID)

    def test_binding_rejects_stale_policy_and_mismatched_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            store.set_effort_mode("run-1", "focused", target="planning", expected_revision=0, request_id=self.RESERVATION_ID)
            policy = self._policy()
            with self.assertRaises(EffortPolicyRevisionError):
                store.prepare_effort_execution("run-1", policy, execution_request_id=self.EXECUTION_ID, expected_revision=0)
            unapproved = store.load("run-1")
            unapproved.plan_revision = 1
            store.save(unapproved)
            with self.assertRaisesRegex(ValueError, "approved plan revision"):
                store.prepare_effort_execution("run-1", policy, execution_request_id=self.EXECUTION_ID, expected_revision=1)
            unapproved.plan_revision = 0
            store.save(unapproved)
            store.prepare_effort_execution("run-1", policy, execution_request_id=self.EXECUTION_ID, expected_revision=1)
            run = store.load("run-1")
            run.active_policy_id = policy.policy_id
            run.active_execution_request_id = self.EXECUTION_ID
            run.plan_revision = 2
            run.plan_approved_revision = 2
            store.save(run)
            with self.assertRaisesRegex(ValueError, "approved plan revision"):
                store.start_effort_execution("run-1", self.EXECUTION_ID)
            self.assertEqual(store.load_effort_policy("run-1").binding(self.EXECUTION_ID).status, "prepared")

    def test_snapshot_corruption_and_failed_start_write_are_not_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(Path(directory))
            store.set_effort_mode("run-1", "focused", target="next_execution", expected_revision=0, request_id=self.RESERVATION_ID)
            policy = self._policy()
            store.prepare_effort_execution("run-1", policy, execution_request_id=self.EXECUTION_ID, expected_revision=1)
            path = store.effort_policy_path("run-1")
            original = path.read_bytes()
            run = store.load("run-1")
            run.active_policy_id = policy.policy_id
            run.active_execution_request_id = self.EXECUTION_ID
            store.save(run)
            with patch.object(store, "_write_json_atomic", side_effect=OSError("fixture start write failure")):
                with self.assertRaisesRegex(OSError, "fixture start write failure"):
                    store.start_effort_execution("run-1", self.EXECUTION_ID)
            self.assertEqual(path.read_bytes(), original)

            valid = json.loads(original)
            broken = json.loads(original)
            broken["prepared_policies"][policy.policy_id]["policy_version"] = 99
            path.write_text(json.dumps(broken), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid effort policy sidecar"):
                store.load_effort_policy("run-1")
            broken = json.loads(original)
            broken["execution_bindings"][self.EXECUTION_ID]["policy_id"] = "75f63b9c-7db3-438c-a76b-bf11ee6f4f6c"
            path.write_text(json.dumps(broken), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid effort policy sidecar"):
                store.load_effort_policy("run-1")
            broken = json.loads(original)
            broken["execution_bindings"][self.EXECUTION_ID]["policy_revision"] = 9
            path.write_text(json.dumps(broken), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid effort policy sidecar"):
                store.load_effort_policy("run-1")
            path.write_text(json.dumps(valid), encoding="utf-8")
            self.assertEqual(store.load_effort_policy("run-1").binding(self.EXECUTION_ID).status, "prepared")


if __name__ == "__main__":
    unittest.main()
