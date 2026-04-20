from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactTrackingDefenseTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_tracking_defense"
    depends_on: ClassVar[list[str]] = ["stg_tracking_defense"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_tracking_defense
    """
