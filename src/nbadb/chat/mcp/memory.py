from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nbadb.chat.memory import MemoryStore, ProfileRecord, TrajectoryRecord


def remember_preference(
    store: MemoryStore,
    key: str,
    value: Any,
    *,
    session_id: str | None = None,
    notes: str | None = None,
) -> ProfileRecord:
    return store.remember_preference(
        key,
        value,
        session_id=session_id,
        notes=notes,
    )


def list_preferences(store: MemoryStore) -> list[ProfileRecord]:
    return store.list_preferences()


def save_trajectory(
    store: MemoryStore,
    archetype: str,
    payload: dict[str, Any],
    *,
    session_id: str | None = None,
) -> TrajectoryRecord:
    return store.save_trajectory(archetype, payload, session_id=session_id)


def search_trajectories(
    store: MemoryStore,
    query: str,
    *,
    limit: int = 10,
) -> list[TrajectoryRecord]:
    return store.search_trajectories(query, limit=limit)


def forget_memory(store: MemoryStore, key: str) -> bool:
    return store.forget_preference(key)
