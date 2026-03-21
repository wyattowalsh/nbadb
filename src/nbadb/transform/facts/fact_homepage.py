from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactHomepageTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_homepage"
    depends_on: ClassVar[list[str]] = [
        "stg_home_page_v2",
        "stg_homepage_v2",
    ]

    _SQL: ClassVar[str] = """
        SELECT *, 'home_page' AS homepage_source
        FROM stg_home_page_v2
        UNION ALL BY NAME
        SELECT *, 'homepage' AS homepage_source
        FROM stg_homepage_v2
    """
