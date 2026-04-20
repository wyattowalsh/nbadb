from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb
import polars as pl

from nbadb.load.csv_loader import CSVLoader
from nbadb.load.duckdb_loader import DuckDBLoader
from nbadb.load.parquet_loader import ParquetLoader
from nbadb.transform.base import BaseTransformer
from nbadb.transform.pipeline import TransformPipeline

if TYPE_CHECKING:
    from pathlib import Path


class _IdentityTransformer(BaseTransformer):
    output_table: ClassVar[str] = "dim_test"
    depends_on: ClassVar[list[str]] = []

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return staging["raw"].collect()


class TestExtractToLoad:
    def test_pipeline_then_load_csv(self, tmp_path: Path) -> None:
        raw_df = pl.DataFrame(
            {
                "player_id": [1, 2, 3],
                "name": ["A", "B", "C"],
                "pts": [20, 25, 30],
            }
        )
        conn = duckdb.connect()
        pipeline = TransformPipeline(conn)
        pipeline.register(_IdentityTransformer())
        outputs = pipeline.run({"raw": raw_df.lazy()})
        csv_loader = CSVLoader(tmp_path / "csv")
        csv_loader.load("dim_test", outputs["dim_test"])
        loaded = pl.read_csv(tmp_path / "csv" / "dim_test.csv")
        assert loaded.shape == (3, 3)
        conn.close()

    def test_pipeline_then_load_parquet(self, tmp_path: Path) -> None:
        raw_df = pl.DataFrame(
            {
                "team_id": [10, 20],
                "name": ["Team A", "Team B"],
            }
        )
        conn = duckdb.connect()
        pipeline = TransformPipeline(conn)
        pipeline.register(_IdentityTransformer())
        outputs = pipeline.run({"raw": raw_df.lazy()})
        pq_loader = ParquetLoader(tmp_path / "parquet")
        pq_loader.load("dim_test", outputs["dim_test"])
        loaded = pl.read_parquet(tmp_path / "parquet" / "dim_test" / "dim_test.parquet")
        assert loaded.shape == (2, 2)
        conn.close()

    def test_pipeline_then_load_duckdb(self) -> None:
        raw_df = pl.DataFrame(
            {
                "game_id": ["001", "002"],
                "pts": [100, 110],
            }
        )
        conn = duckdb.connect()
        pipeline = TransformPipeline(conn)
        pipeline.register(_IdentityTransformer())
        outputs = pipeline.run({"raw": raw_df.lazy()})
        duck_loader = DuckDBLoader(conn)
        duck_loader.load("loaded_dim_test", outputs["dim_test"])
        count = conn.execute("SELECT COUNT(*) FROM loaded_dim_test").fetchone()[0]
        assert count == 2
        conn.close()

    def test_roundtrip_preserves_data(self, tmp_path: Path) -> None:
        original = pl.DataFrame(
            {
                "id": [1, 2, 3, 4, 5],
                "value": [1.1, 2.2, 3.3, 4.4, 5.5],
                "label": ["a", "b", "c", "d", "e"],
            }
        )
        csv_loader = CSVLoader(tmp_path)
        csv_loader.load("roundtrip", original)
        loaded = pl.read_csv(tmp_path / "roundtrip.csv")
        assert loaded.shape == original.shape
        assert loaded["id"].to_list() == original["id"].to_list()
        assert loaded["label"].to_list() == original["label"].to_list()
