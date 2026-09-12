from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggTeamDefenseTransformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_team_defense"
    depends_on: ClassVar[list[str]] = [
        "fact_box_score_advanced_team",
        "fact_team_game_hustle",
        "fact_box_score_four_factors_team",
        "dim_game",
    ]

    _SQL: ClassVar[str] = """
        WITH advanced_projected AS (
            SELECT
                game_id,
                team_id,
                def_rating,
                net_rating
            FROM fact_box_score_advanced_team
        ), advanced_validated AS (
            SELECT
                CASE
                    WHEN game_id IS NULL OR trim(game_id) = ''
                        THEN error('advanced defense source has invalid game_id')
                    ELSE game_id
                END AS game_id,
                CASE
                    WHEN team_id IS NULL OR team_id <= 0
                        THEN error('advanced defense source has invalid team_id')
                    ELSE team_id
                END AS team_id,
                def_rating,
                net_rating
            FROM advanced_projected
        ), advanced_rows AS (
            SELECT DISTINCT
                game_id,
                team_id,
                def_rating,
                net_rating
            FROM advanced_validated
        ), advanced AS (
            SELECT
                CASE WHEN count(*) > 1
                    THEN error('conflicting advanced defense tuple for game-team')
                    ELSE game_id END AS game_id,
                team_id,
                min(def_rating) AS def_rating,
                min(net_rating) AS net_rating
            FROM advanced_rows
            GROUP BY game_id, team_id
        ), four_factors_projected AS (
            SELECT
                game_id,
                team_id,
                opp_effective_field_goal_percentage,
                opp_free_throw_attempt_rate,
                opp_team_turnover_percentage,
                opp_offensive_rebound_percentage
            FROM fact_box_score_four_factors_team
        ), four_factors_validated AS (
            SELECT
                CASE
                    WHEN game_id IS NULL OR trim(game_id) = ''
                        THEN error('four-factors defense source has invalid game_id')
                    ELSE game_id
                END AS game_id,
                CASE
                    WHEN team_id IS NULL OR team_id <= 0
                        THEN error('four-factors defense source has invalid team_id')
                    ELSE team_id
                END AS team_id,
                opp_effective_field_goal_percentage,
                opp_free_throw_attempt_rate,
                opp_team_turnover_percentage,
                opp_offensive_rebound_percentage
            FROM four_factors_projected
        ), four_factors_rows AS (
            SELECT DISTINCT
                game_id,
                team_id,
                opp_effective_field_goal_percentage,
                opp_free_throw_attempt_rate,
                opp_team_turnover_percentage,
                opp_offensive_rebound_percentage
            FROM four_factors_validated
        ), four_factors AS (
            SELECT
                CASE WHEN count(*) > 1
                    THEN error('conflicting four-factors defense tuple for game-team')
                    ELSE game_id END AS game_id,
                team_id,
                min(opp_effective_field_goal_percentage)
                    AS opp_effective_field_goal_percentage,
                min(opp_free_throw_attempt_rate) AS opp_free_throw_attempt_rate,
                min(opp_team_turnover_percentage) AS opp_team_turnover_percentage,
                min(opp_offensive_rebound_percentage)
                    AS opp_offensive_rebound_percentage,
                true AS four_factors_present
            FROM four_factors_rows
            GROUP BY game_id, team_id
        ), hustle_projected AS (
            SELECT
                game_id,
                team_id,
                contested_shots,
                deflections,
                loose_balls_recovered,
                charges_drawn,
                screen_assists
            FROM fact_team_game_hustle
        ), hustle_validated AS (
            SELECT
                CASE
                    WHEN game_id IS NULL OR trim(game_id) = ''
                        THEN error('hustle defense source has invalid game_id')
                    ELSE game_id
                END AS game_id,
                CASE
                    WHEN team_id IS NULL OR team_id <= 0
                        THEN error('hustle defense source has invalid team_id')
                    ELSE team_id
                END AS team_id,
                contested_shots,
                deflections,
                loose_balls_recovered,
                charges_drawn,
                screen_assists
            FROM hustle_projected
        ), hustle_rows AS (
            SELECT DISTINCT
                game_id,
                team_id,
                contested_shots,
                deflections,
                loose_balls_recovered,
                charges_drawn,
                screen_assists
            FROM hustle_validated
        ), hustle AS (
            SELECT
                CASE WHEN count(*) > 1
                    THEN error('conflicting hustle defense tuple for game-team')
                    ELSE game_id END AS game_id,
                team_id,
                min(contested_shots) AS contested_shots,
                min(deflections) AS deflections,
                min(loose_balls_recovered) AS loose_balls_recovered,
                min(charges_drawn) AS charges_drawn,
                min(screen_assists) AS screen_assists,
                true AS hustle_present
            FROM hustle_rows
            GROUP BY game_id, team_id
        ), game_projected AS (
            SELECT
                game_id,
                season_year,
                season_type
            FROM dim_game
        ), game_validated AS (
            SELECT
                CASE
                    WHEN game_id IS NULL OR trim(game_id) = ''
                        THEN error('defense game dimension has invalid game_id')
                    ELSE game_id
                END AS game_id,
                CASE
                    WHEN season_year IS NULL OR trim(season_year) = ''
                        THEN error('defense game dimension has invalid season_year')
                    ELSE season_year
                END AS season_year,
                CASE
                    WHEN season_type IS NULL OR trim(season_type) = ''
                        THEN error('defense game dimension has invalid season_type')
                    ELSE season_type
                END AS season_type
            FROM game_projected
        ), game_rows AS (
            SELECT DISTINCT
                game_id,
                season_year,
                season_type
            FROM game_validated
        ), games AS (
            SELECT
                CASE WHEN count(*) > 1
                    THEN error('conflicting defense game dimension tuple for game')
                    ELSE game_id END AS game_id,
                min(season_year) AS season_year,
                min(season_type) AS season_type
            FROM game_rows
            GROUP BY game_id
        ), source_join AS (
            SELECT
                CASE
                    WHEN advanced.game_id IS NULL
                        AND four_factors.four_factors_present
                        THEN error('orphan four-factors defense game-team key')
                    WHEN advanced.game_id IS NULL
                        AND hustle.hustle_present
                        THEN error('orphan hustle defense game-team key')
                    ELSE advanced.game_id
                END AS game_id,
                advanced.team_id,
                advanced.def_rating,
                advanced.net_rating,
                four_factors.four_factors_present,
                four_factors.opp_effective_field_goal_percentage,
                four_factors.opp_free_throw_attempt_rate,
                four_factors.opp_team_turnover_percentage,
                four_factors.opp_offensive_rebound_percentage,
                hustle.hustle_present,
                hustle.contested_shots,
                hustle.deflections,
                hustle.loose_balls_recovered,
                hustle.charges_drawn,
                hustle.screen_assists
            FROM advanced
            FULL OUTER JOIN four_factors
                ON advanced.game_id = four_factors.game_id
                AND advanced.team_id = four_factors.team_id
            FULL OUTER JOIN hustle
                ON coalesce(advanced.game_id, four_factors.game_id) = hustle.game_id
                AND coalesce(advanced.team_id, four_factors.team_id) = hustle.team_id
        ), joined AS (
            SELECT
                CASE
                    WHEN games.game_id IS NULL
                        THEN error('advanced defense game-team key is missing dim_game')
                    ELSE source_join.game_id
                END AS game_id,
                source_join.team_id,
                games.season_year,
                games.season_type,
                source_join.def_rating,
                source_join.net_rating,
                source_join.four_factors_present,
                source_join.opp_effective_field_goal_percentage,
                source_join.opp_free_throw_attempt_rate,
                source_join.opp_team_turnover_percentage,
                source_join.opp_offensive_rebound_percentage,
                source_join.hustle_present,
                source_join.contested_shots,
                source_join.deflections,
                source_join.loose_balls_recovered,
                source_join.charges_drawn,
                source_join.screen_assists,
                count(*) OVER (
                    PARTITION BY source_join.game_id, source_join.team_id
                ) AS join_multiplicity
            FROM source_join
            LEFT JOIN games ON source_join.game_id = games.game_id
        ), aggregated AS (
            SELECT
                team_id,
                season_year,
                season_type,
                CASE
                    WHEN max(join_multiplicity) > 1
                        OR count(*) <> count(DISTINCT game_id)
                        THEN error('team defense source join multiplied game-team rows')
                    ELSE count(*)
                END AS observed_game_count,
                count(def_rating) AS def_rating_coverage_game_count,
                avg(CAST(def_rating AS DOUBLE)) AS mean_observed_game_def_rating,
                count(net_rating) AS net_rating_coverage_game_count,
                avg(CAST(net_rating AS DOUBLE)) AS mean_observed_game_net_rating,
                count(four_factors_present) AS four_factors_observed_game_count,
                count(opp_effective_field_goal_percentage)
                    AS opp_effective_field_goal_percentage_coverage_game_count,
                avg(CAST(opp_effective_field_goal_percentage AS DOUBLE))
                    AS mean_observed_game_opp_effective_field_goal_percentage,
                count(opp_free_throw_attempt_rate)
                    AS opp_free_throw_attempt_rate_coverage_game_count,
                avg(CAST(opp_free_throw_attempt_rate AS DOUBLE))
                    AS mean_observed_game_opp_free_throw_attempt_rate,
                count(opp_team_turnover_percentage)
                    AS opp_team_turnover_percentage_coverage_game_count,
                avg(CAST(opp_team_turnover_percentage AS DOUBLE))
                    AS mean_observed_game_opp_team_turnover_percentage,
                count(opp_offensive_rebound_percentage)
                    AS opp_offensive_rebound_percentage_coverage_game_count,
                avg(CAST(opp_offensive_rebound_percentage AS DOUBLE))
                    AS mean_observed_game_opp_offensive_rebound_percentage,
                count(hustle_present) AS hustle_observed_game_count,
                count(contested_shots) AS contested_shots_coverage_game_count,
                sum(CAST(contested_shots AS DOUBLE)) AS total_observed_game_contested_shots,
                avg(CAST(contested_shots AS DOUBLE)) AS mean_observed_game_contested_shots,
                count(deflections) AS deflections_coverage_game_count,
                sum(CAST(deflections AS DOUBLE)) AS total_observed_game_deflections,
                avg(CAST(deflections AS DOUBLE)) AS mean_observed_game_deflections,
                count(loose_balls_recovered) AS loose_balls_recovered_coverage_game_count,
                sum(CAST(loose_balls_recovered AS DOUBLE))
                    AS total_observed_game_loose_balls_recovered,
                avg(CAST(loose_balls_recovered AS DOUBLE))
                    AS mean_observed_game_loose_balls_recovered,
                count(charges_drawn) AS charges_drawn_coverage_game_count,
                sum(CAST(charges_drawn AS DOUBLE)) AS total_observed_game_charges_drawn,
                avg(CAST(charges_drawn AS DOUBLE)) AS mean_observed_game_charges_drawn,
                count(screen_assists) AS screen_assists_coverage_game_count,
                sum(CAST(screen_assists AS DOUBLE)) AS total_observed_game_screen_assists,
                avg(CAST(screen_assists AS DOUBLE)) AS mean_observed_game_screen_assists
            FROM joined
            GROUP BY team_id, season_year, season_type
        ), coverage_checked AS (
            SELECT
                CASE
                    WHEN def_rating_coverage_game_count > observed_game_count
                        OR net_rating_coverage_game_count > observed_game_count
                        OR four_factors_observed_game_count > observed_game_count
                        OR opp_effective_field_goal_percentage_coverage_game_count
                            > four_factors_observed_game_count
                        OR opp_free_throw_attempt_rate_coverage_game_count
                            > four_factors_observed_game_count
                        OR opp_team_turnover_percentage_coverage_game_count
                            > four_factors_observed_game_count
                        OR opp_offensive_rebound_percentage_coverage_game_count
                            > four_factors_observed_game_count
                        OR hustle_observed_game_count > observed_game_count
                        OR contested_shots_coverage_game_count > hustle_observed_game_count
                        OR deflections_coverage_game_count > hustle_observed_game_count
                        OR loose_balls_recovered_coverage_game_count
                            > hustle_observed_game_count
                        OR charges_drawn_coverage_game_count > hustle_observed_game_count
                        OR screen_assists_coverage_game_count > hustle_observed_game_count
                        THEN error('team defense coverage count exceeds its denominator')
                    ELSE team_id
                END AS team_id,
                season_year,
                season_type,
                observed_game_count,
                def_rating_coverage_game_count,
                mean_observed_game_def_rating,
                net_rating_coverage_game_count,
                mean_observed_game_net_rating,
                four_factors_observed_game_count,
                opp_effective_field_goal_percentage_coverage_game_count,
                mean_observed_game_opp_effective_field_goal_percentage,
                opp_free_throw_attempt_rate_coverage_game_count,
                mean_observed_game_opp_free_throw_attempt_rate,
                opp_team_turnover_percentage_coverage_game_count,
                mean_observed_game_opp_team_turnover_percentage,
                opp_offensive_rebound_percentage_coverage_game_count,
                mean_observed_game_opp_offensive_rebound_percentage,
                hustle_observed_game_count,
                contested_shots_coverage_game_count,
                total_observed_game_contested_shots,
                mean_observed_game_contested_shots,
                deflections_coverage_game_count,
                total_observed_game_deflections,
                mean_observed_game_deflections,
                loose_balls_recovered_coverage_game_count,
                total_observed_game_loose_balls_recovered,
                mean_observed_game_loose_balls_recovered,
                charges_drawn_coverage_game_count,
                total_observed_game_charges_drawn,
                mean_observed_game_charges_drawn,
                screen_assists_coverage_game_count,
                total_observed_game_screen_assists,
                mean_observed_game_screen_assists
            FROM aggregated
        )
        SELECT
            team_id,
            season_year,
            season_type,
            observed_game_count,
            def_rating_coverage_game_count,
            mean_observed_game_def_rating,
            net_rating_coverage_game_count,
            mean_observed_game_net_rating,
            four_factors_observed_game_count,
            opp_effective_field_goal_percentage_coverage_game_count,
            mean_observed_game_opp_effective_field_goal_percentage,
            opp_free_throw_attempt_rate_coverage_game_count,
            mean_observed_game_opp_free_throw_attempt_rate,
            opp_team_turnover_percentage_coverage_game_count,
            mean_observed_game_opp_team_turnover_percentage,
            opp_offensive_rebound_percentage_coverage_game_count,
            mean_observed_game_opp_offensive_rebound_percentage,
            hustle_observed_game_count,
            contested_shots_coverage_game_count,
            total_observed_game_contested_shots,
            mean_observed_game_contested_shots,
            deflections_coverage_game_count,
            total_observed_game_deflections,
            mean_observed_game_deflections,
            loose_balls_recovered_coverage_game_count,
            total_observed_game_loose_balls_recovered,
            mean_observed_game_loose_balls_recovered,
            charges_drawn_coverage_game_count,
            total_observed_game_charges_drawn,
            mean_observed_game_charges_drawn,
            screen_assists_coverage_game_count,
            total_observed_game_screen_assists,
            mean_observed_game_screen_assists
        FROM coverage_checked
        ORDER BY team_id, season_year, season_type
    """
