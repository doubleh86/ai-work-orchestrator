"""Keep application/CLI contracts stable during facade migration."""

import inspect
import json
from pathlib import Path

from ai_orchestrator import errors, pipeline
from ai_orchestrator.execution import TaskVerificationFailure, TaskVerificationTimeout
from ai_orchestrator.usage import UsageContext


def test_pipeline_public_signatures_and_binding_match_manifest() -> None:
    manifest = json.loads(Path(__file__).with_name("pipeline_api.json").read_text(encoding="utf-8"))
    actual = {}
    for name, member in vars(pipeline.Pipeline).items():
        if name != "__init__" and name.startswith("_"):
            continue
        if isinstance(member, property):
            continue
        binding = "static" if isinstance(member, staticmethod) else "class" if isinstance(member, classmethod) else "instance"
        actual[name] = {"binding": binding, "signature": str(inspect.signature(getattr(pipeline.Pipeline, name)))}
    assert actual == manifest["callables"]
    assert len(actual) - 1 == manifest["baseline_public_methods"] == 112


def test_pipeline_legacy_exports_keep_identity_and_constant_values() -> None:
    for name in ("PipelineError", "ApprovalRequired", "ProviderTimeoutError", "ProviderCapacityError", "ProviderRequestLimitError"):
        assert getattr(pipeline, name) is getattr(errors, name)
    assert issubclass(pipeline.ApprovalRequired, pipeline.PipelineError)
    assert pipeline.TaskVerificationFailure is TaskVerificationFailure
    assert pipeline.TaskVerificationTimeout is TaskVerificationTimeout
    assert pipeline.UsageContext is UsageContext
    constants = {
        "AGENT_OUTPUT_DRAIN_TIMEOUT_SECONDS": 5,
        "AGENT_TERMINATION_TIMEOUT_SECONDS": 10,
        "CODEX_INPUT_LIMIT_CHARACTERS": 1_048_576,
        "INTEGRATION_VERIFICATION_COMMAND_TIMEOUT_SECONDS": 600,
        "RUN_DELETION_TIMEOUT_SECONDS": 60,
        "TASK_LOG_DISPLAY_LIMIT_BYTES": 64 * 1024,
        "BOOTSTRAP_AGENTS_ACCEPTANCE": "root AGENTS.md에 확정한 기술 구성과 검증 명령을 기록한다.",
    }
    assert {name: getattr(pipeline, name) for name in constants} == constants
