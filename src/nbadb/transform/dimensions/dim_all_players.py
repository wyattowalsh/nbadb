from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class DimAllPlayersTransformer(SqlTransformer):
    output_table: ClassVar[str] = "dim_all_players"
    depends_on: ClassVar[list[str]] = ["stg_common_all_players"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_common_all_players
    """
