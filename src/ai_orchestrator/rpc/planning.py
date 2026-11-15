from __future__ import annotations

from ..application import OrchestratorApplication
from ..application.errors import ApplicationError as RpcError
from .contracts import RequestScope, RpcRequest, RpcRoute
from .parameters import (
    boolean,
    nullable_string,
    object_list,
    optional_string,
    required_approval,
    required_integer,
    required_string,
    string_list,
)


def handle_planning(application: OrchestratorApplication, request: RpcRequest) -> object:
    method, values = request.method, request.params
    project_name = request.project_name
    run_id = request.run_id
    if method == "planning.inspectRepositoryMaturity":
        return application.inspect_repository_maturity(project_name)
    if method == "planning.refreshIndex":
        return application.refresh_planning_index(project_name, required_string(values, "sourceRoot"))
    if method == "runs.preparePlanning":
        return application.prepare_planning(
            project_name,
            optional_string(values, "specPath"),
            planning_agent_id=optional_string(values, "planningAgentId"),
            planning_model=optional_string(values, "planningModel"),
            planning_reasoning_effort=optional_string(values, "planningReasoningEffort"),
            planning_mode=(optional_string(values, "planningMode") or "auto"),
            planning_request=optional_string(values, "planningRequest"),
            prepared_index_generated_at=optional_string(values, "preparedIndexGeneratedAt"),
            repository_intent=optional_string(values, "repositoryIntent"),
            effort_mode=(optional_string(values, "effortMode") or "balanced"),
            planning_profile_source=nullable_string(values, "planningProfileSource"),
        )
    if method == "runs.start":
        return application.start(
            project_name,
            required_string(values, "specPath"),
            planning_agent_id=optional_string(values, "planningAgentId"),
            planning_model=optional_string(values, "planningModel"),
            planning_reasoning_effort=optional_string(values, "planningReasoningEffort"),
            planning_mode=(optional_string(values, "planningMode") or "auto"),
            planning_request=optional_string(values, "planningRequest"),
            effort_mode=(optional_string(values, "effortMode") or "balanced"),
            planning_profile_source=nullable_string(values, "planningProfileSource"),
        )
    if method == "runs.beginPlanningRequest":
        return application.begin_planning_request(project_name, run_id, request_id=required_string(values, "requestId"),
                                                       kind=required_string(values, "kind"), message=optional_string(values, "message"))
    if method == "runs.finishPlanningRequest":
        return application.finish_planning_request(project_name, run_id, request_id=required_string(values, "requestId"),
                                                        phase=required_string(values, "phase"), error=optional_string(values, "error"))
    if method == "planning.previewBootstrap":
        return application.preview_bootstrap(project_name, run_id)
    if method == "planning.generateFeaturePlan":
        return application.generate_feature_plan(project_name, run_id)
    if method == "runs.runPlanning":
        return application.run_planning(project_name, run_id)
    if method == "runs.getPlanningPreview":
        return application.planning_apply_preview(project_name, run_id)
    if method == "runs.planningPreviewStatus":
        return application.planning_preview_status(project_name, run_id)
    if method == "runs.interruptPlanning":
        return application.interrupt_planning(project_name, run_id, approved=required_approval(values))
    if method == "runs.sendPlanningMessage":
        return application.send_planning_message(
            project_name,
            run_id,
            required_string(values, "message"),
            planning_agent_id=nullable_string(values, "planningAgentId"),
            planning_model=nullable_string(values, "planningModel"),
            planning_reasoning_effort=nullable_string(values, "planningReasoningEffort"),
        )
    if method == "runs.applyPlanningConversation":
        technology_options: dict[str, object] = {}
        if "expectedTechStackRevision" in values or "answer" in values or "retryFailed" in values:
            technology_options = {
                "answer_message": optional_string(values, "answer"),
                "expected_tech_stack_revision": required_integer(values, "expectedTechStackRevision"),
                "retry_failed": boolean(values, "retryFailed", default=False),
            }
        if any(name in values for name in ("planningAgentId", "planningModel", "planningReasoningEffort")):
            technology_options.update({
                "planning_agent_id": nullable_string(values, "planningAgentId"),
                "planning_model": nullable_string(values, "planningModel"),
                "planning_reasoning_effort": nullable_string(values, "planningReasoningEffort"),
            })
        return application.apply_planning_conversation(
            project_name,
            run_id,
            request_id=required_string(values, "requestId"),
            expected_revision=required_integer(values, "expectedRevision"),
            conversation_revision=required_integer(values, "conversationRevision"),
            **technology_options,
        )
    if method == "runs.requestDirectionChange":
        return application.request_direction_change(
            project_name, run_id, request_id=required_string(values, "requestId"), text=required_string(values, "text")
        )
    if method == "runs.previewPlanningApply":
        return application.preview_planning_apply(
            project_name, run_id, request_id=required_string(values, "requestId")
        )
    if method == "runs.applyPlanningPreview":
        return application.apply_planning_preview(
            project_name, run_id, preview_id=required_string(values, "previewId"),
            fingerprint=required_string(values, "fingerprint"),
            candidate_digest=required_string(values, "candidateDigest"),
        )
    if method == "runs.confirmTechStack":
        return application.confirm_tech_stack(
            project_name,
            run_id,
            option_id=required_string(values, "optionId"),
            expected_revision=required_integer(values, "expectedRevision"),
        )
    if method == "runs.configureBootstrapInstructions":
        return application.configure_bootstrap_agent_instructions(
            project_name,
            run_id,
            create=boolean(values, "create", default=True),
            expected_revision=required_integer(values, "expectedRevision"),
            expected_digest=required_string(values, "expectedDigest"),
        )
    if method == "runs.excludeTasks":
        return application.exclude_tasks(
            project_name, run_id, string_list(values, "taskIds", required=True), approved=required_approval(values)
        )
    if method == "runs.updatePlan":
        return application.update_plan(
            project_name, run_id, object_list(values, "tasks", required=True),
            **({"expected_revision": required_integer(values, "expectedRevision")} if "expectedRevision" in values else {}),
        )
    if method == "runs.confirmPlan":
        if "expectedRevision" in values or "bootstrapDigest" in values:
            return application.confirm_plan(
                project_name, run_id, expected_revision=required_integer(values, "expectedRevision"),
                expected_bootstrap_digest=optional_string(values, "bootstrapDigest"),
            )
        return application.confirm_plan(project_name, run_id)
    raise RpcError("method_not_found", f"unsupported RPC method: {method}")


ROUTES: dict[str, RpcRoute] = {
    "planning.inspectRepositoryMaturity": RpcRoute(RequestScope.PROJECT, handle_planning),
    "planning.refreshIndex": RpcRoute(RequestScope.PROJECT, handle_planning),
    "runs.preparePlanning": RpcRoute(RequestScope.PROJECT, handle_planning),
    "runs.start": RpcRoute(RequestScope.PROJECT, handle_planning),
    "runs.beginPlanningRequest": RpcRoute(RequestScope.RUN, handle_planning),
    "runs.finishPlanningRequest": RpcRoute(RequestScope.RUN, handle_planning),
    "planning.previewBootstrap": RpcRoute(RequestScope.RUN, handle_planning),
    "planning.generateFeaturePlan": RpcRoute(RequestScope.RUN, handle_planning),
    "runs.runPlanning": RpcRoute(RequestScope.RUN, handle_planning),
    "runs.getPlanningPreview": RpcRoute(RequestScope.RUN, handle_planning),
    "runs.planningPreviewStatus": RpcRoute(RequestScope.RUN, handle_planning),
    "runs.interruptPlanning": RpcRoute(RequestScope.RUN, handle_planning),
    "runs.sendPlanningMessage": RpcRoute(RequestScope.RUN, handle_planning),
    "runs.applyPlanningConversation": RpcRoute(RequestScope.RUN, handle_planning),
    "runs.requestDirectionChange": RpcRoute(RequestScope.RUN, handle_planning),
    "runs.previewPlanningApply": RpcRoute(RequestScope.RUN, handle_planning),
    "runs.applyPlanningPreview": RpcRoute(RequestScope.RUN, handle_planning),
    "runs.confirmTechStack": RpcRoute(RequestScope.RUN, handle_planning),
    "runs.configureBootstrapInstructions": RpcRoute(RequestScope.RUN, handle_planning),
    "runs.excludeTasks": RpcRoute(RequestScope.RUN, handle_planning),
    "runs.updatePlan": RpcRoute(RequestScope.RUN, handle_planning),
    "runs.confirmPlan": RpcRoute(RequestScope.RUN, handle_planning),
}
