"""Initial planning inputs, source preparation and immutable snapshots."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol, Sequence

from ..config import AgentConfig
from ..document_index import PlanningSourceIndex, render_planning_source_index
from ..errors import PipelineError
from ..models import EffortMode, ExecutionWorkspaceMode, PlanningMessage, PlanningMessageRole, PlanningMode, ProfileSource
from ..models import RunState, Stage, WorkspaceLocation
from ..planner import read_planning_document
from ..windows_paths import filesystem_path

DIRECTED_PLANNING_WITHOUT_SOURCE_DOCUMENT = """# Directed planning request

No planning document directory was provided. Build the plan from the user's
directed request, active repository instructions, and the minimum relevant
repository code inspected in read-only mode.
"""


class InitialSourceIndex(Protocol):
    def __call__(self, source_root: str | Path, *, base_commit: str) -> tuple[PlanningSourceIndex, bool]: ...


@dataclass(frozen=True, slots=True)
class InitialVerificationSettings:
    task_verify_command_timeout_seconds: int
    task_verify_total_timeout_seconds: int
    integration_verify_command_timeout_seconds: int
    integration_verify_total_timeout_seconds: int
    verification_repair_limit: int

    def ensure_verification(self, state: RunState) -> None:
        state.verification_policy_version = max(1, state.verification_policy_version)
        if state.task_verify_command_timeout_seconds <= 0:
            state.task_verify_command_timeout_seconds = self.task_verify_command_timeout_seconds
        if state.task_verify_total_timeout_seconds <= 0:
            state.task_verify_total_timeout_seconds = self.task_verify_total_timeout_seconds
        if state.integration_verify_command_timeout_seconds <= 0:
            state.integration_verify_command_timeout_seconds = self.integration_verify_command_timeout_seconds
        if state.integration_verify_total_timeout_seconds <= 0:
            state.integration_verify_total_timeout_seconds = self.integration_verify_total_timeout_seconds
        if state.verification_repair_limit <= 0:
            state.verification_repair_limit = self.verification_repair_limit



@dataclass(frozen=True, slots=True)
class PreparedPlanning:
    state: RunState
    document: str
    source_index: PlanningSourceIndex | None
    source_index_reused: bool
    selected_effort: EffortMode
    repository_intent: str
    explicit_repository_intent: bool


@dataclass(frozen=True, slots=True)
class PlanningPreparation:
    repo: Path
    main_branch: str
    default_agent_id: str
    verification: InitialVerificationSettings
    workspace_location: Callable[[], WorkspaceLocation]
    normalize_agent_id: Callable[[str], str]
    normalize_model: Callable[[str], str]
    normalize_effort: Callable[[str], str]
    normalize_mode: Callable[[PlanningMode | str], PlanningMode]
    ensure_git_ready: Callable[[], None]
    available_agent: Callable[[str, str], AgentConfig]
    ensure_provider_ready: Callable[[AgentConfig], None]
    validate_effort: Callable[[AgentConfig, str, str], None]
    read_base_commit: Callable[[], str]
    source_index_for_start: InitialSourceIndex

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
    ) -> PreparedPlanning:
        try:
            selected_effort = EffortMode(effort_mode)
            profile_source = ProfileSource(planning_profile_source) if planning_profile_source is not None else None
        except ValueError as exc:
            raise PipelineError("invalid initial effort mode or Planning profile source") from exc
        if profile_source is not None and profile_source not in {ProfileSource.MANUAL, ProfileSource.ROUTING}:
            raise PipelineError("initial Planning profile source must be manual or routing")
        planning_agent_id = self.normalize_agent_id(planning_agent_id)
        planning_model = self.normalize_model(planning_model)
        planning_reasoning_effort = self.normalize_effort(planning_reasoning_effort)
        normalized_planning_mode = self.normalize_mode(planning_mode)
        planning_request = planning_request.strip()
        explicit_repository_intent = repository_intent is not None
        repository_intent = (repository_intent or "").strip()
        if repository_intent not in {"", "existing_structure", "new_project"}:
            raise PipelineError(f"unsupported repository intent: {repository_intent}")
        if normalized_planning_mode == PlanningMode.DIRECTED and not planning_request:
            raise PipelineError("directed planning requires a specific user request")
        if normalized_planning_mode == PlanningMode.AUTO and planning_request:
            raise PipelineError("full auto planning does not accept a directed request")
        self.ensure_git_ready()
        if planning_agent_id:
            planning_agent = self.available_agent(planning_agent_id, "review")
        else:
            planning_agent = None
        raw_spec_path = str(spec_path).strip()
        if not raw_spec_path and normalized_planning_mode == PlanningMode.AUTO:
            raise PipelineError("full auto planning requires a planning document or directory")
        if not raw_spec_path and prepared_source_index is not None:
            raise PipelineError("prepared planning source index requires a planning directory")
        provider_readiness_agent = planning_agent
        if provider_readiness_agent is None and self.default_agent_id:
            provider_readiness_agent = self.available_agent(self.default_agent_id, "review")
        if provider_readiness_agent is not None:
            self.ensure_provider_ready(provider_readiness_agent)
        reasoning_agent_id = planning_agent_id or self.default_agent_id
        if planning_reasoning_effort and reasoning_agent_id:
            reasoning_agent = self.available_agent(reasoning_agent_id, "review")
            self.validate_effort(reasoning_agent, planning_reasoning_effort, planning_model or reasoning_agent.model)
        path = filesystem_path(Path(raw_spec_path).expanduser()).resolve() if raw_spec_path else None
        source_index: PlanningSourceIndex | None = None
        source_index_reused = False
        if prepared_source_index is not None:
            repository_root = self.repo.expanduser().resolve()
            if (
                path is None
                or not path.is_dir()
                or Path(prepared_source_index.source_root).resolve() != path
                or Path(prepared_source_index.repository_root).resolve() != repository_root
                or not Path(prepared_source_index.cache_path).is_file()
            ):
                raise PipelineError("prepared planning source index does not match the project")
            base_commit = prepared_source_index.base_commit
            source_index = prepared_source_index
            source_index_reused = True
            document = render_planning_source_index(source_index)
        else:
            base_commit = self.read_base_commit()
        if source_index is None and path is not None and path.is_dir():
            source_index, source_index_reused = self.source_index_for_start(path, base_commit=base_commit)
            document = render_planning_source_index(source_index)
        elif source_index is None and path is not None:
            document = read_planning_document(path)
        elif source_index is None:
            document = DIRECTED_PLANNING_WITHOUT_SOURCE_DOCUMENT
        content = document.encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        run_id = reserved_run_id or f"{timestamp}-{digest[:8]}"
        state = RunState(
            id=run_id,
            spec_path=str(path) if path is not None else "",
            spec_digest=digest,
            repo_path=str(self.repo),
            main_branch=self.main_branch,
            stage=Stage.RECEIVED,
            workspace_mode=ExecutionWorkspaceMode.SHARED,
            workspace_location=self.workspace_location(),
            base_commit=base_commit,
            planning_agent_id=planning_agent.id if planning_agent else "",
            planning_provider_id=(planning_agent.provider_id if planning_agent else ""),
            planning_model=planning_model,
            planning_reasoning_effort=planning_reasoning_effort,
            planning_profile_source=profile_source or (
                ProfileSource.MANUAL if planning_agent_id or planning_model or planning_reasoning_effort else ProfileSource.ROUTING
            ),
            planning_mode=normalized_planning_mode,
            planning_request=planning_request,
            revision_source_run_id=revision_source_run_id,
            revision_request_id=revision_request_id,
            revision_request_text=revision_request_text,
            revision_source_task_ids=list(revision_source_task_ids),
            revision_source_paths=list(revision_source_paths),
            task_verify_command_timeout_seconds=self.verification.task_verify_command_timeout_seconds,
            task_verify_total_timeout_seconds=self.verification.task_verify_total_timeout_seconds,
            integration_verify_command_timeout_seconds=self.verification.integration_verify_command_timeout_seconds,
            integration_verify_total_timeout_seconds=self.verification.integration_verify_total_timeout_seconds,
            verification_repair_limit=self.verification.verification_repair_limit,
            planning_messages=(
                [PlanningMessage(role=PlanningMessageRole.USER, text=planning_request)] if normalized_planning_mode == PlanningMode.DIRECTED else []
            ),
            planning_conversation_revision=(1 if normalized_planning_mode == PlanningMode.DIRECTED else 0),
        )
        return PreparedPlanning(state, document, source_index, source_index_reused, selected_effort,
                                repository_intent, explicit_repository_intent)


def write_prepared_planning_sources(prepared: PreparedPlanning, *, run_directory: Callable[[str], Path]) -> None:
    state, document = prepared.state, prepared.document
    source_index, source_index_reused = prepared.source_index, prepared.source_index_reused
    snapshot_path = run_directory(state.id) / "planning-document.md"
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(document, encoding="utf-8")
    state.spec_snapshot_path = str(snapshot_path)
    if source_index is not None:
        index_snapshot_path = run_directory(state.id) / "planning-source-index.json"
        index_snapshot_path.write_text(
            json.dumps(source_index.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        state.add_event(
            "planning",
            f"planning source index "
            f"{'reused' if source_index_reused else 'refreshed'}: "
            f"{source_index.document_count} documents, "
            f"{source_index.updated_count} updated, "
            f"{source_index.reused_count} reused, "
            f"{source_index.added_count} added, "
            f"{source_index.modified_count} modified, "
            f"{source_index.deleted_count} deleted",
        )
