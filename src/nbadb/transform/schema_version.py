"""Schema version tracking for transform pipeline tables.

Detects schema changes (added/removed/reordered columns) and maintains
a version history. Used by the pipeline to warn about drift and by
quality checks to verify consistency.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    import duckdb


@dataclass
class SchemaChange:
    """Represents a detected schema change between versions."""

    table_name: str
    old_version: int
    new_version: int
    added_columns: list[str]
    removed_columns: list[str]
    old_hash: str
    new_hash: str


class SchemaVersionTracker:
    """Tracks and versions table schemas in DuckDB.

    After each pipeline run, call ``record_schemas()`` to snapshot
    current column layouts.  Call ``check_for_changes()`` to detect
    drift between runs.
    """

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn

    @staticmethod
    def _hash_columns(columns: list[str]) -> str:
        """Deterministic hash of sorted column descriptors.

        Accepts plain column names or ``name:type`` pairs for type-aware hashing.
        """
        return hashlib.sha256(",".join(sorted(columns)).encode()).hexdigest()[:16]

    def get_current_version(self, table_name: str) -> tuple[int, str, list[str]] | None:
        """Return (version, hash, columns) for a table, or None if untracked."""
        row = self._conn.execute(
            "SELECT version, column_hash, columns_json FROM _schema_versions WHERE table_name = $1",
            [table_name],
        ).fetchone()
        if row is None:
            return None
        return (row[0], row[1], json.loads(row[2]))

    def record_schema_typed(
        self, table_name: str, columns: list[str], dtypes: list[str] | None = None
    ) -> SchemaChange | None:
        """Record schema with optional type information.

        When *dtypes* is provided, the hash includes ``name:type`` pairs,
        detecting type changes in addition to column additions/removals.
        """
        if dtypes and len(dtypes) == len(columns):
            typed_cols = [f"{c}:{t}" for c, t in zip(columns, dtypes, strict=True)]
            return self._record(table_name, columns, self._hash_columns(typed_cols))
        return self._record(table_name, columns, self._hash_columns(columns))

    def record_schema(
        self, table_name: str, columns: list[str], dtypes: list[str] | None = None
    ) -> SchemaChange | None:
        """Record the current schema for a table.

        When *dtypes* is provided (and matches *columns* in length), the hash
        includes ``name:type`` pairs so that type changes are also detected.

        Returns a SchemaChange if the schema differs from the stored version,
        or None if unchanged (or first recording).
        """
        if dtypes and len(dtypes) == len(columns):
            typed_cols = [f"{c}:{t}" for c, t in zip(columns, dtypes, strict=True)]
            return self._record(table_name, columns, self._hash_columns(typed_cols))
        return self._record(table_name, columns, self._hash_columns(columns))

    def _record(self, table_name: str, columns: list[str], new_hash: str) -> SchemaChange | None:
        columns_json = json.dumps(columns)
        existing = self.get_current_version(table_name)

        if existing is None:
            self._conn.execute(
                """INSERT INTO _schema_versions (table_name, version, column_hash, columns_json)
                   VALUES ($1, 1, $2, $3)
                   ON CONFLICT (table_name) DO UPDATE SET
                       version = 1, column_hash = EXCLUDED.column_hash,
                       columns_json = EXCLUDED.columns_json, recorded_at = now()""",
                [table_name, new_hash, columns_json],
            )
            self._conn.execute(
                """INSERT INTO _schema_version_history
                   (table_name, version, column_hash, columns_json)
                   VALUES ($1, 1, $2, $3)
                   ON CONFLICT (table_name, version) DO NOTHING""",
                [table_name, new_hash, columns_json],
            )
            logger.debug("schema_version: {} registered (v1, {} columns)", table_name, len(columns))
            return None

        old_version, old_hash, old_columns = existing

        if old_hash == new_hash:
            return None

        new_version = old_version + 1
        added = sorted(set(columns) - set(old_columns))
        removed = sorted(set(old_columns) - set(columns))

        self._conn.execute(
            """UPDATE _schema_versions
               SET version = $1, column_hash = $2, columns_json = $3,
                   recorded_at = CURRENT_TIMESTAMP
               WHERE table_name = $4""",
            [new_version, new_hash, columns_json, table_name],
        )
        self._conn.execute(
            """INSERT INTO _schema_version_history (table_name, version, column_hash, columns_json)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (table_name, version) DO NOTHING""",
            [table_name, new_version, new_hash, columns_json],
        )

        change = SchemaChange(
            table_name=table_name,
            old_version=old_version,
            new_version=new_version,
            added_columns=added,
            removed_columns=removed,
            old_hash=old_hash,
            new_hash=new_hash,
        )
        logger.warning(
            "schema_version: {} changed v{} -> v{} (added={}, removed={})",
            table_name,
            old_version,
            new_version,
            added,
            removed,
        )
        return change

    def record_schemas(
        self,
        tables: dict[str, list[str]],
        table_dtypes: dict[str, list[str]] | None = None,
    ) -> list[SchemaChange]:
        """Record schemas for multiple tables. Returns list of detected changes.

        When *table_dtypes* is provided, type information is included in
        the schema hash so type-only changes are also detected.
        """
        changes = []
        dtypes_map = table_dtypes or {}
        for table_name, columns in tables.items():
            try:
                change = self.record_schema(table_name, columns, dtypes=dtypes_map.get(table_name))
                if change is not None:
                    changes.append(change)
            except Exception as exc:
                logger.warning(
                    "schema_version: failed to record {}: {}",
                    table_name,
                    type(exc).__name__,
                )
        return changes

    def get_history(self, table_name: str) -> list[tuple[int, str, list[str], str]]:
        """Return version history for a table as [(version, hash, columns, recorded_at)]."""
        rows = self._conn.execute(
            """SELECT version, column_hash, columns_json, recorded_at
               FROM _schema_version_history
               WHERE table_name = $1
               ORDER BY version""",
            [table_name],
        ).fetchall()
        return [(r[0], r[1], json.loads(r[2]), r[3]) for r in rows]

    def get_all_versions(self) -> dict[str, int]:
        """Return {table_name: current_version} for all tracked tables."""
        rows = self._conn.execute(
            "SELECT table_name, version FROM _schema_versions ORDER BY table_name"
        ).fetchall()
        return {r[0]: r[1] for r in rows}
