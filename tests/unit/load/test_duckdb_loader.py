from __future__ import annotations

import duckdb
import polars as pl

from nbadb.load.duckdb_loader import DuckDBLoader


class TestDuckDBLoader:
    def test_replace_creates_table(self) -> None:
        conn = duckdb.connect()
        loader = DuckDBLoader(conn)
        df = pl.DataFrame({"id": [1, 2], "val": ["a", "b"]})
        loader.load("test_tbl", df, mode="replace")
        result = conn.execute("SELECT * FROM test_tbl ORDER BY id").fetchall()
        assert len(result) == 2
        assert result[0] == (1, "a")
        conn.close()

    def test_replace_overwrites_existing(self) -> None:
        conn = duckdb.connect()
        loader = DuckDBLoader(conn)
        df1 = pl.DataFrame({"id": [1, 2, 3]})
        df2 = pl.DataFrame({"id": [10]})
        loader.load("tbl", df1, mode="replace")
        loader.load("tbl", df2, mode="replace")
        count = conn.execute("SELECT COUNT(*) FROM tbl").fetchone()[0]
        assert count == 1
        conn.close()

    def test_append_adds_rows(self) -> None:
        conn = duckdb.connect()
        loader = DuckDBLoader(conn)
        df1 = pl.DataFrame({"id": [1]})
        loader.load("append_tbl", df1, mode="replace")
        df2 = pl.DataFrame({"id": [2]})
        loader.load("append_tbl", df2, mode="append")
        count = conn.execute("SELECT COUNT(*) FROM append_tbl").fetchone()[0]
        assert count == 2
        conn.close()
