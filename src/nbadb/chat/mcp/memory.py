from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nbadb.chat.memory import MemoryStore, ProfileRecord, TrajectoryRecord

_MAX_MEMORY_PAYLOAD_BYTES = 20_000


def _require_session_id(session_id: str | None) -> str:
    if session_id is None or not session_id.strip():
        raise ValueError("memory mutation tools require a non-empty session_id")
    return session_id.strip()


def _require_bounded_json_payload(name: str, payload: Any) -> None:
    try:
        encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    except TypeError as exc:
        raise ValueError(f"{name} must be JSON-serializable") from exc
    if len(encoded) > _MAX_MEMORY_PAYLOAD_BYTES:
        raise ValueError(f"{name} exceeds {_MAX_MEMORY_PAYLOAD_BYTES:,} byte memory mutation limit")


def remember_preference(
    store: MemoryStore,
    key: str,
    value: Any,
    *,
    session_id: str | None = None,
    notes: str | None = None,
) -> ProfileRecord:
    resolved_session_id = _require_session_id(session_id)
    _require_bounded_json_payload("preference value", value)
    return store.remember_preference(
        key,
        value,
        session_id=resolved_session_id,
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
    resolved_session_id = _require_session_id(session_id)
    _require_bounded_json_payload("trajectory payload", payload)
    return store.save_trajectory(archetype, payload, session_id=resolved_session_id)


def search_trajectories(
    store: MemoryStore,
    query: str,
    *,
    limit: int = 10,
) -> list[TrajectoryRecord]:
    return store.search_trajectories(query, limit=limit)


def forget_memory(
    store: MemoryStore,
    key: str,
    *,
    session_id: str | None = None,
    confirm: bool = False,
) -> bool:
    _require_session_id(session_id)
    if not confirm:
        raise ValueError("forget_memory requires confirm=True")
    return store.forget_preference(key)
