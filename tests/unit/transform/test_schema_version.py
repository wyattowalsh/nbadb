"""Tests for schema version tracking."""

from __future__ import annotations

import duckdb

from nbadb.transform.schema_version import SchemaVersionTracker


def _make_conn() -> duckdb.DuckDBPyConnection:
    """Create in-memory DuckDB with schema version tables."""
    conn = duckdb.connect()
    conn.execute(
        """CREATE TABLE _schema_versions (
        table_name VARCHAR NOT NULL, version INT NOT NULL DEFAULT 1,
        column_hash VARCHAR NOT NULL, columns_json VARCHAR NOT NULL,
        recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (table_name))"""
    )
    conn.execute(
        """CREATE TABLE _schema_version_history (
        table_name VARCHAR NOT NULL, version INT NOT NULL,
        column_hash VARCHAR NOT NULL, columns_json VARCHAR NOT NULL,
        recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (table_name, version))"""
    )
    return conn


class TestSchemaVersionTracker:
    def test_first_record_returns_none(self) -> None:
        conn = _make_conn()
        tracker = SchemaVersionTracker(conn)
        result = tracker.record_schema("dim_team", ["team_id", "name", "city"])
        assert result is None  # First time = no change
        version = tracker.get_current_version("dim_team")
        assert version is not None
        assert version[0] == 1  # version
        conn.close()

    def test_same_schema_no_change(self) -> None:
        conn = _make_conn()
        tracker = SchemaVersionTracker(conn)
        tracker.record_schema("dim_team", ["team_id", "name"])
        result = tracker.record_schema("dim_team", ["team_id", "name"])
        assert result is None
        assert tracker.get_current_version("dim_team")[0] == 1  # Still v1
        conn.close()

    def test_column_added_bumps_version(self) -> None:
        conn = _make_conn()
        tracker = SchemaVersionTracker(conn)
        tracker.record_schema("dim_team", ["team_id", "name"])
        change = tracker.record_schema("dim_team", ["team_id", "name", "city"])
        assert change is not None
        assert change.new_version == 2
        assert change.added_columns == ["city"]
        assert change.removed_columns == []
        conn.close()

    def test_column_removed_bumps_version(self) -> None:
        conn = _make_conn()
        tracker = SchemaVersionTracker(conn)
        tracker.record_schema("dim_team", ["team_id", "name", "city"])
        change = tracker.record_schema("dim_team", ["team_id", "name"])
        assert change is not None
        assert change.new_version == 2
        assert change.removed_columns == ["city"]
        assert change.added_columns == []
        conn.close()

    def test_history_tracks_all_versions(self) -> None:
        conn = _make_conn()
        tracker = SchemaVersionTracker(conn)
        tracker.record_schema("t", ["a", "b"])
        tracker.record_schema("t", ["a", "b", "c"])
        tracker.record_schema("t", ["a", "c", "d"])
        history = tracker.get_history("t")
        assert len(history) == 3
        assert [h[0] for h in history] == [1, 2, 3]
        conn.close()

    def test_get_all_versions(self) -> None:
        conn = _make_conn()
        tracker = SchemaVersionTracker(conn)
        tracker.record_schema("dim_team", ["id"])
        tracker.record_schema("dim_player", ["id", "name"])
        versions = tracker.get_all_versions()
        assert versions == {"dim_player": 1, "dim_team": 1}
        conn.close()

    def test_record_schemas_batch(self) -> None:
        conn = _make_conn()
        tracker = SchemaVersionTracker(conn)
        tracker.record_schema("t1", ["a"])
        changes = tracker.record_schemas({"t1": ["a", "b"], "t2": ["x", "y"]})
        assert len(changes) == 1  # Only t1 changed (t2 is new = no change)
        assert changes[0].table_name == "t1"
        conn.close()

    def test_untracked_table_returns_none(self) -> None:
        conn = _make_conn()
        tracker = SchemaVersionTracker(conn)
        assert tracker.get_current_version("nonexistent") is None
        conn.close()

    def test_hash_is_order_independent(self) -> None:
        """Column order shouldn't affect the hash (we sort before hashing)."""
        h1 = SchemaVersionTracker._hash_columns(["b", "a", "c"])
        h2 = SchemaVersionTracker._hash_columns(["a", "b", "c"])
        assert h1 == h2
