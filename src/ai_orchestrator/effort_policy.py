from __future__ import annotations

from dataclasses import dataclass

from .config import supported_reasoning_efforts
from .models import EffortMode, ProfileSource, WorkTask
from .model_selection import automatic_claude_profile, automatic_codex_profile, select_claude_model, select_codex_model


class EffortPolicyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ReasoningDecision:
    mode: EffortMode
    provider_id: str
    model: str
    reasoning_effort: str
    profile_source: ProfileSource
    unsupported_effects: tuple[str, ...] = ()
    selection_reason: str = ""


@dataclass(frozen=True, slots=True)
class ReviewDecision:
    required: bool
    optional: bool
    policy_added: bool
    requires_reviewer: bool
    reason: str
    unsupported_effects: tuple[str, ...] = ()
    policy_removed: bool = False


@dataclass(frozen=True, slots=True)
class EffortTaskPreview:
    task_id: str
    current_reasoning_effort: str
    reasoning: ReasoningDecision
    review: ReviewDecision
    current_reviewer_agent_id: str


@dataclass(frozen=True, slots=True)
class EffortModePreview:
    mode: EffortMode
    policy_revision: int
    plan_revision: int
    planning_reasoning: ReasoningDecision | None
    tasks: tuple[EffortTaskPreview, ...]
    manual_exception_ids: tuple[str, ...]
    unsupported_effects: tuple[str, ...]
    requires_plan_review: bool


_REASONING_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")


def _mode(value: EffortMode | str) -> EffortMode:
    try:
        return EffortMode(value)
    except ValueError as exc:
        raise EffortPolicyError(f"unsupported effort mode: {value}") from exc


def _source(value: ProfileSource | str) -> ProfileSource:
    try:
        return ProfileSource(value)
    except ValueError as exc:
        raise EffortPolicyError(f"unsupported profile source: {value}") from exc


def resolve_reasoning_profile(
    *,
    mode: EffortMode | str,
    provider_id: str,
    model: str,
    reasoning_effort: str,
    profile_source: ProfileSource | str,
    baseline_reasoning_effort: str | None = None,
    purpose: str = "",
    task: WorkTask | None = None,
) -> ReasoningDecision:
    selected_mode = _mode(mode)
    selected_source = _source(profile_source)
    provider = provider_id.strip().casefold()
    selected_model = model.strip()
    effort = reasoning_effort.strip().casefold()
    if selected_source == ProfileSource.MODE:
        if baseline_reasoning_effort is None:
            return ReasoningDecision(
                selected_mode, provider, selected_model, effort, selected_source,
                ("mode_profile_baseline_missing",),
            )
        if not isinstance(baseline_reasoning_effort, str):
            raise EffortPolicyError("mode profile baseline reasoning must be a string")
        effort = baseline_reasoning_effort.strip().casefold()
        selected_source = ProfileSource.ROUTING
    if not provider:
        raise EffortPolicyError("effort policy requires a selected provider")
    automatic = (provider == "codex" and automatic_codex_profile(selected_source, selected_model)
                 or provider == "claude" and automatic_claude_profile(selected_source, selected_model))
    if purpose and automatic:
        if provider == "claude" and effort and effort not in supported_reasoning_efforts(provider, selected_model):
            raise EffortPolicyError(f"unsupported reasoning effort for {provider}/{selected_model}: {effort}")
        select_model = select_codex_model if provider == "codex" else select_claude_model
        decision = select_model(selected_mode, purpose=purpose, task=task, reasoning_effort=effort)
        # A provider's automatic model option may accompany explicit reasoning.
        manual_effort = selected_source == ProfileSource.MANUAL and effort
        if manual_effort and effort not in supported_reasoning_efforts(provider, decision.model):
            raise EffortPolicyError(f"unsupported reasoning effort for {provider}/{decision.model}: {effort}")
        return ReasoningDecision(
            selected_mode, provider, decision.model, effort if manual_effort else decision.reasoning_effort,
            ProfileSource.MANUAL if manual_effort else ProfileSource.MODE, selection_reason=decision.reason,
        )
    supported = supported_reasoning_efforts(provider, selected_model)
    if effort and selected_source != ProfileSource.LEGACY and effort not in supported:
        raise EffortPolicyError(f"unsupported reasoning effort for {provider}/{selected_model or 'default model'}: {effort}")

    if selected_mode == EffortMode.BALANCED or selected_source in {ProfileSource.MANUAL, ProfileSource.LEGACY}:
        return ReasoningDecision(selected_mode, provider, selected_model, effort, selected_source)

    if selected_mode == EffortMode.ECONOMY:
        target = "low"
    elif effort and _REASONING_ORDER.index(effort) >= _REASONING_ORDER.index("high"):
        return ReasoningDecision(selected_mode, provider, selected_model, effort, selected_source)
    else:
        target = "high"

    if target not in supported:
        return ReasoningDecision(
            selected_mode,
            provider,
            selected_model,
            effort,
            selected_source,
            ("reasoning_auto_adjustment_unsupported",),
        )
    if target == effort:
        return ReasoningDecision(selected_mode, provider, selected_model, effort, selected_source)
    return ReasoningDecision(selected_mode, provider, selected_model, target, ProfileSource.MODE)


def resolve_review_decision(
    *,
    mode: EffortMode | str,
    required: bool,
    explicitly_requested: bool,
    reviewer_agent_id: str,
    is_code_change: bool,
    is_automatic: bool,
    reviewer_available: bool,
) -> ReviewDecision:
    selected_mode = _mode(mode)
    existing_reviewer = bool(reviewer_agent_id.strip())
    policy_added = (
        selected_mode == EffortMode.FOCUSED
        and is_code_change
        and is_automatic
        and not required
        and not explicitly_requested
        and not existing_reviewer
    )
    optional = not required and (explicitly_requested or existing_reviewer or policy_added)
    requires_reviewer = (required or optional) and not existing_reviewer
    unsupported = ("reviewer_unavailable",) if requires_reviewer and not reviewer_available else ()
    if required:
        reason = "required_review"
    elif explicitly_requested:
        reason = "explicit_review"
    elif existing_reviewer:
        reason = "existing_review"
    elif policy_added:
        reason = "focused_code_change_review"
    else:
        reason = "not_requested"
    return ReviewDecision(required, optional, policy_added, requires_reviewer, reason, unsupported)
