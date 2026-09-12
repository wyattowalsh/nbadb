from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from nbadb.contracts import lossless_ownership as ownership_module
from nbadb.contracts.lossless_ownership import (
    MAX_LOSSLESS_OWNERSHIP_BINDINGS,
    LosslessObservationOwnershipV1,
    LosslessOwnershipAuthorityV1,
    LosslessOwnershipBindingV1,
    LosslessOwnershipError,
    LosslessOwnershipPartitionV1,
    LosslessOwnershipReceiptV1,
    build_lossless_ownership_authority,
)
from nbadb.contracts.public_value_types import (
    ExpectedValueUnitInventoryV1,
    ExpectedValueUnitV1,
    ValueRepresentationAssignmentV1,
)

_RAW = "a" * 64
_OBSERVATION_RECORDS = ("1" * 64, "2" * 64, "3" * 64)
_OBSERVATIONS = ("4" * 64, "5" * 64, "6" * 64)
_OCCURRENCES = ("7" * 64, "8" * 64, "9" * 64)
_SOURCE_RECORDS = ("b" * 64, "c" * 64, "d" * 64, "e" * 64)
_FIXED_ZERO_LANDING = "f" * 64


class _TextSubclass(str):
    pass


def _unit(
    *,
    unit_ordinal: int,
    observation_ordinal: int,
    unit_kind: str,
    occurrence_ordinal: int | None = None,
) -> ExpectedValueUnitV1:
    return ExpectedValueUnitV1.build(
        raw_authority_bundle_sha256=_RAW,
        unit_ordinal=unit_ordinal,
        observation_sha256=_OBSERVATIONS[observation_ordinal],
        observation_ordinal=observation_ordinal,
        unit_kind=unit_kind,  # type: ignore[arg-type]
        occurrence_sha256=(
            None if occurrence_ordinal is None else _OCCURRENCES[occurrence_ordinal]
        ),
        occurrence_ordinal=occurrence_ordinal,
    )


def _assignment(
    unit: ExpectedValueUnitV1,
    *,
    source_input_kind: str,
    representation_kind: str,
) -> ValueRepresentationAssignmentV1:
    return ValueRepresentationAssignmentV1.build(
        expected_unit=unit,
        source_input_kind=source_input_kind,  # type: ignore[arg-type]
        representation_kind=representation_kind,  # type: ignore[arg-type]
    )


def _binding(
    *,
    unit: ExpectedValueUnitV1,
    assignment: ValueRepresentationAssignmentV1,
    binding_ordinal: int,
    observation_record_ordinal: int,
    partition_ordinal: int,
    source_record_sha256: str,
) -> LosslessOwnershipBindingV1:
    observation_ordinal = unit.observation_ordinal
    return LosslessOwnershipBindingV1.build(
        raw_authority_bundle_sha256=_RAW,
        observation_record_sha256=_OBSERVATION_RECORDS[observation_ordinal],
        observation_sha256=_OBSERVATIONS[observation_ordinal],
        observation_ordinal=observation_ordinal,
        binding_ordinal=binding_ordinal,
        observation_record_ordinal=observation_record_ordinal,
        partition_ordinal=partition_ordinal,
        source_record_sha256=source_record_sha256,
        expected_unit=unit,
        assignment=assignment,
    )


def _partition(
    *,
    observation_ordinal: int,
    partition_ordinal: int,
    observation_partition_ordinal: int,
    partition_kind: str,
    bindings: tuple[LosslessOwnershipBindingV1, ...],
    unit: ExpectedValueUnitV1 | None = None,
    assignment: ValueRepresentationAssignmentV1 | None = None,
    fixed_zero_landing_sha256: str | None = None,
) -> LosslessOwnershipPartitionV1:
    return LosslessOwnershipPartitionV1.build(
        raw_authority_bundle_sha256=_RAW,
        observation_record_sha256=_OBSERVATION_RECORDS[observation_ordinal],
        observation_sha256=_OBSERVATIONS[observation_ordinal],
        observation_ordinal=observation_ordinal,
        partition_ordinal=partition_ordinal,
        observation_partition_ordinal=observation_partition_ordinal,
        partition_kind=partition_kind,  # type: ignore[arg-type]
        bindings=bindings,
        expected_unit=unit,
        assignment=assignment,
        fixed_zero_landing_sha256=fixed_zero_landing_sha256,
    )


def _authority() -> LosslessOwnershipAuthorityV1:
    units = (
        _unit(
            unit_ordinal=0,
            observation_ordinal=0,
            unit_kind="result_occurrence",
            occurrence_ordinal=0,
        ),
        _unit(
            unit_ordinal=1,
            observation_ordinal=0,
            unit_kind="result_occurrence",
            occurrence_ordinal=1,
        ),
        _unit(unit_ordinal=2, observation_ordinal=0, unit_kind="response_residual"),
        _unit(
            unit_ordinal=3,
            observation_ordinal=1,
            unit_kind="result_occurrence",
            occurrence_ordinal=0,
        ),
        _unit(unit_ordinal=4, observation_ordinal=2, unit_kind="response_fixed_zero"),
    )
    assignments = (
        _assignment(
            units[0],
            source_input_kind="parser_input_body",
            representation_kind="rectangular_result_cells_v1",
        ),
        _assignment(
            units[1],
            source_input_kind="parser_input_body",
            representation_kind="stats_lossless_records_v1",
        ),
        _assignment(
            units[2],
            source_input_kind="parser_input_body",
            representation_kind="response_lossless_records_v1",
        ),
        _assignment(
            units[3],
            source_input_kind="declared_bodyless_packet",
            representation_kind="live_lossless_nodes_v1",
        ),
        _assignment(
            units[4],
            source_input_kind="parser_input_body",
            representation_kind="response_fixed_zero_v1",
        ),
    )
    bindings = (
        _binding(
            unit=units[0],
            assignment=assignments[0],
            binding_ordinal=0,
            observation_record_ordinal=0,
            partition_ordinal=0,
            source_record_sha256=_SOURCE_RECORDS[0],
        ),
        _binding(
            unit=units[2],
            assignment=assignments[2],
            binding_ordinal=1,
            observation_record_ordinal=1,
            partition_ordinal=2,
            source_record_sha256=_SOURCE_RECORDS[1],
        ),
        _binding(
            unit=units[0],
            assignment=assignments[0],
            binding_ordinal=2,
            observation_record_ordinal=2,
            partition_ordinal=0,
            source_record_sha256=_SOURCE_RECORDS[2],
        ),
        _binding(
            unit=units[3],
            assignment=assignments[3],
            binding_ordinal=3,
            observation_record_ordinal=0,
            partition_ordinal=3,
            source_record_sha256=_SOURCE_RECORDS[3],
        ),
    )
    partitions = (
        _partition(
            observation_ordinal=0,
            partition_ordinal=0,
            observation_partition_ordinal=0,
            partition_kind="result_occurrence",
            bindings=(bindings[0], bindings[2]),
            unit=units[0],
            assignment=assignments[0],
        ),
        _partition(
            observation_ordinal=0,
            partition_ordinal=1,
            observation_partition_ordinal=1,
            partition_kind="result_occurrence",
            bindings=(),
            unit=units[1],
            assignment=assignments[1],
        ),
        _partition(
            observation_ordinal=0,
            partition_ordinal=2,
            observation_partition_ordinal=2,
            partition_kind="response_residual",
            bindings=(bindings[1],),
            unit=units[2],
            assignment=assignments[2],
        ),
        _partition(
            observation_ordinal=1,
            partition_ordinal=3,
            observation_partition_ordinal=0,
            partition_kind="result_occurrence",
            bindings=(bindings[3],),
            unit=units[3],
            assignment=assignments[3],
        ),
        _partition(
            observation_ordinal=1,
            partition_ordinal=4,
            observation_partition_ordinal=1,
            partition_kind="response_residual",
            bindings=(),
        ),
        _partition(
            observation_ordinal=2,
            partition_ordinal=5,
            observation_partition_ordinal=0,
            partition_kind="response_fixed_zero",
            bindings=(),
            unit=units[4],
            assignment=assignments[4],
            fixed_zero_landing_sha256=_FIXED_ZERO_LANDING,
        ),
    )
    observations = (
        LosslessObservationOwnershipV1.build(
            raw_authority_bundle_sha256=_RAW,
            observation_record_sha256=_OBSERVATION_RECORDS[0],
            observation_sha256=_OBSERVATIONS[0],
            observation_ordinal=0,
            source_input_kind="parser_input_body",
            partitions=partitions[:3],
            bindings=bindings[:3],
        ),
        LosslessObservationOwnershipV1.build(
            raw_authority_bundle_sha256=_RAW,
            observation_record_sha256=_OBSERVATION_RECORDS[1],
            observation_sha256=_OBSERVATIONS[1],
            observation_ordinal=1,
            source_input_kind="declared_bodyless_packet",
            partitions=partitions[3:5],
            bindings=bindings[3:],
        ),
        LosslessObservationOwnershipV1.build(
            raw_authority_bundle_sha256=_RAW,
            observation_record_sha256=_OBSERVATION_RECORDS[2],
            observation_sha256=_OBSERVATIONS[2],
            observation_ordinal=2,
            source_input_kind="parser_input_body",
            partitions=partitions[5:],
            bindings=(),
        ),
    )
    return build_lossless_ownership_authority(
        raw_authority_bundle_sha256=_RAW,
        expected_unit_inventory=ExpectedValueUnitInventoryV1.build(
            raw_authority_bundle_sha256=_RAW,
            units=units,
        ),
        representation_assignments=assignments,
        observations=observations,
        partitions=partitions,
        bindings=bindings,
    )


def _pure_residual_authority() -> LosslessOwnershipAuthorityV1:
    unit = _unit(unit_ordinal=0, observation_ordinal=0, unit_kind="response_residual")
    assignment = _assignment(
        unit,
        source_input_kind="parser_input_body",
        representation_kind="response_lossless_records_v1",
    )
    binding = _binding(
        unit=unit,
        assignment=assignment,
        binding_ordinal=0,
        observation_record_ordinal=0,
        partition_ordinal=0,
        source_record_sha256=_SOURCE_RECORDS[0],
    )
    partition = _partition(
        observation_ordinal=0,
        partition_ordinal=0,
        observation_partition_ordinal=0,
        partition_kind="response_residual",
        bindings=(binding,),
        unit=unit,
        assignment=assignment,
    )
    observation = LosslessObservationOwnershipV1.build(
        raw_authority_bundle_sha256=_RAW,
        observation_record_sha256=_OBSERVATION_RECORDS[0],
        observation_sha256=_OBSERVATIONS[0],
        observation_ordinal=0,
        source_input_kind="parser_input_body",
        partitions=(partition,),
        bindings=(binding,),
    )
    return build_lossless_ownership_authority(
        raw_authority_bundle_sha256=_RAW,
        expected_unit_inventory=ExpectedValueUnitInventoryV1.build(
            raw_authority_bundle_sha256=_RAW,
            units=(unit,),
        ),
        representation_assignments=(assignment,),
        observations=(observation,),
        partitions=(partition,),
        bindings=(binding,),
    )


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _unsafe_reseal(value: Any, *, digest_field: str, changes: dict[str, object]) -> Any:
    row = value.to_row()
    row.update(changes)
    payload = {
        "schema_version": row["schema_version"],
        "kind": type(value).kind,
        **{key: item for key, item in row.items() if key not in {"schema_version", digest_field}},
    }
    row[digest_field] = _canonical_sha256(payload)
    return type(value).from_row(row)


def _authority_with(
    authority: LosslessOwnershipAuthorityV1,
    **changes: object,
) -> LosslessOwnershipAuthorityV1:
    values: dict[str, object] = {
        "receipt": authority.receipt,
        "expected_unit_inventory": authority.expected_unit_inventory,
        "representation_assignments": authority.representation_assignments,
        "observations": authority.observations,
        "partitions": authority.partitions,
        "bindings": authority.bindings,
    }
    values.update(changes)
    return LosslessOwnershipAuthorityV1(**values)  # type: ignore[arg-type]


def test_complete_authority_closes_hybrid_zero_occurrence_zero_residual_and_fixed_zero() -> None:
    authority = _authority()
    receipt = authority.receipt

    assert receipt.raw_authority_bundle_sha256 == _RAW
    assert receipt.observation_count == 3
    assert receipt.expected_unit_count == 5
    assert receipt.representation_assignment_count == 5
    assert receipt.partition_count == 6
    assert receipt.result_occurrence_partition_count == 3
    assert receipt.zero_result_occurrence_partition_count == 1
    assert receipt.result_occurrence_record_count == 3
    assert receipt.response_residual_partition_count == 2
    assert receipt.positive_response_residual_partition_count == 1
    assert receipt.zero_response_residual_partition_count == 1
    assert receipt.response_residual_record_count == 1
    assert receipt.response_fixed_zero_partition_count == 1
    assert receipt.binding_count == receipt.source_record_count == 4
    assert authority.partitions[1].record_count == 0
    assert (
        authority.partitions[1].unit_sha256
        == authority.expected_unit_inventory.units[1].unit_sha256
    )
    assert authority.partitions[4].record_count == 0
    assert authority.partitions[4].unit_sha256 is None
    assert authority.partitions[5].fixed_zero_landing_sha256 == _FIXED_ZERO_LANDING


def test_interleaved_source_record_order_is_preserved_without_partition_reordering() -> None:
    authority = _authority()

    assert [binding.partition_ordinal for binding in authority.bindings[:3]] == [0, 2, 0]
    assert [binding.observation_record_ordinal for binding in authority.bindings[:3]] == [0, 1, 2]
    assert authority.partitions[0].record_count == 2
    assert authority.partitions[2].record_count == 1


def test_pure_response_residual_has_one_unit_partition_and_binding() -> None:
    authority = _pure_residual_authority()

    assert authority.receipt.observation_count == 1
    assert authority.receipt.result_occurrence_partition_count == 0
    assert authority.receipt.response_residual_partition_count == 1
    assert authority.receipt.positive_response_residual_partition_count == 1
    assert authority.receipt.response_residual_record_count == 1
    assert authority.receipt.expected_unit_count == 1


def test_canonical_empty_bundle_authority_is_exact_and_replayable() -> None:
    inventory = ExpectedValueUnitInventoryV1.build(
        raw_authority_bundle_sha256=_RAW,
        units=(),
    )
    authority = build_lossless_ownership_authority(
        raw_authority_bundle_sha256=_RAW,
        expected_unit_inventory=inventory,
        representation_assignments=(),
        observations=(),
        partitions=(),
        bindings=(),
    )

    assert authority.receipt.observation_count == 0
    assert authority.receipt.expected_unit_count == 0
    assert authority.receipt.partition_count == 0
    assert authority.receipt.binding_count == 0
    assert LosslessOwnershipReceiptV1.from_row(authority.receipt.to_row()) == authority.receipt


def test_all_four_dtos_and_receipt_round_trip_exact_rows_and_bytes() -> None:
    authority = _authority()
    values = (
        authority.bindings[0],
        authority.partitions[0],
        authority.observations[0],
        authority.receipt,
    )

    for value in values:
        assert type(value).from_row(value.to_row()) == value
        assert json.loads(value.canonical_bytes()) == value.to_row()
        row = value.to_row()
        reordered = {key: row[key] for key in reversed(row)}
        with pytest.raises(LosslessOwnershipError, match="ordered row shape"):
            type(value).from_row(reordered)
        row["authorization"] = "redacted"
        with pytest.raises(LosslessOwnershipError, match="ordered row shape"):
            type(value).from_row(row)


def test_orphan_binding_is_rejected_after_exact_reseal() -> None:
    authority = _authority()
    orphan = _unsafe_reseal(
        authority.bindings[1],
        digest_field="binding_sha256",
        changes={"partition_ordinal": 99},
    )

    with pytest.raises(LosslessOwnershipError, match="orphaned, foreign, or reordered"):
        _authority_with(
            authority,
            bindings=(authority.bindings[0], orphan, *authority.bindings[2:]),
        )


def test_cross_observation_partition_binding_is_rejected_after_exact_reseal() -> None:
    authority = _authority()
    cross_observation = _unsafe_reseal(
        authority.bindings[0],
        digest_field="binding_sha256",
        changes={"partition_ordinal": 3},
    )

    with pytest.raises(LosslessOwnershipError, match="orphaned, foreign, or reordered"):
        _authority_with(
            authority,
            bindings=(cross_observation, *authority.bindings[1:]),
        )


def test_dual_assignment_of_one_exact_source_record_is_rejected() -> None:
    authority = _authority()
    duplicate_source = _unsafe_reseal(
        authority.bindings[1],
        digest_field="binding_sha256",
        changes={"source_record_sha256": authority.bindings[0].source_record_sha256},
    )

    with pytest.raises(LosslessOwnershipError, match="dual-assigns"):
        _authority_with(
            authority,
            bindings=(authority.bindings[0], duplicate_source, *authority.bindings[2:]),
        )


def test_binding_reorder_and_observation_reopen_are_rejected() -> None:
    authority = _authority()

    with pytest.raises(LosslessOwnershipError, match="orphaned, foreign, or reordered"):
        _authority_with(
            authority,
            bindings=(authority.bindings[1], authority.bindings[0], *authority.bindings[2:]),
        )
    reopened = _unsafe_reseal(
        authority.bindings[3],
        digest_field="binding_sha256",
        changes={
            "binding_ordinal": 1,
            "observation_record_ordinal": 3,
            "observation_ordinal": 0,
            "observation_record_sha256": _OBSERVATION_RECORDS[0],
            "observation_sha256": _OBSERVATIONS[0],
        },
    )
    with pytest.raises(LosslessOwnershipError):
        _authority_with(
            authority,
            bindings=(
                authority.bindings[0],
                reopened,
                authority.bindings[1],
                authority.bindings[2],
            ),
        )


def test_foreign_or_duplicate_expected_unit_partition_is_rejected() -> None:
    authority = _authority()
    unit = authority.expected_unit_inventory.units[0]
    assignment = authority.representation_assignments[0]
    duplicate = _unsafe_reseal(
        authority.partitions[1],
        digest_field="partition_sha256",
        changes={
            "occurrence_sha256": unit.occurrence_sha256,
            "occurrence_ordinal": unit.occurrence_ordinal,
            "unit_sha256": unit.unit_sha256,
            "unit_ordinal": unit.unit_ordinal,
            "assignment_sha256": assignment.assignment_sha256,
        },
    )

    with pytest.raises(LosslessOwnershipError, match="duplicate or foreign unit"):
        _authority_with(
            authority,
            partitions=(authority.partitions[0], duplicate, *authority.partitions[2:]),
        )


def test_foreign_bundle_inventory_binding_and_partition_are_rejected() -> None:
    authority = _authority()
    foreign_unit = ExpectedValueUnitV1.build(
        raw_authority_bundle_sha256="0" * 64,
        unit_ordinal=0,
        observation_sha256=_OBSERVATIONS[0],
        observation_ordinal=0,
        unit_kind="result_occurrence",
        occurrence_sha256=_OCCURRENCES[0],
        occurrence_ordinal=0,
    )
    foreign_inventory = ExpectedValueUnitInventoryV1.build(
        raw_authority_bundle_sha256="0" * 64,
        units=(foreign_unit,),
    )

    with pytest.raises(LosslessOwnershipError, match="foreign bundle"):
        _authority_with(authority, expected_unit_inventory=foreign_inventory)
    foreign_binding = _unsafe_reseal(
        authority.bindings[0],
        digest_field="binding_sha256",
        changes={"raw_authority_bundle_sha256": "0" * 64},
    )
    with pytest.raises(LosslessOwnershipError, match="orphaned, foreign, or reordered"):
        _authority_with(authority, bindings=(foreign_binding, *authority.bindings[1:]))


def test_binding_and_partition_builders_reject_cross_observation_units() -> None:
    authority = _authority()
    unit = authority.expected_unit_inventory.units[3]
    assignment = authority.representation_assignments[3]

    with pytest.raises(LosslessOwnershipError, match="foreign observation"):
        LosslessOwnershipBindingV1.build(
            raw_authority_bundle_sha256=_RAW,
            observation_record_sha256=_OBSERVATION_RECORDS[0],
            observation_sha256=_OBSERVATIONS[0],
            observation_ordinal=0,
            binding_ordinal=0,
            observation_record_ordinal=0,
            partition_ordinal=0,
            source_record_sha256=_SOURCE_RECORDS[0],
            expected_unit=unit,
            assignment=assignment,
        )
    with pytest.raises(LosslessOwnershipError, match="foreign owner"):
        _partition(
            observation_ordinal=0,
            partition_ordinal=0,
            observation_partition_ordinal=0,
            partition_kind="result_occurrence",
            bindings=(),
            unit=unit,
            assignment=assignment,
        )


def test_assignment_omission_reorder_and_source_kind_mismatch_fail_closed() -> None:
    authority = _authority()

    with pytest.raises(LosslessOwnershipError, match="denominator"):
        _authority_with(
            authority,
            representation_assignments=authority.representation_assignments[:-1],
        )
    with pytest.raises(LosslessOwnershipError, match="expected-unit replay"):
        _authority_with(
            authority,
            representation_assignments=(
                authority.representation_assignments[1],
                authority.representation_assignments[0],
                *authority.representation_assignments[2:],
            ),
        )
    wrong_source = _assignment(
        authority.expected_unit_inventory.units[0],
        source_input_kind="declared_bodyless_packet",
        representation_kind="rectangular_result_cells_v1",
    )
    with pytest.raises(LosslessOwnershipError):
        _authority_with(
            authority,
            representation_assignments=(wrong_source, *authority.representation_assignments[1:]),
        )


def test_partition_record_root_coordinated_reseal_cannot_forge_children() -> None:
    authority = _authority()
    forged = _unsafe_reseal(
        authority.partitions[0],
        digest_field="partition_sha256",
        changes={"record_root_sha256": "0" * 64},
    )

    with pytest.raises(LosslessOwnershipError, match="roots differ"):
        _authority_with(authority, partitions=(forged, *authority.partitions[1:]))


def test_positive_partition_cannot_claim_either_empty_child_root() -> None:
    authority = _authority()

    with pytest.raises(LosslessOwnershipError, match="zero proof"):
        _unsafe_reseal(
            authority.partitions[0],
            digest_field="partition_sha256",
            changes={
                "binding_root_sha256": authority.partitions[1].binding_root_sha256,
            },
        )


def test_observation_partition_root_coordinated_reseal_cannot_forge_children() -> None:
    authority = _authority()
    forged = _unsafe_reseal(
        authority.observations[0],
        digest_field="observation_ownership_sha256",
        changes={"partition_root_sha256": "0" * 64},
    )

    with pytest.raises(LosslessOwnershipError, match="differs from its exact partitions"):
        _authority_with(authority, observations=(forged, *authority.observations[1:]))


def test_receipt_root_coordinated_reseal_cannot_forge_authority() -> None:
    authority = _authority()
    values = {
        key: value
        for key, value in authority.receipt.to_row().items()
        if key not in {"schema_version", "receipt_sha256"}
    }
    values["partition_root_sha256"] = "0" * 64
    forged = LosslessOwnershipReceiptV1.build(**values)

    with pytest.raises(LosslessOwnershipError, match="reconstructed closure"):
        _authority_with(authority, receipt=forged)


def test_partition_and_observation_reorder_fail_closed() -> None:
    authority = _authority()

    with pytest.raises(LosslessOwnershipError, match="foreign owner or order"):
        _authority_with(
            authority,
            partitions=(
                authority.partitions[1],
                authority.partitions[0],
                *authority.partitions[2:],
            ),
        )
    with pytest.raises(LosslessOwnershipError, match="foreign or reordered"):
        _authority_with(
            authority,
            observations=(
                authority.observations[1],
                authority.observations[0],
                authority.observations[2],
            ),
        )


def test_response_and_occurrence_zero_partition_algebra_is_exact() -> None:
    authority = _authority()
    empty_occurrence = authority.partitions[1]
    empty_residual = authority.partitions[4]
    fixed_zero = authority.partitions[5]

    assert empty_occurrence.unit_sha256 is not None
    assert empty_occurrence.assignment_sha256 is not None
    assert empty_residual.unit_sha256 is None
    assert empty_residual.assignment_sha256 is None
    assert fixed_zero.unit_sha256 is not None
    assert fixed_zero.assignment_sha256 is not None
    assert fixed_zero.record_count == 0
    with pytest.raises(LosslessOwnershipError, match="zero/unit shape"):
        _partition(
            observation_ordinal=0,
            partition_ordinal=2,
            observation_partition_ordinal=2,
            partition_kind="response_residual",
            bindings=(),
            unit=authority.expected_unit_inventory.units[2],
            assignment=authority.representation_assignments[2],
        )
    with pytest.raises(LosslessOwnershipError, match="fixed-zero"):
        _partition(
            observation_ordinal=2,
            partition_ordinal=5,
            observation_partition_ordinal=0,
            partition_kind="response_fixed_zero",
            bindings=(),
            unit=authority.expected_unit_inventory.units[4],
            assignment=authority.representation_assignments[4],
        )


def test_positive_residual_cannot_omit_its_unit_assignment() -> None:
    authority = _authority()
    residual_binding = authority.bindings[1]

    with pytest.raises(LosslessOwnershipError, match="cross-owner"):
        _partition(
            observation_ordinal=0,
            partition_ordinal=2,
            observation_partition_ordinal=2,
            partition_kind="response_residual",
            bindings=(residual_binding,),
        )


def test_observation_requires_occurrences_then_exactly_one_response_partition() -> None:
    authority = _authority()

    with pytest.raises(LosslessOwnershipError, match="exactly one response"):
        LosslessObservationOwnershipV1.build(
            raw_authority_bundle_sha256=_RAW,
            observation_record_sha256=_OBSERVATION_RECORDS[0],
            observation_sha256=_OBSERVATIONS[0],
            observation_ordinal=0,
            source_input_kind="parser_input_body",
            partitions=authority.partitions[:2],
            bindings=(authority.bindings[0], authority.bindings[2]),
        )
    with pytest.raises(LosslessOwnershipError, match="partition order or ownership"):
        LosslessObservationOwnershipV1.build(
            raw_authority_bundle_sha256=_RAW,
            observation_record_sha256=_OBSERVATION_RECORDS[0],
            observation_sha256=_OBSERVATIONS[0],
            observation_ordinal=0,
            source_input_kind="parser_input_body",
            partitions=(authority.partitions[2], authority.partitions[2]),
            bindings=(authority.bindings[1],),
        )


def test_bool_integer_subclasses_and_bounds_are_rejected_before_authority() -> None:
    authority = _authority()
    unit = authority.expected_unit_inventory.units[0]
    assignment = authority.representation_assignments[0]

    with pytest.raises(LosslessOwnershipError, match="exact integer"):
        LosslessOwnershipBindingV1.build(
            raw_authority_bundle_sha256=_RAW,
            observation_record_sha256=_OBSERVATION_RECORDS[0],
            observation_sha256=_OBSERVATIONS[0],
            observation_ordinal=0,
            binding_ordinal=True,  # type: ignore[arg-type]
            observation_record_ordinal=0,
            partition_ordinal=0,
            source_record_sha256=_SOURCE_RECORDS[0],
            expected_unit=unit,
            assignment=assignment,
        )
    with pytest.raises(LosslessOwnershipError, match="response partition kind"):
        _unsafe_reseal(
            authority.observations[0],
            digest_field="observation_ownership_sha256",
            changes={"response_partition_kind": _TextSubclass("response_residual")},
        )
    with pytest.raises(LosslessOwnershipError, match="exact integer"):
        LosslessOwnershipBindingV1.build(
            raw_authority_bundle_sha256=_RAW,
            observation_record_sha256=_OBSERVATION_RECORDS[0],
            observation_sha256=_OBSERVATIONS[0],
            observation_ordinal=0,
            binding_ordinal=MAX_LOSSLESS_OWNERSHIP_BINDINGS,
            observation_record_ordinal=0,
            partition_ordinal=0,
            source_record_sha256=_SOURCE_RECORDS[0],
            expected_unit=unit,
            assignment=assignment,
        )


def test_receipt_cross_child_aggregate_algebra_rejects_false_counts() -> None:
    authority = _authority()
    values = {
        key: value
        for key, value in authority.receipt.to_row().items()
        if key not in {"schema_version", "receipt_sha256"}
    }
    values["expected_unit_count"] = 6

    with pytest.raises(LosslessOwnershipError, match="aggregate denominators"):
        LosslessOwnershipReceiptV1.build(**values)


def test_kernel_has_no_stats_live_raw_builder_or_adapter_imports() -> None:
    source = Path(ownership_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}

    assert imports.isdisjoint(
        {
            "nbadb.contracts.stats_lossless_value_authority",
            "nbadb.contracts.live_lossless_value_authority",
            "nbadb.contracts.raw_request_authority",
            "nbadb.contracts.raw_result_cell_authority",
            "nbadb.extract",
            "nbadb.orchestrate",
            "nbadb.schemas",
        }
    )
    assert set(ownership_module.__all__) == {
        "LOSSLESS_OWNERSHIP_SCHEMA_VERSION",
        "MAX_LOSSLESS_OWNERSHIP_BINDINGS",
        "MAX_LOSSLESS_OWNERSHIP_OBSERVATIONS",
        "MAX_LOSSLESS_OWNERSHIP_PARTITIONS",
        "LosslessObservationOwnershipV1",
        "LosslessOwnershipAuthorityV1",
        "LosslessOwnershipBindingKindV1",
        "LosslessOwnershipBindingV1",
        "LosslessOwnershipError",
        "LosslessOwnershipPartitionV1",
        "LosslessOwnershipReceiptV1",
        "build_lossless_ownership_authority",
    }


def test_receipt_reconstruction_does_not_rescan_full_child_inventories() -> None:
    source = Path(ownership_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    derive = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_derive_receipt"
    )
    forbidden_full_scans = {"exact_bindings", "exact_partitions"}
    for outer_loop in (node for node in ast.walk(derive) if isinstance(node, ast.For)):
        nested = (
            child
            for statement in outer_loop.body
            for child in ast.walk(statement)
            if isinstance(child, ast.comprehension)
        )
        assert not any(
            isinstance(comprehension.iter, ast.Name)
            and comprehension.iter.id in forbidden_full_scans
            for comprehension in nested
        )
