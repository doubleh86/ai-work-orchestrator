"""Check the bundled backend in desktop and MCP modes with isolated user data."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from anyio import fail_after, run
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def check_mcp(executable: Path, directory: Path, env: dict[str, str], commands: tuple[list[str], ...]) -> None:
    for args in commands:
        allow_write = "--allow-write" in args
        params = StdioServerParameters(command=str(executable), args=args, cwd=directory, env=env)
        with fail_after(30):
            async with stdio_client(params) as (reader, writer), ClientSession(reader, writer) as client:
                await client.initialize()
                tools = {tool.name for tool in (await client.list_tools()).tools}
                write_tools = {"approve_scope_and_retry", "apply_local_main", "repair_and_continue"}
                if "list_projects" not in tools or tools & write_tools != (write_tools if allow_write else set()):
                    raise RuntimeError(f"Unexpected MCP tool availability: {sorted(tools)}")
                result = await client.call_tool("list_projects", {})
                if result.isError or not result.structuredContent or result.structuredContent.get("projects") != []:
                    raise RuntimeError("MCP did not read the empty test registry")


def main(executable: Path) -> None:
    executable = executable.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="MCP 실행 검사 ") as temporary:
        directory = Path(temporary)
        system_root = Path(os.environ["SystemRoot"])
        env = {"SYSTEMROOT": str(system_root), "WINDIR": str(system_root), "PATH": str(system_root / "System32"),
               **dict.fromkeys(("APPDATA", "LOCALAPPDATA", "HOME", "USERPROFILE", "TEMP", "TMP"), str(directory))}
        requests = "".join(json.dumps({"jsonrpc": "2.0", "id": index, "method": method}) + "\n"
                           for index, method in enumerate(("system.hello", "auth.codex.status"), 1))
        rpc = subprocess.run([str(executable)], input=requests, cwd=directory, env=env, capture_output=True,
                             text=True, encoding="utf-8", timeout=30, check=True)
        responses = {item["id"]: item for item in map(json.loads, rpc.stdout.splitlines())}
        if "result" not in responses.get(1, {}):
            raise RuntimeError("Bundled desktop backend did not answer system.hello")
        if responses.get(2, {}).get("result", {}).get("error_code") != "auth_runtime_missing":
            raise RuntimeError("Packaged backend should report that an external Codex CLI is needed")
        subprocess.run([str(executable), "mcp-stage"], cwd=directory, env=env, timeout=15, check=True)
        if (directory / "ai-work-orchestrator" / "mcp").exists():
            raise RuntimeError("App startup prepared MCP before a connection was registered")
        run(check_mcp, executable, directory, env, (["mcp"], ["mcp", "--allow-write"], ["mcp-auto"]))
        next_runtime = directory / "ai-work-orchestrator" / "mcp" / "versions" / "999.0.0"
        next_runtime.mkdir(parents=True)
        shutil.copy2(executable, next_runtime / executable.name)
        shutil.copytree(executable.parent / "_internal", next_runtime / "_internal")
        run(check_mcp, executable, directory, env, (["mcp-auto"],))
    print("Bundled desktop RPC and MCP read/write tool discovery passed")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
