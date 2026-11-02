import json
import tempfile
import unittest
from pathlib import Path

from ai_orchestrator.config import AgentConfig, RoutingConfig, RoutingRule
from ai_orchestrator.models import PlanningMode, ProfileSource, ReviewStatus, RiskLevel, TaskReadiness, WorkTask
from ai_orchestrator.planner import (
    PLAN_MARKER,
    Plan,
    PlanningError,
    assign_plan_agents,
    assign_task_agent_overrides,
    build_plan,
    discover_repository_instruction_documents,
    infer_capabilities,
    parse_structured_plan,
    planning_prompt,
    read_planning_document,
    read_planning_source_documents,
    read_repository_instruction_documents,
    structured_plan_dict,
    task_paths_may_overlap,
    technology_stack_plan_example,
    validate_task_graph,
)

AGENTS = (
    AgentConfig("backend-ai", ("backend", "api", "database"), (), 3),
    AgentConfig("frontend-ai", ("frontend", "mobile"), (), 3),
    AgentConfig("qa-ai", ("qa", "general"), (), 3),
)


def structured_task(task_id: str, *, capabilities: list[str] | None = None, dependencies: list[str] | None = None) -> dict[str, object]:
    return {
        "id": task_id,
        "title": f"{task_id} title",
        "description": f"{task_id} description",
        "capabilities": capabilities or ["general"],
        "depends_on": dependencies or [],
        "acceptance_criteria": [f"{task_id} works"],
        "expected_paths": [f"src/{task_id}/**"],
        "forbidden_paths": ["secrets/**"],
        "verify_commands": [["python", "-m", "unittest", f"tests.test_{task_id}"]],
        "risk_level": "medium",
    }


class PlannerTest(unittest.TestCase):
    def test_sequential_assignment_reuses_agents_and_keeps_review_separate(self) -> None:
        agents = (
            AgentConfig("codex", ("general",), (), 1, provider_id="codex"),
            AgentConfig("claude", ("general",), ("claude",), 1, provider_id="claude"),
        )
        routing = RoutingConfig(default_provider="codex", review_required=True, balance_providers=False)
        plan = Plan("many tasks", False, [WorkTask(str(i), "Task", ["general"]) for i in range(6)])
        assign_plan_agents(plan, agents, routing, sequential=True)
        self.assertTrue(all(task.agent_id == "codex" for task in plan.tasks))
        self.assertTrue(all(task.reviewer_agent_id == "claude" for task in plan.tasks))
        assign_task_agent_overrides(plan.tasks, agents, routing, {task.id: "claude" for task in plan.tasks}, sequential=True)
        self.assertTrue(all(task.agent_id == "claude" for task in plan.tasks))
        self.assertTrue(all(task.reviewer_agent_id == "codex" for task in plan.tasks))
        with self.assertRaisesRegex(PlanningError, "capacity"):
            assign_plan_agents(plan, agents, routing)
        with self.assertRaisesRegex(PlanningError, "no review agent"):
            assign_plan_agents(Plan("review", False, [WorkTask("only", "Task", ["general"])]), agents[:1], routing, sequential=True)

    def test_sdk_catalog_has_codex_without_command_and_no_sequential_total_limit(self) -> None:
        prompt = planning_prompt("plan", execution_agents=(AgentConfig("sdk", ("general",), (), 1, provider_id="codex"),), sequential=True)
        self.assertIn("Provider `codex`", prompt)
        self.assertIn("agents can be reused without a total Task limit", prompt)
        self.assertNotIn("total Task capacity", prompt)
        self.assertIn("Planning provider and Task execution provider are separate", prompt)

    def test_conflict_path_overlap_is_rooted_and_conservative_for_globs(self) -> None:
        for first, second, expected in (
            ("src", "src/api/a.py", True),
            ("src", "src2/a.py", False),
            ("src/*.py", "src/a.py", True),
            ("src/*.py", "src/nested/a.py", False),
            ("src/**/*.py", "src/a.py", True),
            ("src/**/*.py", "src/nested/a.py", True),
            ("**/model.py", "src/model.py", True),
            ("src/*.py", "docs/*.py", False),
            ("src/*.py", "src/*.ts", True),
            ("src/file[12].py", "src/file3.py", False),
            ("Src/**", "src/file.py", False),
            ("README.md", "README2.md", False),
        ):
            with self.subTest(first=first, second=second):
                self.assertEqual(task_paths_may_overlap(first, second), expected)
                self.assertEqual(task_paths_may_overlap(second, first), expected)

    def test_conflict_groups_preserve_declared_dependency_order(self) -> None:
        a = WorkTask("a", "A", ["general"], expected_paths=["src/**"])
        b = WorkTask("b", "B", ["general"], expected_paths=["src/api/**"], dependencies=["c"])
        c = WorkTask("c", "C", ["general"], expected_paths=["src/lib/**"])
        d = WorkTask("d", "D", ["general"], expected_paths=["docs/**"])
        ordered = validate_task_graph([a, b, c, d])
        self.assertEqual([task.id for task in ordered], ["a", "c", "b", "d"])
        self.assertEqual(a.conflict_group, ["a", "c", "b"])
        self.assertEqual(b.conflict_group, a.conflict_group)
        self.assertEqual(c.conflict_group, a.conflict_group)
        self.assertEqual(d.conflict_group, [])
        self.assertEqual(b.dependencies, ["c"])
        self.assertEqual(b.conflict_dependencies, ["a"])
        self.assertEqual(c.conflict_dependencies, ["a"])
        self.assertEqual(b.blocked_by, ["c", "a"])
        first_result = [task.execution_dependencies for task in ordered]
        self.assertEqual([task.execution_dependencies for task in validate_task_graph(ordered)], first_result)

    def test_conflict_prerequisite_is_scheduled_before_consumer(self) -> None:
        consumer = structured_task("consumer")
        foundation = structured_task("schema")
        consumer["expected_paths"] = ["src/shared/**"]
        foundation["expected_paths"] = ["src/shared/models.py"]
        foundation["is_prerequisite"] = True
        consumer["conflict_dependencies"] = ["forged-missing-task"]
        consumer["conflict_group"] = ["forged-group"]
        plan = parse_structured_plan(
            PLAN_MARKER + " " + json.dumps({"summary": "plan", "server_work": False, "tasks": [consumer, foundation], "questions": []})
        )
        self.assertEqual([task.id for task in plan.tasks], ["schema", "consumer"])
        self.assertTrue(plan.tasks[0].is_prerequisite)
        self.assertEqual(plan.tasks[1].dependencies, [])
        self.assertEqual(plan.tasks[1].conflict_dependencies, ["schema"])
        self.assertEqual(plan.tasks[1].conflict_group, ["schema", "consumer"])
        restored = parse_structured_plan(PLAN_MARKER + " " + json.dumps(structured_plan_dict(plan)))
        self.assertEqual(restored.tasks[1].conflict_dependencies, ["schema"])

    def test_conflict_prerequisite_rejects_reverse_dependency(self) -> None:
        consumer = WorkTask("consumer", "Consumer", ["general"], expected_paths=["src/**"])
        foundation = WorkTask("schema", "Schema", ["general"], expected_paths=["src/models.py"], dependencies=["consumer"], is_prerequisite=True)
        with self.assertRaisesRegex(PlanningError, "conflict prerequisite contradicts"):
            validate_task_graph([foundation, consumer])

    def test_parses_and_round_trips_structured_technology_stack_options(self) -> None:
        option = {
            "option_id": "electron-typescript",
            "label": "Electron + TypeScript",
            "recommendation_rank": 1,
            "components": {
                "languages": ["TypeScript"],
                "runtimes": ["Node.js LTS"],
                "application_frameworks": ["Electron"],
                "ui_frameworks": ["React"],
                "persistence": ["로컬 JSON"],
                "package_and_build_tools": ["npm", "Vite"],
                "test_tools": ["Node test runner"],
                "style_and_analysis": ["TypeScript strict"],
                "packaging_and_deployment": ["Windows installer"],
            },
            "version_policy": ["Node.js LTS 범위에서 고정"],
            "requirement_fit": ["로컬 Windows 데스크톱 앱에 적합"],
            "tradeoffs": ["번들 크기가 커질 수 있음"],
            "unresolved_constraints": [],
            "required_external_dependencies": [],
        }
        payload = {
            "summary": "기술 구성 후보",
            "server_work": False,
            "source_paths": [],
            "instruction_paths": [],
            "tasks": [],
            "questions": [],
            "tech_stack_options": [option],
        }

        plan = parse_structured_plan(f"{PLAN_MARKER} {json.dumps(payload, ensure_ascii=False)}")
        restored = parse_structured_plan(f"{PLAN_MARKER} {json.dumps(structured_plan_dict(plan), ensure_ascii=False)}")

        self.assertEqual(restored.tech_stack_options[0].option_id, "electron-typescript")
        self.assertEqual(restored.tech_stack_options[0].components.ui_frameworks, ["React"])

    def test_greenfield_prompt_example_parses_as_technology_options_without_feature_tasks(self) -> None:
        prompt = planning_prompt(
            "기획 자료 없이 새 앱을 만듭니다.",
            planning_mode=PlanningMode.DIRECTED,
            planning_request="오프라인 메모 앱의 기술 구성을 추천해 주세요.",
            greenfield_bootstrap=True,
        )
        example = next(line for line in prompt.splitlines() if line.startswith(PLAN_MARKER))
        plan = parse_structured_plan(example)
        self.assertEqual(plan.tasks, [])
        self.assertEqual(len(plan.tech_stack_options), 1)
        self.assertTrue(plan.tech_stack_options[0].requirement_fit)
        self.assertTrue(plan.tech_stack_options[0].version_policy)
        self.assertTrue(plan.tech_stack_options[0].tradeoffs)
        self.assertEqual(plan.tech_stack_options[0].unresolved_constraints, [])
        self.assertIn("Do not repeat that choice as a clarification", prompt)
        self.assertIn("only remaining decision, return `questions: []`", prompt)
        self.assertIn("Still ask about genuinely", prompt)

    def test_technology_option_reasons_reject_invalid_types_and_empty_content(self) -> None:
        for field_name in ("version_policy", "requirement_fit", "tradeoffs"):
            for invalid in ("추천 이유", {"reason": "추천 이유"}, None, [], [""], [" "], [{"reason": "추천 이유"}], ["추천 이유", 1]):
                with self.subTest(field=field_name, invalid=invalid):
                    payload = json.loads(technology_stack_plan_example().removeprefix(PLAN_MARKER))
                    payload["tech_stack_options"][0][field_name] = invalid
                    with self.assertRaisesRegex(PlanningError, field_name):
                        parse_structured_plan(f"{PLAN_MARKER} {json.dumps(payload, ensure_ascii=False)}")

    def test_technology_stack_options_reject_noncontiguous_ranks(self) -> None:
        option = {
            "option_id": "python-desktop",
            "label": "Python desktop",
            "recommendation_rank": 2,
            "components": {"languages": ["Python"]},
            "version_policy": ["Python 3.11 이상"],
            "requirement_fit": ["로컬 실행"],
            "tradeoffs": ["패키징 검증 필요"],
        }
        payload = {
            "summary": "기술 구성 후보",
            "server_work": False,
            "tasks": [],
            "questions": [],
            "tech_stack_options": [option],
        }
        with self.assertRaisesRegex(PlanningError, "contiguous order"):
            parse_structured_plan(f"{PLAN_MARKER} {json.dumps(payload)}")

    def test_conflict_recalculation_drops_removed_paths_and_tasks(self) -> None:
        a = WorkTask("a", "A", ["general"], expected_paths=["src/**"])
        b = WorkTask("b", "B", ["general"], expected_paths=["src/**"])
        validate_task_graph([a, b])
        self.assertEqual(b.conflict_dependencies, ["a"])
        b.expected_paths = ["docs/**"]
        validate_task_graph([a, b])
        self.assertEqual(b.conflict_dependencies, [])
        self.assertEqual(a.conflict_group, [])
        b.expected_paths = ["src/**"]
        validate_task_graph([a, b])
        validate_task_graph([b])
        self.assertEqual(b.execution_dependencies, [])
        self.assertEqual(b.conflict_group, [])

    def test_conflict_prerequisite_flag_rejects_string_boolean(self) -> None:
        draft = structured_task("schema")
        draft["is_prerequisite"] = "false"
        with self.assertRaisesRegex(PlanningError, "is_prerequisite must be a boolean"):
            parse_structured_plan(PLAN_MARKER + " " + json.dumps({"summary": "plan", "server_work": False, "tasks": [draft], "questions": []}))

    def test_infers_korean_server_work(self) -> None:
        self.assertIn("backend", infer_capabilities("서버 인증 API 구현"))

    def test_infers_planning_and_architecture_work(self) -> None:
        capabilities = infer_capabilities("기획 명세와 아키텍처 설계 검토")
        self.assertIn("planning", capabilities)
        self.assertIn("architecture", capabilities)
        self.assertIn("review", capabilities)

    def test_parses_tagged_tasks_and_assigns_agents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spec = Path(directory) / "plan.md"
            spec.write_text("# 기능\n\n## 작업\n\n- [backend,api] 조회 API 구현\n- [frontend] 목록 화면 구현\n- 테스트 자동화\n", encoding="utf-8")

            plan = build_plan(spec, AGENTS)

        self.assertTrue(plan.server_work)
        self.assertEqual(len(plan.tasks), 3)
        self.assertEqual(plan.tasks[0].agent_id, "backend-ai")
        self.assertEqual(plan.tasks[1].agent_id, "frontend-ai")
        self.assertEqual(plan.tasks[2].agent_id, "qa-ai")
        self.assertTrue(plan.tasks[0].acceptance_criteria)
        self.assertEqual(plan.tasks[0].risk_level, RiskLevel.MEDIUM)
        self.assertEqual(plan.tasks[2].risk_level, RiskLevel.LOW)

    def test_requires_task_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spec = Path(directory) / "plan.md"
            spec.write_text("# 제목\n\n설명만 있음\n", encoding="utf-8")
            with self.assertRaises(PlanningError):
                build_plan(spec, AGENTS)

    def test_normalizes_database_tag(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            spec = Path(directory) / "plan.md"
            spec.write_text("## 작업\n\n- [db] 스키마 변경\n", encoding="utf-8")

            plan = build_plan(spec, AGENTS)

        self.assertTrue(plan.server_work)
        self.assertEqual(plan.tasks[0].capabilities, ["database"])
        self.assertEqual(plan.tasks[0].agent_id, "backend-ai")

    def test_routes_executor_and_reviewer_to_different_providers(self) -> None:
        agents = (
            AgentConfig("codex-ai", ("general", "backend"), (), 3, provider_id="codex"),
            AgentConfig("claude-ai", ("general", "security", "docs"), (), 3, provider_id="claude"),
        )
        routing = RoutingConfig(default_provider="codex", review_required=True, rules=(RoutingRule(("security", "docs"), "claude"),))
        with tempfile.TemporaryDirectory() as directory:
            spec = Path(directory) / "plan.md"
            spec.write_text("## 작업\n\n- [backend] API 구현\n- [security] 권한 검토\n", encoding="utf-8")

            plan = build_plan(spec, agents, routing)

        self.assertEqual(plan.tasks[0].provider_id, "codex")
        self.assertEqual(plan.tasks[0].reviewer_provider_id, "claude")
        self.assertEqual(plan.tasks[1].provider_id, "claude")
        self.assertEqual(plan.tasks[1].reviewer_provider_id, "codex")
        self.assertEqual(plan.tasks[0].review_status, ReviewStatus.PENDING)
        self.assertIn("공급자 2개", plan.summary)

    def test_reassigns_selected_task_agent_and_cross_provider_reviewer(self) -> None:
        agents = (
            AgentConfig("codex-ai", ("general", "backend", "review"), (), 3, provider_id="codex", model="codex-model"),
            AgentConfig("claude-ai", ("general", "backend", "review"), (), 3, provider_id="claude", model="sonnet"),
        )
        routing = RoutingConfig(default_provider="codex", review_required=True)
        with tempfile.TemporaryDirectory() as directory:
            spec = Path(directory) / "plan.md"
            spec.write_text("## 작업\n\n- [backend] API 구현\n", encoding="utf-8")
            plan = build_plan(spec, agents, routing)

        assign_task_agent_overrides(plan.tasks, agents, routing, {plan.tasks[0].id: "claude-ai"})

        task = plan.tasks[0]
        self.assertEqual(task.agent_id, "claude-ai")
        self.assertEqual(task.provider_id, "claude")
        self.assertEqual(task.model, "sonnet")
        self.assertEqual(task.reviewer_agent_id, "codex-ai")
        self.assertEqual(task.reviewer_provider_id, "codex")
        self.assertEqual(task.routing_reason, "user selected execution provider")

    def test_reassigns_unlocked_task_without_mutating_locked_task(self) -> None:
        agents = (
            AgentConfig("codex-ai", ("general", "backend", "review"), (), 3, provider_id="codex"),
            AgentConfig("claude-ai", ("general", "backend", "review"), (), 3, provider_id="claude", model="sonnet"),
        )
        routing = RoutingConfig(default_provider="codex", review_required=True)
        with tempfile.TemporaryDirectory() as directory:
            spec = Path(directory) / "plan.md"
            spec.write_text("## 작업\n\n- [backend] 완료 작업\n- [backend] 대기 작업\n", encoding="utf-8")
            plan = build_plan(spec, agents, routing)
        locked, pending = plan.tasks
        locked.review_status = ReviewStatus.APPROVED
        locked_profile = (locked.agent_id, locked.provider_id, locked.reviewer_agent_id, locked.reviewer_provider_id, locked.review_status)

        assign_task_agent_overrides(plan.tasks, agents, routing, {pending.id: "claude-ai"}, locked_task_ids={locked.id})

        self.assertEqual(
            (locked.agent_id, locked.provider_id, locked.reviewer_agent_id, locked.reviewer_provider_id, locked.review_status), locked_profile
        )
        self.assertEqual(pending.agent_id, "claude-ai")
        self.assertEqual(pending.reviewer_agent_id, "codex-ai")

    def test_routing_fails_when_provider_lacks_task_capability(self) -> None:
        agents = (
            AgentConfig("codex-ai", ("backend",), (), 2, provider_id="codex"),
            AgentConfig("claude-ai", ("docs",), (), 2, provider_id="claude"),
        )
        routing = RoutingConfig(default_provider="claude", balance_providers=False)
        with tempfile.TemporaryDirectory() as directory:
            spec = Path(directory) / "plan.md"
            spec.write_text("## 작업\n\n- [backend] API 구현\n", encoding="utf-8")

            with self.assertRaisesRegex(PlanningError, "no execution agent capability"):
                build_plan(spec, agents, routing)

    def test_parses_free_form_structured_plan_and_orders_dependencies(self) -> None:
        ui = structured_task("notification-ui", capabilities=["frontend"], dependencies=["notification-api"])
        ui["acceptance_criteria"] = ["알림을 읽음 처리할 수 있다"]
        api = structured_task("notification-api", capabilities=["backend", "api"])
        api["acceptance_criteria"] = ["사용자 알림만 조회한다"]
        payload = {
            "summary": "알림 기능",
            "server_work": True,
            "source_paths": ["features/notifications.md"],
            "instruction_paths": ["AGENTS.md", "Docs/CodeStyle.md"],
            "tasks": [ui, api],
            "questions": [],
        }
        output = f"planner notes\n{PLAN_MARKER} {json.dumps(payload, ensure_ascii=False)}\n"

        plan = parse_structured_plan(output)
        assign_plan_agents(plan, AGENTS)

        self.assertEqual(plan.summary, "알림 기능")
        self.assertTrue(plan.server_work)
        self.assertEqual(plan.source_paths, ["features/notifications.md"])
        self.assertEqual(plan.instruction_paths, ["AGENTS.md", "Docs/CodeStyle.md"])
        self.assertEqual(structured_plan_dict(plan)["source_paths"], ["features/notifications.md"])
        self.assertEqual(structured_plan_dict(plan)["instruction_paths"], ["AGENTS.md", "Docs/CodeStyle.md"])
        self.assertEqual([task.id for task in plan.tasks], ["notification-api", "notification-ui"])
        self.assertEqual(plan.tasks[0].agent_id, "backend-ai")
        self.assertEqual(plan.tasks[1].agent_id, "frontend-ai")
        self.assertEqual(plan.tasks[1].acceptance_criteria, ["알림을 읽음 처리할 수 있다"])
        self.assertEqual(plan.tasks[0].readiness, TaskReadiness.READY)
        self.assertEqual(plan.tasks[1].readiness, TaskReadiness.BLOCKED)
        self.assertEqual(plan.tasks[1].blocked_by, ["notification-api"])
        self.assertEqual(plan.tasks[0].risk_level, RiskLevel.MEDIUM)
        self.assertEqual(plan.tasks[0].verify_commands, [["python", "-m", "unittest", "tests.test_notification-api"]])

    def test_assigns_planning_recommended_execution_profile(self) -> None:
        task = structured_task("ranking-api", capabilities=["backend"])
        task.update(provider_id="codex", model="gpt-6.1-sol", reasoning_effort="high")
        payload = {"summary": "랭킹 API", "server_work": True, "tasks": [task], "questions": []}
        agents = (
            AgentConfig("backend-ai", ("backend",), ("codex", "exec", "-"), 2, provider_id="codex", model="gpt-6-luna"),
        )

        plan = parse_structured_plan(f"{PLAN_MARKER} {json.dumps(payload, ensure_ascii=False)}")
        assign_plan_agents(plan, agents)

        task_plan = plan.tasks[0]
        self.assertEqual(task_plan.agent_id, "backend-ai")
        self.assertEqual(task_plan.provider_id, "codex")
        self.assertEqual(task_plan.model, "gpt-6.1-sol")
        self.assertEqual(task_plan.reasoning_effort, "high")
        self.assertEqual(task_plan.profile_source, ProfileSource.MODE)
        serialized = structured_plan_dict(plan)["tasks"][0]
        self.assertEqual(serialized["model"], "gpt-6.1-sol")
        self.assertEqual(serialized["reasoning_effort"], "high")

    def test_manual_execution_profile_keeps_exact_agent_and_registered_model(self) -> None:
        codex = AgentConfig("codex", ("general",), (), 2, provider_id="codex", model="gpt-6.1-sol")
        selected = AgentConfig("selected", ("general",), ("opencode",), 1, provider_id="nvidia", manual_only=True)
        other = AgentConfig("z-other", ("general",), ("opencode",), 2, provider_id="nvidia", manual_only=True)
        task = WorkTask("manual", "사용자가 선택한 작업", ["general"], agent_id=selected.id, provider_id="nvidia",
                        model="vendor/registered-model", profile_source=ProfileSource.MANUAL, routing_reason="user selection",
                        routing_confidence=1.0)
        new_task = WorkTask("new", "새 자동 배정 작업", ["general"], provider_id="codex", model=codex.model)
        plan = Plan("수동 선택 보존", False, [task, new_task])
        assign_plan_agents(plan, (codex, selected, other), sequential=True, additional_models={"nvidia": (task.model,)})
        self.assertEqual((task.agent_id, task.model, task.profile_source, task.routing_reason),
                         (selected.id, "vendor/registered-model", ProfileSource.MANUAL, "user selection"))
        self.assertEqual(new_task.provider_id, "codex")
        self.assertEqual(new_task.profile_source, ProfileSource.MODE)
        assign_plan_agents(Plan("필수 리뷰", False, [task]), (codex, selected, other), RoutingConfig(review_required=True), sequential=True,
                           additional_models={"nvidia": (task.model,)})
        self.assertEqual(task.reviewer_provider_id, "codex")

    def test_manual_execution_profile_rejects_unavailable_or_invalid_selection_without_fallback(self) -> None:
        selected = AgentConfig("selected", ("backend",), ("opencode",), 1, provider_id="nvidia", manual_only=True)
        other = AgentConfig("other", ("general",), ("opencode",), 2, provider_id="nvidia", manual_only=True)
        cases = [({"agent_id": "missing"}, None, "선택한 실행 AI"),
                 ({}, {"other"}, "선택한 실행 AI"),
                 ({"capabilities": ["frontend"]}, None, "no execution agent capability"),
                 ({"model": "not-registered"}, None, "unsupported model"),
                 ({"reasoning_effort": "high"}, None, "unsupported reasoning")]
        for changes, available, error in cases:
            with self.subTest(changes=changes, available=available):
                values = {"agent_id": selected.id, "provider_id": "nvidia", "model": "registered",
                          "profile_source": ProfileSource.MANUAL, "capabilities": ["backend"], **changes}
                task = WorkTask("manual", "사용자 선택 검증", **values)
                with self.assertRaisesRegex(PlanningError, error):
                    assign_plan_agents(Plan("수동 선택 검증", False, [task]), (selected, other),
                                       execution_agent_ids=available, additional_models={"nvidia": ("registered",)})

    def test_manual_execution_profile_still_obeys_capacity(self) -> None:
        selected = AgentConfig("selected", ("general",), ("opencode",), 1, provider_id="nvidia", manual_only=True)
        tasks = [WorkTask(str(index), "사용자 선택", ["general"], agent_id=selected.id, provider_id="nvidia",
                          profile_source=ProfileSource.MANUAL) for index in range(2)]
        with self.assertRaisesRegex(PlanningError, "capacity"):
            assign_plan_agents(Plan("동시 실행 제한", False, tasks), (selected,))

    def test_ai_output_cannot_declare_a_trusted_manual_profile(self) -> None:
        draft = structured_task("new")
        draft.update(provider_id="codex", model="gpt-6.1-sol", agent_id="injected", profile_source="manual")
        plan = parse_structured_plan("AI_PLAN_RESULT: " + json.dumps({"summary": "새 작업", "server_work": False, "tasks": [draft], "questions": []}))
        codex = AgentConfig("codex", ("general",), (), 1, provider_id="codex", model="gpt-6.1-sol")
        assign_plan_agents(plan, (codex,))
        self.assertEqual(plan.tasks[0].agent_id, codex.id)
        self.assertEqual(plan.tasks[0].profile_source, ProfileSource.MODE)

    def test_manual_codex_model_and_reasoning_remain_exact_and_default_model_is_pinned(self) -> None:
        codex = AgentConfig("selected", ("general",), (), 1, provider_id="codex", model="gpt-6.1-sol")
        for model in ("", "gpt-6.1-sol", "gpt-6.1-terra"):
            with self.subTest(model=model):
                task = WorkTask("manual", "수동 Codex", ["general"], agent_id=codex.id, provider_id="codex", model=model,
                                reasoning_effort="high", profile_source=ProfileSource.MANUAL)
                assign_plan_agents(Plan("수동 Codex 보존", False, [task]), (codex,))
                self.assertEqual((task.model, task.reasoning_effort, task.profile_source), (model or "gpt-6.1-sol", "high", ProfileSource.MANUAL))

    def test_automatic_profile_cannot_reintroduce_a_configured_model_outside_the_allowlist(self) -> None:
        task = structured_task("ranking-api", capabilities=["backend"])
        task.update(provider_id="codex", model="gpt-6-astra", reasoning_effort="high")
        payload = {"summary": "랭킹 API", "server_work": True, "tasks": [task], "questions": []}
        agent = AgentConfig("backend-ai", ("backend",), (), 2, provider_id="codex", model="gpt-6-astra")
        plan = parse_structured_plan(f"{PLAN_MARKER} {json.dumps(payload)}")

        with self.assertRaisesRegex(PlanningError, "unsupported model"):
            assign_plan_agents(plan, (agent,))
        self.assertEqual(agent.model, "gpt-6-astra")

    def test_rejects_unsupported_recommended_execution_profile(self) -> None:
        task = structured_task("ranking-api", capabilities=["backend"])
        task.update(provider_id="codex", model="gpt-6.1-sol", reasoning_effort="ultra")
        payload = {"summary": "랭킹 API", "server_work": True, "tasks": [task], "questions": []}
        agents = (
            AgentConfig("backend-ai", ("backend",), ("codex", "exec", "-"), 2, provider_id="codex"),
        )
        plan = parse_structured_plan(f"{PLAN_MARKER} {json.dumps(payload)}")

        with self.assertRaisesRegex(PlanningError, "unsupported reasoning"):
            assign_plan_agents(plan, agents)

    def test_structured_plan_preserves_clarification_questions(self) -> None:
        output = f'{PLAN_MARKER} {{"summary":"알림 기능","server_work":true,"tasks":[],"questions":["실시간 알림인가요?"]}}'

        plan = parse_structured_plan(output)

        self.assertEqual(plan.tasks, [])
        self.assertEqual(plan.questions, ["실시간 알림인가요?"])
        with self.assertRaisesRegex(PlanningError, "clarification"):
            assign_plan_agents(plan, AGENTS)

    def test_structured_plan_can_require_korean_clarification_questions(self) -> None:
        output = (
            f'{PLAN_MARKER} {{"summary":"구현 대상 확인 필요",'
            '"server_work":false,"tasks":[],"questions":['
            '"Which feature should this implementation plan cover?"]}'
        )

        with self.assertRaisesRegex(PlanningError, "한국어"):
            parse_structured_plan(output, require_korean_questions=True)

        plan = parse_structured_plan(output)
        self.assertEqual(plan.questions, ["Which feature should this implementation plan cover?"])

    def test_structured_plan_rejects_unknown_and_cyclic_dependencies(self) -> None:
        unknown_payload = {
            "summary": "기능",
            "server_work": False,
            "tasks": [structured_task("ui", capabilities=["frontend"], dependencies=["api"])],
            "questions": [],
        }
        unknown = f"{PLAN_MARKER} {json.dumps(unknown_payload)}"
        with self.assertRaisesRegex(PlanningError, "unknown dependency"):
            parse_structured_plan(unknown)

        cyclic_payload = {
            "summary": "기능",
            "server_work": True,
            "tasks": [
                structured_task("api", capabilities=["backend"], dependencies=["ui"]),
                structured_task("ui", capabilities=["frontend"], dependencies=["api"]),
            ],
            "questions": [],
        }
        cyclic = f"{PLAN_MARKER} {json.dumps(cyclic_payload)}"
        with self.assertRaisesRegex(PlanningError, "cyclic task dependency"):
            parse_structured_plan(cyclic)

    def test_structured_plan_rejects_invalid_task_contract(self) -> None:
        for field_name, invalid_value, expected_error in (
            ("expected_paths", ["../outside"], "repository-relative"),
            ("forbidden_paths", ["C:/secret"], "repository-relative"),
            ("verify_commands", ["python -m unittest"], "argv array"),
            ("risk_level", "critical", "low, medium, or high"),
        ):
            task = structured_task("api", capabilities=["backend"])
            task[field_name] = invalid_value
            payload = {"summary": "기능", "server_work": True, "tasks": [task], "questions": []}
            output = f"{PLAN_MARKER} {json.dumps(payload)}"
            with self.subTest(field=field_name):
                with self.assertRaisesRegex(PlanningError, expected_error):
                    parse_structured_plan(output)

    def test_structured_plan_rejects_malformed_result(self) -> None:
        with self.assertRaisesRegex(PlanningError, "exactly one"):
            parse_structured_plan("no structured result")
        with self.assertRaisesRegex(PlanningError, "acceptance_criteria"):
            parse_structured_plan(
                f'{PLAN_MARKER} {{"summary":"기능","server_work":false,'
                '"tasks":[{"id":"docs","title":"문서","description":"수정",'
                '"capabilities":["docs"],"depends_on":[],'
                '"acceptance_criteria":[]}],"questions":[]}'
            )

    def test_reads_supported_utf8_document_formats(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "requirements.txt"
            document.write_text("자유 형식 요구사항", encoding="utf-8")
            self.assertEqual(read_planning_document(document), "자유 형식 요구사항")

            unsupported = root / "requirements.pdf"
            unsupported.write_bytes(b"pdf")
            with self.assertRaisesRegex(PlanningError, "unsupported"):
                read_planning_document(unsupported)

    def test_planning_directory_creates_small_exploration_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "nested"
            nested.mkdir()
            (root / "01-overview.md").write_text("요구사항", encoding="utf-8")
            (nested / "02-details.markdown").write_text("상세 설계", encoding="utf-8")
            (nested / "03-notes.txt").write_text("추가 메모", encoding="utf-8")
            (root / "empty.md").write_text("", encoding="utf-8")
            (root / "ignored.pdf").write_bytes(b"pdf")

            document = read_planning_document(root)

            self.assertIn(root.resolve().as_posix(), document)
            self.assertIn("Supported document count: 4", document)
            self.assertIn("Do not ingest the entire directory", document)
            self.assertNotIn("요구사항", document)
            self.assertNotIn("상세 설계", document)
            self.assertNotIn("추가 메모", document)
            self.assertNotIn("ignored.pdf", document)

    def test_rejects_directory_without_supported_documents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            unsupported = root / "unsupported"
            unsupported.mkdir()
            (unsupported / "requirements.pdf").write_bytes(b"pdf")
            with self.assertRaisesRegex(PlanningError, "no supported documents"):
                read_planning_document(unsupported)

    def test_reads_only_selected_planning_source_documents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = root / "nested"
            nested.mkdir()
            (root / "overview.md").write_text("요구사항", encoding="utf-8")
            (nested / "details.txt").write_text("상세 설계", encoding="utf-8")
            (root / "ignored.md").write_text("무관 문서", encoding="utf-8")

            documents = read_planning_source_documents(root, ["nested/details.txt", "overview.md"])

            self.assertEqual([document.relative_path for document in documents], ["nested/details.txt", "overview.md"])
            self.assertEqual([document.content for document in documents], ["상세 설계", "요구사항"])

    def test_rejects_invalid_selected_planning_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            empty = root / "empty"
            empty.mkdir()
            (empty / "requirements.md").write_text(" \n", encoding="utf-8")
            (root / "requirements.pdf").write_bytes(b"pdf")

            for source_paths, error in (
                (["../outside.md"], "repository-relative POSIX paths"),
                (["missing.md"], "document not found"),
                (["requirements.pdf"], "unsupported document"),
                (["empty/requirements.md"], "document is empty"),
            ):
                with self.subTest(source_paths=source_paths):
                    with self.assertRaisesRegex(PlanningError, error):
                        read_planning_source_documents(root, source_paths)

    def test_discovers_and_reads_repository_instruction_documents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = root / "Docs"
            docs.mkdir()
            (root / "AGENTS.md").write_text("루트 지침", encoding="utf-8")
            (root / "AGENTS.local.md").write_text("로컬 지침", encoding="utf-8")
            (docs / "CodeStyle.md").write_text("코드 규칙", encoding="utf-8")

            discovered = discover_repository_instruction_documents(root)
            routed = read_repository_instruction_documents(root, ["AGENTS.md", "Docs/CodeStyle.md"])

            self.assertEqual([document.relative_path for document in discovered], ["AGENTS.md", "AGENTS.local.md"])
            self.assertEqual([document.content for document in discovered], ["루트 지침", "로컬 지침"])
            self.assertEqual([document.relative_path for document in routed], ["AGENTS.md", "Docs/CodeStyle.md"])

    def test_rejects_invalid_repository_instruction_documents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            empty = root / "empty.md"
            empty.write_text(" \n", encoding="utf-8")
            (root / "rules.pdf").write_bytes(b"pdf")

            for instruction_paths, error in (
                (["../outside.md"], "repository-relative POSIX paths"),
                (["missing.md"], "document not found"),
                (["rules.pdf"], "unsupported document"),
                (["empty.md"], "document is empty"),
            ):
                with self.subTest(instruction_paths=instruction_paths):
                    with self.assertRaisesRegex(PlanningError, error):
                        read_repository_instruction_documents(root, instruction_paths)

    def test_prompt_embeds_active_repository_instructions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agents = root / "AGENTS.md"
            agents.write_text("작업 전 Docs/Workflow.md를 읽는다.", encoding="utf-8")
            documents = discover_repository_instruction_documents(root)

            prompt = planning_prompt("single file plan", repository_root=root.resolve().as_posix(), repository_instruction_documents=documents)

            self.assertIn("작업 전 Docs/Workflow.md를 읽는다.", prompt)
            self.assertIn("application\n  order: `AGENTS.md`", prompt)
            self.assertIn("`instruction_paths`", prompt)
            self.assertIn("nested `AGENTS.md`", prompt)

    def test_prompt_lists_user_facing_execution_profiles(self) -> None:
        agents = (
            AgentConfig("backend-ai", ("backend", "general"), ("codex", "exec", "-"), 2, provider_id="codex", model="gpt-6.1-sol"),
        )

        prompt = planning_prompt("single file plan", execution_agents=agents)

        self.assertIn("## Execution profile catalog", prompt)
        self.assertIn("Provider `codex`", prompt)
        self.assertIn("`gpt-6.1-sol`", prompt)
        self.assertIn("`gpt-6-luna`", prompt)
        terra = next(line for line in prompt.splitlines() if "`gpt-6.1-terra`" in line)
        self.assertIn("`ultra`", terra)
        sol = next(line for line in prompt.splitlines() if "`gpt-6.1-sol`" in line and "reasoning" in line)
        self.assertIn("`gpt-6-luna`", sol)
        self.assertNotIn("`ultra`", sol)
        self.assertNotIn("gpt-5.6", prompt)
        self.assertIn("total Task capacity 2", prompt)
        self.assertNotIn("backend-ai", prompt)
        self.assertIn("do not select the strongest profile", prompt)
        self.assertIn("Use `medium` reasoning for a clearly scoped implementation", prompt)
        self.assertIn("Do not infer the\n  reasoning effort from `risk_level` alone", prompt)

    def test_prompt_embeds_fixed_code_style_snapshot_without_claiming_checks_passed(self) -> None:
        prompt = planning_prompt(
            "single file plan",
            code_style_context=(
                "Snapshot status: detected\n"
                "Rules:\n- Python: ruff (tool_config, pyproject.toml, precedence 20)\n"
                "Configured style checks (not proof of execution):\n"
                '- Python: ["python", "-m", "ruff", "check", "."]'
            ),
        )

        self.assertIn("## Fixed project code style snapshot", prompt)
        self.assertIn("pyproject.toml", prompt)
        self.assertIn("configured check is not\nproof that it ran or passed", prompt)
        self.assertIn("Do not invent commands for fallback standards", prompt)

    def test_prompt_keeps_worktree_lifecycle_out_of_task_graph(self) -> None:
        prompt = planning_prompt(
            "별도 worktree를 만들고 기능을 구현한다.",
            repository_root="C:/Repo",
            planning_mode=PlanningMode.DIRECTED,
            planning_request=("feature/example 브랜치와 C:/Repo-example worktree를 만든 뒤 기능을 구현해 주세요."),
        )

        self.assertIn("The orchestrator owns branch and worktree preparation", prompt)
        self.assertIn("Never create a Task whose only outcome is creating, switching", prompt)
        self.assertIn("Every executable Task must produce meaningful repository file changes", prompt)
        self.assertLess(prompt.index("The orchestrator owns branch and worktree preparation"), prompt.index("## Planning document"))

    def test_prompt_without_repository_instructions_uses_empty_list(self) -> None:
        prompt = planning_prompt("single file plan", repository_root="C:/Repo", repository_instruction_documents=[])

        self.assertIn("No active root `AGENTS.md`", prompt)
        self.assertIn("Return `instruction_paths` as an empty array", prompt)

    def test_prompt_treats_free_input_as_user_planning_messages(self) -> None:
        prompt = planning_prompt("single file plan", "### Conversation message 1 (User)\n\nAPI 검증 Task를 분리해 주세요.")

        self.assertIn("## Planning conversation context", prompt)
        self.assertIn("API 검증 Task를 분리해 주세요.", prompt)
        self.assertIn("request plan\nchanges", prompt)

    def test_directory_prompt_requires_targeted_source_exploration(self) -> None:
        prompt = planning_prompt("directory reference", source_root="C:/PlanningSnapshot")

        self.assertIn("orchestrator-generated source index", prompt)
        self.assertIn("not enumerate the directory again", prompt)
        self.assertIn("Repository instruction documents routed by", prompt)
        self.assertIn("Treat a directory input as backlog discovery", prompt)
        self.assertIn("Do not ask the user to specify a target feature or planning area", prompt)
        self.assertIn("Never return questions without a task draft", prompt)
        self.assertIn("`source_paths`", prompt)
        self.assertIn("Do not read the whole source tree", prompt)
        self.assertIn("`Get-Content -Encoding UTF8`", prompt)
        self.assertIn('"summary":"알림 기능 구현 계획"', prompt)
        self.assertIn("in natural Korean suitable for user display", prompt)
        self.assertIn("`questions`", prompt)
        self.assertIn("`acceptance_criteria`", prompt)
        self.assertIn("form multiple root tasks", prompt)
        self.assertIn("do not\n  invent a single baseline task", prompt)

    def test_directed_directory_prompt_limits_discovery_to_user_request(self) -> None:
        prompt = planning_prompt(
            "directory reference",
            source_root="C:/PlanningSnapshot",
            planning_mode=PlanningMode.DIRECTED,
            planning_request="작업 그룹 삭제 오류만 수정해 주세요.",
        )

        self.assertIn("## Planning scope: directed request", prompt)
        self.assertIn("작업 그룹 삭제 오류만 수정해 주세요.", prompt)
        self.assertIn("not as a\n  backlog to survey", prompt)
        self.assertIn("Derive narrow search patterns", prompt)
        self.assertIn("Do not discover, prioritize, or propose unrelated", prompt)
        self.assertNotIn("Treat a directory input as backlog discovery", prompt)

    def test_directed_prompt_without_source_limits_repository_inspection(self) -> None:
        prompt = planning_prompt(
            "no planning source", repository_root="C:/Repo", planning_mode=PlanningMode.DIRECTED, planning_request="README 표시 오류만 수정해 주세요."
        )

        self.assertIn("## Repository-directed exploration", prompt)
        self.assertIn("repository code and supporting files directly relevant", prompt)
        self.assertIn("Return `source_paths` as an empty array", prompt)
        self.assertNotIn("## Planning source exploration", prompt)

    def test_directed_prompt_requires_request(self) -> None:
        with self.assertRaisesRegex(PlanningError, "requires a specific user request"):
            planning_prompt("directory reference", source_root="C:/PlanningSnapshot", planning_mode=PlanningMode.DIRECTED)


if __name__ == "__main__":
    unittest.main()
