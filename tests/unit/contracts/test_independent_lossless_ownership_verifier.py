from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest

import nbadb.contracts.independent_lossless_ownership_verifier as verifier_module
from nbadb.contracts.independent_lossless_ownership_verifier import (
    FROZEN_LOSSLESS_OWNERSHIP_SOURCE_SHA256,
    FROZEN_LOSSLESS_OWNERSHIP_TEST_SHA256,
    IndependentLosslessOwnershipVerifierError,
    verify_independent_lossless_ownership,
)
from nbadb.contracts.lossless_ownership import (
    LosslessObservationOwnershipV1,
    LosslessOwnershipBindingV1,
    LosslessOwnershipPartitionV1,
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
_SOURCES = ("b" * 64, "c" * 64, "d" * 64, "e" * 64)
_FIXED_LANDING = "f" * 64


class _TextSubclass(str):
    pass


class _TupleSubclass(tuple[object, ...]):
    pass


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _ordered_root(*, kind: str, items: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    digest.update(b'{"count":')
    digest.update(str(len(items)).encode("ascii"))
    digest.update(b',"items":[')
    for ordinal, item in enumerate(items):
        if ordinal:
            digest.update(b",")
        digest.update(_canonical_bytes(item))
    digest.update(b'],"kind":')
    digest.update(_canonical_bytes(kind))
    digest.update(b',"schema_version":1}')
    return digest.hexdigest()


def _unit(
    *,
    unit_ordinal: int,
    observation_ordinal: int,
    unit_kind: str,
    occurrence_ordinal: int | None = None,
) -> ExpectedValueUnitV1:
    occurrence_index = (
        None
        if occurrence_ordinal is None
        else occurrence_ordinal
        if observation_ordinal == 0
        else 2
    )
    return ExpectedValueUnitV1.build(
        raw_authority_bundle_sha256=_RAW,
        unit_ordinal=unit_ordinal,
        observation_sha256=_OBSERVATIONS[observation_ordinal],
        observation_ordinal=observation_ordinal,
        unit_kind=unit_kind,  # type: ignore[arg-type]
        occurrence_sha256=(None if occurrence_index is None else _OCCURRENCES[occurrence_index]),
        occurrence_ordinal=occurrence_ordinal,
    )


def _assignment(
    unit: ExpectedValueUnitV1,
    *,
    representation_kind: str,
) -> ValueRepresentationAssignmentV1:
    return ValueRepresentationAssignmentV1.build(
        expected_unit=unit,
        source_input_kind="parser_input_body",
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


def _fixture(*, second_representation: str = "live_lossless_nodes_v1") -> dict[str, object]:
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
        _assignment(units[0], representation_kind="rectangular_result_cells_v1"),
        _assignment(units[1], representation_kind="stats_lossless_records_v1"),
        _assignment(units[2], representation_kind="response_lossless_records_v1"),
        _assignment(units[3], representation_kind=second_representation),
        _assignment(units[4], representation_kind="response_fixed_zero_v1"),
    )
    bindings = (
        _binding(
            unit=units[0],
            assignment=assignments[0],
            binding_ordinal=0,
            observation_record_ordinal=0,
            partition_ordinal=0,
            source_record_sha256=_SOURCES[0],
        ),
        _binding(
            unit=units[2],
            assignment=assignments[2],
            binding_ordinal=1,
            observation_record_ordinal=1,
            partition_ordinal=2,
            source_record_sha256=_SOURCES[1],
        ),
        _binding(
            unit=units[0],
            assignment=assignments[0],
            binding_ordinal=2,
            observation_record_ordinal=2,
            partition_ordinal=0,
            source_record_sha256=_SOURCES[2],
        ),
        _binding(
            unit=units[3],
            assignment=assignments[3],
            binding_ordinal=3,
            observation_record_ordinal=0,
            partition_ordinal=3,
            source_record_sha256=_SOURCES[3],
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
            fixed_zero_landing_sha256=_FIXED_LANDING,
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
            source_input_kind="parser_input_body",
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
    inventory = ExpectedValueUnitInventoryV1.build(
        raw_authority_bundle_sha256=_RAW,
        units=units,
    )
    authority = build_lossless_ownership_authority(
        raw_authority_bundle_sha256=_RAW,
        expected_unit_inventory=inventory,
        representation_assignments=assignments,
        observations=observations,
        partitions=partitions,
        bindings=bindings,
    )

    raw_occurrence_ids = (
        (_OCCURRENCES[0], _OCCURRENCES[1]),
        (_OCCURRENCES[2],),
        (),
    )
    raw_landing_ids = ((), (), (_FIXED_LANDING,))
    source_families = (
        ("stats", "live", "live")
        if second_representation == "live_lossless_nodes_v1"
        else ("stats", "stats", "stats")
    )
    raw_observations = tuple(
        {
            "schema_version": 2,
            "observation_sha256": _OBSERVATIONS[ordinal],
            "observation_record_sha256": _OBSERVATION_RECORDS[ordinal],
            "logical_invocation_sha256": _RAW,
            "semantic_request_sha256": _SOURCES[2],
            "provider_call_ordinal": ordinal,
            "page_ordinal": None,
            "provider_call_role": "primary",
            "provider_call_sha256": f"{ordinal}" * 64,
            "retry_ordinal": 0,
            "request_ordinal": ordinal,
            "source_family": source_families[ordinal],
            "lifecycle": "selected_terminal",
            "outcome": "success_empty" if ordinal == 2 else "success_nonempty",
            "body_disposition": "public_parser_input",
            "result_occurrence_count": len(raw_occurrence_ids[ordinal]),
            "result_occurrences_sha256": _canonical_sha(list(raw_occurrence_ids[ordinal])),
            "route_landing_count": len(raw_landing_ids[ordinal]),
            "route_landings_sha256": _canonical_sha(list(raw_landing_ids[ordinal])),
        }
        for ordinal in range(3)
    )
    raw_occurrences = (
        {
            "schema_version": 2,
            "occurrence_sha256": _OCCURRENCES[0],
            "observation_sha256": _OBSERVATIONS[0],
            "occurrence_ordinal": 0,
            "landing_disposition": "wide_only",
        },
        {
            "schema_version": 2,
            "occurrence_sha256": _OCCURRENCES[1],
            "observation_sha256": _OBSERVATIONS[0],
            "occurrence_ordinal": 1,
            "landing_disposition": "lossless_only",
        },
        {
            "schema_version": 2,
            "occurrence_sha256": _OCCURRENCES[2],
            "observation_sha256": _OBSERVATIONS[1],
            "occurrence_ordinal": 0,
            "landing_disposition": "lossless_only",
        },
    )
    raw_landings = (
        {
            "schema_version": 2,
            "landing_sha256": _FIXED_LANDING,
            "observation_sha256": _OBSERVATIONS[2],
            "route_ordinal": 0,
            "landing_semantic": "response_fixed_zero",
            "source_occurrence_count": 0,
            "source_occurrences_sha256": _canonical_sha([]),
            "persisted_row_count": 0,
        },
    )
    result_cells = (
        {
            "schema_version": 2,
            "cell_sha256": _SOURCES[0],
            "observation_sha256": _OBSERVATIONS[0],
            "occurrence_sha256": _OCCURRENCES[0],
            "cell_ordinal": 0,
        },
        {
            "schema_version": 2,
            "cell_sha256": _SOURCES[2],
            "observation_sha256": _OBSERVATIONS[0],
            "occurrence_sha256": _OCCURRENCES[0],
            "cell_ordinal": 1,
        },
    )
    stats_rows = (
        {
            "schema_version": 1,
            "record_sha256": _SOURCES[1],
            "raw_authority_bundle_sha256": _RAW,
            "observation_record_sha256": _OBSERVATION_RECORDS[0],
            "observation_sha256": _OBSERVATIONS[0],
            "global_record_ordinal": 0,
            "owner_kind": "response_residual",
            "occurrence_sha256": None,
            "representation_kind": "response_lossless_records_v1",
        },
        *(
            (
                {
                    "schema_version": 1,
                    "record_sha256": _SOURCES[3],
                    "raw_authority_bundle_sha256": _RAW,
                    "observation_record_sha256": _OBSERVATION_RECORDS[1],
                    "observation_sha256": _OBSERVATIONS[1],
                    "global_record_ordinal": 0,
                    "owner_kind": "result_occurrence",
                    "occurrence_sha256": _OCCURRENCES[2],
                    "representation_kind": "stats_lossless_records_v1",
                },
            )
            if second_representation == "stats_lossless_records_v1"
            else ()
        ),
    )
    local_live_unit = ExpectedValueUnitV1.build(
        raw_authority_bundle_sha256=_RAW,
        unit_ordinal=0,
        observation_sha256=_OBSERVATIONS[1],
        observation_ordinal=0,
        unit_kind="result_occurrence",
        occurrence_sha256=_OCCURRENCES[2],
        occurrence_ordinal=0,
    )
    local_live_assignment = ValueRepresentationAssignmentV1.build(
        expected_unit=local_live_unit,
        source_input_kind="parser_input_body",
        representation_kind="live_lossless_nodes_v1",
    )
    live_rows = (
        (
            {
                "schema_version": 1,
                "source_item_sha256": _SOURCES[3],
                "raw_authority_bundle_sha256": _RAW,
                "observation_record_sha256": _OBSERVATION_RECORDS[1],
                "observation_sha256": _OBSERVATIONS[1],
                "global_record_ordinal": 0,
                "observation_record_ordinal": 0,
                "ownership_kind": "result_occurrence",
                "raw_occurrence_sha256": _OCCURRENCES[2],
                "representation_kind": "live_lossless_nodes_v1",
                "expected_unit_sha256": local_live_unit.unit_sha256,
                "expected_unit_ordinal": 0,
                "representation_assignment_sha256": local_live_assignment.assignment_sha256,
            },
        )
        if second_representation == "live_lossless_nodes_v1"
        else ()
    )
    return {
        "authority": authority,
        "expected_raw_authority_bundle_sha256": _RAW,
        "expected_ownership_receipt_sha256": authority.receipt.receipt_sha256,
        "lossless_ownership_source_sha256": FROZEN_LOSSLESS_OWNERSHIP_SOURCE_SHA256,
        "lossless_ownership_test_sha256": FROZEN_LOSSLESS_OWNERSHIP_TEST_SHA256,
        "raw_observation_rows": raw_observations,
        "raw_occurrence_rows": raw_occurrences,
        "raw_landing_rows": raw_landings,
        "result_cell_rows": result_cells,
        "stats_lossless_rows": stats_rows,
        "live_lossless_rows": live_rows,
        "expected_unit_inventory_row": inventory.to_row(),
        "expected_unit_rows": tuple(unit.to_row() for unit in units),
        "representation_assignment_rows": tuple(item.to_row() for item in assignments),
        "ownership_observation_rows": tuple(item.to_row() for item in observations),
        "ownership_partition_rows": tuple(item.to_row() for item in partitions),
        "ownership_binding_rows": tuple(item.to_row() for item in bindings),
        "ownership_receipt_row": authority.receipt.to_row(),
    }


def _large_inventory_fixture(*, unit_count: int = 200) -> dict[str, object]:
    observation_sha256 = _canonical_sha("large-inventory-observation")
    observation_record_sha256 = _canonical_sha("large-inventory-observation-record")
    semantic_request_sha256 = _canonical_sha("large-inventory-semantic-request")
    provider_call_sha256 = _canonical_sha("large-inventory-provider-call")
    occurrence_sha256s = tuple(
        _canonical_sha(f"large-inventory-occurrence:{ordinal}") for ordinal in range(unit_count)
    )
    units = tuple(
        ExpectedValueUnitV1.build(
            raw_authority_bundle_sha256=_RAW,
            unit_ordinal=ordinal,
            observation_sha256=observation_sha256,
            observation_ordinal=0,
            unit_kind="result_occurrence",
            occurrence_sha256=occurrence_sha256,
            occurrence_ordinal=ordinal,
        )
        for ordinal, occurrence_sha256 in enumerate(occurrence_sha256s)
    )
    assignments = tuple(
        _assignment(unit, representation_kind="rectangular_result_cells_v1") for unit in units
    )
    occurrence_partitions = tuple(
        LosslessOwnershipPartitionV1.build(
            raw_authority_bundle_sha256=_RAW,
            observation_record_sha256=observation_record_sha256,
            observation_sha256=observation_sha256,
            observation_ordinal=0,
            partition_ordinal=ordinal,
            observation_partition_ordinal=ordinal,
            partition_kind="result_occurrence",
            bindings=(),
            expected_unit=unit,
            assignment=assignment,
        )
        for ordinal, (unit, assignment) in enumerate(zip(units, assignments, strict=True))
    )
    zero_residual_partition = LosslessOwnershipPartitionV1.build(
        raw_authority_bundle_sha256=_RAW,
        observation_record_sha256=observation_record_sha256,
        observation_sha256=observation_sha256,
        observation_ordinal=0,
        partition_ordinal=unit_count,
        observation_partition_ordinal=unit_count,
        partition_kind="response_residual",
        bindings=(),
    )
    partitions = (*occurrence_partitions, zero_residual_partition)
    observation = LosslessObservationOwnershipV1.build(
        raw_authority_bundle_sha256=_RAW,
        observation_record_sha256=observation_record_sha256,
        observation_sha256=observation_sha256,
        observation_ordinal=0,
        source_input_kind="parser_input_body",
        partitions=partitions,
        bindings=(),
    )
    inventory = ExpectedValueUnitInventoryV1.build(
        raw_authority_bundle_sha256=_RAW,
        units=units,
    )
    authority = build_lossless_ownership_authority(
        raw_authority_bundle_sha256=_RAW,
        expected_unit_inventory=inventory,
        representation_assignments=assignments,
        observations=(observation,),
        partitions=partitions,
        bindings=(),
    )
    raw_observation = {
        "schema_version": 2,
        "observation_sha256": observation_sha256,
        "observation_record_sha256": observation_record_sha256,
        "logical_invocation_sha256": _RAW,
        "semantic_request_sha256": semantic_request_sha256,
        "provider_call_ordinal": 0,
        "page_ordinal": None,
        "provider_call_role": "primary",
        "provider_call_sha256": provider_call_sha256,
        "retry_ordinal": 0,
        "request_ordinal": 0,
        "source_family": "stats",
        "lifecycle": "selected_terminal",
        "outcome": "success_nonempty",
        "body_disposition": "public_parser_input",
        "result_occurrence_count": unit_count,
        "result_occurrences_sha256": _canonical_sha(list(occurrence_sha256s)),
        "route_landing_count": 0,
        "route_landings_sha256": _canonical_sha([]),
    }
    raw_occurrences = tuple(
        {
            "schema_version": 2,
            "occurrence_sha256": occurrence_sha256,
            "observation_sha256": observation_sha256,
            "occurrence_ordinal": ordinal,
            "landing_disposition": "wide_only",
        }
        for ordinal, occurrence_sha256 in enumerate(occurrence_sha256s)
    )
    return {
        "authority": authority,
        "expected_raw_authority_bundle_sha256": _RAW,
        "expected_ownership_receipt_sha256": authority.receipt.receipt_sha256,
        "lossless_ownership_source_sha256": FROZEN_LOSSLESS_OWNERSHIP_SOURCE_SHA256,
        "lossless_ownership_test_sha256": FROZEN_LOSSLESS_OWNERSHIP_TEST_SHA256,
        "raw_observation_rows": (raw_observation,),
        "raw_occurrence_rows": raw_occurrences,
        "raw_landing_rows": (),
        "result_cell_rows": (),
        "stats_lossless_rows": (),
        "live_lossless_rows": (),
        "expected_unit_inventory_row": inventory.to_row(),
        "expected_unit_rows": tuple(unit.to_row() for unit in units),
        "representation_assignment_rows": tuple(item.to_row() for item in assignments),
        "ownership_observation_rows": (observation.to_row(),),
        "ownership_partition_rows": tuple(item.to_row() for item in partitions),
        "ownership_binding_rows": (),
        "ownership_receipt_row": authority.receipt.to_row(),
    }


def _intervening_zero_live_fixture() -> dict[str, object]:
    observation_sha256s = tuple(
        _canonical_sha(f"intervening-live-observation:{ordinal}") for ordinal in range(3)
    )
    observation_record_sha256s = tuple(
        _canonical_sha(f"intervening-live-record:{ordinal}") for ordinal in range(3)
    )
    occurrence_sha256s = tuple(
        _canonical_sha(f"intervening-live-occurrence:{ordinal}") for ordinal in range(3)
    )
    source_sha256s = tuple(
        _canonical_sha(f"intervening-live-source:{ordinal}") for ordinal in range(3)
    )

    units = tuple(
        ExpectedValueUnitV1.build(
            raw_authority_bundle_sha256=_RAW,
            unit_ordinal=unit_ordinal,
            observation_sha256=observation_sha256s[observation_ordinal],
            observation_ordinal=observation_ordinal,
            unit_kind=unit_kind,  # type: ignore[arg-type]
            occurrence_sha256=(
                occurrence_sha256s[observation_ordinal]
                if unit_kind == "result_occurrence"
                else None
            ),
            occurrence_ordinal=(0 if unit_kind == "result_occurrence" else None),
        )
        for unit_ordinal, observation_ordinal, unit_kind in (
            (0, 0, "result_occurrence"),
            (1, 1, "result_occurrence"),
            (2, 2, "result_occurrence"),
            (3, 2, "response_residual"),
        )
    )
    assignments = tuple(
        ValueRepresentationAssignmentV1.build(
            expected_unit=unit,
            source_input_kind="parser_input_body",
            representation_kind=representation_kind,  # type: ignore[arg-type]
        )
        for unit, representation_kind in zip(
            units,
            (
                "rectangular_result_cells_v1",
                "live_lossless_nodes_v1",
                "live_lossless_nodes_v1",
                "response_lossless_records_v1",
            ),
            strict=True,
        )
    )
    binding_specs = (
        (units[0], assignments[0], 0, 0, 0, source_sha256s[0]),
        (units[2], assignments[2], 1, 0, 4, source_sha256s[1]),
        (units[3], assignments[3], 2, 1, 5, source_sha256s[2]),
    )
    bindings = tuple(
        LosslessOwnershipBindingV1.build(
            raw_authority_bundle_sha256=_RAW,
            observation_record_sha256=observation_record_sha256s[unit.observation_ordinal],
            observation_sha256=unit.observation_sha256,
            observation_ordinal=unit.observation_ordinal,
            binding_ordinal=binding_ordinal,
            observation_record_ordinal=observation_record_ordinal,
            partition_ordinal=partition_ordinal,
            source_record_sha256=source_record_sha256,
            expected_unit=unit,
            assignment=assignment,
        )
        for (
            unit,
            assignment,
            binding_ordinal,
            observation_record_ordinal,
            partition_ordinal,
            source_record_sha256,
        ) in binding_specs
    )

    partition_specs = (
        (0, 0, 0, "result_occurrence", (bindings[0],), units[0], assignments[0]),
        (0, 1, 1, "response_residual", (), None, None),
        (1, 2, 0, "result_occurrence", (), units[1], assignments[1]),
        (1, 3, 1, "response_residual", (), None, None),
        (2, 4, 0, "result_occurrence", (bindings[1],), units[2], assignments[2]),
        (2, 5, 1, "response_residual", (bindings[2],), units[3], assignments[3]),
    )
    partitions = tuple(
        LosslessOwnershipPartitionV1.build(
            raw_authority_bundle_sha256=_RAW,
            observation_record_sha256=observation_record_sha256s[observation_ordinal],
            observation_sha256=observation_sha256s[observation_ordinal],
            observation_ordinal=observation_ordinal,
            partition_ordinal=partition_ordinal,
            observation_partition_ordinal=observation_partition_ordinal,
            partition_kind=partition_kind,  # type: ignore[arg-type]
            bindings=partition_bindings,
            expected_unit=unit,
            assignment=assignment,
        )
        for (
            observation_ordinal,
            partition_ordinal,
            observation_partition_ordinal,
            partition_kind,
            partition_bindings,
            unit,
            assignment,
        ) in partition_specs
    )
    observations = tuple(
        LosslessObservationOwnershipV1.build(
            raw_authority_bundle_sha256=_RAW,
            observation_record_sha256=observation_record_sha256s[observation_ordinal],
            observation_sha256=observation_sha256s[observation_ordinal],
            observation_ordinal=observation_ordinal,
            source_input_kind="parser_input_body",
            partitions=partitions[observation_ordinal * 2 : (observation_ordinal + 1) * 2],
            bindings=(
                (bindings[0],)
                if observation_ordinal == 0
                else bindings[1:]
                if observation_ordinal == 2
                else ()
            ),
        )
        for observation_ordinal in range(3)
    )
    inventory = ExpectedValueUnitInventoryV1.build(
        raw_authority_bundle_sha256=_RAW,
        units=units,
    )
    authority = build_lossless_ownership_authority(
        raw_authority_bundle_sha256=_RAW,
        expected_unit_inventory=inventory,
        representation_assignments=assignments,
        observations=observations,
        partitions=partitions,
        bindings=bindings,
    )

    raw_observations = tuple(
        {
            "schema_version": 2,
            "observation_sha256": observation_sha256s[ordinal],
            "observation_record_sha256": observation_record_sha256s[ordinal],
            "logical_invocation_sha256": _RAW,
            "semantic_request_sha256": _canonical_sha("intervening-live-semantic-request"),
            "provider_call_ordinal": ordinal,
            "page_ordinal": None,
            "provider_call_role": "primary",
            "provider_call_sha256": _canonical_sha(f"intervening-live-call:{ordinal}"),
            "retry_ordinal": 0,
            "request_ordinal": ordinal,
            "source_family": "stats" if ordinal == 0 else "live",
            "lifecycle": "selected_terminal",
            "outcome": "success_nonempty",
            "body_disposition": "public_parser_input",
            "result_occurrence_count": 1,
            "result_occurrences_sha256": _canonical_sha([occurrence_sha256s[ordinal]]),
            "route_landing_count": 0,
            "route_landings_sha256": _canonical_sha([]),
        }
        for ordinal in range(3)
    )
    raw_occurrences = tuple(
        {
            "schema_version": 2,
            "occurrence_sha256": occurrence_sha256s[ordinal],
            "observation_sha256": observation_sha256s[ordinal],
            "occurrence_ordinal": 0,
            "landing_disposition": "wide_only" if ordinal == 0 else "lossless_only",
        }
        for ordinal in range(3)
    )
    result_cells = (
        {
            "schema_version": 2,
            "cell_sha256": source_sha256s[0],
            "observation_sha256": observation_sha256s[0],
            "occurrence_sha256": occurrence_sha256s[0],
            "cell_ordinal": 0,
        },
    )
    local_units = (
        ExpectedValueUnitV1.build(
            raw_authority_bundle_sha256=_RAW,
            unit_ordinal=0,
            observation_sha256=observation_sha256s[1],
            observation_ordinal=0,
            unit_kind="result_occurrence",
            occurrence_sha256=occurrence_sha256s[1],
            occurrence_ordinal=0,
        ),
        ExpectedValueUnitV1.build(
            raw_authority_bundle_sha256=_RAW,
            unit_ordinal=1,
            observation_sha256=observation_sha256s[2],
            observation_ordinal=1,
            unit_kind="result_occurrence",
            occurrence_sha256=occurrence_sha256s[2],
            occurrence_ordinal=0,
        ),
        ExpectedValueUnitV1.build(
            raw_authority_bundle_sha256=_RAW,
            unit_ordinal=2,
            observation_sha256=observation_sha256s[2],
            observation_ordinal=1,
            unit_kind="response_residual",
        ),
    )
    local_assignments = tuple(
        ValueRepresentationAssignmentV1.build(
            expected_unit=unit,
            source_input_kind="parser_input_body",
            representation_kind=(
                "response_lossless_records_v1"
                if unit.unit_kind == "response_residual"
                else "live_lossless_nodes_v1"
            ),
        )
        for unit in local_units
    )
    live_rows = (
        {
            "schema_version": 1,
            "source_item_sha256": source_sha256s[1],
            "raw_authority_bundle_sha256": _RAW,
            "observation_record_sha256": observation_record_sha256s[2],
            "observation_sha256": observation_sha256s[2],
            "global_record_ordinal": 0,
            "observation_record_ordinal": 0,
            "ownership_kind": "result_occurrence",
            "raw_occurrence_sha256": occurrence_sha256s[2],
            "representation_kind": "live_lossless_nodes_v1",
            "expected_unit_sha256": local_units[1].unit_sha256,
            "expected_unit_ordinal": 1,
            "representation_assignment_sha256": local_assignments[1].assignment_sha256,
        },
        {
            "schema_version": 1,
            "source_item_sha256": source_sha256s[2],
            "raw_authority_bundle_sha256": _RAW,
            "observation_record_sha256": observation_record_sha256s[2],
            "observation_sha256": observation_sha256s[2],
            "global_record_ordinal": 1,
            "observation_record_ordinal": 1,
            "ownership_kind": "response_residual",
            "raw_occurrence_sha256": None,
            "representation_kind": "response_lossless_records_v1",
            "expected_unit_sha256": local_units[2].unit_sha256,
            "expected_unit_ordinal": 2,
            "representation_assignment_sha256": local_assignments[2].assignment_sha256,
        },
    )
    return {
        "authority": authority,
        "expected_raw_authority_bundle_sha256": _RAW,
        "expected_ownership_receipt_sha256": authority.receipt.receipt_sha256,
        "lossless_ownership_source_sha256": FROZEN_LOSSLESS_OWNERSHIP_SOURCE_SHA256,
        "lossless_ownership_test_sha256": FROZEN_LOSSLESS_OWNERSHIP_TEST_SHA256,
        "raw_observation_rows": raw_observations,
        "raw_occurrence_rows": raw_occurrences,
        "raw_landing_rows": (),
        "result_cell_rows": result_cells,
        "stats_lossless_rows": (),
        "live_lossless_rows": live_rows,
        "expected_unit_inventory_row": inventory.to_row(),
        "expected_unit_rows": tuple(unit.to_row() for unit in units),
        "representation_assignment_rows": tuple(item.to_row() for item in assignments),
        "ownership_observation_rows": tuple(item.to_row() for item in observations),
        "ownership_partition_rows": tuple(item.to_row() for item in partitions),
        "ownership_binding_rows": tuple(item.to_row() for item in bindings),
        "ownership_receipt_row": authority.receipt.to_row(),
    }


def _verify(values: dict[str, object], **changes: object):
    call = {key: value for key, value in values.items() if key != "authority"}
    call.update(changes)
    return verify_independent_lossless_ownership(**call)


def _reseal(
    row: dict[str, object],
    *,
    kind: str,
    digest_field: str,
    changes: dict[str, object],
) -> dict[str, object]:
    result = dict(row)
    result.update(changes)
    result[digest_field] = _canonical_sha(
        {
            "schema_version": result["schema_version"],
            "kind": kind,
            **{
                key: value
                for key, value in result.items()
                if key not in {"schema_version", digest_field}
            },
        }
    )
    return result


def test_independent_parity_closes_hybrid_zero_occurrence_zero_residual_and_fixed_zero() -> None:
    values = _fixture()
    authority = cast("Any", values["authority"])

    result = _verify(values)

    assert result.ownership_receipt_sha256 == authority.receipt.receipt_sha256
    assert result.expected_unit_inventory_sha256 == authority.receipt.expected_unit_inventory_sha256
    assert result.expected_unit_root_sha256 == authority.receipt.expected_unit_root_sha256
    assert result.observation_count == 3
    assert result.occurrence_count == 3
    assert result.partition_count == 6
    assert result.binding_count == result.source_record_count == 4
    assert result.result_cell_count == 2
    assert result.stats_lossless_record_count == 1
    assert result.live_lossless_record_count == 1
    assert result.source_record_root_sha256 == authority.receipt.source_record_root_sha256
    assert len(result.verification_sha256) == 64


def test_stats_before_live_uses_genuine_side_local_unit_and_assignment_ids() -> None:
    values = _fixture()
    central_units = cast("tuple[dict[str, object], ...]", values["expected_unit_rows"])
    central_assignments = cast(
        "tuple[dict[str, object], ...]", values["representation_assignment_rows"]
    )
    live_row = cast("tuple[dict[str, object], ...]", values["live_lossless_rows"])[0]

    assert live_row["expected_unit_ordinal"] == 0
    assert live_row["expected_unit_sha256"] != central_units[3]["unit_sha256"]
    assert (
        live_row["representation_assignment_sha256"] != central_assignments[3]["assignment_sha256"]
    )
    assert _verify(values).live_lossless_record_count == 1


def test_live_side_vector_excludes_the_central_fixed_zero_unit() -> None:
    values = _fixture()
    raw_observations = cast("tuple[dict[str, object], ...]", values["raw_observation_rows"])
    central_units = cast("tuple[dict[str, object], ...]", values["expected_unit_rows"])
    live_rows = cast("tuple[dict[str, object], ...]", values["live_lossless_rows"])

    assert raw_observations[2]["source_family"] == "live"
    assert central_units[-1]["unit_kind"] == "response_fixed_zero"
    assert all(row["observation_sha256"] != _OBSERVATIONS[2] for row in live_rows)
    assert (
        _verify(values).expected_unit_inventory_sha256
        == cast("Any", values["authority"]).receipt.expected_unit_inventory_sha256
    )


def test_intervening_zero_record_live_occurrence_offsets_later_local_owners() -> None:
    values = _intervening_zero_live_fixture()
    live_rows = cast("tuple[dict[str, object], ...]", values["live_lossless_rows"])

    assert tuple(row["expected_unit_ordinal"] for row in live_rows) == (1, 2)
    assert tuple(row["ownership_kind"] for row in live_rows) == (
        "result_occurrence",
        "response_residual",
    )
    result = _verify(values)

    assert result.observation_count == 3
    assert result.live_lossless_record_count == 2
    assert result.binding_count == 3


def test_public_verifier_accepts_canonical_inventory_larger_than_generic_row_bound() -> None:
    values = _large_inventory_fixture()
    inventory_row = cast("dict[str, object]", values["expected_unit_inventory_row"])
    units_json = cast("str", inventory_row["units_json"])

    encoded_size = len(units_json.encode("utf-8"))
    assert encoded_size > verifier_module._MAX_ROW_BYTES
    assert encoded_size < verifier_module._MAX_INVENTORY_BYTES

    result = _verify(values)

    assert result.expected_unit_inventory_sha256 == inventory_row["inventory_sha256"]
    assert result.observation_count == 1
    assert result.occurrence_count == 200
    assert result.partition_count == 201
    assert result.binding_count == result.source_record_count == 0


def test_inventory_row_envelope_fails_before_recursive_decoder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _fixture()
    inventory_row = dict(cast("dict[str, object]", values["expected_unit_inventory_row"]))
    inventory_row["units_json"] = "x" * 100_001
    decoder_calls = 0

    def bomb_decoder(*_args: object, **_kwargs: object) -> object:
        nonlocal decoder_calls
        decoder_calls += 1
        raise AssertionError("inventory decoder must not run after row-envelope rejection")

    monkeypatch.setattr(verifier_module, "_MAX_INVENTORY_ROW_BYTES", 100_000)
    monkeypatch.setattr(verifier_module.json, "loads", bomb_decoder)
    with pytest.raises(
        IndependentLosslessOwnershipVerifierError,
        match="UTF-8 byte bound",
    ):
        _verify(values, expected_unit_inventory_row=inventory_row)
    assert decoder_calls == 0


def test_generic_projection_rows_retain_the_ordinary_row_bound() -> None:
    values = _fixture()
    raw_observations = list(cast("tuple[dict[str, object], ...]", values["raw_observation_rows"]))
    raw_observations[0] = {
        **raw_observations[0],
        "provider_call_role": "x" * verifier_module._MAX_ROW_BYTES,
    }

    with pytest.raises(
        IndependentLosslessOwnershipVerifierError,
        match="UTF-8 byte bound",
    ):
        _verify(values, raw_observation_rows=tuple(raw_observations))


@pytest.mark.parametrize("depth", (10_000, 50_000))
def test_hostile_inventory_json_depth_fails_without_foreign_recursion(depth: int) -> None:
    values = _fixture()
    inventory = dict(cast("dict[str, object]", values["expected_unit_inventory_row"]))
    inventory["units_json"] = ("[" * depth) + "0"

    with pytest.raises(
        IndependentLosslessOwnershipVerifierError,
        match="lexical depth bound",
    ):
        _verify(values, expected_unit_inventory_row=inventory)


def test_external_pins_fail_before_any_row_inventory_is_traversed() -> None:
    values = _fixture()

    with pytest.raises(
        IndependentLosslessOwnershipVerifierError,
        match="source pin differs",
    ):
        _verify(
            values,
            lossless_ownership_source_sha256="0" * 64,
            raw_observation_rows=_TupleSubclass(),
        )


def test_explicit_zero_residual_partition_cannot_be_omitted() -> None:
    values = _fixture()
    partitions = cast("tuple[dict[str, object], ...]", values["ownership_partition_rows"])

    with pytest.raises(
        IndependentLosslessOwnershipVerifierError,
        match="partition denominator",
    ):
        _verify(values, ownership_partition_rows=partitions[:-2] + partitions[-1:])


def test_fixed_zero_requires_one_exact_empty_raw_landing() -> None:
    values = _fixture()

    with pytest.raises(
        IndependentLosslessOwnershipVerifierError,
        match="landing denominator",
    ):
        _verify(values, raw_landing_rows=())


def test_nonowned_raw_fixed_zero_route_may_coexist_with_nonempty_drift() -> None:
    values = _fixture()
    extra_landing_sha256 = "0" * 64
    raw_observations = list(cast("tuple[dict[str, object], ...]", values["raw_observation_rows"]))
    raw_observations[0] = {
        **raw_observations[0],
        "route_landing_count": 1,
        "route_landings_sha256": _canonical_sha([extra_landing_sha256]),
    }
    raw_landings = cast("tuple[dict[str, object], ...]", values["raw_landing_rows"])
    extra_landing = {
        "schema_version": 2,
        "landing_sha256": extra_landing_sha256,
        "observation_sha256": _OBSERVATIONS[0],
        "route_ordinal": 0,
        "landing_semantic": "response_fixed_zero",
        "source_occurrence_count": 0,
        "source_occurrences_sha256": _canonical_sha([]),
        "persisted_row_count": 0,
    }

    result = _verify(
        values,
        raw_observation_rows=tuple(raw_observations),
        raw_landing_rows=(extra_landing, *raw_landings),
    )

    assert (
        result.ownership_receipt_sha256 == cast("Any", values["authority"]).receipt.receipt_sha256
    )


def test_stats_global_record_ordinal_restarts_per_observation_authority() -> None:
    values = _fixture(second_representation="stats_lossless_records_v1")

    result = _verify(values)

    assert result.stats_lossless_record_count == 2
    assert result.live_lossless_record_count == 0


def test_zero_record_occurrence_representation_is_independently_derived() -> None:
    values = _fixture()
    assignments = cast("tuple[dict[str, object], ...]", values["representation_assignment_rows"])
    forged = _reseal(
        assignments[1],
        kind="nbadb_value_representation_assignment_v1",
        digest_field="assignment_sha256",
        changes={"representation_kind": "rectangular_result_cells_v1"},
    )

    with pytest.raises(
        IndependentLosslessOwnershipVerifierError,
        match="occurrence representation",
    ):
        _verify(
            values,
            representation_assignment_rows=(assignments[0], forged, *assignments[2:]),
        )


def test_live_wide_only_occurrence_remains_live_lossless_owned() -> None:
    values = _fixture()
    occurrences = list(cast("tuple[dict[str, object], ...]", values["raw_occurrence_rows"]))
    occurrences[2] = {**occurrences[2], "landing_disposition": "wide_only"}

    result = _verify(values, raw_occurrence_rows=tuple(occurrences))

    assert result.live_lossless_record_count == 1


def test_source_relations_cannot_cross_raw_source_family() -> None:
    values = _fixture()
    observations = list(cast("tuple[dict[str, object], ...]", values["raw_observation_rows"]))
    observations[1] = {**observations[1], "source_family": "stats"}

    with pytest.raises(
        IndependentLosslessOwnershipVerifierError,
        match="live-lossless source belongs to a foreign bundle or observation",
    ):
        _verify(values, raw_observation_rows=tuple(observations))


def test_zero_record_assignment_source_input_cannot_be_independently_resealed() -> None:
    values = _fixture()
    assignments = cast("tuple[dict[str, object], ...]", values["representation_assignment_rows"])
    forged = _reseal(
        assignments[1],
        kind="nbadb_value_representation_assignment_v1",
        digest_field="assignment_sha256",
        changes={"source_input_kind": "declared_bodyless_packet"},
    )

    with pytest.raises(
        IndependentLosslessOwnershipVerifierError,
        match="raw source-input authority",
    ):
        _verify(
            values,
            representation_assignment_rows=(assignments[0], forged, *assignments[2:]),
        )


def test_orphan_source_and_missing_public_source_both_fail() -> None:
    values = _fixture()
    result_cells = cast("tuple[dict[str, object], ...]", values["result_cell_rows"])

    with pytest.raises(
        IndependentLosslessOwnershipVerifierError,
        match="missing public source",
    ):
        _verify(values, result_cell_rows=result_cells[:1])

    extra = dict(result_cells[-1])
    extra["cell_sha256"] = "0" * 64
    extra["cell_ordinal"] = 2
    with pytest.raises(
        IndependentLosslessOwnershipVerifierError,
        match="orphan or missing",
    ):
        _verify(values, result_cell_rows=(*result_cells, extra))


def test_cross_observation_source_and_cross_bundle_source_fail() -> None:
    values = _fixture()
    result_cells = list(cast("tuple[dict[str, object], ...]", values["result_cell_rows"]))
    result_cells[0] = {**result_cells[0], "observation_sha256": _OBSERVATIONS[1]}
    with pytest.raises(
        IndependentLosslessOwnershipVerifierError,
        match="foreign occurrence or observation",
    ):
        _verify(values, result_cell_rows=tuple(result_cells))

    stats_rows = list(cast("tuple[dict[str, object], ...]", values["stats_lossless_rows"]))
    stats_rows[0] = {**stats_rows[0], "raw_authority_bundle_sha256": "0" * 64}
    with pytest.raises(
        IndependentLosslessOwnershipVerifierError,
        match="foreign bundle or observation",
    ):
        _verify(values, stats_lossless_rows=tuple(stats_rows))


def test_duplicate_source_across_relations_is_rejected() -> None:
    values = _fixture()
    stats_rows = list(cast("tuple[dict[str, object], ...]", values["stats_lossless_rows"]))
    stats_rows[0] = {**stats_rows[0], "record_sha256": _SOURCES[0]}

    with pytest.raises(
        IndependentLosslessOwnershipVerifierError,
        match="duplicate one source-record",
    ):
        _verify(values, stats_lossless_rows=tuple(stats_rows))


def test_binding_reorder_and_independently_resealed_dual_assignment_fail() -> None:
    values = _fixture()
    bindings = cast("tuple[dict[str, object], ...]", values["ownership_binding_rows"])
    with pytest.raises(
        IndependentLosslessOwnershipVerifierError,
        match="orphaned, foreign, or reordered",
    ):
        _verify(values, ownership_binding_rows=(bindings[1], bindings[0], *bindings[2:]))

    resealed = _reseal(
        bindings[1],
        kind="nbadb_lossless_ownership_binding_v1",
        digest_field="binding_sha256",
        changes={"source_record_sha256": _SOURCES[0]},
    )
    with pytest.raises(
        IndependentLosslessOwnershipVerifierError,
        match="dual-assigns",
    ):
        _verify(values, ownership_binding_rows=(bindings[0], resealed, *bindings[2:]))


def test_independently_resealed_partition_root_is_recomputed_from_bindings() -> None:
    values = _fixture()
    partitions = cast("tuple[dict[str, object], ...]", values["ownership_partition_rows"])
    forged = _reseal(
        partitions[0],
        kind="nbadb_lossless_ownership_partition_v1",
        digest_field="partition_sha256",
        changes={"record_root_sha256": "0" * 64},
    )

    with pytest.raises(
        IndependentLosslessOwnershipVerifierError,
        match="roots differ",
    ):
        _verify(values, ownership_partition_rows=(forged, *partitions[1:]))


def test_independently_resealed_observation_and_receipt_cannot_self_attest() -> None:
    values = _fixture()
    observations = cast("tuple[dict[str, object], ...]", values["ownership_observation_rows"])
    forged_observation = _reseal(
        observations[0],
        kind="nbadb_lossless_observation_ownership_v1",
        digest_field="observation_ownership_sha256",
        changes={"partition_root_sha256": "0" * 64},
    )
    with pytest.raises(
        IndependentLosslessOwnershipVerifierError,
        match="differs from exact partitions",
    ):
        _verify(
            values,
            ownership_observation_rows=(forged_observation, *observations[1:]),
        )

    receipt = cast("dict[str, object]", values["ownership_receipt_row"])
    forged_receipt = _reseal(
        receipt,
        kind="nbadb_lossless_ownership_receipt_v1",
        digest_field="receipt_sha256",
        changes={"source_record_root_sha256": "0" * 64},
    )
    with pytest.raises(
        IndependentLosslessOwnershipVerifierError,
        match="reconstructed closure",
    ):
        _verify(
            values,
            expected_ownership_receipt_sha256=forged_receipt["receipt_sha256"],
            ownership_receipt_row=forged_receipt,
        )


def test_live_coordinated_local_unit_and_assignment_reseal_cannot_drift() -> None:
    values = _fixture()
    live_rows = list(cast("tuple[dict[str, object], ...]", values["live_lossless_rows"]))
    forged_unit = ExpectedValueUnitV1.build(
        raw_authority_bundle_sha256=_RAW,
        unit_ordinal=1,
        observation_sha256=_OBSERVATIONS[1],
        observation_ordinal=0,
        unit_kind="result_occurrence",
        occurrence_sha256=_OCCURRENCES[2],
        occurrence_ordinal=0,
    )
    forged_assignment = ValueRepresentationAssignmentV1.build(
        expected_unit=forged_unit,
        source_input_kind="parser_input_body",
        representation_kind="live_lossless_nodes_v1",
    )
    live_rows[0] = {
        **live_rows[0],
        "expected_unit_sha256": forged_unit.unit_sha256,
        "expected_unit_ordinal": forged_unit.unit_ordinal,
        "representation_assignment_sha256": forged_assignment.assignment_sha256,
    }
    with pytest.raises(
        IndependentLosslessOwnershipVerifierError,
        match="genuine local unit or assignment",
    ):
        _verify(values, live_lossless_rows=tuple(live_rows))


def test_hostile_subclasses_bool_int_confusion_and_payload_columns_fail() -> None:
    values = _fixture()
    with pytest.raises(IndependentLosslessOwnershipVerifierError, match="lowercase full"):
        _verify(values, expected_raw_authority_bundle_sha256=_TextSubclass(_RAW))

    raw_observations = list(cast("tuple[dict[str, object], ...]", values["raw_observation_rows"]))
    raw_observations[0] = {**raw_observations[0], "result_occurrence_count": True}
    with pytest.raises(IndependentLosslessOwnershipVerifierError, match="exact integer"):
        _verify(values, raw_observation_rows=tuple(raw_observations))

    raw_observations = list(cast("tuple[dict[str, object], ...]", values["raw_observation_rows"]))
    raw_observations[0] = {**raw_observations[0], "source_family": ["stats"]}
    with pytest.raises(IndependentLosslessOwnershipVerifierError, match="closed literal domain"):
        _verify(values, raw_observation_rows=tuple(raw_observations))

    assignments = list(
        cast("tuple[dict[str, object], ...]", values["representation_assignment_rows"])
    )
    assignments[1] = {**assignments[1], "unit_ordinal": True}
    with pytest.raises(IndependentLosslessOwnershipVerifierError, match="exact integer"):
        _verify(values, representation_assignment_rows=tuple(assignments))

    result_cells = list(cast("tuple[dict[str, object], ...]", values["result_cell_rows"]))
    result_cells[0] = {**result_cells[0], "canonical_json": '"secret"'}
    with pytest.raises(IndependentLosslessOwnershipVerifierError, match="plain-row shape"):
        _verify(values, result_cell_rows=tuple(result_cells))


def test_result_and_source_order_are_independently_enforced() -> None:
    values = _fixture()
    observations = cast("tuple[dict[str, object], ...]", values["raw_observation_rows"])
    with pytest.raises(IndependentLosslessOwnershipVerifierError, match="semantic order"):
        _verify(
            values,
            raw_observation_rows=(observations[1], observations[0], *observations[2:]),
        )

    occurrences = cast("tuple[dict[str, object], ...]", values["raw_occurrence_rows"])
    with pytest.raises(IndependentLosslessOwnershipVerifierError, match="occurrence order"):
        _verify(values, raw_occurrence_rows=(occurrences[1], occurrences[0], *occurrences[2:]))

    result_cells = cast("tuple[dict[str, object], ...]", values["result_cell_rows"])
    with pytest.raises(IndependentLosslessOwnershipVerifierError, match="source order"):
        _verify(values, result_cell_rows=tuple(reversed(result_cells)))


def test_production_imports_and_authority_constructor_calls_are_ast_denied() -> None:
    source_path = Path(verifier_module.__file__)
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    forbidden_calls = {"build", "from_row", "validate", "model_validate"}
    seen_forbidden_calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute) and node.func.attr in forbidden_calls:
                seen_forbidden_calls.add(node.func.attr)
            elif isinstance(node.func, ast.Name) and node.func.id in forbidden_calls:
                seen_forbidden_calls.add(node.func.id)

    assert imported <= {"__future__", "hashlib", "json", "re", "dataclasses", "typing"}
    assert not seen_forbidden_calls
    deny_fragments = {
        "contracts.lossless_ownership",
        "stats_lossless",
        "live_lossless",
        "raw_request",
        "raw_result",
        "bodyless",
        "extract",
        "orchestrate",
        "schemas",
        "nba_api",
        "polars",
        "pandera",
    }
    assert not any(fragment in module for module in imported for fragment in deny_fragments)


def test_public_api_and_frozen_pins_are_exact() -> None:
    assert FROZEN_LOSSLESS_OWNERSHIP_SOURCE_SHA256 == (
        "3821abe4475dd85624ae814fa0dedadd5a771bdd9589bc9ea5cda70aa97a21aa"
    )
    assert FROZEN_LOSSLESS_OWNERSHIP_TEST_SHA256 == (
        "e9c2edba8811f53faa2684938126a9fd2fb3f497c60290524ae8bc68d15f81f9"
    )
    assert set(verifier_module.__all__) == {
        "FROZEN_LOSSLESS_OWNERSHIP_SOURCE_SHA256",
        "FROZEN_LOSSLESS_OWNERSHIP_TEST_SHA256",
        "IndependentLosslessOwnershipVerificationV1",
        "IndependentLosslessOwnershipVerifierError",
        "verify_independent_lossless_ownership",
    }


def test_fixture_rows_are_not_mutated() -> None:
    values = _fixture()
    before = copy.deepcopy(values)

    _verify(values)

    assert values == before
