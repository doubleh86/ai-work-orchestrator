from __future__ import annotations

from ..application import OrchestratorApplication
from ..application.errors import ApplicationError as RpcError
from .contracts import RequestScope, RpcRequest, RpcRoute
from .parameters import (
    boolean,
    optional_string,
    required_approval,
    required_integer,
    required_string,
    string_list,
    string_map,
)


def handle_runs(application: OrchestratorApplication, request: RpcRequest) -> object:
    method, values = request.method, request.params
    project_name = request.project_name
    run_id = request.run_id
    if method == "runs.activeGroups":
        return application.active_groups()
    if method == "runs.attentionItems":
        return application.attention_items()
    if method == "runs.list":
        scope = optional_string(values, "scope")
        return application.runs(project_name, scope=scope) if scope else application.runs(project_name)
    if method == "notifications.list":
        limit = values.get("limit", 100)
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise RpcError("invalid_params", "notification limit must be an integer")
        return application.notifications(project_name, after_cursor=optional_string(values, "afterCursor"), limit=limit)
    if method == "runs.resultArtifact":
        return application.result_artifact(project_name, run_id)
    if method == "runs.registerResult":
        return application.register_result(project_name, run_id, kind=required_string(values, "kind"),
                                                relative_path=required_string(values, "relativePath"),
                                                expected_commit=required_string(values, "expectedCommit"))
    if method == "runs.launchResult":
        return application.launch_result(project_name, run_id, expected_digest=required_string(values, "expectedDigest"),
                                              device_id=optional_string(values, "deviceId"))
    if method == "runs.requestChatControl":
        expected = values.get("expected")
        if not isinstance(expected, dict):
            raise RpcError("invalid_params", "expected must be an object")
        profile = values.get("profile", {})
        if not isinstance(profile, dict) or any(key not in {"planningAgentId", "planningModel", "planningReasoningEffort"}
                                               or not isinstance(value, str) for key, value in profile.items()):
            raise RpcError("invalid_params", "profile must contain Planning profile strings")
        return application.request_chat_control(project_name, run_id, request_id=required_string(values, "requestId"),
                                                     intent=required_string(values, "intent"), message=required_string(values, "message"),
                                                     expected=expected, session_id=optional_string(values, "sessionId"), profile=profile)
    if method == "runs.decideProjectChat":
        return application.decide_project_chat(project_name, run_id, required_string(values, "requestId"))
    if method == "runs.performProjectChat":
        return application.perform_project_chat(project_name, run_id, required_string(values, "requestId"),
                                                    required_string(values, "stepId"))
    if method == "runs.advanceChatControl":
        return application.advance_chat_control(project_name, run_id, required_string(values, "requestId"),
                                                     suspend=boolean(values, "suspend", default=False))
    if method == "runs.cancelChatControl":
        return application.cancel_chat_control(project_name, run_id, required_string(values, "requestId"))
    if method == "runs.archivePlan":
        return application.archive_plan(project_name, run_id)
    if method == "runs.archive":
        return application.archive_run(
            project_name,
            run_id,
            expected_revision=required_string(values, "expectedRevision"),
            fingerprint=required_string(values, "fingerprint"),
            request_id=required_string(values, "requestId"),
            approved=required_approval(values),
        )
    if method == "runs.retryArchiveCleanup":
        return application.retry_archive_cleanup(
            project_name,
            run_id,
            fingerprint=required_string(values, "fingerprint"),
            request_id=required_string(values, "requestId"),
            approved=required_approval(values),
        )
    if method == "runs.get":
        return application.status(project_name, run_id, **({"include_user_checks": True} if values.get("includeUserChecks") is True else {}))
    if method == "runs.usage":
        return application.usage(
            project_name, run_id, execution_request_id=optional_string(values, "executionRequestId"),
            cursor=optional_string(values, "cursor"), limit=required_integer(values, "limit") if "limit" in values else 50,
        )
    if method == "runs.previewEffortMode":
        return application.preview_effort_mode(
            project_name, run_id, required_string(values, "mode"), required_integer(values, "expectedRevision")
        )
    if method == "runs.setEffortMode":
        return application.set_effort_mode(
            project_name, run_id, required_string(values, "mode"), required_string(values, "target"),
            required_integer(values, "expectedPolicyRevision"), required_string(values, "requestId"),
        )
    if method == "runs.cancelEffortReservation":
        return application.cancel_effort_reservation(
            project_name, run_id, required_integer(values, "expectedPolicyRevision"), required_string(values, "requestId"),
        )
    if method == "runs.applyEffortModeToPlan":
        return application.apply_effort_mode_to_plan(
            project_name, run_id, required_string(values, "mode"), required_integer(values, "expectedPolicyRevision"),
            required_integer(values, "expectedPlanRevision"), string_map(values, "reviewerAgentIds"),
        )
    if method == "runs.resultRevisions":
        return application.result_revisions(project_name, run_id)
    if method == "runs.proposeResultRevision":
        return application.propose_result_revision(
            project_name, run_id, proposal_id=required_string(values, "proposalId"),
            text=optional_string(values, "text"), focus_task_id=optional_string(values, "focusTaskId"),
        )
    if method == "runs.createResultRevision":
        return application.create_result_revision(
            project_name, run_id, request_id=required_string(values, "requestId"),
            text=optional_string(values, "text"), task_ids=string_list(values, "taskIds"),
            paths=string_list(values, "paths"), proposal_id=optional_string(values, "proposalId"),
        )
    if method == "runs.delete":
        return application.delete_run(project_name, run_id, approved=required_approval(values))
    raise RpcError("method_not_found", f"unsupported RPC method: {method}")


ROUTES: dict[str, RpcRoute] = {
    "runs.activeGroups": RpcRoute(RequestScope.GLOBAL, handle_runs),
    "runs.attentionItems": RpcRoute(RequestScope.GLOBAL, handle_runs),
    "runs.list": RpcRoute(RequestScope.PROJECT, handle_runs),
    "notifications.list": RpcRoute(RequestScope.PROJECT, handle_runs),
    "runs.resultArtifact": RpcRoute(RequestScope.RUN, handle_runs),
    "runs.registerResult": RpcRoute(RequestScope.RUN, handle_runs),
    "runs.launchResult": RpcRoute(RequestScope.RUN, handle_runs),
    "runs.requestChatControl": RpcRoute(RequestScope.RUN, handle_runs),
    "runs.decideProjectChat": RpcRoute(RequestScope.RUN, handle_runs),
    "runs.performProjectChat": RpcRoute(RequestScope.RUN, handle_runs),
    "runs.advanceChatControl": RpcRoute(RequestScope.RUN, handle_runs),
    "runs.cancelChatControl": RpcRoute(RequestScope.RUN, handle_runs),
    "runs.archivePlan": RpcRoute(RequestScope.RUN, handle_runs),
    "runs.archive": RpcRoute(RequestScope.RUN, handle_runs),
    "runs.retryArchiveCleanup": RpcRoute(RequestScope.RUN, handle_runs),
    "runs.get": RpcRoute(RequestScope.RUN, handle_runs),
    "runs.usage": RpcRoute(RequestScope.RUN, handle_runs),
    "runs.previewEffortMode": RpcRoute(RequestScope.RUN, handle_runs),
    "runs.setEffortMode": RpcRoute(RequestScope.RUN, handle_runs),
    "runs.cancelEffortReservation": RpcRoute(RequestScope.RUN, handle_runs),
    "runs.applyEffortModeToPlan": RpcRoute(RequestScope.RUN, handle_runs),
    "runs.resultRevisions": RpcRoute(RequestScope.RUN, handle_runs),
    "runs.proposeResultRevision": RpcRoute(RequestScope.RUN, handle_runs),
    "runs.createResultRevision": RpcRoute(RequestScope.RUN, handle_runs),
    "runs.delete": RpcRoute(RequestScope.RUN, handle_runs),
}
