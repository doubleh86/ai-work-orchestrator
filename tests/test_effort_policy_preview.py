import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, PlanningConfig, ProjectConfig, RoutingConfig
from ai_orchestrator.codex_sdk import CodexSdkAccountStatus
from ai_orchestrator.models import EffortMode, EffortPolicyRevisionError, ProfileSource, ReviewStatus, RunState, Stage, WorkTask
from ai_orchestrator.pipeline import Pipeline, PipelineError
from ai_orchestrator.planner import Plan


class EffortPolicyPreviewTest(unittest.TestCase):
    def _pipeline(self, root: Path, *, review_required: bool = False) -> Pipeline:
        agents = (
            AgentConfig("worker", ("general",), (), 2, provider_id="codex", model="gpt-6-sol"),
            AgentConfig("reviewer", ("general",), (sys.executable, "-c", "pass"), 2, provider_id="local"),
        )
        config = Config(
            path=root / "orchestrator.toml", project=ProjectConfig(repo=root), execution=ExecutionConfig(),
            agents=agents, planning=PlanningConfig(agent_id="worker"),
            routing=RoutingConfig(default_provider="codex", review_required=review_required),
        )
        sdk = Mock()
        sdk.account_status.return_value = CodexSdkAccountStatus(True, "chatgpt", "로그인됨")
        return Pipeline(config, codex_sdk=sdk)

    @staticmethod
    def _task(task_id: str, source: ProfileSource, *, reviewer_agent_id: str = "") -> WorkTask:
        return WorkTask(
            task_id, task_id, ["general"], agent_id="worker", provider_id="codex", model="gpt-6-sol",
            reasoning_effort="medium", profile_source=source, expected_paths=["src/**"], reviewer_agent_id=reviewer_agent_id,
        )

    def test_preview_preserves_manual_and_legacy_profiles_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline = self._pipeline(Path(directory))
            state = RunState(
                "run-1", "plan.md", "digest", directory, "main", stage=Stage.PLANNED,
                planning_agent_id="worker", planning_provider_id="codex", planning_profile_source=ProfileSource.MANUAL,
                plan_revision=2, plan_approved_revision=2,
                tasks=[
                    self._task("routing", ProfileSource.ROUTING),
                    self._task("manual", ProfileSource.MANUAL),
                    self._task("legacy", ProfileSource.LEGACY),
                ],
            )
            pipeline.store.save(state)
            original = pipeline.store.state_path(state.id).read_bytes()

            focused = pipeline.preview_effort_mode(state.id, EffortMode.FOCUSED, expected_revision=0)
            self.assertEqual(focused.plan_revision, 2)
            self.assertEqual([item.reasoning.reasoning_effort for item in focused.tasks], ["high", "medium", "medium"])
            self.assertEqual(focused.manual_exception_ids, ("manual",))
            self.assertTrue(all(item.review.policy_added for item in focused.tasks))
            self.assertIn("legacy:legacy_profile_preserved", focused.unsupported_effects)
            self.assertTrue(focused.requires_plan_review)
            self.assertEqual(focused.planning_reasoning.profile_source, ProfileSource.MANUAL)

            economy = pipeline.preview_effort_mode(state.id, "economy", expected_revision=0)
            self.assertEqual(economy.tasks[0].reasoning.reasoning_effort, "medium")
            self.assertFalse(any(item.review.policy_added for item in economy.tasks))
            balanced = pipeline.preview_effort_mode(state.id, "balanced", expected_revision=0)
            self.assertTrue(balanced.requires_plan_review)
            with self.assertRaises(EffortPolicyRevisionError):
                pipeline.preview_effort_mode(state.id, "focused", expected_revision=1)
            self.assertEqual(pipeline.store.state_path(state.id).read_bytes(), original)
            self.assertFalse(pipeline.store.effort_policy_path(state.id).exists())

    def test_preview_keeps_required_review_and_reports_missing_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline = self._pipeline(Path(directory), review_required=True)
            state = RunState(
                "run-2", "plan.md", "digest", directory, "main", stage=Stage.PLANNED,
                tasks=[self._task("required", ProfileSource.ROUTING, reviewer_agent_id="reviewer")],
            )
            pipeline.store.save(state)
            preview = pipeline.preview_effort_mode(state.id, "economy", expected_revision=0)
            self.assertTrue(preview.tasks[0].review.required)
            self.assertFalse(preview.tasks[0].review.policy_added)

            pipeline.agents.pop("reviewer")
            no_reviewer = pipeline.preview_effort_mode(state.id, "focused", expected_revision=0)
            self.assertTrue(no_reviewer.tasks[0].review.required)
            self.assertFalse(no_reviewer.tasks[0].review.policy_added)
            self.assertIn("required:reviewer_unavailable", no_reviewer.unsupported_effects)

    def test_focused_preview_reports_unavailable_optional_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worker = AgentConfig("worker", ("general",), (), 1, provider_id="codex", model="gpt-6-sol")
            pipeline = Pipeline(
                Config(
                    path=root / "orchestrator.toml", project=ProjectConfig(repo=root), execution=ExecutionConfig(),
                    agents=(worker,), routing=RoutingConfig(default_provider="codex"),
                ),
                codex_sdk=Mock(),
            )
            state = RunState(
                "run-no-reviewer", "plan.md", "digest", directory, "main", stage=Stage.PLANNED,
                tasks=[self._task("t01", ProfileSource.ROUTING)],
            )
            pipeline._codex_sdk = None
            pipeline.store.save(state)

            preview = pipeline.preview_effort_mode(state.id, "focused", expected_revision=0)

            self.assertTrue(preview.tasks[0].review.policy_added)
            self.assertIn("t01:reviewer_unavailable", preview.unsupported_effects)
            self.assertTrue(preview.requires_plan_review)

    def test_plan_edit_marks_changed_profile_manual_and_preserves_unchanged_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = Config(
                path=root / "orchestrator.toml", project=ProjectConfig(repo=root), execution=ExecutionConfig(),
                agents=(
                    AgentConfig("worker-a", ("general",), (sys.executable, "-c", "pass"), provider_id="local-a"),
                    AgentConfig("worker-b", ("general",), (sys.executable, "-c", "pass"), provider_id="local-b"),
                ),
                routing=RoutingConfig(default_provider="local-a"),
            )
            pipeline = Pipeline(config)
            task = WorkTask(
                "t01", "Task", ["general"], description="Update app", acceptance_criteria=["Works"],
                expected_paths=["src/**"], verify_commands=[["python", "-m", "unittest"]],
                agent_id="worker-a", provider_id="local-a", profile_source=ProfileSource.ROUTING,
            )
            state = RunState("run-edit", "plan.md", "digest", directory, "main", stage=Stage.PLANNED, tasks=[task])
            pipeline.store.save(state)

            draft = pipeline._task_plan_draft(task)
            draft["title"] = "Renamed"
            unchanged = pipeline.update_plan(state.id, [draft])
            self.assertEqual(unchanged.tasks[0].profile_source, ProfileSource.ROUTING)

            changed_draft = pipeline._task_plan_draft(unchanged.tasks[0])
            changed_draft["provider_id"] = "local-b"
            changed = pipeline.update_plan(state.id, [changed_draft])
            self.assertEqual(changed.tasks[0].provider_id, "local-b")
            self.assertEqual(changed.tasks[0].profile_source, ProfileSource.MANUAL)

            same_draft = pipeline._task_plan_draft(changed.tasks[0])
            same_draft["title"] = "Renamed again"
            preserved = pipeline.update_plan(state.id, [same_draft])
            self.assertEqual(preserved.tasks[0].profile_source, ProfileSource.MANUAL)

    def test_explicit_planning_profile_change_records_manual_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline = self._pipeline(Path(directory))
            state = RunState(
                "run-3", "plan.md", "digest", directory, "main", stage=Stage.PLANNED,
                planning_agent_id="worker", planning_provider_id="codex", planning_profile_source=ProfileSource.ROUTING,
            )
            pipeline._configure_planning_profile(
                state, planning_agent_id=None, planning_model="gpt-6-sol", planning_reasoning_effort="medium"
            )
            self.assertEqual(state.planning_profile_source, ProfileSource.MANUAL)

    def test_replanning_preserves_manual_source_only_when_profile_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline = self._pipeline(Path(directory))
            original = self._task("t01", ProfileSource.MANUAL)
            state = RunState("run-replan", "plan.md", "digest", directory, "main", stage=Stage.PLANNED, tasks=[original])
            pipeline.store.save(state)

            same_profile = self._task("t01", ProfileSource.ROUTING)
            preserved = pipeline._apply_plan(state, Plan(summary="Plan", server_work=False, tasks=[same_profile]))
            self.assertEqual(preserved.tasks[0].profile_source, ProfileSource.MANUAL)

            changed_profile = self._task("t01", ProfileSource.ROUTING)
            changed_profile.reasoning_effort = "high"
            replaced = pipeline._apply_plan(preserved, Plan(summary="Plan", server_work=False, tasks=[changed_profile]))
            self.assertEqual(replaced.tasks[0].profile_source, ProfileSource.ROUTING)

    def test_mode_application_requires_explicit_reviewer_and_plan_reconfirmation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline = self._pipeline(Path(directory))
            task = self._task("t01", ProfileSource.ROUTING)
            task.description = "Change app"
            task.acceptance_criteria = ["Works"]
            task.verify_commands = [[sys.executable, "-c", "pass"]]
            state = RunState(
                "run-apply", "plan.md", "digest", directory, "main", stage=Stage.PLANNED,
                summary="Plan", plan_revision=1, plan_approved_revision=1, tasks=[task],
                planning_agent_id="worker", planning_provider_id="codex", planning_reasoning_effort="medium",
                planning_profile_source=ProfileSource.ROUTING,
            )
            pipeline.store.save(state)
            pipeline.store.save_planning_chat(state)
            selected = pipeline.set_effort_mode(state.id, "focused", expected_revision=0, request_id=str(uuid.uuid4()))
            self.assertEqual(selected.revision, 1)
            with self.assertRaisesRegex(PipelineError, "must be applied"):
                pipeline.confirm_plan(state.id)
            with self.assertRaises(PipelineError):
                pipeline.apply_effort_mode_to_plan(
                    state.id, "focused", expected_policy_revision=1, expected_plan_revision=1
                )
            with self.assertRaises(PipelineError):
                pipeline.apply_effort_mode_to_plan(
                    state.id, "focused", expected_policy_revision=1, expected_plan_revision=1,
                    reviewer_agent_ids={"t01": "missing"},
                )
            self.assertEqual(pipeline.store.load(state.id).plan_revision, 1)
            self.assertFalse(pipeline.store.run_dir(state.id).joinpath("plan.json").exists())

            applied = pipeline.apply_effort_mode_to_plan(
                state.id, "focused", expected_policy_revision=1, expected_plan_revision=1,
                reviewer_agent_ids={"t01": "reviewer"},
            )
            self.assertEqual(applied.plan_revision, 2)
            self.assertFalse(applied.plan_is_approved)
            self.assertEqual(applied.tasks[0].reasoning_effort, "high")
            self.assertEqual(applied.tasks[0].profile_source, ProfileSource.MODE)
            self.assertEqual(applied.tasks[0].effort_baseline_reasoning, "medium")
            self.assertEqual(applied.planning_reasoning_effort, "high")
            self.assertEqual(applied.planning_effort_baseline_reasoning, "medium")
            self.assertEqual(pipeline.store.load(state.id).planning_effort_baseline_reasoning, "medium")
            self.assertEqual(applied.tasks[0].reviewer_agent_id, "reviewer")
            self.assertTrue(applied.tasks[0].review_policy_added)
            self.assertEqual(applied.tasks[0].review_status, ReviewStatus.PENDING)
            with self.assertRaises(PipelineError):
                pipeline.apply_effort_mode_to_plan(
                    state.id, "focused", expected_policy_revision=1, expected_plan_revision=1,
                    reviewer_agent_ids={"t01": "reviewer"},
                )

            confirmed = pipeline.confirm_plan(state.id)
            self.assertTrue(confirmed.plan_is_approved)
            self.assertEqual(confirmed.tasks[0].reviewer_agent_id, "reviewer")
            self.assertTrue(confirmed.tasks[0].review_policy_added)
            self.assertEqual(confirmed.tasks[0].profile_source, ProfileSource.MODE)
            def observe_started(current: RunState, **_: object) -> RunState:
                binding = pipeline.store.load_effort_policy(current.id).binding(current.active_execution_request_id)
                self.assertIsNotNone(binding)
                self.assertEqual(binding.status, "started")
                self.assertEqual(binding.policy_id, current.active_policy_id)
                return current

            with patch.object(pipeline, "_execute_with_bound_policy", side_effect=observe_started):
                executed = pipeline.execute(state.id)
            self.assertEqual(executed.active_policy_id, "")
            self.assertEqual(executed.active_execution_request_id, "")
            self.assertEqual(pipeline.store.load_effort_policy(state.id).execution_bindings[-1].status, "finished")

            draft = pipeline._task_plan_draft(confirmed.tasks[0])
            draft["title"] = "Renamed task"
            edited = pipeline.update_plan(state.id, [draft])
            self.assertEqual(edited.tasks[0].reviewer_agent_id, "reviewer")
            self.assertTrue(edited.tasks[0].review_policy_added)
            self.assertEqual(edited.tasks[0].effort_baseline_reasoning, "medium")
            pipeline.confirm_plan(state.id)

            pipeline.set_effort_mode(state.id, "economy", expected_revision=1, request_id=str(uuid.uuid4()))
            preview = pipeline.preview_effort_mode(state.id, "economy", expected_revision=2)
            self.assertTrue(preview.tasks[0].review.policy_removed)
            economy = pipeline.apply_effort_mode_to_plan(
                state.id, "economy", expected_policy_revision=2, expected_plan_revision=3
            )
            self.assertEqual(economy.tasks[0].reasoning_effort, "medium")
            self.assertEqual(economy.tasks[0].effort_baseline_reasoning, "medium")
            self.assertEqual(economy.planning_reasoning_effort, "high")
            self.assertEqual(economy.tasks[0].reviewer_agent_id, "")
            self.assertFalse(economy.tasks[0].review_policy_added)
            self.assertFalse(economy.plan_is_approved)

            pipeline.set_effort_mode(state.id, "balanced", expected_revision=2, request_id=str(uuid.uuid4()))
            balanced = pipeline.apply_effort_mode_to_plan(
                state.id, "balanced", expected_policy_revision=3, expected_plan_revision=4
            )
            self.assertEqual(balanced.tasks[0].reasoning_effort, "medium")
            self.assertEqual(balanced.tasks[0].profile_source, ProfileSource.MODE)
            self.assertEqual(balanced.tasks[0].effort_baseline_reasoning, "medium")
            self.assertEqual(balanced.planning_reasoning_effort, "high")
            self.assertEqual(balanced.planning_profile_source, ProfileSource.MODE)
            self.assertEqual(balanced.planning_effort_baseline_reasoning, "medium")

            manual_draft = pipeline._task_plan_draft(balanced.tasks[0])
            manual_draft["reasoning_effort"] = "xhigh"
            manual = pipeline.update_plan(state.id, [manual_draft])
            self.assertEqual(manual.tasks[0].profile_source, ProfileSource.MANUAL)
            self.assertIsNone(manual.tasks[0].effort_baseline_reasoning)

    def test_mode_application_preserves_required_and_legacy_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline = self._pipeline(Path(directory), review_required=True)
            task = self._task("t01", ProfileSource.LEGACY, reviewer_agent_id="reviewer")
            state = RunState(
                "run-required", "plan.md", "digest", directory, "main", stage=Stage.PLANNED,
                summary="Plan", plan_revision=1, plan_approved_revision=1, tasks=[task],
            )
            pipeline.store.save(state)
            pipeline.set_effort_mode(state.id, "economy", expected_revision=0, request_id=str(uuid.uuid4()))
            applied = pipeline.apply_effort_mode_to_plan(
                state.id, "economy", expected_policy_revision=1, expected_plan_revision=1
            )
            self.assertEqual(applied.plan_revision, 1)
            self.assertTrue(applied.plan_is_approved)
            self.assertEqual(applied.tasks[0].reasoning_effort, "medium")
            self.assertEqual(applied.tasks[0].reviewer_agent_id, "reviewer")
            self.assertFalse(applied.tasks[0].review_policy_added)
            self.assertEqual(pipeline.store.load_effort_policy(state.id).revision, 1)

    def test_review_policy_added_round_trip_defaults_false_for_legacy(self) -> None:
        state = RunState(
            "run-review", "plan.md", "digest", "repo", "main", stage=Stage.PLANNED,
            tasks=[self._task("t01", ProfileSource.ROUTING, reviewer_agent_id="reviewer")],
        )
        state.tasks[0].review_policy_added = True
        restored = RunState.from_dict(state.to_dict())
        self.assertTrue(restored.tasks[0].review_policy_added)
        legacy = state.to_dict()
        legacy["schema_version"] = 35
        legacy["tasks"][0].pop("review_policy_added")
        self.assertFalse(RunState.from_dict(legacy).tasks[0].review_policy_added)
        legacy["tasks"][0]["review_policy_added"] = "false"
        with self.assertRaisesRegex(ValueError, "boolean"):
            RunState.from_dict(legacy)


if __name__ == "__main__":
    unittest.main()
