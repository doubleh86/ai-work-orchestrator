from __future__ import annotations

from ..application import OrchestratorApplication
from ..application.errors import ApplicationError as RpcError
from .contracts import RequestScope, RpcRequest, RpcRoute
from .parameters import (
    optional_string,
    required_integer,
    required_string,
    string_map,
)


def handle_execution(application: OrchestratorApplication, request: RpcRequest) -> object:
    method, values = request.method, request.params
    project_name = request.project_name
    run_id = request.run_id
    if method == "tasks.retryContext":
        return application.task_retry_context(project_name, run_id, required_string(values, "taskId"))
    if method == "tasks.repairFromChat":
        return application.repair_task_from_chat(
            project_name, run_id, required_string(values, "taskId"), request_id=required_string(values, "requestId"),
            message=required_string(values, "message"), fingerprint=required_string(values, "fingerprint"),
            conversation_revision=required_integer(values, "conversationRevision"),
            **({"recovery_fingerprint": optional_string(values, "recoveryFingerprint")} if "recoveryFingerprint" in values else {}),
            **({"parent_request_id": required_string(values, "parentRequestId")} if "parentRequestId" in values else {}),
        )
    if method == "tasks.saveRetryInstruction":
        return application.save_task_retry_instruction(
            project_name, run_id, required_string(values, "taskId"), request_id=required_string(values, "requestId"),
            text=required_string(values, "text"), fingerprint=required_string(values, "fingerprint"),
        )
    if method == "tasks.log":
        task_id = required_string(values, "taskId")
        return application.task_log(project_name, run_id, task_id)
    if method == "runs.execute":
        return application.execute(
            project_name,
            run_id,
            agent_overrides=string_map(values, "agentOverrides"),
            model_overrides=string_map(values, "modelOverrides"),
            reasoning_effort_overrides=string_map(values, "reasoningEffortOverrides"),
        )
    if method == "runs.resume":
        return application.resume(project_name, run_id)
    if method == "runs.requestStop":
        return application.request_stop(
            project_name,
            run_id,
            request_id=required_string(values, "requestId"),
            execution_id=required_string(values, "executionId"),
            scope=required_string(values, "scope"),
            task_id=optional_string(values, "taskId"),
            attempt_id=optional_string(values, "attemptId"),
            invocation_id=optional_string(values, "invocationId"),
            **({"chat_message": required_string(values, "chatMessage")} if "chatMessage" in values else {}),
        )
    if method == "tasks.execute":
        task_id = required_string(values, "taskId")
        return application.execute_task(
            project_name,
            run_id,
            task_id,
            agent_overrides=string_map(values, "agentOverrides"),
            model_overrides=string_map(values, "modelOverrides"),
            reasoning_effort_overrides=string_map(values, "reasoningEffortOverrides"),
        )
    if method == "tasks.retry":
        task_id = required_string(values, "taskId")
        return application.retry_task(project_name, run_id, task_id)
    if method == "tasks.updateExecutionProfile":
        expected = string_map(values, "expectedProfile")
        if expected is None or set(expected) != {"agent_id", "model", "reasoning_effort", "last_attempt_id", "status"}:
            raise RpcError("invalid_params", "expectedProfile must contain the displayed execution profile, attempt and status")
        return application.update_task_execution_profile(
            project_name, run_id, required_string(values, "taskId"), agent_id=required_string(values, "agentId"),
            model=optional_string(values, "model"), reasoning_effort=optional_string(values, "reasoningEffort"), expected_profile=expected,
        )
    if method == "runs.verify":
        return application.verify(project_name, run_id)
    if method == "runs.verifyAndRepair":
        return application.verify_and_repair(
            project_name, run_id, required_string(values, "requestId"),
            **({"chat_message": required_string(values, "chatMessage")} if "chatMessage" in values else {}),
            **({"parent_request_id": required_string(values, "parentRequestId")} if "parentRequestId" in values else {}),
        )
    if method == "tasks.complete":
        return application.complete_task(project_name, run_id, required_string(values, "taskId"))
    if method == "tasks.completeManualVerification":
        return application.complete_manual_verification(
            project_name, run_id, required_string(values, "taskId"), note=required_string(values, "note"),
            expected_commit=required_string(values, "expectedCommit"), expected_revision=required_integer(values, "expectedRevision"),
        )
    if method == "runs.recordUserCheck":
        return application.record_user_check(
            project_name, run_id, required_string(values, "checkId"), outcome=required_string(values, "outcome"),
            note=required_string(values, "note"), expected_commit=required_string(values, "expectedCommit"),
            expected_revision=required_integer(values, "expectedRevision"),
        )
    if method == "tasks.handoffToAi":
        return application.handoff_manual_task_to_ai(
            project_name, run_id, required_string(values, "taskId"),
            expected_commit=required_string(values, "expectedCommit"), expected_revision=required_integer(values, "expectedRevision"),
        )
    if method in {"tasks.deferManual", "tasks.resumeManual"}:
        return application.set_manual_task_deferred(
            project_name, run_id, required_string(values, "taskId"), deferred=method == "tasks.deferManual"
        )
    raise RpcError("method_not_found", f"unsupported RPC method: {method}")


ROUTES: dict[str, RpcRoute] = {
    "tasks.retryContext": RpcRoute(RequestScope.RUN, handle_execution),
    "tasks.repairFromChat": RpcRoute(RequestScope.RUN, handle_execution),
    "tasks.saveRetryInstruction": RpcRoute(RequestScope.RUN, handle_execution),
    "tasks.log": RpcRoute(RequestScope.RUN, handle_execution),
    "runs.execute": RpcRoute(RequestScope.RUN, handle_execution),
    "runs.resume": RpcRoute(RequestScope.RUN, handle_execution),
    "runs.requestStop": RpcRoute(RequestScope.RUN, handle_execution),
    "tasks.execute": RpcRoute(RequestScope.RUN, handle_execution),
    "tasks.retry": RpcRoute(RequestScope.RUN, handle_execution),
    "tasks.updateExecutionProfile": RpcRoute(RequestScope.RUN, handle_execution),
    "runs.verify": RpcRoute(RequestScope.RUN, handle_execution),
    "runs.verifyAndRepair": RpcRoute(RequestScope.RUN, handle_execution),
    "tasks.complete": RpcRoute(RequestScope.RUN, handle_execution),
    "tasks.completeManualVerification": RpcRoute(RequestScope.RUN, handle_execution),
    "runs.recordUserCheck": RpcRoute(RequestScope.RUN, handle_execution),
    "tasks.handoffToAi": RpcRoute(RequestScope.RUN, handle_execution),
    "tasks.deferManual": RpcRoute(RequestScope.RUN, handle_execution),
    "tasks.resumeManual": RpcRoute(RequestScope.RUN, handle_execution),
}
