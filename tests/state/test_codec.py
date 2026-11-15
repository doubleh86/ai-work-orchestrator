from __future__ import annotations

import subprocess
import sys

from ai_orchestrator.models import RunState, RunSummary


def test_state_codec_loads_without_run_coordinator_or_store() -> None:
    script = """
import importlib.abc
import sys

class RejectRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {
            'ai_orchestrator.state.run', 'ai_orchestrator.models',
            'ai_orchestrator.pipeline', 'ai_orchestrator.store',
        }:
            raise AssertionError('field decoding must not load runtime or the RunState constructor')

sys.meta_path.insert(0, RejectRuntime())
from ai_orchestrator.state.codec import decode_run_state_fields, decode_run_summary_fields
raw = {'id': 'run', 'spec_path': 'plan.md', 'spec_digest': 'digest', 'repo_path': 'unused',
       'main_branch': 'main', 'stage': 'planned'}
fields = decode_run_state_fields(raw)
assert fields['schema_version'] == 1 and fields['tasks'] == []
assert decode_run_summary_fields(raw)['task_count'] == 0
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_model_restoration_keeps_the_callers_subclass() -> None:
    class CustomRun(RunState):
        pass

    class CustomSummary(RunSummary):
        pass

    raw = {
        "id": "run", "spec_path": "plan.md", "spec_digest": "digest", "repo_path": "unused",
        "main_branch": "main", "stage": "planned",
    }
    restored = CustomRun.from_dict(raw)
    assert isinstance(restored, CustomRun)
    assert isinstance(CustomSummary.from_dict(restored.to_dict()), CustomSummary)
