from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AnalyticsPlayerSeasonCompleteTransformer(SqlTransformer):
    output_table: ClassVar[str] = "analytics_player_season_complete"
    depends_on: ClassVar[list[str]] = [
        "agg_player_season",
        "agg_player_season_per36",
        "agg_player_season_per48",
        "dim_player",
        "dim_team",
    ]

    _SQL: ClassVar[str] = """
        SELECT
            s.player_id,
            s.season_year,
            s.team_id,
            p.full_name AS player_name,
            tm.abbreviation AS team_abbreviation,
            -- totals
            s.gp, s.total_min,
            s.total_pts, s.total_reb, s.total_ast,
            s.total_stl, s.total_blk, s.total_tov,
            s.avg_pts, s.avg_reb, s.avg_ast,
            s.fg_pct, s.fg3_pct, s.ft_pct,
            s.avg_off_rating, s.avg_def_rating, s.avg_net_rating,
            s.avg_pie,
            -- per-36
            p36.pts_per36, p36.reb_per36, p36.ast_per36,
            p36.stl_per36, p36.blk_per36, p36.tov_per36,
            -- per-100
            p100.pts_per48, p100.reb_per48, p100.ast_per48,
            p100.stl_per48, p100.blk_per48, p100.tov_per48
        FROM agg_player_season s
        LEFT JOIN agg_player_season_per36 p36
            ON s.player_id = p36.player_id AND s.season_year = p36.season_year
        LEFT JOIN agg_player_season_per48 p100
            ON s.player_id = p100.player_id AND s.season_year = p100.season_year
        LEFT JOIN dim_player p ON s.player_id = p.player_id AND p.is_current = TRUE
        LEFT JOIN dim_team tm ON s.team_id = tm.team_id
        ORDER BY s.season_year, s.avg_pts DESC
    """
