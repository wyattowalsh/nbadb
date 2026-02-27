from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class DimPlayerTransformer(BaseTransformer):
    output_table: ClassVar[str] = "dim_player"
    depends_on: ClassVar[list[str]] = ["stg_player_info"]

    _SCD2_SQL: ClassVar[str] = """
        WITH versioned AS (
            SELECT
                player_id,
                full_name,
                team_id,
                position,
                jersey_number,
                height,
                weight,
                birth_date,
                country,
                draft_year,
                draft_round,
                draft_number,
                college_id,
                season AS valid_from,
                LAG(team_id) OVER w AS prev_team,
                LAG(position) OVER w AS prev_pos,
                LAG(jersey_number) OVER w AS prev_jersey
            FROM stg_player_info
            WINDOW w AS (PARTITION BY player_id ORDER BY season)
        ),
        changes AS (
            SELECT *
            FROM versioned
            WHERE prev_team IS NULL
               OR team_id != prev_team
               OR position != prev_pos
               OR jersey_number != prev_jersey
        )
        SELECT
            ROW_NUMBER() OVER (ORDER BY player_id, valid_from) AS player_sk,
            player_id,
            full_name,
            position,
            team_id,
            jersey_number,
            height,
            weight,
            birth_date,
            country,
            draft_year,
            draft_round,
            draft_number,
            college_id,
            valid_from,
            LEAD(valid_from) OVER (
                PARTITION BY player_id ORDER BY valid_from
            ) AS valid_to,
            CASE WHEN LEAD(valid_from) OVER (
                PARTITION BY player_id ORDER BY valid_from
            ) IS NULL THEN TRUE ELSE FALSE END AS is_current
        FROM changes
        ORDER BY player_sk
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        conn.register("stg_player_info", staging["stg_player_info"].collect())
        result = conn.execute(self._SCD2_SQL).pl()
        conn.close()
        return result
