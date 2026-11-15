from __future__ import annotations

import subprocess
import sys
from unittest.mock import Mock

from ai_orchestrator.models import RunExecutionAction, RunExecutionSituation, RunLockState, RunLockStatus, RunState, Stage
from ai_orchestrator.run_queries import BranchSnapshot, run_execution_control


def test_common_api_and_mcp_load_without_desktop_transport() -> None:
    script = """
import importlib.abc
import sys

class RejectDesktopTransport(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'ai_orchestrator.desktop_rpc' or fullname.startswith('ai_orchestrator.rpc'):
            raise AssertionError('headless APIs must not import desktop RPC')

sys.meta_path.insert(0, RejectDesktopTransport())
from ai_orchestrator.application import OrchestratorApplication, create_pipeline
from ai_orchestrator.mcp_operations import McpOperations
from ai_orchestrator.cli import main
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_live_execution_query_does_not_probe_repository_or_recovery() -> None:
    state = RunState("run", "plan.md", "digest", "/unused", "main", Stage.EXECUTING)
    probe = Mock(side_effect=AssertionError("live lock must take precedence over repository queries"))
    control = run_execution_control(
        state, RunLockStatus(state.id, RunLockState.ACTIVE, operation="execute"),
        waiting_for_user_checks=probe, read_branch=probe, deferred_task_ids=probe,
        has_main_push_recovery=probe, uses_shared_workspace=probe,
    )
    assert control.situation == RunExecutionSituation.RUNNING
    assert control.action == RunExecutionAction.NONE
    probe.assert_not_called()


def test_branch_query_failure_prevents_resume_without_hiding_reason() -> None:
    state = RunState("run", "plan.md", "digest", "/unused", "main", Stage.EXECUTING)
    later_probe = Mock(side_effect=AssertionError("uncertain branch must prevent recovery queries"))
    control = run_execution_control(
        state, RunLockStatus(state.id, RunLockState.UNLOCKED),
        waiting_for_user_checks=lambda: False, read_branch=lambda: BranchSnapshot(error="branch probe failed"),
        deferred_task_ids=later_probe, has_main_push_recovery=later_probe, uses_shared_workspace=later_probe,
    )
    assert control.situation == RunExecutionSituation.STATUS_UNKNOWN
    assert control.action == RunExecutionAction.NONE
    assert "branch probe failed" in control.reason
    later_probe.assert_not_called()
