from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerGameHustleTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_game_hustle"
    depends_on: ClassVar[list[str]] = ["stg_box_score_hustle"]

    _SQL: ClassVar[str] = """
        SELECT
            game_id, player_id, team_id, min,
            contested_shots, contested_shots_2pt, contested_shots_3pt,
            deflections, charges_drawn,
            screen_assists, screen_ast_pts,
            loose_balls_recovered, box_outs
        FROM stg_box_score_hustle
        WHERE player_id IS NOT NULL
    """
