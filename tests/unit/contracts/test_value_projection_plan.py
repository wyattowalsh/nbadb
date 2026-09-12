"""Independent unit tests for the dependency-pure value-projection plan."""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import fields
from pathlib import Path
from typing import Any

import pytest

from nbadb.contracts import value_projection_plan as plan_module
from nbadb.contracts.value_projection import ValueProjectionPartitionV1
from nbadb.contracts.value_projection_plan import (
    VALUE_PROJECTION_PLAN_RECORD_KINDS_V1,
    VALUE_PROJECTION_PLAN_REPRESENTATION_KINDS_V1,
    VALUE_PROJECTION_PLAN_SOURCE_FAMILIES_V1,
    VALUE_PROJECTION_PLAN_SOURCE_INPUT_KINDS_V1,
    VALUE_PROJECTION_PLAN_SOURCE_RELATION_KINDS_V1,
    VALUE_PROJECTION_PLAN_UNIT_KINDS_V1,
    ValueProjectionPlanAssignmentV1,
    ValueProjectionPlanError,
    ValueProjectionPlanExpectedUnitV1,
    ValueProjectionPlanObservationSourceV1,
    ValueProjectionPlanOccurrenceV1,
    ValueProjectionPlanOwnershipBindingV1,
    ValueProjectionPlanOwnershipObservationV1,
    ValueProjectionPlanOwnershipPartitionV1,
    ValueProjectionPlanSourceRecordV1,
    ValueProjectionPlanV1,
    validate_value_projection_plan,
)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha(value: object) -> str:
    if type(value) is str:
        value = value.encode("utf-8")
    assert type(value) is bytes
    return hashlib.sha256(value).hexdigest()


def _ordered_headers(*headers: object) -> tuple[str, str]:
    encoded = _canonical(list(headers))
    return encoded.decode("utf-8"), _sha(encoded)


def _semantic_row(*, kind: str, digest_field: str, values: dict[str, object]) -> dict[str, object]:
    identity = {"schema_version": 1, "kind": kind, **values}
    return {"schema_version": 1, digest_field: _sha(_canonical(identity)), **values}


def _legacy_root(kind: str, item_sha256s: tuple[str, ...]) -> str:
    return _sha(
        _canonical(
            {
                "schema_version": 1,
                "kind": kind,
                "count": len(item_sha256s),
                "items": list(item_sha256s),
            }
        )
    )


def _unit_root(bundle_sha256: str, item_sha256s: tuple[str, ...]) -> str:
    return _sha(
        _canonical(
            {
                "schema_version": 1,
                "kind": "nbadb_expected_value_unit_ordered_root_v1",
                "raw_authority_bundle_sha256": bundle_sha256,
                "count": len(item_sha256s),
                "items": list(item_sha256s),
            }
        )
    )


def _build_fixture() -> dict[str, Any]:
    bundle = _sha("raw-bundle")
    observation_records = (_sha("observation-record-0"), _sha("observation-record-1"))
    observations_sha = (_sha("observation-0"), _sha("observation-1"))
    occurrence_sha = _sha("occurrence-0")
    fixed_zero_landing_sha = _sha("fixed-zero-landing")

    unit_specs = (
        {
            "raw_authority_bundle_sha256": bundle,
            "unit_ordinal": 0,
            "observation_sha256": observations_sha[0],
            "observation_ordinal": 0,
            "unit_kind": "result_occurrence",
            "occurrence_sha256": occurrence_sha,
            "occurrence_ordinal": 0,
        },
        {
            "raw_authority_bundle_sha256": bundle,
            "unit_ordinal": 1,
            "observation_sha256": observations_sha[0],
            "observation_ordinal": 0,
            "unit_kind": "response_residual",
            "occurrence_sha256": None,
            "occurrence_ordinal": None,
        },
        {
            "raw_authority_bundle_sha256": bundle,
            "unit_ordinal": 2,
            "observation_sha256": observations_sha[1],
            "observation_ordinal": 1,
            "unit_kind": "response_fixed_zero",
            "occurrence_sha256": None,
            "occurrence_ordinal": None,
        },
    )
    units = tuple(
        ValueProjectionPlanExpectedUnitV1.from_row(
            _semantic_row(
                kind="nbadb_expected_value_unit_v1",
                digest_field="unit_sha256",
                values=values,
            )
        )
        for values in unit_specs
    )

    assignment_specs = (
        ("parser_input_body", "rectangular_result_cells_v1"),
        ("parser_input_body", "response_lossless_records_v1"),
        ("declared_bodyless_packet", "response_fixed_zero_v1"),
    )
    assignments = tuple(
        ValueProjectionPlanAssignmentV1.from_row(
            _semantic_row(
                kind="nbadb_value_representation_assignment_v1",
                digest_field="assignment_sha256",
                values={
                    "raw_authority_bundle_sha256": bundle,
                    "unit_sha256": unit.unit_sha256,
                    "unit_ordinal": ordinal,
                    "source_input_kind": source_input_kind,
                    "representation_kind": representation_kind,
                },
            )
        )
        for ordinal, (unit, (source_input_kind, representation_kind)) in enumerate(
            zip(units, assignment_specs, strict=True)
        )
    )
    unit_ids = tuple(item.unit_sha256 for item in units)
    expected_unit_root = _unit_root(bundle, unit_ids)
    inventory_sha = _sha(
        _canonical(
            {
                "kind": "nbadb_expected_value_unit_inventory_v1",
                "schema_version": 1,
                "raw_authority_bundle_sha256": bundle,
                "unit_count": len(units),
                "unit_root_sha256": expected_unit_root,
                "units": [item.to_row() for item in units],
            }
        )
    )

    source_records = (_sha("cell-record"), _sha("response-record"))
    binding_specs = (
        {
            "raw_authority_bundle_sha256": bundle,
            "observation_record_sha256": observation_records[0],
            "observation_sha256": observations_sha[0],
            "observation_ordinal": 0,
            "binding_ordinal": 0,
            "observation_record_ordinal": 0,
            "partition_ordinal": 0,
            "source_record_sha256": source_records[0],
            "unit_sha256": units[0].unit_sha256,
            "unit_ordinal": 0,
            "assignment_sha256": assignments[0].assignment_sha256,
            "ownership_kind": "result_occurrence",
            "occurrence_sha256": occurrence_sha,
            "occurrence_ordinal": 0,
        },
        {
            "raw_authority_bundle_sha256": bundle,
            "observation_record_sha256": observation_records[0],
            "observation_sha256": observations_sha[0],
            "observation_ordinal": 0,
            "binding_ordinal": 1,
            "observation_record_ordinal": 1,
            "partition_ordinal": 1,
            "source_record_sha256": source_records[1],
            "unit_sha256": units[1].unit_sha256,
            "unit_ordinal": 1,
            "assignment_sha256": assignments[1].assignment_sha256,
            "ownership_kind": "response_residual",
            "occurrence_sha256": None,
            "occurrence_ordinal": None,
        },
    )
    bindings = tuple(
        ValueProjectionPlanOwnershipBindingV1.from_row(
            _semantic_row(
                kind="nbadb_lossless_ownership_binding_v1",
                digest_field="binding_sha256",
                values=values,
            )
        )
        for values in binding_specs
    )

    empty_record_root = _legacy_root("nbadb_lossless_partition_source_records_v1", ())
    empty_binding_root = _legacy_root("nbadb_lossless_partition_bindings_v1", ())
    partition_specs = (
        {
            "raw_authority_bundle_sha256": bundle,
            "observation_record_sha256": observation_records[0],
            "observation_sha256": observations_sha[0],
            "observation_ordinal": 0,
            "partition_ordinal": 0,
            "observation_partition_ordinal": 0,
            "partition_kind": "result_occurrence",
            "occurrence_sha256": occurrence_sha,
            "occurrence_ordinal": 0,
            "unit_sha256": units[0].unit_sha256,
            "unit_ordinal": 0,
            "assignment_sha256": assignments[0].assignment_sha256,
            "record_count": 1,
            "record_root_sha256": _legacy_root(
                "nbadb_lossless_partition_source_records_v1", (source_records[0],)
            ),
            "binding_root_sha256": _legacy_root(
                "nbadb_lossless_partition_bindings_v1", (bindings[0].binding_sha256,)
            ),
            "fixed_zero_landing_sha256": None,
        },
        {
            "raw_authority_bundle_sha256": bundle,
            "observation_record_sha256": observation_records[0],
            "observation_sha256": observations_sha[0],
            "observation_ordinal": 0,
            "partition_ordinal": 1,
            "observation_partition_ordinal": 1,
            "partition_kind": "response_residual",
            "occurrence_sha256": None,
            "occurrence_ordinal": None,
            "unit_sha256": units[1].unit_sha256,
            "unit_ordinal": 1,
            "assignment_sha256": assignments[1].assignment_sha256,
            "record_count": 1,
            "record_root_sha256": _legacy_root(
                "nbadb_lossless_partition_source_records_v1", (source_records[1],)
            ),
            "binding_root_sha256": _legacy_root(
                "nbadb_lossless_partition_bindings_v1", (bindings[1].binding_sha256,)
            ),
            "fixed_zero_landing_sha256": None,
        },
        {
            "raw_authority_bundle_sha256": bundle,
            "observation_record_sha256": observation_records[1],
            "observation_sha256": observations_sha[1],
            "observation_ordinal": 1,
            "partition_ordinal": 2,
            "observation_partition_ordinal": 0,
            "partition_kind": "response_fixed_zero",
            "occurrence_sha256": None,
            "occurrence_ordinal": None,
            "unit_sha256": units[2].unit_sha256,
            "unit_ordinal": 2,
            "assignment_sha256": assignments[2].assignment_sha256,
            "record_count": 0,
            "record_root_sha256": empty_record_root,
            "binding_root_sha256": empty_binding_root,
            "fixed_zero_landing_sha256": fixed_zero_landing_sha,
        },
    )
    partitions = tuple(
        ValueProjectionPlanOwnershipPartitionV1.from_row(
            _semantic_row(
                kind="nbadb_lossless_ownership_partition_v1",
                digest_field="partition_sha256",
                values=values,
            )
        )
        for values in partition_specs
    )

    observation_specs = (
        {
            "raw_authority_bundle_sha256": bundle,
            "observation_record_sha256": observation_records[0],
            "observation_sha256": observations_sha[0],
            "observation_ordinal": 0,
            "source_input_kind": "parser_input_body",
            "first_partition_ordinal": 0,
            "partition_count": 2,
            "partition_root_sha256": _legacy_root(
                "nbadb_lossless_observation_partitions_v1",
                (partitions[0].partition_sha256, partitions[1].partition_sha256),
            ),
            "result_occurrence_partition_count": 1,
            "zero_result_occurrence_partition_count": 0,
            "result_occurrence_record_count": 1,
            "response_partition_kind": "response_residual",
            "response_record_count": 1,
            "fixed_zero_landing_sha256": None,
            "record_count": 2,
            "record_root_sha256": _legacy_root(
                "nbadb_lossless_observation_source_records_v1", source_records
            ),
            "binding_count": 2,
            "binding_root_sha256": _legacy_root(
                "nbadb_lossless_observation_bindings_v1",
                tuple(item.binding_sha256 for item in bindings),
            ),
        },
        {
            "raw_authority_bundle_sha256": bundle,
            "observation_record_sha256": observation_records[1],
            "observation_sha256": observations_sha[1],
            "observation_ordinal": 1,
            "source_input_kind": "declared_bodyless_packet",
            "first_partition_ordinal": 2,
            "partition_count": 1,
            "partition_root_sha256": _legacy_root(
                "nbadb_lossless_observation_partitions_v1", (partitions[2].partition_sha256,)
            ),
            "result_occurrence_partition_count": 0,
            "zero_result_occurrence_partition_count": 0,
            "result_occurrence_record_count": 0,
            "response_partition_kind": "response_fixed_zero",
            "response_record_count": 0,
            "fixed_zero_landing_sha256": fixed_zero_landing_sha,
            "record_count": 0,
            "record_root_sha256": _legacy_root("nbadb_lossless_observation_source_records_v1", ()),
            "binding_count": 0,
            "binding_root_sha256": _legacy_root("nbadb_lossless_observation_bindings_v1", ()),
        },
    )
    ownership_observations = tuple(
        ValueProjectionPlanOwnershipObservationV1.from_row(
            _semantic_row(
                kind="nbadb_lossless_observation_ownership_v1",
                digest_field="observation_ownership_sha256",
                values=values,
            )
        )
        for values in observation_specs
    )

    sources = (
        ValueProjectionPlanObservationSourceV1.build(
            raw_authority_bundle_sha256=bundle,
            observation_record_sha256=observation_records[0],
            observation_sha256=observations_sha[0],
            observation_ordinal=0,
            source_input_kind="parser_input_body",
            source_family="stats",
            body_blob_sha256=_sha("body-blob"),
            body_blob_readback_sha256=_sha("body-readback"),
            parser_input_object_sha256=_sha("parser-input"),
            payload_sha256=_sha("payload-0"),
            payload_byte_count=11,
        ),
        ValueProjectionPlanObservationSourceV1.build(
            raw_authority_bundle_sha256=bundle,
            observation_record_sha256=observation_records[1],
            observation_sha256=observations_sha[1],
            observation_ordinal=1,
            source_input_kind="declared_bodyless_packet",
            source_family="static",
            bodyless_packet_sha256=_sha("bodyless-packet"),
            bodyless_readback_sha256=_sha("bodyless-readback"),
            payload_sha256=_sha("payload-1"),
            payload_byte_count=2,
        ),
    )
    headers_json, headers_sha256 = _ordered_headers("H")
    occurrences = (
        ValueProjectionPlanOccurrenceV1.build(
            raw_authority_bundle_sha256=bundle,
            occurrence_plan_ordinal=0,
            observation_record_sha256=observation_records[0],
            observation_sha256=observations_sha[0],
            observation_ordinal=0,
            partition_sha256=partitions[0].partition_sha256,
            partition_ordinal=0,
            occurrence_sha256=occurrence_sha,
            occurrence_ordinal=0,
            unit_sha256=units[0].unit_sha256,
            unit_ordinal=0,
            assignment_sha256=assignments[0].assignment_sha256,
            source_input_kind="parser_input_body",
            representation_kind="rectangular_result_cells_v1",
            result_name="Result",
            result_duplicate_ordinal=0,
            provider_result_ordinal=0,
            expected_result_ordinal=0,
            canonical_result_ordinal=0,
            result_path=None,
            container_kind="nba_api_result_set",
            result_presence="present",
            ordered_headers_json=headers_json,
            ordered_headers_sha256=headers_sha256,
            header_count=1,
            row_count=1,
            cell_count=1,
            node_count=0,
            container_count=1,
            missing_count=0,
            null_count=0,
            parent_state_sha256=_sha(_canonical(["present"])),
            representation_output_sha256=_sha("rectangular-output"),
        ),
    )
    source_record_plans = (
        ValueProjectionPlanSourceRecordV1.build(
            source_record_plan_ordinal=0,
            raw_authority_bundle_sha256=bundle,
            observation_record_sha256=observation_records[0],
            observation_sha256=observations_sha[0],
            observation_ordinal=0,
            partition_sha256=partitions[0].partition_sha256,
            partition_ordinal=0,
            binding_sha256=bindings[0].binding_sha256,
            binding_ordinal=0,
            observation_record_ordinal=0,
            source_record_sha256=source_records[0],
            unit_sha256=units[0].unit_sha256,
            unit_ordinal=0,
            assignment_sha256=assignments[0].assignment_sha256,
            unit_kind="result_occurrence",
            occurrence_sha256=occurrence_sha,
            occurrence_ordinal=0,
            source_input_kind="parser_input_body",
            representation_kind="rectangular_result_cells_v1",
            source_relation_kind="result_cell_v1",
            projection_record_kind="cell",
        ),
        ValueProjectionPlanSourceRecordV1.build(
            source_record_plan_ordinal=1,
            raw_authority_bundle_sha256=bundle,
            observation_record_sha256=observation_records[0],
            observation_sha256=observations_sha[0],
            observation_ordinal=0,
            partition_sha256=partitions[1].partition_sha256,
            partition_ordinal=1,
            binding_sha256=bindings[1].binding_sha256,
            binding_ordinal=1,
            observation_record_ordinal=1,
            source_record_sha256=source_records[1],
            unit_sha256=units[1].unit_sha256,
            unit_ordinal=1,
            assignment_sha256=assignments[1].assignment_sha256,
            unit_kind="response_residual",
            occurrence_sha256=None,
            occurrence_ordinal=None,
            source_input_kind="parser_input_body",
            representation_kind="response_lossless_records_v1",
            source_relation_kind="stats_lossless_record_v1",
            projection_record_kind="response",
        ),
    )

    assignment_root = _legacy_root(
        "nbadb_lossless_representation_assignments_v1",
        tuple(item.assignment_sha256 for item in assignments),
    )
    observation_root = _legacy_root(
        "nbadb_lossless_owned_observations_v1",
        tuple(item.observation_ownership_sha256 for item in ownership_observations),
    )
    partition_root = _legacy_root(
        "nbadb_lossless_ownership_partitions_v1",
        tuple(item.partition_sha256 for item in partitions),
    )
    binding_root = _legacy_root(
        "nbadb_lossless_ownership_bindings_v1",
        tuple(item.binding_sha256 for item in bindings),
    )
    source_record_root = _legacy_root("nbadb_lossless_owned_source_records_v1", source_records)
    ownership_values = {
        "raw_authority_bundle_sha256": bundle,
        "expected_unit_count": 3,
        "expected_unit_inventory_sha256": inventory_sha,
        "expected_unit_root_sha256": expected_unit_root,
        "representation_assignment_count": 3,
        "representation_assignment_root_sha256": assignment_root,
        "observation_count": 2,
        "observation_root_sha256": observation_root,
        "partition_count": 3,
        "partition_root_sha256": partition_root,
        "result_occurrence_partition_count": 1,
        "zero_result_occurrence_partition_count": 0,
        "result_occurrence_record_count": 1,
        "response_residual_partition_count": 1,
        "positive_response_residual_partition_count": 1,
        "zero_response_residual_partition_count": 0,
        "response_residual_record_count": 1,
        "response_fixed_zero_partition_count": 1,
        "fixed_zero_landing_root_sha256": _legacy_root(
            "nbadb_lossless_fixed_zero_landings_v1", (fixed_zero_landing_sha,)
        ),
        "binding_count": 2,
        "binding_root_sha256": binding_root,
        "source_record_count": 2,
        "source_record_root_sha256": source_record_root,
    }
    ownership_receipt = _sha(
        _canonical(
            {
                "schema_version": 1,
                "kind": "nbadb_lossless_ownership_receipt_v1",
                **ownership_values,
            }
        )
    )
    plan = ValueProjectionPlanV1.build(
        raw_authority_bundle_sha256=bundle,
        ownership_receipt_sha256=ownership_receipt,
        expected_unit_inventory_sha256=inventory_sha,
        expected_units=units,
        assignments=assignments,
        ownership_observations=ownership_observations,
        ownership_partitions=partitions,
        ownership_bindings=bindings,
        observation_sources=sources,
        occurrence_plans=occurrences,
        source_record_plans=source_record_plans,
    )
    return {
        "plan": plan,
        "bundle": bundle,
        "ownership_receipt": ownership_receipt,
        "inventory_sha": inventory_sha,
        "units": units,
        "assignments": assignments,
        "observations": ownership_observations,
        "partitions": partitions,
        "bindings": bindings,
        "sources": sources,
        "occurrences": occurrences,
        "source_record_plans": source_record_plans,
    }


def _build_lossless_fixture(
    *,
    representation_kind: str,
    source_family: str,
    source_relation_kind: str,
    projection_record_kinds: tuple[str, ...],
    occurrence_shape: dict[str, object],
) -> dict[str, Any]:
    bundle = _sha(f"{representation_kind}-bundle")
    observation_record_sha256 = _sha(f"{representation_kind}-observation-record")
    observation_sha256 = _sha(f"{representation_kind}-observation")
    occurrence_sha256 = _sha(f"{representation_kind}-occurrence")
    unit = ValueProjectionPlanExpectedUnitV1.from_row(
        _semantic_row(
            kind="nbadb_expected_value_unit_v1",
            digest_field="unit_sha256",
            values={
                "raw_authority_bundle_sha256": bundle,
                "unit_ordinal": 0,
                "observation_sha256": observation_sha256,
                "observation_ordinal": 0,
                "unit_kind": "result_occurrence",
                "occurrence_sha256": occurrence_sha256,
                "occurrence_ordinal": 0,
            },
        )
    )
    assignment = ValueProjectionPlanAssignmentV1.from_row(
        _semantic_row(
            kind="nbadb_value_representation_assignment_v1",
            digest_field="assignment_sha256",
            values={
                "raw_authority_bundle_sha256": bundle,
                "unit_sha256": unit.unit_sha256,
                "unit_ordinal": 0,
                "source_input_kind": "parser_input_body",
                "representation_kind": representation_kind,
            },
        )
    )
    source_record_sha256s = tuple(
        _sha(f"{representation_kind}-source-record-{ordinal}")
        for ordinal in range(len(projection_record_kinds))
    )
    bindings = tuple(
        ValueProjectionPlanOwnershipBindingV1.from_row(
            _semantic_row(
                kind="nbadb_lossless_ownership_binding_v1",
                digest_field="binding_sha256",
                values={
                    "raw_authority_bundle_sha256": bundle,
                    "observation_record_sha256": observation_record_sha256,
                    "observation_sha256": observation_sha256,
                    "observation_ordinal": 0,
                    "binding_ordinal": ordinal,
                    "observation_record_ordinal": ordinal,
                    "partition_ordinal": 0,
                    "source_record_sha256": source_record_sha256,
                    "unit_sha256": unit.unit_sha256,
                    "unit_ordinal": 0,
                    "assignment_sha256": assignment.assignment_sha256,
                    "ownership_kind": "result_occurrence",
                    "occurrence_sha256": occurrence_sha256,
                    "occurrence_ordinal": 0,
                },
            )
        )
        for ordinal, source_record_sha256 in enumerate(source_record_sha256s)
    )
    result_partition = ValueProjectionPlanOwnershipPartitionV1.from_row(
        _semantic_row(
            kind="nbadb_lossless_ownership_partition_v1",
            digest_field="partition_sha256",
            values={
                "raw_authority_bundle_sha256": bundle,
                "observation_record_sha256": observation_record_sha256,
                "observation_sha256": observation_sha256,
                "observation_ordinal": 0,
                "partition_ordinal": 0,
                "observation_partition_ordinal": 0,
                "partition_kind": "result_occurrence",
                "occurrence_sha256": occurrence_sha256,
                "occurrence_ordinal": 0,
                "unit_sha256": unit.unit_sha256,
                "unit_ordinal": 0,
                "assignment_sha256": assignment.assignment_sha256,
                "record_count": len(bindings),
                "record_root_sha256": _legacy_root(
                    "nbadb_lossless_partition_source_records_v1",
                    source_record_sha256s,
                ),
                "binding_root_sha256": _legacy_root(
                    "nbadb_lossless_partition_bindings_v1",
                    tuple(item.binding_sha256 for item in bindings),
                ),
                "fixed_zero_landing_sha256": None,
            },
        )
    )
    empty_record_root = _legacy_root("nbadb_lossless_partition_source_records_v1", ())
    empty_binding_root = _legacy_root("nbadb_lossless_partition_bindings_v1", ())
    response_partition = ValueProjectionPlanOwnershipPartitionV1.from_row(
        _semantic_row(
            kind="nbadb_lossless_ownership_partition_v1",
            digest_field="partition_sha256",
            values={
                "raw_authority_bundle_sha256": bundle,
                "observation_record_sha256": observation_record_sha256,
                "observation_sha256": observation_sha256,
                "observation_ordinal": 0,
                "partition_ordinal": 1,
                "observation_partition_ordinal": 1,
                "partition_kind": "response_residual",
                "occurrence_sha256": None,
                "occurrence_ordinal": None,
                "unit_sha256": None,
                "unit_ordinal": None,
                "assignment_sha256": None,
                "record_count": 0,
                "record_root_sha256": empty_record_root,
                "binding_root_sha256": empty_binding_root,
                "fixed_zero_landing_sha256": None,
            },
        )
    )
    partitions = (result_partition, response_partition)
    observation = ValueProjectionPlanOwnershipObservationV1.from_row(
        _semantic_row(
            kind="nbadb_lossless_observation_ownership_v1",
            digest_field="observation_ownership_sha256",
            values={
                "raw_authority_bundle_sha256": bundle,
                "observation_record_sha256": observation_record_sha256,
                "observation_sha256": observation_sha256,
                "observation_ordinal": 0,
                "source_input_kind": "parser_input_body",
                "first_partition_ordinal": 0,
                "partition_count": 2,
                "partition_root_sha256": _legacy_root(
                    "nbadb_lossless_observation_partitions_v1",
                    tuple(item.partition_sha256 for item in partitions),
                ),
                "result_occurrence_partition_count": 1,
                "zero_result_occurrence_partition_count": int(not bindings),
                "result_occurrence_record_count": len(bindings),
                "response_partition_kind": "response_residual",
                "response_record_count": 0,
                "fixed_zero_landing_sha256": None,
                "record_count": len(bindings),
                "record_root_sha256": _legacy_root(
                    "nbadb_lossless_observation_source_records_v1",
                    source_record_sha256s,
                ),
                "binding_count": len(bindings),
                "binding_root_sha256": _legacy_root(
                    "nbadb_lossless_observation_bindings_v1",
                    tuple(item.binding_sha256 for item in bindings),
                ),
            },
        )
    )
    units = (unit,)
    assignments = (assignment,)
    unit_root = _unit_root(bundle, (unit.unit_sha256,))
    inventory_sha256 = _sha(
        _canonical(
            {
                "kind": "nbadb_expected_value_unit_inventory_v1",
                "schema_version": 1,
                "raw_authority_bundle_sha256": bundle,
                "unit_count": 1,
                "unit_root_sha256": unit_root,
                "units": [unit.to_row()],
            }
        )
    )
    receipt_values = {
        "raw_authority_bundle_sha256": bundle,
        "expected_unit_count": 1,
        "expected_unit_inventory_sha256": inventory_sha256,
        "expected_unit_root_sha256": unit_root,
        "representation_assignment_count": 1,
        "representation_assignment_root_sha256": _legacy_root(
            "nbadb_lossless_representation_assignments_v1",
            (assignment.assignment_sha256,),
        ),
        "observation_count": 1,
        "observation_root_sha256": _legacy_root(
            "nbadb_lossless_owned_observations_v1",
            (observation.observation_ownership_sha256,),
        ),
        "partition_count": 2,
        "partition_root_sha256": _legacy_root(
            "nbadb_lossless_ownership_partitions_v1",
            tuple(item.partition_sha256 for item in partitions),
        ),
        "result_occurrence_partition_count": 1,
        "zero_result_occurrence_partition_count": int(not bindings),
        "result_occurrence_record_count": len(bindings),
        "response_residual_partition_count": 1,
        "positive_response_residual_partition_count": 0,
        "zero_response_residual_partition_count": 1,
        "response_residual_record_count": 0,
        "response_fixed_zero_partition_count": 0,
        "fixed_zero_landing_root_sha256": _legacy_root("nbadb_lossless_fixed_zero_landings_v1", ()),
        "binding_count": len(bindings),
        "binding_root_sha256": _legacy_root(
            "nbadb_lossless_ownership_bindings_v1",
            tuple(item.binding_sha256 for item in bindings),
        ),
        "source_record_count": len(bindings),
        "source_record_root_sha256": _legacy_root(
            "nbadb_lossless_owned_source_records_v1",
            source_record_sha256s,
        ),
    }
    ownership_receipt_sha256 = _sha(
        _canonical(
            {
                "schema_version": 1,
                "kind": "nbadb_lossless_ownership_receipt_v1",
                **receipt_values,
            }
        )
    )
    source = ValueProjectionPlanObservationSourceV1.build(
        raw_authority_bundle_sha256=bundle,
        observation_record_sha256=observation_record_sha256,
        observation_sha256=observation_sha256,
        observation_ordinal=0,
        source_input_kind="parser_input_body",
        source_family=source_family,
        body_blob_sha256=_sha(f"{representation_kind}-body"),
        body_blob_readback_sha256=_sha(f"{representation_kind}-readback"),
        parser_input_object_sha256=_sha(f"{representation_kind}-parser-input"),
        payload_sha256=_sha(f"{representation_kind}-payload"),
        payload_byte_count=1,
    )
    header_count = occurrence_shape["header_count"]
    assert type(header_count) is int
    headers_json, headers_sha256 = _ordered_headers(
        *(f"H{ordinal}" for ordinal in range(header_count))
    )
    occurrence = ValueProjectionPlanOccurrenceV1.build(
        raw_authority_bundle_sha256=bundle,
        occurrence_plan_ordinal=0,
        observation_record_sha256=observation_record_sha256,
        observation_sha256=observation_sha256,
        observation_ordinal=0,
        partition_sha256=result_partition.partition_sha256,
        partition_ordinal=0,
        occurrence_sha256=occurrence_sha256,
        occurrence_ordinal=0,
        unit_sha256=unit.unit_sha256,
        unit_ordinal=0,
        assignment_sha256=assignment.assignment_sha256,
        source_input_kind="parser_input_body",
        representation_kind=representation_kind,
        result_name="Result",
        result_duplicate_ordinal=0,
        provider_result_ordinal=0,
        expected_result_ordinal=0,
        canonical_result_ordinal=0,
        ordered_headers_json=headers_json,
        ordered_headers_sha256=headers_sha256,
        representation_output_sha256=_sha(f"{representation_kind}-output"),
        **occurrence_shape,
    )
    source_record_plans = tuple(
        ValueProjectionPlanSourceRecordV1.build(
            raw_authority_bundle_sha256=bundle,
            source_record_plan_ordinal=ordinal,
            observation_record_sha256=observation_record_sha256,
            observation_sha256=observation_sha256,
            observation_ordinal=0,
            partition_sha256=result_partition.partition_sha256,
            partition_ordinal=0,
            binding_sha256=binding.binding_sha256,
            binding_ordinal=ordinal,
            observation_record_ordinal=ordinal,
            source_record_sha256=binding.source_record_sha256,
            unit_sha256=unit.unit_sha256,
            unit_ordinal=0,
            assignment_sha256=assignment.assignment_sha256,
            unit_kind="result_occurrence",
            occurrence_sha256=occurrence_sha256,
            occurrence_ordinal=0,
            source_input_kind="parser_input_body",
            representation_kind=representation_kind,
            source_relation_kind=source_relation_kind,
            projection_record_kind=projection_record_kind,
        )
        for ordinal, (binding, projection_record_kind) in enumerate(
            zip(bindings, projection_record_kinds, strict=True)
        )
    )
    build_values = {
        "raw_authority_bundle_sha256": bundle,
        "ownership_receipt_sha256": ownership_receipt_sha256,
        "expected_unit_inventory_sha256": inventory_sha256,
        "expected_units": units,
        "assignments": assignments,
        "ownership_observations": (observation,),
        "ownership_partitions": partitions,
        "ownership_bindings": bindings,
        "observation_sources": (source,),
        "occurrence_plans": (occurrence,),
        "source_record_plans": source_record_plans,
    }
    return {
        "plan": ValueProjectionPlanV1.build(**build_values),
        "occurrence": occurrence,
        "build_values": build_values,
    }


def _replay(plan: ValueProjectionPlanV1) -> ValueProjectionPlanV1:
    return ValueProjectionPlanV1.from_canonical_bytes(
        plan.canonical_bytes(),
        expected_plan_sha256=plan.plan_sha256,
        expected_raw_authority_bundle_sha256=plan.raw_authority_bundle_sha256,
        expected_ownership_receipt_sha256=plan.ownership_receipt_sha256,
    )


def _occurrence_build_values(
    occurrence: ValueProjectionPlanOccurrenceV1,
) -> dict[str, object]:
    return {
        item.name: getattr(occurrence, item.name)
        for item in fields(occurrence)
        if item.name != "occurrence_plan_sha256"
    }


def _plan_build_values(fixture: dict[str, Any]) -> dict[str, object]:
    return {
        "raw_authority_bundle_sha256": fixture["bundle"],
        "ownership_receipt_sha256": fixture["ownership_receipt"],
        "expected_unit_inventory_sha256": fixture["inventory_sha"],
        "expected_units": fixture["units"],
        "assignments": fixture["assignments"],
        "ownership_observations": fixture["observations"],
        "ownership_partitions": fixture["partitions"],
        "ownership_bindings": fixture["bindings"],
        "observation_sources": fixture["sources"],
        "occurrence_plans": fixture["occurrences"],
        "source_record_plans": fixture["source_record_plans"],
    }


def test_valid_plan_round_trips_and_binds_all_denominators() -> None:
    fixture = _build_fixture()
    plan = fixture["plan"]
    replayed = _replay(plan)

    assert replayed == plan
    assert (
        validate_value_projection_plan(
            plan,
            expected_plan_sha256=plan.plan_sha256,
            expected_raw_authority_bundle_sha256=fixture["bundle"],
            expected_ownership_receipt_sha256=fixture["ownership_receipt"],
        )
        == plan
    )
    assert (
        plan.expected_unit_count,
        plan.assignment_count,
        plan.observation_count,
        plan.partition_count,
        plan.occurrence_count,
        plan.binding_count,
        plan.source_record_count,
    ) == (3, 3, 2, 3, 1, 2, 2)
    assert plan.expected_unit_authority_root_sha256 == _unit_root(
        fixture["bundle"], tuple(item.unit_sha256 for item in fixture["units"])
    )


def test_zero_row_nonempty_headers_replay_into_value_partition() -> None:
    fixture = _build_lossless_fixture(
        representation_kind="rectangular_result_cells_v1",
        source_family="stats",
        source_relation_kind="result_cell_v1",
        projection_record_kinds=(),
        occurrence_shape={
            "result_path": None,
            "container_kind": "nba_api_result_set",
            "result_presence": "present_empty",
            "header_count": 2,
            "row_count": 0,
            "cell_count": 0,
            "node_count": 0,
            "container_count": 1,
            "missing_count": 0,
            "null_count": 0,
            "parent_state_sha256": _sha(_canonical(["present"])),
        },
    )
    plan = ValueProjectionPlanV1.from_canonical_bytes(
        fixture["plan"].canonical_bytes(),
        expected_plan_sha256=fixture["plan"].plan_sha256,
        expected_raw_authority_bundle_sha256=fixture["plan"].raw_authority_bundle_sha256,
        expected_ownership_receipt_sha256=fixture["plan"].ownership_receipt_sha256,
    )
    occurrence = plan.occurrence_plans[0]
    ownership_partition = plan.ownership_partitions[0]

    assert occurrence.ordered_headers_json == '["H0","H1"]'
    assert occurrence.ordered_headers() == ("H0", "H1")
    partition = ValueProjectionPartitionV1.build(
        raw_authority_bundle_sha256=occurrence.raw_authority_bundle_sha256,
        ownership_partition_sha256=ownership_partition.partition_sha256,
        observation_record_sha256=occurrence.observation_record_sha256,
        observation_sha256=occurrence.observation_sha256,
        observation_ordinal=occurrence.observation_ordinal,
        partition_ordinal=occurrence.partition_ordinal,
        observation_partition_ordinal=ownership_partition.observation_partition_ordinal,
        partition_kind=ownership_partition.partition_kind,
        source_input_kind=occurrence.source_input_kind,
        items=(),
        occurrence_sha256=occurrence.occurrence_sha256,
        occurrence_ordinal=occurrence.occurrence_ordinal,
        unit_sha256=occurrence.unit_sha256,
        unit_ordinal=occurrence.unit_ordinal,
        assignment_sha256=occurrence.assignment_sha256,
        representation_kind=occurrence.representation_kind,
        result_name=occurrence.result_name,
        result_duplicate_ordinal=occurrence.result_duplicate_ordinal,
        provider_result_ordinal=occurrence.provider_result_ordinal,
        expected_result_ordinal=occurrence.expected_result_ordinal,
        canonical_result_ordinal=occurrence.canonical_result_ordinal,
        result_path="$.result",
        container_kind=occurrence.container_kind,
        result_presence=occurrence.result_presence,
        ordered_headers=occurrence.ordered_headers(),
        header_count=occurrence.header_count,
        row_count=occurrence.row_count,
        cell_count=occurrence.cell_count,
        node_count=occurrence.node_count,
        representation_output_sha256=occurrence.representation_output_sha256,
    )
    assert partition.ordered_headers_json == occurrence.ordered_headers_json
    assert partition.item_count == 0


def test_occurrence_ordered_headers_are_exact_bounded_canonical_text() -> None:
    fixture = _build_fixture()
    occurrence = fixture["occurrences"][0]
    values = _occurrence_build_values(occurrence)

    class ForeignText(str):
        pass

    hostile_headers = (
        {
            "ordered_headers_json": '["H", "I"]',
            "ordered_headers_sha256": _sha(b'["H", "I"]'),
            "header_count": 2,
            "row_count": 0,
            "cell_count": 0,
            "result_presence": "present_empty",
        },
        {
            "ordered_headers_json": '["H",1]',
            "ordered_headers_sha256": _sha(b'["H",1]'),
            "header_count": 2,
            "row_count": 0,
            "cell_count": 0,
            "result_presence": "present_empty",
        },
        {"header_count": 0},
        {"ordered_headers_sha256": _sha("wrong ordered-header digest")},
        {"ordered_headers_json": ForeignText(occurrence.ordered_headers_json)},
        {
            "ordered_headers_json": _canonical(["x" * (4 * 1024 * 1024)]).decode("utf-8"),
            "ordered_headers_sha256": _sha(_canonical(["x" * (4 * 1024 * 1024)])),
        },
        {"header_count": 4_097},
    )
    for mutation in hostile_headers:
        with pytest.raises(ValueProjectionPlanError):
            ValueProjectionPlanOccurrenceV1.build(**{**values, **mutation})

    empty_json, empty_sha256 = _ordered_headers()
    empty = ValueProjectionPlanOccurrenceV1.build(
        **{
            **values,
            "ordered_headers_json": empty_json,
            "ordered_headers_sha256": empty_sha256,
            "header_count": 0,
            "row_count": 0,
            "cell_count": 0,
            "result_presence": "present_empty",
        }
    )
    assert empty.ordered_headers_json == "[]"
    assert empty.ordered_headers() == ()


def test_coordinated_ordered_header_reseal_cannot_replay_under_old_plan_pin() -> None:
    fixture = _build_fixture()
    plan = fixture["plan"]
    occurrence = fixture["occurrences"][0]
    forged_json, forged_sha256 = _ordered_headers("FORGED")
    changed_occurrence = ValueProjectionPlanOccurrenceV1.build(
        **{
            **_occurrence_build_values(occurrence),
            "ordered_headers_json": forged_json,
            "ordered_headers_sha256": forged_sha256,
        }
    )
    changed_plan = ValueProjectionPlanV1.build(
        **{
            **_plan_build_values(fixture),
            "occurrence_plans": (changed_occurrence,),
        }
    )

    assert changed_plan.plan_sha256 != plan.plan_sha256
    with pytest.raises(ValueProjectionPlanError, match="external authority pins"):
        ValueProjectionPlanV1.from_row(
            changed_plan.to_row(),
            expected_plan_sha256=plan.plan_sha256,
            expected_raw_authority_bundle_sha256=plan.raw_authority_bundle_sha256,
            expected_ownership_receipt_sha256=plan.ownership_receipt_sha256,
        )


def test_exact_runtime_classes_guard_every_decoder_and_builder_surface() -> None:
    fixture = _build_fixture()
    plan = fixture["plan"]
    row_items = (
        (ValueProjectionPlanExpectedUnitV1, fixture["units"][0]),
        (ValueProjectionPlanAssignmentV1, fixture["assignments"][0]),
        (ValueProjectionPlanOwnershipObservationV1, fixture["observations"][0]),
        (ValueProjectionPlanOwnershipPartitionV1, fixture["partitions"][0]),
        (ValueProjectionPlanOwnershipBindingV1, fixture["bindings"][0]),
        (ValueProjectionPlanObservationSourceV1, fixture["sources"][0]),
        (ValueProjectionPlanOccurrenceV1, fixture["occurrences"][0]),
        (ValueProjectionPlanSourceRecordV1, fixture["source_record_plans"][0]),
    )
    for dto_type, item in row_items:
        foreign_type = type(f"Foreign{dto_type.__name__}", (dto_type,), {})
        with pytest.raises(ValueProjectionPlanError, match="foreign exact class"):
            foreign_type.from_row(item.to_row())
        with pytest.raises(ValueProjectionPlanError, match="foreign exact class"):
            foreign_type.from_canonical_bytes(item.canonical_bytes())

    for dto_type, item, digest_field in (
        (ValueProjectionPlanObservationSourceV1, fixture["sources"][0], "source_sha256"),
        (
            ValueProjectionPlanOccurrenceV1,
            fixture["occurrences"][0],
            "occurrence_plan_sha256",
        ),
        (
            ValueProjectionPlanSourceRecordV1,
            fixture["source_record_plans"][0],
            "source_record_plan_sha256",
        ),
    ):
        foreign_type = type(f"ForeignBuild{dto_type.__name__}", (dto_type,), {})
        values = {
            field.name: getattr(item, field.name)
            for field in fields(item)
            if field.name != digest_field
        }
        with pytest.raises(ValueProjectionPlanError, match="foreign exact class"):
            foreign_type.build(**values)

    foreign_plan_type = type("ForeignValueProjectionPlanV1", (ValueProjectionPlanV1,), {})
    pins = {
        "expected_plan_sha256": plan.plan_sha256,
        "expected_raw_authority_bundle_sha256": plan.raw_authority_bundle_sha256,
        "expected_ownership_receipt_sha256": plan.ownership_receipt_sha256,
    }
    with pytest.raises(ValueProjectionPlanError, match="foreign exact class"):
        foreign_plan_type.from_row(plan.to_row(), **pins)
    with pytest.raises(ValueProjectionPlanError, match="foreign exact class"):
        foreign_plan_type.from_canonical_bytes(plan.canonical_bytes(), **pins)
    with pytest.raises(ValueProjectionPlanError, match="foreign exact class"):
        foreign_plan_type.build(**_plan_build_values(fixture))


def test_stats_and_live_lossless_partition_histograms_are_exact() -> None:
    stats = _build_lossless_fixture(
        representation_kind="stats_lossless_records_v1",
        source_family="stats",
        source_relation_kind="stats_lossless_record_v1",
        projection_record_kinds=(
            "result_set",
            "raw_headers",
            "raw_rows",
            "header",
            "row",
            "cell",
        ),
        occurrence_shape={
            "result_path": None,
            "container_kind": "nba_api_result_set",
            "result_presence": "present",
            "header_count": 1,
            "row_count": 1,
            "cell_count": 1,
            "node_count": 0,
            "container_count": 1,
            "missing_count": 0,
            "null_count": 0,
            "parent_state_sha256": _sha(_canonical(["present"])),
        },
    )
    live = _build_lossless_fixture(
        representation_kind="live_lossless_nodes_v1",
        source_family="live",
        source_relation_kind="live_lossless_node_v1",
        projection_record_kinds=(
            "result_declaration",
            "result_occurrence",
            "node",
            "field_cell",
        ),
        occurrence_shape={
            "result_path": "$.game",
            "container_kind": "nba_api_live_json_array",
            "result_presence": "present",
            "header_count": 1,
            "row_count": 1,
            "cell_count": 1,
            "node_count": 1,
            "container_count": 1,
            "missing_count": 0,
            "null_count": 0,
            "parent_state_sha256": _sha(_canonical(["present"])),
        },
    )
    nested_live = _build_lossless_fixture(
        representation_kind="live_lossless_nodes_v1",
        source_family="live",
        source_relation_kind="live_lossless_node_v1",
        projection_record_kinds=(
            "result_declaration",
            "result_occurrence",
            "node",
            "node",
            "node",
            "node",
            "node",
            "field_cell",
            "field_cell",
            "field_cell",
            "field_cell",
        ),
        occurrence_shape={
            "result_path": "$.game",
            "container_kind": "nba_api_live_json_object",
            "result_presence": "present",
            "header_count": 4,
            "row_count": 1,
            "cell_count": 4,
            "node_count": 1,
            "container_count": 1,
            "missing_count": 0,
            "null_count": 0,
            "parent_state_sha256": _sha(_canonical(["present"])),
        },
    )
    missing_stats = _build_lossless_fixture(
        representation_kind="stats_lossless_records_v1",
        source_family="stats",
        source_relation_kind="stats_lossless_record_v1",
        projection_record_kinds=("missing_expected", "raw_headers", "raw_rows"),
        occurrence_shape={
            "result_path": None,
            "container_kind": "nba_api_result_set",
            "result_presence": "missing",
            "header_count": 0,
            "row_count": 0,
            "cell_count": 0,
            "node_count": 0,
            "container_count": 0,
            "missing_count": 1,
            "null_count": 0,
            "parent_state_sha256": _sha(_canonical(["missing"])),
        },
    )

    assert _replay(stats["plan"]) == stats["plan"]
    assert _replay(live["plan"]) == live["plan"]
    assert _replay(nested_live["plan"]) == nested_live["plan"]
    assert _replay(missing_stats["plan"]) == missing_stats["plan"]
    assert stats["plan"].source_record_count == 6
    assert live["plan"].source_record_count == 4
    assert nested_live["plan"].source_record_count == 11
    assert missing_stats["plan"].source_record_count == 3


def test_live_recursive_nodes_use_owned_histogram_not_raw_root_count() -> None:
    with pytest.raises(ValueProjectionPlanError, match="root-node denominator"):
        _build_lossless_fixture(
            representation_kind="live_lossless_nodes_v1",
            source_family="live",
            source_relation_kind="live_lossless_node_v1",
            projection_record_kinds=(
                "result_declaration",
                "result_occurrence",
                "node",
                "field_cell",
                "field_cell",
            ),
            occurrence_shape={
                "result_path": "$.game",
                "container_kind": "nba_api_live_json_array",
                "result_presence": "present",
                "header_count": 1,
                "row_count": 2,
                "cell_count": 2,
                "node_count": 2,
                "container_count": 1,
                "missing_count": 0,
                "null_count": 0,
                "parent_state_sha256": _sha(_canonical(["present"])),
            },
        )


def test_occurrence_counts_cannot_survive_coordinated_plan_and_receipt_reseals() -> None:
    attacks = (
        {
            "representation_kind": "rectangular_result_cells_v1",
            "source_family": "stats",
            "source_relation_kind": "result_cell_v1",
            "projection_record_kinds": ("cell",),
            "occurrence_shape": {
                "result_path": None,
                "container_kind": "nba_api_result_set",
                "result_presence": "present",
                "header_count": 2,
                "row_count": 1,
                "cell_count": 2,
                "node_count": 0,
                "container_count": 1,
                "missing_count": 0,
                "null_count": 0,
                "parent_state_sha256": _sha(_canonical(["present"])),
            },
        },
        {
            "representation_kind": "stats_lossless_records_v1",
            "source_family": "stats",
            "source_relation_kind": "stats_lossless_record_v1",
            "projection_record_kinds": (
                "result_set",
                "raw_headers",
                "raw_rows",
                "header",
                "row",
            ),
            "occurrence_shape": {
                "result_path": None,
                "container_kind": "nba_api_result_set",
                "result_presence": "present",
                "header_count": 1,
                "row_count": 1,
                "cell_count": 1,
                "node_count": 0,
                "container_count": 1,
                "missing_count": 0,
                "null_count": 0,
                "parent_state_sha256": _sha(_canonical(["present"])),
            },
        },
        {
            "representation_kind": "live_lossless_nodes_v1",
            "source_family": "live",
            "source_relation_kind": "live_lossless_node_v1",
            "projection_record_kinds": (
                "result_declaration",
                "result_occurrence",
                "node",
            ),
            "occurrence_shape": {
                "result_path": "$.game",
                "container_kind": "nba_api_live_json_array",
                "result_presence": "present",
                "header_count": 1,
                "row_count": 1,
                "cell_count": 1,
                "node_count": 1,
                "container_count": 1,
                "missing_count": 0,
                "null_count": 0,
                "parent_state_sha256": _sha(_canonical(["present"])),
            },
        },
    )
    for attack in attacks:
        with pytest.raises(ValueProjectionPlanError, match="exact .* partition"):
            _build_lossless_fixture(**attack)


def test_raw_occurrence_presence_path_parent_and_count_algebra_is_exact() -> None:
    fixture = _build_fixture()
    stats_values = _occurrence_build_values(fixture["occurrences"][0])
    for mutation in (
        {
            "result_presence": "null",
            "container_count": 1,
            "null_count": 1,
            "node_count": 1,
            "parent_state_sha256": _sha(_canonical(["null"])),
        },
        {"result_path": "$.forged"},
        {"container_count": True},
        {"parent_state_sha256": None},
        {"parent_state_sha256": _sha(_canonical(["missing"]))},
    ):
        with pytest.raises(ValueProjectionPlanError):
            ValueProjectionPlanOccurrenceV1.build(**{**stats_values, **mutation})

    live = _build_lossless_fixture(
        representation_kind="live_lossless_nodes_v1",
        source_family="live",
        source_relation_kind="live_lossless_node_v1",
        projection_record_kinds=("result_declaration", "result_occurrence", "node", "field_cell"),
        occurrence_shape={
            "result_path": "$.game",
            "container_kind": "nba_api_live_json_array",
            "result_presence": "present",
            "header_count": 1,
            "row_count": 1,
            "cell_count": 1,
            "node_count": 1,
            "container_count": 1,
            "missing_count": 0,
            "null_count": 0,
            "parent_state_sha256": _sha(_canonical(["present"])),
        },
    )
    live_values = _occurrence_build_values(live["occurrence"])
    empty_headers_json, empty_headers_sha256 = _ordered_headers()
    empty_object = ValueProjectionPlanOccurrenceV1.build(
        **{
            **live_values,
            "container_kind": "nba_api_live_json_object",
            "result_presence": "empty_object",
            "ordered_headers_json": empty_headers_json,
            "ordered_headers_sha256": empty_headers_sha256,
            "header_count": 0,
            "row_count": 0,
            "cell_count": 0,
            "node_count": 1,
            "container_count": 1,
            "missing_count": 0,
            "null_count": 0,
            "parent_state_sha256": _sha(_canonical(["present"])),
        }
    )
    missing = ValueProjectionPlanOccurrenceV1.build(
        **{
            **live_values,
            "result_presence": "missing",
            "ordered_headers_json": empty_headers_json,
            "ordered_headers_sha256": empty_headers_sha256,
            "header_count": 0,
            "row_count": 0,
            "cell_count": 0,
            "node_count": 0,
            "container_count": 0,
            "missing_count": 2,
            "null_count": 0,
            "parent_state_sha256": _sha(_canonical(["missing", "missing"])),
        }
    )
    assert empty_object.result_presence == "empty_object"
    assert missing.missing_count == 2
    with pytest.raises(ValueProjectionPlanError, match="parent-state commitment"):
        ValueProjectionPlanOccurrenceV1.build(
            **{
                **live_values,
                "result_presence": "missing",
                "ordered_headers_json": empty_headers_json,
                "ordered_headers_sha256": empty_headers_sha256,
                "header_count": 0,
                "row_count": 0,
                "cell_count": 0,
                "node_count": 0,
                "container_count": 0,
                "missing_count": 2,
                "null_count": 0,
                "parent_state_sha256": _sha(_canonical(["missing"])),
            }
        )


def test_residual_source_record_domains_and_order_are_exact() -> None:
    fixture = _build_fixture()
    response = fixture["source_record_plans"][1]
    values = {
        item.name: getattr(response, item.name)
        for item in fields(response)
        if item.name != "source_record_plan_sha256"
    }
    wrong_first = ValueProjectionPlanSourceRecordV1.build(
        **{**values, "projection_record_kind": "json_node"}
    )
    with pytest.raises(ValueProjectionPlanError, match="response-residual record order"):
        ValueProjectionPlanV1.build(
            **{
                **_plan_build_values(fixture),
                "source_record_plans": (fixture["source_record_plans"][0], wrong_first),
            }
        )

    live_response = ValueProjectionPlanSourceRecordV1.build(
        **{
            **values,
            "source_relation_kind": "live_lossless_node_v1",
            "projection_record_kind": "node",
        }
    )
    assert live_response.projection_record_kind == "node"

    with pytest.raises(ValueProjectionPlanError, match="relation, owner, or record kind"):
        ValueProjectionPlanSourceRecordV1.build(
            **{
                **values,
                "source_relation_kind": "live_lossless_node_v1",
                "projection_record_kind": "result_declaration",
            }
        )


def test_public_domains_are_exactly_closed() -> None:
    assert VALUE_PROJECTION_PLAN_SOURCE_INPUT_KINDS_V1 == (
        "parser_input_body",
        "declared_bodyless_packet",
    )
    assert VALUE_PROJECTION_PLAN_REPRESENTATION_KINDS_V1 == (
        "rectangular_result_cells_v1",
        "stats_lossless_records_v1",
        "live_lossless_nodes_v1",
        "response_lossless_records_v1",
        "response_fixed_zero_v1",
    )
    assert VALUE_PROJECTION_PLAN_UNIT_KINDS_V1 == (
        "result_occurrence",
        "response_residual",
        "response_fixed_zero",
    )
    assert VALUE_PROJECTION_PLAN_SOURCE_FAMILIES_V1 == ("stats", "live", "static")
    assert VALUE_PROJECTION_PLAN_SOURCE_RELATION_KINDS_V1 == (
        "result_cell_v1",
        "stats_lossless_record_v1",
        "live_lossless_node_v1",
    )
    assert VALUE_PROJECTION_PLAN_RECORD_KINDS_V1 == (
        "cell",
        "response",
        "json_node",
        "result_set",
        "missing_expected",
        "raw_headers",
        "raw_rows",
        "header",
        "row",
        "result_declaration",
        "result_occurrence",
        "node",
        "field_cell",
    )


def test_rows_are_value_free_and_have_exact_ordered_shapes() -> None:
    plan = _build_fixture()["plan"]
    row = plan.to_row()
    assert tuple(row) == ("schema_version", *(item.name for item in fields(ValueProjectionPlanV1)))

    stack: list[object] = [row]
    while stack:
        item = stack.pop()
        if type(item) is dict:
            mapping = item
            assert "value" not in mapping
            assert "canonical_json" not in mapping
            assert "headers_json" not in mapping
            stack.extend(mapping.values())
        elif type(item) is list:
            stack.extend(item)


def test_external_pins_are_checked_before_semantic_replay() -> None:
    plan = _build_fixture()["plan"]
    wrong = _sha("wrong")
    for kwargs in (
        {"expected_plan_sha256": wrong},
        {"expected_raw_authority_bundle_sha256": wrong},
        {"expected_ownership_receipt_sha256": wrong},
    ):
        pins = {
            "expected_plan_sha256": plan.plan_sha256,
            "expected_raw_authority_bundle_sha256": plan.raw_authority_bundle_sha256,
            "expected_ownership_receipt_sha256": plan.ownership_receipt_sha256,
            **kwargs,
        }
        with pytest.raises(ValueProjectionPlanError):
            ValueProjectionPlanV1.from_row(plan.to_row(), **pins)


def test_reorder_sparse_duplicate_and_cross_bundle_rows_fail() -> None:
    fixture = _build_fixture()
    common = {
        "raw_authority_bundle_sha256": fixture["bundle"],
        "ownership_receipt_sha256": fixture["ownership_receipt"],
        "expected_unit_inventory_sha256": fixture["inventory_sha"],
        "expected_units": fixture["units"],
        "assignments": fixture["assignments"],
        "ownership_observations": fixture["observations"],
        "ownership_partitions": fixture["partitions"],
        "ownership_bindings": fixture["bindings"],
        "observation_sources": fixture["sources"],
        "occurrence_plans": fixture["occurrences"],
        "source_record_plans": fixture["source_record_plans"],
    }
    attacks = (
        {"ownership_partitions": tuple(reversed(fixture["partitions"]))},
        {"ownership_bindings": (fixture["bindings"][0], fixture["bindings"][0])},
        {"expected_units": fixture["units"][1:]},
        {
            "observation_sources": (
                ValueProjectionPlanObservationSourceV1.build(
                    raw_authority_bundle_sha256=_sha("foreign-bundle"),
                    observation_record_sha256=fixture["sources"][0].observation_record_sha256,
                    observation_sha256=fixture["sources"][0].observation_sha256,
                    observation_ordinal=0,
                    source_input_kind="parser_input_body",
                    source_family="stats",
                    body_blob_sha256=_sha("body-blob"),
                    body_blob_readback_sha256=_sha("body-readback"),
                    parser_input_object_sha256=_sha("parser-input"),
                    payload_sha256=_sha("payload-0"),
                    payload_byte_count=11,
                ),
                fixture["sources"][1],
            )
        },
    )
    for attack in attacks:
        with pytest.raises(ValueProjectionPlanError):
            ValueProjectionPlanV1.build(**{**common, **attack})


def test_fixed_zero_and_empty_residual_algebra_is_fail_closed() -> None:
    fixture = _build_fixture()
    valid = fixture["observations"][1].to_row()
    values = {name: valid[name] for name in tuple(valid)[2:]}
    values["response_partition_kind"] = "response_residual"
    values["fixed_zero_landing_sha256"] = None
    hostile = _semantic_row(
        kind="nbadb_lossless_observation_ownership_v1",
        digest_field="observation_ownership_sha256",
        values=values,
    )
    with pytest.raises(ValueProjectionPlanError, match="fixed-zero"):
        ValueProjectionPlanOwnershipObservationV1.from_row(hostile)

    fixed = dict(valid)
    fixed["response_record_count"] = 1
    fixed_values = {name: fixed[name] for name in tuple(fixed)[2:]}
    fixed_hostile = _semantic_row(
        kind="nbadb_lossless_observation_ownership_v1",
        digest_field="observation_ownership_sha256",
        values=fixed_values,
    )
    with pytest.raises(ValueProjectionPlanError):
        ValueProjectionPlanOwnershipObservationV1.from_row(fixed_hostile)


def test_source_family_relation_and_occurrence_container_joins_fail_closed() -> None:
    fixture = _build_fixture()
    record = fixture["source_record_plans"][1]
    values = {
        item.name: getattr(record, item.name)
        for item in fields(record)
        if item.name != "source_record_plan_sha256"
    }
    values["source_relation_kind"] = "live_lossless_node_v1"
    with pytest.raises(ValueProjectionPlanError, match="relation, owner, or record kind"):
        ValueProjectionPlanSourceRecordV1.build(**values)

    occurrence = fixture["occurrences"][0]
    occurrence_values = {
        item.name: getattr(occurrence, item.name)
        for item in fields(occurrence)
        if item.name != "occurrence_plan_sha256"
    }
    occurrence_values["container_kind"] = "nba_api_live_json_array"
    with pytest.raises(ValueProjectionPlanError, match="container, path, or presence"):
        ValueProjectionPlanOccurrenceV1.build(**occurrence_values)


def test_rectangular_count_path_presence_and_exact_type_guards() -> None:
    fixture = _build_fixture()
    occurrence = fixture["occurrences"][0]
    values = {
        item.name: getattr(occurrence, item.name)
        for item in fields(occurrence)
        if item.name != "occurrence_plan_sha256"
    }
    for mutation in (
        {"cell_count": 2},
        {"result_path": "$..secret"},
        {"result_presence": "sometimes"},
        {"header_count": True},
    ):
        with pytest.raises(ValueProjectionPlanError):
            ValueProjectionPlanOccurrenceV1.build(**{**values, **mutation})

    source_row = fixture["sources"][0].to_row()
    source_row["payload_byte_count"] = True
    with pytest.raises(ValueProjectionPlanError):
        ValueProjectionPlanObservationSourceV1.from_row(source_row)


def test_coordinated_source_reseal_cannot_replay_under_old_plan_pin() -> None:
    fixture = _build_fixture()
    plan = fixture["plan"]
    source = fixture["sources"][0]
    changed_source = ValueProjectionPlanObservationSourceV1.build(
        raw_authority_bundle_sha256=source.raw_authority_bundle_sha256,
        observation_record_sha256=source.observation_record_sha256,
        observation_sha256=source.observation_sha256,
        observation_ordinal=source.observation_ordinal,
        source_input_kind="parser_input_body",
        source_family="stats",
        body_blob_sha256=source.body_blob_sha256,
        body_blob_readback_sha256=source.body_blob_readback_sha256,
        parser_input_object_sha256=source.parser_input_object_sha256,
        payload_sha256=_sha("coordinated-new-payload"),
        payload_byte_count=12,
    )
    changed = ValueProjectionPlanV1.build(
        raw_authority_bundle_sha256=fixture["bundle"],
        ownership_receipt_sha256=fixture["ownership_receipt"],
        expected_unit_inventory_sha256=fixture["inventory_sha"],
        expected_units=fixture["units"],
        assignments=fixture["assignments"],
        ownership_observations=fixture["observations"],
        ownership_partitions=fixture["partitions"],
        ownership_bindings=fixture["bindings"],
        observation_sources=(changed_source, fixture["sources"][1]),
        occurrence_plans=fixture["occurrences"],
        source_record_plans=fixture["source_record_plans"],
    )
    assert changed.plan_sha256 != plan.plan_sha256
    with pytest.raises(ValueProjectionPlanError, match="external authority pins"):
        ValueProjectionPlanV1.from_row(
            changed.to_row(),
            expected_plan_sha256=plan.plan_sha256,
            expected_raw_authority_bundle_sha256=plan.raw_authority_bundle_sha256,
            expected_ownership_receipt_sha256=plan.ownership_receipt_sha256,
        )


@pytest.mark.parametrize(
    "payload",
    [
        b'{"a":1,"a":2}',
        b"[" * 10_000 + b"0" + b"]" * 10_000,
        b'{"n":' + b"9" * 10_000 + b"}",
    ],
)
def test_hostile_json_is_bounded_and_normalized(payload: bytes) -> None:
    fixture = _build_fixture()
    plan = fixture["plan"]
    with pytest.raises(ValueProjectionPlanError) as exc_info:
        ValueProjectionPlanV1.from_canonical_bytes(
            payload,
            expected_plan_sha256=plan.plan_sha256,
            expected_raw_authority_bundle_sha256=plan.raw_authority_bundle_sha256,
            expected_ownership_receipt_sha256=plan.ownership_receipt_sha256,
        )
    assert exc_info.value.__cause__ is None
    assert not isinstance(exc_info.value, RecursionError)


def test_noncanonical_json_and_foreign_row_keys_fail() -> None:
    plan = _build_fixture()["plan"]
    with pytest.raises(ValueProjectionPlanError, match="noncanonical"):
        ValueProjectionPlanV1.from_canonical_bytes(
            plan.canonical_bytes() + b"\n",
            expected_plan_sha256=plan.plan_sha256,
            expected_raw_authority_bundle_sha256=plan.raw_authority_bundle_sha256,
            expected_ownership_receipt_sha256=plan.ownership_receipt_sha256,
        )
    row = plan.to_row()
    row["foreign"] = 1
    with pytest.raises(ValueProjectionPlanError, match="ordered row shape"):
        ValueProjectionPlanV1.from_row(
            row,
            expected_plan_sha256=plan.plan_sha256,
            expected_raw_authority_bundle_sha256=plan.raw_authority_bundle_sha256,
            expected_ownership_receipt_sha256=plan.ownership_receipt_sha256,
        )


def test_hostile_subclass_is_rejected_before_callback() -> None:
    fixture = _build_fixture()
    calls = 0

    class BombUnit(ValueProjectionPlanExpectedUnitV1):
        def to_row(self) -> dict[str, object]:
            nonlocal calls
            calls += 1
            raise RuntimeError("private callback detail")

    original = fixture["units"][0]
    hostile = BombUnit(**{item.name: getattr(original, item.name) for item in fields(original)})
    with pytest.raises(ValueProjectionPlanError, match="foreign DTO type") as exc_info:
        ValueProjectionPlanV1.build(
            raw_authority_bundle_sha256=fixture["bundle"],
            ownership_receipt_sha256=fixture["ownership_receipt"],
            expected_unit_inventory_sha256=fixture["inventory_sha"],
            expected_units=(hostile, *fixture["units"][1:]),
            assignments=fixture["assignments"],
            ownership_observations=fixture["observations"],
            ownership_partitions=fixture["partitions"],
            ownership_bindings=fixture["bindings"],
            observation_sources=fixture["sources"],
            occurrence_plans=fixture["occurrences"],
            source_record_plans=fixture["source_record_plans"],
        )
    assert calls == 0
    assert exc_info.value.__cause__ is None


def test_module_is_dependency_pure_and_validation_has_no_full_rescans() -> None:
    source_path = Path(plan_module.__file__).resolve()
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imports = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )
    assert imports <= {"__future__", "dataclasses", "hashlib", "json", "re", "typing"}

    forbidden_calls = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"index", "count"}
        ):
            forbidden_calls.append((node.func.attr, node.lineno))
    assert forbidden_calls == []
