from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nbadb.chat.memory import MemoryStore, ProfileRecord, TrajectoryRecord

_MAX_MEMORY_PAYLOAD_BYTES = 20_000
_MAX_KEY_CHARS = 200
_MAX_NOTES_CHARS = 2_000
_MAX_ARCHETYPE_CHARS = 200


def _require_session_id(session_id: str | None) -> str:
    if session_id is None or not session_id.strip():
        raise ValueError("memory tools require a non-empty session_id")
    return session_id.strip()


def _require_bounded_text(name: str, value: str | None, *, max_chars: int) -> str | None:
    if value is None:
        return None
    if len(value) > max_chars:
        raise ValueError(f"{name} exceeds {max_chars:,} character limit")
    return value


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
    bounded_key = _require_bounded_text("preference key", key, max_chars=_MAX_KEY_CHARS)
    if not bounded_key or not bounded_key.strip():
        raise ValueError("preference key must be non-empty")
    bounded_notes = _require_bounded_text("preference notes", notes, max_chars=_MAX_NOTES_CHARS)
    _require_bounded_json_payload("preference value", value)
    return store.remember_preference(
        bounded_key.strip(),
        value,
        session_id=resolved_session_id,
        notes=bounded_notes,
    )


def list_preferences(
    store: MemoryStore,
    *,
    session_id: str | None = None,
) -> list[ProfileRecord]:
    return store.list_preferences(session_id=_require_session_id(session_id))


def save_trajectory(
    store: MemoryStore,
    archetype: str,
    payload: dict[str, Any],
    *,
    session_id: str | None = None,
) -> TrajectoryRecord:
    resolved_session_id = _require_session_id(session_id)
    bounded_archetype = _require_bounded_text(
        "trajectory archetype", archetype, max_chars=_MAX_ARCHETYPE_CHARS
    )
    if not bounded_archetype or not bounded_archetype.strip():
        raise ValueError("trajectory archetype must be non-empty")
    _require_bounded_json_payload("trajectory payload", payload)
    return store.save_trajectory(
        bounded_archetype.strip(),
        payload,
        session_id=resolved_session_id,
    )


def search_trajectories(
    store: MemoryStore,
    query: str,
    *,
    session_id: str | None = None,
    limit: int = 10,
) -> list[TrajectoryRecord]:
    return store.search_trajectories(
        query,
        session_id=_require_session_id(session_id),
        limit=limit,
    )


def forget_memory(
    store: MemoryStore,
    key: str,
    *,
    session_id: str | None = None,
    confirm: bool = False,
) -> bool:
    resolved_session_id = _require_session_id(session_id)
    if not confirm:
        raise ValueError("forget_memory requires confirm=True")
    return store.forget_preference(key, session_id=resolved_session_id)
