from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AnalyticsTeamSeasonSummaryTransformer(SqlTransformer):
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
            ts.season_type,
            tm.full_name AS team_name,
            tm.abbreviation AS team_abbreviation,
            -- season aggregates
            ts.gp,
            ts.avg_pts, ts.avg_reb, ts.avg_ast,
            ts.fg_pct, ts.fg3_pct, ts.ft_pct,
            -- standings
            st.wins, st.losses, st.win_pct,
            st.conference, st.conference_rank,
            st.division, st.division_rank
        FROM agg_team_season ts
        LEFT JOIN fact_standings st
            ON ts.team_id = st.team_id
            AND ts.season_year = st.season_year
        LEFT JOIN dim_team tm ON ts.team_id = tm.team_id
        ORDER BY ts.season_year, ts.season_type,
                 st.win_pct DESC NULLS LAST
    """
