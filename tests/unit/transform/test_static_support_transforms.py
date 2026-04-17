from __future__ import annotations

import duckdb
import polars as pl

from nbadb.transform.facts.fact_static_support import (
    FactStaticPlayersTransformer,
    FactStaticTeamsTransformer,
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
            }
        ).lazy(),
    }

    result = _run(FactStaticTeamsTransformer(), staging)

    assert result.shape == (1, 7)
    validated = _star_schema_map()["fact_static_teams"].validate(result)
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
