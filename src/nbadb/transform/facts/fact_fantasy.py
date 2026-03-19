from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactFantasyTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_fantasy"
    depends_on: ClassVar[list[str]] = ["stg_fanduel_player", "stg_fantasy_widget"]

    _SQL: ClassVar[str] = """
        SELECT *, 'fanduel' AS fantasy_source
        FROM stg_fanduel_player
        UNION ALL BY NAME
        SELECT *, 'fantasy_widget' AS fantasy_source
        FROM stg_fantasy_widget
    """
