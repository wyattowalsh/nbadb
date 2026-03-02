from __future__ import annotations

from typing import ClassVar

import polars as pl
import pytest

from nbadb.transform.base import BaseTransformer


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
