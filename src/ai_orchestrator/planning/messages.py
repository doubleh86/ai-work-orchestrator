"""Planning messages, follow-up text and channel eligibility."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from .conversation import planning_message_is_apply_control
from ..models import PlanningMessage, PlanningMessageRole, RunLockState, RunLockStatus, RunState, Stage


@dataclass
class PlanningMessages:
    run_directory: Callable[[str], Path]
    inspect_lock: Callable[[str], RunLockStatus]
    execution_operations: frozenset[str]

    def append_user(self, state: RunState, message: str, *, counts_as_discussion: bool = True) -> None:
        clarification_dir = self.run_directory(state.id) / "clarifications"
        clarification_dir.mkdir(parents=True, exist_ok=True)
        clarification_path = clarification_dir / f"clarification-{len(state.clarification_paths) + 1}.md"
        clarification_path.write_text(message, encoding="utf-8")
        state.clarification_paths.append(str(clarification_path))
        state.planning_messages.append(PlanningMessage(role=PlanningMessageRole.USER, text=message))
        if counts_as_discussion:
            state.planning_conversation_revision += 1

    @staticmethod
    def append_assistant(state: RunState, message: str, *, counts_as_discussion: bool = True) -> None:
        state.planning_messages.append(PlanningMessage(role=PlanningMessageRole.ASSISTANT, text=message))
        if counts_as_discussion:
            state.planning_conversation_revision += 1

    def execution_available(self, state: RunState) -> bool:
        if state.stage in {Stage.EXECUTING, Stage.FAILED, Stage.READY_TO_MERGE}:
            return True
        if state.stage != Stage.PLANNED:
            return False
        lock = self.inspect_lock(state.id)
        return lock.state == RunLockState.ACTIVE and lock.operation in self.execution_operations

    @staticmethod
    def result_available(state: RunState) -> bool:
        return state.stage in {Stage.VERIFIED, Stage.WORK_BRANCH_PUSHED, Stage.MERGED, Stage.PUSHED, Stage.DEPLOYED}

    @staticmethod
    def follow_up(state: RunState) -> str:
        transcript = "\n\n".join(
            ("사용자" if item.role == PlanningMessageRole.USER else "Planning AI") + ": " + item.text.strip()
            for item in state.planning_messages[-12:]
            if item.text.strip()
            and not (
                item.role == PlanningMessageRole.USER
                and planning_message_is_apply_control(item.text)
            )
        )
        return (
            "다음 Planning 대화에서 결정한 내용을 현재 작업 그룹의 미실행·실패 Task에 "
            "반영해 주세요. 완료 결과는 보존하고 추가 요구는 같은 그룹의 새 Task로 계획하세요."
            + (f"\n\n참고 대화:\n\n{transcript}" if transcript else "")
        )
