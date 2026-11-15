"""Own concurrent project summary queries and their pending work."""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor, wait
from typing import Callable, Literal, Sequence

from ..models import utc_now


SummaryKind = Literal["active_groups", "attention_items", "user_checks"]
ProjectQuery = Callable[[str], list[dict[str, object]]]


class ProjectSummaryQueries:
    def __init__(self, project_names: Callable[[str], Sequence[str]]):
        self._project_names = project_names
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="active-group-query")
        self._pending: dict[SummaryKind, dict[str, Future[list[dict[str, object]]]]] = {
            "active_groups": {}, "attention_items": {}, "user_checks": {},
        }
        self._lock = threading.Lock()

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def snapshot(
        self, kind: SummaryKind, query: ProjectQuery, sort_field: str, project_name: str = "",
    ) -> dict[str, object]:
        cached = self._pending[kind]
        checked_at = utc_now()
        futures: dict[str, Future[list[dict[str, object]]]] = {}
        projects = self._project_names(project_name)
        with self._lock:
            for name in projects:
                future = cached.get(name)
                if future is None or future.done():
                    future = self._executor.submit(query, name)
                    cached[name] = future
                futures[name] = future
        completed, _ = wait(set(futures.values()), timeout=5)
        items: list[dict[str, object]] = []
        errors: list[dict[str, str]] = []
        for project_name, future in futures.items():
            if future not in completed:
                errors.append({"project_name": project_name, "error": "프로젝트 상태 조회 시간이 초과됐습니다.", "checked_at": checked_at})
                continue
            try:
                items.extend({"project_name": project_name, **item} for item in future.result())
            except Exception as exc:
                errors.append({"project_name": project_name, "error": str(exc), "checked_at": checked_at})
            finally:
                with self._lock:
                    if cached.get(project_name) is future:
                        del cached[project_name]
        items.sort(key=lambda item: str(item[sort_field]), reverse=True)
        return {"items": items, "errors": errors, "checked_at": checked_at}
