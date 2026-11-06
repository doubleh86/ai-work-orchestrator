"""Entry point for the frozen desktop backend and MCP server."""

import sys
from subprocess import SubprocessError


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if sys.platform == "win32" and getattr(sys, "frozen", False):
        if args == ["mcp-connect"]:
            from ai_orchestrator.mcp_bundle import connect_packaged_mcp

            try:
                registered = connect_packaged_mcp()
            except (OSError, ValueError, RuntimeError, SubprocessError):
                print("registration_failed")
                return 2
            if not registered:
                print("codex_missing")
                return 2
            print("registered")
            return 0
        if args[:1] == ["mcp-auto"]:
            from ai_orchestrator.mcp_bundle import run_packaged_mcp

            return run_packaged_mcp(args[1:])
        if args == ["mcp-stage"]:
            from ai_orchestrator.mcp_bundle import refresh_packaged_mcp

            try:
                refresh_packaged_mcp()
            except (OSError, ValueError):
                return 2
            return 0
    if args[:1] == ["mcp"]:
        from ai_orchestrator.cli import main as cli_main

        return cli_main(args)
    from ai_orchestrator.desktop_rpc import main as desktop_main

    return desktop_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
