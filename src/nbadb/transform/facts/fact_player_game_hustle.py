from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerGameHustleTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_game_hustle"
    depends_on: ClassVar[list[str]] = ["stg_box_score_hustle", "dim_game"]

    _SQL: ClassVar[str] = """
        SELECT
            b.game_id, b.player_id, b.team_id, b.min,
            g.season_year,
            b.contested_shots, b.contested_shots_2pt, b.contested_shots_3pt,
            b.deflections, b.charges_drawn,
            b.screen_assists, b.screen_ast_pts,
            b.loose_balls_recovered, b.box_outs
        FROM stg_box_score_hustle b
        LEFT JOIN dim_game g ON b.game_id = g.game_id
        WHERE b.player_id IS NOT NULL
    """
