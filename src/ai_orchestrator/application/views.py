from __future__ import annotations

from typing import Any

from ..config import supported_models, supported_reasoning_efforts
from ..document_index import PlanningSourceIndex
from ..models import RunState
from ..nvidia_agent import current_nvidia_model_keys
from ..run_queries import planned_user_checks


def planning_index_view(index: PlanningSourceIndex) -> dict[str, object]:
    return {
        "source_root": index.source_root,
        "generated_at": index.generated_at,
        "document_count": index.document_count,
        "reused_count": index.reused_count,
        "updated_count": index.updated_count,
        "added_count": index.added_count,
        "modified_count": index.modified_count,
        "deleted_count": index.deleted_count,
    }


def expanded_provider_choices(choices: list[object]) -> list[object]:
    expanded: list[dict[str, object]] = []
    for raw_choice in choices:
        provider_id = str(getattr(raw_choice, "provider_id"))
        configured_model = str(getattr(raw_choice, "model", ""))
        models = supported_models(provider_id, (configured_model,) if configured_model else ())
        if provider_id == "nvidia":
            models = tuple(dict.fromkeys((*models, *current_nvidia_model_keys())))
        # Do not offer automatic selection when it would restore an
        # excluded model.
        if not configured_model.strip() or configured_model.strip() in models:
            models = ("",) + models
        for model in dict.fromkeys(models):
            expanded.append(
                {
                    "provider_id": provider_id,
                    "agent_id": str(getattr(raw_choice, "agent_id")),
                    "model": model,
                    "configured_model": configured_model,
                    "reasoning_efforts": list(supported_reasoning_efforts(provider_id, model)),
                    "is_default": bool(getattr(raw_choice, "is_default", False)),
                    "max_tasks": int(getattr(raw_choice, "max_tasks", 1)),
                }
            )
    return expanded


def run_state_view(state: RunState) -> dict[str, Any]:
    result = state.to_dict()
    if state.user_check_plan:
        result["planned_user_checks"] = planned_user_checks(state, include_notes=True)
        result["user_check_blocked_task_ids"] = sorted(state.user_check_blocked_task_ids())
    return result
