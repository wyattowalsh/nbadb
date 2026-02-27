from __future__ import annotations

from typing import ClassVar

import duckdb
import polars as pl

from nbadb.transform.base import BaseTransformer
from nbadb.transform.pipeline import TransformPipeline


class _TransA(BaseTransformer):
    output_table: ClassVar[str] = "table_a"
    depends_on: ClassVar[list[str]] = []

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
