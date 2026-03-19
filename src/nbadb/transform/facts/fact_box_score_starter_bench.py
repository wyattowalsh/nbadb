from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactBoxScoreStarterBenchTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_box_score_starter_bench"
    depends_on: ClassVar[list[str]] = ["stg_box_score_traditional_starter_bench"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_box_score_traditional_starter_bench
    """
