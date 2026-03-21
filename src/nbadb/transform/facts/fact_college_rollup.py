from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactCollegeRollupTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_college_rollup"
    depends_on: ClassVar[list[str]] = [
        "stg_player_college_rollup",
        "stg_player_career_by_college_rollup",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'college' AS rollup_type
        FROM stg_player_college_rollup
        UNION ALL BY NAME
        SELECT *, 'career_by_college' AS rollup_type
        FROM stg_player_career_by_college_rollup
    """
