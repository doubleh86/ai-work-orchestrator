import sys
import tempfile
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, PlanningConfig, ProjectConfig, RoutingConfig
from ai_orchestrator.effort_policy import resolve_reasoning_profile
from ai_orchestrator.model_selection import CODEX_LUNA_MODEL, CODEX_SOL_MODEL, CODEX_TERRA_MODEL, select_codex_model, small_codex_task
from ai_orchestrator.models import EffortMode, ProfileSource, RiskLevel, RunState, Stage, TaskAction, TaskActionResult, WorkTask
from ai_orchestrator.pipeline import Pipeline, PipelineError, TaskVerificationFailure
from ai_orchestrator.planner import Plan, PlanningError, assign_plan_agents


def small_task(**changes: object) -> WorkTask:
    return WorkTask("copy", "버튼 문구 오탈자 수정", ["frontend"], description="정해진 문구만 교체한다.",
                    acceptance_criteria=["동작은 유지하고 맞춤법을 수정한다."], expected_paths=["src/Button.tsx"],
                    risk_level=RiskLevel.LOW, **changes)


class AutomaticModelSelectionTest(unittest.TestCase):
    def test_small_tasks_use_luna_in_economy_and_terra_in_balanced(self) -> None:
        task = small_task()
        self.assertTrue(small_codex_task(task))
        for mode, expected in [(EffortMode.ECONOMY, CODEX_LUNA_MODEL), (EffortMode.BALANCED, CODEX_TERRA_MODEL),
                               (EffortMode.FOCUSED, CODEX_SOL_MODEL)]:
            with self.subTest(mode=mode):
                self.assertEqual(select_codex_model(mode, purpose="task", task=task).model, expected)

    def test_sensitive_unknown_and_unbounded_tasks_always_keep_sol(self) -> None:
        for change in [dict(risk_level=RiskLevel.MEDIUM), dict(description="권한 검사 계약 수정"),
                       dict(expected_paths=["src/**"]), dict(expected_paths=[]), dict(capabilities=["backend"]),
                       dict(title="일반 기능 변경", description="기능을 구현한다.", acceptance_criteria=[]),
                       dict(expected_paths=["src/auth/Button.tsx"]), dict(risk_level=RiskLevel.HIGH)]:
            for mode in EffortMode:
                with self.subTest(change=change, mode=mode):
                    self.assertEqual(select_codex_model(mode, purpose="task", task=replace(small_task(), **change)).model, CODEX_SOL_MODEL)

    def test_prerequisite_and_conflicting_tasks_keep_sol_even_when_the_edit_looks_small(self) -> None:
        for change in [dict(is_prerequisite=True), dict(conflict_group="shared-layout")]:
            for mode in EffortMode:
                with self.subTest(change=change, mode=mode):
                    decision = select_codex_model(mode, purpose="task", task=replace(small_task(), **change))
                    self.assertEqual(decision.model, CODEX_SOL_MODEL)

    def test_balanced_terra_keeps_high_but_reserves_higher_reasoning_for_sol(self) -> None:
        for effort, model, expected_effort in [("", CODEX_TERRA_MODEL, "medium"), ("high", CODEX_TERRA_MODEL, "high"),
                                               ("xhigh", CODEX_SOL_MODEL, "xhigh"), ("max", CODEX_SOL_MODEL, "max"),
                                               ("ultra", CODEX_SOL_MODEL, "ultra")]:
            with self.subTest(effort=effort):
                result = select_codex_model(EffortMode.BALANCED, purpose="task", task=small_task(), reasoning_effort=effort)
                self.assertEqual((result.model, result.reasoning_effort), (model, expected_effort))

    def test_balanced_terra_is_fixed_in_plan_and_effort_preview_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self.bound_pipeline(Path(directory), mode=EffortMode.BALANCED)
            task = state.tasks[0]
            self.assertEqual((task.model, task.reasoning_effort, task.profile_source),
                             (CODEX_TERRA_MODEL, "medium", ProfileSource.MODE))
            decision = resolve_reasoning_profile(mode="balanced", provider_id="codex", model=task.model,
                reasoning_effort=task.reasoning_effort, profile_source=task.profile_source,
                baseline_reasoning_effort=task.effort_baseline_reasoning, purpose="task", task=task)
            self.assertEqual((decision.model, decision.reasoning_effort), (task.model, task.reasoning_effort))
            snapshot = pipeline.store.load_effort_policy(state.id).policy(state.active_policy_id)
            self.assertEqual(dict(snapshot.task_profiles)[task.id].model, CODEX_TERRA_MODEL)
            restored = pipeline.store.load(state.id)
            pipeline._validate_effort_execution_snapshot(restored, snapshot)

    def test_planning_analysis_and_conflicts_keep_sol_in_every_mode(self) -> None:
        for mode in EffortMode:
            for purpose in ["planning", "chat", "recovery", "conflict_resolution"]:
                with self.subTest(mode=mode, purpose=purpose):
                    result = select_codex_model(mode, purpose=purpose, task=small_task())
                    self.assertEqual((result.model, result.reasoning_effort), (CODEX_SOL_MODEL, "high"))

    def test_manual_legacy_and_other_provider_profiles_are_preserved(self) -> None:
        for provider, source in [("codex", ProfileSource.MANUAL), ("codex", ProfileSource.LEGACY),
                                 ("claude", ProfileSource.MANUAL), ("custom", ProfileSource.LEGACY)]:
            with self.subTest(provider=provider, source=source):
                model = "gpt-5.6-sol" if provider == "codex" else "saved-model"
                result = resolve_reasoning_profile(mode="economy", provider_id=provider, model=model, reasoning_effort="high",
                                                   profile_source=source, purpose="task", task=small_task())
                self.assertEqual((result.model, result.reasoning_effort, result.profile_source), (model, "high", source))

    def test_plan_assignment_resolves_models_and_reason_before_execution(self) -> None:
        agent = AgentConfig("worker", ("general",), (), 4, provider_id="codex", model="gpt-5.6-luna")
        plan = Plan("copy", False, [small_task()], [])
        assign_plan_agents(plan, (agent,), RoutingConfig(), effort_mode=EffortMode.ECONOMY)
        task = plan.tasks[0]
        self.assertEqual(task.model, CODEX_LUNA_MODEL)
        self.assertEqual(task.profile_source, ProfileSource.MODE)
        self.assertIn("작은 수정", task.model_selection_reason)
        decision = resolve_reasoning_profile(mode="economy", provider_id="codex", model=task.model,
                                             reasoning_effort=task.reasoning_effort, profile_source=task.profile_source,
                                             baseline_reasoning_effort=task.effort_baseline_reasoning, purpose="task", task=task)
        self.assertEqual((decision.model, decision.reasoning_effort), (task.model, task.reasoning_effort))

    def test_manual_terra_survives_every_effort_mode(self) -> None:
        for mode in EffortMode:
            with self.subTest(mode=mode):
                result = resolve_reasoning_profile(mode=mode, provider_id="codex", model="gpt-6.1-terra", reasoning_effort="ultra",
                                                   profile_source=ProfileSource.MANUAL, purpose="task", task=small_task())
                self.assertEqual((result.model, result.reasoning_effort, result.profile_source),
                                 ("gpt-6.1-terra", "ultra", ProfileSource.MANUAL))

    def test_ai_cannot_reintroduce_an_old_or_arbitrary_automatic_model(self) -> None:
        agent = AgentConfig("worker", ("general",), (), 4, provider_id="codex", model="gpt-5.6-sol")
        for model in ["gpt-5.6-sol", "gpt-5.6-luna", "future-model"]:
            with self.subTest(model=model):
                plan = Plan("copy", False, [small_task(provider_id="codex", model=model)], [])
                with self.assertRaises(PlanningError):
                    assign_plan_agents(plan, (agent,), RoutingConfig(), effort_mode=EffortMode.ECONOMY)

    def test_manual_provider_with_automatic_model_is_concrete_before_confirmation(self) -> None:
        agent = AgentConfig("worker", ("general",), (), 4, provider_id="codex", model="gpt-5.6-luna")
        task = small_task(agent_id=agent.id, provider_id="codex", profile_source=ProfileSource.MANUAL, reasoning_effort="high")
        assign_plan_agents(Plan("copy", False, [task], []), (agent,), RoutingConfig(), effort_mode=EffortMode.ECONOMY)
        self.assertEqual((task.model, task.reasoning_effort, task.profile_source), (CODEX_SOL_MODEL, "high", ProfileSource.MANUAL))

    @staticmethod
    def bound_pipeline(root: Path, *, mode: EffortMode = EffortMode.ECONOMY) -> tuple[Pipeline, RunState]:
        worker = AgentConfig("worker", ("general",), (), 4, provider_id="codex", model=CODEX_SOL_MODEL)
        pipeline = Pipeline(Config(path=root / "config.toml", project=ProjectConfig(repo=root), execution=ExecutionConfig(),
                                   agents=(worker,), planning=PlanningConfig(agent_id="worker"), routing=RoutingConfig()), codex_sdk=Mock())
        plan = Plan("copy", False, [small_task()], [])
        assign_plan_agents(plan, (worker,), RoutingConfig(), effort_mode=mode)
        task = plan.tasks[0]
        task.worktree = str(root)
        task.prompt_path = str(root / "prompt.md")
        Path(task.prompt_path).write_text("implement only the approved copy", encoding="utf-8")
        state = RunState("model-run", "", "", str(root), "main", stage=Stage.PLANNED, plan_revision=1, plan_approved_revision=1,
                         tasks=plan.tasks, planning_agent_id="worker", planning_provider_id="codex", planning_model=CODEX_SOL_MODEL,
                         planning_reasoning_effort="high", planning_profile_source=ProfileSource.MANUAL)
        pipeline.store.save(state)
        pipeline.set_effort_mode(state.id, mode.value, expected_revision=0, request_id=str(uuid.uuid4()))
        pipeline._begin_effort_execution(state, agent_overrides=None, model_overrides=None, reasoning_effort_overrides=None)
        return pipeline, state

    @staticmethod
    def record_failure(task: WorkTask) -> None:
        task.action_results.append(TaskActionResult(action="verify", status="failed", baseline_commit="commit",
                                                   verification_failure_kind="command_failed"))

    def test_promotion_is_bound_saved_once_and_does_not_change_the_frozen_original_profile(self) -> None:
        for mode, original in [(EffortMode.ECONOMY, CODEX_LUNA_MODEL), (EffortMode.BALANCED, CODEX_TERRA_MODEL)]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                pipeline, state = self.bound_pipeline(Path(directory), mode=mode)
                task = state.tasks[0]
                self.record_failure(task)
                failure = TaskVerificationFailure(task.id, ["test"], "AssertionError: wrong text", Path(directory) / "test.log")
                pipeline._promote_automatic_model(state, task, failure)
                self.assertEqual(task.model, CODEX_SOL_MODEL)
                self.assertEqual(task.reasoning_effort, "high")
                restored = pipeline.store.load(state.id)
                self.assertEqual(restored.tasks[0].model_escalation_policy_id, state.active_policy_id)
                snapshot = pipeline.store.load_effort_policy(state.id).policy(state.active_policy_id)
                self.assertEqual(dict(snapshot.task_profiles)[task.id].model, original)
                pipeline._validate_effort_execution_snapshot(restored, snapshot)
                count = len(state.events)
                pipeline._promote_automatic_model(state, task, failure)
                self.assertEqual(len(state.events), count)
                with patch.object(pipeline, "_invoke_provider_command", return_value="fixed") as provider:
                    pipeline._invoke_agent(state, task, pipeline.agents[task.agent_id], "correct",
                                           Path(directory) / "repair.log", TaskAction.EXECUTE)
                    self.assertEqual(provider.call_args.kwargs["model"], CODEX_SOL_MODEL)

    def test_promotion_does_not_allow_a_manual_change_or_tampered_failure_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self.bound_pipeline(Path(directory))
            task = state.tasks[0]
            self.record_failure(task)
            failure = TaskVerificationFailure(task.id, ["test"], "AssertionError", Path(directory) / "test.log")
            pipeline._promote_automatic_model(state, task, failure)
            snapshot = pipeline.store.load_effort_policy(state.id).policy(state.active_policy_id)
            for field, value in [("reasoning_effort", "max"), ("model", "gpt-5.6-sol"),
                                 ("model_escalation_policy_id", "other"), ("model_escalation_result_index", 12)]:
                with self.subTest(field=field):
                    changed = RunState.from_dict(state.to_dict())
                    setattr(changed.tasks[0], field, value)
                    with self.assertRaises(PipelineError):
                        pipeline._validate_effort_execution_snapshot(changed, snapshot)
            task.action_results[0].verification_failure_kind = "timeout"
            with self.assertRaises(PipelineError):
                pipeline._validate_effort_execution_snapshot(state, snapshot)

    def test_existing_automatic_correction_loop_executes_the_promoted_model_once(self) -> None:
        for mode, original in [(EffortMode.ECONOMY, CODEX_LUNA_MODEL), (EffortMode.BALANCED, CODEX_TERRA_MODEL)]:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                pipeline, state = self.bound_pipeline(Path(directory), mode=mode)
                task = state.tasks[0]
                calls = []

                def attempt(*args: object, **kwargs: object) -> None:
                    calls.append(task.model)
                    if len(calls) == 1:
                        self.record_failure(task)
                        raise TaskVerificationFailure(task.id, ["test"], "AssertionError: copy mismatch", Path(directory) / "test.log")
                    with patch.object(pipeline, "_invoke_provider_command", return_value="corrected") as provider:
                        pipeline._invoke_agent(state, task, pipeline.agents[task.agent_id], "fix",
                                               Path(directory) / "repair.log", TaskAction.EXECUTE)
                        self.assertEqual(provider.call_args.kwargs["model"], CODEX_SOL_MODEL)

                with patch.object(pipeline, "_run_task_attempt", side_effect=attempt), \
                        patch.object(pipeline, "_ensure_verification_head"), patch.object(pipeline, "_validate_task_change_scope"):
                    pipeline._run_task(state, task)
                self.assertEqual(calls, [original, CODEX_SOL_MODEL])
                self.assertEqual(task.model_escalation_result_index, 0)

    def test_unchanged_failure_after_promotion_keeps_existing_repeat_guard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self.bound_pipeline(Path(directory))
            task = state.tasks[0]
            calls = []

            def attempt(*args: object, **kwargs: object) -> None:
                calls.append(task.model)
                self.record_failure(task)
                raise TaskVerificationFailure(task.id, ["test"], "AssertionError: unchanged", Path(directory) / "test.log")

            with patch.object(pipeline, "_run_task_attempt", side_effect=attempt), \
                    patch.object(pipeline, "_ensure_verification_head"), patch.object(pipeline, "_validate_task_change_scope"):
                with self.assertRaisesRegex(PipelineError, "같은 검증 실패"):
                    pipeline._run_task(state, task)
            self.assertEqual(calls, [CODEX_LUNA_MODEL, CODEX_SOL_MODEL])

    def test_environment_errors_and_manual_selection_never_promote(self) -> None:
        for mode, original in [(EffortMode.ECONOMY, CODEX_LUNA_MODEL), (EffortMode.BALANCED, CODEX_TERRA_MODEL)]:
            for source, output, kind in [(ProfileSource.MODE, ".NET SDK not found", "command_failed"),
                                        (ProfileSource.MODE, "MSB4236 missing SDK", "command_failed"),
                                        (ProfileSource.MODE, "timeout", "timeout"),
                                        (ProfileSource.MANUAL, "AssertionError: wrong text", "command_failed")]:
                with self.subTest(mode=mode, source=source, output=output), tempfile.TemporaryDirectory() as directory:
                    pipeline, state = self.bound_pipeline(Path(directory), mode=mode)
                    task = state.tasks[0]
                    task.profile_source = source
                    self.record_failure(task)
                    task.action_results[-1].verification_failure_kind = kind
                    pipeline._promote_automatic_model(state, task, TaskVerificationFailure(
                        task.id, ["test"], output, Path(directory) / "test.log"))
                    self.assertEqual(task.model, original)
                    self.assertEqual(task.model_escalation_result_index, -1)

    def test_started_pre_terra_balanced_policy_is_reused_without_reselection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self.bound_pipeline(Path(directory), mode=EffortMode.BALANCED)
            saved = pipeline.store.load_effort_policy(state.id)
            current = saved.policy(state.active_policy_id)
            old = replace(current, task_profiles=tuple((task_id, replace(profile, model=CODEX_SOL_MODEL))
                                                      for task_id, profile in current.task_profiles))
            saved = replace(saved, prepared_policies=tuple(old if item.policy_id == old.policy_id else item
                                                           for item in saved.prepared_policies))
            state.tasks[0].model = CODEX_SOL_MODEL
            restored = RunState.from_dict(state.to_dict())
            with patch.object(pipeline.store, "load_effort_policy", return_value=saved), \
                    patch.object(pipeline, "preview_effort_mode", side_effect=AssertionError("started policy must stay fixed")):
                request_id = pipeline._begin_effort_execution(restored, agent_overrides=None, model_overrides=None,
                                                              reasoning_effort_overrides=None)
            self.assertEqual(request_id, state.active_execution_request_id)
            self.assertEqual(restored.tasks[0].model, CODEX_SOL_MODEL)

    def test_legacy_state_has_no_promotion_and_completed_profiles_do_not_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self.bound_pipeline(Path(directory))
            raw = state.to_dict()
            for name in ["model_selection_reason", "model_escalation_policy_id", "model_escalation_result_index"]:
                raw["tasks"][0].pop(name)
            restored = RunState.from_dict(raw)
            self.assertEqual(restored.tasks[0].model_escalation_result_index, -1)
            state.tasks[0].status = "completed"
            pipeline.store.save(state)
            result = pipeline.preview_effort_mode(state.id, "balanced", expected_revision=1)
            self.assertEqual(result.tasks[0].reasoning.model, CODEX_LUNA_MODEL)

    def test_old_fixed_execution_policy_is_not_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self.bound_pipeline(Path(directory))
            task = state.tasks[0]
            self.record_failure(task)
            saved = pipeline.store.load_effort_policy(state.id)
            old = replace(saved, prepared_policies=tuple(replace(item, policy_version=2) for item in saved.prepared_policies))
            with patch.object(pipeline.store, "load_effort_policy", return_value=old):
                pipeline._promote_automatic_model(state, task, TaskVerificationFailure(
                    task.id, ["test"], "AssertionError", Path(directory) / "test.log",
                ))
            self.assertEqual(task.model, CODEX_LUNA_MODEL)
            self.assertEqual(task.model_escalation_result_index, -1)

    def test_new_automatic_task_added_in_plan_editor_keeps_its_selection_origin_and_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pipeline, state = self.bound_pipeline(Path(directory))
            draft = pipeline._task_plan_draft(small_task())
            draft["id"] = "new-copy"
            draft["verify_commands"] = [[sys.executable, "-c", "pass"]]
            with patch.object(pipeline, "_planning_execution_agents", return_value=pipeline.config.agents):
                plan = pipeline._validated_plan_draft(state, [draft])
            task = plan.tasks[0]
            self.assertEqual((task.model, task.profile_source, task.effort_baseline_reasoning),
                             (CODEX_LUNA_MODEL, ProfileSource.MODE, ""))
            self.assertTrue(task.model_selection_reason)

    def test_new_balanced_plan_is_already_pinned_without_an_extra_mode_apply_step(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worker = AgentConfig("worker", ("general",), (), 4, provider_id="codex", model="gpt-5.6-luna")
            pipeline = Pipeline(Config(path=root / "config.toml", project=ProjectConfig(repo=root), execution=ExecutionConfig(),
                                       agents=(worker,), planning=PlanningConfig(agent_id="worker")), codex_sdk=Mock())
            state = RunState("new-plan", "", "", str(root), "main", stage=Stage.REVIEWED,
                             planning_agent_id="worker", planning_provider_id="codex", planning_profile_source=ProfileSource.ROUTING)
            pipeline.store.save(state)
            plan = Plan("copy", False, [small_task()], [])
            assign_plan_agents(plan, (worker,), RoutingConfig())
            pipeline._apply_plan(state, plan)
            preview = pipeline.preview_effort_mode(state.id, "balanced", expected_revision=0)
            self.assertFalse(preview.requires_plan_review)
            self.assertEqual((state.planning_model, state.planning_reasoning_effort), (CODEX_SOL_MODEL, "high"))
            prompt = root / "planning.md"
            prompt.write_text("Plan", encoding="utf-8")
            with patch.object(pipeline, "_invoke_provider_command", return_value="planned") as provider:
                pipeline._invoke_planning_agent(state, worker, "Plan", prompt, root / "planning.log")
                self.assertEqual(provider.call_args.kwargs["model"], CODEX_SOL_MODEL)

    def test_planning_without_a_selected_mode_closes_the_sdk_default_but_keeps_manual_choice(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pipeline, state = self.bound_pipeline(root)
            fresh = replace(state, id="no-mode", planning_model="gpt-5.6-luna", planning_reasoning_effort="medium",
                            planning_profile_source=ProfileSource.ROUTING)
            pipeline.store.save(fresh)
            prompt = root / "planning.md"
            prompt.write_text("Plan", encoding="utf-8")
            for source, expected, effort in [(ProfileSource.ROUTING, CODEX_SOL_MODEL, "high"),
                                             (ProfileSource.MANUAL, "gpt-5.6-luna", "medium")]:
                with self.subTest(source=source), patch.object(pipeline, "_invoke_provider_command", return_value="planned") as provider:
                    fresh.planning_profile_source = source
                    pipeline._invoke_planning_agent(fresh, pipeline.agents["worker"], "Plan", prompt, root / "planning.log")
                    self.assertEqual((provider.call_args.kwargs["model"], provider.call_args.kwargs["reasoning_effort"]),
                                     (expected, effort))
