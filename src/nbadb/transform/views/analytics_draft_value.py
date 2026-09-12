from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AnalyticsDraftValueTransformer(SqlTransformer):
    output_table: ClassVar[str] = "analytics_draft_value"
    depends_on: ClassVar[list[str]] = [
        "fact_draft",
        "agg_player_career",
        "dim_player",
    ]

    _SQL: ClassVar[str] = """
        WITH draft_enriched AS (
            SELECT
                d.*,
                p.full_name AS as_of_player_name,
                p.position AS as_of_position,
                p.country AS as_of_country
            FROM fact_draft d
            LEFT JOIN LATERAL (
                SELECT
                    CASE
                        WHEN COUNT(*) > 1
                            THEN error('conflicting dim_player SCD rows')
                        ELSE MIN(full_name)
                    END AS full_name,
                    CASE
                        WHEN COUNT(*) > 1
                            THEN error('conflicting dim_player SCD rows')
                        ELSE MIN(position)
                    END AS position,
                    CASE
                        WHEN COUNT(*) > 1
                            THEN error('conflicting dim_player SCD rows')
                        ELSE MIN(country)
                    END AS country
                FROM (
                    SELECT DISTINCT
                        full_name,
                        position,
                        country,
                        valid_from,
                        valid_to
                    FROM dim_player p0
                    WHERE p0.player_id = d.person_id
                      AND TRY_CAST(d.season AS INTEGER) >= TRY_CAST(
                          LEFT(CAST(p0.valid_from AS VARCHAR), 4) AS INTEGER
                      )
                      AND (
                          p0.valid_to IS NULL
                          OR TRY_CAST(d.season AS INTEGER) < TRY_CAST(
                              LEFT(CAST(p0.valid_to AS VARCHAR), 4) AS INTEGER
                          )
                      )
                ) matching_player_rows
            ) p ON TRUE
        )
        SELECT
            d.person_id,
            d.season,
            d.round_number,
            d.round_pick,
            d.overall_pick,
            d.team_id,
            COALESCE(d.as_of_player_name, d.player_name) AS player_name,
            d.as_of_position AS position,
            d.as_of_country AS country,
            c.career_gp,
            c.career_pts,
            c.career_ppg,
            c.career_rpg,
            c.career_apg,
            c.career_fg_pct,
            c.career_fg3_pct,
            c.seasons_played,
            c.first_season,
            c.last_season
        FROM draft_enriched d
        LEFT JOIN agg_player_career c ON d.person_id = c.player_id
    """
