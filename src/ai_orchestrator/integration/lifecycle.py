from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .conflicts import conflict_request_id
from .layout import WorkspaceLayout, shared_run_branch_name, uses_shared_workspace
from .workspaces import WorkspaceInspector
from ..errors import PipelineError
from ..git import GitError, GitWorkspace, GitWorktree, LOCAL_GIT_TIMEOUT_SECONDS
from ..models import ArchiveCleanupTarget, ConflictResolutionCandidate, RunState, WorkTask


@dataclass(frozen=True, slots=True)
class WorkspaceLifecycle:
    git: GitWorkspace
    layout: WorkspaceLayout
    inspector: WorkspaceInspector
    repository: Path
    records_root: Path

    def cleanup_archive_target(self, state: RunState, target: ArchiveCleanupTarget) -> None:
        worktree = Path(target.recorded_path).expanduser().resolve()
        if not self.archive_path_is_owned(state, worktree):
            raise PipelineError(f"작업공간 경로의 그룹 소유권을 확인할 수 없습니다: {worktree}")
        registered = {
            item.path: item
            for item in self.git.list_worktrees(non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        }
        entry = registered.get(worktree)
        if entry is None:
            if not worktree.exists():
                target.status = "already_removed"
                target.error = ""
                return
            if self.git.owns_orphaned_worktree_marker(
                worktree,
                non_interactive=True,
                timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
            ):
                self.git.remove_orphaned_worktree_residue(
                    worktree,
                    non_interactive=True,
                    timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
                )
            elif (
                self.recorded_removal_failure(state, worktree)
                or self.target_has_removal_failure(target, worktree)
                or self.contains_only_managed_state_residue(worktree)
            ):
                self.git.remove_worktree_residue(worktree)
            else:
                raise PipelineError(f"Git이 소유하지 않는 경로는 정리하지 않았습니다: {worktree}")
            target.status = "removed"
            target.error = ""
            run_root = self.layout.run_root(state)
            if run_root.is_dir() and not any(run_root.iterdir()):
                run_root.rmdir()
            return
        if not worktree.is_dir():
            raise PipelineError(f"등록된 worktree 경로를 읽을 수 없습니다: {worktree}")
        if entry.head != target.expected_head:
            raise PipelineError(f"worktree HEAD가 보관 확인 값과 다릅니다: {entry.head}")
        expected_branch = self.archive_expected_branch(state, target.id)
        if entry.branch != expected_branch:
            raise PipelineError(f"worktree branch가 보관 확인 값과 다릅니다: {entry.branch or 'detached'}")
        managed_roots = self.layout.managed_state_roots(worktree)
        if self.git.has_worktree_uncommitted_changes(
            worktree,
            ignored_untracked_roots=managed_roots,
            non_interactive=True,
            timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
        ):
            raise PipelineError("미커밋 또는 미추적 사용자 변경이 있어 정리를 보류했습니다.")
        if self.git.worktree_has_unapproved_ignored_files(
            worktree,
            allowed_roots=managed_roots,
            non_interactive=True,
            timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
        ):
            raise PipelineError("소유권을 확인할 수 없는 ignored 파일이 있어 정리를 보류했습니다.")
        for managed_root in managed_roots:
            if not managed_root.exists():
                continue
            is_junction = getattr(managed_root, "is_junction", lambda: False)
            if managed_root.is_symlink() or is_junction() or managed_root.parent.resolve() != worktree:
                raise PipelineError(f"관리 상태 경로의 소유권을 확인할 수 없습니다: {managed_root}")
            shutil.rmtree(managed_root)
        self.git.remove_worktree(worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        target.status = "removed"
        target.error = ""
        run_root = self.layout.run_root(state)
        if run_root.is_dir() and not any(run_root.iterdir()):
            run_root.rmdir()

    def archive_cleanup_targets(
        self, state: RunState, registered: dict[Path, GitWorktree]
    ) -> list[ArchiveCleanupTarget]:
        specs: list[tuple[str, Path, str]] = []
        run_root = self.layout.run_root(state)
        if uses_shared_workspace(state):
            worktree = self.layout.shared_path(state).resolve()
            expected_head = state.verified_integration_head or next(
                (task.completed_commit for task in reversed(state.tasks) if task.completed_commit), ""
            )
            specs.append(("shared", worktree, expected_head))
        else:
            for task in state.tasks:
                specs.append((f"task-{task.id}", (run_root / task.id).resolve(), task.completed_commit))
            verification = self.layout.verification_path(state).resolve()
            if verification.exists() or verification in registered:
                specs.append(("verification", verification, state.verified_integration_head))
        candidate = state.integration_conflict.candidate if state.integration_conflict else None
        if candidate is not None and candidate.worktree:
            specs.append(("conflict-candidate", Path(candidate.worktree).expanduser().resolve(), candidate.commit))
        targets: list[ArchiveCleanupTarget] = []
        seen: set[Path] = set()
        for target_id, worktree, expected_head in specs:
            if worktree in seen:
                continue
            seen.add(worktree)
            target = ArchiveCleanupTarget(id=target_id, recorded_path=str(worktree), expected_head=expected_head)
            entry = registered.get(worktree)
            if entry is None and not worktree.exists():
                target.status = "already_removed"
            elif not self.archive_path_is_owned(state, worktree):
                target.status = "blocked"
                target.error = "작업공간 경로의 그룹 소유권을 확인할 수 없습니다."
            elif entry is None:
                target.status = "blocked"
                target.error = "Git이 소유하지 않는 경로입니다."
            elif not expected_head or entry.head != expected_head:
                target.status = "blocked"
                target.error = "worktree HEAD가 저장된 완료 commit과 일치하지 않습니다."
            else:
                expected_branch = self.archive_expected_branch(state, target_id)
                if entry.branch != expected_branch:
                    target.status = "blocked"
                    target.error = "worktree branch가 저장된 그룹 소유 정보와 일치하지 않습니다."
                else:
                    try:
                        managed_roots = self.layout.managed_state_roots(worktree)
                        if self.git.has_worktree_uncommitted_changes(
                            worktree,
                            ignored_untracked_roots=managed_roots,
                            non_interactive=True,
                            timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
                        ):
                            target.status = "blocked"
                            target.error = "미커밋 또는 미추적 사용자 변경이 있습니다."
                        elif self.git.worktree_has_unapproved_ignored_files(
                            worktree,
                            allowed_roots=managed_roots,
                            non_interactive=True,
                            timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
                        ):
                            target.status = "blocked"
                            target.error = "소유권을 확인할 수 없는 ignored 파일이 있습니다."
                    except (GitError, OSError) as exc:
                        target.status = "blocked"
                        target.error = str(exc)
            targets.append(target)
        return targets

    def archive_path_is_owned(self, state: RunState, worktree: Path) -> bool:
        run_root = self.layout.run_root(state).resolve()
        repository = self.repository.resolve()
        records = self.records_root.resolve()
        return (
            worktree != run_root
            and worktree.is_relative_to(run_root)
            and worktree != repository
            and not repository.is_relative_to(worktree)
            and worktree != records
            and not records.is_relative_to(worktree)
            and not worktree.is_symlink()
            and not getattr(worktree, "is_junction", lambda: False)()
        )

    def archive_expected_branch(self, state: RunState, target_id: str) -> str:
        if target_id == "shared":
            return shared_run_branch_name(state.id)
        if target_id.startswith("task-"):
            task_id = target_id.removeprefix("task-")
            return f"ai/{state.id}/{task_id}"
        return ""

    def deletion_targets(
        self,
        state: RunState,
        registered: dict[Path, GitWorktree],
        *,
        additional_expected_worktrees: tuple[Path, ...] = (),
        remaining_timeout: Callable[[], float] | None = None,
    ) -> list[tuple[str, Path, WorkTask]]:
        group_root = self.layout.run_root(state)
        expected_worktrees = set(additional_expected_worktrees)
        targets: list[tuple[str, Path, WorkTask]] = []
        workspace_tasks = state.tasks
        if uses_shared_workspace(state) and state.tasks:
            try:
                self.layout.shared_boundary(state)
            except PipelineError as exc:
                raise PipelineError(f"작업 그룹을 삭제할 수 없습니다. 공유 작업공간이 허용된 경계 밖에 있습니다: {exc}") from exc
            workspace_tasks = state.tasks[:1]
        for task in workspace_tasks:
            if uses_shared_workspace(state):
                expected_branch = shared_run_branch_name(state.id)
                expected_worktree = self.layout.shared_path(state).resolve()
                branch = state.execution_branch or task.branch or expected_branch
                configured_worktree = state.execution_worktree or task.worktree
            else:
                expected_branch = f"ai/{state.id}/{task.id}"
                expected_worktree = (group_root / task.id).resolve()
                branch = task.branch or expected_branch
                configured_worktree = task.worktree
            worktree = Path(configured_worktree).expanduser().resolve() if configured_worktree else expected_worktree
            if branch != expected_branch or worktree != expected_worktree:
                raise PipelineError(f"작업 그룹을 삭제할 수 없습니다. Task 작업공간이 허용된 경계 밖에 있습니다: {task.id}")
            entry = registered.get(worktree)
            if (
                worktree.exists()
                and entry is None
                and not self.git.owns_orphaned_worktree_marker(
                    worktree,
                    non_interactive=True,
                    timeout_seconds=remaining_timeout() if remaining_timeout is not None else LOCAL_GIT_TIMEOUT_SECONDS,
                )
                and not self.recorded_removal_failure(state, worktree)
                and not self.contains_only_managed_state_residue(worktree)
            ):
                raise PipelineError(f"작업 그룹을 삭제할 수 없습니다. 작업공간 경로를 Git이 소유하지 않습니다: {worktree}")
            if entry is not None and entry.branch != branch:
                raise PipelineError(f"작업 그룹을 삭제할 수 없습니다. 등록된 worktree가 다른 branch를 사용합니다: {worktree}")
            branch_owners = [item.path for item in registered.values() if item.branch == branch and item.path != worktree]
            if branch_owners:
                raise PipelineError(f"작업 그룹을 삭제할 수 없습니다. Task branch가 다른 worktree에서 사용 중입니다: {branch_owners[0]}")
            expected_worktrees.add(worktree)
            targets.append((branch, worktree, task))

        if group_root.exists():
            if not group_root.is_dir():
                raise PipelineError(f"작업 그룹의 worktree 루트가 디렉터리가 아닙니다: {group_root}")
            unexpected = [child for child in group_root.iterdir() if child.resolve() not in expected_worktrees]
            if unexpected:
                raise PipelineError(f"작업 그룹을 삭제할 수 없습니다. worktree 루트에 소유권을 확인할 수 없는 경로가 있습니다: {unexpected[0]}")
        return targets

    @staticmethod
    def recorded_removal_failure(state: RunState, worktree: Path) -> bool:
        if (worktree / ".git").exists():
            return False
        expected_path = str(worktree).casefold()
        expected_posix_path = expected_path.replace("\\", "/")
        for event in reversed(state.events):
            if event.kind != "workspace":
                continue
            message = event.message.casefold()
            if (
                ("run deletion failed:" in message or "workspace cleanup deferred:" in message or " cleanup failed:" in message)
                and ("worktree remove" in message or "could not remove worktree residue at" in message)
                and (expected_path in message or expected_posix_path in message)
            ):
                return True
        return False

    @staticmethod
    def target_has_removal_failure(target: ArchiveCleanupTarget, worktree: Path) -> bool:
        if target.status != "failed" or (worktree / ".git").exists():
            return False
        message = target.error.casefold()
        expected_path = str(worktree).casefold()
        expected_posix_path = expected_path.replace("\\", "/")
        return (
            ("worktree remove" in message or "could not remove worktree residue at" in message)
            and (expected_path in message or expected_posix_path in message)
        )

    def contains_only_managed_state_residue(self, worktree: Path) -> bool:
        selected_worktree = worktree.expanduser().absolute()
        is_junction = getattr(selected_worktree, "is_junction", lambda: False)
        if selected_worktree.is_symlink() or is_junction() or not selected_worktree.is_dir():
            return False
        try:
            children = list(selected_worktree.iterdir())
        except OSError:
            return False
        if not children:
            return True
        managed_roots = {
            root.absolute()
            for root in self.layout.managed_state_roots(selected_worktree)
            if root.parent.absolute() == selected_worktree
        }
        if not managed_roots:
            return False
        for child in children:
            child_is_junction = getattr(child, "is_junction", lambda: False)
            if child.is_symlink() or child_is_junction() or child.absolute() not in managed_roots:
                return False
        return True

    def deletion_verification_path(
        self,
        state: RunState,
        registered: dict[Path, GitWorktree],
        *,
        remaining_timeout: Callable[[], float] | None = None,
    ) -> Path | None:
        if uses_shared_workspace(state):
            return None
        group_root = self.layout.run_root(state).resolve()
        verification_worktree = self.layout.verification_path(state).resolve()
        if verification_worktree.parent != group_root:
            raise PipelineError(f"작업 그룹을 삭제할 수 없습니다. 검증용 worktree가 허용된 경계 밖에 있습니다: {verification_worktree}")
        entry = registered.get(verification_worktree)
        if entry is not None:
            if entry.branch:
                raise PipelineError(f"작업 그룹을 삭제할 수 없습니다. 검증용 worktree가 branch를 사용 중입니다: {entry.branch}")
            return verification_worktree
        if (
            verification_worktree.exists()
            and not self.git.owns_orphaned_worktree_marker(
                verification_worktree,
                non_interactive=True,
                timeout_seconds=remaining_timeout() if remaining_timeout is not None else LOCAL_GIT_TIMEOUT_SECONDS,
            )
            and not self.recorded_removal_failure(state, verification_worktree)
            and not self.contains_only_managed_state_residue(verification_worktree)
        ):
            raise PipelineError(f"작업 그룹을 삭제할 수 없습니다. 검증용 경로를 Git이 소유하지 않습니다: {verification_worktree}")
        return verification_worktree if verification_worktree.exists() else None

    def deletion_conflict_path(self, state: RunState, registered: dict[Path, GitWorktree]) -> Path | None:
        candidate = state.integration_conflict.candidate if state.integration_conflict else None
        if candidate is None or not candidate.worktree:
            return None
        group_root = self.layout.run_root(state).resolve()
        conflict_root = (group_root / ".conflict-resolution").resolve()
        worktree = Path(candidate.worktree).expanduser().resolve()
        try:
            request_id = conflict_request_id(candidate.request_id)
        except PipelineError as exc:
            raise PipelineError("작업 그룹을 삭제할 수 없습니다. 충돌 해결 후보 request ID가 올바르지 않습니다.") from exc
        expected_worktree = (conflict_root / request_id).resolve()
        if candidate.id != f"candidate-{request_id}" or worktree != expected_worktree:
            raise PipelineError(f"작업 그룹을 삭제할 수 없습니다. 충돌 해결 후보가 허용된 경계 밖에 있습니다: {worktree}")
        entry = registered.get(worktree)
        if entry is not None and entry.branch:
            raise PipelineError(f"작업 그룹을 삭제할 수 없습니다. 충돌 해결 후보가 branch를 사용 중입니다: {entry.branch}")
        if worktree.exists() and entry is None and (worktree / ".git").exists():
            raise PipelineError(f"작업 그룹을 삭제할 수 없습니다. 미등록 충돌 해결 후보에 Git marker가 남아 있습니다: {worktree}")
        return worktree if entry is not None or worktree.exists() else None

    def discard_conflict_candidate(self, state: RunState, candidate: ConflictResolutionCandidate) -> None:
        path = Path(candidate.worktree)
        root = (self.layout.run_root(state) / ".conflict-resolution").resolve()
        if path.is_symlink() or path.resolve().parent != root or path.name != candidate.request_id:
            raise PipelineError("충돌 해결 후보 경로가 작업 그룹 경계를 벗어났습니다.")
        target = path.resolve()
        try:
            self.git.discard_detached_worktree(target, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        except GitError:
            registered = self.git.list_worktrees(non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
            if any(worktree.path == target for worktree in registered) or not target.is_dir() or target.is_symlink():
                raise
        if target.is_dir():
            try:
                target.rmdir()
            except OSError as exc:
                raise PipelineError(f"등록되지 않은 충돌 후보 폴더가 비어 있지 않거나 사용 중입니다: {target}") from exc

    def cleanup_shared(
        self, state: RunState, *, discard_idle_clients: Callable[[], None],
        on_deferred: Callable[[Exception], None],
    ) -> None:
        branch, worktree = self.layout.shared_boundary(state)
        discard_idle_clients()
        registered = {item.path: item for item in self.git.list_worktrees(non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)}
        entry = registered.get(worktree)
        if entry is not None and entry.branch != branch:
            raise PipelineError("shared run worktree is registered on a different branch")
        if worktree.exists() and entry is None:
            if not self.recorded_removal_failure(state, worktree):
                raise PipelineError("shared run worktree path exists but is not registered by Git")
            self.git.remove_worktree_residue(worktree)
        if entry is not None:
            self.inspector.ensure_clean(worktree)
            managed_state_exists = any(path.exists() for path in self.layout.managed_state_roots(worktree))
            try:
                self.git.remove_worktree(
                    worktree, force=managed_state_exists, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
                )
            except (GitError, OSError) as exc:
                remaining = self.git.list_worktrees(non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
                if any(item.path == worktree for item in remaining):
                    raise
                on_deferred(exc)
                if not self.recorded_removal_failure(state, worktree):
                    raise
                self.git.remove_worktree_residue(worktree)
        if self.git.branch_exists(branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS):
            if not self.git.branch_is_merged(branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS):
                raise PipelineError("shared run branch is not contained in Main")
            self.git.delete_branch(branch, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS)
        run_root = self.layout.run_root(state)
        if run_root.is_dir() and not any(run_root.iterdir()):
            run_root.rmdir()
