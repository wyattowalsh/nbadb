from __future__ import annotations

import duckdb
import polars as pl

from nbadb.transform.facts.fact_box_score_four_factors import FactBoxScoreFourFactorsTransformer


def _run_transform(t: FactBoxScoreFourFactorsTransformer, staging: dict) -> pl.DataFrame:
    conn = duckdb.connect()
    for key, val in staging.items():
        conn.register(key, val.collect())
    t._conn = conn
    result = t.transform(staging)
    conn.close()
    return result


class TestFactBoxScoreFourFactorsTransformer:
    def test_class_attributes(self) -> None:
        assert FactBoxScoreFourFactorsTransformer.output_table == "fact_box_score_four_factors"
        assert "stg_box_score_four_factors_player" in FactBoxScoreFourFactorsTransformer.depends_on

    def test_transform_basic(self) -> None:
        staging = {
            "stg_box_score_four_factors_player": pl.DataFrame(
                {
                    "game_id": ["0022300001", "0022300001"],
                    "team_id": [1610612737, 1610612738],
                    "player_id": [201566, 203507],
                    "player_name": ["Russell Westbrook", "Giannis Antetokounmpo"],
                    "min": ["32:00", "36:00"],
                    "effective_field_goal_percentage": [0.52, 0.61],
                    "free_throw_attempt_rate": [0.35, 0.42],
                    "team_turnover_percentage": [0.12, 0.10],
                    "offensive_rebound_percentage": [0.08, 0.15],
                    "opp_effective_field_goal_percentage": [0.48, 0.50],
                    "opp_free_throw_attempt_rate": [0.30, 0.28],
                    "opp_team_turnover_percentage": [0.14, 0.11],
                    "opp_offensive_rebound_percentage": [0.10, 0.09],
                }
            ).lazy(),
        }
        t = FactBoxScoreFourFactorsTransformer()
        result = _run_transform(t, staging)
        assert isinstance(result, pl.DataFrame)
        assert result.shape[0] == 2
        assert "effective_field_goal_percentage" in result.columns
        assert "game_id" in result.columns
        assert "player_name" not in result.columns  # Dropped in SQL SELECT

    def test_drops_non_selected_columns(self) -> None:
        staging = {
            "stg_box_score_four_factors_player": pl.DataFrame(
                {
                    "game_id": ["0022300001"],
                    "team_id": [1610612737],
                    "player_id": [201566],
                    "player_name": ["Russell Westbrook"],
                    "min": ["32:00"],
                    "effective_field_goal_percentage": [0.52],
                    "free_throw_attempt_rate": [0.35],
                    "team_turnover_percentage": [0.12],
                    "offensive_rebound_percentage": [0.08],
                    "opp_effective_field_goal_percentage": [0.48],
                    "opp_free_throw_attempt_rate": [0.30],
                    "opp_team_turnover_percentage": [0.14],
                    "opp_offensive_rebound_percentage": [0.10],
                }
            ).lazy(),
        }
        t = FactBoxScoreFourFactorsTransformer()
        result = _run_transform(t, staging)
        expected_cols = {
            "game_id",
            "team_id",
            "player_id",
            "effective_field_goal_percentage",
            "free_throw_attempt_rate",
            "team_turnover_percentage",
            "offensive_rebound_percentage",
            "opp_effective_field_goal_percentage",
            "opp_free_throw_attempt_rate",
            "opp_team_turnover_percentage",
            "opp_offensive_rebound_percentage",
        }
        assert set(result.columns) == expected_cols

    def test_ordered_by_game_team_player(self) -> None:
        staging = {
            "stg_box_score_four_factors_player": pl.DataFrame(
                {
                    "game_id": ["0022300002", "0022300001"],
                    "team_id": [1610612738, 1610612737],
                    "player_id": [203507, 201566],
                    "player_name": ["Giannis", "Westbrook"],
                    "min": ["36:00", "32:00"],
                    "effective_field_goal_percentage": [0.61, 0.52],
                    "free_throw_attempt_rate": [0.42, 0.35],
                    "team_turnover_percentage": [0.10, 0.12],
                    "offensive_rebound_percentage": [0.15, 0.08],
                    "opp_effective_field_goal_percentage": [0.50, 0.48],
                    "opp_free_throw_attempt_rate": [0.28, 0.30],
                    "opp_team_turnover_percentage": [0.11, 0.14],
                    "opp_offensive_rebound_percentage": [0.09, 0.10],
                }
            ).lazy(),
        }
        t = FactBoxScoreFourFactorsTransformer()
        result = _run_transform(t, staging)
        assert result["game_id"].to_list() == ["0022300001", "0022300002"]
