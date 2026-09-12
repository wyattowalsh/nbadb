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
        WITH dashboard_rows AS (
            SELECT
                CASE
                    WHEN player_id IS NULL
                        THEN error('agg_clutch_stats: dashboard player_id is null')
                    ELSE player_id
                END AS player_id,
                CASE
                    WHEN season_year IS NULL
                        THEN error('agg_clutch_stats: dashboard season_year is null')
                    ELSE season_year
                END AS season_year,
                gp,
                min,
                pts,
                fg_pct,
                ft_pct
            FROM stg_player_dashboard_clutch
            WHERE group_set = 'Overall'
              AND group_value = 'Overall'
        ), dashboard_overall AS (
            SELECT
                player_id,
                season_year,
                CASE
                    WHEN COUNT(DISTINCT ROW(gp, min, pts, fg_pct, ft_pct)) = 1
                        THEN MAX(gp)
                    ELSE error('agg_clutch_stats: conflicting dashboard projected rows')
                END AS gp,
                CASE
                    WHEN COUNT(DISTINCT ROW(gp, min, pts, fg_pct, ft_pct)) = 1
                        THEN MAX(min)
                    ELSE error('agg_clutch_stats: conflicting dashboard projected rows')
                END AS min,
                CASE
                    WHEN COUNT(DISTINCT ROW(gp, min, pts, fg_pct, ft_pct)) = 1
                        THEN MAX(pts)
                    ELSE error('agg_clutch_stats: conflicting dashboard projected rows')
                END AS pts,
                CASE
                    WHEN COUNT(DISTINCT ROW(gp, min, pts, fg_pct, ft_pct)) = 1
                        THEN MAX(fg_pct)
                    ELSE error('agg_clutch_stats: conflicting dashboard projected rows')
                END AS fg_pct,
                CASE
                    WHEN COUNT(DISTINCT ROW(gp, min, pts, fg_pct, ft_pct)) = 1
                        THEN MAX(ft_pct)
                    ELSE error('agg_clutch_stats: conflicting dashboard projected rows')
                END AS ft_pct
            FROM dashboard_rows
            GROUP BY player_id, season_year
        ), league_rows AS (
            SELECT
                CASE
                    WHEN player_id IS NULL
                        THEN error('agg_clutch_stats: league player_id is null')
                    ELSE player_id
                END AS player_id,
                CASE
                    WHEN season_year IS NULL
                        THEN error('agg_clutch_stats: league season_year is null')
                    ELSE season_year
                END AS season_year,
                pts,
                fg_pct
            FROM stg_league_player_clutch
            WHERE group_set = 'Overall'
        ), league_overall AS (
            SELECT
                player_id,
                season_year,
                CASE
                    WHEN COUNT(DISTINCT ROW(pts, fg_pct)) = 1 THEN MAX(pts)
                    ELSE error('agg_clutch_stats: conflicting league projected rows')
                END AS pts,
                CASE
                    WHEN COUNT(DISTINCT ROW(pts, fg_pct)) = 1 THEN MAX(fg_pct)
                    ELSE error('agg_clutch_stats: conflicting league projected rows')
                END AS fg_pct
            FROM league_rows
            GROUP BY player_id, season_year
        )
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
        FROM dashboard_overall d
        FULL OUTER JOIN league_overall l
            ON d.player_id = l.player_id
            AND d.season_year = l.season_year
        ORDER BY player_id, season_year
    """
