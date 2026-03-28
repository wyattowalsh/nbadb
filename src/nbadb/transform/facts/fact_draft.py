from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactDraftTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_draft"
    depends_on: ClassVar[list[str]] = ["stg_draft", "stg_draft_combine"]

    _SQL: ClassVar[str] = """
        SELECT
            d.person_id,
            d.player_name,
            d.season,
            d.round_number,
            d.round_pick,
            d.overall_pick,
            d.draft_type,
            d.team_id,
            d.organization,
            d.organization_type,
            c.height_wo_shoes,
            c.height_w_shoes,
            c.weight,
            c.wingspan,
            c.standing_reach,
            c.body_fat_pct,
            c.hand_length,
            c.hand_width,
            c.standing_vertical_leap,
            c.max_vertical_leap,
            c.lane_agility_time,
            c.three_quarter_sprint,
            c.bench_press
        FROM stg_draft d
        LEFT JOIN stg_draft_combine c
            ON d.person_id = c.player_id AND d.season = c.season
    """
