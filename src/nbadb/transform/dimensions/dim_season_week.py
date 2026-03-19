from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class DimSeasonWeekTransformer(SqlTransformer):
    output_table: ClassVar[str] = "dim_season_week"
    depends_on: ClassVar[list[str]] = ["stg_schedule_weeks"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_schedule_weeks
    """
