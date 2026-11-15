"""Prepare the initial Run before either direct or linked planning."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence
from ..document_index import PlanningSourceIndex
from ..errors import PipelineError
from ..models import EffortMode, PlanningMode, ProfileSource, RunState, RunStep, Stage
from .initialization import PlanningRepositoryContext
from .preparation import PlanningPreparation, write_prepared_planning_sources


@dataclass
class PlanningIntake:
    state_path: Callable[[str], Path]
    run_directory: Callable[[str], Path]
    save_state: Callable[[RunState], None]
    initialize_effort: Callable[..., object]
    preparation: Callable[[], PlanningPreparation]
    repository_context: Callable[[], PlanningRepositoryContext]

    def prepare(
        self,
        spec_path: str | Path,
        *,
        planning_agent_id: str = "",
        planning_model: str = "",
        planning_reasoning_effort: str = "",
        planning_mode: PlanningMode | str = PlanningMode.AUTO,
        planning_request: str = "",
        prepared_source_index: PlanningSourceIndex | None = None,
        repository_intent: str | None = None,
        revision_source_run_id: str = "",
        revision_request_id: str = "",
        revision_request_text: str = "",
        revision_source_task_ids: Sequence[str] = (),
        revision_source_paths: Sequence[str] = (),
        effort_mode: EffortMode | str = EffortMode.BALANCED,
        planning_profile_source: ProfileSource | str | None = None,
        reserved_run_id: str = "",
    ) -> RunState:
        if reserved_run_id and (not re.fullmatch(r"mcp-[a-f0-9]{32}", reserved_run_id) or self.state_path(reserved_run_id).exists()):
            raise PipelineError("이미 사용 중이거나 올바르지 않은 기획 작업 ID입니다.")
        preparation = self.preparation()
        prepared = preparation.prepare(
            spec_path, planning_agent_id=planning_agent_id, planning_model=planning_model, planning_reasoning_effort=planning_reasoning_effort,
            planning_mode=planning_mode, planning_request=planning_request, prepared_source_index=prepared_source_index,
            repository_intent=repository_intent, revision_source_run_id=revision_source_run_id, revision_request_id=revision_request_id,
            revision_request_text=revision_request_text, revision_source_task_ids=revision_source_task_ids,
            revision_source_paths=revision_source_paths, effort_mode=effort_mode, planning_profile_source=planning_profile_source,
            reserved_run_id=reserved_run_id,
        )
        state = prepared.state
        repository_intent, explicit_repository_intent = prepared.repository_intent, prepared.explicit_repository_intent
        self.repository_context().apply(
            state, repository_intent=repository_intent, explicit_repository_intent=explicit_repository_intent,
        )
        state.begin_step(RunStep.PLANNING)
        write_prepared_planning_sources(prepared, run_directory=self.run_directory)
        state.add_event("stage", "planning document received")
        state.add_event("planning", f"planning scope selected: {state.planning_mode.value}")
        self.initialize_effort(state, prepared.selected_effort.value)

        state.transition(Stage.REVIEWED, "planning document reviewed")
        self.save_state(state)
        return state

    def prepare_revision_run(
        self, context: str, run_id: str, request_id: str, text: str, task_ids: list[str], paths: list[str],
    ) -> RunState:
        return self.prepare(
            "", planning_mode=PlanningMode.DIRECTED, planning_request=context,
            revision_source_run_id=run_id, revision_request_id=request_id,
            revision_request_text=text, revision_source_task_ids=task_ids, revision_source_paths=paths,
        )
