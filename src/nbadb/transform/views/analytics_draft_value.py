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
        SELECT
            d.person_id,
            d.season,
            d.round_number,
            d.round_pick,
            d.overall_pick,
            d.team_id,
            -- is_current=TRUE: player name from current record; team_id from fact table
            COALESCE(p.full_name, d.player_name) AS player_name,
            p.position,
            p.country,
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
        FROM fact_draft d
        LEFT JOIN agg_player_career c ON d.person_id = c.player_id
        LEFT JOIN dim_player p ON d.person_id = p.player_id AND p.is_current = TRUE
    """
