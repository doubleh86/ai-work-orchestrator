import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, PlanningConfig, ProjectConfig
from ai_orchestrator.errors import PipelineError
from ai_orchestrator.git import GitWorkspace
from ai_orchestrator.integration import (
    ConflictCandidateBuilder, ConflictResolutionRecords, ConflictResolutionService, candidate_content_digest,
)
from ai_orchestrator.models import (
    ConflictResolutionCandidate, ConflictResolutionStatus, IntegrationConflict, IntegrationConflictFile, RunState, Stage,
)
from ai_orchestrator.pipeline import Pipeline


def resolution_fixture(root: Path):
    git = Mock(spec=GitWorkspace)
    git.blob_at.return_value = "reviewed-blob"
    candidate = ConflictResolutionCandidate(
        "candidate", "generation-request", status=ConflictResolutionStatus.CANDIDATE_READY.value,
        worktree=str(root / "candidate"), commit="candidate-commit",
    )
    conflict = IntegrationConflict(
        "conflict", "verification", "main-head", "work-head", [], [IntegrationConflictFile("result.txt", "content")],
        "fingerprint", candidate=candidate,
    )
    candidate.content_digest = candidate_content_digest(git, root / "candidate", candidate.commit, conflict.files)
    git.reset_mock()
    state = RunState("run", "plan.md", "digest", str(root), "main", Stage.FAILED, integration_conflict=conflict)
    records = ConflictResolutionRecords(Mock(), Mock(), Mock())
    service = ConflictResolutionService(
        git, root, records, lambda _state: ("work", root / "work"), Mock(), lambda _state: root / "run",
        Mock(), Mock(), Mock(spec=ConflictCandidateBuilder), Mock(),
    )
    return service, state, conflict, candidate


@pytest.mark.parametrize("changed", ["main", "candidate"])
def test_reviewed_candidate_is_not_applied_when_main_or_its_content_changed(tmp_path: Path, changed: str) -> None:
    service, state, conflict, candidate = resolution_fixture(tmp_path)
    if changed == "main":
        service.git.head.side_effect = ["different-main"]
    else:
        service.git.head.side_effect = [conflict.main_head, conflict.work_head]
        service.git.blob_at.return_value = "changed-after-review"

    with pytest.raises(PipelineError, match="적용하지 않았습니다"):
        service.apply_candidate(state, conflict, candidate_id=candidate.id, candidate_revision=1, normalized_request_id="apply")

    assert conflict.resolution_status == ConflictResolutionStatus.STALE
    service.records.save_state.assert_called_once_with(state)
    service.records.claim_operation.assert_not_called()
    service.git.fast_forward_worktree.assert_not_called()


def test_repeated_successful_apply_does_not_touch_git_or_claim_another_operation(tmp_path: Path) -> None:
    service, state, conflict, candidate = resolution_fixture(tmp_path)
    candidate.apply_request_id = "apply"
    candidate.status = ConflictResolutionStatus.APPLIED.value

    result = service.apply_candidate(state, conflict, candidate_id=candidate.id, candidate_revision=1, normalized_request_id="apply")

    assert result is None
    assert service.git.mock_calls == []
    service.records.claim_operation.assert_not_called()
    service.records.save_state.assert_not_called()


def test_conflict_resolution_falls_back_to_the_configured_planning_agent(tmp_path: Path) -> None:
    agent = AgentConfig("configured-ai", ("general",), (sys.executable, "-c", "pass"), provider_id="local", model="local-model")
    pipeline = Pipeline(Config(
        path=tmp_path / "config.toml", project=ProjectConfig(repo=tmp_path), execution=ExecutionConfig(), agents=(agent,),
        planning=PlanningConfig(agent_id=agent.id),
    ))
    state = RunState("run", "plan.md", "digest", str(tmp_path), "main", Stage.FAILED)

    profile = pipeline._common_runtime.integration.conflicts.conflict_resolution_profile(state, "", "", "")

    assert profile.agent is agent
    assert profile.model == agent.model
    assert profile.reasoning_effort == ""
