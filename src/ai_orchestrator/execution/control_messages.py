"""ExecutionMessages with explicit feature and persistence dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, ContextManager
from ..models import RunState
from ..persistence.execution_records import ExecutionMessagesRecords
from ..planning.messages import PlanningMessages


@dataclass
class ExecutionMessages:
    records: ExecutionMessagesRecords
    planning_messages: PlanningMessages

    def record(self, run_id: str, message: str, response: str) -> RunState:
        with self.records.planning_chat_lock(run_id):
            state = self.records.load(run_id)
            if message:
                self.planning_messages.append_user(state, message, counts_as_discussion=False)
            self.planning_messages.append_assistant(state, response, counts_as_discussion=False)
            state.add_event("planning", "explicit execution command received through chat")
            self.records.save_planning_chat(state)
            return state
