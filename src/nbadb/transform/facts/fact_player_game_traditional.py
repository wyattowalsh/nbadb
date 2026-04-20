from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactPlayerGameTraditionalTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_player_game_traditional"
    depends_on: ClassVar[list[str]] = ["stg_box_score_traditional", "dim_game"]

    _SQL: ClassVar[str] = """
        SELECT
            b.game_id, b.player_id, b.team_id,
            g.season_year,
            b.start_position, b.comment,
            TRY_CAST(b.min AS DOUBLE) AS min,
            b.fgm, b.fga, b.fg_pct,
            b.fg3m, b.fg3a, b.fg3_pct,
            b.ftm, b.fta, b.ft_pct,
            b.oreb, b.dreb, b.reb,
            b.ast, b.stl, b.blk, b.tov, b.pf,
            b.pts, b.plus_minus
        FROM stg_box_score_traditional b
        LEFT JOIN dim_game g ON b.game_id = g.game_id
        WHERE b.player_id IS NOT NULL
    """
