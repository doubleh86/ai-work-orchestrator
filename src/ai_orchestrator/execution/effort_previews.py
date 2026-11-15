"""Effort preview validation shared by queries and plan application."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..effort_policy import EffortModePreview
from ..errors import PipelineError
from ..models import EffortMode, EffortPolicyRevisionError, RunState
from .effort_queries import EffortPolicyLoader
from .effort_preview import EffortPreviewBuilder


@dataclass(frozen=True, slots=True)
class EffortPreviewQueries:
    load_state: Callable[[str], RunState]
    load_policy: EffortPolicyLoader
    preview_builder: Callable[[], EffortPreviewBuilder]

    def preview_effort_mode(self, run_id: str, mode: EffortMode | str, *, expected_revision: int) -> EffortModePreview:
        try:
            selected = EffortMode(mode)
        except ValueError as exc:
            raise PipelineError(f"unsupported effort mode: {mode}") from exc
        policy = self.load_policy(run_id)
        if type(expected_revision) is not int or expected_revision < 0:
            raise PipelineError("expected effort policy revision must be a non-negative integer")
        if policy.revision != expected_revision:
            raise EffortPolicyRevisionError(
                f"effort policy revision mismatch: expected {expected_revision}, actual {policy.revision}"
            )
        state = self.load_state(run_id)
        return self.build_preview(state, selected, policy.revision)

    def build_preview(
        self, state: RunState, selected: EffortMode, policy_revision: int, *, preserve_execution_profiles: bool = False,
        runtime_excluded_task_ids: frozenset[str] = frozenset(),
    ) -> EffortModePreview:
        return self.preview_builder().build(
            state, selected, policy_revision, preserve_execution_profiles=preserve_execution_profiles,
            runtime_excluded_task_ids=runtime_excluded_task_ids,
        )
