from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactDraftCombineDetailTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_draft_combine_detail"
    depends_on: ClassVar[list[str]] = [
        "stg_draft_combine_drills",
        "stg_draft_combine_anthro",
        "stg_draft_combine_nonstat_shooting",
        "stg_draft_combine_spot_shooting",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'drills' AS detail_type
        FROM stg_draft_combine_drills
        UNION ALL BY NAME
        SELECT *, 'anthro' AS detail_type
        FROM stg_draft_combine_anthro
        UNION ALL BY NAME
        SELECT *, 'nonstat_shooting' AS detail_type
        FROM stg_draft_combine_nonstat_shooting
        UNION ALL BY NAME
        SELECT *, 'spot_shooting' AS detail_type
        FROM stg_draft_combine_spot_shooting
    """
