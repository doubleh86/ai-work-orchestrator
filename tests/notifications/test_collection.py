from unittest.mock import Mock

import pytest

from ai_orchestrator.errors import PipelineError
from ai_orchestrator.notifications import NotificationCollector


@pytest.mark.parametrize("limit", [0, 501])
def test_invalid_limit_is_rejected_before_reading_project_or_run_state(limit: int) -> None:
    read = Mock(side_effect=AssertionError("invalid query must not read state"))
    collector = NotificationCollector(read, read, read, read)

    with pytest.raises(PipelineError, match="notification limit"):
        collector.page(limit=limit)

    read.assert_not_called()


def test_run_read_failure_is_not_reported_as_an_empty_inbox() -> None:
    error = OSError("run storage unavailable")
    collector = NotificationCollector(lambda: "repo", lambda: False, Mock(side_effect=error), Mock())

    with pytest.raises(OSError) as caught:
        collector.page()

    assert caught.value is error
