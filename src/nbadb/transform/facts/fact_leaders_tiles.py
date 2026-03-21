from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactLeadersTilesTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_leaders_tiles"
    depends_on: ClassVar[list[str]] = ["stg_leaders_tiles"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_leaders_tiles
    """
