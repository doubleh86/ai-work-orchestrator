"""Check the bundled backend in desktop and MCP modes with isolated user data."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from anyio import fail_after, run
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def check_mcp(executable: Path, directory: Path, env: dict[str, str]) -> None:
    for allow_write in (False, True):
        args = ["mcp", "--allow-write"] if allow_write else ["mcp"]
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
    with tempfile.TemporaryDirectory(prefix="MCP 실행 검사 ", dir=executable.parent) as temporary:
        directory = Path(temporary)
        system_root = Path(os.environ["SystemRoot"])
        env = {"SYSTEMROOT": str(system_root), "WINDIR": str(system_root), "PATH": str(system_root / "System32"),
               **dict.fromkeys(("APPDATA", "LOCALAPPDATA", "HOME", "USERPROFILE", "TEMP", "TMP"), str(directory))}
        hello = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "system.hello"}) + "\n"
        rpc = subprocess.run([str(executable)], input=hello, cwd=directory, env=env, capture_output=True,
                             text=True, encoding="utf-8", timeout=30, check=True)
        response = json.loads(rpc.stdout)
        if response.get("id") != 1 or "result" not in response:
            raise RuntimeError("Bundled desktop backend did not answer system.hello")
        run(check_mcp, executable, directory, env)
    print("Bundled desktop RPC and MCP read/write tool discovery passed")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
