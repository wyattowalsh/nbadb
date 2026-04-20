from __future__ import annotations

from typing import TYPE_CHECKING

import polars as pl

from nbadb.load.parquet_loader import PARTITIONED_TABLES, ParquetLoader

if TYPE_CHECKING:
    from pathlib import Path


class TestParquetLoader:
    def test_writes_single_file(self, tmp_path: Path) -> None:
        loader = ParquetLoader(tmp_path)
        df = pl.DataFrame(
            {
                "player_id": [1, 2],
                "name": ["A", "B"],
            }
        )
        loader.load("dim_player", df)
        parquet_file = tmp_path / "dim_player" / "dim_player.parquet"
        assert parquet_file.exists()
        loaded = pl.read_parquet(parquet_file)
        assert loaded.shape == (2, 2)

    def test_partitioned_by_season(self, tmp_path: Path) -> None:
        table = next(iter(PARTITIONED_TABLES))
        loader = ParquetLoader(tmp_path)
        df = pl.DataFrame(
            {
                "game_id": ["001", "002", "003"],
                "season_year": ["2023-24", "2023-24", "2024-25"],
                "pts": [100, 110, 105],
            }
        )
        loader.load(table, df)
        assert (tmp_path / table / "season_year=2023-24" / "part0.parquet").exists()
        assert (tmp_path / table / "season_year=2024-25" / "part0.parquet").exists()

    def test_partitioned_drops_season_column(self, tmp_path: Path) -> None:
        table = next(iter(PARTITIONED_TABLES))
        loader = ParquetLoader(tmp_path)
        df = pl.DataFrame(
            {
                "game_id": ["001"],
                "season_year": ["2024-25"],
                "pts": [100],
            }
        )
        loader.load(table, df)
        part_file = tmp_path / table / "season_year=2024-25" / "part0.parquet"
        loaded = pl.read_parquet(part_file)
        assert "season_year" not in loaded.columns
        assert "game_id" in loaded.columns

    def test_non_partitioned_table_not_hive_split(self, tmp_path: Path) -> None:
        loader = ParquetLoader(tmp_path)
        df = pl.DataFrame(
            {
                "id": [1],
                "season_year": ["2024-25"],
            }
        )
        loader.load("small_table", df)
        assert (tmp_path / "small_table" / "small_table.parquet").exists()
        assert not (tmp_path / "small_table" / "season_year=2024-25").exists()

    def test_partitioned_table_without_season_col(self, tmp_path: Path) -> None:
        table = next(iter(PARTITIONED_TABLES))
        loader = ParquetLoader(tmp_path)
        df = pl.DataFrame({"game_id": ["001"], "pts": [100]})
        loader.load(table, df)
        assert (tmp_path / table / f"{table}.parquet").exists()

    def test_custom_compression_level(self, tmp_path: Path) -> None:
        loader = ParquetLoader(tmp_path, compression_level=1)
        df = pl.DataFrame({"x": [1]})
        loader.load("compressed", df)
        assert (tmp_path / "compressed" / "compressed.parquet").exists()

    def test_creates_nested_dirs(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b"
        loader = ParquetLoader(nested)
        df = pl.DataFrame({"x": [1]})
        loader.load("tbl", df)
        assert (nested / "tbl" / "tbl.parquet").exists()
