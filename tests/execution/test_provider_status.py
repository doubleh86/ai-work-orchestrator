from pathlib import Path
from unittest.mock import Mock

from ai_orchestrator.config import AgentConfig, Config, ExecutionConfig, ProjectConfig
from ai_orchestrator.pipeline import Pipeline


def test_status_probes_keep_review_fallback_and_skip_missing_sdk_or_commands(tmp_path: Path, monkeypatch) -> None:
    pipeline = Pipeline(Config(
        path=tmp_path / "config.toml", project=ProjectConfig(repo=tmp_path), execution=ExecutionConfig(), agents=(
            AgentConfig("sdk", ("general",), ("must-not-resolve",), provider_id="codex"),
            AgentConfig("review-only", ("general",), (), provider_id="local", review_command=("review-only-bin",)),
            AgentConfig("no-command", ("general",), (), provider_id="empty"),
        ),
    ), codex_sdk=None)
    resolve = Mock(return_value="resolved-review-bin")
    monkeypatch.setattr(pipeline._common_runtime.provider_probes, "resolve_executable", resolve)

    sdk = pipeline.provider_statuses("codex")[0]
    fallback = pipeline.provider_statuses("local")[0]
    empty = pipeline.provider_statuses("empty")[0]

    assert not sdk.available and sdk.authenticated is False
    assert sdk.auth_method == "error" and sdk.auth_label == "SDK 사용 불가" and sdk.executable == ""
    assert fallback.available and fallback.executable == "resolved-review-bin"
    assert not empty.available and empty.executable == ""
    resolve.assert_called_once_with("review-only-bin")
