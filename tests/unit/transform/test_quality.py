from __future__ import annotations

import hashlib

import duckdb

from nbadb.transform.quality import CheckLayer, DataQualityMonitor


def _make_monitor() -> tuple[duckdb.DuckDBPyConnection, DataQualityMonitor]:
    conn = duckdb.connect()
    conn.execute("""
        CREATE TABLE test_facts (
            game_id VARCHAR NOT NULL,
            player_id INT NOT NULL,
            team_id INT NOT NULL,
            pts INT,
            reb INT
        )
    """)
    conn.execute("""
        INSERT INTO test_facts VALUES
        ('001', 1, 10, 25, 10),
        ('001', 2, 10, 18, 7),
        ('002', 1, 10, 30, 12),
        ('002', 3, 20, 22, NULL)
    """)
    conn.execute("""
        CREATE TABLE test_dims (
            player_id INT PRIMARY KEY,
            name VARCHAR
        )
    """)
    conn.execute("""
        INSERT INTO test_dims VALUES
        (1, 'Player A'),
        (2, 'Player B')
    """)
    return conn, DataQualityMonitor(conn=conn)


class TestRowCountAnomaly:
    def test_within_threshold_passes(self) -> None:
        conn, monitor = _make_monitor()
        result = monitor.check_row_count_anomaly(
            "test_facts", current_count=4, historical_avg=4.0, historical_std=1.0
        )
        assert result.passed
        conn.close()

    def test_beyond_threshold_fails(self) -> None:
        conn, monitor = _make_monitor()
        result = monitor.check_row_count_anomaly(
            "test_facts", current_count=100, historical_avg=4.0, historical_std=1.0
        )
        assert not result.passed
        conn.close()

    def test_zero_std_always_passes(self) -> None:
        conn, monitor = _make_monitor()
        result = monitor.check_row_count_anomaly(
            "test_facts", current_count=999, historical_avg=4.0, historical_std=0.0
        )
        assert result.passed
        conn.close()


class TestSchemaDrift:
    def test_matching_hash_passes(self) -> None:
        conn, monitor = _make_monitor()
        cols = ["game_id", "player_id", "pts", "reb", "team_id"]
        expected = hashlib.sha256(",".join(sorted(cols)).encode()).hexdigest()[:16]
        result = monitor.check_schema_drift("test_facts", expected, cols)
        assert result.passed
        conn.close()

    def test_drift_detected(self) -> None:
        conn, monitor = _make_monitor()
        result = monitor.check_schema_drift("test_facts", "wrong_hash_value", ["game_id", "pts"])
        assert not result.passed
        assert result.details["expected"] == "wrong_hash_value"
        conn.close()


class TestNullRate:
    def test_column_with_null_fails_at_zero_threshold(self) -> None:
        conn, monitor = _make_monitor()
        result = monitor.check_null_rate("test_facts", "reb", max_null_fraction=0.0)
        assert not result.passed  # reb has 1/4 nulls -> fails at 0.0 threshold
        conn.close()

    def test_allows_some_nulls(self) -> None:
        conn, monitor = _make_monitor()
        result = monitor.check_null_rate("test_facts", "reb", max_null_fraction=0.5)
        assert result.passed
        conn.close()


class TestUniqueness:
    def test_unique_columns_pass(self) -> None:
        conn, monitor = _make_monitor()
        result = monitor.check_uniqueness("test_facts", ["game_id", "player_id"])
        assert result.passed
        conn.close()

    def test_non_unique_fails(self) -> None:
        conn, monitor = _make_monitor()
        result = monitor.check_uniqueness("test_facts", ["team_id"])
        assert not result.passed
        assert result.details["duplicates"] > 0
        conn.close()


class TestReferentialIntegrity:
    def test_all_referenced_passes(self) -> None:
        conn, monitor = _make_monitor()
        conn.execute("INSERT INTO test_dims VALUES (3, 'Player C')")
        result = monitor.check_referential_integrity(
            "test_facts", "player_id", "test_dims", "player_id"
        )
        assert result.passed
        conn.close()

    def test_orphans_detected(self) -> None:
        conn, monitor = _make_monitor()
        result = monitor.check_referential_integrity(
            "test_facts", "player_id", "test_dims", "player_id"
        )
        assert not result.passed
        assert result.details["orphans"] > 0
        conn.close()


class TestCardinality:
    def test_within_bounds(self) -> None:
        conn, monitor = _make_monitor()
        result = monitor.check_cardinality(
            "test_facts", "player_id", min_distinct=1, max_distinct=10
        )
        assert result.passed
        conn.close()

    def test_below_min_fails(self) -> None:
        conn, monitor = _make_monitor()
        result = monitor.check_cardinality("test_facts", "player_id", min_distinct=100)
        assert not result.passed
        conn.close()


class TestValueRange:
    def test_within_range(self) -> None:
        conn, monitor = _make_monitor()
        result = monitor.check_value_range("test_facts", "pts", min_val=0, max_val=100)
        assert result.passed
        conn.close()

    def test_out_of_range(self) -> None:
        conn, monitor = _make_monitor()
        result = monitor.check_value_range("test_facts", "pts", min_val=0, max_val=20)
        assert not result.passed
        conn.close()


class TestSummary:
    def test_summary_counts(self) -> None:
        conn, monitor = _make_monitor()
        monitor.check_row_count_anomaly(
            "t", current_count=4, historical_avg=4.0, historical_std=1.0
        )
        monitor.check_row_count_anomaly(
            "t", current_count=100, historical_avg=4.0, historical_std=1.0
        )
        s = monitor.summary()
        assert s["total"] == 2
        assert s["passed"] == 1
        assert s["failed"] == 1
        conn.close()

    def test_failed_filter(self) -> None:
        conn, monitor = _make_monitor()
        monitor.check_row_count_anomaly(
            "t", current_count=4, historical_avg=4.0, historical_std=1.0
        )
        monitor.check_row_count_anomaly(
            "t", current_count=100, historical_avg=4.0, historical_std=1.0
        )
        assert len(monitor.failed()) == 1
        conn.close()

    def test_results_by_layer(self) -> None:
        conn, monitor = _make_monitor()
        monitor.check_row_count_anomaly(
            "t", current_count=4, historical_avg=4.0, historical_std=1.0
        )
        structural = monitor.results_by_layer(CheckLayer.STRUCTURAL)
        relational = monitor.results_by_layer(CheckLayer.RELATIONAL)
        assert len(structural) == 1
        assert len(relational) == 0
        conn.close()

    def test_summary_by_layer(self) -> None:
        conn, monitor = _make_monitor()
        monitor.check_row_count_anomaly(
            "t", current_count=4, historical_avg=4.0, historical_std=1.0
        )
        s = monitor.summary_by_layer()
        assert "structural" in s
        assert s["structural"]["total"] == 1
        conn.close()

    def test_to_report_serializes_results(self) -> None:
        conn, monitor = _make_monitor()
        monitor.check_row_count_anomaly(
            "t", current_count=4, historical_avg=4.0, historical_std=1.0
        )
        report = monitor.to_report()
        assert report["summary"]["total"] == 1
        assert report["summary_by_layer"]["structural"]["total"] == 1
        assert report["results"][0]["layer"] == "structural"
        conn.close()

    def test_log_summary_runs(self) -> None:
        conn, monitor = _make_monitor()
        monitor.check_row_count_anomaly(
            "t", current_count=4, historical_avg=4.0, historical_std=1.0
        )
        monitor.check_row_count_anomaly(
            "t", current_count=100, historical_avg=4.0, historical_std=1.0
        )
        monitor.log_summary()  # should not raise
        conn.close()


class TestCrossValidate:
    def test_matching_sums_pass(self) -> None:
        conn, monitor = _make_monitor()
        # Create a reference table with same sums
        conn.execute("""
            CREATE TABLE ref_facts (
                game_id VARCHAR NOT NULL,
                player_id INT NOT NULL,
                team_id INT NOT NULL,
                pts INT,
                reb INT
            )
        """)
        conn.execute("""
            INSERT INTO ref_facts VALUES
            ('001', 1, 10, 25, 10),
            ('001', 2, 10, 18, 7),
            ('002', 1, 10, 30, 12),
            ('002', 3, 20, 22, 0)
        """)
        result = monitor.cross_validate("test_facts", "ref_facts", ["pts"])
        assert result.passed
        assert result.layer == CheckLayer.STATISTICAL
        conn.close()

    def test_mismatched_sums_fail(self) -> None:
        conn, monitor = _make_monitor()
        conn.execute("""
            CREATE TABLE ref_facts2 (pts INT)
        """)
        conn.execute("INSERT INTO ref_facts2 VALUES (999)")
        result = monitor.cross_validate("test_facts", "ref_facts2", ["pts"])
        assert not result.passed
        assert len(result.details["mismatches"]) > 0
        conn.close()

    def test_query_error_handled(self) -> None:
        conn, monitor = _make_monitor()
        # Column doesn't exist in the reference table
        conn.execute("CREATE TABLE ref_empty (other_col INT)")
        conn.execute("INSERT INTO ref_empty VALUES (1)")
        result = monitor.cross_validate(
            "test_facts", "ref_empty", ["nonexistent_col"]
        )
        assert not result.passed
        conn.close()

    def test_within_tolerance(self) -> None:
        conn, monitor = _make_monitor()
        conn.execute("CREATE TABLE ref_close (pts INT)")
        # Total pts in test_facts = 95. Insert something very close.
        conn.execute("INSERT INTO ref_close VALUES (95)")
        result = monitor.cross_validate(
            "test_facts", "ref_close", ["pts"], tolerance=1.0
        )
        assert result.passed
        conn.close()


class TestCardinalityMaxDistinct:
    def test_exceeds_max_distinct_fails(self) -> None:
        conn, monitor = _make_monitor()
        result = monitor.check_cardinality(
            "test_facts", "player_id", min_distinct=1, max_distinct=2
        )
        # 3 distinct player_ids (1, 2, 3) > max_distinct=2
        assert not result.passed
        conn.close()


class TestValueRangeMinViolation:
    def test_below_min_fails(self) -> None:
        conn, monitor = _make_monitor()
        result = monitor.check_value_range("test_facts", "pts", min_val=20)
        assert not result.passed
        assert "min=" in result.message
        conn.close()

    def test_no_bounds_passes(self) -> None:
        conn, monitor = _make_monitor()
        result = monitor.check_value_range("test_facts", "pts")
        assert result.passed
        conn.close()
