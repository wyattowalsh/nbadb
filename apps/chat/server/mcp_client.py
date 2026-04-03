from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from langchain_mcp_adapters.client import MultiServerMCPClient
from loguru import logger

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
    # Merge user-configured MCP servers (reject in demo mode and on name collisions)
    if settings.public_demo_mode and settings.extra_mcp_servers:
        logger.info("Ignoring extra_mcp_servers in public demo mode")
    elif settings.extra_mcp_servers:
        builtin_names = frozenset(servers.keys())
        for key, val in settings.extra_mcp_servers.items():
            if key in builtin_names:
                logger.warning("Ignoring extra_mcp_server {!r} — collides with built-in name", key)
                continue
            servers[key] = val

    if settings.extra_mcp_servers and not settings.public_demo_mode:
        logger.info(
            "Loaded {} extra MCP server(s) from config: {}",
            len(settings.extra_mcp_servers),
            list(settings.extra_mcp_servers.keys()),
        )

    client = MultiServerMCPClient(servers)
    tools = await client.get_tools()
    return tools, client
