"""Planning output validation, profile preservation and cache identity."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable

from ..config import AgentConfig, RoutingConfig
from ..document_index import PlanningSourceIndex
from ..models import EffortMode, PlanningMode, ProfileSource, ResolvedEffortPolicy, RunState, WorkTask
from ..planner import read_planning_source_documents, read_repository_instruction_documents
from .assignment import assign_plan_agents
from .contracts import Plan
from .protocol import parse_structured_plan
from .validation import validate_plan_document_references, validate_planning_phase


def validated_planning_plan(
    output: str,
    *,
    repo: Path,
    agents: tuple[AgentConfig, ...],
    routing: RoutingConfig,
    additional_models: Callable[[], dict[str, tuple[str, ...]]],
    effort_mode: Callable[[], EffortMode | None],
    source_root: Path | None,
    source_index: PlanningSourceIndex | None,
    required_instruction_paths: set[str],
    execution_agents: tuple[AgentConfig, ...],
    planning_mode: PlanningMode,
    require_directory_task_draft: bool,
    previous_tasks: list[WorkTask] | None = None,
    sequential: bool = False,
    greenfield_bootstrap: bool = False,
    greenfield_initial: bool = False,
    greenfield_feature: bool = False,
) -> Plan:
    plan = parse_structured_plan(output, require_korean_questions=True)
    read_repository_instruction_documents(repo, plan.instruction_paths)
    validate_plan_document_references(
        plan, required_instruction_paths=frozenset(required_instruction_paths), has_source_root=source_root is not None,
        indexed_source_paths=frozenset(document.relative_path for document in source_index.documents)
        if source_root is not None and source_index is not None else frozenset(),
        planning_mode=planning_mode, require_directory_task_draft=require_directory_task_draft, greenfield_bootstrap=greenfield_bootstrap,
    )
    if source_root is not None:
        read_planning_source_documents(source_root, plan.source_paths)
    validate_planning_phase(
        plan, greenfield_bootstrap=greenfield_bootstrap, greenfield_initial=greenfield_initial, greenfield_feature=greenfield_feature,
    )
    if not plan.questions:
        manual_profiles = {task.id: task for task in previous_tasks or [] if task.profile_source == ProfileSource.MANUAL}
        for task in plan.tasks:
            previous = manual_profiles.get(task.id)
            if previous is not None:
                for field in (
                    "agent_id", "provider_id", "model", "reasoning_effort", "profile_source", "effort_baseline_reasoning",
                    "routing_reason", "routing_confidence",
                ):
                    setattr(task, field, getattr(previous, field))
        assign_plan_agents(
            plan,
            agents,
            routing,
            sequential=sequential,
            execution_agent_ids={execution_agent.id for execution_agent in execution_agents},
            additional_models=additional_models(),
            effort_mode=effort_mode(),
        )
    return plan


def planning_cache_key(
    state: RunState, agent: AgentConfig, prompt: str, *, sdk_profile: tuple[str, str] | None,
    policy: ResolvedEffortPolicy | None, review_command: Callable[[], tuple[str, ...]],
) -> str:
    raw = json.dumps(
        {
            "schema": 4,
            "effort_policy": {
                "mode": policy.mode.value, "version": policy.policy_version,
                "profile": policy.planning_profile.to_dict() if policy.planning_profile is not None else None,
            } if policy is not None else None,
            "base_commit": state.base_commit,
            "agent_id": agent.id,
            "provider_id": agent.provider_id,
            "review_command": ([] if sdk_profile is not None else list(review_command())),
            "codex_sdk_profile": list(sdk_profile or ()),
            "model": state.planning_model,
            "reasoning_effort": state.planning_reasoning_effort,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
