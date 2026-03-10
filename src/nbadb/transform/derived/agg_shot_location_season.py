from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggShotLocationSeasonTransformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_shot_location_season"
    depends_on: ClassVar[list[str]] = ["stg_shot_locations"]

    _SQL: ClassVar[str] = """
        SELECT
            *,
            ROW_NUMBER() OVER (
                PARTITION BY season_year
                ORDER BY fgm DESC NULLS LAST
            ) AS season_fgm_rank
        FROM stg_shot_locations
        ORDER BY season_year, season_fgm_rank
    """
