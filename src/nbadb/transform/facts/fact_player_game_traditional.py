from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerGameTraditionalTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_game_traditional"
    depends_on: ClassVar[list[str]] = ["stg_box_score_traditional", "dim_game"]

    _SQL: ClassVar[str] = """
        WITH player_game_payload AS (
            SELECT *
            FROM stg_box_score_traditional
            WHERE player_id IS NOT NULL AND team_id IS NOT NULL
        ),
        player_game_unique AS (
            SELECT DISTINCT *
            FROM player_game_payload
        ),
        player_game_authority AS (
            SELECT
                CASE
                    WHEN COUNT(*) OVER (
                        PARTITION BY game_id, player_id, team_id
                    ) = 1
                        THEN game_id
                    ELSE error(
                        'fact_player_game_traditional: conflicting player-game rows for one key'
                    )
                END AS game_id,
                * EXCLUDE (game_id)
            FROM player_game_unique
        ),
        game_unique AS (
            SELECT DISTINCT *
            FROM dim_game
        ),
        game_authority AS (
            SELECT
                CASE
                    WHEN COUNT(*) OVER (PARTITION BY game_id) = 1
                        THEN game_id
                    ELSE error(
                        'fact_player_game_traditional: conflicting game-dimension rows for one key'
                    )
                END AS game_id,
                * EXCLUDE (game_id)
            FROM game_unique
        )
        SELECT
            b.game_id, b.player_id, b.team_id,
            g.season_year,
            b.start_position, b.comment,
            CASE
                WHEN regexp_full_match(
                    trim(CAST(b.min AS VARCHAR)),
                    '^[0-9]+:[0-9]{2}([.][0-9]+)?$'
                )
                    THEN TRY_CAST(
                        split_part(trim(CAST(b.min AS VARCHAR)), ':', 1)
                        AS DOUBLE
                    ) + TRY_CAST(
                        split_part(trim(CAST(b.min AS VARCHAR)), ':', 2)
                        AS DOUBLE
                    ) / 60.0
                WHEN regexp_full_match(
                    trim(CAST(b.min AS VARCHAR)),
                    '^PT[0-9]+M[0-9]+([.][0-9]+)?S$'
                )
                    THEN TRY_CAST(
                        regexp_extract(
                            trim(CAST(b.min AS VARCHAR)),
                            '^PT([0-9]+)M',
                            1
                        ) AS DOUBLE
                    ) + TRY_CAST(
                        regexp_extract(
                            trim(CAST(b.min AS VARCHAR)),
                            'M([0-9]+([.][0-9]+)?)S$',
                            1
                        ) AS DOUBLE
                    ) / 60.0
                WHEN regexp_full_match(
                    trim(CAST(b.min AS VARCHAR)),
                    '^[0-9]+([.][0-9]+)?$'
                )
                    THEN TRY_CAST(trim(CAST(b.min AS VARCHAR)) AS DOUBLE)
                ELSE NULL
            END AS min,
            b.fgm, b.fga, b.fg_pct,
            b.fg3m, b.fg3a, b.fg3_pct,
            b.ftm, b.fta, b.ft_pct,
            b.oreb, b.dreb, b.reb,
            b.ast, b.stl, b.blk, b.tov, b.pf,
            b.pts, b.plus_minus
        FROM player_game_authority b
        LEFT JOIN game_authority g ON b.game_id = g.game_id
    """
