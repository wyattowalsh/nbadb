from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerAwardsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_awards"
    depends_on: ClassVar[list[str]] = ["stg_player_awards"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_player_awards
    """
