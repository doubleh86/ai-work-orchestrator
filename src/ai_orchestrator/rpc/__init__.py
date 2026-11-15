"""Validated, allowlisted local JSON Lines request routing."""

from ..application import OrchestratorApplication
from ..application.errors import ApplicationError as RpcError
from . import connections, execution, integration, planning, projects, runs
from .contracts import RequestScope, RpcRequest, RpcRoute
from .parameters import object_params, required_string

RPC_ROUTES: dict[str, RpcRoute] = {
    **connections.ROUTES,
    **projects.ROUTES,
    **planning.ROUTES,
    **execution.ROUTES,
    **integration.ROUTES,
    **runs.ROUTES,
}


def dispatch(application: OrchestratorApplication, method: str, params: object = None) -> object:
    values = object_params(params)
    route = RPC_ROUTES.get(method)
    if route is None:
        raise RpcError("method_not_found", f"unsupported RPC method: {method}")
    project_name = required_string(values, "projectName") if route.scope != RequestScope.GLOBAL else ""
    run_id = required_string(values, "runId") if route.scope == RequestScope.RUN else ""
    return route.handler(application, RpcRequest(method, values, project_name, run_id))
