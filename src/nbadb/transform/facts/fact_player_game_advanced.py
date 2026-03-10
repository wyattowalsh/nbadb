from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerGameAdvancedTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_game_advanced"
    depends_on: ClassVar[list[str]] = ["stg_box_score_advanced"]

    _SQL: ClassVar[str] = """
        SELECT
            game_id, player_id, team_id, min,
            off_rating, def_rating, net_rating,
            ast_pct, ast_tov, ast_ratio,
            oreb_pct, dreb_pct, reb_pct,
            tov_pct, efg_pct, ts_pct,
            usg_pct, pace, poss, pie,
            e_off_rating, e_def_rating, e_net_rating,
            e_usg_pct, e_pace
        FROM stg_box_score_advanced
        WHERE player_id IS NOT NULL
    """
