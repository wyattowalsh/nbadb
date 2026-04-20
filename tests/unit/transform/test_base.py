from __future__ import annotations

from typing import ClassVar

import polars as pl
import pytest

from nbadb.transform.base import BaseTransformer, SqlTransformer


class _StubTransformer(BaseTransformer):
    output_table: ClassVar[str] = "test_table"
    depends_on: ClassVar[list[str]] = []

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return staging["input"].collect()


class TestBaseTransformer:
    def test_run_calls_transform(self) -> None:
        t = _StubTransformer()
        df = pl.DataFrame({"x": [1, 2, 3]})
        result = t.run({"input": df.lazy()})
        assert result.shape == (3, 1)
        assert result["x"].to_list() == [1, 2, 3]

    def test_conn_raises_without_injection(self) -> None:
        t = _StubTransformer()
        with pytest.raises(RuntimeError, match="No DuckDB connection injected"):
            _ = t.conn

    def test_conn_uses_injected(self) -> None:
        import duckdb

        shared = duckdb.connect()
        t = _StubTransformer()
        t._conn = shared
        assert t.conn is shared
        shared.close()

    def test_class_attributes(self) -> None:
        assert _StubTransformer.output_table == "test_table"
        assert _StubTransformer.depends_on == []

    def test_abstract_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            BaseTransformer()  # type: ignore[abstract]


class _TestSqlTransformer(SqlTransformer):
    output_table: ClassVar[str] = "test_sql"
    depends_on: ClassVar[list[str]] = []
    _SQL: ClassVar[str] = "SELECT 1 AS val"


class TestSqlTransformer:
    def test_executes_sql(self) -> None:
        import duckdb

        conn = duckdb.connect()
        t = _TestSqlTransformer()
        t._conn = conn
        result = t.transform({})
        assert result["val"].to_list() == [1]
        conn.close()

    def test_missing_sql_raises(self) -> None:
        import duckdb

        class _NoSql(SqlTransformer):
            output_table: ClassVar[str] = "no_sql"
            depends_on: ClassVar[list[str]] = []

        conn = duckdb.connect()
        t = _NoSql()
        t._conn = conn
        with pytest.raises(NotImplementedError, match="must define a non-empty _SQL"):
            t.transform({})
        conn.close()

    def test_is_not_abstract(self) -> None:
        """SqlTransformer with _SQL set can be instantiated directly."""
        t = _TestSqlTransformer()
        assert t.output_table == "test_sql"

    def test_run_delegates_to_transform(self) -> None:
        import duckdb

        conn = duckdb.connect()
        t = _TestSqlTransformer()
        t._conn = conn
        result = t.run({})
        assert result.shape == (1, 1)
        conn.close()

    def test_conn_property_used(self) -> None:
        """Without injection, transform raises RuntimeError via .conn."""
        t = _TestSqlTransformer()
        with pytest.raises(RuntimeError, match="No DuckDB connection injected"):
            t.transform({})
