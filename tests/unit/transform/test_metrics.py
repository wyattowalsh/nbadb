"""Tests for transform pipeline metrics."""

from __future__ import annotations

import time

import duckdb

from nbadb.transform.metrics import PipelineMetrics, TransformerMetric


class TestTransformerMetric:
    def test_duration(self) -> None:
        m = TransformerMetric(table_name="t", started_at=100.0, completed_at=102.5)
        assert m.duration_seconds == 2.5

    def test_duration_pending(self) -> None:
        m = TransformerMetric(table_name="t", started_at=100.0)
        assert m.duration_seconds == 0.0


class TestPipelineMetrics:
    def test_start_and_complete(self) -> None:
        pm = PipelineMetrics(run_id="test")
        pm.start_transformer("dim_team")
        time.sleep(0.01)
        pm.complete_transformer("dim_team", row_count=30, column_count=9)
        assert pm.success_count == 1
        assert pm.failed_count == 0
        m = pm.transformers["dim_team"]
        assert m.status == "success"
        assert m.row_count == 30
        assert m.duration_seconds > 0

    def test_fail_transformer(self) -> None:
        pm = PipelineMetrics(run_id="test")
        pm.start_transformer("broken")
        pm.fail_transformer("broken", "ValueError: bad data")
        assert pm.failed_count == 1
        assert pm.transformers["broken"].error_message == "ValueError: bad data"

    def test_skip_transformer(self) -> None:
        pm = PipelineMetrics(run_id="test")
        pm.skip_transformer("cached")
        assert pm.skipped_count == 1
        assert pm.transformers["cached"].status == "skipped"

    def test_summary(self) -> None:
        pm = PipelineMetrics(run_id="test")
        pm.start_transformer("a")
        pm.complete_transformer("a", 100, 5)
        pm.start_transformer("b")
        pm.fail_transformer("b", "error")
        pm.skip_transformer("c")
        pm.finalize()

        s = pm.summary()
        assert s["success"] == 1
        assert s["failed"] == 1
        assert s["skipped"] == 1
        assert s["transformers_total"] == 3
        assert s["total_rows"] == 100
        assert len(s["failures"]) == 1
        assert s["failures"][0]["table"] == "b"

    def test_slowest(self) -> None:
        pm = PipelineMetrics(run_id="test")
        # Manually set metrics with controlled timing
        pm.transformers["fast"] = TransformerMetric(
            table_name="fast",
            started_at=0,
            completed_at=0.1,
            row_count=10,
            column_count=2,
            status="success",
        )
        pm.transformers["slow"] = TransformerMetric(
            table_name="slow",
            started_at=0,
            completed_at=5.0,
            row_count=1000,
            column_count=20,
            status="success",
        )
        pm.transformers["medium"] = TransformerMetric(
            table_name="medium",
            started_at=0,
            completed_at=1.0,
            row_count=100,
            column_count=5,
            status="success",
        )
        result = pm.slowest(2)
        assert len(result) == 2
        assert result[0].table_name == "slow"
        assert result[1].table_name == "medium"

    def test_total_rows(self) -> None:
        pm = PipelineMetrics(run_id="test")
        pm.start_transformer("a")
        pm.complete_transformer("a", 100, 5)
        pm.start_transformer("b")
        pm.complete_transformer("b", 200, 3)
        assert pm.total_rows == 300

    def test_persist(self) -> None:
        conn = duckdb.connect()
        conn.execute("""CREATE TABLE _transform_metrics (
            run_id VARCHAR NOT NULL, table_name VARCHAR NOT NULL,
            started_at TIMESTAMP, completed_at TIMESTAMP,
            duration_seconds FLOAT, row_count BIGINT, column_count INT,
            status VARCHAR NOT NULL DEFAULT 'success', error_message VARCHAR,
            PRIMARY KEY (run_id, table_name))""")

        pm = PipelineMetrics(run_id="test-persist")
        pm.start_transformer("dim_team")
        pm.complete_transformer("dim_team", 30, 9)
        pm.persist(conn)

        row = conn.execute(
            "SELECT table_name, row_count, status "
            "FROM _transform_metrics WHERE run_id='test-persist'"
        ).fetchone()
        assert row is not None
        assert row[0] == "dim_team"
        assert row[1] == 30
        assert row[2] == "success"
        conn.close()

    def test_persist_handles_missing_table(self) -> None:
        """Persist gracefully handles missing _transform_metrics table."""
        conn = duckdb.connect()
        pm = PipelineMetrics(run_id="test")
        pm.start_transformer("a")
        pm.complete_transformer("a", 10, 2)
        # Should not raise even though table doesn't exist
        pm.persist(conn)
        conn.close()
