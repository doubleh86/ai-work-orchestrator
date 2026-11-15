from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from ..errors import PipelineError
from ..git import GitError, GitWorkspace
from ..models import (
    MainChangeDiff,
    MainChangeItem,
    MainChangeSnapshot,
    MainMutationResult,
    MainSyncStatus,
    utc_now,
)


@dataclass(frozen=True, slots=True)
class MainChangeService:
    git: GitWorkspace
    repo: Path
    remote: str
    main_branch: str
    managed_roots: tuple[Path, ...]
    save_snapshot: Callable[[str, dict[str, object]], None]
    load_snapshot: Callable[[str], dict[str, object] | None]

    def snapshot(self, *, remote_checked: bool, remote_error: str = "") -> MainChangeSnapshot:
        state = self.git.main_change_state(excluded_roots=self.managed_roots)
        relation, ahead, behind, remote_head = self.git.main_remote_relation(self.remote)
        if remote_error:
            relation, ahead, behind, remote_head = "unknown", None, None, ""
        sync = MainSyncStatus(
            local_head=state.head,
            remote_head=remote_head,
            remote=self.remote,
            target_branch=self.main_branch,
            relation=relation,
            ahead=ahead,
            behind=behind,
            checked_at=utc_now() if remote_checked else "",
            error=remote_error,
        )
        changes = tuple(
            MainChangeItem(
                item.path,
                item.status,
                item.staged,
                item.unstaged,
                item.staged_status,
                item.unstaged_status,
                item.original_path,
            )
            for item in state.changes
        )
        blocked_reason = ""
        if state.branch != self.main_branch:
            blocked_reason = f"현재 branch가 {state.branch or 'detached HEAD'}입니다. {self.main_branch}에서 다시 확인해 주세요."
        elif any(item.status == "conflicted" or item.staged_status == "conflicted" or item.unstaged_status == "conflicted" for item in changes):
            blocked_reason = "해결되지 않은 Git 충돌이 있어 선택 커밋을 진행할 수 없습니다."
        payload: dict[str, object] = {
            "head": state.head,
            "branch": state.branch,
            "index_tree": state.index_tree,
            "content_digest": state.content_digest,
            "changes": [asdict(item) for item in changes],
            "excluded_count": state.excluded_count,
        }
        snapshot_id = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        self.save_snapshot(snapshot_id, payload)
        return MainChangeSnapshot(
            snapshot_id,
            str(self.repo),
            state.branch,
            self.main_branch,
            changes,
            state.excluded_count,
            sync,
            blocked_reason,
        )

    def require_snapshot(self, snapshot_id: str) -> MainChangeSnapshot:
        saved = self.load_snapshot(snapshot_id)
        if saved is None:
            raise PipelineError("Main 변경 검토 기록을 찾을 수 없습니다. 변경 내용을 다시 확인해 주세요.")
        current = self.snapshot(remote_checked=False)
        if current.snapshot_id != snapshot_id:
            raise PipelineError("검토 후 Main의 HEAD, index 또는 파일 내용이 변경되었습니다. 변경 내용을 다시 확인해 주세요.")
        return current

    @staticmethod
    def validated_selections(
        snapshot: MainChangeSnapshot, selections: list[tuple[str, str]]
    ) -> list[tuple[str, str, str]]:
        if not selections:
            raise PipelineError("커밋할 변경을 하나 이상 선택해 주세요.")
        available = {item.path: item for item in snapshot.changes}
        validated: list[tuple[str, str, str]] = []
        seen: set[str] = set()
        for path, mode in selections:
            item = available.get(path)
            if item is None or path in seen:
                raise PipelineError("검토하지 않았거나 중복된 Main 변경이 선택되었습니다.")
            if mode not in {"staged", "whole"} or (mode == "staged" and not item.staged):
                raise PipelineError("선택한 Main 변경 범위가 현재 staging 상태와 일치하지 않습니다.")
            seen.add(path)
            validated.append((path, mode, item.original_path))
        return validated

    @staticmethod
    def safe_remote_error(error: GitError) -> str:
        detail = str(error).casefold()
        if "non-fast-forward" in detail or "rejected" in detail:
            return "원격 branch가 변경되어 Push가 거절되었습니다. 원격 상태를 다시 확인해 주세요."
        if "authentication" in detail or "permission denied" in detail or "access denied" in detail:
            return "원격 저장소 인증 또는 권한 확인에 실패했습니다."
        if "timed out" in detail or "timeout" in detail:
            return "원격 저장소 확인 시간이 초과되었습니다."
        return "원격 저장소에 연결하거나 branch를 확인하지 못했습니다. backend 로그를 확인해 주세요."

    def diff(self, snapshot_id: str, path: str, mode: str) -> MainChangeDiff:
        snapshot = self.require_snapshot(snapshot_id)
        change = next((item for item in snapshot.changes if item.path == path), None)
        if change is None:
            raise PipelineError("선택한 파일이 Main 변경 snapshot에 없습니다.")
        if mode == "staged" and not change.staged:
            raise PipelineError("선택한 파일에는 staging된 변경이 없습니다.")
        content, binary, truncated = self.git.main_change_diff(path, mode)
        return MainChangeDiff(snapshot_id, path, mode, content, binary, truncated)

    def commit(self, snapshot_id: str, selections: list[tuple[str, str]], message: str) -> MainMutationResult:
        snapshot = self.require_snapshot(snapshot_id)
        if snapshot.blocked_reason:
            raise PipelineError(snapshot.blocked_reason)
        selected = self.validated_selections(snapshot, selections)
        commit = self.git.commit_main_changes(selected, message)
        current = self.snapshot(remote_checked=False)
        return MainMutationResult("commit_completed", commit, True, False, len(current.changes), current)

    def push(self, snapshot_id: str) -> MainMutationResult:
        snapshot = self.require_snapshot(snapshot_id)
        if snapshot.branch != snapshot.expected_branch:
            raise PipelineError("등록된 Main branch가 아니므로 Push할 수 없습니다.")
        if snapshot.sync.behind:
            raise PipelineError("원격에도 새 commit이 있어 먼저 통합해야 합니다.")
        if snapshot.sync.ahead is None:
            raise PipelineError("원격 상태를 먼저 확인한 뒤 Push해 주세요.")
        if not snapshot.sync.ahead:
            raise PipelineError("원격에 보낼 Main commit이 없습니다.")
        commit = snapshot.sync.local_head
        try:
            self.git.push_main_commit(self.remote, commit)
            self.git.refresh_main_remote(self.remote)
            current = self.snapshot(remote_checked=True)
            return MainMutationResult("push_completed", commit, False, True, len(current.changes), current)
        except GitError as exc:
            current = self.snapshot(remote_checked=False)
            return MainMutationResult(
                "push_failed", commit, False, False, len(current.changes), current, self.safe_remote_error(exc)
            )

    def commit_and_push(self, snapshot_id: str, selections: list[tuple[str, str]], message: str) -> MainMutationResult:
        snapshot = self.require_snapshot(snapshot_id)
        if snapshot.blocked_reason:
            raise PipelineError(snapshot.blocked_reason)
        if snapshot.sync.behind:
            raise PipelineError("원격에도 새 commit이 있어 먼저 통합해야 합니다.")
        if snapshot.sync.ahead is None:
            raise PipelineError("원격 상태를 먼저 확인한 뒤 커밋·Push해 주세요.")
        selected = self.validated_selections(snapshot, selections)
        commit = self.git.commit_main_changes(selected, message)
        try:
            self.git.push_main_commit(self.remote, commit)
            self.git.refresh_main_remote(self.remote)
            current = self.snapshot(remote_checked=True)
            return MainMutationResult("push_completed", commit, True, True, len(current.changes), current)
        except GitError as exc:
            current = self.snapshot(remote_checked=False)
            return MainMutationResult(
                "push_failed", commit, True, False, len(current.changes), current, self.safe_remote_error(exc)
            )
