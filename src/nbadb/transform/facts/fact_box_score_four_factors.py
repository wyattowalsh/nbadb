from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactBoxScoreFourFactorsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_box_score_four_factors"
    depends_on: ClassVar[list[str]] = ["stg_box_score_four_factors_player"]

    _SQL: ClassVar[str] = """
        SELECT
            game_id, team_id, player_id,
            effective_field_goal_percentage,
            free_throw_attempt_rate,
            team_turnover_percentage,
            offensive_rebound_percentage,
            opp_effective_field_goal_percentage,
            opp_free_throw_attempt_rate,
            opp_team_turnover_percentage,
            opp_offensive_rebound_percentage
        FROM stg_box_score_four_factors_player
        ORDER BY game_id, team_id, player_id
    """
