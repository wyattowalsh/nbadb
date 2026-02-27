from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class AnalyticsTeamSeasonSummaryTransformer(BaseTransformer):
    output_table: ClassVar[str] = "analytics_team_season_summary"
    depends_on: ClassVar[list[str]] = [
        "agg_team_season",
        "fact_standings",
        "dim_team",
    ]

    _SQL: ClassVar[str] = """
        SELECT
            ts.team_id,
            ts.season_year,
            tm.team_name,
            tm.team_abbreviation,
            -- season aggregates
            ts.gp, ts.wins, ts.losses, ts.win_pct,
            ts.avg_pts, ts.avg_reb, ts.avg_ast,
            ts.avg_pts_allowed,
            ts.avg_fg_pct, ts.avg_fg3_pct, ts.avg_ft_pct,
            -- standings
            st.conference, st.conference_rank,
            st.division, st.division_rank,
            st.playoff_seed
        FROM agg_team_season ts
        LEFT JOIN fact_standings st
            ON ts.team_id = st.team_id AND ts.season_year = st.season_year
        LEFT JOIN dim_team tm ON ts.team_id = tm.team_id
        ORDER BY ts.season_year, ts.win_pct DESC
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        for dep in self.depends_on:
            conn.register(dep, staging[dep].collect())
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
