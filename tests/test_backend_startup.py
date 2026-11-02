import json
from pathlib import Path
import subprocess
import sys


def test_real_backend_serves_initial_queries_without_importing_codex_runtime(tmp_path: Path) -> None:
    script = """
import importlib.abc
import sys

class RejectCodexRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'openai_codex' or fullname.startswith('openai_codex.'):
            raise AssertionError('initial backend queries must not load the AI runtime')

sys.meta_path.insert(0, RejectCodexRuntime())
from ai_orchestrator.desktop_rpc import main
raise SystemExit(main(['--registry', sys.argv[1]]))
"""
    requests = [{"id": 1, "method": "system.hello", "params": {}}, {"id": 2, "method": "projects.list", "params": {}}]
    result = subprocess.run(
        [sys.executable, "-u", "-c", script, str(tmp_path / "registry.json")],
        input="".join(json.dumps(request) + "\n" for request in requests),
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stderr
    frames = {frame["id"]: frame for frame in map(json.loads, result.stdout.splitlines())}
    assert frames == {
        1: {"id": 1, "result": {"rpcVersion": 1, "application": "ai-work-orchestrator"}},
        2: {"id": 2, "result": []},
    }
