from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class FactGameResultTransformer(BaseTransformer):
    output_table: ClassVar[str] = "fact_game_result"
    depends_on: ClassVar[list[str]] = ["stg_league_game_log", "stg_line_score"]

    _SQL: ClassVar[str] = """
        SELECT
            g.game_id,
            g.game_date,
            g.season_year,
            g.season_type,
            g.home_team_id,
            g.visitor_team_id,
            g.wl_home,
            g.pts_home,
            g.pts_away,
            g.plus_minus_home,
            g.plus_minus_away,
            l.pts_qtr1_home, l.pts_qtr2_home,
            l.pts_qtr3_home, l.pts_qtr4_home,
            l.pts_ot1_home, l.pts_ot2_home,
            l.pts_qtr1_away, l.pts_qtr2_away,
            l.pts_qtr3_away, l.pts_qtr4_away,
            l.pts_ot1_away, l.pts_ot2_away
        FROM stg_league_game_log g
        LEFT JOIN stg_line_score l ON g.game_id = l.game_id
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        conn.register("stg_league_game_log", staging["stg_league_game_log"].collect())
        conn.register("stg_line_score", staging["stg_line_score"].collect())
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
