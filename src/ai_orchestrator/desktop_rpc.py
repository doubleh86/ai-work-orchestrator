from __future__ import annotations

import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import TextIO

from .application import ApplicationError as RpcError, OrchestratorApplication as DesktopApplication
from .application.views import expanded_provider_choices as _expanded_provider_choices, run_state_view
from .claude_credentials import claude_credential_scope
from .models import RunState
from .nvidia_agent import nvidia_credential_scope, redact_nvidia_output
from .registry import ProjectRegistry
from .rpc import dispatch
from .rpc.contracts import RPC_VERSION, RpcResponse

_LONG_RUNNING_RPC_METHODS = frozenset(
    {
        "runs.decideProjectChat", "runs.performProjectChat",
        "runs.recoveryPlan",
        "runs.applyRecovery",
        "runs.prepareConflictResolution",
        "runs.applyConflictResolution",
        "projects.updateMain",
        "projects.initializeGit",
        "projects.createInitialCommit",
        "projects.mainChanges",
        "projects.mainChangeDiff",
        "projects.refreshMainRemote",
        "projects.commitMainChanges",
        "projects.commitAndPushMainChanges",
        "projects.pushMainCommits",
        "projects.checkDotnet",
        "projects.checkWorkerMcp",
        "planning.refreshIndex",
        "runs.preparePlanning",
        "runs.proposeResultRevision",
        "runs.createResultRevision",
        "runs.runPlanning",
        "runs.start",
        "runs.sendPlanningMessage",
        "runs.previewPlanningApply",
        "runs.applyPlanningPreview",
        "runs.applyEffortModeToPlan",
        "runs.applyPlanningConversation",
        "planning.generateFeaturePlan",
        "runs.execute",
        "runs.resume",
        "tasks.execute",
        "tasks.retry",
        "tasks.repairFromChat",
        "tasks.complete",
        "tasks.completeManualVerification",
        "runs.recordUserCheck",
        "connections.registerExternal",
        "runs.launchResult",
        "runs.registerResult",
        "tasks.handoffToAi",
        "tasks.deferManual",
        "tasks.resumeManual",
        "runs.verify",
        "runs.verifyAndRepair",
        "runs.updatePlan",
        "runs.confirmPlan",
        "runs.merge",
        "runs.push",
        "runs.retryMainPush",
        "runs.recoverMainApply",
        "runs.deploy",
        "runs.archive",
        "runs.retryArchiveCleanup",
        "runs.delete",
        "workspaces.cleanup",
    }
)
_STATUS_RPC_METHODS = frozenset(
    {
        "system.hello",
        "connections.externalGuide",
        "runs.resultArtifact",
        "auth.codex.status",
        "auth.claude.status",
        "providers.accountUsage",
        "providers.codexModels",
        "auth.codex.get",
        "projects.list",
        "runs.activeGroups",
        "runs.attentionItems",
        "projects.capabilities",
        "projects.codeStyleProfile",
        "projects.workerMcp",
        "projects.inspectGitReadiness",
        "projects.previewGitInitialization",
        "projects.previewInitialCommit",
        "planning.inspectRepositoryMaturity",
        "planning.previewBootstrap",
        "projects.workspaceLocation",
        "notifications.list",
        "runs.list",
        "runs.archivePlan",
        "runs.get",
        "runs.getPlanningPreview",
        "runs.planningPreviewStatus",
        "runs.previewEffortMode",
        "runs.usage",
        "tasks.retryContext",
        "runs.resultRevisions",
        "operations.get",
        "operations.latest",
        "runs.integrationConflict",
        "tasks.log",
        "workspaces.list",
        "locks.get",
    }
)


class RpcService:
    def __init__(self, application: DesktopApplication):
        self.application = application

    def dispatch(self, method: str, params: object = None) -> object:
        return dispatch(self.application, method, params)


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, RunState):
        return _json_value(run_state_view(value))
    if hasattr(value, "to_dict"):
        return _json_value(value.to_dict())  # type: ignore[attr-defined]
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    raise TypeError(f"unsupported RPC result type: {type(value).__name__}")


def handle_request(service: RpcService, raw: object) -> RpcResponse:
    request_id: object = None
    credential = raw.get("nvidia_api_key") if isinstance(raw, dict) else None
    secrets = [credential] if isinstance(credential, str) else []
    claude_credential = raw.get("claude_api_key") if isinstance(raw, dict) else None
    if isinstance(claude_credential, str) and claude_credential.strip():
        secrets.append(claude_credential.strip())
    if isinstance(raw, dict) and raw.get("method") == "auth.codex.apiKey" and isinstance(raw.get("params"), dict):
        codex_key = raw["params"].get("apiKey")
        if isinstance(codex_key, str) and codex_key.strip():
            secrets.append(codex_key.strip())
    model_credentials = raw.get("nvidia_model_api_keys") if isinstance(raw, dict) else None
    if isinstance(model_credentials, dict):
        secrets.extend(key for key in model_credentials.values() if isinstance(key, str))

    def error_message(error: Exception) -> str:
        message = redact_nvidia_output(str(error), {})
        for key in sorted(set(secrets), key=len, reverse=True):
            message = redact_nvidia_output(message, {"NVIDIA_API_KEY": key})
        return message
    try:
        if not isinstance(raw, dict):
            raise RpcError("invalid_request", "request must be an object")
        request_id = raw.get("id")
        if not isinstance(request_id, (str, int)):
            raise RpcError("invalid_request", "id must be a string or integer")
        method = raw.get("method")
        if not isinstance(method, str) or not method.strip():
            raise RpcError("invalid_request", "method must be a non-empty string")
        with nvidia_credential_scope(raw.get("nvidia_api_key"), model_credentials), claude_credential_scope(claude_credential):
            result = service.dispatch(method.strip(), raw.get("params"))
        return {"id": request_id, "result": _json_value(result)}
    except RpcError as exc:
        return {"id": request_id, "error": {"code": exc.code, "message": error_message(exc)}}
    # RPC boundary must preserve a valid response frame.
    except Exception as exc:
        return {"id": request_id, "error": {"code": "application_error", "message": error_message(exc)}}


def serve(service: RpcService, input_stream: TextIO, output_stream: TextIO) -> None:
    output_lock = threading.Lock()

    def write_response(response: RpcResponse) -> None:
        frame = json.dumps(response, ensure_ascii=True) + "\n"
        with output_lock:
            output_stream.write(frame)
            output_stream.flush()

    def process(raw: object) -> None:
        write_response(handle_request(service, raw))

    with (
        ThreadPoolExecutor(max_workers=4, thread_name_prefix="desktop-status-rpc") as status_executor,
        ThreadPoolExecutor(max_workers=4, thread_name_prefix="desktop-control-rpc") as control_executor,
        ThreadPoolExecutor(max_workers=4, thread_name_prefix="desktop-work-rpc") as work_executor,
    ):
        for line in input_stream:
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                write_response({"id": None, "error": {"code": "parse_error", "message": str(exc)}})
            else:
                method = raw.get("method") if isinstance(raw, dict) else None
                if method in _LONG_RUNNING_RPC_METHODS:
                    executor = work_executor
                elif method in _STATUS_RPC_METHODS:
                    executor = status_executor
                else:
                    executor = control_executor
                executor.submit(process, raw)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI Work Orchestrator Electron backend")
    parser.add_argument("--registry", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_standard_streams()
    args = build_parser().parse_args(argv)
    registry = ProjectRegistry(args.registry or None)
    application = DesktopApplication(registry)
    service = RpcService(application)
    try:
        serve(service, sys.stdin, sys.stdout)
    finally:
        application.close()
    return 0


def _configure_standard_streams() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="strict")


if __name__ == "__main__":
    raise SystemExit(main())
