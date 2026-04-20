from __future__ import annotations

from typing import ClassVar

import duckdb
import pandera.polars as pa
import polars as pl

from nbadb.schemas.base import BaseSchema
from nbadb.transform.base import BaseTransformer
from nbadb.transform.pipeline import TransformPipeline, _input_schema_for


class _TransA(BaseTransformer):
    output_table: ClassVar[str] = "table_a"
    depends_on: ClassVar[list[str]] = ["raw_input"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return staging["raw_input"].collect().with_columns(pl.col("val").alias("val_a"))


class _TransB(BaseTransformer):
    output_table: ClassVar[str] = "table_b"
    depends_on: ClassVar[list[str]] = ["table_a"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        a = staging["table_a"].collect()
        return a.with_columns((pl.col("val") * 2).alias("val_b"))


class _TransC(BaseTransformer):
    output_table: ClassVar[str] = "table_c"
    depends_on: ClassVar[list[str]] = ["table_b"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        b = staging["table_b"].collect()
        return b.with_columns((pl.col("val_b") + 1).alias("val_c"))


class _ValidatedFactSchema(BaseSchema):
    player_id: int = pa.Field(gt=0)
    pts: int = pa.Field(ge=0)


class _ValidatedInputSchema(BaseSchema):
    val: int = pa.Field(gt=0)


class _ValidatedTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_validated"
    depends_on: ClassVar[list[str]] = []

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return pl.DataFrame({"player_id": [1], "pts": [24]})


class _InvalidValidatedTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_invalid"
    depends_on: ClassVar[list[str]] = []

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return pl.DataFrame({"player_id": [-1], "pts": [24]})


class TestTransformPipeline:
    def test_execution_order_respects_dependencies(self) -> None:
        conn = duckdb.connect()
        pipeline = TransformPipeline(conn)
        pipeline.register(_TransB())
        pipeline.register(_TransA())
        order = pipeline.execution_order
        assert order.index("table_a") < order.index("table_b")
        conn.close()

    def test_three_node_chain_ordering(self) -> None:
        """A -> B -> C: verify topological sort with 3-node chain."""
        conn = duckdb.connect()
        pipeline = TransformPipeline(conn)
        # Register in reverse order to stress the sort
        pipeline.register(_TransC())
        pipeline.register(_TransA())
        pipeline.register(_TransB())
        order = pipeline.execution_order
        assert order.index("table_a") < order.index("table_b")
        assert order.index("table_b") < order.index("table_c")
        conn.close()

    def test_three_node_chain_run(self) -> None:
        """A -> B -> C: verify data flows through the full chain."""
        conn = duckdb.connect()
        pipeline = TransformPipeline(conn)
        pipeline.register(_TransC())
        pipeline.register(_TransB())
        pipeline.register(_TransA())
        staging = {"raw_input": pl.DataFrame({"val": [10]}).lazy()}
        outputs = pipeline.run(staging)
        assert "table_a" in outputs
        assert "table_b" in outputs
        assert "table_c" in outputs
        # val=10, val_b=20, val_c=21
        assert outputs["table_c"]["val_c"].to_list() == [21]
        conn.close()

    def test_run_produces_outputs(self) -> None:
        conn = duckdb.connect()
        pipeline = TransformPipeline(conn)
        pipeline.register(_TransA())
        pipeline.register(_TransB())
        staging = {"raw_input": pl.DataFrame({"val": [10, 20]}).lazy()}
        outputs = pipeline.run(staging)
        assert "table_a" in outputs
        assert "table_b" in outputs
        assert outputs["table_b"]["val_b"].to_list() == [20, 40]
        conn.close()

    def test_get_output(self) -> None:
        conn = duckdb.connect()
        pipeline = TransformPipeline(conn)
        pipeline.register(_TransA())
        staging = {"raw_input": pl.DataFrame({"val": [5]}).lazy()}
        pipeline.run(staging)
        assert pipeline.get_output("table_a") is not None
        assert pipeline.get_output("nonexistent") is None
        conn.close()

    def test_register_all(self) -> None:
        conn = duckdb.connect()
        pipeline = TransformPipeline(conn)
        pipeline.register_all([_TransA(), _TransB()])
        assert len(pipeline.execution_order) == 2
        conn.close()

    def test_outputs_registered_in_duckdb(self) -> None:
        """Verify pipeline registers output tables in the DuckDB connection."""
        conn = duckdb.connect()
        pipeline = TransformPipeline(conn)
        pipeline.register(_TransA())
        staging = {"raw_input": pl.DataFrame({"val": [42]}).lazy()}
        pipeline.run(staging)
        result = conn.execute("SELECT val_a FROM table_a").fetchone()
        assert result[0] == 42
        conn.close()

    def test_resolves_input_schema_aliases(self) -> None:
        assert _input_schema_for("stg_schedule").__name__ == "StagingScheduleLeagueV2Schema"
        assert _input_schema_for("stg_player_info").__name__ == "RawCommonPlayerInfoSchema"

    def test_validates_input_schema_before_transform(self, monkeypatch) -> None:
        conn = duckdb.connect()
        pipeline = TransformPipeline(conn)
        pipeline.register(_TransA())
        monkeypatch.setattr(
            "nbadb.transform.pipeline._input_schema_for",
            lambda table: _ValidatedInputSchema if table == "raw_input" else None,
        )

        outputs = pipeline.run(
            {"raw_input": pl.DataFrame({"val": [42], "extra": ["drop-me"]}).lazy()},
            validate_input_schemas=True,
        )

        assert outputs["table_a"].columns == ["val", "val_a"]
        assert conn.execute("SELECT * FROM raw_input").pl().columns == ["val"]
        conn.close()

    def test_input_schema_validation_failure_marks_dependents_failed(self, monkeypatch) -> None:
        conn = duckdb.connect()
        pipeline = TransformPipeline(conn)
        pipeline.register(_TransA())
        monkeypatch.setattr(
            "nbadb.transform.pipeline._input_schema_for",
            lambda table: _ValidatedInputSchema if table == "raw_input" else None,
        )

        outputs = pipeline.run(
            {"raw_input": pl.DataFrame({"val": [-1]}).lazy()},
            validate_input_schemas=True,
        )

        assert "table_a" not in outputs
        result = pipeline.last_result
        assert result is not None
        assert result.failed == [("table_a", "missing staging: raw_input")]
        conn.close()

    def test_validates_output_against_matching_star_schema(self, monkeypatch) -> None:
        conn = duckdb.connect()
        pipeline = TransformPipeline(conn)
        pipeline.register(_ValidatedTransformer())
        monkeypatch.setattr(
            "nbadb.transform.pipeline._star_schema_map",
            lambda: {"fact_validated": _ValidatedFactSchema},
        )

        outputs = pipeline.run({})

        assert "fact_validated" in outputs
        assert outputs["fact_validated"]["pts"].to_list() == [24]
        conn.close()

    def test_schema_validation_failure_marks_transform_failed(self, monkeypatch) -> None:
        conn = duckdb.connect()
        pipeline = TransformPipeline(conn)
        pipeline.register(_InvalidValidatedTransformer())
        pipeline.register(_TransA())
        monkeypatch.setattr(
            "nbadb.transform.pipeline._star_schema_map",
            lambda: {"fact_invalid": _ValidatedFactSchema},
        )

        staging = {"raw_input": pl.DataFrame({"val": [7]}).lazy()}
        outputs = pipeline.run(staging)

        assert "fact_invalid" not in outputs
        assert "table_a" in outputs
        result = pipeline.last_result
        assert result is not None
        assert any(table == "fact_invalid" for table, _ in result.failed)
        conn.close()

    def test_pipeline_exception_continues_and_logs(self) -> None:
        """When a transformer raises, the pipeline continues and logs the failure."""
        from loguru import logger

        class _BrokenTransformer(BaseTransformer):
            output_table: ClassVar[str] = "broken_table"
            depends_on: ClassVar[list[str]] = []

            def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
                raise ValueError("intentional transform failure")

        log_messages: list[str] = []

        sink_id = logger.add(log_messages.append, format="{message}", level="ERROR")
        try:
            conn = duckdb.connect()
            pipeline = TransformPipeline(conn)
            pipeline.register(_BrokenTransformer())
            pipeline.register(_TransA())

            staging: dict[str, pl.LazyFrame] = {"raw_input": pl.DataFrame({"val": [1]}).lazy()}

            outputs = pipeline.run(staging)

            # Pipeline should continue: broken_table skipped, table_a succeeded
            assert "broken_table" not in outputs
            assert "table_a" in outputs
            conn.close()
        finally:
            logger.remove(sink_id)

        # The error log should contain the transformer class name
        all_messages = "\n".join(log_messages)
        assert "_BrokenTransformer" in all_messages or "broken_table" in all_messages

    # ------------------------------------------------------------------
    # Checkpoint / resume tests
    # ------------------------------------------------------------------

    @staticmethod
    def _create_checkpoint_table(conn: duckdb.DuckDBPyConnection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS _transform_checkpoints (
                run_id VARCHAR NOT NULL,
                table_name VARCHAR NOT NULL,
                completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                row_count BIGINT,
                PRIMARY KEY (run_id, table_name)
            )
        """)

    def test_checkpoint_saves_on_success(self) -> None:
        """After successful transform, checkpoint is recorded then cleared."""
        conn = duckdb.connect()
        self._create_checkpoint_table(conn)
        pipeline = TransformPipeline(conn, run_id="test-run")
        pipeline.register(_TransA())
        staging = {"raw_input": pl.DataFrame({"val": [10]}).lazy()}
        pipeline.run(staging)
        # Checkpoint should be cleared after a fully successful run
        rows = conn.execute(
            "SELECT COUNT(*) FROM _transform_checkpoints WHERE run_id='test-run'"
        ).fetchone()
        assert rows[0] == 0
        conn.close()

    def test_checkpoint_resume_skips_completed(self) -> None:
        """Resume skips tables that were checkpointed from a prior partial run."""
        conn = duckdb.connect()
        self._create_checkpoint_table(conn)
        # Simulate a prior partial run that completed table_a
        conn.execute(
            "INSERT INTO _transform_checkpoints VALUES "
            "('test-run', 'table_a', CURRENT_TIMESTAMP, 1)"
        )
        # Also register table_a data in DuckDB as if it had been computed
        conn.register("table_a", pl.DataFrame({"val": [10], "val_a": [10]}))

        pipeline = TransformPipeline(conn, run_id="test-run")
        pipeline.register(_TransA())
        pipeline.register(_TransB())
        staging = {"raw_input": pl.DataFrame({"val": [10]}).lazy()}
        outputs = pipeline.run(staging, resume=True)

        assert "table_a" in outputs  # Loaded from checkpoint
        assert "table_b" in outputs  # Computed normally
        result = pipeline.last_result
        assert result is not None
        assert "table_a" in result.skipped  # Was skipped via checkpoint
        conn.close()

    def test_checkpoint_without_table_is_noop(self) -> None:
        """If checkpoint table doesn't exist, resume gracefully returns empty."""
        conn = duckdb.connect()
        pipeline = TransformPipeline(conn, run_id="test-run")
        pipeline.register(_TransA())
        staging = {"raw_input": pl.DataFrame({"val": [10]}).lazy()}
        outputs = pipeline.run(staging, resume=True)
        assert "table_a" in outputs
        conn.close()

    def test_checkpoint_retained_on_partial_failure(self) -> None:
        """When a transformer fails, checkpoints for completed tables are retained."""

        class _FailingTransB(BaseTransformer):
            output_table: ClassVar[str] = "table_b"
            depends_on: ClassVar[list[str]] = ["table_a"]

            def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
                raise RuntimeError("simulated failure")

        conn = duckdb.connect()
        self._create_checkpoint_table(conn)
        pipeline = TransformPipeline(conn, run_id="test-run")
        pipeline.register(_TransA())
        pipeline.register(_FailingTransB())
        staging = {"raw_input": pl.DataFrame({"val": [10]}).lazy()}
        pipeline.run(staging)

        # table_a succeeded so its checkpoint should be retained (run had failures)
        rows = conn.execute(
            "SELECT table_name FROM _transform_checkpoints WHERE run_id='test-run'"
        ).fetchall()
        assert ("table_a",) in rows
        conn.close()
