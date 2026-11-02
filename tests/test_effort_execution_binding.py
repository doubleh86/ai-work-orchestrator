import tempfile
import unittest
import uuid
import sys
import json
from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from itertools import product
from pathlib import Path
from unittest.mock import Mock, patch

from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, PlanningConfig, ProjectConfig, RoutingConfig
from ai_orchestrator.models import (
    EffortMode, IntegrationControl, IntegrationStatus, ProfileSource, RunExecutionAction, RunExecutionControl,
    RunExecutionSituation, RunLockState, RunState, RunStep, Stage, TaskAction, TaskStatus, WorkTask,
)
from ai_orchestrator.pipeline import Pipeline, PipelineError


class EffortExecutionBindingTest(unittest.TestCase):
    @staticmethod
    def _pipeline(root: Path) -> Pipeline:
        worker = AgentConfig("worker", ("general",), (), 2, provider_id="codex", model="gpt-6.1-sol")
        config = Config(
            path=root / "orchestrator.toml", project=ProjectConfig(repo=root), execution=ExecutionConfig(),
            agents=(worker,), planning=PlanningConfig(agent_id="worker"),
            routing=RoutingConfig(default_provider="codex"),
        )
        return Pipeline(config, codex_sdk=Mock())

    @staticmethod
    def _state(root: Path) -> RunState:
        task = WorkTask(
            "t01", "Update app", ["general"], agent_id="worker", provider_id="codex", model="gpt-6.1-sol",
            reasoning_effort="medium", profile_source=ProfileSource.MODE, effort_baseline_reasoning="medium",
            expected_paths=["src/**"],
        )
        return RunState(
            "run-policy", "plan.md", "digest", str(root), "main", stage=Stage.PLANNED,
            summary="Plan", plan_revision=1, plan_approved_revision=1, tasks=[task],
            planning_agent_id="worker", planning_provider_id="codex",
            planning_reasoning_effort="high", planning_profile_source=ProfileSource.MODE,
            planning_effort_baseline_reasoning="medium",
        )

    def _selected_pipeline(self, root: Path) -> Pipeline:
        pipeline = self._pipeline(root)
        pipeline.store.save(self._state(root))
        pipeline.set_effort_mode("run-policy", EffortMode.ECONOMY, expected_revision=0, request_id=str(uuid.uuid4()))
        return pipeline

    def test_execution_starts_before_ai_and_finishes_after_return(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline = self._selected_pipeline(Path(directory))
            observed: list[str] = []

            def execute(current: RunState, **_: object) -> RunState:
                policy_state = pipeline.store.load_effort_policy(current.id)
                binding = policy_state.binding(current.active_execution_request_id)
                self.assertIsNotNone(binding)
                self.assertEqual(binding.status, "started")
                snapshot = policy_state.policy(binding.policy_id)
                self.assertEqual(snapshot.mode, EffortMode.ECONOMY)
                self.assertEqual(snapshot.policy_version, 3)
                self.assertEqual(snapshot.plan_revision, 1)
                self.assertEqual(snapshot.task_profiles[0][1].reasoning_effort, "medium")
                with patch.object(pipeline, "_invoke_provider_command", return_value="done") as provider:
                    pipeline._invoke_agent(
                        current, current.tasks[0], pipeline.agents["worker"], "implement", Path(directory) / "agent.log",
                        TaskAction.EXECUTE,
                    )
                    self.assertIn("Execution effort policy: economy", provider.call_args.kwargs["prompt"])
                    self.assertIn("mandatory checks", provider.call_args.kwargs["prompt"])
                observed.append(binding.execution_request_id)
                return current

            with patch.object(pipeline, "_execute_with_bound_policy", side_effect=execute):
                finished = pipeline.execute("run-policy")

            self.assertEqual(len(observed), 1)
            self.assertEqual(finished.active_policy_id, "")
            self.assertEqual(finished.active_execution_request_id, "")
            binding = pipeline.store.load_effort_policy("run-policy").binding(observed[0])
            self.assertEqual(binding.status, "finished")

    def test_prepared_interruption_abandons_without_consuming_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline = self._selected_pipeline(Path(directory))
            pipeline.store.set_effort_mode(
                "run-policy", "economy", target="next_execution", expected_revision=1, request_id=str(uuid.uuid4())
            )
            with patch.object(pipeline.store, "start_effort_execution", side_effect=OSError("interrupted")):
                with self.assertRaisesRegex(OSError, "interrupted"):
                    pipeline.execute("run-policy")
            before = pipeline.store.load_effort_policy("run-policy")
            self.assertEqual(before.execution_bindings[-1].status, "prepared")
            self.assertEqual(before.pending_execution_mode, EffortMode.ECONOMY)
            first_request_id = before.execution_bindings[-1].execution_request_id

            with patch.object(pipeline, "_execute_with_bound_policy", side_effect=lambda current, **_: current):
                pipeline.execute("run-policy")
            after = pipeline.store.load_effort_policy("run-policy")
            self.assertEqual(after.binding(first_request_id).status, "abandoned")
            self.assertEqual(after.execution_bindings[-1].status, "finished")
            self.assertIsNone(after.pending_execution_mode)

    def test_pending_manual_profile_preserves_the_bound_snapshot_and_next_mode_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline = self._selected_pipeline(root)
            state = pipeline.store.load("run-policy")
            state.tasks.append(WorkTask(
                "t02", "다음 작업", ["general"], agent_id="worker", provider_id="codex", model="gpt-6.1-sol",
                reasoning_effort="medium", profile_source=ProfileSource.MODE, effort_baseline_reasoning="medium", expected_paths=["src/**"],
            ))
            pipeline.store.save(state)
            seen = []

            def execute(current: RunState, **_: object) -> RunState:
                current.stage, current.active_step = Stage.EXECUTING, RunStep.AGENT_EXECUTION
                current.tasks[0].status, current.tasks[0].active_action = TaskStatus.RUNNING, TaskAction.EXECUTE
                pipeline.store.save(current)
                original = pipeline.store.load_effort_policy(current.id).policy(current.active_policy_id).to_dict()
                pipeline.store.set_effort_mode(
                    current.id, "focused", target="next_execution", expected_revision=1, request_id=str(uuid.uuid4())
                )
                remote = self._pipeline(root)
                target = current.tasks[-1]
                remote.update_task_execution_profile(
                    current.id, target.id, agent_id="worker", model="gpt-6.1-sol", reasoning_effort="high",
                    expected_profile=remote._task_execution_profile_snapshot(target),
                )
                self.assertEqual(target.reasoning_effort, "medium")
                current.tasks[0].status, current.tasks[0].active_action = TaskStatus.COMPLETED, None
                with pipeline.store.planning_chat_lock(current.id):
                    self.assertTrue(pipeline._apply_queued_execution_profiles(current))
                self.assertEqual(target.reasoning_effort, "high")
                policy = pipeline.store.load_effort_policy(current.id)
                self.assertEqual(policy.policy(current.active_policy_id).to_dict(), original)
                self.assertEqual(policy.pending_execution_mode, EffortMode.FOCUSED)
                with patch.object(pipeline, "_invoke_provider_command", return_value="done") as provider:
                    pipeline._invoke_agent(current, target, pipeline.agents["worker"], "implement", root / "agent.log", TaskAction.EXECUTE)
                    self.assertEqual(provider.call_args.kwargs["reasoning_effort"], "high")
                    self.assertEqual(provider.call_args.kwargs["usage_context"].policy_id, current.active_policy_id)
                receipt_path = pipeline.store.task_execution_profiles_path(current.id)
                receipt = pipeline.store.load_task_execution_profiles(current.id)
                pipeline.store.save_task_execution_profiles(current.id, {})
                with self.assertRaisesRegex(PipelineError, "policy profile differs"):
                    pipeline._invoke_agent(current, target, pipeline.agents["worker"], "implement", root / "agent.log", TaskAction.EXECUTE)
                self.assertTrue(receipt_path.exists())
                pipeline.store.save_task_execution_profiles(current.id, receipt)
                seen.append(current.active_policy_id)
                current.active_step = None
                pipeline.store.save(current)
                return current

            with patch.object(pipeline, "_execute_with_bound_policy", side_effect=execute):
                completed = pipeline.execute(state.id)
            final = pipeline.store.load_effort_policy(state.id)
            self.assertEqual(len(final.execution_bindings), 1)
            self.assertEqual(final.execution_bindings[0].status, "finished")
            self.assertEqual(final.pending_execution_mode, EffortMode.FOCUSED)
            self.assertEqual(completed.active_policy_id, "")
            self.assertEqual(final.policy(seen[0]).task_profiles[-1][1].reasoning_effort, "medium")

    def test_started_failure_resumes_with_same_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline = self._selected_pipeline(Path(directory))
            with patch.object(pipeline, "_execute_with_bound_policy", side_effect=PipelineError("worker interrupted")):
                with self.assertRaisesRegex(PipelineError, "worker interrupted"):
                    pipeline.execute("run-policy")
            started = pipeline.store.load("run-policy")
            request_id = started.active_execution_request_id
            self.assertEqual(pipeline.store.load_effort_policy(started.id).binding(request_id).status, "started")
            pipeline.store.set_effort_mode(
                started.id, "focused", target="next_execution", expected_revision=1, request_id=str(uuid.uuid4())
            )

            def resumed(current: RunState, **_: object) -> RunState:
                self.assertEqual(current.active_execution_request_id, request_id)
                return current

            with patch.object(pipeline, "_execute_with_bound_policy", side_effect=resumed):
                pipeline.resume("run-policy")
            final_policy = pipeline.store.load_effort_policy(started.id)
            self.assertEqual(final_policy.binding(request_id).status, "finished")
            self.assertEqual(final_policy.pending_execution_mode, EffortMode.FOCUSED)
            self.assertEqual(pipeline.store.load(started.id).active_execution_request_id, "")
            with self.assertRaisesRegex(PipelineError, "policy_plan_review_required"):
                pipeline.execute(started.id)
            self.assertEqual(pipeline.store.load_effort_policy(started.id).pending_execution_mode, EffortMode.FOCUSED)

    def test_task_repair_keeps_saved_models_and_does_not_apply_the_next_effort_reservation(self) -> None:
        for entry, reserve in (("chat", True), ("chat", False), ("retry", True), ("retry", False)):
            with self.subTest(entry=entry, reserve=reserve), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                pipeline = self._selected_pipeline(root)
                state = pipeline.store.load("run-policy")
                state.stage, state.failed_step = Stage.FAILED, RunStep.AGENT_EXECUTION
                task = state.tasks[0]
                task.status, task.failed_action, task.last_attempt_id = TaskStatus.FAILED, TaskAction.EXECUTE, "failed-attempt"
                task.error = "worker failed"
                state.tasks.append(WorkTask(
                    "t02", "Saved next model", ["general"], agent_id="worker", provider_id="codex", model="gpt-6-luna",
                    reasoning_effort="high", profile_source=ProfileSource.MANUAL, expected_paths=["src/**"],
                ))
                done = deepcopy(task)
                done.id, done.status, done.completed_commit = "done", TaskStatus.COMPLETED, "a" * 40
                state.tasks.insert(0, done)
                state.refresh_task_readiness()
                completed_before = deepcopy(done)
                state.planning_reasoning_effort = "medium"
                pipeline.store.save(state)
                if reserve:
                    pipeline.set_effort_mode(state.id, "focused", target="next_execution", expected_revision=1, request_id=str(uuid.uuid4()))
                reserved = pipeline.store.load_effort_policy(state.id).view()

                def execute(current: RunState, **_: object) -> RunState:
                    policy_state = pipeline.store.load_effort_policy(current.id)
                    binding = policy_state.binding(current.active_execution_request_id)
                    self.assertEqual(binding.status, "started")
                    self.assertEqual(binding.reservation_request_id, "")
                    snapshot = policy_state.policy(binding.policy_id)
                    self.assertEqual(snapshot.mode, EffortMode.ECONOMY)
                    self.assertEqual(policy_state.view(), reserved)
                    profiles = dict(snapshot.task_profiles)
                    self.assertEqual((profiles["t02"].model, profiles["t02"].reasoning_effort), ("gpt-6-luna", "high"))
                    current.stage, current.failed_step = Stage.EXECUTING, None
                    for item in current.tasks:
                        item.status = TaskStatus.COMPLETED
                    pipeline.store.save(current)
                    return current

                with patch.object(pipeline, "_execute_with_bound_policy", side_effect=execute) as work:
                    if entry == "chat":
                        context = pipeline.task_retry_context(state.id, task.id)
                        result = pipeline.repair_task_from_chat(
                            state.id, task.id, request_id=str(uuid.uuid4()), message="고쳐서 계속해줘",
                            fingerprint=context["fingerprint"], conversation_revision=state.planning_conversation_revision,
                        )
                    else:
                        result = pipeline.retry_task(state.id, task.id)
                self.assertEqual(work.call_count, 1)
                restarted = self._pipeline(root)
                final = restarted.store.load_effort_policy(state.id)
                self.assertEqual(final.execution_bindings[-1].status, "finished")
                self.assertEqual(final.view(), reserved)
                self.assertEqual(result.plan_approved_revision, state.plan_approved_revision)
                self.assertEqual(result.tasks[-1].model, "gpt-6-luna")
                self.assertEqual(result.tasks[0], completed_before)

    def test_partial_group_resume_preserves_saved_profiles_and_next_reservation(self) -> None:
        for stage, reserved, history, entry in product((Stage.EXECUTING, Stage.FAILED), (False, True), (False, True), ("resume", "chat")):
            with self.subTest(stage=stage, reserved=reserved, history=history, entry=entry), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                pipeline = self._selected_pipeline(root)
                if history:
                    with patch.object(pipeline, "_execute_with_bound_policy", side_effect=lambda current, **_: current):
                        pipeline.execute("run-policy")
                state = pipeline.store.load("run-policy")
                state.stage = stage
                state.failed_step = RunStep.AGENT_EXECUTION if stage == Stage.FAILED else None
                state.planning_reasoning_effort = "medium"
                done = state.tasks[0]
                done.status, done.completed_commit = TaskStatus.COMPLETED, "a" * 40
                state.tasks.append(WorkTask(
                    "t02", "Next saved task", ["general"], agent_id="worker", provider_id="codex", model="gpt-6.1-sol",
                    reasoning_effort="medium", profile_source=ProfileSource.MODE, effort_baseline_reasoning="medium", expected_paths=["src/**"],
                ))
                state.refresh_task_readiness()
                pipeline.store.save(state)
                if reserved:
                    policy = pipeline.store.load_effort_policy(state.id)
                    pipeline.set_effort_mode(state.id, "focused", target="next_execution", expected_revision=policy.revision,
                                             request_id=str(uuid.uuid4()))
                before = pipeline.store.load_effort_policy(state.id).view()
                contracts = deepcopy(state.tasks)

                def execute(current: RunState, **_: object) -> RunState:
                    policy = pipeline.store.load_effort_policy(current.id)
                    binding = policy.binding(current.active_execution_request_id)
                    self.assertEqual(binding.status, "started")
                    self.assertEqual(binding.reservation_request_id, "")
                    snapshot = policy.policy(binding.policy_id)
                    self.assertEqual(snapshot.mode, EffortMode.ECONOMY)
                    profiles = dict(snapshot.task_profiles)
                    self.assertEqual((profiles["t02"].model, profiles["t02"].reasoning_effort), ("gpt-6.1-sol", "medium"))
                    self.assertEqual(current.tasks, contracts)
                    current.tasks[1].status = TaskStatus.COMPLETED
                    current.stage, current.failed_step, current.failure_message = Stage.READY_TO_MERGE, None, ""
                    pipeline.store.save(current)
                    return current

                with patch.object(pipeline, "_execute_with_bound_policy", side_effect=execute) as work:
                    if entry == "resume":
                        result = pipeline.resume(state.id)
                    else:
                        control = RunExecutionControl(RunExecutionSituation.READY, RunExecutionAction.RESUME, "resume", RunLockState.UNLOCKED)
                        integration = IntegrationControl(IntegrationStatus.NOT_READY, "waiting", "waiting", False, False)
                        with (
                            patch.object(pipeline, "status_with_controls",
                                         side_effect=lambda _: (pipeline.store.load(state.id), control, integration)),
                            patch.object(pipeline, "_configure_planning_profile", return_value=pipeline.agents["worker"]),
                            patch.object(pipeline, "_planning_effort_scope", return_value=nullcontext()),
                            patch.object(pipeline, "_invoke_planning_agent", return_value=json.dumps({
                                "action": "continue", "message": "저장한 설정으로 계속합니다.", "authorized": True,
                            })),
                        ):
                            parent = pipeline.request_chat_control(state.id, request_id=str(uuid.uuid4()), intent="project", message="고치고 이어서 진행해줘",
                                expected={"planRevision": state.plan_revision,
                                          "conversationRevision": state.planning_conversation_revision, "taskId": ""})
                            decision = pipeline.decide_project_chat(state.id, parent["request_id"])
                            observed = pipeline.perform_project_chat(state.id, parent["request_id"], decision["payload"]["step_id"])
                            pipeline.perform_project_chat(state.id, parent["request_id"], decision["payload"]["step_id"])
                            self.assertEqual(observed["payload"]["history"][-1]["error"], "")
                            result = pipeline.store.load(state.id)
                self.assertEqual(work.call_count, 1)
                self.assertEqual(result.stage, Stage.READY_TO_MERGE)
                self.assertEqual(result.tasks[0], contracts[0])
                self.assertEqual((result.plan_revision, result.plan_approved_revision), (state.plan_revision, state.plan_approved_revision))
                restored = self._pipeline(root).store.load_effort_policy(state.id)
                self.assertEqual(restored.view(), before)
                self.assertEqual(restored.execution_bindings[-1].status, "finished")

    def test_saved_profile_recovery_keeps_approval_and_required_review_guards(self) -> None:
        for entry, blocked in product(("retry", "resume"), ("approval", "required-review", "worker")):
            with self.subTest(entry=entry, blocked=blocked), tempfile.TemporaryDirectory() as directory:
                pipeline = self._selected_pipeline(Path(directory))
                state = pipeline.store.load("run-policy")
                state.stage, state.failed_step = Stage.FAILED, RunStep.AGENT_EXECUTION
                state.tasks[0].status = TaskStatus.FAILED
                if blocked == "approval":
                    state.plan_approved_revision = 0
                elif blocked == "required-review":
                    pipeline.config = replace(pipeline.config, routing=replace(pipeline.config.routing, review_required=True))
                else:
                    state.tasks[0].provider_id = "other-provider"
                pipeline.store.save(state)
                with patch.object(pipeline, "_execute_with_bound_policy") as work, self.assertRaises(PipelineError):
                    if entry == "retry":
                        pipeline.retry_task(state.id, state.tasks[0].id)
                    else:
                        pipeline.resume(state.id)
                work.assert_not_called()
                self.assertFalse(pipeline.store.load_effort_policy(state.id).execution_bindings)

    def test_plan_mismatch_and_snapshot_drift_block_ai(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline = self._selected_pipeline(Path(directory))
            state = pipeline.store.load("run-policy")
            state.tasks[0].reasoning_effort = "medium"
            state.tasks[0].profile_source = ProfileSource.ROUTING
            state.tasks[0].effort_baseline_reasoning = None
            pipeline.store.save(state)
            for start in (pipeline.execute, pipeline.resume):
                with self.subTest(entry=start.__name__), self.assertRaisesRegex(PipelineError, "policy_plan_review_required"):
                    start(state.id)
            self.assertFalse(pipeline.store.load_effort_policy(state.id).execution_bindings)

            state.tasks[0].reasoning_effort = "medium"
            state.tasks[0].profile_source = ProfileSource.MODE
            state.tasks[0].effort_baseline_reasoning = "medium"
            pipeline.store.save(state)
            started_id = pipeline._begin_effort_execution(
                state, agent_overrides=None, model_overrides=None, reasoning_effort_overrides=None
            )
            state.tasks[0].reasoning_effort = "high"
            with patch.object(pipeline, "_invoke_provider_command") as provider:
                with self.assertRaisesRegex(PipelineError, "profile differs"):
                    pipeline._invoke_agent(
                        state, state.tasks[0], pipeline.agents["worker"], "implement", Path(directory) / "agent.log",
                        TaskAction.EXECUTE,
                    )
                provider.assert_not_called()
            self.assertEqual(pipeline.store.load_effort_policy(state.id).binding(started_id).status, "started")

    def test_worker_runtime_mismatch_blocks_binding_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline = self._selected_pipeline(Path(directory))
            pipeline.agents["planner"] = AgentConfig("planner", ("general",), (), 2, provider_id="codex", model="gpt-6.1-sol")
            state = pipeline.store.load("run-policy")
            state.planning_agent_id = "planner"
            pipeline.store.save(state)
            pipeline.agents["worker"] = AgentConfig(
                "worker", ("general",), (sys.executable, "-c", "pass"), 2,
                provider_id="local-worker", model="worker-v1",
            )
            with patch.object(pipeline, "_execute_with_bound_policy") as execute:
                with self.assertRaisesRegex(PipelineError, "worker profile differs"):
                    pipeline.execute("run-policy")
                execute.assert_not_called()
            self.assertFalse(pipeline.store.load_effort_policy("run-policy").execution_bindings)

    def test_reviewer_runtime_must_match_started_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worker = AgentConfig("worker", ("general",), (), 2, provider_id="codex", model="gpt-6.1-sol")
            reviewer = AgentConfig(
                "reviewer", ("general",), (sys.executable, "-c", "pass"), 2,
                provider_id="local-review", model="review-v1",
            )
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml", project=ProjectConfig(repo=root), execution=ExecutionConfig(),
                    agents=(worker, reviewer), planning=PlanningConfig(agent_id="worker"),
                    routing=RoutingConfig(default_provider="codex"),
                ),
                codex_sdk=Mock(),
            )
            state = self._state(root)
            state.tasks[0].reasoning_effort = "high"
            state.tasks[0].reviewer_agent_id = "reviewer"
            state.tasks[0].reviewer_provider_id = "local-review"
            state.tasks[0].reviewer_model = "review-v1"
            state.tasks[0].review_policy_added = True
            state.planning_reasoning_effort = "high"
            pipeline.store.save(state)
            pipeline.set_effort_mode(state.id, "focused", expected_revision=0, request_id=str(uuid.uuid4()))
            state.tasks[0].reviewer_model = "review-unknown"
            pipeline.store.save(state)
            with self.assertRaisesRegex(PipelineError, "policy_plan_review_required"):
                pipeline._begin_effort_execution(
                    state, agent_overrides=None, model_overrides=None, reasoning_effort_overrides=None
                )
            state.tasks[0].reviewer_model = "review-v1"
            pipeline.store.save(state)
            pipeline._begin_effort_execution(
                state, agent_overrides=None, model_overrides=None, reasoning_effort_overrides=None
            )
            snapshot = pipeline.store.load_effort_policy(state.id).prepared_policies[-1]
            self.assertEqual(snapshot.review_decisions[0].reviewer_model, "review-v1")
            with patch.object(pipeline, "_invoke_provider_command", return_value="approved") as provider:
                pipeline._invoke_agent(
                    state, state.tasks[0], reviewer, "review", root / "review.log", TaskAction.REVIEW
                )
                self.assertIn("Execution effort policy: focused", provider.call_args.kwargs["prompt"])
            changed_reviewer = AgentConfig(
                "reviewer", ("general",), (sys.executable, "-c", "pass"), 2,
                provider_id="local-review", model="review-v2",
            )
            pipeline.agents["reviewer"] = changed_reviewer
            with patch.object(pipeline, "_invoke_provider_command") as provider:
                with self.assertRaisesRegex(PipelineError, "reviewer runtime differs"):
                    pipeline._invoke_agent(
                        state, state.tasks[0], changed_reviewer, "review", root / "review.log", TaskAction.REVIEW
                    )
                provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
