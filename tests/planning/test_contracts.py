import os
from dataclasses import replace
from pathlib import Path
import subprocess
import sys

import pytest

from ai_orchestrator import planner, planning
from ai_orchestrator.models import PlanningMode, UserCheck, WorkTask


def test_public_planning_contracts_preserve_legacy_types_and_response_errors():
    for name in ("Plan", "PlanningSourceDocument", "PlanningError"):
        assert getattr(planning, name) is getattr(planner, name)
    plan = planning.parse_structured_plan(planning.technology_stack_plan_example())
    assert isinstance(plan, planner.Plan) and plan.tech_stack_options and not plan.tasks
    with pytest.raises(planner.PlanningError, match="exactly one"):
        planning.parse_structured_plan("invalid response")


def test_planning_package_import_does_not_load_io_or_workflow_owners(tmp_path: Path):
    source = Path(__file__).resolve().parents[2] / "src"
    environment = {**os.environ, "PYTHONPATH": str(source)}
    subprocess.run([
        sys.executable, "-c", "import sys; import ai_orchestrator.planning; "
        "assert not {'ai_orchestrator.planner','ai_orchestrator.pipeline','ai_orchestrator.store',"
        "'ai_orchestrator.git','ai_orchestrator.registry','ai_orchestrator.document_index'} & set(sys.modules)",
    ], cwd=tmp_path, env=environment, check=True, timeout=15, capture_output=True)


@pytest.mark.parametrize(("error", "has_retry_context", "continuation", "has_base", "has_materialization", "has_catalog"), [
    ("", False, False, True, False, False),
    ("", False, True, False, True, True),
    ("schema rejected", False, True, True, False, False),
    ("schema rejected", True, False, False, False, True),
])
def test_attempt_prompt_preserves_retry_context_follow_up_tasks_and_catalog_order(
    error, has_retry_context, continuation, has_base, has_materialization, has_catalog,
):
    tasks = '[{"id":"kept","status":"completed"}]'
    prompt = planning.render_planning_attempt_prompt(
        "BASE-CONTRACT", last_error=error, provider_retry_has_context=has_retry_context, continuation=continuation,
        materialization_prompt="MATERIALIZE", greenfield_bootstrap=bool(error), follow_up_tasks=tasks, execution_catalog="CATALOG",
    )
    assert ("BASE-CONTRACT" in prompt) == has_base and ("MATERIALIZE" in prompt) == has_materialization
    assert ("CATALOG" in prompt) == has_catalog
    assert "Preserve completed/waiting Tasks" in prompt and tasks in prompt
    assert ("Technology option schema correction" in prompt) == bool(error)
    if has_catalog:
        assert prompt.index(tasks) < prompt.index("CATALOG")
    if error:
        assert error in prompt and planning.technology_stack_plan_example() in prompt


def test_continuation_flag_keeps_empty_materialization_instead_of_restoring_the_base_prompt():
    assert planning.render_planning_attempt_prompt(
        "BASE-CONTRACT", last_error="", provider_retry_has_context=False, continuation=True,
        materialization_prompt="", greenfield_bootstrap=False, follow_up_tasks=None, execution_catalog="CATALOG",
    ) == "CATALOG"


@pytest.mark.parametrize("continuation", [False, True])
def test_planning_chat_replays_saved_context_only_for_a_new_conversation(continuation):
    prompt = planning.render_planning_chat_prompt(
        "현재 계획 확인", continuation=continuation, document="SAVED-DOCUMENT", conversation_context="SAVED-CONTEXT",
        repository_root="C:/example", catalog="CATALOG",
    )
    assert "현재 계획 확인" in prompt and "CATALOG" in prompt and "conversation turn only" in prompt
    assert ("SAVED-DOCUMENT" in prompt) == (not continuation) and ("SAVED-CONTEXT" in prompt) == (not continuation)


@pytest.mark.parametrize(("after", "blocks", "error"), [
    ("prepare", ("later",), None), ("later", ("prepare",), "순환 의존성"), ("absent", ("later",), "등록되지 않은 작업"),
])
def test_user_check_validation_keeps_task_and_manual_check_dependencies(after, blocks, error):
    tasks = [WorkTask("prepare", "준비", ["general"]), WorkTask("later", "구현", ["general"], dependencies=["prepare"])]
    checks = [UserCheck("manual", "직접 확인", "확인 절차", ("완료 기준",), after, blocks)]
    if error:
        with pytest.raises(planner.PlanningError, match=error):
            planning.validate_user_checks(tasks, checks)
    else:
        planning.validate_user_checks(tasks, checks)


@pytest.mark.parametrize(("kind", "bootstrap", "initial", "feature", "error"), [
    ("options", True, True, False, None), ("options", False, False, False, "only valid for new project"),
    ("bootstrap", True, False, False, None), ("bootstrap", True, True, False, "technology choices before"),
    ("bootstrap", False, False, True, "feature Planning cannot"),
    ("mixed_options", True, False, False, "cannot return technology stack options"),
    ("mixed_questions", True, False, False, "cannot mix unresolved questions"),
    ("dependent_bootstrap", True, False, False, "cannot depend on feature Tasks"),
])
def test_planning_phase_preserves_technology_choice_bootstrap_and_feature_boundaries(kind, bootstrap, initial, feature, error):
    options = planning.parse_structured_plan(planning.technology_stack_plan_example())
    task = WorkTask("project-bootstrap", "초기 구성", ["general"], dependencies=["feature"] if kind == "dependent_bootstrap" else [])
    plan = options if kind == "options" else planning.Plan(
        "bootstrap", False, [task], questions=["확인할까요?"] if kind == "mixed_questions" else [],
        tech_stack_options=options.tech_stack_options if kind == "mixed_options" else [],
    )
    params = dict(greenfield_bootstrap=bootstrap, greenfield_initial=initial, greenfield_feature=feature)
    if error:
        with pytest.raises(planner.PlanningError, match=error):
            planning.validate_planning_phase(plan, **params)
    else:
        planning.validate_planning_phase(plan, **params)


def test_plan_document_reference_validation_keeps_instruction_and_source_error_priority():
    plan = planning.Plan("질문", False, [], questions=["기준을 확인할까요?"], source_paths=["outside.md"])
    params = dict(required_instruction_paths=frozenset({"AGENTS.md"}), has_source_root=True, indexed_source_paths=frozenset({"known.md"}),
                  planning_mode=PlanningMode.DIRECTED, require_directory_task_draft=False, greenfield_bootstrap=False)
    with pytest.raises(planner.PlanningError, match="omitted active repository instructions"):
        planning.validate_plan_document_references(plan, **params)
    params["required_instruction_paths"] = frozenset()
    with pytest.raises(planner.PlanningError, match="outside the planning source index"):
        planning.validate_plan_document_references(plan, **params)
    params["require_directory_task_draft"] = True
    with pytest.raises(planner.PlanningError, match="best-effort tasks"):
        planning.validate_plan_document_references(replace(plan, source_paths=[]), **params)
