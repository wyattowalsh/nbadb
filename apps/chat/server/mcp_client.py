from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from langchain_mcp_adapters.client import MultiServerMCPClient

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from apps.chat.server.config import ChatSettings


async def setup_mcp_tools(settings: ChatSettings) -> list[BaseTool]:
    """Set up MCP tool connections and return all tools."""
    servers: dict[str, dict] = {
        "nbadb-sql": {
            "command": sys.executable,
            "args": ["-m", "apps.chat.mcp_servers.sql", str(settings.duckdb_path)],
            "transport": "stdio",
        },
    }
    # Merge user-configured MCP servers
    servers.update(settings.extra_mcp_servers)

    client = MultiServerMCPClient(servers)
    return await client.get_tools()
