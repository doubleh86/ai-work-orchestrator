"""Entry point for the frozen desktop backend and MCP server."""

import sys


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["mcp"]:
        from ai_orchestrator.cli import main as cli_main

        return cli_main(args)
    from ai_orchestrator.desktop_rpc import main as desktop_main

    return desktop_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
