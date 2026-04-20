from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl
import pytest

from nbadb.load.sqlite import SQLiteLoader

if TYPE_CHECKING:
    from pathlib import Path


class TestSQLiteLoader:
    def test_writes_to_sqlite(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.sqlite"
        loader = SQLiteLoader(db_path)
        df = pl.DataFrame({"id": [1, 2], "name": ["a", "b"]})
        loader.load("test_table", df)
        loaded = pl.read_database_uri(
            "SELECT * FROM test_table ORDER BY id",
            f"sqlite:///{db_path}",
            engine="adbc",
        )
        assert loaded.shape == (2, 2)

    def test_replace_mode_overwrites(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.sqlite"
        loader = SQLiteLoader(db_path)
        df1 = pl.DataFrame({"id": [1, 2, 3]})
        df2 = pl.DataFrame({"id": [10]})
        loader.load("tbl", df1)
        loader.load("tbl", df2, mode="replace")
        loaded = pl.read_database_uri(
            "SELECT COUNT(*) as cnt FROM tbl",
            f"sqlite:///{db_path}",
            engine="adbc",
        )
        assert loaded["cnt"][0] == 1

    @pytest.mark.skip(reason="adbc append may not work on all platforms")
    def test_append_mode(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.sqlite"
        loader = SQLiteLoader(db_path)
        df1 = pl.DataFrame({"id": [1]})
        loader.load("tbl", df1)
        df2 = pl.DataFrame({"id": [2]})
        loader.load("tbl", df2, mode="append")
        loaded = pl.read_database_uri(
            "SELECT COUNT(*) as cnt FROM tbl",
            f"sqlite:///{db_path}",
            engine="adbc",
        )
        assert loaded["cnt"][0] == 2
