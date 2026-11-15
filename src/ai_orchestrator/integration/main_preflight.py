"""Main apply checks inside caller-owned project and run locks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..errors import PipelineError
from ..git import GitWorkspace, LOCAL_GIT_TIMEOUT_SECONDS
from ..models import RunState, Stage, TaskStatus


@dataclass(frozen=True, slots=True)
class IsolatedMainApplyPreflight:
    git: GitWorkspace
    repo: Path
    integration_branch: Callable[[str], str]
    invalidate: Callable[[RunState, str], None]
    ensure_main_ready: Callable[[], None]

    def validate(self, state: RunState, run_id: str) -> None:
        if state.stage != Stage.VERIFIED:
            raise PipelineError(f"run {run_id} is at '{state.stage.value}', expected one of: {Stage.VERIFIED.value}")
        if not state.verified_task_heads:
            raise PipelineError("run has no pre-merge verification record")
        if not (state.verified_main_head and state.verified_integration_head):
            self.invalidate(state, "pre-merge verification record requires refresh")
            raise PipelineError("verified run has no preserved integration commit; run verification again")
        if not all(task.status == TaskStatus.COMPLETED for task in state.tasks):
            raise PipelineError("only completed, unmerged tasks can be merged")
        changed_heads = [
            task.id
            for task in state.tasks
            if state.verified_task_heads.get(task.id)
            != self.git.branch_head(task.branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        ]
        if changed_heads:
            self.invalidate(state, "pre-merge verification invalidated by changed task branches")
            raise PipelineError("task branches changed after verification: " + ", ".join(changed_heads))
        self.ensure_main_ready()
        current_main_head = self.git.head(self.repo, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        if current_main_head != state.verified_main_head:
            self.invalidate(state, "pre-merge verification invalidated by changed main HEAD")
            raise PipelineError(
                "main HEAD changed after integration verification "
                f"(expected {state.verified_main_head}, "
                f"found {current_main_head}); run verification again"
            )
        integration_branch = self.integration_branch(state.id)
        if (
            not self.git.branch_exists(integration_branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            or self.git.branch_head(integration_branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            != state.verified_integration_head
        ):
            self.invalidate(state, "preserved integration commit is unavailable")
            raise PipelineError("preserved integration commit is unavailable; run verification again")


@dataclass(frozen=True, slots=True)
class SharedMainApplyPreflight:
    git: GitWorkspace
    repo: Path
    shared_boundary: Callable[[RunState], tuple[str, Path]]
    invalidate: Callable[[RunState, str], None]

    def validate(self, state: RunState, *, remote_configured: bool) -> str:
        expected_stage = Stage.WORK_BRANCH_PUSHED if remote_configured else Stage.VERIFIED
        if state.stage != expected_stage:
            raise PipelineError(f"run {state.id} is at '{state.stage.value}', expected one of: {expected_stage.value}")
        if not all(task.status == TaskStatus.COMPLETED for task in state.tasks):
            raise PipelineError("shared run Main apply requires every task to be completed")
        if not (state.verified_main_head and state.verified_integration_head) or (
            remote_configured and not state.pushed_work_branch_head
        ):
            self.invalidate(state, "shared run verification or required work branch Push record is incomplete")
            raise PipelineError("shared run has no complete verified commit record; run verification and any required work branch Push again")
        branch, _ = self.shared_boundary(state)
        branch_head = self.git.branch_head(branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        if branch_head != state.verified_integration_head or (
            remote_configured and branch_head != state.pushed_work_branch_head
        ):
            self.invalidate(state, "shared work branch changed after verification or Push")
            raise PipelineError("shared work branch changed after verification or Push; run verification and work branch Push again")
        self.git.ensure_main_branch(non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        current_main_head = self.git.head(self.repo, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        if current_main_head not in {state.verified_main_head, state.verified_integration_head}:
            self.invalidate(state, "shared run verification invalidated by changed main HEAD")
            raise PipelineError(
                "main HEAD changed after shared workspace verification "
                f"(expected {state.verified_main_head}, "
                f"found {current_main_head}); run verification and Push again"
            )
        return current_main_head
