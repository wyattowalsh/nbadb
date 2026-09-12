from __future__ import annotations

import hashlib
import json

import polars as pl
import pytest

import nbadb.transform.dimensions.dim_arena as dim_arena_module
from nbadb.schemas.star.dim_arena import DimArenaSchema
from nbadb.schemas.star.dim_official import DimOfficialSchema
from nbadb.schemas.star.dim_play_event_type import DimPlayEventTypeSchema
from nbadb.schemas.star.dim_season import DimSeasonSchema
from nbadb.transform.dimensions.dim_arena import DimArenaTransformer
from nbadb.transform.dimensions.dim_official import DimOfficialTransformer
from nbadb.transform.dimensions.dim_play_event_type import DimPlayEventTypeTransformer
from nbadb.transform.dimensions.dim_season import DimSeasonTransformer


def _arena_staging() -> dict[str, pl.LazyFrame]:
    return {
        "stg_schedule": pl.DataFrame(
            {
                "arena_name": ["Arena One", "Arena Two"],
                "arena_city": ["City A", "City B"],
            }
        ).lazy(),
        "stg_league_game_log": pl.DataFrame(
            {
                "arena_name": ["Arena Two", "Arena Three"],
                "arena_city": ["City B", "City C"],
            }
        ).lazy(),
        "stg_arena_info": pl.DataFrame(
            {
                "arena_name": ["Arena One", "Arena Two", "Arena Three"],
                "arena_city": ["City A", "City B", "City C"],
                "arena_state": ["AA", "BB", None],
                "arena_country": ["US", "CA", None],
                "arena_timezone": ["ET", "PT", None],
            }
        ).lazy(),
    }


def _expected_arena_id(name: str, city: str) -> int:
    identity = json.dumps(
        [name, city],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return int.from_bytes(hashlib.sha256(identity).digest()[:8], "big") % ((1 << 63) - 1) + 1


def test_arena_transform_matches_public_schema_and_has_reproducible_ids() -> None:
    first = DimArenaTransformer().transform(_arena_staging())
    reversed_staging = {
        name: frame.collect().reverse().lazy() for name, frame in _arena_staging().items()
    }
    second = DimArenaTransformer().transform(reversed_staging)

    assert first.columns == ["arena_id", "arena_name", "city", "state", "country", "timezone"]
    assert first.to_dicts() == second.to_dicts()
    assert first["arena_id"].to_list() == [
        _expected_arena_id("Arena One", "City A"),
        _expected_arena_id("Arena Three", "City C"),
        _expected_arena_id("Arena Two", "City B"),
    ]
    assert first["arena_id"].dtype == pl.Int64
    assert DimArenaSchema.validate(first).to_dicts() == first.to_dicts()
    assert list(DimArenaSchema.to_schema().columns) == first.columns


def test_arena_transform_rejects_surrogate_collisions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dim_arena_module, "_stable_arena_id", lambda _value: 1)

    with pytest.raises(ValueError, match="surrogate collision"):
        DimArenaTransformer().transform(_arena_staging())


def test_official_transform_renames_staging_jersey_number_to_public_jersey_num() -> None:
    staging = {
        "stg_officials": pl.DataFrame(
            {
                "official_id": [101, 102, 101],
                "first_name": ["First", "Second", "First"],
                "last_name": ["Official", "Referee", "Official"],
                "jersey_number": ["12", "34", "12"],
            }
        ).lazy()
    }

    result = DimOfficialTransformer().transform(staging)

    assert result.columns == ["official_id", "first_name", "last_name", "jersey_num"]
    assert result.sort("official_id")["jersey_num"].to_list() == ["12", "34"]
    assert DimOfficialSchema.validate(result).to_dicts() == result.to_dicts()
    assert list(DimOfficialSchema.to_schema().columns) == result.columns


def test_play_event_type_schema_exposes_only_executable_lookup_columns() -> None:
    result = DimPlayEventTypeTransformer().transform({})

    assert result.shape == (14, 2)
    assert result.columns == ["event_type_id", "event_type_name"]
    assert "event_category" not in DimPlayEventTypeSchema.to_schema().columns
    assert DimPlayEventTypeSchema.validate(result).to_dicts() == result.to_dicts()
    assert result.row(0) == (1, "made_shot")
    assert result.row(-1) == (14, "unknown")


def test_season_schema_exposes_only_dates_derived_from_game_log() -> None:
    staging = {
        "stg_league_game_log": pl.DataFrame(
            {
                "season_year": ["2023-24", "2024-25", "2024-25", "2023-24"],
                "game_date": ["2023-10-24", "2025-04-13", "2024-10-22", "2024-04-14"],
            }
        ).lazy()
    }

    result = DimSeasonTransformer().transform(staging)

    assert result.columns == ["season_year", "start_date", "end_date"]
    assert result.to_dicts() == [
        {
            "season_year": "2023-24",
            "start_date": "2023-10-24",
            "end_date": "2024-04-14",
        },
        {
            "season_year": "2024-25",
            "start_date": "2024-10-22",
            "end_date": "2025-04-13",
        },
    ]
    assert "all_star_date" not in DimSeasonSchema.to_schema().columns
    assert "playoff_start_date" not in DimSeasonSchema.to_schema().columns
    assert DimSeasonSchema.validate(result).to_dicts() == result.to_dicts()
