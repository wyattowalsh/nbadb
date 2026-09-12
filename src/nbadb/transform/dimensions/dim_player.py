from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class DimPlayerTransformer(SqlTransformer):
    output_table: ClassVar[str] = "dim_player"
    depends_on: ClassVar[list[str]] = ["stg_player_info"]

    _SQL: ClassVar[str] = """
        WITH distinct_observations AS (
            SELECT DISTINCT
                player_id,
                full_name,
                first_name,
                last_name,
                roster_status,
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
                from_year,
                to_year
            FROM stg_player_info
            WHERE player_id IS NOT NULL
        ),
        authoritative AS (
            SELECT
                player_id,
                CASE WHEN COUNT(*) > 1
                    THEN error('conflicting current player identity observations')
                    ELSE MIN(full_name) END AS full_name,
                MIN(first_name) AS first_name,
                MIN(last_name) AS last_name,
                CASE
                    WHEN MIN(CAST(roster_status AS VARCHAR)) IN ('Active', '1')
                        THEN TRUE
                    ELSE FALSE
                END AS is_active,
                NULLIF(MIN(team_id), 0) AS team_id,
                MIN(position) AS position,
                MIN(jersey_number) AS jersey_number,
                MIN(height) AS height,
                MIN(weight) AS weight,
                MIN(birth_date) AS birth_date,
                MIN(country) AS country,
                MIN(draft_year) AS draft_year,
                MIN(draft_round) AS draft_round,
                MIN(draft_number) AS draft_number,
                MIN(college_id) AS college_id,
                TRY_CAST(MIN(from_year) AS INTEGER) AS from_year,
                TRY_CAST(MIN(to_year) AS INTEGER) AS to_year
            FROM distinct_observations
            GROUP BY player_id
        )
        SELECT
            ROW_NUMBER() OVER (ORDER BY player_id) AS player_sk,
            player_id,
            full_name,
            first_name,
            last_name,
            is_active,
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
            from_year,
            to_year,
            COALESCE(CAST(from_year AS VARCHAR), 'unknown') AS valid_from,
            CAST(NULL AS VARCHAR) AS valid_to,
            TRUE AS is_current
        FROM authoritative
    """
