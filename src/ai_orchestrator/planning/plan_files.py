"""Read and write plans through an explicit run-directory port."""

from __future__ import annotations

from ..planning.conversation import task_plan_draft

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from ..errors import PipelineError
from ..models import RunState
from .contracts import Plan
from .conversation import task_plan_draft
from .protocol import structured_plan_dict


@dataclass(frozen=True, slots=True)
class PlanFiles:
    run_directory: Callable[[str], Path]

    def result_paths(self, state: RunState) -> tuple[list[str], list[str]]:
        if not state.structured_plan_path:
            return [], []
        result_path = Path(state.structured_plan_path)
        if not result_path.is_file():
            raise PipelineError(f"stored task plan not found: {result_path}")
        try:
            raw = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PipelineError(f"stored task plan is unreadable: {result_path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise PipelineError(f"stored task plan must be an object: {result_path}")
        return (
            self.stored_path_values(raw, "source_paths", result_path),
            self.stored_path_values(raw, "instruction_paths", result_path),
        )

    @staticmethod
    def stored_path_values(raw: dict[str, object], name: str, result_path: Path) -> list[str]:
        value = raw.get(name, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise PipelineError(f"stored task plan {name} is invalid: {result_path}")
        return list(value)

    def write_result(self, state: RunState, plan: Plan) -> None:
        result_path = self.run_directory(state.id) / "plan.json"
        result = structured_plan_dict(plan)
        if state.user_check_plan:
            result["user_checks"] = [asdict(check) for check in state.user_check_plan]
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        state.structured_plan_path = str(result_path)

    def refresh_tasks(self, state: RunState) -> None:
        if not state.structured_plan_path:
            return
        result_path = Path(state.structured_plan_path)
        try:
            raw = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PipelineError(f"stored task plan is unreadable: {result_path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise PipelineError(f"stored task plan must be an object: {result_path}")
        raw["tasks"] = [task_plan_draft(task) for task in state.tasks]
        result_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
