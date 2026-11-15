"""Generate result revisions with borrowed SDK conversation cleanup."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Callable
from ..codex_sdk import CodexSdkManager
from ..execution.provider_commands import agent_command
from ..models import RunState
from ..planning import result_revision_evidence, parse_result_revision_proposal, result_revision_available_paths
from .result_revisions import ResultRevisionProposalPreparation
from ..usage import UsageContext


@dataclass
class ResultRevisionAI:
    preparation: Callable[[], ResultRevisionProposalPreparation]
    invoke_provider: Callable[..., str]
    sdk: Callable[[], CodexSdkManager | None]
    timeout: Callable[[], int]

    def generate(
        self, state: RunState, text: str, focus_task_id: str, proposal_id: str
    ) -> dict[str, object]:
        prepared = self.preparation().prepare(state, text, focus_task_id, proposal_id)
        try:
            output = self.invoke_provider(
                agent=prepared.agent, command_template=agent_command(prepared.agent, "review"),
                replacements={"{worktree}": str(prepared.artifact_root), "{prompt}": str(prepared.prompt_path),
                              "{task_id}": "result-revision", "{run_id}": state.id},
                cwd=prepared.artifact_root, prompt=prepared.prompt, prompt_path=str(prepared.prompt_path), log_path=prepared.log_path,
                action="review", task_id="result-revision", timeout_seconds=self.timeout(),
                model=state.planning_model or prepared.agent.model, reasoning_effort=state.planning_reasoning_effort,
                sdk_conversation_id=prepared.conversation_id,
                usage_context=UsageContext(state.id, "result_revision", operation_request_id=proposal_id),
            )
        finally:
            if self.sdk() is not None:
                self.sdk().close_conversation(prepared.conversation_id)
        return self.parse(state, output)

    @classmethod
    def fingerprint(cls, state: RunState) -> str:
        evidence = result_revision_evidence(state)
        return hashlib.sha256(json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    def parse(self, state: RunState, output: str) -> dict[str, object]:
        return parse_result_revision_proposal(state, output, available_paths=result_revision_available_paths)
