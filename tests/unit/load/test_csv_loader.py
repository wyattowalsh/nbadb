from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from nbadb.load.csv_loader import CSVLoader

if TYPE_CHECKING:
    from pathlib import Path


class TestCSVLoader:
    def test_writes_csv_file(self, tmp_path: Path) -> None:
        loader = CSVLoader(tmp_path / "csv")
        df = pl.DataFrame({"a": [1, 2], "b": ["x", "y"]})
        loader.load("test_table", df)
        output = tmp_path / "csv" / "test_table.csv"
        assert output.exists()
        loaded = pl.read_csv(output)
        assert loaded.shape == (2, 2)
        assert loaded["a"].to_list() == [1, 2]

    def test_creates_output_dir(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "c"
        loader = CSVLoader(nested)
        df = pl.DataFrame({"x": [1]})
        loader.load("tbl", df)
        assert (nested / "tbl.csv").exists()

    def test_replace_overwrites(self, tmp_path: Path) -> None:
        loader = CSVLoader(tmp_path)
        df1 = pl.DataFrame({"v": [1, 2, 3]})
        df2 = pl.DataFrame({"v": [10]})
        loader.load("t", df1)
        loader.load("t", df2, mode="replace")
        loaded = pl.read_csv(tmp_path / "t.csv")
        assert loaded.shape == (1, 1)
