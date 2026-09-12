from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.schemas.star.bridge_game_official import BridgeGameOfficialSchema
from nbadb.transform.facts.bridge_game_official import BridgeGameOfficialTransformer

_STAGING_SCHEMA = {
    "game_id": pl.String,
    "official_id": pl.Int64,
    "first_name": pl.String,
    "last_name": pl.String,
    "jersey_number": pl.String,
}


def _officials(rows: list[tuple[object, ...]]) -> pl.DataFrame:
    return pl.DataFrame(rows, schema=_STAGING_SCHEMA, orient="row")


def _run(frame: pl.DataFrame) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        conn.register("stg_officials", frame)
        transformer = BridgeGameOfficialTransformer()
        transformer._conn = conn
        return transformer.transform({"stg_officials": frame.lazy()})
    finally:
        conn.close()


def test_game_official_collapses_exact_duplicates_and_resolves_nullable_jersey() -> None:
    result = _run(
        _officials(
            [
                ("0022400001", 101, "A", "One", "12"),
                ("0022400001", 101, "A", "One", "12"),
                ("0022400001", 102, "B", "Two", None),
                ("0022400001", 102, "B", "Two", None),
                ("0022400001", 103, "C", "Three", None),
                ("0022400001", 103, "C", "Three", "34"),
            ]
        )
    )

    assert result.columns == ["game_id", "official_id", "jersey_num"]
    assert result.to_dicts() == [
        {"game_id": "0022400001", "official_id": 101, "jersey_num": "12"},
        {"game_id": "0022400001", "official_id": 102, "jersey_num": None},
        {"game_id": "0022400001", "official_id": 103, "jersey_num": "34"},
    ]
    assert result.unique(subset=["game_id", "official_id"]).height == result.height
    assert BridgeGameOfficialSchema.validate(result).to_dicts() == result.to_dicts()
    assert list(BridgeGameOfficialSchema.to_schema().columns) == result.columns


def test_game_official_preserves_same_official_across_games_and_multiple_game_officials() -> None:
    result = _run(
        _officials(
            [
                ("0022400001", 101, "A", "One", "12"),
                ("0022400001", 102, "B", "Two", "34"),
                ("0022400002", 101, "A", "One", "12"),
            ]
        )
    )

    assert result.select("game_id", "official_id").rows() == [
        ("0022400001", 101),
        ("0022400001", 102),
        ("0022400002", 101),
    ]


def test_game_official_omits_rows_without_a_positive_official_identity() -> None:
    result = _run(
        _officials(
            [
                ("0022400001", 101, "A", "One", "12"),
                ("0022400001", None, None, None, None),
                ("0022400001", 0, None, None, None),
            ]
        )
    )

    assert result.select("official_id").to_series().to_list() == [101]


def test_game_official_mutated_jersey_conflict_fails_closed() -> None:
    with pytest.raises(duckdb.Error, match="conflicting game-official jersey numbers"):
        _run(
            _officials(
                [
                    ("0022400001", 101, "A", "One", "12"),
                    ("0022400001", 101, "A", "One", "13"),
                ]
            )
        )


def test_game_official_contract_identity() -> None:
    assert BridgeGameOfficialTransformer.output_table == "bridge_game_official"
    assert BridgeGameOfficialTransformer.depends_on == ["stg_officials"]
