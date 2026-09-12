from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerGameAdvancedTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_game_advanced"
    depends_on: ClassVar[list[str]] = ["stg_box_score_advanced", "dim_game"]

    _SQL: ClassVar[str] = """
        WITH player_game_payload AS (
            SELECT *
            FROM stg_box_score_advanced
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
                        'fact_player_game_advanced: conflicting player-game rows for one key'
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
                        'fact_player_game_advanced: conflicting game-dimension rows for one key'
                    )
                END AS game_id,
                * EXCLUDE (game_id)
            FROM game_unique
        )
        SELECT
            b.game_id,
            b.player_id,
            b.team_id,
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
            g.season_year,
            b.off_rating,
            b.def_rating,
            b.net_rating,
            b.ast_pct,
            b.ast_tov,
            b.ast_ratio,
            b.oreb_pct,
            b.dreb_pct,
            b.reb_pct,
            b.tov_pct,
            b.efg_pct,
            b.ts_pct,
            b.usg_pct,
            b.pace,
            b.pace_per40,
            b.poss,
            b.pie,
            b.e_off_rating,
            b.e_def_rating,
            b.e_net_rating,
            b.e_usg_pct,
            b.e_pace
        FROM player_game_authority b
        LEFT JOIN game_authority g ON b.game_id = g.game_id
    """
