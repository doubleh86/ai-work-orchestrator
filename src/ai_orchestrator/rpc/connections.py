from __future__ import annotations

from ..application import OrchestratorApplication
from ..application.errors import ApplicationError as RpcError
from .contracts import RPC_VERSION, RequestScope, RpcRequest, RpcRoute
from .parameters import required_string, string_list

def handle_connections(application: OrchestratorApplication, request: RpcRequest) -> object:
    method, values = request.method, request.params
    if method == "system.hello":
        return {"rpcVersion": RPC_VERSION, "application": "ai-work-orchestrator"}
    if method == "connections.externalGuide":
        from ..mcp_bundle import external_connection_guide

        return external_connection_guide(application.registry.path)
    if method == "connections.registerExternal":
        from ..mcp_bundle import register_external_connection

        return register_external_connection(required_string(values, "client"), application.registry.path)
    if method == "auth.codex.status":
        return application.codex_auth_status()
    if method == "providers.codexModels":
        return application.codex_model_settings()
    if method == "providers.updateCodexModels":
        return application.update_codex_model_settings(
            string_list(values, "models", required=True), expected_models=string_list(values, "expectedModels", required=True),
        )
    if method == "auth.claude.status":
        return application.claude_auth_status()
    if method == "auth.claude.setExecutable":
        return application.set_claude_executable(required_string(values, "path"))
    if method == "auth.claude.clearExecutable":
        return application.clear_claude_executable()
    if method == "providers.accountUsage":
        provider = required_string(values, "provider")
        if provider not in {"codex", "claude"}:
            raise RpcError("invalid_params", "provider must be codex or claude")
        return application.account_usage(provider)
    if method == "auth.codex.start":
        login_method = required_string(values, "method")
        if login_method not in {"browser", "device_code"}:
            raise RpcError("invalid_params", "Codex login method must be browser or device_code")
        return application.start_codex_auth(login_method, required_string(values, "requestId"))
    if method == "auth.codex.apiKey":
        if isinstance(values.get("apiKey"), str) and any(c in values["apiKey"] for c in ("\x00", "\n", "\r")):
            raise RpcError("invalid_params", "OpenAI API 키를 공백 없는 한 줄로 입력해 주세요.")
        api_key = required_string(values, "apiKey")
        if len(api_key) > 4096 or any(ord(character) < 33 or ord(character) > 126 for character in api_key):
            raise RpcError("invalid_params", "OpenAI API 키를 공백 없는 한 줄로 입력해 주세요.")
        return application.connect_codex_api_key(api_key, required_string(values, "requestId"))
    if method == "auth.codex.get":
        return application.codex_auth_attempt(required_string(values, "attemptId"))
    if method == "auth.codex.cancel":
        return application.cancel_codex_auth(required_string(values, "attemptId"))
    raise RpcError("method_not_found", f"unsupported RPC method: {method}")


ROUTES: dict[str, RpcRoute] = {
    "system.hello": RpcRoute(RequestScope.GLOBAL, handle_connections),
    "connections.externalGuide": RpcRoute(RequestScope.GLOBAL, handle_connections),
    "connections.registerExternal": RpcRoute(RequestScope.GLOBAL, handle_connections),
    "auth.codex.status": RpcRoute(RequestScope.GLOBAL, handle_connections),
    "auth.claude.status": RpcRoute(RequestScope.GLOBAL, handle_connections),
    "auth.claude.setExecutable": RpcRoute(RequestScope.GLOBAL, handle_connections),
    "auth.claude.clearExecutable": RpcRoute(RequestScope.GLOBAL, handle_connections),
    "providers.accountUsage": RpcRoute(RequestScope.GLOBAL, handle_connections),
    "providers.codexModels": RpcRoute(RequestScope.GLOBAL, handle_connections),
    "providers.updateCodexModels": RpcRoute(RequestScope.GLOBAL, handle_connections),
    "auth.codex.start": RpcRoute(RequestScope.GLOBAL, handle_connections),
    "auth.codex.apiKey": RpcRoute(RequestScope.GLOBAL, handle_connections),
    "auth.codex.get": RpcRoute(RequestScope.GLOBAL, handle_connections),
    "auth.codex.cancel": RpcRoute(RequestScope.GLOBAL, handle_connections),
}
