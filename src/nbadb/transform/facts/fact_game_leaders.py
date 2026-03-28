from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactGameLeadersTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_game_leaders"
    depends_on: ClassVar[list[str]] = ["stg_game_leaders"]

    _SQL: ClassVar[str] = """
        SELECT
            game_id, team_id, leader_type,
            person_id, name, player_slug,
            jersey_num, position, team_tricode,
            points, rebounds, assists
        FROM stg_game_leaders
    """
