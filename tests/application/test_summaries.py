from concurrent.futures import wait
from threading import Event, Lock
from types import SimpleNamespace
from unittest.mock import Mock, patch

from ai_orchestrator.application import OrchestratorApplication


def test_selected_project_checks_do_not_reuse_another_query_kinds_pending_work() -> None:
    registry = Mock()
    registry.list.return_value = [SimpleNamespace(name="first"), SimpleNamespace(name="second")]
    registry.get.return_value = SimpleNamespace(name="second")
    application = OrchestratorApplication(registry, codex_sdk=Mock())
    release = Event()

    def attention(project_name: str) -> list[dict[str, object]]:
        if project_name == "second":
            assert release.wait(3)
        return []

    try:
        with (
            patch.object(application, "_attention_items_for_project", side_effect=attention) as pending,
            patch.object(application, "_user_checks_for_project", return_value=[{"run_id": "check", "updated_at": "now"}]) as checks,
            patch("ai_orchestrator.application.summaries.wait", side_effect=lambda futures, timeout: wait(futures, timeout=0.1)),
        ):
            first = application.attention_items()
            selected = application.user_check_items("second")
            second = application.attention_items()
        assert [item["project_name"] for item in first["errors"]] == ["second"]
        assert [item["project_name"] for item in second["errors"]] == ["second"]
        assert [call.args[0] for call in pending.call_args_list].count("second") == 1
        assert selected["items"] == [{"project_name": "second", "run_id": "check", "updated_at": "now"}]
        assert selected["errors"] == []
        checks.assert_called_once_with("second")
        registry.get.assert_called_once_with("second")
    finally:
        release.set()
        application.close()


def test_close_cancels_queued_queries_before_sdk_close_without_waiting_for_running_queries() -> None:
    names = [f"project-{index}" for index in range(6)]
    registry = Mock()
    registry.list.return_value = [SimpleNamespace(name=name) for name in names]
    sdk = Mock()
    application = OrchestratorApplication(registry, codex_sdk=sdk)
    release, running = Event(), Event()
    lock = Lock()
    started: list[str] = []
    captured = set()

    def query(project_name: str) -> list[dict[str, object]]:
        with lock:
            started.append(project_name)
            if len(started) == 4:
                running.set()
        assert release.wait(3)
        return []

    def bounded_wait(futures, timeout):
        assert timeout == 5
        assert running.wait(1)
        captured.update(futures)
        return wait(futures, timeout=0)

    def close_sdk() -> None:
        assert sum(future.cancelled() for future in captured) == 2
        assert not release.is_set()

    sdk.close.side_effect = close_sdk
    try:
        with patch.object(application, "_active_groups_for_project", side_effect=query), patch(
            "ai_orchestrator.application.summaries.wait", side_effect=bounded_wait,
        ):
            result = application.active_groups()
            application.close()
        sdk.close.assert_called_once_with()
        assert len(result["errors"]) == 6
        assert set(started) == set(names[:4])
    finally:
        release.set()
        for future in captured:
            if not future.cancelled():
                future.result(timeout=2)
        if not sdk.close.called:
            application.close()
