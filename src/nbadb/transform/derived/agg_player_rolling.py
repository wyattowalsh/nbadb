from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggPlayerRollingTransformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_player_rolling"
    depends_on: ClassVar[list[str]] = ["fact_player_game_traditional", "dim_game"]

    _SQL: ClassVar[str] = """
        WITH player_game_payload AS (
            SELECT
                game_id, player_id, team_id, season_year,
                pts, reb, ast
            FROM fact_player_game_traditional
        ),
        player_game_unique AS (
            SELECT DISTINCT *
            FROM player_game_payload
        ),
        player_game_authority AS (
            SELECT
                CASE
                    WHEN COUNT(*) OVER (PARTITION BY game_id, player_id) = 1
                        THEN game_id
                    ELSE error(
                        'agg_player_rolling: conflicting player-game rows for one key'
                    )
                END AS game_id,
                * EXCLUDE (game_id)
            FROM player_game_unique
        ),
        game_payload AS (
            SELECT game_id, season_year, season_type, game_date
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
                        'agg_player_rolling: conflicting game-dimension rows for one key'
                    )
                END AS game_id,
                * EXCLUDE (game_id)
            FROM game_unique
        ),
        ordered_games AS (
            SELECT
                t.game_id, t.player_id, t.team_id,
                CASE
                    WHEN t.season_year = g.season_year THEN g.season_year
                    ELSE error(
                        'agg_player_rolling: fact and game-dimension seasons disagree'
                    )
                END AS season_year,
                g.season_type, g.game_date,
                t.pts, t.reb, t.ast
            FROM player_game_authority t
            JOIN game_authority g ON t.game_id = g.game_id
        )
        SELECT
            game_id, player_id, season_year, game_date,
            AVG(pts) OVER w5 AS pts_roll5,
            AVG(reb) OVER w5 AS reb_roll5,
            AVG(ast) OVER w5 AS ast_roll5,
            AVG(pts) OVER w10 AS pts_roll10,
            AVG(reb) OVER w10 AS reb_roll10,
            AVG(ast) OVER w10 AS ast_roll10,
            AVG(pts) OVER w20 AS pts_roll20,
            AVG(reb) OVER w20 AS reb_roll20,
            AVG(ast) OVER w20 AS ast_roll20
        FROM ordered_games
        WINDOW
            w5 AS (
                PARTITION BY player_id, team_id, season_year, season_type
                ORDER BY game_date, game_id
                ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
            ),
            w10 AS (
                PARTITION BY player_id, team_id, season_year, season_type
                ORDER BY game_date, game_id
                ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
            ),
            w20 AS (
                PARTITION BY player_id, team_id, season_year, season_type
                ORDER BY game_date, game_id
                ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
            )
    """
