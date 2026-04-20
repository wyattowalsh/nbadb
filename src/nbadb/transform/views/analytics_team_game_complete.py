from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AnalyticsTeamGameCompleteTransformer(SqlTransformer):
    output_table: ClassVar[str] = "analytics_team_game_complete"
    depends_on: ClassVar[list[str]] = [
        "fact_team_game",
        "fact_box_score_advanced_team",
        "fact_box_score_misc_team",
        "fact_team_game_hustle",
        "fact_box_score_player_track_team",
        "dim_team",
        "dim_game",
    ]

    _SQL: ClassVar[str] = """
        SELECT
            t.team_id,
            t.game_id,
            g.season_year,
            g.game_date,
            tm.full_name AS team_name,
            tm.abbreviation AS team_abbreviation,
            -- traditional
            t.pts, t.reb, t.ast, t.stl, t.blk, t.tov,
            t.fgm, t.fga, t.fg_pct,
            t.fg3m, t.fg3a, t.fg3_pct,
            t.ftm, t.fta, t.ft_pct,
            t.oreb, t.dreb, t.pf, t.plus_minus,
            -- advanced
            a.off_rating, a.def_rating, a.net_rating,
            a.ast_pct, a.reb_pct, a.oreb_pct, a.dreb_pct,
            a.efg_pct, a.ts_pct, a.pace, a.pie,
            -- misc
            m.pts_off_tov, m.second_chance_pts, m.fbps, m.pitp,
            -- hustle
            h.contested_shots, h.deflections,
            h.loose_balls_recovered, h.charges_drawn,
            h.screen_assists,
            -- tracking
            k.dist, k.spd, k.tchs, k.passes
        FROM fact_team_game t
        LEFT JOIN fact_box_score_advanced_team a
            ON t.team_id = a.team_id AND t.game_id = a.game_id
        LEFT JOIN fact_box_score_misc_team m
            ON t.team_id = m.team_id AND t.game_id = m.game_id
        LEFT JOIN fact_team_game_hustle h
            ON t.team_id = h.team_id AND t.game_id = h.game_id
        LEFT JOIN fact_box_score_player_track_team k
            ON t.team_id = k.team_id AND t.game_id = k.game_id
        LEFT JOIN dim_team tm ON t.team_id = tm.team_id
        LEFT JOIN dim_game g ON t.game_id = g.game_id
    """
