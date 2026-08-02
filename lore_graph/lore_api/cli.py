from __future__ import annotations

import argparse


def main() -> int:
    """Run the packaged Cradle lore MCP server over stdio."""
    parser = argparse.ArgumentParser(
        prog="cradle-lore-mcp",
        description="Source-grounded MCP server for Unsouled and Soulsmith",
    )
    parser.parse_args()
    from .app import mcp

    mcp.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
