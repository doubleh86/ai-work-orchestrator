from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def test_stdio_applies_source_changes_without_reconnecting(tmp_path: Path) -> None:
    pytest.importorskip("mcp")
    from anyio import Event, fail_after, run
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.types import ServerNotification, ToolListChangedNotification

    root = Path(__file__).resolve().parents[1]
    source = tmp_path / "src" / "ai_orchestrator"
    shutil.copytree(root / "src" / "ai_orchestrator", source, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(root / "pyproject.toml", tmp_path / "pyproject.toml")
    server_file = source / "mcp_server.py"
    original = server_file.read_text(encoding="utf-8")
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "ai_orchestrator", "--registry", str(tmp_path / "projects.json"), "mcp", "--watch-source"],
        env={"PYTHONPATH": str(source.parent), "TEMP": str(tmp_path), "TMP": str(tmp_path)},
    )

    async def scenario() -> None:
        changed = Event()

        async def handle(message: object) -> None:
            if isinstance(message, ServerNotification) and isinstance(message.root, ToolListChangedNotification):
                changed.set()

        async with stdio_client(parameters) as (reader, writer), ClientSession(reader, writer, message_handler=handle) as client:
            initialized = await client.initialize()
            assert initialized.capabilities.tools.listChanged is True
            tools = (await client.list_tools()).tools
            assert any(tool.name == "list_projects" for tool in tools)
            assert "repair_and_continue" not in {tool.name for tool in tools}
            initial = await client.call_tool("list_projects", {})
            assert initial.structuredContent["projects"] == []

            updated = original.replace("List projects registered", "Find projects registered").replace(
                "return await to_thread.run_sync(operations.projects)",
                "import os\n        return {'projects': [], 'revision': 'updated', 'pid': os.getpid()}",
            )
            server_file.write_text(updated, encoding="utf-8")
            await changed.wait()
            tools = (await client.list_tools()).tools
            assert next(tool.description for tool in tools if tool.name == "list_projects").startswith("Find projects registered")
            result = await client.call_tool("list_projects", {})
            assert result.structuredContent["revision"] == "updated"
            repeated = await client.call_tool("list_projects", {})
            assert repeated.structuredContent == result.structuredContent

            server_file.write_text("invalid Python source", encoding="utf-8")
            failed = await client.call_tool("list_projects", {})
            assert failed.isError
            assert "현재 MCP 소스를 실행하지 못했습니다" in failed.content[0].text

            server_file.write_text(updated.replace("'updated'", "'restored'"), encoding="utf-8")
            recovered = await client.call_tool("list_projects", {})
            assert recovered.structuredContent["revision"] == "restored"

    async def bounded_scenario() -> None:
        with fail_after(60):
            await scenario()

    run(bounded_scenario)


@pytest.mark.parametrize("write_args", [["--allow-write"], ["--projects-root", "."]])
def test_watch_source_rejects_write_options(write_args: list[str]) -> None:
    pytest.importorskip("mcp")
    result = subprocess.run([sys.executable, "-m", "ai_orchestrator", "mcp", "--watch-source", *write_args], capture_output=True, timeout=20)
    assert result.returncode == 2
    assert b"--watch-source" in result.stderr
