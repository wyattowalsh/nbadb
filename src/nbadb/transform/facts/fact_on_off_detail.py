from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactOnOffDetailTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_on_off_detail"
    depends_on: ClassVar[list[str]] = [
        "stg_on_off_details_overall",
        "stg_on_off_details_off_court",
        "stg_on_off_details_on_court",
        "stg_on_off_summary_overall",
        "stg_on_off_summary_off_court",
        "stg_on_off_summary_on_court",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'detail_overall' AS court_status
        FROM stg_on_off_details_overall
        UNION ALL BY NAME
        SELECT *, 'detail_off_court' AS court_status
        FROM stg_on_off_details_off_court
        UNION ALL BY NAME
        SELECT *, 'detail_on_court' AS court_status
        FROM stg_on_off_details_on_court
        UNION ALL BY NAME
        SELECT *, 'summary_overall' AS court_status
        FROM stg_on_off_summary_overall
        UNION ALL BY NAME
        SELECT *, 'summary_off_court' AS court_status
        FROM stg_on_off_summary_off_court
        UNION ALL BY NAME
        SELECT *, 'summary_on_court' AS court_status
        FROM stg_on_off_summary_on_court
    """
