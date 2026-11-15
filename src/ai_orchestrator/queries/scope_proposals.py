"""Read the exact failed-task scope proposal and chat fingerprint."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..models import ExecutionControlRecord, RunState, RunStep, Stage, TaskStatus
from ..planning.conversation import task_plan_draft
from ..planning.validation import task_path_matches
from ..task_scope_review import scope_approval_paths
from ..execution import task_scope_review, scope_contract_digest


@dataclass(frozen=True, slots=True)
class ScopeProposalQueries:
    repository: Callable[[], Path]
    load_control: Callable[[str], ExecutionControlRecord | None]

    def fingerprint(self, state: RunState) -> str:
        execution = self.load_control(state.id)
        value = {
            "repo": str(self.repository().resolve()), "run": state.id, "goal": state.spec_digest, "summary": state.summary,
            "plan": state.plan_revision, "conversation": state.planning_conversation_revision,
            "stage": state.stage.value, "failed_step": state.failed_step, "archive": bool(state.archive),
            "execution": execution.execution_id if execution else "",
            "stop_request": execution.stop_request_id if execution else "",
            "tasks": [{**task_plan_draft(task), "status": task.status.value, "attempt": task.last_attempt_id,
                       "invocation": task.active_invocation_id, "active_action": task.active_action,
                       "notes": task.implementation_notes} for task in state.tasks],
        }
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def proposal(self, state: RunState, task_id: str = "") -> dict[str, object] | None:
        if (state.archive or state.stage != Stage.FAILED or state.failed_step != RunStep.AGENT_EXECUTION or state.active_step
                or any(task.active_action or task.status in {TaskStatus.RUNNING, TaskStatus.REVIEWING, TaskStatus.REVISING}
                       for task in state.tasks)):
            return None
        failed = [task for task in state.tasks if task.status in {TaskStatus.FAILED, TaskStatus.STOPPED, TaskStatus.WAITING}]
        if len(failed) != 1 or task_id and failed[0].id != task_id:
            return None
        task = failed[0]
        review = task_scope_review(task)
        if review is None or not review.paths:
            return None
        try:
            candidates = scope_approval_paths(review.paths)
        except ValueError:
            return None
        if any(any(task_path_matches(path, rule) for rule in task.forbidden_paths) for path in candidates):
            return None
        paths = [path for path in candidates if task.expected_paths
                 and not any(task_path_matches(path, rule) for rule in task.expected_paths)]
        if not paths:
            return None
        return {"task_id": task.id, "paths": paths, "contract": scope_contract_digest(task),
                "attempt_id": task.last_attempt_id, "plan_revision": state.plan_revision,
                "fingerprint": self.fingerprint(state)}
