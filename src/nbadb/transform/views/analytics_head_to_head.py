from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class AnalyticsHeadToHeadTransformer(BaseTransformer):
    output_table: ClassVar[str] = "analytics_head_to_head"
    depends_on: ClassVar[list[str]] = [
        "fact_team_game",
        "dim_team",
    ]

    _SQL: ClassVar[str] = """
        SELECT
            h.team_id,
            h.opponent_team_id,
            h.season_year,
            t1.team_abbreviation AS team_abbr,
            t2.team_abbreviation AS opponent_abbr,
            COUNT(*) AS games_played,
            SUM(CASE WHEN h.wl = 'W' THEN 1 ELSE 0 END) AS wins,
            SUM(CASE WHEN h.wl = 'L' THEN 1 ELSE 0 END) AS losses,
            AVG(h.pts) AS avg_pts_scored,
            AVG(h.pts_against) AS avg_pts_allowed,
            AVG(h.pts - h.pts_against) AS avg_margin
        FROM fact_team_game h
        LEFT JOIN dim_team t1 ON h.team_id = t1.team_id
        LEFT JOIN dim_team t2 ON h.opponent_team_id = t2.team_id
        GROUP BY h.team_id, h.opponent_team_id, h.season_year,
                 t1.team_abbreviation, t2.team_abbreviation
        ORDER BY h.season_year, t1.team_abbreviation, wins DESC
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        for dep in self.depends_on:
            conn.register(dep, staging[dep].collect())
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
