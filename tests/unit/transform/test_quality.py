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


class TestSchemaDriftWithTypes:
    """Cover check_schema_drift when current_types is provided (lines 71-73)."""

    def test_typed_hash_matches(self) -> None:
        conn, monitor = _make_monitor()
        cols = ["game_id", "player_id", "pts", "reb", "team_id"]
        types = ["VARCHAR", "INT", "INT", "INT", "INT"]
        # Build expected typed hash: sorted (col, type) pairs
        pairs = sorted(zip(cols, types, strict=True))
        raw = ",".join(f"{c}:{t}" for c, t in pairs)
        expected = hashlib.sha256(raw.encode()).hexdigest()[:16]
        result = monitor.check_schema_drift("test_facts", expected, cols, current_types=types)
        assert result.passed
        conn.close()

    def test_typed_hash_differs_from_untyped(self) -> None:
        conn, monitor = _make_monitor()
        cols = ["game_id", "player_id", "pts", "reb", "team_id"]
        types = ["VARCHAR", "INT", "INT", "INT", "INT"]
        # Compute untyped hash
        untyped_hash = hashlib.sha256(",".join(sorted(cols)).encode()).hexdigest()[:16]
        # Using typed check with untyped expected hash should fail
        result = monitor.check_schema_drift("test_facts", untyped_hash, cols, current_types=types)
        assert not result.passed
        conn.close()

    def test_mismatched_types_length_falls_back_to_untyped(self) -> None:
        conn, monitor = _make_monitor()
        cols = ["game_id", "player_id", "pts", "reb", "team_id"]
        types = ["VARCHAR", "INT"]  # wrong length
        untyped_hash = hashlib.sha256(",".join(sorted(cols)).encode()).hexdigest()[:16]
        result = monitor.check_schema_drift("test_facts", untyped_hash, cols, current_types=types)
        assert result.passed
        conn.close()


def _make_staging_monitor(
    stg_tables: dict[str, int],
) -> tuple[duckdb.DuckDBPyConnection, DataQualityMonitor]:
    """Create a DuckDB with stg_* tables having the given row counts."""
    conn = duckdb.connect()
    for name, row_count in stg_tables.items():
        conn.execute(f"CREATE TABLE {name} (id INT)")
        for i in range(row_count):
            conn.execute(f"INSERT INTO {name} VALUES ({i})")
    return conn, DataQualityMonitor(conn=conn)


class TestStagingGate:
    def test_passes_when_enough_tables_with_data(self) -> None:
        tables = {f"stg_t{i}": 5 for i in range(12)}
        conn, monitor = _make_staging_monitor(tables)
        assert monitor.run_staging_gate(min_tables=10) is True
        gate_results = [r for r in monitor.results if r.check_type == "staging_gate"]
        assert len(gate_results) == 1
        assert gate_results[0].passed
        conn.close()

    def test_fails_when_not_enough_tables(self) -> None:
        tables = {f"stg_t{i}": 5 for i in range(3)}
        conn, monitor = _make_staging_monitor(tables)
        assert monitor.run_staging_gate(min_tables=10) is False
        gate_results = [r for r in monitor.results if r.check_type == "staging_gate"]
        assert len(gate_results) == 1
        assert not gate_results[0].passed
        assert "Only 3" in gate_results[0].message
        conn.close()

    def test_warns_on_empty_tables(self) -> None:
        tables = {"stg_a": 5, "stg_b": 0, "stg_c": 3}
        conn, monitor = _make_staging_monitor(tables)
        assert monitor.run_staging_gate(min_tables=1, warn_empty=True) is True
        empty_results = [r for r in monitor.results if r.check_type == "staging_empty"]
        assert len(empty_results) == 1
        assert empty_results[0].table == "stg_b"
        assert empty_results[0].passed  # WARN, not FAIL
        assert "WARN" in empty_results[0].message
        conn.close()

    def test_fails_on_empty_critical_table(self) -> None:
        tables = {"stg_a": 5, "stg_critical": 0, "stg_c": 3}
        conn, monitor = _make_staging_monitor(tables)
        result = monitor.run_staging_gate(
            min_tables=1,
            fail_on_empty_critical=True,
            critical_tables={"stg_critical"},
        )
        assert result is False
        empty_results = [r for r in monitor.results if r.check_type == "staging_empty"]
        assert len(empty_results) == 1
        assert not empty_results[0].passed  # FAIL
        assert "FAIL" in empty_results[0].message
        conn.close()

    def test_critical_but_not_fail_on_empty_is_warn(self) -> None:
        tables = {"stg_a": 5, "stg_critical": 0}
        conn, monitor = _make_staging_monitor(tables)
        result = monitor.run_staging_gate(
            min_tables=1,
            fail_on_empty_critical=False,
            critical_tables={"stg_critical"},
        )
        assert result is True
        empty_results = [r for r in monitor.results if r.check_type == "staging_empty"]
        assert len(empty_results) == 1
        assert empty_results[0].passed  # WARN, not FAIL
        conn.close()

    def test_empty_non_critical_suppressed_when_warn_false(self) -> None:
        tables = {"stg_a": 5, "stg_b": 0}
        conn, monitor = _make_staging_monitor(tables)
        result = monitor.run_staging_gate(min_tables=1, warn_empty=False)
        assert result is True
        empty_results = [r for r in monitor.results if r.check_type == "staging_empty"]
        assert len(empty_results) == 0
        conn.close()

    def test_query_exception_returns_false(self) -> None:
        conn = duckdb.connect()
        # Close connection to cause execute to fail
        conn.close()
        monitor = DataQualityMonitor(conn=conn)
        assert monitor.run_staging_gate() is False

    def test_all_tables_have_data(self) -> None:
        tables = {"stg_x": 10, "stg_y": 20, "stg_z": 30}
        conn, monitor = _make_staging_monitor(tables)
        assert monitor.run_staging_gate(min_tables=3) is True
        empty_results = [r for r in monitor.results if r.check_type == "staging_empty"]
        assert len(empty_results) == 0
        gate_results = [r for r in monitor.results if r.check_type == "staging_gate"]
        assert gate_results[0].passed
        assert "PASS" in gate_results[0].message
        conn.close()

    def test_mixed_empty_and_critical(self) -> None:
        """Multiple empty tables, one critical, one not."""
        tables = {"stg_a": 5, "stg_b": 0, "stg_critical": 0, "stg_d": 10}
        conn, monitor = _make_staging_monitor(tables)
        result = monitor.run_staging_gate(
            min_tables=1,
            warn_empty=True,
            fail_on_empty_critical=True,
            critical_tables={"stg_critical"},
        )
        assert result is False
        empty_results = [r for r in monitor.results if r.check_type == "staging_empty"]
        assert len(empty_results) == 2
        critical_result = [r for r in empty_results if r.table == "stg_critical"][0]
        warn_result = [r for r in empty_results if r.table == "stg_b"][0]
        assert not critical_result.passed
        assert warn_result.passed
        conn.close()
