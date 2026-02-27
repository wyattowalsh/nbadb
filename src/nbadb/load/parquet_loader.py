from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from loguru import logger

from nbadb.load.base import BaseLoader

if TYPE_CHECKING:
    from pathlib import Path

    import polars as pl

PARTITIONED_TABLES = {
    "fact_player_game_traditional",
    "fact_player_game_advanced",
    "fact_player_game_misc",
    "fact_player_game_hustle",
    "fact_player_game_tracking",
    "fact_team_game_stats",
    "fact_play_by_play",
    "fact_shot_chart",
    "fact_matchup",
    "fact_rotation",
    "fact_game_result",
    "fact_game_scoring",
    "fact_standings",
    "fact_win_probability",
    "fact_lineup_stats",
    "fact_synergy_play_type",
    "fact_tracking_defense",
    "fact_estimated_metrics",
    "analytics_player_game_complete",
    "analytics_player_season_complete",
    "analytics_team_season_summary",
    "analytics_head_to_head",
    "agg_player_season",
    "agg_player_rolling",
    "agg_team_season",
}


class ParquetLoader(BaseLoader):
    def __init__(
        self, parquet_dir: Path, compression_level: int = 3
    ) -> None:
        self.parquet_dir = parquet_dir
        self.compression_level = compression_level

    def load(
        self,
        table: str,
        df: pl.DataFrame,
        mode: Literal["replace", "append"] = "replace",
    ) -> None:
        if table in PARTITIONED_TABLES and "season_year" in df.columns:
            for (season,), part in df.group_by("season_year"):
                out_dir = self.parquet_dir / table / f"season_year={season}"
                out_dir.mkdir(parents=True, exist_ok=True)
                part.drop("season_year").write_parquet(
                    out_dir / "part0.parquet",
                    compression="zstd",
                    compression_level=self.compression_level,
                    statistics=True,
                )
        else:
            out_dir = self.parquet_dir / table
            out_dir.mkdir(parents=True, exist_ok=True)
            df.write_parquet(
                out_dir / f"{table}.parquet",
                compression="zstd",
                compression_level=self.compression_level,
                statistics=True,
            )
        logger.debug(
            f"Parquet: wrote {df.shape[0]} rows to {table}/"
        )
