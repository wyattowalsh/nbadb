from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from nbadb.chat.mcp import catalog as catalog_tools

SERVER_NAME = "nbadb-catalog"
server = FastMCP(SERVER_NAME)


@server.tool()
def search_catalog(query: str, limit: int = 12) -> list[dict[str, Any]]:
    return catalog_tools.search_catalog(query, limit=limit)


if __name__ == "__main__":
    server.run(transport="stdio")
