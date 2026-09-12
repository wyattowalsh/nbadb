from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggGameTotalsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_game_totals"
    depends_on: ClassVar[list[str]] = [
        "fact_team_game",
        "bridge_game_team",
        "dim_game",
    ]

    _SQL: ClassVar[str] = """
        WITH fact_projected AS (
            SELECT
                game_id,
                team_id,
                pts,
                reb,
                ast,
                fgm,
                fga
            FROM fact_team_game
        ), fact_rows AS (
            SELECT DISTINCT
                game_id,
                team_id,
                pts,
                reb,
                ast,
                fgm,
                fga
            FROM fact_projected
        ), fact_by_team AS (
            SELECT
                game_id,
                team_id,
                count(*) AS fact_tuple_count,
                min(pts) AS pts,
                min(reb) AS reb,
                min(ast) AS ast,
                min(fgm) AS fgm,
                min(fga) AS fga,
                true AS fact_present
            FROM fact_rows
            GROUP BY game_id, team_id
        ), fact_by_game AS (
            SELECT
                game_id,
                count(*) AS fact_team_count,
                sum(
                    CASE
                        WHEN game_id IS NULL OR trim(game_id) = ''
                            OR team_id IS NULL OR team_id <= 0
                            THEN 1
                        ELSE 0
                    END
                ) AS invalid_fact_key_count,
                sum(CASE WHEN fact_tuple_count <> 1 THEN 1 ELSE 0 END)
                    AS conflicting_fact_team_count
            FROM fact_by_team
            GROUP BY game_id
        ), bridge_projected AS (
            SELECT
                game_id,
                team_id,
                side
            FROM bridge_game_team
        ), bridge_rows AS (
            SELECT DISTINCT
                game_id,
                team_id,
                side
            FROM bridge_projected
        ), bridge_by_game AS (
            SELECT
                game_id,
                count(*) AS bridge_row_count,
                sum(
                    CASE
                        WHEN game_id IS NULL OR trim(game_id) = ''
                            OR team_id IS NULL OR team_id <= 0
                            THEN 1
                        ELSE 0
                    END
                ) AS invalid_bridge_key_count,
                sum(
                    CASE
                        WHEN side IS NULL OR side NOT IN ('home', 'away') THEN 1
                        ELSE 0
                    END
                ) AS invalid_bridge_side_count,
                count(*) FILTER (WHERE side = 'home') AS home_side_count,
                count(*) FILTER (WHERE side = 'away') AS away_side_count,
                min(team_id) FILTER (WHERE side = 'home') AS home_team_id,
                min(team_id) FILTER (WHERE side = 'away') AS away_team_id
            FROM bridge_rows
            GROUP BY game_id
        ), dim_projected AS (
            SELECT
                game_id,
                game_date,
                season_year,
                season_type,
                home_team_id,
                visitor_team_id
            FROM dim_game
        ), dim_rows AS (
            SELECT DISTINCT
                game_id,
                game_date,
                season_year,
                season_type,
                home_team_id,
                visitor_team_id
            FROM dim_projected
        ), dim_by_game AS (
            SELECT
                game_id,
                count(*) AS dim_tuple_count,
                min(game_date) AS game_date,
                min(season_year) AS season_year,
                min(season_type) AS season_type,
                min(home_team_id) AS dim_home_team_id,
                min(visitor_team_id) AS dim_visitor_team_id
            FROM dim_rows
            GROUP BY game_id
        ), candidate_games AS (
            SELECT game_id FROM fact_by_game
            UNION
            SELECT game_id FROM bridge_by_game
        ), reconciled AS (
            SELECT
                candidates.game_id AS candidate_game_id,
                facts.game_id AS fact_game_id,
                facts.fact_team_count,
                facts.invalid_fact_key_count,
                facts.conflicting_fact_team_count,
                bridge.game_id AS bridge_game_id,
                bridge.bridge_row_count,
                bridge.invalid_bridge_key_count,
                bridge.invalid_bridge_side_count,
                bridge.home_side_count,
                bridge.away_side_count,
                bridge.home_team_id,
                bridge.away_team_id,
                games.game_id AS dim_game_id,
                games.dim_tuple_count,
                games.game_date,
                games.season_year,
                games.season_type,
                games.dim_home_team_id,
                games.dim_visitor_team_id,
                home_fact.fact_present AS home_fact_present,
                home_fact.pts AS home_pts,
                home_fact.reb AS home_reb,
                home_fact.ast AS home_ast,
                home_fact.fgm AS home_fgm,
                home_fact.fga AS home_fga,
                away_fact.fact_present AS away_fact_present,
                away_fact.pts AS away_pts,
                away_fact.reb AS away_reb,
                away_fact.ast AS away_ast,
                away_fact.fgm AS away_fgm,
                away_fact.fga AS away_fga
            FROM candidate_games AS candidates
            LEFT JOIN fact_by_game AS facts
                ON candidates.game_id IS NOT DISTINCT FROM facts.game_id
            LEFT JOIN bridge_by_game AS bridge
                ON candidates.game_id IS NOT DISTINCT FROM bridge.game_id
            LEFT JOIN dim_by_game AS games
                ON candidates.game_id IS NOT DISTINCT FROM games.game_id
            LEFT JOIN fact_by_team AS home_fact
                ON candidates.game_id IS NOT DISTINCT FROM home_fact.game_id
                AND bridge.home_team_id = home_fact.team_id
            LEFT JOIN fact_by_team AS away_fact
                ON candidates.game_id IS NOT DISTINCT FROM away_fact.game_id
                AND bridge.away_team_id = away_fact.team_id
        ), validated AS (
            SELECT
                CASE
                    WHEN candidate_game_id IS NULL OR trim(candidate_game_id) = ''
                        THEN error('agg_game_totals: candidate has invalid game_id')
                    WHEN fact_game_id IS NULL
                        THEN error('agg_game_totals: candidate is missing fact_team_game')
                    WHEN bridge_game_id IS NULL
                        THEN error('agg_game_totals: candidate is missing bridge_game_team')
                    WHEN invalid_fact_key_count <> 0
                        THEN error('agg_game_totals: fact source has invalid key')
                    WHEN conflicting_fact_team_count <> 0
                        THEN error(
                            'agg_game_totals: conflicting consumed fact tuple for game-team'
                        )
                    WHEN invalid_bridge_key_count <> 0
                        THEN error('agg_game_totals: bridge source has invalid key')
                    WHEN invalid_bridge_side_count <> 0
                        THEN error('agg_game_totals: bridge source has invalid side')
                    WHEN home_side_count > 1 OR away_side_count > 1
                        THEN error('agg_game_totals: bridge has multiple teams for one side')
                    WHEN home_side_count <> 1 OR away_side_count <> 1
                        THEN error('agg_game_totals: bridge does not have an exact side pair')
                    WHEN bridge_row_count <> 2
                        THEN error('agg_game_totals: bridge has noncanonical side rows')
                    WHEN home_team_id = away_team_id
                        THEN error('agg_game_totals: bridge assigns one team to both sides')
                    WHEN fact_team_count <> 2
                        THEN error('agg_game_totals: fact source does not have exactly two teams')
                    WHEN home_fact_present IS NULL OR away_fact_present IS NULL
                        THEN error('agg_game_totals: fact and bridge team sets differ')
                    WHEN dim_game_id IS NULL
                        THEN error('agg_game_totals: candidate is missing dim_game')
                    WHEN dim_tuple_count <> 1
                        THEN error('agg_game_totals: conflicting consumed dim_game tuple')
                    WHEN game_date IS NULL OR trim(game_date) = ''
                        THEN error('agg_game_totals: dim_game has invalid game_date')
                    WHEN season_year IS NULL OR trim(season_year) = ''
                        THEN error('agg_game_totals: dim_game has invalid season_year')
                    WHEN season_type IS NOT NULL AND trim(season_type) = ''
                        THEN error('agg_game_totals: dim_game has blank season_type')
                    WHEN (dim_home_team_id IS NULL) <> (dim_visitor_team_id IS NULL)
                        THEN error('agg_game_totals: dim_game has a partial optional team pair')
                    WHEN dim_home_team_id IS NOT NULL
                        AND dim_home_team_id = dim_visitor_team_id
                        THEN error('agg_game_totals: dim_game assigns one team to both sides')
                    WHEN dim_home_team_id IS NOT NULL
                        AND (
                            dim_home_team_id <> home_team_id
                            OR dim_visitor_team_id <> away_team_id
                        )
                        THEN error('agg_game_totals: dim_game and bridge team pairs differ')
                    ELSE candidate_game_id
                END AS game_id,
                game_date,
                season_year,
                season_type,
                home_team_id,
                away_team_id,
                home_pts,
                away_pts,
                CASE
                    WHEN home_pts IS NOT NULL AND away_pts IS NOT NULL
                        THEN home_pts + away_pts
                    ELSE NULL
                END AS total_pts,
                home_reb,
                away_reb,
                home_ast,
                away_ast,
                CASE
                    WHEN home_fgm IS NOT NULL AND home_fga IS NOT NULL AND home_fga > 0
                        THEN CAST(home_fgm AS DOUBLE) / CAST(home_fga AS DOUBLE)
                    ELSE NULL
                END AS home_fg_pct,
                CASE
                    WHEN away_fgm IS NOT NULL AND away_fga IS NOT NULL AND away_fga > 0
                        THEN CAST(away_fgm AS DOUBLE) / CAST(away_fga AS DOUBLE)
                    ELSE NULL
                END AS away_fg_pct
            FROM reconciled
        )
        SELECT
            game_id,
            game_date,
            season_year,
            season_type,
            home_team_id,
            away_team_id,
            home_pts,
            away_pts,
            total_pts,
            home_reb,
            away_reb,
            home_ast,
            away_ast,
            home_fg_pct,
            away_fg_pct
        FROM validated
        ORDER BY game_id
    """
