from __future__ import annotations

import polars as pl
import pytest
from pandera import errors as pa_errors

from nbadb.contracts.public_value_types import (
    PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
    ExpectedValueUnitV1,
    ValueRepresentationAssignmentV1,
)
from nbadb.schemas.raw.nba_api_value_representation import (
    RawNbaApiValueRepresentationSchema,
)
from nbadb.schemas.registry import _raw_schema_registry

_RAW_BUNDLE_A = "a" * 64
_RAW_BUNDLE_B = "b" * 64


def _assignment(
    *,
    raw_authority_bundle_sha256: str = _RAW_BUNDLE_A,
    unit_ordinal: int = 0,
    occurrence_ordinal: int = 0,
) -> ValueRepresentationAssignmentV1:
    unit = ExpectedValueUnitV1.build(
        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
        unit_ordinal=unit_ordinal,
        observation_sha256="1" * 64,
        observation_ordinal=0,
        unit_kind="result_occurrence",
        occurrence_sha256=f"{occurrence_ordinal + 2:x}" * 64,
        occurrence_ordinal=occurrence_ordinal,
    )
    return ValueRepresentationAssignmentV1.build(
        expected_unit=unit,
        source_input_kind="parser_input_body",
        representation_kind="rectangular_result_cells_v1",
    )


def test_assignment_row_validates_with_exact_order_and_registry_name() -> None:
    row = _assignment().to_row()
    frame = pl.DataFrame([row], infer_schema_length=None)
    validated = RawNbaApiValueRepresentationSchema.validate(frame)

    assert validated.to_dicts() == [row]
    assert tuple(validated.columns) == tuple(row)
    assert tuple(RawNbaApiValueRepresentationSchema.to_schema().columns) == tuple(row)
    _raw_schema_registry.cache_clear()
    assert (
        _raw_schema_registry()["raw_nba_api_value_representation"]
        is RawNbaApiValueRepresentationSchema
    )


def test_typed_zero_row_assignment_frame_is_schema_valid() -> None:
    empty = pl.DataFrame(
        schema={
            "schema_version": pl.Int64,
            "assignment_sha256": pl.String,
            "raw_authority_bundle_sha256": pl.String,
            "unit_sha256": pl.String,
            "unit_ordinal": pl.Int64,
            "source_input_kind": pl.String,
            "representation_kind": pl.String,
        }
    )
    assert RawNbaApiValueRepresentationSchema.validate(empty).height == 0


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: {**row, "schema_version": True},
        lambda row: {**row, "unit_ordinal": True},
        lambda row: {**row, "assignment_sha256": "0" * 64},
        lambda row: {**row, "raw_authority_bundle_sha256": _RAW_BUNDLE_B},
        lambda row: {**row, "source_input_kind": "private_cache"},
        lambda row: {**row, "representation_kind": "compatibility_projection_v0"},
        lambda row: {**row, "extra": "foreign"},
        lambda row: {key: value for key, value in row.items() if key != "unit_sha256"},
        lambda row: dict(reversed(row.items())),
    ],
)
def test_assignment_schema_rejects_hostile_or_noncanonical_rows(mutation: object) -> None:
    row = _assignment().to_row()
    changed = mutation(row)  # type: ignore[operator]
    with pytest.raises((pa_errors.SchemaError, pa_errors.SchemaErrors)):
        RawNbaApiValueRepresentationSchema.validate(
            pl.DataFrame([changed], infer_schema_length=None)
        )


def test_assignment_schema_columns_remain_the_exact_public_v1_contract() -> None:
    assert PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION == 1
    assert tuple(RawNbaApiValueRepresentationSchema.to_schema().columns) == (
        "schema_version",
        "assignment_sha256",
        "raw_authority_bundle_sha256",
        "unit_sha256",
        "unit_ordinal",
        "source_input_kind",
        "representation_kind",
    )


def test_assignment_table_rejects_reversed_or_gapped_unit_order() -> None:
    first_unit = ExpectedValueUnitV1.build(
        raw_authority_bundle_sha256=_RAW_BUNDLE_A,
        unit_ordinal=0,
        observation_sha256="1" * 64,
        observation_ordinal=0,
        unit_kind="result_occurrence",
        occurrence_sha256="2" * 64,
        occurrence_ordinal=0,
    )
    second_unit = ExpectedValueUnitV1.build(
        raw_authority_bundle_sha256=_RAW_BUNDLE_A,
        unit_ordinal=1,
        observation_sha256="1" * 64,
        observation_ordinal=0,
        unit_kind="result_occurrence",
        occurrence_sha256="3" * 64,
        occurrence_ordinal=1,
    )
    assignments = [
        ValueRepresentationAssignmentV1.build(
            expected_unit=unit,
            source_input_kind="parser_input_body",
            representation_kind="rectangular_result_cells_v1",
        ).to_row()
        for unit in (first_unit, second_unit)
    ]
    with pytest.raises((pa_errors.SchemaError, pa_errors.SchemaErrors)):
        RawNbaApiValueRepresentationSchema.validate(
            pl.DataFrame(list(reversed(assignments)), infer_schema_length=None)
        )
    with pytest.raises((pa_errors.SchemaError, pa_errors.SchemaErrors)):
        RawNbaApiValueRepresentationSchema.validate(
            pl.DataFrame([assignments[1]], infer_schema_length=None)
        )


def test_assignment_table_accepts_bundle_local_ordinals_even_when_interleaved() -> None:
    first_bundle = [
        _assignment(unit_ordinal=ordinal, occurrence_ordinal=ordinal).to_row()
        for ordinal in range(2)
    ]
    second_bundle = [
        _assignment(
            raw_authority_bundle_sha256=_RAW_BUNDLE_B,
            unit_ordinal=ordinal,
            occurrence_ordinal=ordinal,
        ).to_row()
        for ordinal in range(2)
    ]

    rows = [first_bundle[0], second_bundle[0], first_bundle[1], second_bundle[1]]
    validated = RawNbaApiValueRepresentationSchema.validate(
        pl.DataFrame(rows, infer_schema_length=None)
    )
    assert validated.to_dicts() == rows


@pytest.mark.parametrize(
    "rows",
    [
        [_assignment(unit_ordinal=1, occurrence_ordinal=1).to_row()],
        [
            _assignment().to_row(),
            _assignment().to_row(),
        ],
        [
            _assignment(unit_ordinal=1, occurrence_ordinal=1).to_row(),
            _assignment().to_row(),
        ],
    ],
)
def test_assignment_table_rejects_bundle_local_gaps_duplicates_and_reorder(
    rows: list[dict[str, object]],
) -> None:
    with pytest.raises((pa_errors.SchemaError, pa_errors.SchemaErrors)):
        RawNbaApiValueRepresentationSchema.validate(pl.DataFrame(rows, infer_schema_length=None))


def test_assignment_table_rejects_cross_bundle_reseal_and_global_digest_reuse() -> None:
    first = _assignment().to_row()
    cross_scope = {**first, "raw_authority_bundle_sha256": _RAW_BUNDLE_B}
    with pytest.raises((pa_errors.SchemaError, pa_errors.SchemaErrors)):
        RawNbaApiValueRepresentationSchema.validate(
            pl.DataFrame([cross_scope], infer_schema_length=None)
        )

    second = _assignment(raw_authority_bundle_sha256=_RAW_BUNDLE_B).to_row()
    second["assignment_sha256"] = first["assignment_sha256"]
    with pytest.raises((pa_errors.SchemaError, pa_errors.SchemaErrors)):
        RawNbaApiValueRepresentationSchema.validate(
            pl.DataFrame([first, second], infer_schema_length=None)
        )
