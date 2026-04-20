from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactHomepageLeadersTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_homepage_leaders"
    depends_on: ClassVar[list[str]] = [
        "stg_home_page_leaders",
        "stg_homepage_leaders",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'home_page' AS leader_source
        FROM stg_home_page_leaders
        UNION ALL BY NAME
        SELECT *, 'homepage' AS leader_source
        FROM stg_homepage_leaders
    """
