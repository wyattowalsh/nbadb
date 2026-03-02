from __future__ import annotations

import duckdb
import polars as pl

from nbadb.transform.facts.fact_game_leaders import FactGameLeadersTransformer


def _run_transform(t: FactGameLeadersTransformer, staging: dict) -> pl.DataFrame:
    conn = duckdb.connect()
    for key, val in staging.items():
        conn.register(key, val.collect())
    t._conn = conn
    result = t.transform(staging)
    conn.close()
    return result


class TestFactGameLeadersTransformer:
    def test_class_attributes(self) -> None:
        assert FactGameLeadersTransformer.output_table == "fact_game_leaders"
        assert "stg_game_leaders" in FactGameLeadersTransformer.depends_on

    def test_transform_basic(self) -> None:
        staging = {
            "stg_game_leaders": pl.DataFrame(
                {
                    "game_id": ["0022300001", "0022300001"],
                    "team_id": [1610612737, 1610612738],
                    "leader_type": ["homeLeaders", "awayLeaders"],
                    "person_id": [201566, 203507],
                    "name": ["Russell Westbrook", "Giannis Antetokounmpo"],
                    "player_slug": ["russell-westbrook", "giannis-antetokounmpo"],
                    "jersey_num": ["0", "34"],
                    "position": ["G", "F"],
                    "team_tricode": ["LAC", "MIL"],
                    "points": [25.0, 32.0],
                    "rebounds": [8.0, 12.0],
                    "assists": [10.0, 5.0],
                }
            ).lazy(),
        }
        t = FactGameLeadersTransformer()
        result = _run_transform(t, staging)
        assert isinstance(result, pl.DataFrame)
        assert result.shape[0] == 2
        assert "game_id" in result.columns
        assert "person_id" in result.columns
        assert "points" in result.columns

    def test_output_columns_match_sql_select(self) -> None:
        staging = {
            "stg_game_leaders": pl.DataFrame(
                {
                    "game_id": ["0022300001"],
                    "team_id": [1610612737],
                    "leader_type": ["homeLeaders"],
                    "person_id": [201566],
                    "name": ["Russell Westbrook"],
                    "player_slug": ["russell-westbrook"],
                    "jersey_num": ["0"],
                    "position": ["G"],
                    "team_tricode": ["LAC"],
                    "points": [25.0],
                    "rebounds": [8.0],
                    "assists": [10.0],
                }
            ).lazy(),
        }
        t = FactGameLeadersTransformer()
        result = _run_transform(t, staging)
        expected_cols = {
            "game_id",
            "team_id",
            "leader_type",
            "person_id",
            "name",
            "player_slug",
            "jersey_num",
            "position",
            "team_tricode",
            "points",
            "rebounds",
            "assists",
        }
        assert set(result.columns) == expected_cols

    def test_ordered_by_game_id_team_id(self) -> None:
        staging = {
            "stg_game_leaders": pl.DataFrame(
                {
                    "game_id": ["0022300002", "0022300001"],
                    "team_id": [1610612738, 1610612737],
                    "leader_type": ["awayLeaders", "homeLeaders"],
                    "person_id": [203507, 201566],
                    "name": ["Giannis", "Westbrook"],
                    "player_slug": ["giannis-antetokounmpo", "russell-westbrook"],
                    "jersey_num": ["34", "0"],
                    "position": ["F", "G"],
                    "team_tricode": ["MIL", "LAC"],
                    "points": [32.0, 25.0],
                    "rebounds": [12.0, 8.0],
                    "assists": [5.0, 10.0],
                }
            ).lazy(),
        }
        t = FactGameLeadersTransformer()
        result = _run_transform(t, staging)
        assert result["game_id"].to_list() == ["0022300001", "0022300002"]

    def test_extra_staging_columns_not_in_output(self) -> None:
        staging = {
            "stg_game_leaders": pl.DataFrame(
                {
                    "game_id": ["0022300001"],
                    "team_id": [1610612737],
                    "leader_type": ["homeLeaders"],
                    "person_id": [201566],
                    "name": ["Russell Westbrook"],
                    "player_slug": ["russell-westbrook"],
                    "jersey_num": ["0"],
                    "position": ["G"],
                    "team_tricode": ["LAC"],
                    "points": [25.0],
                    "rebounds": [8.0],
                    "assists": [10.0],
                    "extra_column": ["should_not_appear"],
                }
            ).lazy(),
        }
        t = FactGameLeadersTransformer()
        result = _run_transform(t, staging)
        assert "extra_column" not in result.columns
