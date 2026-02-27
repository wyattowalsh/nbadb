from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class FactEstimatedMetricsTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_estimated_metrics"
    depends_on: ClassVar[list[str]] = [
        "stg_player_tracking",
        "stg_team_dashboard_estimated",
    ]

    _SQL: ClassVar[str] = """
        SELECT
            'player' AS entity_type,
            p.player_id AS entity_id,
            p.team_id,
            p.season_year,
            p.gp, p.min,
            p.e_off_rating, p.e_def_rating, p.e_net_rating,
            p.e_pace, p.e_usg_pct
        FROM stg_player_tracking p
        UNION ALL
        SELECT
            'team' AS entity_type,
            t.team_id AS entity_id,
            t.team_id,
            t.season_year,
            t.gp, t.min,
            t.e_off_rating, t.e_def_rating, t.e_net_rating,
            t.e_pace, NULL AS e_usg_pct
        FROM stg_team_dashboard_estimated t
        ORDER BY season_year, entity_type, entity_id
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        conn.register("stg_player_tracking", staging["stg_player_tracking"].collect())
        conn.register(
            "stg_team_dashboard_estimated",
            staging["stg_team_dashboard_estimated"].collect(),
        )
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
