from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggPlayerSeasonAdvancedTransformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_player_season_advanced"
    depends_on: ClassVar[list[str]] = ["fact_player_game_advanced", "dim_game"]

    _METRICS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("off_rating", "avg_off_rating"),
        ("def_rating", "avg_def_rating"),
        ("net_rating", "avg_net_rating"),
        ("ts_pct", "avg_ts_pct"),
        ("usg_pct", "avg_usg_pct"),
        ("efg_pct", "avg_efg_pct"),
        ("ast_pct", "avg_ast_pct"),
        ("ast_ratio", "avg_ast_ratio"),
        ("oreb_pct", "avg_oreb_pct"),
        ("dreb_pct", "avg_dreb_pct"),
        ("reb_pct", "avg_reb_pct"),
        ("tov_pct", "avg_tov_pct"),
        ("pie", "avg_pie"),
    )

    _WEIGHTED_METRICS_SQL: ClassVar[str] = ",\n".join(
        f"""
                COUNT(*) FILTER (
                    WHERE poss > 0.0 AND {source} IS NOT NULL
                ) AS {source}_covered_games,
                SUM(poss) FILTER (
                    WHERE poss > 0.0 AND {source} IS NOT NULL
                ) AS {source}_covered_possessions,
                SUM({source} * poss) FILTER (
                    WHERE poss > 0.0 AND {source} IS NOT NULL
                ) / NULLIF(
                    SUM(poss) FILTER (
                        WHERE poss > 0.0 AND {source} IS NOT NULL
                    ),
                    0.0
                ) AS {output}"""
        for source, output in _METRICS
    )

    _SQL: ClassVar[str] = f"""
        WITH advanced_unique AS (
            SELECT DISTINCT *
            FROM fact_player_game_advanced
            WHERE player_id IS NOT NULL AND team_id IS NOT NULL
        ),
        advanced_authority AS (
            SELECT
                CASE
                    WHEN COUNT(*) OVER (
                        PARTITION BY game_id, player_id, team_id
                    ) = 1
                        THEN game_id
                    ELSE error(
                        'agg_player_season_advanced: conflicting player-game rows'
                    )
                END AS game_id,
                * EXCLUDE (game_id)
            FROM advanced_unique
        ),
        game_unique AS (
            SELECT DISTINCT game_id, season_year, season_type
            FROM dim_game
        ),
        game_authority AS (
            SELECT
                CASE
                    WHEN COUNT(*) OVER (PARTITION BY game_id) = 1
                        THEN game_id
                    ELSE error(
                        'agg_player_season_advanced: conflicting game-dimension rows'
                    )
                END AS game_id,
                season_year,
                season_type
            FROM game_unique
        ),
        canonical_games AS (
            SELECT
                a.*,
                CASE
                    WHEN g.game_id IS NULL
                        THEN error(
                            'agg_player_season_advanced: missing game-dimension authority'
                        )
                    ELSE g.season_year
                END AS canonical_season_year,
                g.season_type AS canonical_season_type
            FROM advanced_authority a
            LEFT JOIN game_authority g ON a.game_id = g.game_id
        )
        SELECT
            player_id,
            team_id,
            canonical_season_year AS season_year,
            canonical_season_type AS season_type,
            COUNT(*) AS gp,
            COUNT(min) FILTER (WHERE min >= 0.0) AS minutes_covered_games,
            SUM(min) FILTER (WHERE min >= 0.0) AS total_min,
            COUNT(poss) FILTER (WHERE poss >= 0.0) AS possession_covered_games,
            SUM(poss) FILTER (WHERE poss >= 0.0) AS total_possessions,
            COUNT(*) FILTER (
                WHERE pace IS NOT NULL AND min > 0.0
            ) AS pace_covered_games,
            SUM(min) FILTER (
                WHERE pace IS NOT NULL AND min > 0.0
            ) AS pace_covered_minutes,
            SUM(pace * min) FILTER (
                WHERE pace IS NOT NULL AND min > 0.0
            ) / NULLIF(
                SUM(min) FILTER (
                    WHERE pace IS NOT NULL AND min > 0.0
                ),
                0.0
            ) AS avg_pace,
{_WEIGHTED_METRICS_SQL},
            'provider_possession_weighted' AS advanced_metric_source,
            'provider_minute_weighted' AS pace_source
        FROM canonical_games
        GROUP BY
            player_id,
            team_id,
            canonical_season_year,
            canonical_season_type
    """
