"""Isolated conflict candidate construction and evidence checks."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, ContextManager, Protocol

from ..codex_sdk import CodexSdkProgress
from ..config import AgentConfig
from ..errors import PipelineError
from ..git import GitError, GitWorkspace, LOCAL_GIT_TIMEOUT_SECONDS
from ..models import IntegrationConflict, IntegrationConflictFile, OperationRecord, RunState, utc_now
from ..progress import advance_progress_observation
from ..usage import UsageContext
from .conflicts import conflict_resolution_prompt, integration_conflict_fingerprint


@dataclass(frozen=True, slots=True)
class ConflictResolutionProfile:
    agent: AgentConfig
    model: str
    reasoning_effort: str


@dataclass(frozen=True, slots=True)
class ConflictCandidateEvidence:
    commit: str
    content_digest: str
    allowed_paths: set[str]
    output: str


class ConflictCandidateInvocation(Protocol):
    def __call__(
        self, *, agent: AgentConfig, command_template: tuple[str, ...], replacements: dict[str, str],
        cwd: Path, prompt: str, prompt_path: str, log_path: Path, action: str, usage_context: UsageContext,
        task_id: str, model: str, reasoning_effort: str, progress_callback: Callable[[CodexSdkProgress], None] | None,
        attempt_id: str, invocation_id: str,
    ) -> str: ...


def candidate_content_digest(
    git: GitWorkspace, worktree: Path, commit: str, files: list[IntegrationConflictFile]
) -> str:
    values: list[tuple[str, str]] = []
    for item in files:
        blob = git.blob_at(
            worktree, commit, item.path, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
        )
        values.append((item.path, blob))
    return hashlib.sha256(json.dumps(values, ensure_ascii=False).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ConflictCandidateBuilder:
    git: GitWorkspace
    run_directory: Callable[[str], Path]
    prepare_command: Callable[[AgentConfig, str, str], tuple[str, ...]]
    invoke: ConflictCandidateInvocation
    progress_lock: ContextManager[object]
    save_operation: Callable[[OperationRecord], None]

    def build(
        self, state: RunState, conflict: IntegrationConflict, operation: OperationRecord, *,
        candidate_worktree: Path, normalized_request_id: str, agent: AgentConfig, selected_model: str, selected_effort: str,
    ) -> ConflictCandidateEvidence:
        self.git.prepare_detached_worktree(
            candidate_worktree, conflict.work_head, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
        )
        try:
            self.git.merge_into(
                candidate_worktree,
                conflict.main_head,
                f"merge({state.id}): resolve latest main conflict",
                non_interactive=True,
                timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
            )
        except GitError:
            reproduced = self.git.unmerged_entries(
                candidate_worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
            )
            reproduced_fingerprint = integration_conflict_fingerprint(
                conflict.main_head,
                conflict.work_head,
                [
                    IntegrationConflictFile(
                        path=item.path,
                        kind=item.kind,
                        base_blob=item.base_blob,
                        work_blob=item.work_blob,
                        main_blob=item.main_blob,
                        base_mode=item.base_mode,
                        work_mode=item.work_mode,
                        main_mode=item.main_mode,
                        binary=item.binary,
                        supported=item.supported,
                    )
                    for item in reproduced
                ],
            )
            if reproduced_fingerprint != conflict.fingerprint:
                raise PipelineError("충돌을 동일하게 재현하지 못했습니다. 최신 snapshot을 다시 확인하세요.")
        else:
            raise PipelineError("후보 작업공간에서 충돌이 재현되지 않아 기존 snapshot이 stale 상태입니다.")

        prompt_path = self.run_directory(state.id) / "prompts" / f"conflict-{normalized_request_id}.md"
        log_path = self.run_directory(state.id) / "logs" / f"conflict-{normalized_request_id}.log"
        prompt = conflict_resolution_prompt(state, conflict)
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt, encoding="utf-8")
        command_template = self.prepare_command(agent, selected_model, selected_effort)
        operation.update("generating")
        self.save_operation(operation)
        invocation_id = str(uuid.uuid4())

        def report(progress: CodexSdkProgress) -> None:
            if progress.attempt_id != normalized_request_id or progress.invocation_id != invocation_id:
                raise PipelineError("충돌 해결 활동 이벤트가 현재 요청과 일치하지 않습니다.")
            with self.progress_lock:
                received_at = progress.received_at or utc_now()
                previous_received_at = (
                    operation.progress_observation.last_event_received_at if operation.progress_observation else ""
                )
                operation.progress_observation = advance_progress_observation(
                    operation.progress_observation,
                    attempt_id=normalized_request_id,
                    invocation_id=invocation_id,
                    turn_id=progress.turn_id,
                    phase=progress.phase,
                    detail=progress.detail,
                    received_at=received_at,
                    event_seq=progress.event_seq,
                    activity_changed=progress.activity_changed,
                    evidence_kind=progress.evidence_kind,
                )
                if operation.progress_observation.evidence_kind != "provider_event" or previous_received_at != received_at:
                    self.save_operation(operation)

        output = self.invoke(
            agent=agent,
            command_template=command_template,
            replacements={
                "{worktree}": str(candidate_worktree),
                "{prompt}": str(prompt_path),
                "{task_id}": "conflict-resolution",
                "{run_id}": state.id,
            },
            cwd=candidate_worktree,
            prompt=prompt,
            prompt_path=str(prompt_path),
            log_path=log_path,
            action="conflict_resolution",
            usage_context=UsageContext(state.id, "conflict_resolution", operation_request_id=normalized_request_id),
            task_id="conflict-resolution",
            model=selected_model,
            reasoning_effort=selected_effort,
            progress_callback=report if agent.provider_id == "codex" else None,
            attempt_id=normalized_request_id,
            invocation_id=invocation_id,
        )
        operation.update("checking_candidate")
        self.save_operation(operation)
        allowed_paths = {item.path for item in conflict.files}
        pending_paths = set(self.git.pending_worktree_paths(
            candidate_worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
        ))
        outside = sorted(pending_paths - allowed_paths)
        if outside:
            raise PipelineError("AI 해결안이 허용된 충돌 파일 밖을 변경했습니다: " + ", ".join(outside))
        for item in conflict.files:
            selected = candidate_worktree.joinpath(*PurePosixPath(item.path).parts).resolve()
            if not selected.is_relative_to(candidate_worktree.resolve()) or not selected.is_file():
                raise PipelineError(f"해결안 파일이 없거나 작업공간 경계를 벗어났습니다: {item.path}")
            content = selected.read_text(encoding="utf-8")
            if any(marker in content for marker in ("<<<<<<<", "=======", ">>>>>>>")):
                raise PipelineError(f"해결되지 않은 충돌 표식이 남아 있습니다: {item.path}")
        self.git.stage_paths(
            candidate_worktree, sorted(allowed_paths), non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
        )
        if self.git.unmerged_entries(candidate_worktree, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS):
            raise PipelineError("후보 index에 해결되지 않은 충돌이 남아 있습니다.")
        commit = self.git.commit_merge(
            candidate_worktree,
            f"resolve({state.id}): integrate latest main",
            non_interactive=True,
            timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS,
        )
        if self.git.commit_parents(
            candidate_worktree, commit, non_interactive=True, timeout_seconds=LOCAL_GIT_TIMEOUT_SECONDS
        ) != [conflict.work_head, conflict.main_head]:
            raise PipelineError("해결안 commit의 부모가 고정한 작업/Main commit과 일치하지 않습니다.")
        digest = candidate_content_digest(self.git, candidate_worktree, commit, conflict.files)
        return ConflictCandidateEvidence(commit, digest, allowed_paths, output)
