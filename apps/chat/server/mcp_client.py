from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from langchain_mcp_adapters.client import MultiServerMCPClient

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool
    from server.config import ChatSettings


async def setup_mcp_tools(
    settings: ChatSettings,
    session_id: str,
) -> tuple[list[BaseTool], MultiServerMCPClient]:
    """Set up MCP tool connections and return tools + client handle."""
    servers: dict[str, dict] = {
        "nbadb-sql": {
            "command": sys.executable,
            "args": ["-m", "mcp_servers.sql", str(settings.duckdb_path)],
            "transport": "stdio",
        },
        "nbadb-sandbox": {
            "command": sys.executable,
            "args": [
                "-m",
                "mcp_servers.sandbox",
                str(settings.duckdb_path),
                session_id,
            ],
            "transport": "stdio",
        },
    }
    # Merge user-configured MCP servers
    servers.update(settings.extra_mcp_servers)

    if settings.extra_mcp_servers:
        import logging

        logging.getLogger(__name__).warning(
            "Loading %d extra MCP server(s) from config: %s",
            len(settings.extra_mcp_servers),
            list(settings.extra_mcp_servers.keys()),
        )

    client = MultiServerMCPClient(servers)
    tools = await client.get_tools()
    return tools, client
