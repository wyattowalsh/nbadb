from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggClutchStatsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_clutch_stats"
    depends_on: ClassVar[list[str]] = [
        "stg_player_dashboard_clutch",
        "stg_league_player_clutch",
    ]

    _SQL: ClassVar[str] = """
        SELECT
            COALESCE(d.player_id, l.player_id) AS player_id,
            COALESCE(d.season_year, l.season_year) AS season_year,
            d.gp AS clutch_gp,
            d.min AS clutch_min,
            d.pts AS clutch_pts,
            d.fg_pct AS clutch_fg_pct,
            d.ft_pct AS clutch_ft_pct,
            l.pts AS league_clutch_pts,
            l.fg_pct AS league_clutch_fg_pct
        FROM stg_player_dashboard_clutch d
        FULL OUTER JOIN stg_league_player_clutch l
            ON d.player_id = l.player_id
            AND d.season_year = l.season_year
        ORDER BY season_year, player_id
    """
