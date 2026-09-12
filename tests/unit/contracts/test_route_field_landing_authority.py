from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from typing import cast

import polars as pl
import pytest
from pandera import errors as pa_errors

from nbadb.contracts.public_value_types import (
    ExpectedValueUnitV1,
    ValueRepresentationAssignmentV1,
)
from nbadb.contracts.route_field_landing_authority import (
    RAW_NBA_API_ROUTE_FIELD_LANDING_COLUMNS,
    RawNbaApiRouteFieldLandingV1,
    RouteFieldLandingAuthorityError,
)
from nbadb.schemas.raw.nba_api_route_field_landing import (
    RawNbaApiRouteFieldLandingSchema,
)
from nbadb.schemas.registry import _raw_schema_registry

_RAW_BUNDLE_A = "3" * 64
_RAW_BUNDLE_B = "8" * 64


def _reseal_landing_row(row: dict[str, object]) -> dict[str, object]:
    identity = {
        "kind": "raw_nba_api_route_field_landing_v1",
        **{key: value for key, value in row.items() if key != "landing_field_sha256"},
    }
    row["landing_field_sha256"] = hashlib.sha256(
        json.dumps(
            identity,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return row


def _result_unit(
    *,
    raw_authority_bundle_sha256: str = _RAW_BUNDLE_A,
    unit_ordinal: int = 0,
    occurrence_ordinal: int = 0,
) -> ExpectedValueUnitV1:
    return ExpectedValueUnitV1.build(
        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
        unit_ordinal=unit_ordinal,
        observation_sha256="1" * 64,
        observation_ordinal=0,
        unit_kind="result_occurrence",
        occurrence_sha256="2" * 64,
        occurrence_ordinal=occurrence_ordinal,
    )


def _result_row(
    *,
    landing_field_ordinal: int = 0,
    field_ordinal: int = 0,
    unit_ordinal: int = 0,
    occurrence_ordinal: int = 0,
    raw_authority_bundle_sha256: str = _RAW_BUNDLE_A,
) -> RawNbaApiRouteFieldLandingV1:
    unit = _result_unit(
        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
        unit_ordinal=unit_ordinal,
        occurrence_ordinal=occurrence_ordinal,
    )
    assignment = ValueRepresentationAssignmentV1.build(
        expected_unit=unit,
        source_input_kind="parser_input_body",
        representation_kind="rectangular_result_cells_v1",
    )
    return RawNbaApiRouteFieldLandingV1.build(
        landing_field_ordinal=landing_field_ordinal,
        route_receipt_ordinal=0,
        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
        route_landing_receipt_sha256="4" * 64,
        raw_route_landing_sha256="5" * 64,
        observation_sha256=unit.observation_sha256,
        route_ordinal=0,
        route_id="endpoint:stg_table:0",
        staging_key="stg_table",
        unit_sha256=unit.unit_sha256,
        unit_ordinal=unit.unit_ordinal,
        unit_kind=unit.unit_kind,
        occurrence_sha256=unit.occurrence_sha256,
        occurrence_ordinal=unit.occurrence_ordinal,
        assignment_sha256=assignment.assignment_sha256,
        source_input_kind=assignment.source_input_kind,
        representation_kind=assignment.representation_kind,
        row_kind="field_binding",
        field_ordinal=field_ordinal,
        field_name=f"FIELD_{field_ordinal}",
        field_authority_sha256="6" * 64,
        field_origin="provider_bound",
        logical_type_sha256="7" * 64,
    )


def _route_only_row() -> RawNbaApiRouteFieldLandingV1:
    unit = ExpectedValueUnitV1.build(
        raw_authority_bundle_sha256=_RAW_BUNDLE_A,
        unit_ordinal=0,
        observation_sha256="1" * 64,
        observation_ordinal=0,
        unit_kind="response_fixed_zero",
    )
    assignment = ValueRepresentationAssignmentV1.build(
        expected_unit=unit,
        source_input_kind="declared_bodyless_packet",
        representation_kind="response_fixed_zero_v1",
    )
    return RawNbaApiRouteFieldLandingV1.build(
        landing_field_ordinal=0,
        route_receipt_ordinal=0,
        raw_authority_bundle_sha256=_RAW_BUNDLE_A,
        route_landing_receipt_sha256="4" * 64,
        raw_route_landing_sha256="5" * 64,
        observation_sha256=unit.observation_sha256,
        route_ordinal=0,
        route_id="static:stg_table:0",
        staging_key="stg_table",
        unit_sha256=unit.unit_sha256,
        unit_ordinal=unit.unit_ordinal,
        unit_kind=unit.unit_kind,
        occurrence_sha256=None,
        occurrence_ordinal=None,
        assignment_sha256=assignment.assignment_sha256,
        source_input_kind=assignment.source_input_kind,
        representation_kind=assignment.representation_kind,
        row_kind="route_only",
        field_ordinal=None,
        field_name=None,
        field_authority_sha256=None,
        field_origin=None,
        logical_type_sha256=None,
    )


def test_field_binding_and_zero_field_sentinel_roundtrip_exactly() -> None:
    rows = [_result_row().to_row(), _route_only_row().to_row()]
    assert tuple(rows[0]) == RAW_NBA_API_ROUTE_FIELD_LANDING_COLUMNS
    assert [RawNbaApiRouteFieldLandingV1.from_row(row).to_row() for row in rows] == rows
    assert all(
        b"canonical_json" not in RawNbaApiRouteFieldLandingV1.from_row(row).canonical_bytes()
        for row in rows
    )


def test_strict_schema_validates_ordered_rows_and_registry_name() -> None:
    rows = [_result_row().to_row(), _result_row(landing_field_ordinal=1, field_ordinal=1).to_row()]
    validated = RawNbaApiRouteFieldLandingSchema.validate(
        pl.DataFrame(rows, infer_schema_length=None)
    )
    assert validated.to_dicts() == rows
    assert tuple(validated.columns) == RAW_NBA_API_ROUTE_FIELD_LANDING_COLUMNS
    _raw_schema_registry.cache_clear()
    assert (
        _raw_schema_registry()["raw_nba_api_route_field_landing"]
        is RawNbaApiRouteFieldLandingSchema
    )


def test_typed_zero_row_route_field_frame_is_valid() -> None:
    nullable_strings = {
        "occurrence_sha256",
        "field_name",
        "field_authority_sha256",
        "field_origin",
        "logical_type_sha256",
    }
    nullable_integers = {"occurrence_ordinal", "field_ordinal"}
    integer_columns = {
        "schema_version",
        "landing_field_ordinal",
        "route_receipt_ordinal",
        "route_ordinal",
        "unit_ordinal",
        *nullable_integers,
    }
    empty = pl.DataFrame(
        schema={
            column: pl.Int64 if column in integer_columns else pl.String
            for column in RAW_NBA_API_ROUTE_FIELD_LANDING_COLUMNS
        }
    )
    assert nullable_strings
    assert RawNbaApiRouteFieldLandingSchema.validate(empty).height == 0


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: {**row, "schema_version": True},
        lambda row: {**row, "landing_field_ordinal": True},
        lambda row: {**row, "landing_field_sha256": "0" * 64},
        lambda row: {**row, "unit_kind": "response_fixed_zero"},
        lambda row: {**row, "occurrence_sha256": None},
        lambda row: {**row, "occurrence_ordinal": None},
        lambda row: {**row, "assignment_sha256": "8" * 64},
        lambda row: {**row, "representation_kind": "response_fixed_zero_v1"},
        lambda row: {**row, "source_input_kind": "private_cache"},
        lambda row: {**row, "row_kind": "route_only"},
        lambda row: {**row, "field_name": "/Users/private-name"},
        lambda row: {**row, "field_name": "authToken"},
        lambda row: {**row, "field_name": "ghp_12345678901234567890"},
        lambda row: {**row, "field_origin": "unknown"},
        lambda row: {**row, "extra": "forbidden-value-column"},
        lambda row: {key: value for key, value in row.items() if key != "unit_sha256"},
        lambda row: dict(reversed(row.items())),
    ],
)
def test_row_replay_rejects_mutated_or_forbidden_shapes(mutation: object) -> None:
    changed = mutation(_result_row().to_row())  # type: ignore[operator]
    with pytest.raises(RouteFieldLandingAuthorityError):
        RawNbaApiRouteFieldLandingV1.from_row(changed)


@pytest.mark.parametrize(
    "changes",
    [
        {"field_name": None},
        {"field_authority_sha256": None},
        {"logical_type_sha256": None},
        {"row_kind": "route_only"},
        {"occurrence_sha256": None},
        {"occurrence_ordinal": None},
    ],
)
def test_dataclass_reseals_do_not_bypass_field_or_occurrence_algebra(
    changes: dict[str, object],
) -> None:
    with pytest.raises(RouteFieldLandingAuthorityError):
        replace(_result_row(), landing_field_sha256="0" * 64, **changes)


def test_schema_rejects_reordered_or_noncontiguous_rows() -> None:
    second = _result_row(landing_field_ordinal=1, field_ordinal=1).to_row()
    first = _result_row().to_row()
    with pytest.raises((pa_errors.SchemaError, pa_errors.SchemaErrors)):
        RawNbaApiRouteFieldLandingSchema.validate(
            pl.DataFrame([second, first], infer_schema_length=None)
        )
    with pytest.raises((pa_errors.SchemaError, pa_errors.SchemaErrors)):
        RawNbaApiRouteFieldLandingSchema.validate(
            pl.DataFrame([first, first], infer_schema_length=None)
        )


def test_schema_accepts_bundle_local_landing_ordinals() -> None:
    first_bundle = [
        _result_row(landing_field_ordinal=ordinal, field_ordinal=ordinal).to_row()
        for ordinal in range(2)
    ]
    second_bundle = [
        _result_row(
            raw_authority_bundle_sha256=_RAW_BUNDLE_B,
            landing_field_ordinal=ordinal,
            field_ordinal=ordinal,
        ).to_row()
        for ordinal in range(2)
    ]
    rows = [first_bundle[0], second_bundle[0], first_bundle[1], second_bundle[1]]

    validated = RawNbaApiRouteFieldLandingSchema.validate(
        pl.DataFrame(rows, infer_schema_length=None)
    )
    assert validated.to_dicts() == rows


def test_schema_rejects_bundle_local_gap_and_reorder() -> None:
    first = _result_row().to_row()
    first_next = _result_row(landing_field_ordinal=1, field_ordinal=1).to_row()

    for rows in (
        [first_next],
        [first_next, first],
    ):
        with pytest.raises((pa_errors.SchemaError, pa_errors.SchemaErrors)):
            RawNbaApiRouteFieldLandingSchema.validate(pl.DataFrame(rows, infer_schema_length=None))


def test_route_row_rejects_cross_bundle_assignment_reseal() -> None:
    original = _result_row()
    cross_scope = original.to_row()
    cross_scope["raw_authority_bundle_sha256"] = _RAW_BUNDLE_B
    _reseal_landing_row(cross_scope)

    with pytest.raises(RouteFieldLandingAuthorityError, match="assignment binding"):
        replace(
            original,
            raw_authority_bundle_sha256=_RAW_BUNDLE_B,
            landing_field_sha256=cast("str", cross_scope["landing_field_sha256"]),
        )
    with pytest.raises(RouteFieldLandingAuthorityError):
        RawNbaApiRouteFieldLandingV1.from_row(cross_scope)
    with pytest.raises((pa_errors.SchemaError, pa_errors.SchemaErrors)):
        RawNbaApiRouteFieldLandingSchema.validate(
            pl.DataFrame([cross_scope], infer_schema_length=None)
        )


def test_public_schema_contract_is_exactly_the_value_free_25_columns() -> None:
    assert tuple(RawNbaApiRouteFieldLandingSchema.to_schema().columns) == (
        RAW_NBA_API_ROUTE_FIELD_LANDING_COLUMNS
    )
    forbidden = {
        "canonical_json",
        "identity_json",
        "value_receipts",
        "conditional_row_receipts",
        "values_sha256",
        "conditional_rows_sha256",
    }
    assert forbidden.isdisjoint(RAW_NBA_API_ROUTE_FIELD_LANDING_COLUMNS)


def test_row_kind_rejects_hostile_string_subclasses_before_sealing() -> None:
    class HostileStr(str):
        pass

    row = _result_row().to_row()
    row["row_kind"] = HostileStr("field_binding")
    with pytest.raises(RouteFieldLandingAuthorityError):
        RawNbaApiRouteFieldLandingV1.from_row(row)

    with pytest.raises(RouteFieldLandingAuthorityError):
        RawNbaApiRouteFieldLandingV1.build(
            landing_field_ordinal=0,
            route_receipt_ordinal=0,
            raw_authority_bundle_sha256=_RAW_BUNDLE_A,
            route_landing_receipt_sha256="4" * 64,
            raw_route_landing_sha256="5" * 64,
            observation_sha256="1" * 64,
            route_ordinal=0,
            route_id="endpoint:stg_table:0",
            staging_key="stg_table",
            unit_sha256=cast("str", row["unit_sha256"]),
            unit_ordinal=0,
            unit_kind="result_occurrence",
            occurrence_sha256="2" * 64,
            occurrence_ordinal=0,
            assignment_sha256=cast("str", row["assignment_sha256"]),
            source_input_kind="parser_input_body",
            representation_kind="rectangular_result_cells_v1",
            row_kind=HostileStr("field_binding"),
            field_ordinal=0,
            field_name="FIELD_0",
            field_authority_sha256="6" * 64,
            field_origin="provider_bound",
            logical_type_sha256="7" * 64,
        )


def test_route_unit_ordinal_matches_the_central_public_value_bound() -> None:
    assert _result_row(unit_ordinal=99_999).unit_ordinal == 99_999
    with pytest.raises(RouteFieldLandingAuthorityError, match="expected-unit ordinal"):
        replace(_result_row(), unit_ordinal=100_000)

    row = _result_row().to_row()
    row["unit_ordinal"] = 100_000
    with pytest.raises((pa_errors.SchemaError, pa_errors.SchemaErrors)):
        RawNbaApiRouteFieldLandingSchema.validate(pl.DataFrame([row], infer_schema_length=None))


def test_route_occurrence_ordinal_matches_the_central_public_value_bound() -> None:
    accepted = _result_row(occurrence_ordinal=99_999)
    assert accepted.occurrence_ordinal == 99_999
    assert RawNbaApiRouteFieldLandingV1.from_row(accepted.to_row()) == accepted

    with pytest.raises(RouteFieldLandingAuthorityError, match="occurrence ordinal"):
        replace(_result_row(), occurrence_ordinal=100_000)

    invalid_row = _result_row().to_row()
    invalid_row["occurrence_ordinal"] = 100_000
    with pytest.raises(RouteFieldLandingAuthorityError):
        RawNbaApiRouteFieldLandingV1.from_row(invalid_row)
    with pytest.raises((pa_errors.SchemaError, pa_errors.SchemaErrors)):
        RawNbaApiRouteFieldLandingSchema.validate(
            pl.DataFrame([invalid_row], infer_schema_length=None)
        )


def test_route_field_ordinal_matches_the_landing_receipt_bound() -> None:
    assert _result_row(field_ordinal=4_095).field_ordinal == 4_095
    with pytest.raises(RouteFieldLandingAuthorityError):
        _result_row(field_ordinal=4_096)

    row = _result_row().to_row()
    row["field_ordinal"] = 4_096
    with pytest.raises((pa_errors.SchemaError, pa_errors.SchemaErrors)):
        RawNbaApiRouteFieldLandingSchema.validate(pl.DataFrame([row], infer_schema_length=None))
