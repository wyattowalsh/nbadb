from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactFantasyTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_fantasy"
    depends_on: ClassVar[list[str]] = ["stg_fanduel_player"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_fanduel_player
    """
