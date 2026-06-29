from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from nbadb.chat.mcp import memory as memory_tools
from nbadb.chat.memory import MemoryStore

SERVER_NAME = "nbadb-memory"
server = FastMCP(SERVER_NAME)


@server.tool()
def remember_preference(
    key: str,
    value: Any,
    session_id: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    record = memory_tools.remember_preference(
        MemoryStore(),
        key,
        value,
        session_id=session_id,
        notes=notes,
    )
    return record.model_dump()


@server.tool()
def list_preferences() -> list[dict[str, Any]]:
    return [record.model_dump() for record in memory_tools.list_preferences(MemoryStore())]


@server.tool()
def save_trajectory(
    archetype: str,
    payload: dict[str, Any],
    session_id: str | None = None,
) -> dict[str, Any]:
    record = memory_tools.save_trajectory(
        MemoryStore(),
        archetype,
        payload,
        session_id=session_id,
    )
    return record.model_dump()


@server.tool()
def search_trajectories(
    query: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    return [
        record.model_dump()
        for record in memory_tools.search_trajectories(MemoryStore(), query, limit=limit)
    ]


@server.tool()
def forget_memory(key: str) -> bool:
    return memory_tools.forget_memory(MemoryStore(), key)


if __name__ == "__main__":
    server.run(transport="stdio")
