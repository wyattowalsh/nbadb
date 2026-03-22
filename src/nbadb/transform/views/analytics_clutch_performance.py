from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AnalyticsClutchPerformanceTransformer(SqlTransformer):
    output_table: ClassVar[str] = "analytics_clutch_performance"
    depends_on: ClassVar[list[str]] = [
        "fact_player_clutch_detail",
        "dim_player",
        "dim_team",
    ]

    _SQL: ClassVar[str] = """
        SELECT
            c.player_id,
            c.team_id,
            c.season_year,
            c.clutch_window,
            p.full_name AS player_name,
            tm.abbreviation AS team_abbreviation,
            c.gp, c.w, c.l, c.min,
            c.fgm, c.fga, c.fg_pct,
            c.fg3m, c.fg3a, c.fg3_pct,
            c.ftm, c.fta, c.ft_pct,
            c.oreb, c.dreb, c.reb,
            c.ast, c.tov, c.stl, c.blk,
            c.pf, c.pts, c.plus_minus,
            c.net_rating, c.off_rating, c.def_rating
        FROM fact_player_clutch_detail c
        LEFT JOIN dim_player p ON c.player_id = p.player_id AND p.is_current = TRUE
        LEFT JOIN dim_team tm ON c.team_id = tm.team_id
        ORDER BY c.season_year, c.clutch_window, c.pts DESC NULLS LAST
    """
