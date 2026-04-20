from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb
import polars as pl

from nbadb.core.db import DBManager
from nbadb.load.csv_loader import CSVLoader
from nbadb.load.duckdb_loader import DuckDBLoader
from nbadb.load.multi import MultiLoader, create_multi_loader
from nbadb.load.parquet_loader import ParquetLoader
from nbadb.load.sqlite import SQLiteLoader
from nbadb.transform.base import BaseTransformer
from nbadb.transform.dimensions.dim_season import DimSeasonTransformer
from nbadb.transform.pipeline import TransformPipeline

if TYPE_CHECKING:
    from pathlib import Path


class _DimTeamStubTransformer(BaseTransformer):
    output_table: ClassVar[str] = "dim_team"
    depends_on: ClassVar[list[str]] = ["stg_league_game_log"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        gl = staging["stg_league_game_log"]
        home = gl.select(pl.col("home_team_id").alias("team_id"))
        away = gl.select(pl.col("visitor_team_id").alias("team_id"))
        return pl.concat([home, away]).unique().sort("team_id").collect()


def _make_staging() -> dict[str, pl.LazyFrame]:
    game_log = pl.DataFrame(
        {
            "game_id": ["0022300001", "0022300002", "0022300003", "0022400001", "0022400002"],
            "season_year": ["2023-24", "2023-24", "2023-24", "2024-25", "2024-25"],
            "game_date": [
                "2023-10-24",
                "2023-12-25",
                "2024-04-14",
                "2024-10-22",
                "2025-01-15",
            ],
            "home_team_id": [1610612747, 1610612738, 1610612744, 1610612747, 1610612738],
            "visitor_team_id": [1610612750, 1610612752, 1610612746, 1610612750, 1610612752],
        }
    )
    return {
        "stg_league_game_log": game_log.lazy(),
    }


class TestPipelineE2E:
    def test_dim_season_produces_correct_output(self) -> None:
        conn = duckdb.connect()
        pipeline = TransformPipeline(conn)
        pipeline.register(DimSeasonTransformer())
        outputs = pipeline.run(_make_staging(), validate_output_schemas=False)
        df = outputs["dim_season"]
        assert df.shape[0] == 2
        assert "season_year" in df.columns
        assert "start_date" in df.columns
        assert "end_date" in df.columns
        seasons = df["season_year"].to_list()
        assert "2023-24" in seasons
        assert "2024-25" in seasons
        conn.close()

    def test_dim_team_stub_produces_unique_teams(self) -> None:
        conn = duckdb.connect()
        pipeline = TransformPipeline(conn)
        pipeline.register(_DimTeamStubTransformer())
        outputs = pipeline.run(_make_staging(), validate_output_schemas=False)
        df = outputs["dim_team"]
        assert df.shape[1] == 1
        assert "team_id" in df.columns
        assert df["team_id"].n_unique() == df.shape[0]
        conn.close()

    def test_pipeline_multiple_transformers_dependency_order(self) -> None:
        conn = duckdb.connect()
        pipeline = TransformPipeline(conn)
        pipeline.register_all([DimSeasonTransformer(), _DimTeamStubTransformer()])
        order = pipeline.execution_order
        assert "dim_season" in order
        assert "dim_team" in order
        conn.close()

    def test_pipeline_registers_tables_in_duckdb(self) -> None:
        conn = duckdb.connect()
        pipeline = TransformPipeline(conn)
        pipeline.register_all([DimSeasonTransformer(), _DimTeamStubTransformer()])
        pipeline.run(_make_staging(), validate_output_schemas=False)
        season_count = conn.execute("SELECT COUNT(*) FROM dim_season").fetchone()[0]
        assert season_count == 2
        team_count = conn.execute("SELECT COUNT(*) FROM dim_team").fetchone()[0]
        assert team_count > 0
        conn.close()

    def test_all_four_loaders_match_row_counts(self, tmp_path: Path) -> None:
        conn = duckdb.connect()
        pipeline = TransformPipeline(conn)
        pipeline.register(DimSeasonTransformer())
        outputs = pipeline.run(_make_staging(), validate_output_schemas=False)
        df = outputs["dim_season"]
        expected_rows = df.shape[0]

        sqlite_path = tmp_path / "test.sqlite"
        sqlite_loader = SQLiteLoader(sqlite_path)
        sqlite_loader.load("dim_season", df)

        duck_loader = DuckDBLoader(conn)
        duck_loader.load("dim_season_loaded", df)

        pq_loader = ParquetLoader(tmp_path / "parquet")
        pq_loader.load("dim_season", df)

        csv_loader = CSVLoader(tmp_path / "csv")
        csv_loader.load("dim_season", df)

        sqlite_df = pl.read_database_uri(
            "SELECT COUNT(*) as cnt FROM dim_season",
            f"sqlite:///{sqlite_path}",
            engine="adbc",
        )
        assert sqlite_df["cnt"][0] == expected_rows

        duck_count = conn.execute("SELECT COUNT(*) FROM dim_season_loaded").fetchone()[0]
        assert duck_count == expected_rows

        pq_df = pl.read_parquet(tmp_path / "parquet" / "dim_season" / "dim_season.parquet")
        assert pq_df.shape[0] == expected_rows

        csv_df = pl.read_csv(tmp_path / "csv" / "dim_season.csv")
        assert csv_df.shape[0] == expected_rows

        conn.close()

    def test_multi_loader_all_formats(self, tmp_path: Path) -> None:
        conn = duckdb.connect()
        pipeline = TransformPipeline(conn)
        pipeline.register(DimSeasonTransformer())
        outputs = pipeline.run(_make_staging(), validate_output_schemas=False)
        df = outputs["dim_season"]

        loader = MultiLoader(
            [
                CSVLoader(tmp_path / "csv"),
                ParquetLoader(tmp_path / "parquet"),
                DuckDBLoader(conn),
            ]
        )
        loader.load("dim_season", df)

        assert (tmp_path / "csv" / "dim_season.csv").exists()
        assert (tmp_path / "parquet" / "dim_season" / "dim_season.parquet").exists()
        duck_count = conn.execute("SELECT COUNT(*) FROM dim_season").fetchone()[0]
        assert duck_count == df.shape[0]
        conn.close()

    def test_full_roundtrip_with_db_manager(self, tmp_path: Path) -> None:
        with DBManager(
            sqlite_path=tmp_path / "test.sqlite",
            duckdb_path=tmp_path / "test.duckdb",
        ) as db:
            pipeline = TransformPipeline(db.duckdb)
            pipeline.register(DimSeasonTransformer())
            outputs = pipeline.run(_make_staging(), validate_output_schemas=False)
            csv_loader = CSVLoader(tmp_path / "csv")
            csv_loader.load("dim_season", outputs["dim_season"])
            loaded = pl.read_csv(tmp_path / "csv" / "dim_season.csv")
            assert loaded.shape[0] == 2

    def test_create_multi_loader_factory_e2e(self, tmp_path: Path) -> None:
        from nbadb.core.config import NbaDbSettings

        settings = NbaDbSettings(
            data_dir=tmp_path / "data",
            log_dir=tmp_path / "logs",
            formats=["csv", "parquet"],
        )
        conn = duckdb.connect()
        pipeline = TransformPipeline(conn)
        pipeline.register(DimSeasonTransformer())
        outputs = pipeline.run(_make_staging(), validate_output_schemas=False)
        loader = create_multi_loader(settings)
        loader.load("dim_season", outputs["dim_season"])
        assert (tmp_path / "data" / "csv" / "dim_season.csv").exists()
        assert (tmp_path / "data" / "parquet" / "dim_season" / "dim_season.parquet").exists()
        conn.close()

    def test_get_output_returns_correct_df(self) -> None:
        conn = duckdb.connect()
        pipeline = TransformPipeline(conn)
        pipeline.register(DimSeasonTransformer())
        pipeline.run(_make_staging(), validate_output_schemas=False)
        result = pipeline.get_output("dim_season")
        assert result is not None
        assert result.shape[0] == 2
        assert pipeline.get_output("nonexistent") is None
        conn.close()
