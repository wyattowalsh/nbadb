from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggTeamDefenseTransformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_team_defense"
    depends_on: ClassVar[list[str]] = [
        "fact_box_score_advanced_team",
        "fact_team_game_hustle",
        "fact_box_score_four_factors_team",
        "dim_game",
    ]

    _SQL: ClassVar[str] = """
        SELECT
            a.team_id,
            g.season_year,
            g.season_type,
            COUNT(*) AS gp,
            AVG(a.def_rating) AS avg_def_rating,
            AVG(a.net_rating) AS avg_net_rating,
            AVG(ff.opp_effective_field_goal_percentage) AS avg_opp_efg_pct,
            AVG(ff.opp_free_throw_attempt_rate) AS avg_opp_fta_rate,
            AVG(ff.opp_team_turnover_percentage) AS avg_opp_tov_pct,
            AVG(ff.opp_offensive_rebound_percentage) AS avg_opp_oreb_pct,
            AVG(h.contested_shots) AS avg_contested_shots,
            AVG(h.deflections) AS avg_deflections,
            AVG(h.loose_balls_recovered) AS avg_loose_balls_recovered,
            AVG(h.charges_drawn) AS avg_charges_drawn,
            AVG(h.screen_assists) AS avg_screen_assists
        FROM fact_box_score_advanced_team a
        JOIN dim_game g ON a.game_id = g.game_id
        LEFT JOIN fact_team_game_hustle h
            ON a.team_id = h.team_id AND a.game_id = h.game_id
        LEFT JOIN fact_box_score_four_factors_team ff
            ON a.team_id = ff.team_id AND a.game_id = ff.game_id
        GROUP BY a.team_id, g.season_year, g.season_type
    """
