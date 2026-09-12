from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class BridgeGameOfficialTransformer(SqlTransformer):
    output_table: ClassVar[str] = "bridge_game_official"
    depends_on: ClassVar[list[str]] = ["stg_officials"]

    _SQL: ClassVar[str] = """
        WITH official_rows AS (
            SELECT
                game_id,
                official_id,
                jersey_number
            FROM stg_officials
            WHERE game_id IS NOT NULL
              AND official_id IS NOT NULL
              AND official_id > 0
        ), official_authority AS (
            SELECT
                game_id,
                official_id,
                CASE
                    WHEN COUNT(DISTINCT jersey_number) > 1
                        THEN error('conflicting game-official jersey numbers')
                    ELSE MIN(jersey_number)
                END AS jersey_num
            FROM official_rows
            GROUP BY game_id, official_id
        )
        SELECT
            game_id,
            official_id,
            jersey_num
        FROM official_authority
        ORDER BY game_id, official_id
    """
