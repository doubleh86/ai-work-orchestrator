from __future__ import annotations

from ..application import OrchestratorApplication
from ..application.errors import ApplicationError as RpcError
from .contracts import RequestScope, RpcRequest, RpcRoute
from .parameters import (
    optional_string,
    required_approval,
    required_string,
)


def handle_integration(application: OrchestratorApplication, request: RpcRequest) -> object:
    method, values = request.method, request.params
    project_name = request.project_name
    run_id = request.run_id
    if method == "runs.integrationConflict":
        return application.integration_conflict(
            project_name,
            run_id,
            optional_string(values, "conflictId"),
            optional_string(values, "filePath"),
            optional_string(values, "recoveryTaskId"),
        )
    if method == "runs.recoveryPlan":
        request_id = optional_string(values, "requestId")
        return application.recovery_plan(project_name, run_id, **({"request_id": request_id} if request_id else {}))
    if method == "runs.applyRecovery":
        selected = values.get("sourceIds")
        if not isinstance(selected, list) or not all(isinstance(item, str) for item in selected):
            raise RpcError("invalid_params", "sourceIds must be an array of strings")
        recovery_options: dict[str, object] = {"approved": required_approval(values)}
        request_id = optional_string(values, "requestId")
        resume_request_id = optional_string(values, "resumeRequestId")
        if request_id:
            recovery_options["request_id"] = request_id
        if resume_request_id:
            recovery_options["resume_request_id"] = resume_request_id
        return application.apply_recovery(
            project_name,
            run_id,
            required_string(values, "fingerprint"),
            selected,
            **recovery_options,
        )
    if method == "operations.get":
        return application.recovery_operation(project_name, run_id, required_string(values, "requestId"))
    if method == "operations.latest":
        return application.latest_recovery_operation(project_name, run_id, required_string(values, "kind"))
    if method == "runs.prepareConflictResolution":
        return application.prepare_conflict_resolution(
            project_name,
            run_id,
            conflict_id=required_string(values, "conflictId"),
            fingerprint=required_string(values, "fingerprint"),
            request_id=required_string(values, "requestId"),
            agent_id=optional_string(values, "agentId"),
            model=optional_string(values, "model"),
            reasoning_effort=optional_string(values, "reasoningEffort"),
        )
    if method == "runs.applyConflictResolution":
        revision = values.get("candidateRevision")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise RpcError("invalid_params", "candidateRevision must be a positive integer")
        return application.apply_conflict_resolution(
            project_name,
            run_id,
            conflict_id=required_string(values, "conflictId"),
            candidate_id=required_string(values, "candidateId"),
            candidate_revision=revision,
            fingerprint=required_string(values, "fingerprint"),
            request_id=required_string(values, "requestId"),
            approved=required_approval(values),
        )
    if method in {"runs.merge", "runs.push", "runs.retryMainPush", "runs.recoverMainApply", "runs.deploy"}:
        approved = required_approval(values)
        recovery_target = {
            "expected_repo": required_string(values, "repoPath"),
            "expected_commit": required_string(values, "targetCommit"),
        } if method == "runs.recoverMainApply" else {}
        return application.approved_run_action(
            project_name,
            run_id,
            method.removeprefix("runs."),
            approved=approved,
            request_id=optional_string(values, "requestId"),
            **recovery_target,
        )
    if method == "workspaces.list":
        return application.workspace_statuses(project_name, run_id)
    if method == "workspaces.cleanup":
        return application.cleanup_workspace(project_name, run_id, required_string(values, "taskId"), approved=required_approval(values))
    if method == "locks.get":
        return application.run_lock_status(project_name, run_id)
    if method == "locks.clear":
        return application.clear_run_lock(project_name, run_id, approved=required_approval(values))
    raise RpcError("method_not_found", f"unsupported RPC method: {method}")


ROUTES: dict[str, RpcRoute] = {
    "runs.integrationConflict": RpcRoute(RequestScope.RUN, handle_integration),
    "runs.recoveryPlan": RpcRoute(RequestScope.RUN, handle_integration),
    "runs.applyRecovery": RpcRoute(RequestScope.RUN, handle_integration),
    "operations.get": RpcRoute(RequestScope.RUN, handle_integration),
    "operations.latest": RpcRoute(RequestScope.RUN, handle_integration),
    "runs.prepareConflictResolution": RpcRoute(RequestScope.RUN, handle_integration),
    "runs.applyConflictResolution": RpcRoute(RequestScope.RUN, handle_integration),
    "runs.deploy": RpcRoute(RequestScope.RUN, handle_integration),
    "runs.merge": RpcRoute(RequestScope.RUN, handle_integration),
    "runs.push": RpcRoute(RequestScope.RUN, handle_integration),
    "runs.recoverMainApply": RpcRoute(RequestScope.RUN, handle_integration),
    "runs.retryMainPush": RpcRoute(RequestScope.RUN, handle_integration),
    "workspaces.list": RpcRoute(RequestScope.RUN, handle_integration),
    "workspaces.cleanup": RpcRoute(RequestScope.RUN, handle_integration),
    "locks.get": RpcRoute(RequestScope.RUN, handle_integration),
    "locks.clear": RpcRoute(RequestScope.RUN, handle_integration),
}
