from __future__ import annotations

import hashlib
import json

import polars as pl
import pytest

import nbadb.transform.dimensions.dim_college as dim_college_module
import nbadb.transform.dimensions.dim_shot_zone as dim_shot_zone_module
from nbadb.schemas.star.dim_college import DimCollegeSchema
from nbadb.schemas.star.dim_shot_zone import DimShotZoneSchema
from nbadb.transform.dimensions.dim_college import DimCollegeTransformer
from nbadb.transform.dimensions.dim_shot_zone import DimShotZoneTransformer

_MAX_SIGNED_BIGINT = (1 << 63) - 1


def _expected_id(parts: list[str]) -> int:
    identity = json.dumps(
        parts,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return int.from_bytes(hashlib.sha256(identity).digest()[:8], "big") % _MAX_SIGNED_BIGINT + 1


def _college_staging(names: list[str | None]) -> dict[str, pl.LazyFrame]:
    return {"stg_player_college": pl.DataFrame({"college_name": names}).lazy()}


def _shot_zone_staging(*, reverse: bool = False) -> dict[str, pl.LazyFrame]:
    frame = pl.DataFrame(
        {
            "shot_zone_basic": ["Restricted Area", "Mid-Range", "Restricted Area", None],
            "shot_zone_area": ["Center(C)", "Left Side(L)", "Center(C)", "Unknown"],
            "shot_zone_range": ["Less Than 8 ft.", "8-16 ft.", "Less Than 8 ft.", "Unknown"],
        }
    )
    return {"stg_shot_chart": (frame.reverse() if reverse else frame).lazy()}


def test_college_ids_are_reproducible_positive_bigints_for_exact_names() -> None:
    first = DimCollegeTransformer().transform(_college_staging(["UNC", "Duke", "UNC", None]))
    second = DimCollegeTransformer().transform(_college_staging([None, "UNC", "Duke", "UNC"]))

    assert first.to_dicts() == second.to_dicts()
    assert first.to_dicts() == [
        {"college_id": _expected_id(["Duke"]), "college_name": "Duke"},
        {"college_id": _expected_id(["UNC"]), "college_name": "UNC"},
    ]
    assert first["college_id"].dtype == pl.Int64
    assert first["college_id"].min() > 0
    assert DimCollegeSchema.validate(first).to_dicts() == first.to_dicts()
    assert list(DimCollegeSchema.to_schema().columns) == first.columns


def test_college_transform_rejects_surrogate_collisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dim_college_module, "_stable_college_id", lambda _value: 1)

    with pytest.raises(ValueError, match="college surrogate collision"):
        DimCollegeTransformer().transform(_college_staging(["Duke", "UNC"]))


def test_shot_zone_ids_bind_exact_nonnull_tuple_and_are_reproducible() -> None:
    first = DimShotZoneTransformer().transform(_shot_zone_staging())
    second = DimShotZoneTransformer().transform(_shot_zone_staging(reverse=True))

    assert first.to_dicts() == second.to_dicts()
    assert first.to_dicts() == [
        {
            "zone_id": _expected_id(["Mid-Range", "Left Side(L)", "8-16 ft."]),
            "shot_zone_basic": "Mid-Range",
            "shot_zone_area": "Left Side(L)",
            "shot_zone_range": "8-16 ft.",
        },
        {
            "zone_id": _expected_id(["Restricted Area", "Center(C)", "Less Than 8 ft."]),
            "shot_zone_basic": "Restricted Area",
            "shot_zone_area": "Center(C)",
            "shot_zone_range": "Less Than 8 ft.",
        },
    ]
    assert first["zone_id"].dtype == pl.Int64
    assert first["zone_id"].min() > 0
    assert DimShotZoneSchema.validate(first).to_dicts() == first.to_dicts()
    assert list(DimShotZoneSchema.to_schema().columns) == first.columns


def test_shot_zone_transform_rejects_surrogate_collisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dim_shot_zone_module, "_stable_shot_zone_id", lambda _value: 1)

    with pytest.raises(ValueError, match="shot-zone surrogate collision"):
        DimShotZoneTransformer().transform(_shot_zone_staging())
