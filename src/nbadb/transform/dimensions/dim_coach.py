from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class DimCoachTransformer(SqlTransformer):
    output_table: ClassVar[str] = "dim_coach"
    depends_on: ClassVar[list[str]] = ["stg_team_info", "stg_coaches"]

    _SQL: ClassVar[str] = """
        SELECT
            coach_id,
            coach_name,
            team_id,
            season_year,
            coach_type,
        FROM stg_team_info
        UNION ALL BY NAME
        SELECT *
        FROM stg_coaches
    """
