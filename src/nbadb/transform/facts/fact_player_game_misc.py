from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class FactPlayerGameMiscTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_player_game_misc"
    depends_on: ClassVar[list[str]] = [
        "stg_box_score_misc",
        "stg_box_score_scoring",
        "stg_box_score_usage",
    ]

    _SQL: ClassVar[str] = """
        SELECT
            m.game_id,
            m.player_id,
            m.team_id,
            m.pts_off_tov,
            m.pts_2nd_chance,
            m.pts_fb,
            m.pts_paint,
            m.opp_pts_off_tov,
            m.opp_pts_2nd_chance,
            m.opp_pts_fb,
            m.opp_pts_paint,
            s.pct_fga_2pt,
            s.pct_fga_3pt,
            s.pct_pts_2pt,
            s.pct_pts_2pt_mr,
            s.pct_pts_3pt,
            s.pct_pts_fb,
            s.pct_pts_ft,
            s.pct_pts_off_tov,
            s.pct_pts_paint,
            s.pct_ast_2pm,
            s.pct_uast_2pm,
            s.pct_ast_3pm,
            s.pct_uast_3pm,
            s.pct_ast_fgm,
            s.pct_uast_fgm,
            u.usg_pct,
            u.pct_fgm,
            u.pct_fga,
            u.pct_fg3m,
            u.pct_fg3a,
            u.pct_ftm,
            u.pct_fta,
            u.pct_oreb,
            u.pct_dreb,
            u.pct_reb,
            u.pct_ast,
            u.pct_tov,
            u.pct_stl,
            u.pct_blk,
            u.pct_pts
        FROM stg_box_score_misc m
        LEFT JOIN stg_box_score_scoring s
            ON m.game_id = s.game_id AND m.player_id = s.player_id
        LEFT JOIN stg_box_score_usage u
            ON m.game_id = u.game_id AND m.player_id = u.player_id
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        conn.register("stg_box_score_misc", staging["stg_box_score_misc"].collect())
        conn.register("stg_box_score_scoring", staging["stg_box_score_scoring"].collect())
        conn.register("stg_box_score_usage", staging["stg_box_score_usage"].collect())
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
