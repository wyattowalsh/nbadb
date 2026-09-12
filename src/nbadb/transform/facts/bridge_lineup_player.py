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
            collected = src.select("group_id", "team_id", "season_year").collect()
            df = collected if isinstance(collected, pl.DataFrame) else collected.fetch_blocking()
            if df.is_empty():
                continue

            prepared = (
                df.with_columns(
                    pl.col("group_id").str.split("-").alias("_player_tokens"),
                )
                .with_columns(
                    pl.col("_player_tokens")
                    .list.eval(pl.element().cast(pl.Int64, strict=False))
                    .alias("_player_ids"),
                    pl.col("_player_tokens").list.len().alias("_player_count"),
                )
                .with_columns(
                    pl.col("_player_tokens")
                    .list.eval(pl.element().str.len_chars() > 0)
                    .list.all()
                    .alias("_tokens_nonempty"),
                    pl.col("_player_ids")
                    .list.eval(pl.element().is_not_null() & (pl.element() > 0))
                    .list.all()
                    .alias("_ids_positive"),
                    pl.col("_player_ids").list.n_unique().alias("_unique_player_count"),
                )
            )
            valid_group = (
                pl.col("_player_count").is_between(1, 5)
                & pl.col("_tokens_nonempty")
                & pl.col("_ids_positive")
                & (pl.col("_unique_player_count") == pl.col("_player_count"))
            ).fill_null(False)
            if prepared.filter(~valid_group).height:
                raise ValueError(
                    "lineup group_id must contain 1-5 unique positive Int64 player tokens"
                )

            exploded = (
                prepared.unique(subset=["group_id", "team_id", "season_year"])
                .explode("_player_ids", empty_as_null=True)
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
            .sort("group_id", "team_id", "season_year", "position_in_lineup")
        )
