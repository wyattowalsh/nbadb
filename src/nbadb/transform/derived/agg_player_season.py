from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggPlayerSeasonTransformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_player_season"
    depends_on: ClassVar[list[str]] = [
        "fact_player_game_traditional",
        "fact_player_game_advanced",
        "dim_game",
        "dim_team",
    ]

    _SQL: ClassVar[str] = """
        WITH traditional_unique AS (
            SELECT DISTINCT *
            FROM fact_player_game_traditional
            WHERE player_id IS NOT NULL AND team_id IS NOT NULL
        ),
        traditional_authority AS (
            SELECT
                CASE
                    WHEN COUNT(*) OVER (
                        PARTITION BY game_id, player_id, team_id
                    ) = 1
                        THEN game_id
                    ELSE error(
                        'agg_player_season: conflicting traditional player-game rows'
                    )
                END AS game_id,
                * EXCLUDE (game_id)
            FROM traditional_unique
        ),
        advanced_unique AS (
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
                        'agg_player_season: conflicting advanced player-game rows'
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
                        'agg_player_season: conflicting game-dimension rows'
                    )
                END AS game_id,
                season_year,
                season_type
            FROM game_unique
        ),
        team_unique AS (
            SELECT DISTINCT team_id, abbreviation
            FROM dim_team
        ),
        team_authority AS (
            SELECT
                CASE
                    WHEN COUNT(*) OVER (PARTITION BY team_id) = 1
                        THEN team_id
                    ELSE error(
                        'agg_player_season: conflicting team-dimension rows'
                    )
                END AS team_id,
                abbreviation
            FROM team_unique
        ),
        canonical_games AS (
            SELECT
                t.*,
                CASE
                    WHEN g.game_id IS NULL
                        THEN error(
                            'agg_player_season: missing game-dimension authority'
                        )
                    ELSE g.season_year
                END AS canonical_season_year,
                g.season_type AS canonical_season_type,
                tm.abbreviation AS team_abbreviation,
                a.game_id AS advanced_game_id,
                a.poss AS advanced_poss,
                a.off_rating,
                a.def_rating,
                a.net_rating,
                a.ts_pct AS provider_ts_pct,
                a.usg_pct,
                a.pie
            FROM traditional_authority t
            LEFT JOIN game_authority g ON t.game_id = g.game_id
            LEFT JOIN team_authority tm ON t.team_id = tm.team_id
            LEFT JOIN advanced_authority a
                ON t.game_id = a.game_id
                AND t.player_id = a.player_id
                AND t.team_id = a.team_id
        ),
        metrics AS (
            SELECT
                player_id,
                team_id,
                team_abbreviation,
                canonical_season_year AS season_year,
                canonical_season_type AS season_type,
                COUNT(*) AS gp,
                COUNT(min) AS minutes_covered_games,
                COUNT(pts) AS scoring_covered_games,
                COUNT(reb) AS rebounding_covered_games,
                COUNT(ast) AS playmaking_covered_games,
                COUNT(*) FILTER (
                    WHERE fgm IS NOT NULL
                        AND fga IS NOT NULL
                        AND fg3m IS NOT NULL
                        AND fg3a IS NOT NULL
                        AND ftm IS NOT NULL
                        AND fta IS NOT NULL
                        AND pts IS NOT NULL
                ) AS shooting_covered_games,
                COUNT(advanced_game_id) AS advanced_covered_games,
                SUM(advanced_poss) FILTER (
                    WHERE advanced_poss > 0.0
                ) AS advanced_possessions,
                SUM(min) AS total_min,
                SUM(min) / NULLIF(COUNT(min), 0) AS avg_min,
                SUM(pts) AS total_pts,
                SUM(pts) / NULLIF(COUNT(pts), 0) AS avg_pts,
                SUM(reb) AS total_reb,
                SUM(reb) / NULLIF(COUNT(reb), 0) AS avg_reb,
                SUM(ast) AS total_ast,
                SUM(ast) / NULLIF(COUNT(ast), 0) AS avg_ast,
                SUM(stl) AS total_stl,
                SUM(stl) / NULLIF(COUNT(stl), 0) AS avg_stl,
                SUM(blk) AS total_blk,
                SUM(blk) / NULLIF(COUNT(blk), 0) AS avg_blk,
                SUM(tov) AS total_tov,
                SUM(tov) / NULLIF(COUNT(tov), 0) AS avg_tov,
                SUM(fgm) AS total_fgm,
                SUM(fga) AS total_fga,
                SUM(fg3m) AS total_fg3m,
                SUM(fg3a) AS total_fg3a,
                SUM(ftm) AS total_ftm,
                SUM(fta) AS total_fta,
                SUM(oreb) AS total_oreb,
                SUM(dreb) AS total_dreb,
                SUM(pf) AS total_pf,
                SUM(plus_minus) AS total_plus_minus,
                COUNT(*) FILTER (
                    WHERE advanced_poss > 0.0
                        AND off_rating IS NOT NULL
                        AND def_rating IS NOT NULL
                        AND net_rating IS NOT NULL
                ) AS rating_covered_games,
                SUM(advanced_poss) FILTER (
                    WHERE advanced_poss > 0.0
                        AND off_rating IS NOT NULL
                        AND def_rating IS NOT NULL
                        AND net_rating IS NOT NULL
                ) AS rating_possessions,
                SUM(off_rating * advanced_poss) FILTER (
                    WHERE advanced_poss > 0.0
                        AND off_rating IS NOT NULL
                        AND def_rating IS NOT NULL
                        AND net_rating IS NOT NULL
                ) / NULLIF(
                    SUM(advanced_poss) FILTER (
                        WHERE advanced_poss > 0.0
                            AND off_rating IS NOT NULL
                            AND def_rating IS NOT NULL
                            AND net_rating IS NOT NULL
                    ),
                    0.0
                ) AS avg_off_rating,
                SUM(def_rating * advanced_poss) FILTER (
                    WHERE advanced_poss > 0.0
                        AND off_rating IS NOT NULL
                        AND def_rating IS NOT NULL
                        AND net_rating IS NOT NULL
                ) / NULLIF(
                    SUM(advanced_poss) FILTER (
                        WHERE advanced_poss > 0.0
                            AND off_rating IS NOT NULL
                            AND def_rating IS NOT NULL
                            AND net_rating IS NOT NULL
                    ),
                    0.0
                ) AS avg_def_rating,
                SUM(net_rating * advanced_poss) FILTER (
                    WHERE advanced_poss > 0.0
                        AND off_rating IS NOT NULL
                        AND def_rating IS NOT NULL
                        AND net_rating IS NOT NULL
                ) / NULLIF(
                    SUM(advanced_poss) FILTER (
                        WHERE advanced_poss > 0.0
                            AND off_rating IS NOT NULL
                            AND def_rating IS NOT NULL
                            AND net_rating IS NOT NULL
                    ),
                    0.0
                ) AS avg_net_rating,
                COUNT(*) FILTER (
                    WHERE advanced_poss > 0.0 AND provider_ts_pct IS NOT NULL
                ) AS provider_ts_covered_games,
                SUM(advanced_poss) FILTER (
                    WHERE advanced_poss > 0.0 AND provider_ts_pct IS NOT NULL
                ) AS provider_ts_possessions,
                SUM(provider_ts_pct * advanced_poss) FILTER (
                    WHERE advanced_poss > 0.0 AND provider_ts_pct IS NOT NULL
                ) / NULLIF(
                    SUM(advanced_poss) FILTER (
                        WHERE advanced_poss > 0.0 AND provider_ts_pct IS NOT NULL
                    ),
                    0.0
                ) AS provider_avg_ts_pct,
                COUNT(*) FILTER (
                    WHERE advanced_poss > 0.0 AND usg_pct IS NOT NULL
                ) AS usage_covered_games,
                SUM(advanced_poss) FILTER (
                    WHERE advanced_poss > 0.0 AND usg_pct IS NOT NULL
                ) AS usage_possessions,
                SUM(usg_pct * advanced_poss) FILTER (
                    WHERE advanced_poss > 0.0 AND usg_pct IS NOT NULL
                ) / NULLIF(
                    SUM(advanced_poss) FILTER (
                        WHERE advanced_poss > 0.0 AND usg_pct IS NOT NULL
                    ),
                    0.0
                ) AS avg_usg_pct,
                COUNT(*) FILTER (
                    WHERE advanced_poss > 0.0 AND pie IS NOT NULL
                ) AS pie_covered_games,
                SUM(advanced_poss) FILTER (
                    WHERE advanced_poss > 0.0 AND pie IS NOT NULL
                ) AS pie_possessions,
                SUM(pie * advanced_poss) FILTER (
                    WHERE advanced_poss > 0.0 AND pie IS NOT NULL
                ) / NULLIF(
                    SUM(advanced_poss) FILTER (
                        WHERE advanced_poss > 0.0 AND pie IS NOT NULL
                    ),
                    0.0
                ) AS avg_pie
            FROM canonical_games
            GROUP BY
                player_id,
                team_id,
                team_abbreviation,
                canonical_season_year,
                canonical_season_type
        )
        SELECT
            *,
            total_fgm / NULLIF(total_fga, 0.0) AS fg_pct,
            total_fg3m / NULLIF(total_fg3a, 0.0) AS fg3_pct,
            total_ftm / NULLIF(total_fta, 0.0) AS ft_pct,
            (total_fgm + 0.5 * total_fg3m)
                / NULLIF(total_fga, 0.0) AS efg_pct,
            total_pts / NULLIF(
                2.0 * (total_fga + 0.44 * total_fta),
                0.0
            ) AS avg_ts_pct,
            total_fg3a / NULLIF(total_fga, 0.0) AS three_point_attempt_rate,
            total_fta / NULLIF(total_fga, 0.0) AS free_throw_attempt_rate,
            total_ast / NULLIF(total_tov, 0.0) AS ast_tov_ratio,
            'derived_traditional_totals' AS shooting_efficiency_source,
            'provider_possessions' AS advanced_metric_weight
        FROM metrics
    """
