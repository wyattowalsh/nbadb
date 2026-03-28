from __future__ import annotations

from typing import ClassVar

import polars as pl

from nbadb.transform.base import BaseTransformer


class BridgeLineupPlayerTransformer(BaseTransformer):
    """Explode opaque ``group_id`` (e.g. "201566-203507-1627759-1628389-1629029")
    from lineup stats into individual player rows so consumers can query
    "find all lineups containing player X".
    """

    output_table: ClassVar[str] = "bridge_lineup_player"
    depends_on: ClassVar[list[str]] = ["stg_lineup", "stg_team_lineups"]

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        frames: list[pl.DataFrame] = []
        for key in ("stg_lineup", "stg_team_lineups"):
            src = staging.get(key)
            if src is None:
                continue
            df = src.select("group_id", "team_id", "season_year").unique().collect()
            if df.is_empty():
                continue
            exploded = (
                df.with_columns(
                    pl.col("group_id").str.split("-").alias("_player_ids"),
                )
                .explode("_player_ids")
                .with_columns(
                    pl.col("_player_ids").cast(pl.Int64).alias("player_id"),
                    (pl.int_range(pl.len()).over("group_id", "team_id", "season_year") + 1)
                    .cast(pl.Int32)
                    .alias("position_in_lineup"),
                )
                .select("group_id", "player_id", "team_id", "position_in_lineup", "season_year")
            )
            frames.append(exploded)

        if not frames:
            return pl.DataFrame(
                schema={
                    "group_id": pl.Utf8,
                    "player_id": pl.Int64,
                    "team_id": pl.Int64,
                    "position_in_lineup": pl.Int32,
                    "season_year": pl.Utf8,
                },
            )

        return (
            pl.concat(frames)
            .unique(subset=["group_id", "player_id", "team_id", "season_year"])
            .sort("group_id", "position_in_lineup")
        )
