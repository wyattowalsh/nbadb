from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactLineupStatsTransformer(SqlTransformer):
    """Reconcile the league- and team-scoped copies of each lineup row.

    ``LeagueDashLineups`` is the precedence source because one league request
    covers every team.  ``TeamDashLineups`` is retained as corroborating
    coverage.  The two endpoints rank lineups against different populations,
    so their rank columns are intentionally not part of this canonical fact.
    Common payload values must agree exactly before precedence is applied.
    """

    output_table: ClassVar[str] = "fact_lineup_stats"
    depends_on: ClassVar[list[str]] = [
        "stg_lineup",
        "stg_team_lineups",
    ]

    _SQL: ClassVar[str] = """
        WITH source_payload AS (
            SELECT
                group_set, group_id, group_name, team_id,
                gp, w, l, w_pct, min,
                fgm, fga, fg_pct,
                fg3m, fg3a, fg3_pct,
                ftm, fta, ft_pct,
                oreb, dreb, reb, ast, tov, stl, blk, blka, pf, pfd,
                pts, plus_minus,
                season_year, season_type,
                'league' AS lineup_source,
                1 AS source_priority
            FROM stg_lineup
            UNION ALL
            SELECT
                group_set, group_id, group_name, team_id,
                gp, w, l, w_pct, min,
                fgm, fga, fg_pct,
                fg3m, fg3a, fg3_pct,
                ftm, fta, ft_pct,
                oreb, dreb, reb, ast, tov, stl, blk, blka, pf, pfd,
                pts, plus_minus,
                season_year, season_type,
                'team' AS lineup_source,
                2 AS source_priority
            FROM stg_team_lineups
        ),
        source_unique AS (
            SELECT DISTINCT *
            FROM source_payload
        )
        SELECT
            arg_min(group_set, source_priority) AS group_set,
            CASE
                WHEN COUNT(DISTINCT ROW(
                    group_set, group_name,
                    gp, w, l, w_pct, min,
                    fgm, fga, fg_pct,
                    fg3m, fg3a, fg3_pct,
                    ftm, fta, ft_pct,
                    oreb, dreb, reb, ast, tov, stl, blk, blka, pf, pfd,
                    pts, plus_minus
                )) = 1
                    THEN group_id
                ELSE error(
                    'fact_lineup_stats: conflicting lineup rows for one canonical key'
                )
            END AS group_id,
            arg_min(group_name, source_priority) AS group_name,
            team_id,
            arg_min(gp, source_priority) AS gp,
            arg_min(w, source_priority) AS w,
            arg_min(l, source_priority) AS l,
            arg_min(w_pct, source_priority) AS w_pct,
            arg_min(min, source_priority) AS min,
            arg_min(fgm, source_priority) AS fgm,
            arg_min(fga, source_priority) AS fga,
            arg_min(fg_pct, source_priority) AS fg_pct,
            arg_min(fg3m, source_priority) AS fg3m,
            arg_min(fg3a, source_priority) AS fg3a,
            arg_min(fg3_pct, source_priority) AS fg3_pct,
            arg_min(ftm, source_priority) AS ftm,
            arg_min(fta, source_priority) AS fta,
            arg_min(ft_pct, source_priority) AS ft_pct,
            arg_min(oreb, source_priority) AS oreb,
            arg_min(dreb, source_priority) AS dreb,
            arg_min(reb, source_priority) AS reb,
            arg_min(ast, source_priority) AS ast,
            arg_min(tov, source_priority) AS tov,
            arg_min(stl, source_priority) AS stl,
            arg_min(blk, source_priority) AS blk,
            arg_min(blka, source_priority) AS blka,
            arg_min(pf, source_priority) AS pf,
            arg_min(pfd, source_priority) AS pfd,
            arg_min(pts, source_priority) AS pts,
            arg_min(plus_minus, source_priority) AS plus_minus,
            NULL::DOUBLE AS net_rating,
            season_year,
            season_type,
            arg_min(lineup_source, source_priority) AS lineup_source,
            COUNT(DISTINCT lineup_source)::BIGINT AS lineup_source_count,
            string_agg(lineup_source, '+' ORDER BY source_priority)
                AS lineup_source_coverage
        FROM source_unique
        GROUP BY group_id, team_id, season_year, season_type
    """
