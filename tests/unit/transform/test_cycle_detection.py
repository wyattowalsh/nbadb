"""Tests for TransformPipeline topological sort and cycle detection."""

from __future__ import annotations

from typing import ClassVar

import duckdb
import polars as pl
import pytest

from nbadb.transform.base import BaseTransformer
from nbadb.transform.pipeline import TransformPipeline


# ---------------------------------------------------------------------------
# Stub transformers
# ---------------------------------------------------------------------------


class TransformerA(BaseTransformer):
    output_table: ClassVar[str] = "table_a"
    depends_on: ClassVar[list[str]] = []

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return pl.DataFrame({"x": [1]})


class TransformerB(BaseTransformer):
    output_table: ClassVar[str] = "table_b"
    depends_on: ClassVar[list[str]] = ["table_a"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return pl.DataFrame({"x": [2]})


class TransformerC(BaseTransformer):
    output_table: ClassVar[str] = "table_c"
    depends_on: ClassVar[list[str]] = ["table_b"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return pl.DataFrame({"x": [3]})


class CyclicA(BaseTransformer):
    output_table: ClassVar[str] = "cyc_a"
    depends_on: ClassVar[list[str]] = ["cyc_b"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return pl.DataFrame({"x": [1]})


class CyclicB(BaseTransformer):
    output_table: ClassVar[str] = "cyc_b"
    depends_on: ClassVar[list[str]] = ["cyc_a"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return pl.DataFrame({"x": [2]})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_topological_sort_linear() -> None:
    conn = duckdb.connect()
    pipeline = TransformPipeline(conn)
    pipeline.register_all([TransformerC(), TransformerA(), TransformerB()])
    order = pipeline.execution_order
    assert order.index("table_a") < order.index("table_b")
    assert order.index("table_b") < order.index("table_c")
    conn.close()


def test_topological_sort_cycle_detection() -> None:
    conn = duckdb.connect()
    pipeline = TransformPipeline(conn)
    pipeline.register_all([CyclicA(), CyclicB()])
    with pytest.raises(ValueError, match="Cyclic dependency"):
        pipeline.execution_order
    conn.close()


def test_missing_dependency_handled() -> None:
    """Transformer with dep on non-registered table should not crash the sort."""
    conn = duckdb.connect()
    pipeline = TransformPipeline(conn)
    pipeline.register(TransformerB())  # depends on table_a which is not registered
    order = pipeline.execution_order
    assert order == ["table_b"]
    conn.close()
