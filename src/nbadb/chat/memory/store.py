from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from nbadb.chat.memory.models import ProfileRecord, TrajectoryRecord

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")
_DEFAULT_ROOT = Path.home() / ".nbadb" / "chat" / "memory"
_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_OWNERSHIP_ERROR = "preference is not owned by this session"
_INVALID_RECORD_ERROR = "stored preference record is invalid"
_INVALID_TRAJECTORY_ERROR = "stored trajectory record is invalid"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _preference_clock_now() -> datetime:
    """Return the wall clock used only for preference mutations.

    Trajectory timestamps intentionally retain the existing whole-second
    ``_utc_now`` behavior. Preference updates need microsecond precision so an
    authorized write can advance monotonically even when the wall clock is
    frozen or moves backward.
    """

    return datetime.now(UTC)


def _sorted_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True)


def _normalize_session_id(session_id: str | None) -> str | None:
    if session_id is None:
        return None
    normalized = session_id.strip()
    if not normalized:
        raise ValueError("session_id must be non-empty")
    return normalized


def _profile_record_from_row(row: sqlite3.Row, *, expected_key: str) -> ProfileRecord:
    try:
        record = ProfileRecord.model_validate_json(row["record_json"])
    except (TypeError, ValueError) as exc:
        raise ValueError(_INVALID_RECORD_ERROR) from exc
    if record.key != expected_key:
        raise ValueError(_INVALID_RECORD_ERROR)
    return record


def _trajectory_record_from_row(row: sqlite3.Row) -> TrajectoryRecord:
    try:
        record = TrajectoryRecord.model_validate_json(row["record_json"])
    except (TypeError, ValueError) as exc:
        raise ValueError(_INVALID_TRAJECTORY_ERROR) from exc
    if record.session_id != row["session_id"]:
        raise ValueError(_INVALID_TRAJECTORY_ERROR)
    return record


def _parse_preference_timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError(_INVALID_RECORD_ERROR)
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(_INVALID_RECORD_ERROR)
        return parsed.astimezone(UTC)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(_INVALID_RECORD_ERROR) from exc


def _prior_preference_timestamp(record: ProfileRecord, row: sqlite3.Row) -> datetime:
    timestamps = [
        timestamp
        for timestamp in (
            _parse_preference_timestamp(record.updated_at),
            _parse_preference_timestamp(row["updated_at"]),
        )
        if timestamp is not None
    ]
    if not timestamps:
        raise ValueError(_INVALID_RECORD_ERROR)
    return max(timestamps)


def _next_preference_timestamp(prior: datetime | None) -> str:
    try:
        now = _preference_clock_now()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError(_INVALID_RECORD_ERROR)
        next_timestamp = now.astimezone(UTC)
        if prior is not None:
            next_timestamp = max(next_timestamp, prior + timedelta(microseconds=1))
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(_INVALID_RECORD_ERROR) from exc
    return next_timestamp.isoformat(timespec="microseconds")


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
        resolved_session_id = _normalize_session_id(session_id)
        with self._connect() as conn:
            # Serialize the ownership check and write across independent store
            # connections so a competing first writer cannot be overwritten.
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT record_json, updated_at FROM preferences WHERE key = ?",
                [key],
            ).fetchone()
            prior_timestamp: datetime | None = None
            created_at: str | None = None
            record_session_id = resolved_session_id
            record_notes = notes
            if row is not None:
                try:
                    existing = _profile_record_from_row(row, expected_key=key)
                except ValueError as exc:
                    if resolved_session_id is not None:
                        raise PermissionError(_OWNERSHIP_ERROR) from None
                    raise exc
                if resolved_session_id is not None and existing.session_id != resolved_session_id:
                    raise PermissionError(_OWNERSHIP_ERROR)
                try:
                    prior_timestamp = _prior_preference_timestamp(existing, row)
                except ValueError as exc:
                    if resolved_session_id is not None:
                        raise PermissionError(_OWNERSHIP_ERROR) from None
                    raise exc
                created_at = existing.created_at or prior_timestamp.isoformat(
                    timespec="microseconds"
                )
                record_session_id = existing.session_id
                if notes is None:
                    record_notes = existing.notes
            try:
                now = _next_preference_timestamp(prior_timestamp)
            except ValueError as exc:
                if row is not None and resolved_session_id is not None:
                    raise PermissionError(_OWNERSHIP_ERROR) from None
                raise exc
            if created_at is None:
                created_at = now
            record = ProfileRecord(
                key=key,
                value=value,
                session_id=record_session_id,
                notes=record_notes,
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

    def list_preferences(self, *, session_id: str) -> list[ProfileRecord]:
        resolved_session_id = _normalize_session_id(session_id)
        if resolved_session_id is None:
            raise ValueError("session_id must be non-empty")
        with self._connect() as conn:
            rows = conn.execute("SELECT key, record_json FROM preferences ORDER BY key").fetchall()
        records: list[ProfileRecord] = []
        skipped = 0
        for row in rows:
            try:
                record = _profile_record_from_row(row, expected_key=row["key"])
                if record.session_id is None:
                    continue
                owner = _normalize_session_id(record.session_id)
            except ValueError:
                # One corrupt row must not disable listing for every session.
                skipped += 1
                continue
            if owner == resolved_session_id:
                records.append(record)
        if skipped:
            logger.warning("skipped {count} corrupt preference rows during listing", count=skipped)
        return records

    def list_all_preferences(self) -> list[ProfileRecord]:
        """Return every valid preference for an explicit administrator caller."""
        with self._connect() as conn:
            rows = conn.execute("SELECT key, record_json FROM preferences ORDER BY key").fetchall()
        records: list[ProfileRecord] = []
        skipped = 0
        for row in rows:
            try:
                records.append(_profile_record_from_row(row, expected_key=row["key"]))
            except ValueError:
                # One corrupt row must not disable the administrator listing.
                skipped += 1
        if skipped:
            logger.warning("skipped {count} corrupt preference rows during listing", count=skipped)
        return records

    def forget_preference(self, key: str, *, session_id: str | None = None) -> bool:
        """Delete a preference.

        When ``session_id`` is provided, only delete if the stored record's
        session_id matches (ownership check).
        """
        resolved_session_id = _normalize_session_id(session_id)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT record_json FROM preferences WHERE key = ?",
                [key],
            ).fetchone()
            if row is None:
                return False
            try:
                existing = _profile_record_from_row(row, expected_key=key)
            except ValueError:
                raise PermissionError(_OWNERSHIP_ERROR) from None
            # Exact ownership: null/empty stored session is not free-for-all.
            if resolved_session_id is not None and existing.session_id != resolved_session_id:
                raise PermissionError(_OWNERSHIP_ERROR)
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

    def search_trajectories(
        self,
        query: str,
        *,
        session_id: str,
        limit: int = 10,
    ) -> list[TrajectoryRecord]:
        resolved_session_id = _normalize_session_id(session_id)
        if resolved_session_id is None:
            raise ValueError("session_id must be non-empty")
        return self._search_trajectories(
            query,
            limit=limit,
            session_id=resolved_session_id,
        )

    def search_all_trajectories(
        self,
        query: str,
        *,
        limit: int = 10,
    ) -> list[TrajectoryRecord]:
        """Search all trajectories for an explicit administrator caller."""
        return self._search_trajectories(query, limit=limit, session_id=None)

    def _search_trajectories(
        self,
        query: str,
        *,
        limit: int,
        session_id: str | None,
    ) -> list[TrajectoryRecord]:
        if not query.strip():
            return []
        normalized_query = query.casefold()
        tokens = _TOKEN_RE.findall(normalized_query)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT session_id, record_json, created_at "
                "FROM trajectories ORDER BY created_at DESC"
            ).fetchall()

        scored: list[tuple[int, str, TrajectoryRecord]] = []
        skipped = 0
        for row in rows:
            try:
                record = _trajectory_record_from_row(row)
                if session_id is not None:
                    if record.session_id is None:
                        continue
                    owner = _normalize_session_id(record.session_id)
            except ValueError:
                # One corrupt row must not disable trajectory search.
                skipped += 1
                continue
            if session_id is not None and owner != session_id:
                continue
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

        if skipped:
            logger.warning("skipped {count} corrupt trajectory rows during search", count=skipped)
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [record for _, _, record in scored[:limit]]
