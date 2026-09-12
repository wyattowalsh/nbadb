from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggShotZonesTransformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_shot_zones"
    depends_on: ClassVar[list[str]] = ["fact_shot_chart", "dim_game"]

    _SQL: ClassVar[str] = """
        WITH fact_projected AS (
            SELECT
                game_id,
                game_event_id,
                player_id,
                season_year,
                season_type,
                shot_zone_basic,
                shot_zone_area,
                shot_zone_range,
                shot_made_flag,
                shot_distance
            FROM fact_shot_chart
        ), fact_exact_rows AS (
            SELECT
                game_id,
                game_event_id,
                player_id,
                season_year,
                season_type,
                shot_zone_basic,
                shot_zone_area,
                shot_zone_range,
                shot_made_flag,
                shot_distance
            FROM fact_projected
            GROUP BY
                game_id,
                game_event_id,
                player_id,
                season_year,
                season_type,
                shot_zone_basic,
                shot_zone_area,
                shot_zone_range,
                shot_made_flag,
                shot_distance
        ), event_authority AS (
            SELECT
                game_id,
                game_event_id,
                count(*) AS event_tuple_count,
                min(player_id) AS player_id,
                min(season_year) AS fact_season_year,
                min(season_type) AS fact_season_type,
                min(shot_zone_basic) AS shot_zone_basic,
                min(shot_zone_area) AS shot_zone_area,
                min(shot_zone_range) AS shot_zone_range,
                min(shot_made_flag) AS shot_made_flag,
                min(CAST(shot_distance AS DOUBLE)) AS shot_distance
            FROM fact_exact_rows
            GROUP BY game_id, game_event_id
        ), dim_projected AS (
            SELECT
                game_id,
                season_year,
                season_type
            FROM dim_game
        ), dim_exact_rows AS (
            SELECT
                game_id,
                season_year,
                season_type
            FROM dim_projected
            GROUP BY
                game_id,
                season_year,
                season_type
        ), game_authority AS (
            SELECT
                game_id,
                count(*) AS dim_tuple_count,
                min(season_year) AS dim_season_year,
                min(season_type) AS dim_season_type
            FROM dim_exact_rows
            GROUP BY game_id
        ), admitted_events AS (
            SELECT
                CASE
                    WHEN events.game_event_id IS NULL
                        THEN error('event_identity_authority_missing')
                    WHEN events.event_tuple_count <> 1
                        THEN error(
                            'agg_shot_zones: conflicting consumed fact tuple for event identity'
                        )
                    WHEN events.game_id IS NULL OR trim(events.game_id) = ''
                        THEN error('agg_shot_zones: fact has invalid game_id')
                    WHEN events.player_id IS NULL OR events.player_id <= 0
                        THEN error('agg_shot_zones: fact has invalid player_id')
                    WHEN events.fact_season_year IS NULL
                        OR trim(events.fact_season_year) = ''
                        THEN error('agg_shot_zones: fact has invalid season_year')
                    WHEN events.fact_season_type IS NULL
                        OR trim(events.fact_season_type) = ''
                        THEN error('agg_shot_zones: fact has invalid season_type')
                    WHEN events.shot_zone_basic IS NULL
                        OR trim(events.shot_zone_basic) = ''
                        THEN error('agg_shot_zones: fact has invalid shot_zone_basic')
                    WHEN events.shot_zone_area IS NULL
                        OR trim(events.shot_zone_area) = ''
                        THEN error('agg_shot_zones: fact has invalid shot_zone_area')
                    WHEN events.shot_zone_range IS NULL
                        OR trim(events.shot_zone_range) = ''
                        THEN error('agg_shot_zones: fact has invalid shot_zone_range')
                    WHEN events.shot_made_flag IS NOT NULL
                        AND events.shot_made_flag NOT IN (0, 1)
                        THEN error('agg_shot_zones: fact has invalid shot_made_flag')
                    WHEN events.shot_distance IS NOT NULL
                        AND (
                            NOT isfinite(events.shot_distance)
                            OR events.shot_distance < 0
                        )
                        THEN error('agg_shot_zones: fact has invalid shot_distance')
                    WHEN games.game_id IS NULL
                        THEN error('agg_shot_zones: fact event is missing dim_game')
                    WHEN games.dim_tuple_count <> 1
                        THEN error('agg_shot_zones: conflicting consumed dim_game tuple')
                    WHEN games.dim_season_year IS NULL OR trim(games.dim_season_year) = ''
                        THEN error('agg_shot_zones: dim_game has invalid season_year')
                    WHEN games.dim_season_type IS NULL OR trim(games.dim_season_type) = ''
                        THEN error('agg_shot_zones: dim_game has invalid season_type')
                    WHEN events.fact_season_year <> games.dim_season_year
                        OR events.fact_season_type <> games.dim_season_type
                        THEN error('agg_shot_zones: fact and dim_game season scope differs')
                    ELSE 1
                END AS admitted_event_count,
                events.player_id,
                games.dim_season_year AS season_year,
                games.dim_season_type AS season_type,
                events.shot_zone_basic,
                events.shot_zone_area,
                events.shot_zone_range,
                events.shot_made_flag,
                events.shot_distance
            FROM event_authority AS events
            LEFT JOIN game_authority AS games ON events.game_id = games.game_id
        ), aggregated AS (
            SELECT
                player_id,
                season_year,
                season_type,
                shot_zone_basic,
                shot_zone_area,
                shot_zone_range,
                sum(admitted_event_count) AS shot_event_count,
                count(shot_made_flag) AS outcome_observed_attempt_count,
                count(*) FILTER (WHERE shot_made_flag = 1)
                    AS made_shot_count_of_observed_outcomes,
                CASE
                    WHEN count(shot_made_flag) > 0
                        THEN CAST(
                            count(*) FILTER (WHERE shot_made_flag = 1)
                            AS DOUBLE
                        ) / CAST(count(shot_made_flag) AS DOUBLE)
                    ELSE NULL
                END AS fg_pct_of_observed_outcomes,
                count(shot_distance) AS distance_observed_attempt_count,
                CASE
                    WHEN count(shot_distance) > 0
                        THEN avg(shot_distance)
                    ELSE NULL
                END AS mean_observed_shot_distance
            FROM admitted_events
            GROUP BY
                player_id,
                season_year,
                season_type,
                shot_zone_basic,
                shot_zone_area,
                shot_zone_range
        )
        SELECT
            player_id,
            season_year,
            season_type,
            shot_zone_basic,
            shot_zone_area,
            shot_zone_range,
            shot_event_count,
            outcome_observed_attempt_count,
            made_shot_count_of_observed_outcomes,
            fg_pct_of_observed_outcomes,
            distance_observed_attempt_count,
            mean_observed_shot_distance
        FROM aggregated
        ORDER BY
            player_id,
            season_year,
            season_type,
            shot_zone_basic,
            shot_zone_area,
            shot_zone_range
    """
