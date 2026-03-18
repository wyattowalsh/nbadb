from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class DimTeamHistoryTransformer(BaseTransformer):
    output_table: ClassVar[str] = "dim_team_history"
    depends_on: ClassVar[list[str]] = ["stg_team_info", "stg_franchise"]

    _SCD2_SQL: ClassVar[str] = """
        WITH source AS (
            SELECT
                ti.team_id,
                ti.city,
                ti.full_name AS nickname,
                ti.abbreviation,
                fr.team_name AS franchise_name,
                fr.league_id,
                ti.season_year,
                LAG(ti.city) OVER w AS prev_city,
                LAG(ti.full_name) OVER w AS prev_nickname,
                LAG(ti.abbreviation) OVER w AS prev_abbr
            FROM stg_team_info ti
            LEFT JOIN stg_franchise fr ON ti.team_id = fr.team_id
            WINDOW w AS (PARTITION BY ti.team_id ORDER BY ti.season_year)
        ),
        changes AS (
            SELECT *
            FROM source
            WHERE prev_city IS NULL
               OR city IS DISTINCT FROM prev_city
               OR nickname IS DISTINCT FROM prev_nickname
               OR abbreviation IS DISTINCT FROM prev_abbr
        )
        SELECT
            ROW_NUMBER() OVER (ORDER BY team_id, season_year)
                AS team_history_sk,
            team_id,
            city,
            nickname,
            abbreviation,
            franchise_name,
            league_id,
            season_year AS valid_from,
            LEAD(season_year) OVER (
                PARTITION BY team_id ORDER BY season_year
            ) AS valid_to,
            CASE WHEN LEAD(season_year) OVER (
                PARTITION BY team_id ORDER BY season_year
            ) IS NULL THEN TRUE ELSE FALSE END AS is_current
        FROM changes
        ORDER BY team_history_sk
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return self._conn.execute(self._SCD2_SQL).pl()
