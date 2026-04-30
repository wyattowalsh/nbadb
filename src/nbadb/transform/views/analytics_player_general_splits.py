from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AnalyticsPlayerGeneralSplitsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "analytics_player_general_splits"
    depends_on: ClassVar[list[str]] = [
        "fact_player_general_splits_detail",
        "dim_player",
    ]

    _SQL: ClassVar[str] = """
        WITH overall AS (
            SELECT
                player_id,
                season_year,
                season_type,
                gp AS overall_gp,
                w_pct AS overall_w_pct,
                min AS overall_min,
                pts AS overall_pts,
                reb AS overall_reb,
                ast AS overall_ast,
                fg_pct AS overall_fg_pct,
                fg3_pct AS overall_fg3_pct,
                ft_pct AS overall_ft_pct,
                plus_minus AS overall_plus_minus
            FROM fact_player_general_splits_detail
            WHERE split_type = 'general_overall'
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY player_id, season_year, season_type
                ORDER BY gp DESC NULLS LAST, min DESC NULLS LAST
            ) = 1
        )
        SELECT
            s.player_id,
            s.season_year,
            s.season_type,
            s.split_type,
            s.group_set,
            s.group_value,
            p.full_name AS player_name,
            s.gp,
            s.w,
            s.l,
            s.w_pct,
            s.min,
            s.pts,
            s.reb,
            s.ast,
            s.fg_pct,
            s.fg3_pct,
            s.ft_pct,
            s.plus_minus,
            o.overall_gp,
            o.overall_w_pct,
            o.overall_min,
            o.overall_pts,
            o.overall_reb,
            o.overall_ast,
            o.overall_fg_pct,
            o.overall_fg3_pct,
            o.overall_ft_pct,
            o.overall_plus_minus,
            CASE
                WHEN o.overall_gp IS NULL OR o.overall_gp = 0 THEN NULL
                ELSE CAST(s.gp AS DOUBLE) / o.overall_gp
            END AS gp_share,
            s.w_pct - o.overall_w_pct AS w_pct_delta,
            s.min - o.overall_min AS min_delta,
            s.pts - o.overall_pts AS pts_delta,
            s.reb - o.overall_reb AS reb_delta,
            s.ast - o.overall_ast AS ast_delta,
            s.fg_pct - o.overall_fg_pct AS fg_pct_delta,
            s.fg3_pct - o.overall_fg3_pct AS fg3_pct_delta,
            s.ft_pct - o.overall_ft_pct AS ft_pct_delta,
            s.plus_minus - o.overall_plus_minus AS plus_minus_delta
        FROM fact_player_general_splits_detail s
        LEFT JOIN overall o
            ON s.player_id = o.player_id
            AND s.season_year = o.season_year
            AND s.season_type = o.season_type
        LEFT JOIN dim_player p
            ON s.player_id = p.player_id
            AND p.is_current = TRUE
    """
