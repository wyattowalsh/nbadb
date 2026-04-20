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

    # ------------------------------------------------------------------
    # Arrow path (_load_via_arrow) — triggered when rows >= 100K
    # ------------------------------------------------------------------

    def test_arrow_path_replace(self) -> None:
        """Large DataFrame (>=100K rows) triggers the Arrow zero-copy path."""
        conn = duckdb.connect()
        loader = DuckDBLoader(conn)
        df = pl.DataFrame({"id": range(100_001)})
        loader.load("arrow_tbl", df, mode="replace")
        count = conn.execute("SELECT COUNT(*) FROM arrow_tbl").fetchone()[0]
        assert count == 100_001
        conn.close()

    def test_arrow_path_append(self) -> None:
        """Append mode via Arrow path adds rows to an existing table."""
        conn = duckdb.connect()
        loader = DuckDBLoader(conn)
        df1 = pl.DataFrame({"id": range(100_001)})
        loader.load("arrow_append", df1, mode="replace")
        df2 = pl.DataFrame({"id": range(100_001, 200_002)})
        loader.load("arrow_append", df2, mode="append")
        count = conn.execute("SELECT COUNT(*) FROM arrow_append").fetchone()[0]
        assert count == 200_002
        conn.close()

    # ------------------------------------------------------------------
    # load_arrow — direct PyArrow table loading
    # ------------------------------------------------------------------

    def test_load_arrow_replace(self) -> None:
        """load_arrow creates a table from a PyArrow table in replace mode."""
        import pyarrow as pa

        conn = duckdb.connect()
        loader = DuckDBLoader(conn)
        arrow_table = pa.table({"id": [1, 2, 3], "val": ["a", "b", "c"]})
        loader.load_arrow("pa_tbl", arrow_table, mode="replace")
        result = conn.execute("SELECT * FROM pa_tbl ORDER BY id").fetchall()
        assert len(result) == 3
        assert result[0] == (1, "a")
        conn.close()

    def test_load_arrow_append(self) -> None:
        """load_arrow in append mode adds rows to an existing table."""
        import pyarrow as pa

        conn = duckdb.connect()
        loader = DuckDBLoader(conn)
        t1 = pa.table({"id": [1, 2]})
        loader.load_arrow("pa_append", t1, mode="replace")
        t2 = pa.table({"id": [3, 4]})
        loader.load_arrow("pa_append", t2, mode="append")
        count = conn.execute("SELECT COUNT(*) FROM pa_append").fetchone()[0]
        assert count == 4
        conn.close()

    def test_load_arrow_replace_overwrites(self) -> None:
        """load_arrow in replace mode drops old data."""
        import pyarrow as pa

        conn = duckdb.connect()
        loader = DuckDBLoader(conn)
        t1 = pa.table({"id": [1, 2, 3]})
        loader.load_arrow("pa_overwrite", t1, mode="replace")
        t2 = pa.table({"id": [99]})
        loader.load_arrow("pa_overwrite", t2, mode="replace")
        rows = conn.execute("SELECT id FROM pa_overwrite").fetchall()
        assert rows == [(99,)]
        conn.close()
