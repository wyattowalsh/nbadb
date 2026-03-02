from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import duckdb
import polars as pl

from nbadb.core.config import NbaDbSettings
from nbadb.load.csv_loader import CSVLoader
from nbadb.load.duckdb_loader import DuckDBLoader
from nbadb.load.multi import MultiLoader, create_multi_loader
from nbadb.load.parquet_loader import ParquetLoader

if TYPE_CHECKING:
    from pathlib import Path


class TestMultiLoader:
    def test_loads_to_multiple_formats(self, tmp_path: Path) -> None:
        loaders = [
            CSVLoader(tmp_path / "csv"),
            ParquetLoader(tmp_path / "parquet"),
        ]
        loader = MultiLoader(loaders)
        df = pl.DataFrame({"id": [1, 2], "val": ["a", "b"]})
        loader.load("test_table", df)
        assert (tmp_path / "csv" / "test_table.csv").exists()
        assert (tmp_path / "parquet" / "test_table" / "test_table.parquet").exists()

    def test_delegates_to_each_child_with_same_args(self) -> None:
        mock1 = MagicMock()
        mock2 = MagicMock()
        mock3 = MagicMock()
        loader = MultiLoader([mock1, mock2, mock3])
        df = pl.DataFrame({"x": [1]})
        loader.load("tbl", df, mode="append")
        for m in (mock1, mock2, mock3):
            m.load.assert_called_once_with("tbl", df, "append")

    def test_empty_loaders_list(self) -> None:
        loader = MultiLoader([])
        df = pl.DataFrame({"x": [1]})
        loader.load("tbl", df)

    def test_with_duckdb_loader(self) -> None:
        conn = duckdb.connect()
        loader = MultiLoader([DuckDBLoader(conn)])
        df = pl.DataFrame({"id": [1]})
        loader.load("duck_tbl", df)
        result = conn.execute("SELECT * FROM duck_tbl").fetchall()
        assert len(result) == 1
        conn.close()


class TestCreateMultiLoader:
    def test_creates_csv_and_parquet(self, tmp_path: Path) -> None:
        settings = NbaDbSettings(
            data_dir=tmp_path / "data",
            log_dir=tmp_path / "logs",
            formats=["csv", "parquet"],
        )
        ml = create_multi_loader(settings)
        assert len(ml._loaders) == 2
        df = pl.DataFrame({"id": [1]})
        ml.load("tbl", df)
        assert (tmp_path / "data" / "csv" / "tbl.csv").exists()
        assert (tmp_path / "data" / "parquet" / "tbl" / "tbl.parquet").exists()

    def test_duckdb_opens_own_conn_when_none_passed(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True)
        # Create an empty DuckDB file so the loader can open it
        db_path = data_dir / "nba.duckdb"
        conn = duckdb.connect(str(db_path))
        conn.close()
        settings = NbaDbSettings(
            data_dir=data_dir,
            log_dir=tmp_path / "logs",
            formats=["duckdb"],
        )
        ml = create_multi_loader(settings)
        assert len(ml._loaders) == 1

    def test_duckdb_with_conn(self, tmp_path: Path) -> None:
        settings = NbaDbSettings(
            data_dir=tmp_path / "data",
            log_dir=tmp_path / "logs",
            formats=["duckdb"],
        )
        conn = duckdb.connect()
        ml = create_multi_loader(settings, duckdb_conn=conn)
        assert len(ml._loaders) == 1
        conn.close()

    def test_sqlite_format(self, tmp_path: Path) -> None:
        settings = NbaDbSettings(
            data_dir=tmp_path / "data",
            log_dir=tmp_path / "logs",
            formats=["sqlite"],
        )
        ml = create_multi_loader(settings)
        assert len(ml._loaders) == 1
