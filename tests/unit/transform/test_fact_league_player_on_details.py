from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.orchestrate.transformers import discover_all_transformers
from nbadb.schemas.registry import get_output_schema
from nbadb.schemas.star.fact_league_player_on_details import (
    FactLeaguePlayerOnDetailsSchema,
)
from nbadb.transform.facts.fact_league_player_on_details import (
    FactLeaguePlayerOnDetailsTransformer,
)

_PAYLOAD: dict[str, object] = {
    "group_set": "On/Off Court",
    "team_id": 1610612744,
    "team_abbreviation": "GSW",
    "team_name": "Golden State Warriors",
    "vs_player_id": 201939,
    "vs_player_name": "Stephen Curry",
    "court_status": "On",
    "gp": 70,
    "w": 48,
    "l": 22,
    "w_pct": 0.686,
    "min": 2268.0,
    "fgm": 2980.0,
    "fga": 6320.0,
    "fg_pct": 0.472,
    "fg3m": 1100.0,
    "fg3a": 2890.0,
    "fg3_pct": 0.381,
    "ftm": 1190.0,
    "fta": 1510.0,
    "ft_pct": 0.788,
    "oreb": 710.0,
    "dreb": 2230.0,
    "reb": 2940.0,
    "ast": 1920.0,
    "tov": 810.0,
    "stl": 490.0,
    "blk": 330.0,
    "blka": 290.0,
    "pf": 1310.0,
    "pfd": 1250.0,
    "pts": 8250.0,
    "plus_minus": 412.0,
    "gp_rank": 1,
    "w_rank": 2,
    "l_rank": 7,
    "w_pct_rank": 3,
    "min_rank": 5,
    "fgm_rank": 2,
    "fga_rank": 3,
    "fg_pct_rank": 8,
    "fg3m_rank": 1,
    "fg3a_rank": 1,
    "fg3_pct_rank": 6,
    "ftm_rank": 4,
    "fta_rank": 4,
    "ft_pct_rank": 9,
    "oreb_rank": 12,
    "dreb_rank": 5,
    "reb_rank": 6,
    "ast_rank": 2,
    "tov_rank": 18,
    "stl_rank": 4,
    "blk_rank": 8,
    "blka_rank": 11,
    "pf_rank": 15,
    "pfd_rank": 4,
    "pts_rank": 2,
    "plus_minus_rank": 1,
    "season_year": "2024-25",
    "season_type": "Regular Season",
}


def _frame(**overrides: object) -> pl.DataFrame:
    payload = {**_PAYLOAD, **overrides}
    return pl.DataFrame({column: [value] for column, value in payload.items()})


def _run(frame: pl.DataFrame) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        conn.register("stg_player_on_details", frame)
        transformer = FactLeaguePlayerOnDetailsTransformer()
        transformer._conn = conn
        return transformer.transform({})
    finally:
        conn.close()


def test_preserves_every_provider_and_request_scope_field() -> None:
    result = _run(_frame())

    assert result.shape == (1, 61)
    assert result.to_dicts() == [_PAYLOAD]
    validated = FactLeaguePlayerOnDetailsSchema.validate(result)
    assert validated.columns == result.columns


def test_exact_duplicate_rows_are_idempotent() -> None:
    row = _frame()
    assert _run(pl.concat([row, row])).to_dicts() == [_PAYLOAD]


def test_declared_grain_keeps_distinct_court_status_rows() -> None:
    off_court = _frame(court_status="Off", pts=7610.0, plus_minus=-19.0)

    result = _run(pl.concat([_frame(), off_court])).sort("court_status")

    assert result["court_status"].to_list() == ["Off", "On"]
    assert FactLeaguePlayerOnDetailsSchema.__consumer_metadata__["grain"] == (
        "team-vs-player-court-status-group-season-season_type"
    )


def test_distinct_payloads_at_natural_key_fail_closed() -> None:
    conflicting = _frame(pts=8251.0)

    with pytest.raises(
        duckdb.InvalidInputException,
        match="conflicting distinct payloads at natural key",
    ):
        _run(pl.concat([_frame(), conflicting]))


def test_missing_natural_key_field_fails_closed() -> None:
    with pytest.raises(
        duckdb.InvalidInputException,
        match="missing natural-key field",
    ):
        _run(_frame(court_status=""))


def test_dynamic_registries_discover_schema_and_transformer() -> None:
    assert get_output_schema("fact_league_player_on_details") is (FactLeaguePlayerOnDetailsSchema)
    matches = [
        transformer
        for transformer in discover_all_transformers(include_live=True)
        if transformer.output_table == "fact_league_player_on_details"
    ]
    assert len(matches) == 1
    assert matches[0].depends_on == ["stg_player_on_details"]
