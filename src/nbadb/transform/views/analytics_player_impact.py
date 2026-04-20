from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AnalyticsPlayerImpactTransformer(SqlTransformer):
    output_table: ClassVar[str] = "analytics_player_impact"
    depends_on: ClassVar[list[str]] = [
        "agg_on_off_splits",
        "agg_player_season",
        "dim_player",
        "dim_team",
    ]

    _SQL: ClassVar[str] = """
        WITH on_court AS (
            SELECT entity_id AS player_id, team_id, season_year, season_type,
                   off_rating AS on_off_rating, def_rating AS on_def_rating,
                   net_rating AS on_net_rating, pts AS on_pts, reb AS on_reb, ast AS on_ast
            FROM agg_on_off_splits
            WHERE entity_type = 'player' AND on_off = 'On'
        ),
        off_court AS (
            SELECT entity_id AS player_id, team_id, season_year, season_type,
                   off_rating AS off_off_rating, def_rating AS off_def_rating,
                   net_rating AS off_net_rating
            FROM agg_on_off_splits
            WHERE entity_type = 'player' AND on_off = 'Off'
        )
        SELECT
            s.player_id,
            s.team_id,
            s.season_year,
            s.season_type,
            p.full_name AS player_name,
            tm.abbreviation AS team_abbreviation,
            s.gp, s.avg_min, s.avg_pts, s.avg_reb, s.avg_ast,
            s.fg_pct, s.fg3_pct, s.ft_pct,
            s.avg_off_rating, s.avg_def_rating, s.avg_net_rating,
            s.avg_ts_pct, s.avg_usg_pct, s.avg_pie,
            -- on/off impact
            o.on_off_rating, o.on_def_rating, o.on_net_rating,
            o.on_pts, o.on_reb, o.on_ast,
            f.off_off_rating, f.off_def_rating, f.off_net_rating,
            o.on_net_rating - f.off_net_rating AS net_rating_diff
        FROM agg_player_season s
        LEFT JOIN on_court o
            ON s.player_id = o.player_id AND s.team_id = o.team_id
            AND s.season_year = o.season_year
            AND s.season_type = o.season_type
        LEFT JOIN off_court f
            ON s.player_id = f.player_id AND s.team_id = f.team_id
            AND s.season_year = f.season_year
            AND s.season_type = f.season_type
        LEFT JOIN dim_player p
            ON s.player_id = p.player_id AND p.is_current = TRUE
        LEFT JOIN dim_team tm ON s.team_id = tm.team_id
    """
