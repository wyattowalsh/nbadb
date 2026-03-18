from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactIstStandingsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_ist_standings"
    depends_on: ClassVar[list[str]] = ["stg_ist_standings"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_ist_standings
    """
