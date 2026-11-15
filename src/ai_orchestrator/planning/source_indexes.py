"""Planning source index refresh, reuse and run snapshot restoration."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Protocol

from ..document_index import (
    DocumentIndexError, PLANNING_INDEX_TIMEOUT_SECONDS, PlanningSourceIndex,
    load_matching_planning_source_index, load_planning_source_index,
)
from ..errors import PipelineError
from ..git import GitRepositoryReadiness
from ..git import inspect_git_readiness
from ..models import RunState


class SourceIndexRefresh(Protocol):
    def __call__(
        self, source_root: str | Path, state_root: str | Path, repository_root: str | Path, base_commit: str, *,
        candidate_paths: Iterable[str | Path] | None = None, excluded_roots: Iterable[str | Path] = (),
        timeout_seconds: float | None = None,
    ) -> PlanningSourceIndex: ...


def require_planning_git_ready(readiness: GitRepositoryReadiness) -> None:
    if readiness.kind == "ready":
        return
    guidance = {
        "unborn": "프로젝트 등록에서 첫 commit을 만든 뒤 다시 시도하세요.",
        "not_initialized": "프로젝트 등록에서 로컬 Git 저장소를 만든 뒤 첫 commit을 준비하세요.",
        "inside_other_repository": f"감지한 저장소 루트를 프로젝트로 등록하세요: {readiness.repository_root}",
        "git_unavailable": "Git을 설치하거나 실행 경로를 확인한 뒤 다시 시도하세요.",
        "invalid": "프로젝트 저장소 경로와 접근 권한을 확인하세요.",
    }.get(readiness.kind, "프로젝트 Git 상태를 확인하세요.")
    raise PipelineError(f"프로젝트 Git 준비가 필요합니다 ({readiness.kind}). {guidance}")


def ensure_planning_git_ready(repository: Path) -> None:
    require_planning_git_ready(inspect_git_readiness(repository))


@dataclass(frozen=True, slots=True)
class PlanningSourceIndexes:
    repo: Path
    records_root: Path
    run_directory: Callable[[str], Path]
    workspace_root: Callable[[], Path]
    ensure_git_ready: Callable[[], None]
    ensure_repository: Callable[[float], None]
    list_project_files: Callable[[Path, float], list[Path]]
    read_head: Callable[[Path, float], str]
    has_changes: Callable[[Path], bool]
    refresh_source_index: SourceIndexRefresh

    def refresh(self, source_root: str | Path, *, base_commit: str = "") -> PlanningSourceIndex:
        deadline = time.monotonic() + PLANNING_INDEX_TIMEOUT_SECONDS

        def remaining_timeout() -> float:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DocumentIndexError(f"planning document index timed out after {PLANNING_INDEX_TIMEOUT_SECONDS}s")
            return remaining

        self.ensure_git_ready()
        self.ensure_repository(remaining_timeout())
        root = Path(source_root).expanduser().resolve()
        if not root.is_dir():
            raise DocumentIndexError(f"planning source directory not found: {root}")
        repository_root = self.repo.resolve()
        candidate_paths = (
            self.list_project_files(root, remaining_timeout())
            if root.is_relative_to(repository_root)
            else None
        )
        selected_base_commit = base_commit or self.read_head(repository_root, remaining_timeout())
        workspace_root = self.workspace_root()
        return self.refresh_source_index(
            root,
            self.records_root,
            repository_root,
            selected_base_commit,
            candidate_paths=candidate_paths,
            excluded_roots=(workspace_root,),
            timeout_seconds=remaining_timeout(),
        )

    def for_start(self, source_root: str | Path, *, base_commit: str) -> tuple[PlanningSourceIndex, bool]:
        root = Path(source_root).expanduser().resolve()
        repository_root = self.repo.resolve()
        cached = load_matching_planning_source_index(self.records_root, root, repository_root, base_commit)
        if cached is not None and root.is_relative_to(repository_root):
            if not self.has_changes(root):
                return cached, True
        return (self.refresh(root, base_commit=base_commit), False)

    def snapshot(self, state: RunState) -> PlanningSourceIndex | None:
        if not state.spec_path.strip():
            return None
        source_root = Path(state.spec_path).expanduser().resolve()
        if not source_root.is_dir():
            return None
        snapshot_path = self.run_directory(state.id) / "planning-source-index.json"
        if snapshot_path.is_file():
            return load_planning_source_index(snapshot_path)
        return self.refresh(source_root, base_commit=state.base_commit)
