from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class DimCoachTransformer(SqlTransformer):
    output_table: ClassVar[str] = "dim_coach"
    depends_on: ClassVar[list[str]] = ["stg_coaches"]

    _SQL: ClassVar[str] = """
        SELECT
            coach_id,
            team_id,
            season AS season_year,
            first_name,
            last_name,
            coach_type,
            CAST(is_assistant AS BOOLEAN) AS is_assistant
        FROM stg_coaches
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY coach_id, team_id, season_year
            ORDER BY coach_type
        ) = 1
    """
