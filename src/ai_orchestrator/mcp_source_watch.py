"""Keep a development MCP connection open while reading updated Python source."""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from anyio import TASK_STATUS_IGNORED, Event, Lock, create_task_group, fail_after, run, sleep
from anyio.abc import TaskStatus
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server import NotificationOptions, Server
from mcp.server.stdio import stdio_server
from mcp.shared.exceptions import McpError
from mcp.shared.message import SessionMessage
from mcp.types import CONNECTION_CLOSED, INTERNAL_ERROR, CallToolResult, ErrorData, JSONRPCMessage, JSONRPCNotification, Tool


_LOGGER = logging.getLogger(__name__)
_SourceRevision = dict[Path, tuple[int, int, int]]


@dataclass(slots=True)
class _Worker:
    client: ClientSession
    tools: list[Tool]
    stop: Event
    finished: Event


def _source_revision(source: Path) -> _SourceRevision:
    revision = {}
    for path in source.rglob("*.py"):
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue  # An editor can replace a file while we are enumerating it.
        revision[path] = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
    return revision


async def _run_worker(parameters: StdioServerParameters, *, task_status: TaskStatus[_Worker] = TASK_STATUS_IGNORED) -> None:
    stop, finished = Event(), Event()
    started = False
    try:
        async with stdio_client(parameters) as (reader, writer), ClientSession(reader, writer) as client:
            with fail_after(15):
                await client.initialize()
                tools = (await client.list_tools()).tools
            task_status.started(_Worker(client, tools, stop, finished))
            started = True
            await stop.wait()
    except Exception as exc:
        _LOGGER.warning("MCP source worker failed", exc_info=exc)
        if not started:
            raise McpError(ErrorData(code=INTERNAL_ERROR, message="현재 MCP 소스를 실행하지 못했습니다. MCP 서버 로그를 확인해 주세요.")) from exc
    finally:
        finished.set()


async def _serve(source: Path, parameters: StdioServerParameters, name: str, instructions: str) -> None:
    server = Server(name, instructions=instructions)
    lock = Lock()

    async with stdio_server() as (reader, writer), create_task_group() as tasks:
        worker: _Worker | None = None
        catalog: list[Tool] | None = None
        attempted_revision: _SourceRevision | None = None

        async def current_worker(revision: _SourceRevision) -> _Worker:
            nonlocal worker, catalog, attempted_revision
            if worker is not None and revision == attempted_revision and not worker.finished.is_set():
                return worker
            if worker is not None:
                worker.stop.set()
                await worker.finished.wait()
                worker = None
            attempted_revision = revision
            worker = await tasks.start(_run_worker, parameters)
            previous, catalog = catalog, worker.tools
            if previous is not None and catalog != previous:
                notification = JSONRPCNotification(method="notifications/tools/list_changed", jsonrpc="2.0")
                await writer.send(SessionMessage(JSONRPCMessage(notification)))
            return worker

        @server.list_tools()
        async def list_tools() -> list[Tool]:
            async with lock:
                return (await current_worker(_source_revision(source))).tools

        @server.call_tool(validate_input=False)
        async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
            async with lock:
                active = await current_worker(_source_revision(source))
                try:
                    return await active.client.call_tool(name, arguments)
                except McpError as exc:
                    if exc.error.code == CONNECTION_CLOSED:
                        active.stop.set()
                        await active.finished.wait()
                    raise

        async def watch() -> None:
            while True:
                await sleep(1)
                async with lock:
                    if attempted_revision is None:
                        continue
                    try:
                        revision = _source_revision(source)
                        if revision != attempted_revision:
                            await current_worker(revision)
                    except McpError:
                        continue  # The worker logged this revision. Retry on the next edit or explicit request.
                    except OSError as exc:
                        _LOGGER.warning("Could not check the MCP source for changes: %s", exc)

        tasks.start_soon(watch)
        try:
            await server.run(reader, writer, server.create_initialization_options(NotificationOptions(tools_changed=True)))
        finally:
            async with lock:
                if worker is not None:
                    worker.stop.set()
                    await worker.finished.wait()
                tasks.cancel_scope.cancel()


def serve_source_checkout(registry_path: Path, *, name: str, instructions: str) -> None:
    source = Path(__file__).resolve().parent
    if getattr(sys, "frozen", False) or source.parent.name != "src" or not (source.parent.parent / "pyproject.toml").is_file():
        raise ValueError("--watch-source는 소스 체크아웃에서 설치한 MCP에서 사용할 수 있습니다.")

    # A fresh cache location also bypasses stale .pyc files for same-second edits.
    with TemporaryDirectory(prefix="orchestrator-mcp-cache-") as cache:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-B", "-P", "-X", f"pycache_prefix={cache}", "-m", "ai_orchestrator", "--registry", str(registry_path), "mcp"],
            env={"PYTHONPATH": str(source.parent)},
        )
        run(_serve, source, parameters, name, instructions)
