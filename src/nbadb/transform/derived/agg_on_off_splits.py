from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class AggOnOffSplitsTransformer(BaseTransformer):
    output_table: ClassVar[str] = "agg_on_off_splits"
    depends_on: ClassVar[list[str]] = [
        "stg_team_dashboard_on_off",
        "stg_on_off",
    ]

    _SQL: ClassVar[str] = """
        SELECT
            'player' AS entity_type,
            player_id AS entity_id,
            team_id,
            season_year,
            on_off,
            gp, min, pts, reb, ast,
            off_rating, def_rating, net_rating
        FROM stg_on_off
        UNION ALL
        SELECT
            'team' AS entity_type,
            NULL AS entity_id,
            team_id,
            season_year,
            on_off,
            gp, min, pts, reb, ast,
            off_rating, def_rating, net_rating
        FROM stg_team_dashboard_on_off
        ORDER BY season_year, entity_type, entity_id
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        conn.register("stg_on_off", staging["stg_on_off"].collect())
        conn.register(
            "stg_team_dashboard_on_off",
            staging["stg_team_dashboard_on_off"].collect(),
        )
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
