from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerAvailableSeasonsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_available_seasons"
    depends_on: ClassVar[list[str]] = ["stg_player_available_seasons"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_player_available_seasons
    """
