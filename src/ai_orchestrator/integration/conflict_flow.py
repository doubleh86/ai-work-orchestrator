"""ConflictFlow with explicit phase and persistence dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, ContextManager
from ..config import AgentConfig, PlanningConfig
from ..execution import normalize_reasoning_effort, validate_reasoning_effort
from ..execution.lifecycle import StoredStopSignal
from ..execution.provider_choices import ProviderAvailability
from ..execution.provider_commands import agent_command, command_with_model
from ..execution.provider_runtime import ProviderRuntime
from ..execution.task_workflows import TaskWorkflows
from ..git import GitWorkspace
from ..integration import ConflictCandidateBuilder, ConflictInspector, ConflictResolutionProfile, ConflictResolutionRecords, ConflictResolutionService
from ..integration.workspace_access import WorkspaceAccess
from ..integration.workspace_flows import WorkspaceFlows
from ..model_selection import CODEX_SOL_MODEL
from ..models import ConflictResolutionCandidate, RunState
from ..persistence.integration_records import ConflictFlowRecords


@dataclass
class ConflictFlow:
    records: ConflictFlowRecords
    read_log_tail: Callable[[Path], str]
    read_git: Callable[[], GitWorkspace]
    read_repo: Callable[[], Path]
    workspaces: WorkspaceFlows
    availability: ProviderAvailability
    planning_settings: Callable[[], PlanningConfig]
    workspace: WorkspaceAccess
    provider: ProviderRuntime[StoredStopSignal]
    state_lock: ContextManager[object]

    def view(
        self, run_id: str, *, conflict_id: str = "", file_path: str = "", recovery_task_id: str = ""
    ) -> dict[str, object]:
        state = self.records.load(run_id)
        return ConflictInspector(
            self.read_git(), self.read_repo(), self.records.run_dir, self.records.load_operation, self.read_log_tail,
        ).view(state, run_id, conflict_id=conflict_id, file_path=file_path, recovery_task_id=recovery_task_id)


    def discard_conflict_candidate_worktree(self, state: RunState, candidate: ConflictResolutionCandidate) -> None:
        return self.workspaces.lifecycle().discard_conflict_candidate(state, candidate)


    def conflict_resolution_profile(
        self, state: RunState, agent_id: str, model: str, reasoning_effort: str,
    ) -> ConflictResolutionProfile:
        selected_agent_id = agent_id.strip() or state.planning_agent_id or self.planning_settings().agent_id
        agent = self.availability.require(selected_agent_id, "execute")
        selected_model = model.strip() or (CODEX_SOL_MODEL if agent.provider_id == "codex" else agent.model)
        selected_effort = normalize_reasoning_effort(reasoning_effort)
        validate_reasoning_effort(agent, selected_effort, selected_model)
        return ConflictResolutionProfile(agent, selected_model, selected_effort)


    def conflict_resolution_command(self, agent: AgentConfig, selected_model: str, selected_effort: str) -> tuple[str, ...]:
        command_template = agent_command(agent, "execute")
        command_template = command_with_model(agent, command_template, selected_model)
        command_template = TaskWorkflows.command_with_reasoning_effort(agent, command_template, selected_effort, selected_model)
        return command_template


    def service(self) -> ConflictResolutionService:
        records = ConflictResolutionRecords(
            self.records.save, self.records.claim_operation, self.records.save_operation,
        )
        builder = ConflictCandidateBuilder(
            self.read_git(), self.records.run_dir, self.conflict_resolution_command, self.provider.invoke,
            self.state_lock, self.records.save_operation,
        )
        return ConflictResolutionService(
            self.read_git(), self.read_repo(), records, self.workspace.shared_workspace_boundary, self.workspace.ensure_worktree_clean,
            self.workspace.run_worktree_root, self.discard_conflict_candidate_worktree, self.conflict_resolution_profile, builder,
            lambda run_id, conflict_id: self.view(run_id, conflict_id=conflict_id),
        )
