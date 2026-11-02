import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, PlanningConfig, ProjectConfig
from ai_orchestrator.codex_sdk import CodexSdkAccountStatus
from ai_orchestrator.models import (
    ArchiveCleanupStatus, ArchiveCleanupTarget, EffortMode, EffortPolicyState, ProfileSource, RunArchive,
    RunState, RunStep, Stage, TaskStatus, WorkTask,
)
from ai_orchestrator.pipeline import Pipeline, PipelineError
from ai_orchestrator.store import RunLockedError, StateStore


class EffortPlanningBindingTest(unittest.TestCase):
    def _archived(self, root: Path) -> tuple[Pipeline, RunState]:
        pipeline, state = self._selected(root)
        pipeline.store.set_effort_mode(state.id, "focused", target="next_execution", expected_revision=1, request_id=str(uuid.uuid4()))
        spec = root / "spec.md"
        spec.write_text("Preserve the completed work", encoding="utf-8")
        state.spec_snapshot_path = str(spec)
        state.stage = Stage.PUSHED
        state.tasks = [WorkTask(
            "done", "Completed work", ["general"], status=TaskStatus.COMPLETED, completed_commit="abc123",
            agent_id="planner", provider_id="codex", model="gpt-6.1-sol",
        )]
        state.archive = RunArchive(
            "saved", "revision", "snapshot.json", "manifest.json", "summary.md", "fingerprint",
            cleanup_status=ArchiveCleanupStatus.BLOCKED,
            cleanup_targets=[ArchiveCleanupTarget("shared", str(root / "removed-worktree"), "abc123", "blocked", "소유권을 확인할 수 없는 ignored 파일")],
        )
        state.refresh_task_readiness()
        pipeline.store.save(state)
        return pipeline, state

    def test_archived_chat_fixes_policy_before_provider_and_preserves_original_records_across_failure_and_retry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._archived(Path(directory))
            preserved = {path: path.read_bytes() for path in pipeline.store.run_dir(state.id).rglob("*") if path.is_file()}
            inherited = pipeline.store.load_effort_policy(state.id, archived_chat=True)
            self.assertEqual(inherited.selected_mode, EffortMode.ECONOMY)
            self.assertFalse(inherited.planning_bindings)
            self.assertIsNone(inherited.pending_execution_mode)
            self.assertFalse(pipeline.store.effort_policy_path(state.id, archived_chat=True).exists())
            calls = []

            def provider(**kwargs: object) -> str:
                calls.append(kwargs)
                archived_policy = pipeline.store.load_effort_policy(state.id, archived_chat=True)
                binding = archived_policy.planning_bindings[-1]
                self.assertEqual(binding.status, "started")
                self.assertEqual(pipeline.effort_control(state.id)["planning_request_status"], "started")
                self.assertTrue(binding.started_at)
                self.assertEqual(kwargs["usage_context"].operation_request_id, binding.planning_request_id)
                self.assertEqual(kwargs["model"], "gpt-6.1-sol")
                self.assertEqual((kwargs["agent"].review_sandbox_mode, kwargs["agent"].review_approval_mode), ("read-only", "deny-all"))
                self.assertIn("Saved archive cleanup evidence", kwargs["prompt"])
                self.assertIn("소유권을 확인할 수 없는 ignored 파일", kwargs["prompt"])
                for path, content in preserved.items():
                    self.assertEqual(path.read_bytes(), content, str(path))
                if len(calls) == 2:
                    raise PipelineError("provider unavailable")
                return "삭제 범위 밖의 파일을 보존하고 확인해야 합니다."

            with (patch.object(pipeline, "_invoke_provider_command", side_effect=provider),
                  patch.object(pipeline, "_build_plan") as build_plan,
                  patch.object(pipeline, "execute") as execute):
                for index in range(3):
                    if index == 1:
                        with self.assertRaisesRegex(PipelineError, "provider unavailable"):
                            pipeline.send_planning_message(state.id, "정리를 도와줘")
                    else:
                        chatted = pipeline.send_planning_message(state.id, "정리를 도와줘")
                        self.assertEqual(chatted.planning_messages[-1].role, "assistant")
                        self.assertEqual(chatted.archive, state.archive)
                        self.assertEqual(chatted.tasks, state.tasks)
                build_plan.assert_not_called()
                execute.assert_not_called()
            history = pipeline.store.load_effort_policy(state.id, archived_chat=True)
            self.assertEqual([item.status for item in history.planning_bindings], ["finished", "failed", "finished"])
            self.assertEqual(history.selected_mode, EffortMode.ECONOMY)
            self.assertIsNone(history.pending_execution_mode)
            self.assertEqual(len({item.planning_request_id for item in history.planning_bindings}), 3)
            self.assertEqual(pipeline.store.load_effort_policy(state.id).pending_execution_mode, EffortMode.FOCUSED)
            control = pipeline.effort_control(state.id)
            self.assertEqual(control["planning_request_status"], "finished")
            self.assertEqual(control["planning_policy"]["policy_id"], history.planning_bindings[-1].policy_id)
            self.assertFalse(control["can_select_plan"] or control["can_apply_plan"] or control["can_reserve"])
            for path, content in preserved.items():
                self.assertEqual(path.read_bytes(), content, str(path))
            self.assertEqual(pipeline.store.load(state.id).planning_messages[-1].role, "assistant")
            self.assertFalse(Path(state.archive.cleanup_targets[0].recorded_path).exists())

    def test_archived_chat_guard_and_corrupt_policy_do_not_invoke_provider(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._archived(Path(directory))
            original = pipeline.store.effort_policy_path(state.id).read_bytes()
            prompt = Path(directory) / "prompt.md"
            prompt.write_text("Help", encoding="utf-8")
            with patch.object(pipeline, "_invoke_provider_command") as provider:
                with self.assertRaisesRegex(PipelineError, "fixed effort policy request"):
                    pipeline._invoke_planning_agent(
                        state, pipeline.agents["planner"], "Help", prompt, Path(directory) / "unused.log", usage_purpose="chat",
                    )
                pipeline.store.effort_policy_path(state.id, archived_chat=True).write_text("{broken", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "invalid effort policy sidecar"):
                    pipeline.send_planning_message(state.id, "Help")
                provider.assert_not_called()
            self.assertEqual(pipeline.store.effort_policy_path(state.id).read_bytes(), original)

    def test_legacy_archived_chat_without_policy_keeps_legacy_model_and_does_not_create_policy(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._archived(Path(directory))
            pipeline.store.effort_policy_path(state.id).unlink()
            state.planning_profile_source = ProfileSource.LEGACY
            pipeline.store.save(state)
            with patch.object(pipeline, "_invoke_provider_command", return_value="보관된 기록입니다.") as provider:
                pipeline.send_planning_message(state.id, "도움")
            self.assertEqual(provider.call_args.kwargs["reasoning_effort"], "medium")
            self.assertFalse(pipeline.store.effort_policy_path(state.id, archived_chat=True).exists())

    def test_archived_chat_keeps_manual_model_selection_in_the_conversation_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._archived(Path(directory))
            original = pipeline.store.state_path(state.id).read_bytes()
            original_policy = pipeline.store.effort_policy_path(state.id).read_bytes()
            with patch.object(pipeline, "_invoke_provider_command", return_value="답변") as provider:
                chatted = pipeline.send_planning_message(
                    state.id, "도움", planning_model="gpt-6-luna", planning_reasoning_effort="low",
                )
            self.assertEqual(provider.call_args.kwargs["model"], "gpt-6-luna")
            self.assertEqual(provider.call_args.kwargs["reasoning_effort"], "low")
            self.assertEqual(chatted.planning_profile_source, ProfileSource.MANUAL)
            self.assertEqual(pipeline.store.state_path(state.id).read_bytes(), original)
            self.assertEqual(pipeline.store.effort_policy_path(state.id).read_bytes(), original_policy)

    def test_failed_chat_keeps_active_planning_and_execution_owners_blocked_without_provider_call(self) -> None:
        for operation in ("planning-chat", "planning-preview"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as directory:
                pipeline, state = self._selected(Path(directory))
                state.fail_step(RunStep.AGENT_EXECUTION, "saved failure")
                pipeline.store.save(state)
                original = pipeline.store.state_path(state.id).read_bytes()
                with (pipeline.store.lock(state.id, "execute"), pipeline.store.planning_chat_lock(state.id, operation),
                      patch.object(pipeline, "_invoke_provider_command") as provider):
                    execution = pipeline.store.lock_path(state.id).read_bytes()
                    planning = pipeline.store.planning_chat_lock_path(state.id).read_bytes()
                    with self.assertRaisesRegex(RunLockedError, f"operation={operation}"):
                        pipeline.send_planning_message(state.id, "What failed?")
                    provider.assert_not_called()
                    self.assertEqual(pipeline.store.lock_path(state.id).read_bytes(), execution)
                    self.assertEqual(pipeline.store.planning_chat_lock_path(state.id).read_bytes(), planning)
                    self.assertEqual(pipeline.store.state_path(state.id).read_bytes(), original)

    def test_failed_chat_with_selected_policy_preserves_held_execution_lock_and_task_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._selected(Path(directory))
            spec = Path(directory) / "plan.md"
            spec.write_text("Discuss the saved failure only", encoding="utf-8")
            state.spec_snapshot_path = str(spec)
            state.tasks = [WorkTask("failed", "Failed work", ["general"], status=TaskStatus.FAILED, error="saved failure")]
            state.fail_step(RunStep.AGENT_EXECUTION, "saved failure")
            pipeline.store.save(state)
            original = pipeline.store.state_path(state.id).read_bytes()
            with pipeline.store.lock(state.id, "execute"), patch.object(pipeline, "_invoke_provider_command", return_value="Saved failure explanation"):
                lock = pipeline.store.lock_path(state.id).read_bytes()
                chatted = pipeline.send_planning_message(state.id, "What failed?")
                self.assertEqual(chatted.planning_messages[-1].text, "Saved failure explanation")
                self.assertEqual(pipeline.store.lock_path(state.id).read_bytes(), lock)
                self.assertEqual(pipeline.store.state_path(state.id).read_bytes(), original)
                self.assertEqual(chatted.stage, Stage.FAILED)
                self.assertEqual(chatted.failure_message, "saved failure")
                self.assertEqual(chatted.tasks[0].status, TaskStatus.FAILED)
            self.assertEqual(pipeline.store.load_effort_policy(state.id).planning_bindings[-1].status, "finished")

    def test_failed_chat_waits_for_a_transient_policy_writer_without_releasing_execution_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._selected(Path(directory))
            spec = Path(directory) / "plan.md"
            spec.write_text("Discuss the saved failure only", encoding="utf-8")
            state.spec_snapshot_path = str(spec)
            state.fail_step(RunStep.AGENT_EXECUTION, "saved failure")
            pipeline.store.save(state)
            original = pipeline.store.state_path(state.id).read_bytes()
            writer = pipeline.store.effort_policy_lock(state.id)
            writer.__enter__()
            create = pipeline.store._create_lock_file
            collisions = []

            def finish_writer_on_contention(path: Path, retry_until: float | None) -> int:
                try:
                    return create(path, retry_until)
                except FileExistsError:
                    collisions.append(path)
                    writer.__exit__(None, None, None)
                    raise

            try:
                with (pipeline.store.lock(state.id, "execute"),
                      patch.object(pipeline.store, "_create_lock_file", side_effect=finish_writer_on_contention),
                      patch.object(pipeline, "_invoke_provider_command", return_value="Saved failure explanation")):
                    lock = pipeline.store.lock_path(state.id).read_bytes()
                    chatted = pipeline.send_planning_message(state.id, "What failed?")
                    self.assertEqual(chatted.planning_messages[-1].text, "Saved failure explanation")
                    self.assertEqual(pipeline.store.lock_path(state.id).read_bytes(), lock)
                    self.assertEqual(pipeline.store.state_path(state.id).read_bytes(), original)
                self.assertEqual(collisions, [pipeline.store.effort_policy_lock_path(state.id)])
            finally:
                if not collisions:
                    writer.__exit__(None, None, None)

    @staticmethod
    def _pipeline(root: Path) -> Pipeline:
        agent = AgentConfig("planner", ("general",), (), provider_id="codex", model="gpt-6.1-sol")
        sdk = Mock()
        sdk.account_status.return_value = CodexSdkAccountStatus(True, "chatgpt", "로그인됨")
        return Pipeline(Config(
            path=root / "orchestrator.toml", project=ProjectConfig(repo=root), execution=ExecutionConfig(),
            agents=(agent,), planning=PlanningConfig(agent_id=agent.id),
        ), codex_sdk=sdk)

    def _selected(self, root: Path, mode: str = "economy") -> tuple[Pipeline, RunState]:
        pipeline = self._pipeline(root)
        state = RunState(
            "run-planning", "plan.md", "digest", str(root), "main", stage=Stage.REVIEWED,
            planning_agent_id="planner", planning_provider_id="codex", planning_model="gpt-6.1-sol",
            planning_reasoning_effort="medium", planning_profile_source=ProfileSource.ROUTING,
        )
        pipeline.store.save(state)
        pipeline.store.set_effort_mode(state.id, mode, target="planning", expected_revision=0, request_id=str(uuid.uuid4()))
        return pipeline, state

    def _invoke(self, pipeline: Pipeline, state: RunState) -> str:
        directory = pipeline.store.run_dir(state.id)
        prompt = directory / "prompt.md"
        prompt.write_text("Plan the requested work", encoding="utf-8")
        return pipeline._invoke_planning_agent(state, pipeline.agents["planner"], prompt.read_text(), prompt, directory / "agent.log")

    def test_same_request_freezes_profile_across_corrections_and_ignores_execution_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._selected(Path(directory))
            pipeline.store.set_effort_mode(state.id, "focused", target="next_execution", expected_revision=1, request_id=str(uuid.uuid4()))
            observed = []

            def provider(**kwargs: object) -> str:
                policy = pipeline.store.load_effort_policy(state.id)
                self.assertEqual(policy.planning_bindings[-1].status, "started")
                self.assertTrue(policy.planning_bindings[-1].started_at)
                observed.append(kwargs)
                return "answer"

            with patch.object(pipeline, "_invoke_provider_command", side_effect=provider):
                with pipeline._planning_effort_scope(state, purpose="planning") as first:
                    self._invoke(pipeline, state)
                    pipeline.store.set_effort_mode(state.id, "balanced", target="planning", expected_revision=2, request_id=str(uuid.uuid4()))
                    with pipeline._planning_effort_scope(state, purpose="chat") as nested:
                        self.assertEqual(first, nested)
                        self._invoke(pipeline, state)
            policy = StateStore(pipeline.store.root).load_effort_policy(state.id)
            self.assertEqual(len(policy.planning_bindings), 1)
            self.assertEqual(policy.planning_bindings[0].status, "finished")
            self.assertEqual(policy.pending_execution_mode, EffortMode.FOCUSED)
            self.assertEqual(policy.selected_mode, EffortMode.BALANCED)
            self.assertFalse(policy.execution_bindings)
            self.assertEqual(state.planning_reasoning_effort, "medium")
            self.assertEqual(state.planning_profile_source, ProfileSource.ROUTING)
            self.assertEqual([item["reasoning_effort"] for item in observed], ["high", "high"])
            self.assertTrue(all("effort policy: economy" in item["prompt"] for item in observed))

    def test_manual_profile_is_preserved_and_failed_request_is_not_reused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._selected(Path(directory))
            state.planning_profile_source = ProfileSource.MANUAL
            state.planning_reasoning_effort = "xhigh"
            pipeline.store.save(state)
            with patch.object(pipeline, "_invoke_provider_command", side_effect=PipelineError("provider failed")) as provider:
                with self.assertRaisesRegex(PipelineError, "provider failed"):
                    with pipeline._planning_effort_scope(state, purpose="planning_preview"):
                        self._invoke(pipeline, state)
            self.assertEqual(provider.call_args.kwargs["reasoning_effort"], "xhigh")
            policy = pipeline.store.load_effort_policy(state.id)
            first = policy.planning_bindings[0]
            self.assertEqual(first.status, "failed")
            self.assertEqual(policy.policy(first.policy_id).manual_exception_ids, ("planning",))
            with pipeline._planning_effort_scope(state, purpose="recovery_planning"):
                pass  # A cached or static plan has no actual AI start.
            after = pipeline.store.load_effort_policy(state.id)
            self.assertEqual(after.planning_bindings[0], first)
            self.assertEqual(after.planning_bindings[1].purpose, "recovery_planning")
            self.assertEqual(after.planning_bindings[1].status, "finished")
            self.assertEqual(after.planning_bindings[1].started_at, "")

    def test_prepare_or_start_storage_failure_prevents_ai(self) -> None:
        for method in ("prepare_effort_planning", "start_effort_planning"):
            with self.subTest(method=method), tempfile.TemporaryDirectory() as directory:
                pipeline, state = self._selected(Path(directory))
                with patch.object(pipeline.store, method, side_effect=OSError("write denied")):
                    with patch.object(pipeline, "_invoke_provider_command") as provider:
                        with self.assertRaisesRegex(OSError, "write denied"):
                            with pipeline._planning_effort_scope(state, purpose="chat"):
                                self._invoke(pipeline, state)
                provider.assert_not_called()
                bindings = pipeline.store.load_effort_policy(state.id).planning_bindings
                if method == "start_effort_planning":
                    self.assertEqual(bindings[-1].status, "failed")
                    self.assertEqual(bindings[-1].started_at, "")
                else:
                    self.assertFalse(bindings)

    def test_builder_corrections_share_policy_and_cache_is_separated_by_mode(self) -> None:
        valid = 'AI_PLAN_RESULT: ' + json.dumps({
            "summary": "Update docs", "server_work": False, "source_paths": [], "instruction_paths": [], "questions": [],
            "tasks": [{"id": "docs", "title": "Update docs", "description": "Update README", "capabilities": ["general"],
                       "depends_on": [], "acceptance_criteria": ["Usage is described"], "expected_paths": ["README.md"],
                       "forbidden_paths": [], "verify_commands": [["python", "-m", "compileall", "-q", "src"]], "risk_level": "low"}],
        })
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._selected(Path(directory))
            calls = []

            def provider(**kwargs: object) -> str:
                calls.append(kwargs)
                if len(calls) == 1:
                    pipeline.store.set_effort_mode(state.id, "balanced", target="planning", expected_revision=1, request_id=str(uuid.uuid4()))
                    return "invalid response"
                return valid

            with patch.object(pipeline, "_invoke_provider_command", side_effect=provider), \
                    patch.object(pipeline.git, "has_uncommitted_changes", return_value=False):
                self.assertEqual(pipeline._build_plan(state, "Update the README").tasks[0].id, "docs")
                self.assertEqual(len(calls), 2)
                self.assertEqual([item["reasoning_effort"] for item in calls], ["high", "high"])
                pipeline._build_plan(state, "Update the README")
                self.assertEqual(len(calls), 3)  # A different mode cannot use the first cached policy.
                self.assertEqual(calls[-1]["reasoning_effort"], "high")
                pipeline._build_plan(state, "Update the README")
                self.assertEqual(len(calls), 3)  # An identical policy can reuse validated output.
            bindings = pipeline.store.load_effort_policy(state.id).planning_bindings
            self.assertEqual(len(bindings), 3)
            self.assertEqual(bindings[-1].status, "finished")
            self.assertEqual(bindings[-1].started_at, "")

    def test_v1_migrates_without_losing_selection_and_corrupt_binding_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self._selected(Path(directory))
            path = pipeline.store.effort_policy_path(state.id)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["schema_version"] = 1
            payload.pop("planning_bindings")
            path.write_text(json.dumps(payload), encoding="utf-8")
            with pipeline._planning_effort_scope(state, purpose="planning") as snapshot:
                policy = pipeline.store.load_effort_policy(state.id)
                binding = policy.planning_bindings[-1]
                replay, saved = policy.prepare_planning(
                    snapshot, request_id=binding.planning_request_id, expected_revision=1, purpose="planning",
                )
                self.assertEqual(replay, policy)
                self.assertEqual(saved, binding)
                with self.assertRaises(ValueError):
                    policy.prepare_planning(snapshot, request_id=binding.planning_request_id, expected_revision=1, purpose="chat")
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 2)
            bad = json.loads(json.dumps(payload))
            bad["planning_bindings"][binding.planning_request_id]["policy_id"] = str(uuid.uuid4())
            with self.assertRaises(ValueError):
                EffortPolicyState.from_dict(bad)
            with self.assertRaises(ValueError):
                pipeline.store.load_effort_policy(state.id).start_planning(binding.planning_request_id)

    def test_legacy_without_sidecar_and_original_state_are_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline = self._pipeline(Path(directory))
            state = RunState("legacy", "plan", "digest", directory, "main", Stage.REVIEWED, planning_reasoning_effort="medium")
            pipeline.store.save(state)
            with patch.object(pipeline, "_invoke_provider_command", return_value="answer") as provider:
                with pipeline._planning_effort_scope(state, purpose="planning") as policy:
                    self.assertIsNone(policy)
                    self._invoke(pipeline, state)
            self.assertEqual(provider.call_args.kwargs["reasoning_effort"], "medium")
            self.assertFalse(pipeline.store.effort_policy_path(state.id).exists())

    def test_new_request_defaults_balanced_and_explicit_profile_source_is_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline = self._pipeline(Path(directory))
            with (patch.object(pipeline, "_ensure_planning_provider_ready"), patch.object(pipeline, "_ensure_git_ready_for_planning"),
                  patch.object(pipeline.git, "ensure_repository"), patch.object(pipeline.git, "head", return_value="abc123")):
                state = pipeline.prepare_planning("", planning_mode="directed", planning_request="Update the requested feature")
                self.assertEqual(pipeline.store.load_effort_policy(state.id).selected_mode, EffortMode.BALANCED)
                self.assertEqual(state.planning_profile_source, ProfileSource.ROUTING)
                manual = pipeline.prepare_planning(
                    "", planning_mode="directed", planning_request="Second request", effort_mode="focused",
                    planning_model="gpt-6.1-sol", planning_profile_source="manual",
                )
                self.assertEqual(pipeline.store.load_effort_policy(manual.id).selected_mode, EffortMode.FOCUSED)
                self.assertEqual(manual.planning_profile_source, ProfileSource.MANUAL)
                routed = pipeline.prepare_planning(
                    "", planning_mode="directed", planning_request="Third request", effort_mode="economy",
                    planning_model="gpt-6.1-sol", planning_profile_source="routing",
                )
                self.assertEqual(routed.planning_profile_source, ProfileSource.ROUTING)
                for changes in ({"effort_mode": "invalid"}, {"planning_profile_source": "legacy"}):
                    with self.assertRaises(PipelineError):
                        pipeline.prepare_planning("", planning_mode="directed", planning_request="bad", **changes)

    def test_initial_policy_is_written_before_run_becomes_visible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline = self._pipeline(Path(directory))
            state = RunState("initial", "plan", "digest", directory, "main", Stage.RECEIVED)
            save = pipeline.store.save

            def observe(current: RunState) -> None:
                policy = EffortPolicyState.from_dict(json.loads(pipeline.store.effort_policy_path(current.id).read_text(encoding="utf-8")))
                self.assertEqual(policy.selected_mode, EffortMode.BALANCED)
                self.assertFalse(pipeline.store.state_path(current.id).exists())
                save(current)

            with patch.object(pipeline.store, "save", side_effect=observe):
                pipeline.store.initialize_effort_mode(state, "balanced")
            with self.assertRaises(ValueError):
                pipeline.store.initialize_effort_mode(state, "economy")
