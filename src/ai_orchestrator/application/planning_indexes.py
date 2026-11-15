"""Own one-use handoff of explicitly refreshed planning source indexes."""

from __future__ import annotations

import threading
from pathlib import Path

from ..document_index import PlanningSourceIndex


class PreparedPlanningIndexes:
    def __init__(self) -> None:
        self._indexes: dict[tuple[str, str], PlanningSourceIndex] = {}
        self._lock = threading.Lock()

    def remember(self, project_name: str, index: PlanningSourceIndex) -> None:
        token_key = (project_name, str(Path(index.source_root).resolve()))
        with self._lock:
            self._indexes[token_key] = index

    def consume(self, project_name: str, spec_path: str | Path, generated_at: str) -> PlanningSourceIndex | None:
        raw_spec_path = str(spec_path).strip()
        issued_index = None
        if raw_spec_path:
            token_key = (project_name, str(Path(raw_spec_path).expanduser().resolve()))
            with self._lock:
                issued_index = self._indexes.pop(token_key, None)
        return issued_index if issued_index is not None and generated_at == issued_index.generated_at else None
