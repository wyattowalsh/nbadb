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
        WITH clutch_enriched AS (
            SELECT
                c.*,
                p.player_name
            FROM fact_player_clutch_detail c
            LEFT JOIN LATERAL (
                SELECT
                    CASE
                        WHEN COUNT(*) > 1
                            THEN error('conflicting dim_player SCD rows')
                        ELSE MIN(full_name)
                    END AS player_name
                FROM (
                    SELECT DISTINCT
                        full_name,
                        valid_from,
                        valid_to
                    FROM dim_player p0
                    WHERE p0.player_id = c.player_id
                      AND c.season_year >= p0.valid_from
                      AND (
                          p0.valid_to IS NULL
                          OR c.season_year < p0.valid_to
                      )
                ) matching_player_rows
            ) p ON TRUE
        )
        SELECT
            c.player_id,
            c.team_id,
            c.season_year,
            c.season_type,
            c.clutch_window,
            c.group_set,
            c.group_value,
            c.player_name,
            tm.abbreviation AS team_abbreviation,
            c.gp, c.w, c.l, c.min,
            c.fgm, c.fga, c.fg_pct,
            c.fg3m, c.fg3a, c.fg3_pct,
            c.ftm, c.fta, c.ft_pct,
            c.oreb, c.dreb, c.reb,
            c.ast, c.tov, c.stl, c.blk,
            c.pf, c.pts, c.plus_minus,
            c.net_rating, c.off_rating, c.def_rating
        FROM clutch_enriched c
        LEFT JOIN dim_team tm ON c.team_id = tm.team_id
    """
