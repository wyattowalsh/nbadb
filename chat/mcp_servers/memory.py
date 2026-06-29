from __future__ import annotations

from nbadb.chat.mcp import memory as memory_tools
from nbadb.chat.memory import MemoryStore

SERVER_NAME = "nbadb-memory"


def remember_preference(key: str, value: str, *, store: MemoryStore | None = None) -> dict:
    active_store = store or MemoryStore()
    record = memory_tools.remember_preference(active_store, key, value)
    return record.model_dump()


def list_preferences(*, store: MemoryStore | None = None) -> list[dict]:
    active_store = store or MemoryStore()
    return [record.model_dump() for record in memory_tools.list_preferences(active_store)]


def save_trajectory(
    archetype: str,
    payload: dict,
    *,
    session_id: str | None = None,
    store: MemoryStore | None = None,
) -> dict:
    active_store = store or MemoryStore()
    record = memory_tools.save_trajectory(
        active_store,
        archetype,
        payload,
        session_id=session_id,
    )
    return record.model_dump()


def search_trajectories(
    query: str,
    *,
    limit: int = 10,
    store: MemoryStore | None = None,
) -> list[dict]:
    active_store = store or MemoryStore()
    return [
        record.model_dump()
        for record in memory_tools.search_trajectories(active_store, query, limit=limit)
    ]


def forget_memory(key: str, *, store: MemoryStore | None = None) -> bool:
    active_store = store or MemoryStore()
    return memory_tools.forget_memory(active_store, key)
