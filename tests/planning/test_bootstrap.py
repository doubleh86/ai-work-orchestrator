from pathlib import Path

import pytest

from ai_orchestrator.errors import PipelineError
from ai_orchestrator.planning import bootstrap


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_snapshot_refuses_to_truncate_paths_over_the_safety_limit(tmp_path: Path, monkeypatch, kind: str) -> None:
    for name in ["one", "two"]:
        path = tmp_path / name
        if kind == "file":
            path.write_text("snapshot", encoding="utf-8")
        else:
            path.mkdir()
    monkeypatch.setattr(bootstrap, "BOOTSTRAP_SNAPSHOT_MAX_PATHS", 1)

    with pytest.raises(PipelineError, match="1개를 넘어"):
        bootstrap.bootstrap_path_snapshot(tmp_path, ["**"])


def test_snapshot_read_failure_keeps_the_cause_instead_of_returning_empty_paths(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "unreadable.txt").write_text("snapshot", encoding="utf-8")
    cause = PermissionError("snapshot file is not readable")

    def fail_read(_path: Path) -> str:
        raise cause

    monkeypatch.setattr(bootstrap, "file_sha256", fail_read)

    with pytest.raises(PipelineError, match="예상 경로를 확인하지 못했습니다") as caught:
        bootstrap.bootstrap_path_snapshot(tmp_path, ["**"])

    assert caught.value.__cause__ is cause
