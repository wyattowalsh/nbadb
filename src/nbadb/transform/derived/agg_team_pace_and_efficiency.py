from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggTeamPaceAndEfficiencyTransformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_team_pace_and_efficiency"
    depends_on: ClassVar[list[str]] = [
        "fact_box_score_advanced_team",
        "dim_game",
    ]

    _SQL: ClassVar[str] = """
        WITH team_game_payload AS (
            SELECT *
            FROM fact_box_score_advanced_team
        ),
        team_game_unique AS (
            SELECT DISTINCT *
            FROM team_game_payload
        ),
        team_game_authority AS (
            SELECT
                CASE
                    WHEN COUNT(*) OVER (PARTITION BY game_id, team_id) = 1
                        THEN game_id
                    ELSE error(
                        'agg_team_pace_and_efficiency: conflicting team-game rows for one key'
                    )
                END AS game_id,
                * EXCLUDE (game_id)
            FROM team_game_unique
        ),
        game_payload AS (
            SELECT *
            FROM dim_game
        ),
        game_unique AS (
            SELECT DISTINCT *
            FROM game_payload
        ),
        game_authority AS (
            SELECT
                CASE
                    WHEN COUNT(*) OVER (PARTITION BY game_id) = 1
                        THEN game_id
                    ELSE error(
                        'agg_team_pace_and_efficiency: conflicting game-dimension rows for one key'
                    )
                END AS game_id,
                * EXCLUDE (game_id)
            FROM game_unique
        ),
        parsed_games AS (
            SELECT
                a.game_id,
                a.team_id,
                g.season_year,
                g.season_type,
                a.pace,
                a.poss,
                a.off_rating,
                a.def_rating,
                CASE
                    -- BoxScoreAdvancedV3 TeamStats.MIN is total player-minutes:
                    -- 240:00 in regulation, plus 25:00 for each overtime.
                    WHEN regexp_full_match(
                        trim(a.min),
                        '^[0-9]+:[0-9]{2}([.][0-9]+)?$'
                    )
                        THEN (
                            TRY_CAST(split_part(trim(a.min), ':', 1) AS DOUBLE)
                            + TRY_CAST(split_part(trim(a.min), ':', 2) AS DOUBLE) / 60.0
                        ) / 5.0
                    WHEN regexp_full_match(trim(a.min), '^[0-9]+([.][0-9]+)?$')
                        THEN TRY_CAST(trim(a.min) AS DOUBLE) / 5.0
                    ELSE NULL
                END AS actual_team_minutes
            FROM team_game_authority a
            JOIN game_authority g ON a.game_id = g.game_id
        ),
        covered_games AS (
            SELECT
                *,
                CASE
                    WHEN poss > 0.0 AND actual_team_minutes > 0.0
                        THEN actual_team_minutes
                    WHEN poss > 0.0 AND pace > 0.0
                        THEN poss * 48.0 / pace
                    ELSE NULL
                END AS pace_team_minutes,
                poss > 0.0
                    AND off_rating IS NOT NULL
                    AND def_rating IS NOT NULL AS has_rating_coverage
            FROM parsed_games
        ),
        metrics AS (
            SELECT
                team_id,
                season_year,
                season_type,
                COUNT(*) AS gp,
                SUM(poss) FILTER (WHERE poss >= 0.0) AS total_possessions,
                COUNT(*) FILTER (WHERE has_rating_coverage) AS rating_covered_games,
                SUM(poss) FILTER (WHERE has_rating_coverage) AS rating_possessions,
                COUNT(*) FILTER (WHERE pace_team_minutes IS NOT NULL) AS pace_covered_games,
                COUNT(*) FILTER (
                    WHERE poss > 0.0 AND actual_team_minutes > 0.0
                ) AS pace_actual_minutes_games,
                COUNT(*) FILTER (
                    WHERE poss > 0.0
                        AND (actual_team_minutes IS NULL OR actual_team_minutes <= 0.0)
                        AND pace > 0.0
                ) AS pace_inferred_minutes_games,
                SUM(pace_team_minutes) FILTER (
                    WHERE pace_team_minutes IS NOT NULL
                ) AS pace_covered_minutes,
                48.0 * SUM(poss) FILTER (
                    WHERE pace_team_minutes IS NOT NULL
                ) / NULLIF(
                    SUM(pace_team_minutes) FILTER (
                        WHERE pace_team_minutes IS NOT NULL
                    ),
                    0.0
                ) AS avg_pace,
                SUM(off_rating * poss) FILTER (
                    WHERE has_rating_coverage
                ) / NULLIF(
                    SUM(poss) FILTER (WHERE has_rating_coverage),
                    0.0
                ) AS avg_ortg,
                SUM(def_rating * poss) FILTER (
                    WHERE has_rating_coverage
                ) / NULLIF(
                    SUM(poss) FILTER (WHERE has_rating_coverage),
                    0.0
                ) AS avg_drtg
            FROM covered_games
            GROUP BY team_id, season_year, season_type
        )
        SELECT
            team_id,
            season_year,
            season_type,
            gp,
            total_possessions,
            rating_covered_games,
            rating_possessions,
            pace_covered_games,
            pace_actual_minutes_games,
            pace_inferred_minutes_games,
            pace_covered_minutes,
            avg_pace,
            avg_ortg,
            avg_drtg,
            avg_ortg - avg_drtg AS avg_net_rtg
        FROM metrics
    """
