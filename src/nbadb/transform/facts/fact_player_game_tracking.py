from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class FactPlayerGameTrackingTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_player_game_tracking"
    depends_on: ClassVar[list[str]] = [
        "stg_box_score_player_track",
        "stg_box_score_defensive",
    ]

    _SQL: ClassVar[str] = """
        SELECT
            t.game_id, t.player_id, t.team_id, t.min,
            t.spd, t.dist,
            t.orbc, t.drbc, t.rbc,
            t.tchs, t.sast, t.ftast,
            t.cfgm, t.cfga, t.cfg_pct,
            t.ufgm, t.ufga, t.ufg_pct,
            t.dfgm, t.dfga, t.dfg_pct,
            d.matchup_min,
            d.partial_poss,
            d.switches_on,
            d.player_pts AS def_player_pts,
            d.def_fgm AS def_matchup_fgm,
            d.def_fga AS def_matchup_fga,
            d.def_fg_pct AS def_matchup_fg_pct
        FROM stg_box_score_player_track t
        LEFT JOIN stg_box_score_defensive d
            ON t.game_id = d.game_id AND t.player_id = d.player_id
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        conn.register("stg_box_score_player_track", staging["stg_box_score_player_track"].collect())
        conn.register("stg_box_score_defensive", staging["stg_box_score_defensive"].collect())
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
