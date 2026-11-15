"""Recovery receipts with caller-owned Git and planning scope."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from ..config import AgentConfig
from ..errors import PipelineError
from ..git import GitError
from ..models import OperationRecord, RunState, TaskAction, TaskStatus


class RecoveryOperationClaim(Protocol):
    def __call__(
        self,
        state: RunState,
        action: str,
        request_id: str,
        payload: dict[str, object],
        phase: str,
        *,
        resume_request_id: str = "",
    ) -> tuple[OperationRecord, bool]:
        ...


class RecoveryPlanningProfile(Protocol):
    def __call__(
        self, state: RunState, *, planning_agent_id: str | None, planning_model: str | None, planning_reasoning_effort: str | None,
    ) -> AgentConfig: ...


@dataclass(frozen=True, slots=True)
class RecoveryApplyRecords:
    load_run: Callable[[str], RunState]
    save_state: Callable[[RunState], None]
    save_chat: Callable[[RunState], None]
    save_operation: Callable[[OperationRecord], None]
    save_result: Callable[[str, str, dict[str, object]], str]


@dataclass(frozen=True, slots=True)
class RecoveryApplication:
    records: RecoveryApplyRecords
    claim_operation: RecoveryOperationClaim
    raise_existing: Callable[[OperationRecord], None]
    resume_replanning: Callable[[RunState, OperationRecord, str, list[str]], str]
    recovery_plan: Callable[[RunState], dict[str, object]]
    configure_profile: RecoveryPlanningProfile
    shared_boundary: Callable[[RunState], tuple[str, Path]]
    recover_commits: Callable[[Path, str, list[str]], str]
    append_user: Callable[[RunState, str], None]
    replan: Callable[[RunState], RunState]
    fail_operation: Callable[[OperationRecord, Exception], None]

    def apply(
        self, run_id: str, fingerprint: str, source_ids: list[str], *, request_id: str = "", resume_request_id: str = "",
    ) -> RunState:
        state = self.records.load_run(run_id)
        operation_input = {
            "fingerprint": fingerprint,
            "source_ids": list(dict.fromkeys(source_ids)),
            "resume_request_id": resume_request_id,
        }
        operation, created = self.claim_operation(
            state,
            "recovery_apply",
            request_id,
            operation_input,
            "validating_plan",
            resume_request_id=resume_request_id,
        )
        if not created:
            if operation.status == "succeeded":
                return state
            self.raise_existing(operation)
        try:
            if resume_request_id:
                integrated = self.resume_replanning(state, operation, fingerprint, source_ids)
            else:
                operation.update("validating_plan")
                self.records.save_operation(operation)
                plan = self.recovery_plan(state)
                if plan["fingerprint"] != fingerprint:
                    raise PipelineError("작업 상태나 복구 후보가 변경됐습니다. 복구안을 다시 생성하세요.")
                sources = {source["run_id"]: source for source in plan["sources"]}
                if not set(source_ids) <= sources.keys():
                    raise PipelineError("확인하지 않은 복구 후보가 포함돼 있습니다.")
                self.configure_profile(state, planning_agent_id=None, planning_model=None, planning_reasoning_effort=None)
                selected = [sources[source_id] for source_id in dict.fromkeys(source_ids)]
                commits = list(dict.fromkeys(commit for source in selected for commit in source["commits"]))
                _, worktree = self.shared_boundary(state)
                operation.update("integrating_commits")
                self.records.save_operation(operation)
                try:
                    integrated = self.recover_commits(worktree, str(plan["baseline"]), commits)
                except GitError as exc:
                    state.add_event("planning", f"복구 commit 통합 실패: {exc}")
                    self.records.save_state(state)
                    self.records.save_chat(state)
                    raise
                operation.result_commit = integrated
                operation.result_ref = self.records.save_result(
                    state.id,
                    operation.request_id,
                    {
                        "fingerprint": fingerprint,
                        "source_ids": list(dict.fromkeys(source_ids)),
                        "result_commit": integrated,
                    },
                )
                operation.update("replanning")
                self.records.save_operation(operation)
                state.add_event("planning", f"복구 기준선 통합: {plan['baseline']} -> {integrated}; commits={','.join(commits)}")
                for task in state.tasks:
                    if task.status in {TaskStatus.PENDING, TaskStatus.FAILED}:
                        task.started_commit = integrated
                        if task.status == TaskStatus.FAILED:
                            task.failed_action = TaskAction.EXECUTE
                instruction = (
                    f"현재 그룹을 복구하세요. 실제 코드 확인은 {worktree} 작업공간의 {integrated} commit을 기준으로 수행하세요. "
                    "아래 완료 commit은 해당 작업공간에 통합됐습니다. "
                    "실패한 Task의 응답과 선택한 원래 그룹의 미완료 Task를 참고해 누락된 선행 구현을 "
                    "같은 그룹의 Task로 추가하고 의존 순서와 실제 필요한 허용 경로를 수정하세요. "
                    "이미 구현된 기능을 중복 구현하도록 요구하지 마세요. 완료 Task와 실행 이력은 보존하세요.\n"
                    + json.dumps({"selected_sources": selected, "failures": plan["failed_tasks"]}, ensure_ascii=False)
                )
                self.append_user(state, instruction)
                state.planning_follow_up_requests.append(instruction)
                self.records.save_state(state)
                self.records.save_chat(state)
            operation.update("replanning")
            self.records.save_operation(operation)
            updated = self.replan(state)
            operation.result_commit = integrated
            operation.result_revision = updated.plan_revision
            operation.update("completed", status="succeeded")
            self.records.save_operation(operation)
            return updated
        except Exception as exc:
            if operation.result_commit and operation.phase == "replanning":
                operation.update("replanning", status="partial", error=str(exc), error_code="replanning_failed")
                self.records.save_operation(operation)
                raise PipelineError(
                    f"복구 commit 통합은 완료됐지만 Task 재계획에 실패했습니다. 기준선 {operation.result_commit}; "
                    f"적용 대기 요청은 보존했습니다: {exc}"
                ) from exc
            self.fail_operation(operation, exc)
            raise
