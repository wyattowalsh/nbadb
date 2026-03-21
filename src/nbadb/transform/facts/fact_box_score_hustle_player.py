from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactBoxScoreHustlePlayerTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_box_score_hustle_player"
    depends_on: ClassVar[list[str]] = ["stg_box_score_hustle_player"]

    _SQL: ClassVar[str] = """
        SELECT *
        FROM stg_box_score_hustle_player
    """
