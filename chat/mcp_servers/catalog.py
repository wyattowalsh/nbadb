from __future__ import annotations

from nbadb.chat.mcp import catalog as catalog_tools

SERVER_NAME = "nbadb-catalog"


def search_catalog(query: str, *, limit: int = 12) -> list[dict]:
    return catalog_tools.search_catalog(query, limit=limit)
