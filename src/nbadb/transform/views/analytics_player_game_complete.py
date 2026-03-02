from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class AnalyticsPlayerGameCompleteTransformer(BaseTransformer):
    output_table: ClassVar[str] = "analytics_player_game_complete"
    depends_on: ClassVar[list[str]] = [
        "fact_player_game_traditional",
        "fact_player_game_advanced",
        "fact_player_game_misc",
        "fact_player_game_hustle",
        "fact_player_game_tracking",
        "dim_player",
        "dim_game",
        "dim_team",
    ]

    _SQL: ClassVar[str] = """
        SELECT
            t.player_id,
            t.game_id,
            t.team_id,
            g.season_year,
            g.game_date,
            p.full_name AS player_name,
            tm.abbreviation AS team_abbreviation,
            -- traditional
            t.min, t.pts, t.reb, t.ast, t.stl, t.blk, t.tov,
            t.fgm, t.fga, t.fg_pct,
            t.fg3m, t.fg3a, t.fg3_pct,
            t.ftm, t.fta, t.ft_pct,
            t.oreb, t.dreb, t.pf, t.plus_minus,
            -- advanced
            a.off_rating, a.def_rating, a.net_rating,
            a.ast_pct, a.ast_ratio, a.reb_pct, a.oreb_pct, a.dreb_pct,
            a.efg_pct, a.ts_pct, a.pace, a.pie,
            -- misc
            m.pts_off_tov, m.pts_2nd_chance, m.pts_fb, m.pts_paint,
            m.usg_pct,
            -- hustle
            h.contested_shots, h.deflections,
            h.loose_balls_recovered, h.charges_drawn,
            h.screen_assists,
            -- tracking
            k.dist_miles, k.speed, k.touches, k.passes,
            k.contested_shots_defended, k.dfg_pct
        FROM fact_player_game_traditional t
        LEFT JOIN fact_player_game_advanced a
            ON t.player_id = a.player_id AND t.game_id = a.game_id
        LEFT JOIN fact_player_game_misc m
            ON t.player_id = m.player_id AND t.game_id = m.game_id
        LEFT JOIN fact_player_game_hustle h
            ON t.player_id = h.player_id AND t.game_id = h.game_id
        LEFT JOIN fact_player_game_tracking k
            ON t.player_id = k.player_id AND t.game_id = k.game_id
        LEFT JOIN dim_player p ON t.player_id = p.player_id AND p.is_current = TRUE
        LEFT JOIN dim_game g ON t.game_id = g.game_id
        LEFT JOIN dim_team tm ON t.team_id = tm.team_id
        ORDER BY g.game_date, t.player_id
    """

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        return self._conn.execute(self._SQL).pl()
