from __future__ import annotations

import json
import re
from pathlib import PurePosixPath

from ..models import RiskLevel, TechStackComponents, TechStackOption, WorkTask
from .contracts import CAPABILITY_ALIASES, PLAN_MARKER, TASK_ID, Plan, PlanningError
from .validation import validate_prerequisite_flag, validate_task_graph


def parse_structured_plan(output: str, *, require_korean_questions: bool = False) -> Plan:
    pattern = rf"^{re.escape(PLAN_MARKER)}\s*(\{{.*\}})\s*$"
    matches = re.findall(pattern, output, flags=re.MULTILINE)
    if len(matches) != 1:
        raise PlanningError("planning output must contain exactly one AI_PLAN_RESULT line")
    try:
        raw = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        raise PlanningError(f"invalid planning JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise PlanningError("planning result must be a JSON object")

    summary = _required_string(raw.get("summary"), "summary")
    server_work = raw.get("server_work")
    if not isinstance(server_work, bool):
        raise PlanningError("server_work must be a boolean")
    questions = _string_list(raw.get("questions"), "questions", allow_empty=True)
    if require_korean_questions:
        english_questions = [question for question in questions if not re.search(r"[가-힣]", question)]
        if english_questions:
            raise PlanningError("Planning AI 질문은 사용자에게 표시할 자연스러운 한국어로 작성해야 합니다.")
    source_paths = validate_relative_paths(raw.get("source_paths", []), "source_paths", allow_empty=True)
    instruction_paths = validate_relative_paths(raw.get("instruction_paths", []), "instruction_paths", allow_empty=True)
    tech_stack_options = _tech_stack_options(raw.get("tech_stack_options", []))
    raw_tasks = raw.get("tasks")
    if not isinstance(raw_tasks, list):
        raise PlanningError("tasks must be an array")
    if not raw_tasks and not questions and not tech_stack_options:
        raise PlanningError("planning result requires tasks, clarification questions, or technology stack options")

    tasks: list[WorkTask] = []
    task_ids: set[str] = set()
    for index, item in enumerate(raw_tasks, start=1):
        if not isinstance(item, dict):
            raise PlanningError(f"task {index} must be an object")
        task_id = _required_string(item.get("id"), f"task {index} id")
        if not TASK_ID.fullmatch(task_id):
            raise PlanningError(f"invalid task id: {task_id}")
        if task_id in task_ids:
            raise PlanningError(f"duplicate task id: {task_id}")
        task_ids.add(task_id)
        capabilities = [
            CAPABILITY_ALIASES.get(value.casefold(), value.casefold())
            for value in _string_list(item.get("capabilities"), f"task {task_id} capabilities", allow_empty=False)
        ]
        tasks.append(
            WorkTask(
                id=task_id,
                title=_required_string(item.get("title"), f"task {task_id} title"),
                description=_required_string(item.get("description"), f"task {task_id} description"),
                capabilities=list(dict.fromkeys(capabilities)),
                dependencies=_string_list(item.get("depends_on"), f"task {task_id} depends_on", allow_empty=True),
                is_prerequisite=validate_prerequisite_flag(item.get("is_prerequisite", False)),
                acceptance_criteria=_string_list(item.get("acceptance_criteria"), f"task {task_id} acceptance_criteria", allow_empty=False),
                expected_paths=validate_relative_paths(item.get("expected_paths"), f"task {task_id} expected_paths", allow_empty=False),
                forbidden_paths=validate_relative_paths(item.get("forbidden_paths"), f"task {task_id} forbidden_paths", allow_empty=True),
                verify_commands=_command_list(item.get("verify_commands"), f"task {task_id} verify_commands"),
                risk_level=_risk_level(item.get("risk_level"), f"task {task_id} risk_level"),
                provider_id=_optional_string(item.get("provider_id"), f"task {task_id} provider_id").casefold(),
                model=_optional_string(item.get("model"), f"task {task_id} model"),
                reasoning_effort=_optional_string(item.get("reasoning_effort"), f"task {task_id} reasoning_effort").casefold(),
            )
        )
        overlap = set(tasks[-1].expected_paths) & set(tasks[-1].forbidden_paths)
        if overlap:
            paths = ", ".join(sorted(overlap))
            raise PlanningError(f"task {task_id} paths cannot be both expected and forbidden: {paths}")
    return Plan(
        summary=summary,
        server_work=server_work,
        tasks=validate_task_graph(tasks) if tasks else [],
        questions=questions,
        source_paths=source_paths,
        instruction_paths=instruction_paths,
        tech_stack_options=tech_stack_options,
    )


def structured_plan_dict(plan: Plan) -> dict[str, object]:
    return {
        "summary": plan.summary,
        "server_work": plan.server_work,
        "source_paths": plan.source_paths,
        "instruction_paths": plan.instruction_paths,
        "tasks": [
            {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "capabilities": task.capabilities,
                "depends_on": task.dependencies,
                "is_prerequisite": task.is_prerequisite,
                "conflict_dependencies": task.conflict_dependencies,
                "conflict_group": task.conflict_group,
                "acceptance_criteria": task.acceptance_criteria,
                "expected_paths": task.expected_paths,
                "forbidden_paths": task.forbidden_paths,
                "verify_commands": task.verify_commands,
                "risk_level": task.risk_level,
                "readiness": task.readiness,
                "blocked_by": task.blocked_by,
                "agent_id": task.agent_id,
                "provider_id": task.provider_id,
                "model": task.model,
                "reasoning_effort": task.reasoning_effort,
                "profile_source": task.profile_source,
                "effort_baseline_reasoning": task.effort_baseline_reasoning,
                "reviewer_agent_id": task.reviewer_agent_id,
                "reviewer_provider_id": task.reviewer_provider_id,
                "review_policy_added": task.review_policy_added,
            }
            for task in plan.tasks
        ],
        "questions": plan.questions,
        "tech_stack_options": [
            {
                "option_id": option.option_id,
                "label": option.label,
                "recommendation_rank": option.recommendation_rank,
                "components": {
                    "languages": option.components.languages,
                    "runtimes": option.components.runtimes,
                    "application_frameworks": option.components.application_frameworks,
                    "ui_frameworks": option.components.ui_frameworks,
                    "persistence": option.components.persistence,
                    "package_and_build_tools": option.components.package_and_build_tools,
                    "test_tools": option.components.test_tools,
                    "style_and_analysis": option.components.style_and_analysis,
                    "packaging_and_deployment": option.components.packaging_and_deployment,
                },
                "version_policy": option.version_policy,
                "requirement_fit": option.requirement_fit,
                "tradeoffs": option.tradeoffs,
                "unresolved_constraints": option.unresolved_constraints,
                "required_external_dependencies": option.required_external_dependencies,
            }
            for option in plan.tech_stack_options
        ],
    }


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PlanningError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_string(value: object, field_name: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise PlanningError(f"{field_name} must be a string")
    return value.strip()


def _tech_stack_options(value: object) -> list[TechStackOption]:
    if not isinstance(value, list):
        raise PlanningError("tech_stack_options must be an array")
    if len(value) > 3:
        raise PlanningError("tech_stack_options must contain at most three options")
    options: list[TechStackOption] = []
    option_ids: set[str] = set()
    ranks: set[int] = set()
    component_fields = (
        "languages",
        "runtimes",
        "application_frameworks",
        "ui_frameworks",
        "persistence",
        "package_and_build_tools",
        "test_tools",
        "style_and_analysis",
        "packaging_and_deployment",
    )
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            raise PlanningError(f"tech_stack_options item {index} must be an object")
        option_id = _required_string(item.get("option_id"), f"tech_stack_options item {index} option_id")
        if not TASK_ID.fullmatch(option_id):
            raise PlanningError(f"invalid technology stack option id: {option_id}")
        if option_id in option_ids:
            raise PlanningError(f"duplicate technology stack option id: {option_id}")
        option_ids.add(option_id)
        rank = item.get("recommendation_rank")
        if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
            raise PlanningError(f"tech_stack_options item {index} recommendation_rank must be a positive integer")
        if rank in ranks:
            raise PlanningError(f"duplicate technology stack recommendation rank: {rank}")
        ranks.add(rank)
        raw_components = item.get("components")
        if not isinstance(raw_components, dict):
            raise PlanningError(f"tech_stack_options item {index} components must be an object")
        components = {
            field_name: _string_list(raw_components.get(field_name, []), f"tech_stack_options item {index} components.{field_name}", allow_empty=True)
            for field_name in component_fields
        }
        if not any(components[field_name] for field_name in ("languages", "runtimes", "application_frameworks", "ui_frameworks")):
            raise PlanningError(f"tech_stack_options item {index} must identify a language, runtime, or framework")
        options.append(
            TechStackOption(
                option_id=option_id,
                label=_required_string(item.get("label"), f"tech_stack_options item {index} label"),
                recommendation_rank=rank,
                components=TechStackComponents(**components),
                version_policy=_string_list(
                    item.get("version_policy"), f"tech_stack_options item {index} version_policy", allow_empty=False
                ),
                requirement_fit=_string_list(
                    item.get("requirement_fit"), f"tech_stack_options item {index} requirement_fit", allow_empty=False
                ),
                tradeoffs=_string_list(item.get("tradeoffs"), f"tech_stack_options item {index} tradeoffs", allow_empty=False),
                unresolved_constraints=_string_list(
                    item.get("unresolved_constraints", []),
                    f"tech_stack_options item {index} unresolved_constraints",
                    allow_empty=True,
                ),
                required_external_dependencies=_string_list(
                    item.get("required_external_dependencies", []),
                    f"tech_stack_options item {index} required_external_dependencies",
                    allow_empty=True,
                ),
            )
        )
    if ranks and ranks != set(range(1, len(options) + 1)):
        raise PlanningError("tech_stack_options recommendation_rank must form a contiguous order starting at 1")
    return sorted(options, key=lambda option: option.recommendation_rank)


def _string_list(value: object, field_name: str, *, allow_empty: bool) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise PlanningError(f"{field_name} must be an array of non-empty strings")
    result = list(dict.fromkeys(item.strip() for item in value))
    if not allow_empty and not result:
        raise PlanningError(f"{field_name} must not be empty")
    return result


def validate_relative_paths(value: object, field_name: str, *, allow_empty: bool) -> list[str]:
    paths = _string_list(value, field_name, allow_empty=allow_empty)
    for path in paths:
        parsed = PurePosixPath(path)
        if (
            "\\" in path
            or parsed.is_absolute()
            or path == "."
            or ".." in parsed.parts
            or re.match(r"^[a-zA-Z]:", path)
        ):
            raise PlanningError(f"{field_name} must contain repository-relative POSIX paths: {path}")
    return paths


def _command_list(value: object, field_name: str) -> list[list[str]]:
    if not isinstance(value, list) or not value:
        raise PlanningError(f"{field_name} must be a non-empty array of commands")
    commands: list[list[str]] = []
    for index, command in enumerate(value, start=1):
        if (
            not isinstance(command, list)
            or not command
            or not all(isinstance(argument, str) and argument.strip() for argument in command)
        ):
            raise PlanningError(f"{field_name} command {index} must be a non-empty argv array")
        commands.append([argument.strip() for argument in command])
    return commands


def _risk_level(value: object, field_name: str) -> RiskLevel:
    if not isinstance(value, str):
        raise PlanningError(f"{field_name} must be low, medium, or high")
    try:
        return RiskLevel(value.strip().casefold())
    except ValueError as exc:
        raise PlanningError(f"{field_name} must be low, medium, or high") from exc
