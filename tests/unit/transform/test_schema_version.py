"""Tests for schema version tracking."""

from __future__ import annotations

import duckdb
import pytest

from nbadb.transform.schema_version import SchemaChange, SchemaEvolutionError, SchemaVersionTracker


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

    def test_record_schema_with_dtypes(self) -> None:
        """When dtypes is provided and matches columns length, uses typed hash."""
        conn = _make_conn()
        tracker = SchemaVersionTracker(conn)
        tracker.record_schema("t", ["a", "b"], dtypes=["INT", "VARCHAR"])
        # Same columns but different types → should detect a change
        change = tracker.record_schema("t", ["a", "b"], dtypes=["INT", "INT"])
        assert change is not None
        assert change.new_version == 2
        conn.close()

    def test_record_schema_dtypes_ignored_when_length_mismatch(self) -> None:
        """When dtypes length doesn't match columns, falls back to untyped hash."""
        conn = _make_conn()
        tracker = SchemaVersionTracker(conn)
        tracker.record_schema("t", ["a", "b"], dtypes=["INT"])  # Wrong length
        # Re-record with same columns, no dtypes → same untyped hash → no change
        change = tracker.record_schema("t", ["a", "b"])
        assert change is None
        conn.close()

    def test_record_schemas_with_table_dtypes(self) -> None:
        """record_schemas passes dtypes through to record_schema."""
        conn = _make_conn()
        tracker = SchemaVersionTracker(conn)
        tracker.record_schema("t1", ["a"], dtypes=["INT"])
        changes = tracker.record_schemas(
            {"t1": ["a"], "t2": ["x"]},
            table_dtypes={"t1": ["VARCHAR"]},  # Type change for t1
        )
        assert len(changes) == 1
        assert changes[0].table_name == "t1"
        conn.close()

    def test_record_schemas_error_handling(self) -> None:
        """record_schemas logs warning and continues when record_schema raises."""
        conn = _make_conn()
        tracker = SchemaVersionTracker(conn)
        # Drop the tables to cause errors
        conn.execute("DROP TABLE _schema_versions")
        conn.execute("DROP TABLE _schema_version_history")
        # Should not raise, just return empty changes
        changes = tracker.record_schemas({"t1": ["a"], "t2": ["b"]})
        assert changes == []
        conn.close()


class TestCompatibleChange:
    def test_additive_change_is_compatible(self) -> None:
        change = SchemaChange(
            table_name="t",
            old_version=1,
            new_version=2,
            added_columns=["c"],
            removed_columns=[],
            old_hash="aaa",
            new_hash="bbb",
        )
        assert SchemaVersionTracker.compatible_change(change) is True

    def test_destructive_change_is_not_compatible(self) -> None:
        change = SchemaChange(
            table_name="t",
            old_version=1,
            new_version=2,
            added_columns=[],
            removed_columns=["c"],
            old_hash="aaa",
            new_hash="bbb",
        )
        assert SchemaVersionTracker.compatible_change(change) is False

    def test_mixed_change_is_not_compatible(self) -> None:
        change = SchemaChange(
            table_name="t",
            old_version=1,
            new_version=2,
            added_columns=["d"],
            removed_columns=["c"],
            old_hash="aaa",
            new_hash="bbb",
        )
        assert SchemaVersionTracker.compatible_change(change) is False


class TestGuardEvolution:
    def test_additive_changes_return_warnings(self) -> None:
        conn = _make_conn()
        tracker = SchemaVersionTracker(conn)
        changes = [
            SchemaChange(
                table_name="t1",
                old_version=1,
                new_version=2,
                added_columns=["c"],
                removed_columns=[],
                old_hash="aaa",
                new_hash="bbb",
            ),
        ]
        warnings = tracker.guard_evolution(changes)
        assert len(warnings) == 1
        assert "added columns" in warnings[0]
        conn.close()

    def test_destructive_change_raises(self) -> None:
        conn = _make_conn()
        tracker = SchemaVersionTracker(conn)
        changes = [
            SchemaChange(
                table_name="t1",
                old_version=1,
                new_version=2,
                added_columns=[],
                removed_columns=["old_col"],
                old_hash="aaa",
                new_hash="bbb",
            ),
        ]
        with pytest.raises(SchemaEvolutionError, match="Destructive schema changes"):
            tracker.guard_evolution(changes)
        conn.close()

    def test_allowed_removal_does_not_raise(self) -> None:
        conn = _make_conn()
        tracker = SchemaVersionTracker(conn)
        changes = [
            SchemaChange(
                table_name="t1",
                old_version=1,
                new_version=2,
                added_columns=[],
                removed_columns=["old_col"],
                old_hash="aaa",
                new_hash="bbb",
            ),
        ]
        warnings = tracker.guard_evolution(changes, allow_removals={"t1"})
        assert warnings == []
        conn.close()

    def test_mixed_allowed_and_forbidden_removals(self) -> None:
        conn = _make_conn()
        tracker = SchemaVersionTracker(conn)
        changes = [
            SchemaChange(
                table_name="t_safe",
                old_version=1,
                new_version=2,
                added_columns=[],
                removed_columns=["x"],
                old_hash="a",
                new_hash="b",
            ),
            SchemaChange(
                table_name="t_unsafe",
                old_version=1,
                new_version=2,
                added_columns=["new_col"],
                removed_columns=["old_col"],
                old_hash="c",
                new_hash="d",
            ),
        ]
        with pytest.raises(SchemaEvolutionError, match="t_unsafe"):
            tracker.guard_evolution(changes, allow_removals={"t_safe"})
        conn.close()

    def test_no_changes_returns_empty(self) -> None:
        conn = _make_conn()
        tracker = SchemaVersionTracker(conn)
        warnings = tracker.guard_evolution([])
        assert warnings == []
        conn.close()


class TestGetHistory:
    def test_returns_version_tuples(self) -> None:
        conn = _make_conn()
        tracker = SchemaVersionTracker(conn)
        tracker.record_schema("t", ["a", "b"])
        tracker.record_schema("t", ["a", "b", "c"])
        history = tracker.get_history("t")
        assert len(history) == 2
        # Each entry: (version, hash, columns, recorded_at)
        assert history[0][0] == 1
        assert history[1][0] == 2
        assert history[0][2] == ["a", "b"]
        assert history[1][2] == ["a", "b", "c"]
        # recorded_at is present
        assert history[0][3] is not None
        conn.close()

    def test_empty_history_for_unknown_table(self) -> None:
        conn = _make_conn()
        tracker = SchemaVersionTracker(conn)
        history = tracker.get_history("nonexistent")
        assert history == []
        conn.close()


class TestSchemaEvolutionError:
    def test_is_exception(self) -> None:
        assert issubclass(SchemaEvolutionError, Exception)

    def test_message(self) -> None:
        err = SchemaEvolutionError("test message")
        assert str(err) == "test message"
