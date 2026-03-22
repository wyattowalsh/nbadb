from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerYoyDetailTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_yoy_detail"
    depends_on: ClassVar[list[str]] = [
        "stg_player_yoy_by_year",
        "stg_player_yoy_overall",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'by_year' AS yoy_type
        FROM stg_player_yoy_by_year
        UNION ALL BY NAME
        SELECT *, 'overall' AS yoy_type
        FROM stg_player_yoy_overall
    """
