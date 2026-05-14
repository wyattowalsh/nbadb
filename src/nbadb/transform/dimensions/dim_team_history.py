from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class DimTeamHistoryTransformer(SqlTransformer):
    output_table: ClassVar[str] = "dim_team_history"
    depends_on: ClassVar[list[str]] = ["stg_team_info_common", "stg_franchise"]

    _SQL: ClassVar[str] = """
        WITH source AS (
            SELECT
                ti.team_id,
                ti.team_city AS city,
                ti.team_name AS nickname,
                ti.team_abbreviation AS abbreviation,
                fr.team_name AS franchise_name,
                fr.league_id,
                ti.season_year,
                LAG(ti.team_city) OVER w AS prev_city,
                LAG(ti.team_name) OVER w AS prev_nickname,
                LAG(ti.team_abbreviation) OVER w AS prev_abbr
            FROM stg_team_info_common ti
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
    """
