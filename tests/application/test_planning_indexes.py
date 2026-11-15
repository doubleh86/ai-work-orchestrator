from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock

from ai_orchestrator.application.planning_indexes import PreparedPlanningIndexes


def test_stale_token_consumes_only_its_project_and_blank_input_preserves_the_handoff(tmp_path: Path) -> None:
    source = tmp_path / "planning"
    first = Mock(source_root=str(source), generated_at="first-revision")
    second = Mock(source_root=str(source), generated_at="second-revision")
    indexes = PreparedPlanningIndexes()
    indexes.remember("first", first)
    indexes.remember("second", second)

    assert indexes.consume("first", "   ", "first-revision") is None
    assert indexes.consume("first", source, "first-revision") is first
    indexes.remember("first", first)
    assert indexes.consume("first", source, "stale-revision") is None
    assert indexes.consume("first", source, "first-revision") is None
    assert indexes.consume("second", str(source) + "/./", "second-revision") is second


def test_latest_refreshed_index_can_be_consumed_by_only_one_concurrent_request(tmp_path: Path) -> None:
    source = tmp_path / "planning"
    previous = Mock(source_root=str(source), generated_at="old")
    current = Mock(source_root=str(source), generated_at="new")
    indexes = PreparedPlanningIndexes()
    indexes.remember("project", previous)
    indexes.remember("project", current)
    start = Barrier(2)

    def consume():
        start.wait(timeout=2)
        return indexes.consume("project", source, "new")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(consume) for _ in range(2)]
        results = [future.result(timeout=3) for future in futures]
    assert sum(result is current for result in results) == 1
    assert sum(result is None for result in results) == 1
