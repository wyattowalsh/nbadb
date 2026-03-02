from __future__ import annotations

import duckdb
import polars as pl

from nbadb.transform.facts.fact_league_dash_player_stats import FactLeagueDashPlayerStatsTransformer
from nbadb.transform.facts.fact_league_dash_team_stats import FactLeagueDashTeamStatsTransformer


def _run_transform(t, staging: dict) -> pl.DataFrame:
    conn = duckdb.connect()
    for key, val in staging.items():
        conn.register(key, val.collect())
    t._conn = conn
    result = t.transform(staging)
    conn.close()
    return result


class TestFactLeagueDashPlayerStatsTransformer:
    def test_class_attributes(self) -> None:
        assert FactLeagueDashPlayerStatsTransformer.output_table == "fact_league_dash_player_stats"
        assert "stg_league_dash_player_stats" in FactLeagueDashPlayerStatsTransformer.depends_on

    def test_transform_basic(self) -> None:
        staging = {
            "stg_league_dash_player_stats": pl.DataFrame(
                {
                    "player_id": [201566, 203507],
                    "player_name": ["Russell Westbrook", "Giannis Antetokounmpo"],
                    "team_id": [1610612737, 1610612738],
                    "team_abbreviation": ["LAC", "MIL"],
                    "gp": [70, 65],
                    "pts": [22.5, 30.1],
                }
            ).lazy(),
        }
        t = FactLeagueDashPlayerStatsTransformer()
        result = _run_transform(t, staging)
        assert isinstance(result, pl.DataFrame)
        assert result.shape[0] == 2
        assert "player_id" in result.columns

    def test_ordered_by_player_id(self) -> None:
        staging = {
            "stg_league_dash_player_stats": pl.DataFrame(
                {
                    "player_id": [203507, 201566],
                    "player_name": ["Giannis", "Westbrook"],
                    "team_id": [1610612738, 1610612737],
                    "team_abbreviation": ["MIL", "LAC"],
                    "gp": [65, 70],
                    "pts": [30.1, 22.5],
                }
            ).lazy(),
        }
        t = FactLeagueDashPlayerStatsTransformer()
        result = _run_transform(t, staging)
        assert result["player_id"].to_list() == [201566, 203507]

    def test_select_star_preserves_all_columns(self) -> None:
        staging = {
            "stg_league_dash_player_stats": pl.DataFrame(
                {
                    "player_id": [201566],
                    "player_name": ["Westbrook"],
                    "team_id": [1610612737],
                    "team_abbreviation": ["LAC"],
                    "gp": [70],
                    "pts": [22.5],
                }
            ).lazy(),
        }
        t = FactLeagueDashPlayerStatsTransformer()
        result = _run_transform(t, staging)
        expected_cols = {"player_id", "player_name", "team_id", "team_abbreviation", "gp", "pts"}
        assert set(result.columns) == expected_cols


class TestFactLeagueDashTeamStatsTransformer:
    def test_class_attributes(self) -> None:
        assert FactLeagueDashTeamStatsTransformer.output_table == "fact_league_dash_team_stats"
        assert "stg_league_dash_team_stats" in FactLeagueDashTeamStatsTransformer.depends_on

    def test_transform_basic(self) -> None:
        staging = {
            "stg_league_dash_team_stats": pl.DataFrame(
                {
                    "team_id": [1610612737, 1610612738],
                    "team_name": ["Hawks", "Celtics"],
                    "gp": [82, 82],
                    "pts": [110.5, 117.3],
                }
            ).lazy(),
        }
        t = FactLeagueDashTeamStatsTransformer()
        result = _run_transform(t, staging)
        assert isinstance(result, pl.DataFrame)
        assert result.shape[0] == 2
        assert "team_id" in result.columns

    def test_ordered_by_team_id(self) -> None:
        staging = {
            "stg_league_dash_team_stats": pl.DataFrame(
                {
                    "team_id": [1610612738, 1610612737],
                    "team_name": ["Celtics", "Hawks"],
                    "gp": [82, 82],
                    "pts": [117.3, 110.5],
                }
            ).lazy(),
        }
        t = FactLeagueDashTeamStatsTransformer()
        result = _run_transform(t, staging)
        assert result["team_id"].to_list() == [1610612737, 1610612738]

    def test_select_star_preserves_all_columns(self) -> None:
        staging = {
            "stg_league_dash_team_stats": pl.DataFrame(
                {
                    "team_id": [1610612737],
                    "team_name": ["Hawks"],
                    "gp": [82],
                    "pts": [110.5],
                }
            ).lazy(),
        }
        t = FactLeagueDashTeamStatsTransformer()
        result = _run_transform(t, staging)
        expected_cols = {"team_id", "team_name", "gp", "pts"}
        assert set(result.columns) == expected_cols
