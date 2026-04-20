from __future__ import annotations

import duckdb
import polars as pl

from nbadb.transform.facts.fact_player_matchups_detail import (
    FactPlayerMatchupsDetailTransformer,
)
from nbadb.transform.facts.fact_player_matchups_shot_detail import (
    FactPlayerMatchupsShotDetailTransformer,
)
from nbadb.transform.facts.fact_team_matchups_detail import FactTeamMatchupsDetailTransformer
from nbadb.transform.facts.fact_team_matchups_shot_detail import (
    FactTeamMatchupsShotDetailTransformer,
)
from nbadb.transform.pipeline import _star_schema_map


def _run(transformer, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        for key, val in staging.items():
            conn.register(key, val.collect())
        transformer._conn = conn
        return transformer.transform(staging)
    finally:
        conn.close()


def _assert_schema_valid(table: str, df: pl.DataFrame) -> None:
    schema_cls = _star_schema_map()[table]
    validated = schema_cls.validate(df)
    assert isinstance(validated, pl.DataFrame)


class TestFactPlayerMatchupsDetail:
    def test_class_attrs(self) -> None:
        assert FactPlayerMatchupsDetailTransformer.output_table == "fact_player_matchups_detail"
        assert len(FactPlayerMatchupsDetailTransformer.depends_on) == 4

    def test_consolidates_player_comparison_stats_packets(self) -> None:
        staging = {
            "stg_player_compare_individual": pl.DataFrame(
                {
                    "group_set": ["Individual"],
                    "description": ["Starter"],
                    "min": [18.5],
                    "pts": [9.2],
                    "plus_minus": [2.1],
                }
            ).lazy(),
            "stg_pvp_overall": pl.DataFrame(
                {
                    "group_set": ["Overall"],
                    "group_value": ["Overall"],
                    "player_id": [201939],
                    "player_name": ["Stephen Curry"],
                    "vs_player_id": [2544],
                    "vs_player_name": ["LeBron James"],
                    "gp": [12],
                    "pts": [28.4],
                    "plus_minus": [6.3],
                }
            ).lazy(),
        }

        result = _run(FactPlayerMatchupsDetailTransformer(), staging)

        assert result.shape[0] == 2
        assert {"detail_source", "detail_variant", "group_set", "pts"}.issubset(result.columns)
        assert set(result["detail_source"].to_list()) == {"player_compare", "player_vs_player"}
        assert set(result["detail_variant"].to_list()) == {"individual", "overall"}
        _assert_schema_valid("fact_player_matchups_detail", result)


class TestFactPlayerMatchupsShotDetail:
    def test_class_attrs(self) -> None:
        assert (
            FactPlayerMatchupsShotDetailTransformer.output_table
            == "fact_player_matchups_shot_detail"
        )
        assert len(FactPlayerMatchupsShotDetailTransformer.depends_on) == 6

    def test_consolidates_player_shot_split_packets(self) -> None:
        staging = {
            "stg_pvp_shot_area_off": pl.DataFrame(
                {
                    "group_set": ["ShotArea"],
                    "group_value": ["Restricted Area"],
                    "player_id": [201939],
                    "vs_player_id": [2544],
                    "court_status": ["Off"],
                    "fgm": [4.0],
                    "fga": [8.0],
                    "fg_pct": [0.5],
                }
            ).lazy(),
            "stg_pvp_shot_dist_overall": pl.DataFrame(
                {
                    "group_set": ["ShotDistance"],
                    "group_value": ["24+ ft"],
                    "player_id": [201939],
                    "fgm": [3.0],
                    "fga": [9.0],
                    "fg_pct": [0.333],
                }
            ).lazy(),
        }

        result = _run(FactPlayerMatchupsShotDetailTransformer(), staging)

        assert result.shape[0] == 2
        assert set(result["split_family"].to_list()) == {"shot_area", "shot_distance"}
        assert set(result["split_scope"].to_list()) == {"off_court", "overall"}
        _assert_schema_valid("fact_player_matchups_shot_detail", result)


class TestFactTeamMatchupsDetail:
    def test_class_attrs(self) -> None:
        assert FactTeamMatchupsDetailTransformer.output_table == "fact_team_matchups_detail"
        assert len(FactTeamMatchupsDetailTransformer.depends_on) == 8

    def test_consolidates_team_comparison_stats_packets(self) -> None:
        staging = {
            "stg_tvp_on_off_court": pl.DataFrame(
                {
                    "group_set": ["OnOffCourt"],
                    "team_id": [1610612738],
                    "team_abbreviation": ["BOS"],
                    "team_name": ["Celtics"],
                    "vs_player_id": [2544],
                    "vs_player_name": ["LeBron James"],
                    "court_status": ["On"],
                    "gp": [5],
                    "pts": [114.2],
                    "plus_minus": [7.0],
                }
            ).lazy(),
            "stg_tapvp_team_on": pl.DataFrame(
                {
                    "group_set": ["TeamPlayersVsPlayersOn"],
                    "title_description": ["Lineup On"],
                    "player_id": [201939],
                    "player_name": ["Stephen Curry"],
                    "min": [21.4],
                    "pts": [18.0],
                    "plus_minus": [4.5],
                }
            ).lazy(),
        }

        result = _run(FactTeamMatchupsDetailTransformer(), staging)

        assert result.shape[0] == 2
        assert set(result["detail_source"].to_list()) == {
            "team_vs_player",
            "team_and_players_vs",
        }
        assert set(result["detail_variant"].to_list()) == {
            "on_off_court",
            "team_players_vs_players_on",
        }
        _assert_schema_valid("fact_team_matchups_detail", result)


class TestFactTeamMatchupsShotDetail:
    def test_class_attrs(self) -> None:
        assert (
            FactTeamMatchupsShotDetailTransformer.output_table == "fact_team_matchups_shot_detail"
        )
        assert len(FactTeamMatchupsShotDetailTransformer.depends_on) == 6

    def test_consolidates_team_shot_split_packets(self) -> None:
        staging = {
            "stg_tvp_shot_area_off": pl.DataFrame(
                {
                    "group_set": ["ShotArea"],
                    "group_value": ["Paint"],
                    "team_id": [1610612738],
                    "team_abbreviation": ["BOS"],
                    "team_name": ["Celtics"],
                    "vs_player_id": [2544],
                    "vs_player_name": ["LeBron James"],
                    "court_status": ["Off"],
                    "fgm": [12.0],
                    "fga": [24.0],
                    "fg_pct": [0.5],
                }
            ).lazy(),
            "stg_tvp_shot_dist_overall": pl.DataFrame(
                {
                    "group_set": ["ShotDistance"],
                    "group_value": ["24+ ft"],
                    "team_id": [1610612738],
                    "team_abbreviation": ["BOS"],
                    "team_name": ["Celtics"],
                    "fgm": [14.0],
                    "fga": [39.0],
                    "fg_pct": [0.359],
                }
            ).lazy(),
        }

        result = _run(FactTeamMatchupsShotDetailTransformer(), staging)

        assert result.shape[0] == 2
        assert set(result["split_family"].to_list()) == {"shot_area", "shot_distance"}
        assert set(result["split_scope"].to_list()) == {"off_court", "overall"}
        _assert_schema_valid("fact_team_matchups_shot_detail", result)


def test_new_comparison_detail_schemas_are_discovered_without_init_exports() -> None:
    schema_map = _star_schema_map()

    assert {
        "fact_player_matchups_detail",
        "fact_player_matchups_shot_detail",
        "fact_team_matchups_detail",
        "fact_team_matchups_shot_detail",
    }.issubset(schema_map)
