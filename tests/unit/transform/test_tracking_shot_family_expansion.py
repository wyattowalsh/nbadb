from __future__ import annotations

import duckdb
import polars as pl

from nbadb.transform.facts.fact_league_pt_shots import (
    FactLeagueOppPtShotTransformer,
    FactLeaguePlayerPtShotTransformer,
    FactLeaguePtStatsTransformer,
    FactLeaguePtTeamDefendTransformer,
    FactLeagueTeamPtShotTransformer,
)
from nbadb.transform.facts.fact_league_shot_locations import (
    FactLeaguePlayerShotLocationsTransformer,
    FactLeagueTeamShotLocationsTransformer,
)
from nbadb.transform.facts.fact_player_pt_tracking import (
    FactPlayerPtPassTransformer,
    FactPlayerPtShotDefendTransformer,
)
from nbadb.transform.facts.fact_tracking_defense import FactLeaguePtDefendTransformer
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


def _assert_output_schema(table: str, df: pl.DataFrame) -> None:
    validated = _star_schema_map()[table].validate(df)
    assert isinstance(validated, pl.DataFrame)


def test_league_tracking_and_shot_splits_expand_to_endpoint_tables() -> None:
    pt_row = pl.DataFrame(
        {
            "id": [1],
            "player_id": [2544],
            "player_name": ["LeBron James"],
            "team_id": [1610612747],
            "team_name": ["Los Angeles Lakers"],
            "team_abbreviation": ["LAL"],
            "season_year": ["2024-25"],
            "g": [82],
            "sort_order": [1],
            "close_def_dist_range": ["6+ Feet - Wide Open"],
            "fga_frequency": [0.286],
            "fgm": [205],
            "fga": [420],
            "fg_pct": [0.488],
            "efg_pct": [0.612],
            "fg2m": [88],
            "fg2a": [160],
            "fg2_pct": [0.55],
            "fg3m": [117],
            "fg3a": [260],
            "fg3_pct": [0.45],
            "dfgm": [14],
            "dfga": [36],
            "dfg_pct": [0.389],
        }
    ).lazy()
    defend_row = pl.DataFrame(
        {
            "player_id": [203999],
            "player_name": ["Nikola Jokic"],
            "team_id": [1610612743],
            "team_abbreviation": ["DEN"],
            "defense_category": ["Overall"],
            "season_year": ["2024-25"],
            "gp": [20],
            "g": [20],
            "freq": [0.33],
            "d_fgm": [4],
            "d_fga": [9],
            "d_fg_pct": [0.444],
            "normal_fg_pct": [0.49],
            "pct_plusminus": [-0.046],
        }
    ).lazy()
    shot_locations_team = pl.DataFrame(
        {
            "team_id": [1610612747],
            "team_name": ["Los Angeles Lakers"],
            "season_year": ["2024-25"],
            "shot_zone_basic": ["Restricted Area"],
            "shot_zone_area": ["Center(C)"],
            "shot_zone_range": ["Less Than 8 ft."],
            "fgm": [120.0],
            "fga": [180.0],
            "fg_pct": [0.667],
        }
    ).lazy()
    shot_locations_player = pl.DataFrame(
        {
            "season_year": ["2024-25"],
            "player_id": [2544],
            "player_name": ["LeBron James"],
            "team_id": [1610612747],
            "team_abbreviation": ["LAL"],
            "shot_zone_basic": ["Restricted Area"],
            "shot_zone_area": ["Center(C)"],
            "shot_zone_range": ["Less Than 8 ft."],
            "fgm": [120.0],
            "fga": [180.0],
            "fg_pct": [0.667],
        }
    ).lazy()
    player_pass = pl.DataFrame(
        {
            "player_id": [2544],
            "player_name_last_first": ["James, LeBron"],
            "team_name": ["Lakers"],
            "team_id": [1610612747],
            "team_abbreviation": ["LAL"],
            "pass_type": ["made"],
            "g": [82],
            "pass_to": [None],
            "pass_from": ["LeBron James"],
            "pass_teammate_player_id": [1627759],
            "frequency": [0.148],
            "pass": [312],
            "ast": [28],
            "fgm": [41],
            "fga": [88],
            "fg_pct": [0.466],
            "fg2m": [23],
            "fg2a": [40],
            "fg2_pct": [0.575],
            "fg3m": [18],
            "fg3a": [48],
            "fg3_pct": [0.375],
            "season_type": ["Regular Season"],
        }
    ).lazy()
    shot_defend = pl.DataFrame(
        {
            "close_def_person_id": [2544],
            "gp": [20],
            "g": [20],
            "defense_category": ["Overall"],
            "freq": [0.33],
            "d_fgm": [4],
            "d_fga": [9],
            "d_fg_pct": [0.444],
            "normal_fg_pct": [0.49],
            "pct_plusminus": [-0.046],
            "season_type": ["Regular Season"],
        }
    ).lazy()

    for transformer, table in [
        (FactLeaguePtDefendTransformer(), "fact_league_pt_defend"),
        (FactLeaguePtStatsTransformer(), "fact_league_pt_stats"),
        (FactLeaguePtTeamDefendTransformer(), "fact_league_pt_team_defend"),
        (FactLeagueTeamPtShotTransformer(), "fact_league_team_pt_shot"),
        (FactLeagueOppPtShotTransformer(), "fact_league_opp_pt_shot"),
        (FactLeaguePlayerPtShotTransformer(), "fact_league_player_pt_shot"),
    ]:
        if table == "fact_league_pt_defend":
            staging = {"stg_tracking_defense": defend_row}
        elif table == "fact_league_pt_stats":
            staging = {"stg_league_pt_stats": pt_row}
        elif table == "fact_league_pt_team_defend":
            staging = {"stg_league_pt_team_defend": pt_row}
        elif table == "fact_league_team_pt_shot":
            staging = {"stg_league_team_pt_shot": pt_row}
        elif table == "fact_league_opp_pt_shot":
            staging = {"stg_league_opp_pt_shot": pt_row}
        else:
            staging = {"stg_league_player_pt_shot": pt_row}

        result = _run(transformer, staging)
        assert result.height == 1
        _assert_output_schema(table, result)

    for transformer, table, staging in [
        (
            FactLeagueTeamShotLocationsTransformer(),
            "fact_league_team_shot_locations",
            {"stg_league_team_shot_locations": shot_locations_team},
        ),
        (
            FactLeaguePlayerShotLocationsTransformer(),
            "fact_league_player_shot_locations",
            {"stg_shot_locations": shot_locations_player},
        ),
        (
            FactPlayerPtPassTransformer(),
            "fact_player_pt_pass",
            {"stg_player_pt_pass": player_pass},
        ),
        (
            FactPlayerPtShotDefendTransformer(),
            "fact_player_pt_shot_defend",
            {"stg_player_pt_shot_defend": shot_defend},
        ),
    ]:
        result = _run(transformer, staging)
        assert result.height == 1
        _assert_output_schema(table, result)
