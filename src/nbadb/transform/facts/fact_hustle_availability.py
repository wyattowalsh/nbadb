from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactHustleAvailabilityTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_hustle_availability"
    depends_on: ClassVar[list[str]] = [
        "stg_hustle_stats_available",
        "stg_box_score_hustle_box",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'availability' AS hustle_type
        FROM stg_hustle_stats_available
        UNION ALL BY NAME
        SELECT *, 'box_score' AS hustle_type
        FROM stg_box_score_hustle_box
    """
