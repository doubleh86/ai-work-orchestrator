"""Verification repair candidate Git effects without Run authority."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from ..config import AgentConfig
from ..errors import PipelineError
from ..git import GitWorkspace, LOCAL_GIT_TIMEOUT_SECONDS
from ..models import RunState, WorkTask

if TYPE_CHECKING:
    from ..execution.verification_repair import VerificationRepairProposal


@dataclass(frozen=True, slots=True)
class VerificationRepairWorkspace:
    git: GitWorkspace
    save_state: Callable[[RunState], None]
    uses_shared: Callable[[RunState], bool]
    integration_branch: Callable[[str], str]
    worktree_root: Callable[[RunState], Path]
    shared_boundary: Callable[[RunState], tuple[str, Path]]
    ensure_clean: Callable[[Path], None]
    validate_scope: Callable[[WorkTask, RunState], None]
    propose: Callable[[RunState, AgentConfig, Path, str, Exception, int], VerificationRepairProposal]

    def repair(self, state: RunState, agent: AgentConfig, error: Exception, repair_index: int) -> None:
        isolated = not self.uses_shared(state)
        integration_branch = self.integration_branch(state.id)
        if isolated:
            if not state.verification_repair_head or not self.git.branch_exists(
                integration_branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
            ):
                raise PipelineError("자동 수정에 사용할 통합 검증 후보 commit이 없습니다.")
            worktree = self.worktree_root(state) / ".verification-repair"
            self.git.prepare_detached_worktree(
                worktree,
                state.verification_repair_head,
                non_interactive=True,
                timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
            )
        else:
            _, worktree = self.shared_boundary(state)
        try:
            self.ensure_clean(worktree)
            before = self.git.head(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            proposal = self.propose(state, agent, worktree, before, error, repair_index)
            attempt = proposal.attempt
            self.validate_scope(proposal.task, state)
            self.git.commit_all(
                worktree,
                f"fix(verification): repair failed final check {repair_index}",
                non_interactive=True,
                timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
            )
            after = self.git.head(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            if after == before:
                raise PipelineError("검증 자동 수정 Agent가 변경 commit을 만들지 않았습니다.")
            self.ensure_clean(worktree)
            if isolated:
                self.git.update_branch(integration_branch, after, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            state.verification_repair_head = after
            if not state.verification_repair_main_head and attempt is not None:
                state.verification_repair_main_head = attempt.main_head
                state.verification_repair_task_heads = dict(attempt.task_heads)
            self.save_state(state)
        finally:
            if isolated:
                self.git.discard_detached_worktree(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
