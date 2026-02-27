from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import duckdb

from nbadb.transform.base import BaseTransformer

if TYPE_CHECKING:
    import polars as pl


class FactBoxScoreFourFactorsTransformer(BaseTransformer):
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

    def transform(self, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
        conn = duckdb.connect()
        table = "stg_box_score_four_factors_player"
        conn.register(table, staging[table].collect())
        result = conn.execute(self._SQL).pl()
        conn.close()
        return result
