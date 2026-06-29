from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nbadb.chat.memory.models import ProfileRecord, TrajectoryRecord

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")
_DEFAULT_ROOT = Path.home() / ".nbadb" / "chat" / "memory"
_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _sorted_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True)


class MemoryStore:
    def __init__(self, root: Path | None = None) -> None:
        self._root = root or _DEFAULT_ROOT
        self._root.mkdir(parents=True, exist_ok=True)
        self._db_path = self._root / "memory.sqlite3"
        self._init_db()

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        schema = _SCHEMA_PATH.read_text(encoding="utf-8")
        with self._connect() as conn:
            conn.executescript(schema)

    def remember_preference(
        self,
        key: str,
        value: Any,
        *,
        session_id: str | None = None,
        notes: str | None = None,
    ) -> ProfileRecord:
        now = _utc_now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT record_json, updated_at FROM preferences WHERE key = ?",
                [key],
            ).fetchone()
            created_at = now
            existing_session_id = session_id
            existing_notes = notes
            if row is not None:
                existing = json.loads(row["record_json"])
                created_at = existing.get("created_at", row["updated_at"])
                if session_id is None:
                    existing_session_id = existing.get("session_id")
                if notes is None:
                    existing_notes = existing.get("notes")
            record = ProfileRecord(
                key=key,
                value=value,
                session_id=existing_session_id,
                notes=existing_notes,
                created_at=created_at,
                updated_at=now,
            )
            conn.execute(
                "INSERT INTO preferences(key, record_json, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET record_json = excluded.record_json, "
                "updated_at = excluded.updated_at",
                [key, record.model_dump_json(), now],
            )
            conn.commit()
        return record

    def list_preferences(self) -> list[ProfileRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT record_json FROM preferences ORDER BY key").fetchall()
        return [ProfileRecord.model_validate_json(row["record_json"]) for row in rows]

    def forget_preference(self, key: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM preferences WHERE key = ?", [key])
            conn.commit()
            return cursor.rowcount > 0

    def save_trajectory(
        self,
        archetype: str,
        payload: dict[str, Any],
        *,
        session_id: str | None = None,
    ) -> TrajectoryRecord:
        now = _utc_now()
        created_at = str(payload.get("created_at") or now)
        updated_at = str(payload.get("updated_at") or now)
        record = TrajectoryRecord(
            archetype=archetype,
            payload=payload,
            session_id=session_id or payload.get("session_id"),
            created_at=created_at,
            updated_at=updated_at,
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO trajectories(session_id, archetype, record_json, created_at) "
                "VALUES (?, ?, ?, ?)",
                [
                    record.session_id,
                    record.archetype,
                    record.model_dump_json(),
                    record.created_at,
                ],
            )
            conn.commit()
        return record

    def search_trajectories(self, query: str, *, limit: int = 10) -> list[TrajectoryRecord]:
        if not query.strip():
            return []
        normalized_query = query.casefold()
        tokens = _TOKEN_RE.findall(normalized_query)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT record_json, created_at FROM trajectories ORDER BY created_at DESC"
            ).fetchall()

        scored: list[tuple[int, str, TrajectoryRecord]] = []
        for row in rows:
            record = TrajectoryRecord.model_validate_json(row["record_json"])
            primary_text = " ".join(
                filter(
                    None,
                    [
                        record.archetype,
                        record.grain or "",
                        " ".join(record.chosen_surfaces),
                    ],
                )
            ).casefold()
            search_text = " ".join(
                filter(
                    None,
                    [
                        primary_text,
                        " ".join(record.tags),
                        " ".join(record.repair_notes),
                        " ".join(record.artifact_kinds),
                        record.sql_hash or "",
                        record.replay_handle or "",
                        _sorted_json(record.payload),
                    ],
                )
            ).casefold()
            score = 0
            if normalized_query in primary_text:
                score += 5
            if normalized_query in search_text:
                score += 3
            for token in tokens:
                if token in primary_text:
                    score += 2
                elif token in search_text:
                    score += 1
            if score > 0:
                scored.append((score, record.created_at or "", record))

        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [record for _, _, record in scored[:limit]]
