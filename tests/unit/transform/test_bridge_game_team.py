from __future__ import annotations

import duckdb
import polars as pl

from nbadb.transform.facts.bridge_game_team import BridgeGameTeamTransformer


def _run(transformer, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        for key, val in staging.items():
            conn.register(key, val.collect())
        transformer._conn = conn
        return transformer.transform(staging)
    finally:
        conn.close()


class TestBridgeGameTeam:
    def test_class_attrs(self) -> None:
        assert BridgeGameTeamTransformer.output_table == "bridge_game_team"
        assert BridgeGameTeamTransformer.depends_on == ["stg_league_game_log"]

    def test_home_away_rows(self) -> None:
        staging = {
            "stg_league_game_log": pl.DataFrame(
                {
                    "game_id": ["0022400001"],
                    "home_team_id": [1],
                    "visitor_team_id": [2],
                    "wl_home": ["W"],
                    "season_year": ["2024-25"],
                }
            ).lazy(),
        }

        result = _run(BridgeGameTeamTransformer(), staging)

        assert result.shape[0] == 2

        home = result.filter(pl.col("side") == "home")
        assert home.shape[0] == 1
        assert home["team_id"][0] == 1
        assert home["wl"][0] == "W"
        assert home["game_id"][0] == "0022400001"
        assert home["season_year"][0] == "2024-25"

        away = result.filter(pl.col("side") == "away")
        assert away.shape[0] == 1
        assert away["team_id"][0] == 2
        assert away["wl"][0] == "L"
        assert away["game_id"][0] == "0022400001"
        assert away["season_year"][0] == "2024-25"
