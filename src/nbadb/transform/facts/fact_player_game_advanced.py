from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerGameAdvancedTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_game_advanced"
    depends_on: ClassVar[list[str]] = ["stg_box_score_advanced", "dim_game"]

    _SQL: ClassVar[str] = """
        SELECT
            b.game_id, b.player_id, b.team_id, b.min,
            g.season_year,
            b.off_rating, b.def_rating, b.net_rating,
            b.ast_pct, b.ast_tov, b.ast_ratio,
            b.oreb_pct, b.dreb_pct, b.reb_pct,
            b.tov_pct, b.efg_pct, b.ts_pct,
            b.usg_pct, b.pace, b.poss, b.pie,
            b.e_off_rating, b.e_def_rating, b.e_net_rating,
            b.e_usg_pct, b.e_pace
        FROM stg_box_score_advanced b
        LEFT JOIN dim_game g ON b.game_id = g.game_id
        WHERE b.player_id IS NOT NULL
    """
