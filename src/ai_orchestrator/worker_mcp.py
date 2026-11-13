"""Project-scoped MCP definitions and adapters for worker AI clients."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import time
from contextlib import AsyncExitStack, ExitStack, contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterator, Mapping, Sequence
from urllib.parse import parse_qsl, urlsplit

from .app_paths import application_config_root
from .execution_control import CancellationSignal, ExecutionStopped


class WorkerMcpError(ValueError):
    pass


_NAME = re.compile(r"[A-Za-z0-9_-]{1,48}\Z")
_VARIABLE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}\Z")
_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}\Z")
_PROVIDER_CREDENTIALS = frozenset({
    "OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "CODEX_AUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "GOOGLE_APPLICATION_CREDENTIALS",
})


def _text(value: object, limit: int = 4096) -> str:
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        raise WorkerMcpError("도구 연결에 올바른 문자열을 입력해 주세요.")
    return value


def _references(raw: object) -> tuple[tuple[str, str], ...]:
    if raw is None:
        return ()
    if isinstance(raw, list):
        raw = {name: name for name in raw if isinstance(name, str)} if all(isinstance(name, str) for name in raw) else None
    if not isinstance(raw, dict) or len(raw) > 32:
        raise WorkerMcpError("환경변수 연결 형식을 확인해 주세요.")
    result = []
    for name, source in raw.items():
        if not isinstance(name, str) or not _VARIABLE.fullmatch(name) or not isinstance(source, str) or not _VARIABLE.fullmatch(source):
            raise WorkerMcpError("키 원문 대신 환경변수 이름으로 연결해 주세요.")
        if source.upper() in _PROVIDER_CREDENTIALS:
            raise WorkerMcpError("작업 AI 인증 대신 이 도구 전용 환경변수를 연결해 주세요.")
        result.append((name, source))
    return tuple(sorted(result))


@dataclass(frozen=True, slots=True)
class WorkerMcpServer:
    id: str
    transport: str
    label: str = ""
    command: str = ""
    args: tuple[str, ...] = ()
    url: str = ""
    env_vars: tuple[tuple[str, str], ...] = ()
    bearer_token_env_var: str = ""
    env_http_headers: tuple[tuple[str, str], ...] = ()
    enabled_tools: tuple[str, ...] | None = None
    enabled: bool = True
    exclusive: bool = True

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["args"] = list(self.args)
        result["env_vars"] = dict(self.env_vars)
        result["env_http_headers"] = dict(self.env_http_headers)
        result["enabled_tools"] = list(self.enabled_tools) if self.enabled_tools is not None else None
        return result

    @classmethod
    def from_dict(cls, raw: object, *, server_id: str = "") -> WorkerMcpServer:
        if not isinstance(raw, dict):
            raise WorkerMcpError("도구 연결 설정은 JSON 객체여야 합니다.")
        allowed = {"id", "label", "transport", "type", "command", "args", "url", "env_vars", "env", "bearer_token_env_var",
                   "env_http_headers", "headers", "enabled_tools", "enabled", "exclusive"}
        if set(raw) - allowed:
            raise WorkerMcpError("지원하지 않는 연결 옵션이 있습니다. 로컬 실행 또는 HTTP 연결 설정을 확인해 주세요.")
        identity = _text(server_id or raw.get("id", ""), 48)
        if not _NAME.fullmatch(identity):
            raise WorkerMcpError("연결 이름은 영문·숫자·밑줄·하이픈으로 입력해 주세요.")
        transport = raw.get("transport", raw.get("type", "http" if raw.get("url") else "stdio"))
        if transport == "streamable-http":
            transport = "http"
        if not isinstance(transport, str) or transport not in {"stdio", "http"}:
            raise WorkerMcpError("현재 로컬 실행(stdio)과 Streamable HTTP 연결을 지원합니다.")
        command, url = _text(raw.get("command", "")), _text(raw.get("url", ""))
        args = raw.get("args", [])
        if not isinstance(args, list) or len(args) > 64:
            raise WorkerMcpError("실행 인자는 문자열 목록으로 입력해 주세요.")
        arguments = tuple(_text(arg) for arg in args)
        for argument in (command, *arguments):
            secret_argument = r"(?i)(?:^--(?:api[-_]key|access[-_]token|token|password|secret)(?:=|$)|Bearer\s+|sk-[A-Za-z0-9_-]{16,})"
            if re.search(secret_argument, argument):
                raise WorkerMcpError("실행 인자에 키를 넣지 말고 환경변수 참조로 연결해 주세요.")
        if transport == "stdio" and (not command.strip() or url):
            raise WorkerMcpError("로컬 도구의 실행 파일과 인자를 확인해 주세요.")
        if transport == "http":
            try:
                parsed = urlsplit(url)
                parsed.port
            except ValueError as exc:
                raise WorkerMcpError("HTTP 주소 형식을 확인해 주세요.") from exc
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
                    or parsed.fragment or command or arguments or any(
                        re.search(r"(?i)token|key|secret|password|credential|authorization|^auth$", key)
                        for key, _ in parse_qsl(parsed.query)
                    )):
                raise WorkerMcpError("HTTP 주소를 확인해 주세요. 인증 키는 주소에 넣지 않고 환경변수로 연결합니다.")
        references = dict(_references(raw.get("env_vars")))
        env = raw.get("env", {})
        if not isinstance(env, dict):
            raise WorkerMcpError("환경변수 연결 형식을 확인해 주세요.")
        for name, value in env.items():
            match = _REFERENCE.fullmatch(value) if isinstance(value, str) else None
            if not match or name in references:
                raise WorkerMcpError("env 값은 키 원문 대신 ${환경변수이름}으로 입력해 주세요.")
            references[name] = match[1]
        references = _references(references)
        header_refs = raw.get("env_http_headers", {})
        if not isinstance(header_refs, dict) or len(header_refs) > 32:
            raise WorkerMcpError("HTTP 헤더의 환경변수 연결을 확인해 주세요.")
        headers = dict(header_refs)
        bearer = _text(raw.get("bearer_token_env_var", ""), 128)
        supplied_headers = raw.get("headers", {})
        if not isinstance(supplied_headers, dict):
            raise WorkerMcpError("HTTP 헤더 연결을 확인해 주세요.")
        for name, value in supplied_headers.items():
            if (isinstance(name, str) and name.casefold() == "authorization"
                    and isinstance(value, str) and value.startswith("Bearer ")):
                match = _REFERENCE.fullmatch(value[7:])
                if not match or bearer:
                    raise WorkerMcpError("인증 키 대신 Bearer ${환경변수이름}으로 연결해 주세요.")
                bearer = match[1]
            else:
                match = _REFERENCE.fullmatch(value) if isinstance(value, str) else None
                if not match or name in headers:
                    raise WorkerMcpError("HTTP 헤더 값은 ${환경변수이름}으로 연결해 주세요.")
                headers[name] = match[1]
        if bearer and not _VARIABLE.fullmatch(bearer):
            raise WorkerMcpError("인증 키의 환경변수 이름을 확인해 주세요.")
        for name, source in headers.items():
            if (not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,64}", name)
                    or not isinstance(source, str) or not _VARIABLE.fullmatch(source)):
                raise WorkerMcpError("HTTP 헤더의 환경변수 연결을 확인해 주세요.")
        if len({name.casefold() for name in headers}) != len(headers):
            raise WorkerMcpError("중복된 HTTP 헤더 연결이 있습니다.")
        if bearer.upper() in _PROVIDER_CREDENTIALS or any(source.upper() in _PROVIDER_CREDENTIALS for source in headers.values()):
            raise WorkerMcpError("작업 AI 인증 대신 이 도구 전용 환경변수를 연결해 주세요.")
        if bearer and any(name.casefold() == "authorization" for name in headers):
            raise WorkerMcpError("Authorization 연결 방식은 하나만 선택해 주세요.")
        if transport == "stdio" and (bearer or headers) or transport == "http" and references:
            raise WorkerMcpError("로컬 실행과 HTTP의 환경변수 옵션을 구분해 주세요.")
        tools = raw.get("enabled_tools")
        if tools is not None and (not isinstance(tools, list) or len(tools) > 128 or any(
            not isinstance(tool, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,128}", tool) for tool in tools
        )):
            raise WorkerMcpError("사용할 도구 이름을 문자열 목록으로 입력해 주세요.")
        for flag in ("enabled", "exclusive"):
            if type(raw.get(flag, True)) is not bool:
                raise WorkerMcpError("도구 연결의 켜기/끄기 값을 확인해 주세요.")
        return cls(identity, transport, _text(raw.get("label", identity), 80), command, arguments, url, references, bearer,
                   tuple(sorted(headers.items())), tuple(tools) if tools is not None else None,
                   raw.get("enabled", True), raw.get("exclusive", True))

    def variable_names(self) -> set[str]:
        names = {source for _, source in (*self.env_vars, *self.env_http_headers)}
        return names | ({self.bearer_token_env_var} if self.bearer_token_env_var else set())

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()


def parse_mcp_servers(raw: object) -> tuple[WorkerMcpServer, ...]:
    if isinstance(raw, str):
        if len(raw) > 65536:
            raise WorkerMcpError("도구 연결 설정이 너무 큽니다.")
        try:
            raw = json.loads(raw)
        except ValueError as exc:
            raise WorkerMcpError("MCP 연결 설정의 JSON 형식을 확인해 주세요.") from exc
    if isinstance(raw, dict):
        raw = raw.get("mcpServers", raw.get("mcp_servers", raw))
        if not isinstance(raw, dict) or len(raw) > 16:
            raise WorkerMcpError("프로젝트에는 도구 연결을 최대 16개까지 등록할 수 있습니다.")
        servers = tuple(WorkerMcpServer.from_dict(value, server_id=name) for name, value in raw.items())
    elif isinstance(raw, list) and len(raw) <= 16:
        servers = tuple(WorkerMcpServer.from_dict(item) for item in raw)
    else:
        raise WorkerMcpError("도구 연결 목록을 확인해 주세요.")
    if len({server.id.casefold() for server in servers}) != len(servers):
        raise WorkerMcpError("중복된 도구 연결 이름이 있습니다.")
    return servers


def secret_values(servers: Sequence[WorkerMcpServer], environment: Mapping[str, str] | None = None) -> tuple[str, ...]:
    environment = os.environ if environment is None else environment
    values = {environment[name] for server in servers for name in server.variable_names() if environment.get(name)}
    return tuple(sorted(values, key=len, reverse=True))


def redact_mcp_output(value: str, secrets: Sequence[str]) -> str:
    for secret in secrets:
        value = value.replace(secret, "[REDACTED]")
    return value


def redact_mcp_data(value: object, secrets: Sequence[str]) -> object:
    if isinstance(value, str):
        return redact_mcp_output(value, secrets)
    if isinstance(value, dict):
        return {redact_mcp_output(key, secrets) if isinstance(key, str) else key: redact_mcp_data(item, secrets)
                for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_mcp_data(item, secrets) for item in value]
    return value


def _environment(servers: Sequence[WorkerMcpServer]) -> dict[str, str]:
    result = {}
    for server in servers:
        for name in server.variable_names():
            if name.upper() in _PROVIDER_CREDENTIALS:
                raise WorkerMcpError("작업 AI 인증 대신 이 도구 전용 환경변수를 연결해 주세요.")
            value = os.environ.get(name)
            if not value:
                raise WorkerMcpError(f"도구 연결에 필요한 환경변수가 없습니다: {name}")
            result[name] = value
    return result


def _expand(value: str, workspace: Path, project: Path) -> str:
    return value.replace("{worktree}", str(workspace.resolve())).replace("{project_root}", str(project.resolve()))


def codex_mcp_config(servers: Sequence[WorkerMcpServer], workspace: Path, project: Path) -> dict[str, object]:
    environment = _environment(servers)
    result = {}
    for server in servers:
        config: dict[str, object] = {"enabled": True, "required": True, "startup_timeout_sec": 15}
        if server.transport == "stdio":
            config.update(command=_expand(server.command, workspace, project), args=[_expand(arg, workspace, project) for arg in server.args],
                          cwd=str(workspace.resolve()), env={name: environment[source] for name, source in server.env_vars})
        else:
            headers = {name: environment[source] for name, source in server.env_http_headers}
            if server.bearer_token_env_var:
                headers["Authorization"] = "Bearer " + environment[server.bearer_token_env_var]
            config.update(url=server.url, http_headers=headers)
        if server.enabled_tools is not None:
            config["enabled_tools"] = list(server.enabled_tools)
        result[server.id] = config
    return {"mcp_servers": result}


def claude_mcp_options(servers: Sequence[WorkerMcpServer], workspace: Path, project: Path) -> tuple[list[str], dict[str, str]]:
    if any(server.enabled_tools is not None for server in servers):
        raise WorkerMcpError("도구별 허용 목록은 Codex에서 지원합니다. Claude에서는 연결 전체를 허용하거나 이 연결을 꺼 주세요.")
    environment = _environment(servers)
    aliases = {name: f"AI_ORCHESTRATOR_MCP_{index}" for index, name in enumerate(sorted(environment))}
    injected = {aliases[name]: value for name, value in environment.items()}
    entries = {}
    tools = []
    for server in servers:
        if server.transport == "stdio":
            entries[server.id] = {"type": "stdio", "command": _expand(server.command, workspace, project),
                                  "args": [_expand(arg, workspace, project) for arg in server.args],
                                  "env": {name: "${" + aliases[source] + "}" for name, source in server.env_vars}}
        else:
            headers = {name: "${" + aliases[source] + "}" for name, source in server.env_http_headers}
            if server.bearer_token_env_var:
                headers["Authorization"] = "Bearer ${" + aliases[server.bearer_token_env_var] + "}"
            entries[server.id] = {"type": "http", "url": server.url, "headers": headers}
        tools.extend(f"mcp__{server.id}__{tool}" for tool in (server.enabled_tools if server.enabled_tools is not None else ("*",)))
    options = ["--strict-mcp-config", "--mcp-config", json.dumps({"mcpServers": entries})]
    if tools:
        options.extend(["--allowedTools", ",".join(tools)])
    return options, injected


def configure_claude_mcp(command: list[str], servers: Sequence[WorkerMcpServer], workspace: Path, project: Path) -> dict[str, str]:
    if any(part == "--mcp-config" or part.startswith("--mcp-config=") or part == "--strict-mcp-config" for part in command):
        raise WorkerMcpError("작업 AI 명령에 MCP 설정이 이미 있습니다. 프로젝트 도구 연결과 중복되지 않게 설정해 주세요.")
    options, environment = claude_mcp_options(servers, workspace, project)
    if "--allowedTools" in options and "--allowedTools" in command:
        index = command.index("--allowedTools") + 1
        if index >= len(command) or command[index].startswith("--"):
            raise WorkerMcpError("Claude의 도구 권한 설정을 확인해 주세요.")
        command[index] += "," + options[-1]
        options = options[:-2]
    command.extend(options)
    return environment


def check_mcp_connection(server: WorkerMcpServer, workspace: Path, project: Path) -> dict[str, object]:
    """Initialize and list tools, never invoke a tool to check a connection."""
    if not server.enabled:
        return {"id": server.id, "status": "error", "message": "사용 중지된 연결입니다. 사용하기를 켠 뒤 확인해 주세요."}
    try:
        from anyio import fail_after, run
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mcp.client.streamable_http import streamable_http_client
        import httpx

        config = codex_mcp_config((server,), workspace, project)["mcp_servers"][server.id]

        async def inspect() -> list[str]:
            with fail_after(15):
                async with AsyncExitStack() as stack:
                    if server.transport == "stdio":
                        null = stack.enter_context(open(os.devnull, "w"))
                        transport = stdio_client(StdioServerParameters(command=config["command"], args=config["args"],
                                                                       cwd=str(workspace), env=config["env"]), errlog=null)
                    else:
                        client = await stack.enter_async_context(httpx.AsyncClient(headers=config["http_headers"], timeout=15))
                        transport = streamable_http_client(server.url, http_client=client)
                    streams = await stack.enter_async_context(transport)
                    async with ClientSession(streams[0], streams[1]) as session:
                        await session.initialize()
                        names, cursor = [], None
                        for _ in range(8):
                            page = await session.list_tools(cursor=cursor)
                            names.extend(tool.name for tool in page.tools)
                            if len(names) > 512:
                                raise WorkerMcpError("도구 목록이 너무 큽니다.")
                            cursor = page.nextCursor
                            if cursor is None:
                                return names
                        raise WorkerMcpError("도구 목록이 너무 큽니다.")

        names = run(inspect)
        selected = names if server.enabled_tools is None else [name for name in names if name in server.enabled_tools]
        if server.enabled_tools is not None and set(server.enabled_tools) - set(names):
            raise WorkerMcpError("허용한 도구 이름과 서버의 도구 목록이 다릅니다.")
        return {"id": server.id, "status": "connected", "tool_count": len(selected), "message": "연결을 확인했습니다."}
    except WorkerMcpError as exc:
        return {"id": server.id, "status": "error", "message": str(exc)}
    except ImportError:
        return {"id": server.id, "status": "error", "message": "MCP 지원 패키지를 설치한 뒤 다시 확인해 주세요."}
    except Exception as exc:
        return {"id": server.id, "status": "error", "message": "연결하지 못했습니다. 실행 명령·주소·인증 환경변수를 확인해 주세요.",
                "diagnostic_type": type(exc).__name__}


@contextmanager
def worker_mcp_lease(
    servers: Sequence[WorkerMcpServer], *, cancel_signal: CancellationSignal | None = None,
    timeout_seconds: float | None = None, on_wait: Callable[[], None] | None = None,
) -> Iterator[None]:
    """Serialize shared external tools across backend processes."""
    with ExitStack() as stack:
        notified = False
        keys = {hashlib.sha256(json.dumps([s.transport, s.command, s.args, s.url]).encode()).hexdigest()
                for s in servers if s.exclusive}
        for key in sorted(keys):
            path = application_config_root() / "mcp-locks" / (key + ".lock")
            path.parent.mkdir(parents=True, exist_ok=True)
            stream = stack.enter_context(path.open("a+b"))
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            deadline = time.monotonic() + timeout_seconds if timeout_seconds is not None else None
            while True:
                if cancel_signal is not None and cancel_signal.is_set():
                    raise ExecutionStopped("도구 연결 대기 중 실행을 중지했습니다.",
                                           request_id=getattr(cancel_signal, "request_id", ""))
                try:
                    if os.name == "nt":
                        import msvcrt
                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                        raise
                    if deadline is not None and time.monotonic() >= deadline:
                        raise WorkerMcpError("연결한 도구를 다른 작업이 사용 중입니다. 작업이 끝난 뒤 다시 시도해 주세요.") from exc
                    if on_wait is not None and not notified:
                        on_wait()
                        notified = True
                    time.sleep(0.1)
        yield
