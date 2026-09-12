from __future__ import annotations

import duckdb
import polars as pl

from nbadb.transform.facts.fact_static_support import (
    FactStaticPlayersTransformer,
    FactStaticTeamsTransformer,
    FactStaticWnbaPlayersTransformer,
    FactStaticWnbaTeamsTransformer,
)
from nbadb.transform.facts.fact_team_streak_finder import FactTeamStreakFinderTransformer
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


def test_static_support_star_schemas_are_discovered() -> None:
    assert {
        "fact_static_players",
        "fact_static_teams",
        "fact_static_wnba_players",
        "fact_static_wnba_teams",
        "fact_team_streak_finder",
    }.issubset(_star_schema_map())


def test_fact_static_players_transform_passthrough_validates() -> None:
    staging = {
        "stg_static_players": pl.DataFrame(
            {
                "id": [2544],
                "full_name": ["LeBron James"],
                "first_name": ["LeBron"],
                "last_name": ["James"],
                "is_active": [True],
            }
        ).lazy(),
    }

    result = _run(FactStaticPlayersTransformer(), staging)

    assert result.shape == (1, 5)
    validated = _star_schema_map()["fact_static_players"].validate(result)
    assert isinstance(validated, pl.DataFrame)


def test_fact_static_teams_transform_passthrough_validates() -> None:
    staging = {
        "stg_static_teams": pl.DataFrame(
            {
                "id": [1610612747],
                "full_name": ["Los Angeles Lakers"],
                "abbreviation": ["LAL"],
                "nickname": ["Lakers"],
                "city": ["Los Angeles"],
                "state": ["California"],
                "year_founded": [1947],
                "championship_years_json": ["[1949,1950]"],
            }
        ).lazy(),
    }

    result = _run(FactStaticTeamsTransformer(), staging)

    assert result.shape == (1, 8)
    assert result["championship_years_json"].to_list() == ["[1949,1950]"]
    validated = _star_schema_map()["fact_static_teams"].validate(result)
    assert isinstance(validated, pl.DataFrame)


def test_fact_static_wnba_players_transform_passthrough_validates() -> None:
    staging = {
        "stg_static_wnba_players": pl.DataFrame(
            {
                "id": [203025],
                "last_name": ["Abdi"],
                "first_name": ["Farhiya"],
                "full_name": ["Farhiya Abdi"],
                "is_active": [False],
                "league": ["WNBA"],
            }
        ).lazy(),
    }

    result = _run(FactStaticWnbaPlayersTransformer(), staging)

    assert result.shape == (1, 6)
    assert result.columns == [
        "id",
        "last_name",
        "first_name",
        "full_name",
        "is_active",
        "league",
    ]
    validated = _star_schema_map()["fact_static_wnba_players"].validate(result)
    assert isinstance(validated, pl.DataFrame)


def test_fact_static_wnba_teams_transform_passthrough_validates() -> None:
    staging = {
        "stg_static_wnba_teams": pl.DataFrame(
            {
                "id": [1611661328],
                "abbreviation": ["SEA"],
                "nickname": ["Storm"],
                "year_founded": [2000],
                "city": ["Seattle"],
                "full_name": ["Seattle Storm"],
                "state": ["Washington"],
                "championship_years_json": ["[2004,2010,2018,2020]"],
                "league": ["WNBA"],
            }
        ).lazy(),
    }

    result = _run(FactStaticWnbaTeamsTransformer(), staging)

    assert result.shape == (1, 9)
    assert result["championship_years_json"].to_list() == ["[2004,2010,2018,2020]"]
    assert result["league"].to_list() == ["WNBA"]
    validated = _star_schema_map()["fact_static_wnba_teams"].validate(result)
    assert isinstance(validated, pl.DataFrame)


def test_fact_team_streak_finder_transform_passthrough_validates() -> None:
    staging = {
        "stg_team_streak_finder": pl.DataFrame(
            {
                "team_name": ["Los Angeles Lakers"],
                "team_id": [1610612747],
                "gamestreak": ["5 WINS"],
                "startdate": ["2024-01-10"],
                "enddate": ["2024-01-20"],
                "activestreak": ["Y"],
                "numseasons": [1],
                "lastseason": ["2024-25"],
                "firstseason": ["2024-25"],
                "abbreviation": ["LAL"],
            }
        ).lazy(),
    }

    result = _run(FactTeamStreakFinderTransformer(), staging)

    assert result.shape == (1, 10)
    validated = _star_schema_map()["fact_team_streak_finder"].validate(result)
    assert isinstance(validated, pl.DataFrame)
