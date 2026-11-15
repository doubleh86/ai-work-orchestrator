from __future__ import annotations

from ..application import OrchestratorApplication
from ..application.errors import ApplicationError as RpcError
from .contracts import RequestScope, RpcRequest, RpcRoute
from .parameters import (
    boolean,
    code_style_preference,
    main_change_selections,
    optional_string,
    required_approval,
    required_integer,
    required_path_string,
    required_string,
    string_list,
)


def handle_projects(application: OrchestratorApplication, request: RpcRequest) -> object:
    method, values = request.method, request.params
    project_name = request.project_name
    if method == "projects.list":
        return application.projects()
    if method == "projects.inspectGitReadiness":
        return application.inspect_git_readiness(required_path_string(values, "repo"))
    if method == "projects.previewGitInitialization":
        return application.preview_git_initialization(required_path_string(values, "repo"))
    if method == "projects.initializeGit":
        return application.initialize_git(
            required_path_string(values, "repo"),
            required_string(values, "expectedKind"),
            approved=required_approval(values),
        )
    if method == "projects.previewInitialCommit":
        return application.preview_initial_commit(required_path_string(values, "repo"))
    if method == "projects.createInitialCommit":
        return application.create_initial_commit(
            required_path_string(values, "repo"),
            required_string(values, "snapshotId"),
            string_list(values, "selectedPaths"),
            required_string(values, "message"),
            author_name=optional_string(values, "authorName"),
            author_email=optional_string(values, "authorEmail"),
            save_author=boolean(values, "saveAuthor", default=True),
            allow_empty=boolean(values, "allowEmpty", default=False),
            approved=required_approval(values),
        )
    if method == "projects.add":
        return application.register_project(
            optional_string(values, "name"),
            required_string(values, "repo"),
            optional_string(values, "configPath") or None,
            optional_string(values, "planningSourceDir") or None,
        )
    if method == "projects.workerMcp":
        return application.worker_mcp_connections(project_name)
    if method == "projects.updateWorkerMcp":
        return application.update_worker_mcp_connections(
            project_name, values.get("servers"), expected_revision=required_integer(values, "expectedRevision"),
            approved=required_approval(values),
            append=values.get("append", False),
        )
    if method == "projects.checkWorkerMcp":
        return application.check_worker_mcp_connection(
            project_name, required_string(values, "serverId"), expected_revision=required_integer(values, "expectedRevision"),
        )
    if method == "projects.updateDotnet":
        return application.update_dotnet(project_name, optional_string(values, "executable"))
    if method == "projects.capabilities":
        return application.project_capabilities(project_name)
    if method == "projects.codeStyleProfile":
        return application.code_style_profile(project_name)
    if method == "projects.previewCodeStylePreference":
        return application.preview_code_style_preference(project_name, code_style_preference(values))
    if method == "projects.updateCodeStylePreference":
        return application.update_code_style_preference(
            project_name,
            code_style_preference(values),
            required_integer(values, "expectedRevision"),
            approved=required_approval(values),
        )
    if method == "projects.workspaceLocation":
        return application.workspace_location(project_name)
    if method == "projects.checkDotnet":
        return application.check_dotnet(project_name, optional_string(values, "runId"), optional_string(values, "taskId"))
    if method == "projects.remove":
        return application.remove_project(project_name, approved=required_approval(values))
    if method == "projects.updatePlanningSource":
        return application.update_planning_source(project_name, optional_string(values, "sourceRoot") or None)
    if method == "projects.updateMain":
        return application.update_main(project_name, approved=required_approval(values))
    if method == "projects.mainChanges":
        return application.main_changes(project_name)
    if method == "projects.refreshMainRemote":
        return application.main_changes(project_name, refresh_remote=True)
    if method == "projects.mainChangeDiff":
        return application.main_change_diff(
            project_name,
            required_string(values, "snapshotId"),
            required_path_string(values, "path"),
            required_string(values, "mode"),
        )
    if method in {"projects.commitMainChanges", "projects.commitAndPushMainChanges"}:
        selections = main_change_selections(values)
        arguments = (
            project_name,
            required_string(values, "snapshotId"),
            selections,
            required_string(values, "message"),
        )
        if method == "projects.commitMainChanges":
            return application.commit_main_changes(*arguments, approved=required_approval(values))
        return application.commit_and_push_main_changes(*arguments, approved=required_approval(values))
    if method == "projects.pushMainCommits":
        return application.push_main_commits(
            project_name, required_string(values, "snapshotId"), approved=required_approval(values)
        )
    if method == "providers.planning":
        return application.planning_provider_choices(project_name)
    if method == "providers.execution":
        return application.execution_provider_choices(project_name, string_list(values, "capabilities"))
    if method == "providers.status":
        return application.provider_statuses(project_name)
    raise RpcError("method_not_found", f"unsupported RPC method: {method}")


ROUTES: dict[str, RpcRoute] = {
    "projects.list": RpcRoute(RequestScope.GLOBAL, handle_projects),
    "projects.inspectGitReadiness": RpcRoute(RequestScope.GLOBAL, handle_projects),
    "projects.previewGitInitialization": RpcRoute(RequestScope.GLOBAL, handle_projects),
    "projects.initializeGit": RpcRoute(RequestScope.GLOBAL, handle_projects),
    "projects.previewInitialCommit": RpcRoute(RequestScope.GLOBAL, handle_projects),
    "projects.createInitialCommit": RpcRoute(RequestScope.GLOBAL, handle_projects),
    "projects.add": RpcRoute(RequestScope.GLOBAL, handle_projects),
    "projects.workerMcp": RpcRoute(RequestScope.PROJECT, handle_projects),
    "projects.updateWorkerMcp": RpcRoute(RequestScope.PROJECT, handle_projects),
    "projects.checkWorkerMcp": RpcRoute(RequestScope.PROJECT, handle_projects),
    "projects.updateDotnet": RpcRoute(RequestScope.PROJECT, handle_projects),
    "projects.capabilities": RpcRoute(RequestScope.PROJECT, handle_projects),
    "projects.codeStyleProfile": RpcRoute(RequestScope.PROJECT, handle_projects),
    "projects.previewCodeStylePreference": RpcRoute(RequestScope.PROJECT, handle_projects),
    "projects.updateCodeStylePreference": RpcRoute(RequestScope.PROJECT, handle_projects),
    "projects.workspaceLocation": RpcRoute(RequestScope.PROJECT, handle_projects),
    "projects.checkDotnet": RpcRoute(RequestScope.PROJECT, handle_projects),
    "projects.remove": RpcRoute(RequestScope.PROJECT, handle_projects),
    "projects.updatePlanningSource": RpcRoute(RequestScope.PROJECT, handle_projects),
    "projects.updateMain": RpcRoute(RequestScope.PROJECT, handle_projects),
    "projects.mainChanges": RpcRoute(RequestScope.PROJECT, handle_projects),
    "projects.refreshMainRemote": RpcRoute(RequestScope.PROJECT, handle_projects),
    "projects.mainChangeDiff": RpcRoute(RequestScope.PROJECT, handle_projects),
    "projects.commitAndPushMainChanges": RpcRoute(RequestScope.PROJECT, handle_projects),
    "projects.commitMainChanges": RpcRoute(RequestScope.PROJECT, handle_projects),
    "projects.pushMainCommits": RpcRoute(RequestScope.PROJECT, handle_projects),
    "providers.planning": RpcRoute(RequestScope.PROJECT, handle_projects),
    "providers.execution": RpcRoute(RequestScope.PROJECT, handle_projects),
    "providers.status": RpcRoute(RequestScope.PROJECT, handle_projects),
}
