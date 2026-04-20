from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayoffSeriesTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_playoff_series"
    depends_on: ClassVar[list[str]] = ["stg_common_playoff_series"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_common_playoff_series
    """
