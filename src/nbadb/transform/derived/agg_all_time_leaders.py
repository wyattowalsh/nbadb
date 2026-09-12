from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggAllTimeLeadersTransformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_all_time_leaders"
    depends_on: ClassVar[list[str]] = [
        "stg_all_time_pts",
        "stg_all_time_ast",
        "stg_all_time_reb",
    ]

    _SQL: ClassVar[str] = """
        WITH pts_rows AS (
            SELECT DISTINCT
                player_id,
                player_name,
                pts,
                pts_rank
            FROM stg_all_time_pts
        ), ast_rows AS (
            SELECT DISTINCT
                player_id,
                player_name,
                ast,
                ast_rank
            FROM stg_all_time_ast
        ), reb_rows AS (
            SELECT DISTINCT
                player_id,
                player_name,
                reb,
                reb_rank
            FROM stg_all_time_reb
        ), pts_source AS (
            SELECT
                CASE WHEN player_id IS NULL
                    THEN error('all-time points source has null player_id')
                    ELSE player_id END AS player_id,
                CASE WHEN COUNT(DISTINCT pts) > 1
                    THEN error('conflicting all-time points values')
                    ELSE MIN(pts) END AS pts,
                CASE WHEN COUNT(DISTINCT pts_rank) > 1
                    THEN error('conflicting all-time points ranks')
                    ELSE MIN(pts_rank) END AS pts_rank
            FROM pts_rows
            GROUP BY player_id
        ), ast_source AS (
            SELECT
                CASE WHEN player_id IS NULL
                    THEN error('all-time assists source has null player_id')
                    ELSE player_id END AS player_id,
                CASE WHEN COUNT(DISTINCT ast) > 1
                    THEN error('conflicting all-time assists values')
                    ELSE MIN(ast) END AS ast,
                CASE WHEN COUNT(DISTINCT ast_rank) > 1
                    THEN error('conflicting all-time assists ranks')
                    ELSE MIN(ast_rank) END AS ast_rank
            FROM ast_rows
            GROUP BY player_id
        ), reb_source AS (
            SELECT
                CASE WHEN player_id IS NULL
                    THEN error('all-time rebounds source has null player_id')
                    ELSE player_id END AS player_id,
                CASE WHEN COUNT(DISTINCT reb) > 1
                    THEN error('conflicting all-time rebounds values')
                    ELSE MIN(reb) END AS reb,
                CASE WHEN COUNT(DISTINCT reb_rank) > 1
                    THEN error('conflicting all-time rebounds ranks')
                    ELSE MIN(reb_rank) END AS reb_rank
            FROM reb_rows
            GROUP BY player_id
        ), name_rows AS (
            SELECT player_id, player_name FROM pts_rows
            UNION ALL
            SELECT player_id, player_name FROM ast_rows
            UNION ALL
            SELECT player_id, player_name FROM reb_rows
        ), name_authority AS (
            SELECT
                player_id,
                CASE WHEN COUNT(DISTINCT player_name) > 1
                    THEN error('conflicting all-time player names')
                    ELSE MIN(player_name) END AS player_name
            FROM name_rows
            GROUP BY player_id
        ), metric_authority AS (
            SELECT
                COALESCE(pts_source.player_id, ast_source.player_id, reb_source.player_id)
                    AS player_id,
                pts_source.pts,
                ast_source.ast,
                reb_source.reb,
                pts_source.pts_rank,
                ast_source.ast_rank,
                reb_source.reb_rank
            FROM pts_source
            FULL OUTER JOIN ast_source
                ON pts_source.player_id = ast_source.player_id
            FULL OUTER JOIN reb_source
                ON COALESCE(pts_source.player_id, ast_source.player_id) = reb_source.player_id
        )
        SELECT
            metric_authority.player_id,
            name_authority.player_name,
            metric_authority.pts,
            metric_authority.ast,
            metric_authority.reb,
            metric_authority.pts_rank,
            metric_authority.ast_rank,
            metric_authority.reb_rank
        FROM metric_authority
        LEFT JOIN name_authority
            ON metric_authority.player_id = name_authority.player_id
        ORDER BY metric_authority.player_id
    """
