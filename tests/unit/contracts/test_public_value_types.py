from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from typing import cast

import pytest

from nbadb.contracts.public_value_types import (
    EXPECTED_VALUE_UNIT_KINDS_V1,
    MAX_PUBLIC_VALUE_EXPECTED_UNITS,
    PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
    PUBLIC_VALUE_REPRESENTATION_KINDS_V1,
    PUBLIC_VALUE_SOURCE_INPUT_KINDS_V1,
    ExpectedValueUnitInventoryV1,
    ExpectedValueUnitKindV1,
    ExpectedValueUnitV1,
    PublicValueRepresentationKindV1,
    PublicValueSourceInputKindV1,
    PublicValueTypesError,
    ValueRepresentationAssignmentV1,
)

_SHA_A = "a" * 64
_SHA_B = "b" * 64
_SHA_C = "c" * 64
_SHA_D = "d" * 64
_BUNDLE_A = "e" * 64
_BUNDLE_B = "f" * 64


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _unit_digest(row: dict[str, object]) -> str:
    return _digest(
        {
            "kind": "nbadb_expected_value_unit_v1",
            "schema_version": 1,
            "raw_authority_bundle_sha256": row["raw_authority_bundle_sha256"],
            "unit_ordinal": row["unit_ordinal"],
            "observation_sha256": row["observation_sha256"],
            "observation_ordinal": row["observation_ordinal"],
            "unit_kind": row["unit_kind"],
            "occurrence_sha256": row["occurrence_sha256"],
            "occurrence_ordinal": row["occurrence_ordinal"],
        }
    )


def _assignment_digest(row: dict[str, object]) -> str:
    return _digest(
        {
            "kind": "nbadb_value_representation_assignment_v1",
            "schema_version": 1,
            "raw_authority_bundle_sha256": row["raw_authority_bundle_sha256"],
            "unit_sha256": row["unit_sha256"],
            "unit_ordinal": row["unit_ordinal"],
            "source_input_kind": row["source_input_kind"],
            "representation_kind": row["representation_kind"],
        }
    )


def _ordered_root(
    units: tuple[ExpectedValueUnitV1, ...],
    *,
    raw_authority_bundle_sha256: str = _BUNDLE_A,
) -> str:
    payload = (
        b'{"count":'
        + str(len(units)).encode("ascii")
        + b',"items":['
        + b",".join(_canonical(unit.unit_sha256) for unit in units)
        + b'],"kind":"nbadb_expected_value_unit_ordered_root_v1"'
        + b',"raw_authority_bundle_sha256":'
        + _canonical(raw_authority_bundle_sha256)
        + b',"schema_version":1}'
    )
    return hashlib.sha256(payload).hexdigest()


def _inventory_digest(
    units: tuple[ExpectedValueUnitV1, ...],
    root: str,
    *,
    raw_authority_bundle_sha256: str = _BUNDLE_A,
) -> str:
    return _digest(
        {
            "kind": "nbadb_expected_value_unit_inventory_v1",
            "schema_version": 1,
            "raw_authority_bundle_sha256": raw_authority_bundle_sha256,
            "unit_count": len(units),
            "unit_root_sha256": root,
            "units": [unit.to_row() for unit in units],
        }
    )


def _unit(
    *,
    raw_authority_bundle_sha256: str = _BUNDLE_A,
    unit_ordinal: int = 0,
    observation_sha256: str = _SHA_A,
    observation_ordinal: int = 0,
    unit_kind: ExpectedValueUnitKindV1 = "result_occurrence",
    occurrence_sha256: str | None = _SHA_B,
    occurrence_ordinal: int | None = 0,
) -> ExpectedValueUnitV1:
    return ExpectedValueUnitV1.build(
        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
        unit_ordinal=unit_ordinal,
        observation_sha256=observation_sha256,
        observation_ordinal=observation_ordinal,
        unit_kind=unit_kind,
        occurrence_sha256=occurrence_sha256,
        occurrence_ordinal=occurrence_ordinal,
    )


def _response_unit(
    *,
    unit_ordinal: int,
    raw_authority_bundle_sha256: str = _BUNDLE_A,
    observation_sha256: str = _SHA_A,
    observation_ordinal: int = 0,
    unit_kind: ExpectedValueUnitKindV1 = "response_residual",
) -> ExpectedValueUnitV1:
    return _unit(
        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
        unit_ordinal=unit_ordinal,
        observation_sha256=observation_sha256,
        observation_ordinal=observation_ordinal,
        unit_kind=unit_kind,
        occurrence_sha256=None,
        occurrence_ordinal=None,
    )


def test_closed_public_value_domains_are_exact_and_separately_versioned() -> None:
    assert PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION == 1
    assert PUBLIC_VALUE_REPRESENTATION_KINDS_V1 == (
        "rectangular_result_cells_v1",
        "stats_lossless_records_v1",
        "live_lossless_nodes_v1",
        "response_lossless_records_v1",
        "response_fixed_zero_v1",
    )
    assert PUBLIC_VALUE_SOURCE_INPUT_KINDS_V1 == (
        "parser_input_body",
        "declared_bodyless_packet",
    )
    assert EXPECTED_VALUE_UNIT_KINDS_V1 == (
        "result_occurrence",
        "response_residual",
        "response_fixed_zero",
    )


def test_expected_unit_is_immutable_canonical_and_strictly_round_trips() -> None:
    unit = _unit()

    assert ExpectedValueUnitV1.from_row(unit.to_row()) == unit
    assert json.loads(unit.canonical_bytes()) == unit.to_row()
    assert unit.unit_sha256 == _unit_digest(unit.to_row())
    with pytest.raises(FrozenInstanceError):
        unit.unit_ordinal = 2

    reordered = {key: unit.to_row()[key] for key in reversed(unit.to_row())}
    with pytest.raises(PublicValueTypesError, match="exact ordered row shape"):
        ExpectedValueUnitV1.from_row(reordered)
    with pytest.raises(PublicValueTypesError, match="exact ordered row shape"):
        ExpectedValueUnitV1.from_row({**unit.to_row(), "local_path": "/Users/alice"})


@pytest.mark.parametrize("ordinal", [True, -1, 1 << 63])
def test_expected_unit_rejects_non_exact_or_unbounded_ordinals(ordinal: object) -> None:
    row = _unit().to_row()
    row["unit_ordinal"] = ordinal
    with pytest.raises(PublicValueTypesError, match="exact integer"):
        ExpectedValueUnitV1.from_row(row)


def test_expected_unit_checks_type_before_hostile_equality_or_comparison() -> None:
    class HostileInt(int):
        def __lt__(self, _other: object) -> bool:
            raise AssertionError("hostile comparison was invoked")

        def __gt__(self, _other: object) -> bool:
            raise AssertionError("hostile comparison was invoked")

    class HostileStr(str):
        def __eq__(self, _other: object) -> bool:
            raise AssertionError("hostile equality was invoked")

        __hash__ = str.__hash__

    row = _unit().to_row()
    row["unit_ordinal"] = HostileInt(0)
    with pytest.raises(PublicValueTypesError):
        ExpectedValueUnitV1.from_row(row)

    row = _unit().to_row()
    row["unit_kind"] = HostileStr("result_occurrence")
    with pytest.raises(PublicValueTypesError):
        ExpectedValueUnitV1.from_row(row)


def test_expected_unit_shape_is_checked_after_independent_reseal() -> None:
    result_row = _unit().to_row()
    result_row["occurrence_sha256"] = None
    result_row["occurrence_ordinal"] = None
    result_row["unit_sha256"] = _unit_digest(result_row)
    with pytest.raises(PublicValueTypesError, match="occurrence"):
        ExpectedValueUnitV1.from_row(result_row)

    response_row = _response_unit(unit_ordinal=0).to_row()
    response_row["occurrence_sha256"] = _SHA_B
    response_row["occurrence_ordinal"] = 0
    response_row["unit_sha256"] = _unit_digest(response_row)
    with pytest.raises(PublicValueTypesError, match="cannot carry occurrence"):
        ExpectedValueUnitV1.from_row(response_row)


def test_expected_unit_rejects_foreign_or_secret_shaped_identity_text() -> None:
    with pytest.raises(PublicValueTypesError, match="SHA-256"):
        _unit(observation_sha256="/Users/alice/.secrets/token")
    with pytest.raises(PublicValueTypesError, match="SHA-256"):
        _unit(observation_sha256="A" * 64)
    with pytest.raises(PublicValueTypesError, match="closed V1 domain"):
        _unit(unit_kind=cast("ExpectedValueUnitKindV1", "bearer token-value"))


def test_inventory_preserves_same_bundle_multi_observation_and_response_order() -> None:
    units = (
        _unit(unit_ordinal=0, occurrence_sha256=_SHA_B, occurrence_ordinal=0),
        _unit(unit_ordinal=1, occurrence_sha256=_SHA_C, occurrence_ordinal=1),
        _response_unit(unit_ordinal=2),
        _response_unit(
            unit_ordinal=3,
            observation_sha256=_SHA_D,
            observation_ordinal=1,
            unit_kind="response_fixed_zero",
        ),
    )
    inventory = ExpectedValueUnitInventoryV1.build(
        raw_authority_bundle_sha256=_BUNDLE_A,
        units=units,
    )

    assert inventory.unit_count == 4
    assert inventory.raw_authority_bundle_sha256 == _BUNDLE_A
    assert tuple(unit.raw_authority_bundle_sha256 for unit in inventory.units) == (
        _BUNDLE_A,
        _BUNDLE_A,
        _BUNDLE_A,
        _BUNDLE_A,
    )
    assert tuple(unit.unit_ordinal for unit in inventory.units) == (0, 1, 2, 3)
    assert inventory.unit_root_sha256 == _ordered_root(units)
    assert inventory.inventory_sha256 == _inventory_digest(units, inventory.unit_root_sha256)
    assert ExpectedValueUnitInventoryV1.from_row(inventory.to_row()) == inventory
    assert json.loads(inventory.canonical_bytes())["units_json"] == inventory.to_row()["units_json"]


def test_empty_inventory_is_canonical_stable_and_bundle_scoped() -> None:
    first = ExpectedValueUnitInventoryV1.build(
        raw_authority_bundle_sha256=_BUNDLE_A,
        units=(),
    )
    second = ExpectedValueUnitInventoryV1.build(
        raw_authority_bundle_sha256=_BUNDLE_A,
        units=(),
    )
    foreign = ExpectedValueUnitInventoryV1.build(
        raw_authority_bundle_sha256=_BUNDLE_B,
        units=(),
    )

    assert first == second
    assert first != foreign
    assert first.unit_count == 0
    assert first.unit_root_sha256 != foreign.unit_root_sha256
    assert first.inventory_sha256 != foreign.inventory_sha256
    assert ExpectedValueUnitInventoryV1.from_row(first.to_row()) == first


def test_independent_result_bundles_each_start_with_unit_ordinal_zero() -> None:
    first_unit = _unit(raw_authority_bundle_sha256=_BUNDLE_A)
    second_unit = _unit(raw_authority_bundle_sha256=_BUNDLE_B)
    first = ExpectedValueUnitInventoryV1.build(
        raw_authority_bundle_sha256=_BUNDLE_A,
        units=(first_unit,),
    )
    second = ExpectedValueUnitInventoryV1.build(
        raw_authority_bundle_sha256=_BUNDLE_B,
        units=(second_unit,),
    )

    assert first.units[0].unit_ordinal == second.units[0].unit_ordinal == 0
    assert first.units[0].unit_sha256 != second.units[0].unit_sha256
    assert first.unit_root_sha256 != second.unit_root_sha256
    assert first.inventory_sha256 != second.inventory_sha256


def test_independent_response_bundles_each_start_with_unit_ordinal_zero() -> None:
    first_unit = _response_unit(
        raw_authority_bundle_sha256=_BUNDLE_A,
        unit_ordinal=0,
    )
    second_unit = _response_unit(
        raw_authority_bundle_sha256=_BUNDLE_B,
        unit_ordinal=0,
    )
    first = ValueRepresentationAssignmentV1.build(
        expected_unit=first_unit,
        source_input_kind="parser_input_body",
        representation_kind="response_lossless_records_v1",
    )
    second = ValueRepresentationAssignmentV1.build(
        expected_unit=second_unit,
        source_input_kind="parser_input_body",
        representation_kind="response_lossless_records_v1",
    )

    assert first.unit_ordinal == second.unit_ordinal == 0
    assert first.raw_authority_bundle_sha256 == _BUNDLE_A
    assert second.raw_authority_bundle_sha256 == _BUNDLE_B
    assert first.assignment_sha256 != second.assignment_sha256
    assert first.validate_for_unit(first_unit) is first
    assert second.validate_for_unit(second_unit) is second


def test_inventory_rejects_cross_bundle_member_after_envelope_reseal() -> None:
    foreign_unit = _unit(raw_authority_bundle_sha256=_BUNDLE_B)
    units = (foreign_unit,)
    root = _ordered_root(units, raw_authority_bundle_sha256=_BUNDLE_A)

    with pytest.raises(PublicValueTypesError, match="foreign raw-authority bundle"):
        ExpectedValueUnitInventoryV1(
            inventory_sha256=_inventory_digest(
                units,
                root,
                raw_authority_bundle_sha256=_BUNDLE_A,
            ),
            raw_authority_bundle_sha256=_BUNDLE_A,
            unit_count=1,
            unit_root_sha256=root,
            units=units,
        )


def test_inventory_rejects_reorder_even_when_roots_are_independently_resealed() -> None:
    first = _unit(unit_ordinal=0, occurrence_sha256=_SHA_B, occurrence_ordinal=0)
    second = _unit(unit_ordinal=1, occurrence_sha256=_SHA_C, occurrence_ordinal=1)
    reordered = (second, first)
    root = _ordered_root(reordered)

    with pytest.raises(PublicValueTypesError, match="declared ordinals"):
        ExpectedValueUnitInventoryV1(
            inventory_sha256=_inventory_digest(reordered, root),
            raw_authority_bundle_sha256=_BUNDLE_A,
            unit_count=2,
            unit_root_sha256=root,
            units=reordered,
        )


def test_inventory_rejects_noncanonical_observation_and_occurrence_shapes() -> None:
    with pytest.raises(PublicValueTypesError, match="occurrence order"):
        ExpectedValueUnitInventoryV1.build(
            raw_authority_bundle_sha256=_BUNDLE_A,
            units=(_unit(occurrence_ordinal=1),),
        )

    response = _response_unit(unit_ordinal=0)
    later_occurrence = _unit(unit_ordinal=1, occurrence_ordinal=0)
    with pytest.raises(PublicValueTypesError, match="occurrence order"):
        ExpectedValueUnitInventoryV1.build(
            raw_authority_bundle_sha256=_BUNDLE_A,
            units=(response, later_occurrence),
        )

    with pytest.raises(PublicValueTypesError, match="several response units"):
        ExpectedValueUnitInventoryV1.build(
            raw_authority_bundle_sha256=_BUNDLE_A,
            units=(
                _response_unit(unit_ordinal=0),
                _response_unit(unit_ordinal=1, unit_kind="response_fixed_zero"),
            ),
        )

    reopened = (
        _response_unit(unit_ordinal=0),
        _response_unit(
            unit_ordinal=1,
            observation_sha256=_SHA_D,
            observation_ordinal=1,
            unit_kind="response_fixed_zero",
        ),
        _response_unit(unit_ordinal=2, observation_ordinal=0),
    )
    with pytest.raises(PublicValueTypesError, match="reopens"):
        ExpectedValueUnitInventoryV1.build(
            raw_authority_bundle_sha256=_BUNDLE_A,
            units=reopened,
        )


def test_inventory_rejects_fixed_zero_after_result_but_preserves_hybrid_residual() -> None:
    result = _unit(unit_ordinal=0)
    fixed_zero = _response_unit(
        unit_ordinal=1,
        unit_kind="response_fixed_zero",
    )
    with pytest.raises(PublicValueTypesError, match="fixed-zero response"):
        ExpectedValueUnitInventoryV1.build(
            raw_authority_bundle_sha256=_BUNDLE_A,
            units=(result, fixed_zero),
        )

    residual = _response_unit(unit_ordinal=1)
    hybrid = ExpectedValueUnitInventoryV1.build(
        raw_authority_bundle_sha256=_BUNDLE_A,
        units=(result, residual),
    )
    assert hybrid.units == (result, residual)


def test_inventory_from_row_rejects_independently_resealed_fixed_zero_after_result() -> None:
    units = (
        _unit(unit_ordinal=0),
        _response_unit(unit_ordinal=1, unit_kind="response_fixed_zero"),
    )
    root = _ordered_root(units)
    row: dict[str, object] = {
        "schema_version": 1,
        "inventory_sha256": _inventory_digest(units, root),
        "raw_authority_bundle_sha256": _BUNDLE_A,
        "unit_count": 2,
        "unit_root_sha256": root,
        "units_json": _canonical([unit.to_row() for unit in units]).decode("utf-8"),
    }

    with pytest.raises(PublicValueTypesError, match="fixed-zero response"):
        ExpectedValueUnitInventoryV1.from_row(row)


def test_inventory_strict_json_rejects_mutation_and_hostile_structure() -> None:
    inventory = ExpectedValueUnitInventoryV1.build(
        raw_authority_bundle_sha256=_BUNDLE_A,
        units=(_unit(),),
    )
    row = inventory.to_row()
    units_json = cast("str", row["units_json"])

    noncanonical = dict(row)
    noncanonical["units_json"] = units_json.replace(",", ", ", 1)
    with pytest.raises(PublicValueTypesError, match="not canonical"):
        ExpectedValueUnitInventoryV1.from_row(noncanonical)

    duplicate = dict(row)
    duplicate["units_json"] = units_json.replace(
        '"schema_version":1',
        '"schema_version":1,"schema_version":1',
        1,
    )
    with pytest.raises(PublicValueTypesError, match="duplicate object keys"):
        ExpectedValueUnitInventoryV1.from_row(duplicate)

    deep = dict(row)
    deep["units_json"] = "[[[[[[[[[[]]]]]]]]]]"
    with pytest.raises(PublicValueTypesError, match="structural bound"):
        ExpectedValueUnitInventoryV1.from_row(deep)

    floating = dict(row)
    floating["units_json"] = "[1.0]"
    with pytest.raises(PublicValueTypesError, match="non-integer number"):
        ExpectedValueUnitInventoryV1.from_row(floating)


def test_inventory_rejects_foreign_containers_and_bound_before_members() -> None:
    inventory = ExpectedValueUnitInventoryV1.build(
        raw_authority_bundle_sha256=_BUNDLE_A,
        units=(),
    )
    with pytest.raises(PublicValueTypesError, match="exact tuple"):
        ExpectedValueUnitInventoryV1(
            inventory_sha256=inventory.inventory_sha256,
            raw_authority_bundle_sha256=_BUNDLE_A,
            unit_count=0,
            unit_root_sha256=inventory.unit_root_sha256,
            units=cast("tuple[ExpectedValueUnitV1, ...]", []),
        )
    with pytest.raises(PublicValueTypesError, match="unit bound"):
        ExpectedValueUnitInventoryV1(
            inventory_sha256=inventory.inventory_sha256,
            raw_authority_bundle_sha256=_BUNDLE_A,
            unit_count=MAX_PUBLIC_VALUE_EXPECTED_UNITS + 1,
            unit_root_sha256=inventory.unit_root_sha256,
            units=(),
        )


@pytest.mark.parametrize(
    ("unit_kind", "representation_kind"),
    [
        ("result_occurrence", "rectangular_result_cells_v1"),
        ("result_occurrence", "stats_lossless_records_v1"),
        ("result_occurrence", "live_lossless_nodes_v1"),
        ("response_residual", "response_lossless_records_v1"),
        ("response_fixed_zero", "response_fixed_zero_v1"),
    ],
)
def test_assignment_binds_one_compatible_closed_representation(
    unit_kind: ExpectedValueUnitKindV1,
    representation_kind: PublicValueRepresentationKindV1,
) -> None:
    unit = (
        _unit(unit_kind=unit_kind)
        if unit_kind == "result_occurrence"
        else _response_unit(unit_ordinal=0, unit_kind=unit_kind)
    )
    assignment = ValueRepresentationAssignmentV1.build(
        expected_unit=unit,
        source_input_kind="parser_input_body",
        representation_kind=representation_kind,
    )

    assert assignment.unit_sha256 == unit.unit_sha256
    assert assignment.validate_for_unit(unit) is assignment
    assert ValueRepresentationAssignmentV1.from_row(assignment.to_row()) == assignment
    assert assignment.assignment_sha256 == _assignment_digest(assignment.to_row())
    assert json.loads(assignment.canonical_bytes()) == assignment.to_row()


@pytest.mark.parametrize(
    ("unit_kind", "representation_kind"),
    [
        ("result_occurrence", "response_lossless_records_v1"),
        ("result_occurrence", "response_fixed_zero_v1"),
        ("response_residual", "rectangular_result_cells_v1"),
        ("response_fixed_zero", "response_lossless_records_v1"),
    ],
)
def test_assignment_rejects_incompatible_unit_representation_shape(
    unit_kind: ExpectedValueUnitKindV1,
    representation_kind: PublicValueRepresentationKindV1,
) -> None:
    unit = (
        _unit(unit_kind=unit_kind)
        if unit_kind == "result_occurrence"
        else _response_unit(unit_ordinal=0, unit_kind=unit_kind)
    )
    with pytest.raises(PublicValueTypesError, match="representation"):
        ValueRepresentationAssignmentV1.build(
            expected_unit=unit,
            source_input_kind="parser_input_body",
            representation_kind=representation_kind,
        )


def test_assignment_independent_reseal_cannot_change_fixed_zero_shape() -> None:
    unit = _response_unit(unit_ordinal=0, unit_kind="response_fixed_zero")
    assignment = ValueRepresentationAssignmentV1.build(
        expected_unit=unit,
        source_input_kind="declared_bodyless_packet",
        representation_kind="response_fixed_zero_v1",
    )
    row = assignment.to_row()
    row["representation_kind"] = "rectangular_result_cells_v1"
    row["assignment_sha256"] = _assignment_digest(row)
    resealed = ValueRepresentationAssignmentV1.from_row(row)

    with pytest.raises(PublicValueTypesError, match="fixed-zero"):
        resealed.validate_for_unit(unit)


def test_assignment_rejects_cross_bundle_coordinated_reseal_substitution() -> None:
    original_unit = _unit(raw_authority_bundle_sha256=_BUNDLE_A)
    foreign_unit = _unit(raw_authority_bundle_sha256=_BUNDLE_B)
    assignment = ValueRepresentationAssignmentV1.build(
        expected_unit=original_unit,
        source_input_kind="parser_input_body",
        representation_kind="rectangular_result_cells_v1",
    )
    row = assignment.to_row()
    row["raw_authority_bundle_sha256"] = _BUNDLE_B
    row["unit_sha256"] = foreign_unit.unit_sha256
    row["assignment_sha256"] = _assignment_digest(row)
    resealed = ValueRepresentationAssignmentV1.from_row(row)

    assert resealed.validate_for_unit(foreign_unit) is resealed
    with pytest.raises(PublicValueTypesError, match="foreign expected unit"):
        resealed.validate_for_unit(original_unit)


def test_assignment_rejects_foreign_unit_and_nonclosed_kinds() -> None:
    unit = _unit()
    assignment = ValueRepresentationAssignmentV1.build(
        expected_unit=unit,
        source_input_kind="parser_input_body",
        representation_kind="rectangular_result_cells_v1",
    )
    foreign = _unit(observation_sha256=_SHA_D)
    with pytest.raises(PublicValueTypesError, match="foreign expected unit"):
        assignment.validate_for_unit(foreign)

    for source_kind in ("body", "Bearer abcdefghijklmnop"):
        with pytest.raises(PublicValueTypesError, match="source-input kind"):
            ValueRepresentationAssignmentV1.build(
                expected_unit=unit,
                source_input_kind=cast("PublicValueSourceInputKindV1", source_kind),
                representation_kind="rectangular_result_cells_v1",
            )
    with pytest.raises(PublicValueTypesError, match="representation kind"):
        ValueRepresentationAssignmentV1.build(
            expected_unit=unit,
            source_input_kind="parser_input_body",
            representation_kind=cast(
                "PublicValueRepresentationKindV1", "stats_lossless_records_v2"
            ),
        )


def test_assignment_row_is_strict_and_bool_is_not_an_integer() -> None:
    assignment = ValueRepresentationAssignmentV1.build(
        expected_unit=_unit(),
        source_input_kind="parser_input_body",
        representation_kind="rectangular_result_cells_v1",
    )
    row = assignment.to_row()
    row["unit_ordinal"] = True
    with pytest.raises(PublicValueTypesError, match="exact integer"):
        ValueRepresentationAssignmentV1.from_row(row)

    reordered = {key: assignment.to_row()[key] for key in reversed(assignment.to_row())}
    with pytest.raises(PublicValueTypesError, match="exact ordered row shape"):
        ValueRepresentationAssignmentV1.from_row(reordered)


def test_stale_inventory_rejects_independently_resealed_unit_mutation() -> None:
    inventory = ExpectedValueUnitInventoryV1.build(
        raw_authority_bundle_sha256=_BUNDLE_A,
        units=(_unit(),),
    )
    mutated = _unit(observation_sha256=_SHA_D)

    with pytest.raises(PublicValueTypesError, match="root"):
        replace(inventory, units=(mutated,))
