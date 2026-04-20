from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggTeamPaceAndEfficiencyTransformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_team_pace_and_efficiency"
    depends_on: ClassVar[list[str]] = [
        "fact_box_score_advanced_team",
        "dim_game",
    ]

    _SQL: ClassVar[str] = """
        SELECT
            a.team_id,
            g.season_year,
            g.season_type,
            COUNT(*) AS gp,
            AVG(a.pace) AS avg_pace,
            AVG(a.off_rating) AS avg_ortg,
            AVG(a.def_rating) AS avg_drtg,
            AVG(a.net_rating) AS avg_net_rtg
        FROM fact_box_score_advanced_team a
        JOIN dim_game g ON a.game_id = g.game_id
        GROUP BY a.team_id, g.season_year, g.season_type
    """
