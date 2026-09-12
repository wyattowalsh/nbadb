from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any, cast

import pytest

import nbadb.contracts.value_projection as value_projection
from nbadb.contracts.independent_live_value_decoder import DecodedLiveNodeV1
from nbadb.contracts.lossless_ownership import (
    LosslessObservationOwnershipV1,
    LosslessOwnershipAuthorityV1,
    LosslessOwnershipBindingV1,
    LosslessOwnershipPartitionV1,
)
from nbadb.contracts.public_value_types import (
    ExpectedValueUnitInventoryV1,
    ExpectedValueUnitV1,
    ValueRepresentationAssignmentV1,
)
from nbadb.contracts.value_projection import (
    BODY_VALUE_PROJECTION_SCHEMA_VERSION,
    VALUE_PROJECTION_COORDINATE_FIELDS_V1,
    BodyValueProjectionReceiptV1,
    ValueProjectionError,
    ValueProjectionItemV1,
    ValueProjectionPartitionV1,
    ValueProjectionReceiptV1,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _canonical_value_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _named_header_slots(headers: tuple[str, ...]) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "header_reference_kind": "named",
            "header_name": header,
            "header_value_sha256": _canonical_value_sha(header),
        }
        for header in headers
    )


def _coordinate(**changes: object) -> dict[str, object]:
    value = {field_name: None for field_name in VALUE_PROJECTION_COORDINATE_FIELDS_V1}
    value.update(changes)
    return value


def _item(
    *,
    item_ordinal: int,
    partition_ordinal: int,
    partition_item_ordinal: int,
    observation_ordinal: int,
    representation_kind: str,
    unit_kind: str,
    unit_ordinal: int,
    record_kind: str,
    coordinate: dict[str, object],
    value_state: str = "canonical",
    value: object = None,
    missing_presence_kind: str | None = None,
    structural_value_kind: str | None = None,
    source_input_kind: str = "parser_input_body",
    occurrence_ordinal: int = 0,
) -> ValueProjectionItemV1:
    occurrence_sha256 = (
        _sha(f"occurrence-{observation_ordinal}-{occurrence_ordinal}")
        if unit_kind == "result_occurrence"
        else None
    )
    exact_occurrence_ordinal = occurrence_ordinal if unit_kind == "result_occurrence" else None
    exact_coordinate = coordinate if type(coordinate) is not dict else dict(coordinate)
    if (
        type(exact_coordinate) is dict
        and representation_kind == "live_lossless_nodes_v1"
        and record_kind in {"result_occurrence", "node", "field_cell"}
    ):
        node_ordinal = exact_coordinate["node_ordinal"]
        if type(node_ordinal) is int and exact_coordinate["decoder_value_sha256"] is None:
            exact_coordinate["decoder_value_sha256"] = _sha(
                f"decoder-value-{observation_ordinal}-{node_ordinal}"
            )
    if (
        type(exact_coordinate) is dict
        and representation_kind == "live_lossless_nodes_v1"
        and record_kind == "node"
        and exact_coordinate["matches_result_occurrence"] is None
    ):
        exact_coordinate["matches_result_occurrence"] = False
    kwargs: dict[str, object] = {
        "raw_authority_bundle_sha256": _sha("bundle"),
        "ownership_binding_sha256": _sha(f"binding-{item_ordinal}"),
        "ownership_binding_ordinal": item_ordinal,
        "source_record_sha256": _sha(f"record-{item_ordinal}"),
        "observation_record_sha256": _sha(f"observation-record-{observation_ordinal}"),
        "observation_sha256": _sha(f"observation-{observation_ordinal}"),
        "observation_ordinal": observation_ordinal,
        "ownership_partition_sha256": _sha(f"ownership-partition-{partition_ordinal}"),
        "partition_ordinal": partition_ordinal,
        "unit_sha256": _sha(f"unit-{unit_ordinal}"),
        "unit_ordinal": unit_ordinal,
        "assignment_sha256": _sha(f"assignment-{unit_ordinal}"),
        "source_input_kind": source_input_kind,
        "representation_kind": representation_kind,
        "unit_kind": unit_kind,
        "occurrence_sha256": occurrence_sha256,
        "occurrence_ordinal": exact_occurrence_ordinal,
        "global_item_ordinal": item_ordinal,
        "partition_item_ordinal": partition_item_ordinal,
        "record_kind": record_kind,
        "coordinate": exact_coordinate,
        "value_state": value_state,
    }
    if value_state == "canonical":
        kwargs["value"] = value
    elif value_state == "missing":
        kwargs["missing_presence_kind"] = missing_presence_kind
    elif value_state == "structural_container":
        kwargs["structural_value_kind"] = structural_value_kind
    return ValueProjectionItemV1.build(**cast("Any", kwargs))


def _result_partition(
    *,
    partition_ordinal: int,
    observation_ordinal: int,
    observation_partition_ordinal: int,
    unit_ordinal: int,
    representation_kind: str,
    items: tuple[ValueProjectionItemV1, ...],
    result_name: str,
    ordered_headers: tuple[str, ...],
    result_presence: str = "present",
    header_count: int = 0,
    ordered_header_slots: tuple[dict[str, object], ...] | None = None,
    header_record_count: int | None = None,
    header_slot_count: int | None = None,
    field_count: int = 0,
    row_count: int = 0,
    cell_count: int = 0,
    node_count: int = 0,
    source_input_kind: str = "parser_input_body",
    occurrence_ordinal: int = 0,
    result_duplicate_ordinal: int = 0,
    provider_result_ordinal: int = 0,
    expected_result_ordinal: int = 0,
    canonical_result_ordinal: int = 0,
    result_path: str | None = None,
    container_kind: str | None = None,
) -> ValueProjectionPartitionV1:
    exact_container_kind = container_kind
    if exact_container_kind is None:
        exact_container_kind = (
            "nba_api_live_json_array"
            if representation_kind == "live_lossless_nodes_v1"
            else "nba_api_result_set"
        )
    exact_ordered_headers: tuple[str, ...] | None = ordered_headers
    exact_header_count = header_count
    exact_header_slots = ordered_header_slots
    exact_header_record_count = 0 if header_record_count is None else header_record_count
    exact_header_slot_count = 0 if header_slot_count is None else header_slot_count
    if representation_kind == "stats_lossless_records_v1":
        if exact_header_slots is None:
            exact_header_slots = _named_header_slots(ordered_headers)
            exact_header_record_count = len(ordered_headers)
            exact_header_slot_count = len(ordered_headers)
        exact_ordered_headers = None
        exact_header_count = 0
    return ValueProjectionPartitionV1.build(
        raw_authority_bundle_sha256=_sha("bundle"),
        ownership_partition_sha256=_sha(f"ownership-partition-{partition_ordinal}"),
        observation_record_sha256=_sha(f"observation-record-{observation_ordinal}"),
        observation_sha256=_sha(f"observation-{observation_ordinal}"),
        observation_ordinal=observation_ordinal,
        partition_ordinal=partition_ordinal,
        observation_partition_ordinal=observation_partition_ordinal,
        partition_kind="result_occurrence",
        source_input_kind=cast("Any", source_input_kind),
        items=items,
        occurrence_sha256=_sha(f"occurrence-{observation_ordinal}-{occurrence_ordinal}"),
        occurrence_ordinal=occurrence_ordinal,
        unit_sha256=_sha(f"unit-{unit_ordinal}"),
        unit_ordinal=unit_ordinal,
        assignment_sha256=_sha(f"assignment-{unit_ordinal}"),
        representation_kind=cast("Any", representation_kind),
        result_name=result_name,
        result_duplicate_ordinal=result_duplicate_ordinal,
        provider_result_ordinal=provider_result_ordinal,
        expected_result_ordinal=expected_result_ordinal,
        canonical_result_ordinal=canonical_result_ordinal,
        result_path=(f"$.results[{observation_ordinal}]" if result_path is None else result_path),
        container_kind=exact_container_kind,
        result_presence=result_presence,
        ordered_headers=exact_ordered_headers,
        header_count=exact_header_count,
        ordered_header_slots=exact_header_slots,
        header_record_count=exact_header_record_count,
        header_slot_count=exact_header_slot_count,
        field_count=field_count,
        row_count=row_count,
        cell_count=cell_count,
        node_count=node_count,
        representation_output_sha256=_sha(f"output-{partition_ordinal}"),
    )


def _zero_residual_partition(
    *,
    partition_ordinal: int,
    observation_ordinal: int,
    observation_partition_ordinal: int,
    source_input_kind: str = "parser_input_body",
) -> ValueProjectionPartitionV1:
    return ValueProjectionPartitionV1.build(
        raw_authority_bundle_sha256=_sha("bundle"),
        ownership_partition_sha256=_sha(f"ownership-partition-{partition_ordinal}"),
        observation_record_sha256=_sha(f"observation-record-{observation_ordinal}"),
        observation_sha256=_sha(f"observation-{observation_ordinal}"),
        observation_ordinal=observation_ordinal,
        partition_ordinal=partition_ordinal,
        observation_partition_ordinal=observation_partition_ordinal,
        partition_kind="response_residual",
        source_input_kind=cast("Any", source_input_kind),
        items=(),
    )


def _positive_residual_partition(
    *,
    partition_ordinal: int,
    observation_ordinal: int,
    unit_ordinal: int,
    items: tuple[ValueProjectionItemV1, ...],
    source_input_kind: str,
) -> ValueProjectionPartitionV1:
    return ValueProjectionPartitionV1.build(
        raw_authority_bundle_sha256=_sha("bundle"),
        ownership_partition_sha256=_sha(f"ownership-partition-{partition_ordinal}"),
        observation_record_sha256=_sha(f"observation-record-{observation_ordinal}"),
        observation_sha256=_sha(f"observation-{observation_ordinal}"),
        observation_ordinal=observation_ordinal,
        partition_ordinal=partition_ordinal,
        observation_partition_ordinal=0,
        partition_kind="response_residual",
        source_input_kind=cast("Any", source_input_kind),
        items=items,
        unit_sha256=_sha(f"unit-{unit_ordinal}"),
        unit_ordinal=unit_ordinal,
        assignment_sha256=_sha(f"assignment-{unit_ordinal}"),
        representation_kind="response_lossless_records_v1",
        node_count=sum(item.record_kind in {"node", "json_node"} for item in items),
        representation_output_sha256=_sha(f"output-{partition_ordinal}"),
    )


def _fixed_zero_partition(
    *,
    partition_ordinal: int,
    observation_ordinal: int,
    unit_ordinal: int,
) -> ValueProjectionPartitionV1:
    return ValueProjectionPartitionV1.build(
        raw_authority_bundle_sha256=_sha("bundle"),
        ownership_partition_sha256=_sha(f"ownership-partition-{partition_ordinal}"),
        observation_record_sha256=_sha(f"observation-record-{observation_ordinal}"),
        observation_sha256=_sha(f"observation-{observation_ordinal}"),
        observation_ordinal=observation_ordinal,
        partition_ordinal=partition_ordinal,
        observation_partition_ordinal=0,
        partition_kind="response_fixed_zero",
        source_input_kind="declared_bodyless_packet",
        items=(),
        unit_sha256=_sha(f"unit-{unit_ordinal}"),
        unit_ordinal=unit_ordinal,
        assignment_sha256=_sha(f"assignment-{unit_ordinal}"),
        representation_kind="response_fixed_zero_v1",
        fixed_zero_landing_sha256=_sha(f"fixed-zero-{partition_ordinal}"),
    )


def _authority_kwargs(authority: LosslessOwnershipAuthorityV1) -> dict[str, object]:
    return {
        "ownership_receipt_row": authority.receipt.to_row(),
        "expected_unit_rows": tuple(
            unit.to_row() for unit in authority.expected_unit_inventory.units
        ),
        "representation_assignment_rows": tuple(
            assignment.to_row() for assignment in authority.representation_assignments
        ),
        "ownership_observation_rows": tuple(
            observation.to_row() for observation in authority.observations
        ),
        "ownership_partition_rows": tuple(partition.to_row() for partition in authority.partitions),
        "ownership_binding_rows": tuple(binding.to_row() for binding in authority.bindings),
    }


def _rebuild_item(
    item: ValueProjectionItemV1,
    *,
    binding: LosslessOwnershipBindingV1,
    ownership_partition: LosslessOwnershipPartitionV1,
    assignment: ValueRepresentationAssignmentV1,
) -> ValueProjectionItemV1:
    kwargs: dict[str, object] = {
        "raw_authority_bundle_sha256": binding.raw_authority_bundle_sha256,
        "ownership_binding_sha256": binding.binding_sha256,
        "ownership_binding_ordinal": binding.binding_ordinal,
        "source_record_sha256": binding.source_record_sha256,
        "observation_record_sha256": binding.observation_record_sha256,
        "observation_sha256": binding.observation_sha256,
        "observation_ordinal": binding.observation_ordinal,
        "ownership_partition_sha256": ownership_partition.partition_sha256,
        "partition_ordinal": binding.partition_ordinal,
        "unit_sha256": binding.unit_sha256,
        "unit_ordinal": binding.unit_ordinal,
        "assignment_sha256": binding.assignment_sha256,
        "source_input_kind": assignment.source_input_kind,
        "representation_kind": assignment.representation_kind,
        "unit_kind": binding.ownership_kind,
        "occurrence_sha256": binding.occurrence_sha256,
        "occurrence_ordinal": binding.occurrence_ordinal,
        "global_item_ordinal": binding.binding_ordinal,
        "partition_item_ordinal": item.partition_item_ordinal,
        "record_kind": item.record_kind,
        "coordinate": item.coordinate(),
        "value_state": item.value_state,
    }
    if item.value_state == "canonical":
        kwargs["value"] = item.value()
    elif item.value_state == "missing":
        kwargs["missing_presence_kind"] = item.presence_kind
    elif item.value_state == "structural_container":
        kwargs["structural_value_kind"] = item.value_kind
    return ValueProjectionItemV1.build(**cast("Any", kwargs))


def _rebuild_partition(
    partition: ValueProjectionPartitionV1,
    *,
    ownership_partition: LosslessOwnershipPartitionV1,
    items: tuple[ValueProjectionItemV1, ...],
    assignments: tuple[ValueRepresentationAssignmentV1, ...],
) -> ValueProjectionPartitionV1:
    assignment = (
        None
        if ownership_partition.unit_ordinal is None
        else assignments[ownership_partition.unit_ordinal]
    )
    ordered_headers = (
        None
        if partition.ordered_headers_json is None
        else tuple(cast("list[str]", json.loads(partition.ordered_headers_json)))
    )
    ordered_header_slots = (
        None
        if partition.ordered_header_slots_json is None
        else tuple(cast("list[dict[str, object]]", json.loads(partition.ordered_header_slots_json)))
    )
    return ValueProjectionPartitionV1.build(
        raw_authority_bundle_sha256=ownership_partition.raw_authority_bundle_sha256,
        ownership_partition_sha256=ownership_partition.partition_sha256,
        observation_record_sha256=ownership_partition.observation_record_sha256,
        observation_sha256=ownership_partition.observation_sha256,
        observation_ordinal=ownership_partition.observation_ordinal,
        partition_ordinal=ownership_partition.partition_ordinal,
        observation_partition_ordinal=ownership_partition.observation_partition_ordinal,
        partition_kind=ownership_partition.partition_kind,
        source_input_kind=partition.source_input_kind,
        items=items,
        occurrence_sha256=ownership_partition.occurrence_sha256,
        occurrence_ordinal=ownership_partition.occurrence_ordinal,
        unit_sha256=ownership_partition.unit_sha256,
        unit_ordinal=ownership_partition.unit_ordinal,
        assignment_sha256=ownership_partition.assignment_sha256,
        representation_kind=None if assignment is None else assignment.representation_kind,
        result_name=partition.result_name,
        result_duplicate_ordinal=partition.result_duplicate_ordinal,
        provider_result_ordinal=partition.provider_result_ordinal,
        expected_result_ordinal=partition.expected_result_ordinal,
        canonical_result_ordinal=partition.canonical_result_ordinal,
        result_path=partition.result_path,
        container_kind=partition.container_kind,
        result_presence=partition.result_presence,
        ordered_headers=ordered_headers,
        header_count=partition.header_count,
        ordered_header_slots=ordered_header_slots,
        header_record_count=partition.header_record_count,
        header_slot_count=partition.header_slot_count,
        field_count=partition.field_count,
        row_count=partition.row_count,
        cell_count=partition.cell_count,
        node_count=partition.node_count,
        representation_output_sha256=partition.representation_output_sha256,
        fixed_zero_landing_sha256=ownership_partition.fixed_zero_landing_sha256,
    )


def _rebuild_authority_with_assignments(
    authority: LosslessOwnershipAuthorityV1,
    assignments: tuple[ValueRepresentationAssignmentV1, ...],
) -> LosslessOwnershipAuthorityV1:
    units = authority.expected_unit_inventory.units
    bindings = tuple(
        LosslessOwnershipBindingV1.build(
            raw_authority_bundle_sha256=binding.raw_authority_bundle_sha256,
            observation_record_sha256=binding.observation_record_sha256,
            observation_sha256=binding.observation_sha256,
            observation_ordinal=binding.observation_ordinal,
            binding_ordinal=binding.binding_ordinal,
            observation_record_ordinal=binding.observation_record_ordinal,
            partition_ordinal=binding.partition_ordinal,
            source_record_sha256=binding.source_record_sha256,
            expected_unit=units[binding.unit_ordinal],
            assignment=assignments[binding.unit_ordinal],
        )
        for binding in authority.bindings
    )
    partitions = tuple(
        LosslessOwnershipPartitionV1.build(
            raw_authority_bundle_sha256=partition.raw_authority_bundle_sha256,
            observation_record_sha256=partition.observation_record_sha256,
            observation_sha256=partition.observation_sha256,
            observation_ordinal=partition.observation_ordinal,
            partition_ordinal=partition.partition_ordinal,
            observation_partition_ordinal=partition.observation_partition_ordinal,
            partition_kind=partition.partition_kind,
            bindings=tuple(
                binding
                for binding in bindings
                if binding.partition_ordinal == partition.partition_ordinal
            ),
            expected_unit=(
                None if partition.unit_ordinal is None else units[partition.unit_ordinal]
            ),
            assignment=(
                None if partition.unit_ordinal is None else assignments[partition.unit_ordinal]
            ),
            fixed_zero_landing_sha256=partition.fixed_zero_landing_sha256,
        )
        for partition in authority.partitions
    )
    observations = tuple(
        LosslessObservationOwnershipV1.build(
            raw_authority_bundle_sha256=observation.raw_authority_bundle_sha256,
            observation_record_sha256=observation.observation_record_sha256,
            observation_sha256=observation.observation_sha256,
            observation_ordinal=observation.observation_ordinal,
            source_input_kind=observation.source_input_kind,
            partitions=tuple(
                partition
                for partition in partitions
                if partition.observation_ordinal == observation.observation_ordinal
            ),
            bindings=tuple(
                binding
                for binding in bindings
                if binding.observation_ordinal == observation.observation_ordinal
            ),
        )
        for observation in authority.observations
    )
    return LosslessOwnershipAuthorityV1.build(
        raw_authority_bundle_sha256=authority.receipt.raw_authority_bundle_sha256,
        expected_unit_inventory=authority.expected_unit_inventory,
        representation_assignments=assignments,
        observations=observations,
        partitions=partitions,
        bindings=bindings,
    )


def _seal_projection(
    *,
    partitions: tuple[ValueProjectionPartitionV1, ...],
    items: tuple[ValueProjectionItemV1, ...],
) -> tuple[
    ValueProjectionReceiptV1,
    tuple[ValueProjectionPartitionV1, ...],
    tuple[ValueProjectionItemV1, ...],
    LosslessOwnershipAuthorityV1,
]:
    items = _augment_live_fixture_items(partitions=partitions, items=items)
    unit_partitions = tuple(
        partition for partition in partitions if partition.unit_ordinal is not None
    )
    units_by_ordinal: list[ExpectedValueUnitV1 | None] = [None] * len(unit_partitions)
    assignments_by_ordinal: list[ValueRepresentationAssignmentV1 | None] = [None] * len(
        unit_partitions
    )
    for partition in unit_partitions:
        unit_ordinal = cast("int", partition.unit_ordinal)
        unit = ExpectedValueUnitV1.build(
            raw_authority_bundle_sha256=partition.raw_authority_bundle_sha256,
            unit_ordinal=unit_ordinal,
            observation_sha256=partition.observation_sha256,
            observation_ordinal=partition.observation_ordinal,
            unit_kind=partition.partition_kind,
            occurrence_sha256=partition.occurrence_sha256,
            occurrence_ordinal=partition.occurrence_ordinal,
        )
        assignment = ValueRepresentationAssignmentV1.build(
            expected_unit=unit,
            source_input_kind=partition.source_input_kind,
            representation_kind=cast("Any", partition.representation_kind),
        )
        if unit_ordinal >= len(units_by_ordinal) or units_by_ordinal[unit_ordinal] is not None:
            raise AssertionError("fixture unit ordinals are not unique and contiguous")
        units_by_ordinal[unit_ordinal] = unit
        assignments_by_ordinal[unit_ordinal] = assignment
    if any(unit is None for unit in units_by_ordinal) or any(
        assignment is None for assignment in assignments_by_ordinal
    ):
        raise AssertionError("fixture unit ordinals are not contiguous")
    units = cast("tuple[ExpectedValueUnitV1, ...]", tuple(units_by_ordinal))
    assignments = cast(
        "tuple[ValueRepresentationAssignmentV1, ...]",
        tuple(assignments_by_ordinal),
    )
    inventory = ExpectedValueUnitInventoryV1.build(
        raw_authority_bundle_sha256=_sha("bundle"),
        units=units,
    )
    observation_record_ordinals: dict[int, int] = {}
    ownership_bindings: list[LosslessOwnershipBindingV1] = []
    for binding_ordinal, item in enumerate(items):
        unit = units[item.unit_ordinal]
        assignment = assignments[item.unit_ordinal]
        observation_record_ordinal = observation_record_ordinals.get(item.observation_ordinal, 0)
        ownership_bindings.append(
            LosslessOwnershipBindingV1.build(
                raw_authority_bundle_sha256=item.raw_authority_bundle_sha256,
                observation_record_sha256=item.observation_record_sha256,
                observation_sha256=item.observation_sha256,
                observation_ordinal=item.observation_ordinal,
                binding_ordinal=binding_ordinal,
                observation_record_ordinal=observation_record_ordinal,
                partition_ordinal=item.partition_ordinal,
                source_record_sha256=item.source_record_sha256,
                expected_unit=unit,
                assignment=assignment,
            )
        )
        observation_record_ordinals[item.observation_ordinal] = observation_record_ordinal + 1
    binding_tuple = tuple(ownership_bindings)
    ownership_partitions: list[LosslessOwnershipPartitionV1] = []
    for partition in partitions:
        partition_bindings = tuple(
            binding
            for binding in binding_tuple
            if binding.partition_ordinal == partition.partition_ordinal
        )
        unit = None if partition.unit_ordinal is None else units[partition.unit_ordinal]
        assignment = None if partition.unit_ordinal is None else assignments[partition.unit_ordinal]
        ownership_partitions.append(
            LosslessOwnershipPartitionV1.build(
                raw_authority_bundle_sha256=partition.raw_authority_bundle_sha256,
                observation_record_sha256=partition.observation_record_sha256,
                observation_sha256=partition.observation_sha256,
                observation_ordinal=partition.observation_ordinal,
                partition_ordinal=partition.partition_ordinal,
                observation_partition_ordinal=partition.observation_partition_ordinal,
                partition_kind=partition.partition_kind,
                bindings=partition_bindings,
                expected_unit=unit,
                assignment=assignment,
                fixed_zero_landing_sha256=partition.fixed_zero_landing_sha256,
            )
        )
    ownership_partition_tuple = tuple(ownership_partitions)
    observations: list[LosslessObservationOwnershipV1] = []
    for observation_ordinal in sorted({item.observation_ordinal for item in partitions}):
        projection_observation_partitions = tuple(
            partition
            for partition in partitions
            if partition.observation_ordinal == observation_ordinal
        )
        observation_partitions = tuple(
            partition
            for partition in ownership_partition_tuple
            if partition.observation_ordinal == observation_ordinal
        )
        observation_bindings = tuple(
            binding
            for binding in binding_tuple
            if binding.observation_ordinal == observation_ordinal
        )
        first = projection_observation_partitions[0]
        observations.append(
            LosslessObservationOwnershipV1.build(
                raw_authority_bundle_sha256=first.raw_authority_bundle_sha256,
                observation_record_sha256=first.observation_record_sha256,
                observation_sha256=first.observation_sha256,
                observation_ordinal=observation_ordinal,
                source_input_kind=first.source_input_kind,
                partitions=observation_partitions,
                bindings=observation_bindings,
            )
        )
    authority = LosslessOwnershipAuthorityV1.build(
        raw_authority_bundle_sha256=_sha("bundle"),
        expected_unit_inventory=inventory,
        representation_assignments=assignments,
        observations=tuple(observations),
        partitions=ownership_partition_tuple,
        bindings=binding_tuple,
    )
    rebuilt_items = tuple(
        _rebuild_item(
            item,
            binding=binding_tuple[item.global_item_ordinal],
            ownership_partition=ownership_partition_tuple[item.partition_ordinal],
            assignment=assignments[item.unit_ordinal],
        )
        for item in items
    )
    rebuilt_partitions = tuple(
        _rebuild_partition(
            partition,
            ownership_partition=ownership_partition_tuple[partition.partition_ordinal],
            items=tuple(
                item
                for item in rebuilt_items
                if item.partition_ordinal == partition.partition_ordinal
            ),
            assignments=assignments,
        )
        for partition in partitions
    )
    receipt = ValueProjectionReceiptV1.build(
        raw_authority_bundle_sha256=_sha("bundle"),
        partitions=rebuilt_partitions,
        items=rebuilt_items,
        **cast("Any", _authority_kwargs(authority)),
    )
    return receipt, rebuilt_partitions, rebuilt_items, authority


def _receipt(
    *,
    partitions: tuple[ValueProjectionPartitionV1, ...],
    items: tuple[ValueProjectionItemV1, ...],
    authority: LosslessOwnershipAuthorityV1 | None = None,
) -> ValueProjectionReceiptV1:
    if authority is None:
        return _seal_projection(partitions=partitions, items=items)[0]
    return ValueProjectionReceiptV1.build(
        raw_authority_bundle_sha256=_sha("bundle"),
        partitions=partitions,
        items=items,
        **cast("Any", _authority_kwargs(authority)),
    )


def _complete_projection() -> tuple[
    ValueProjectionReceiptV1,
    tuple[ValueProjectionPartitionV1, ...],
    tuple[ValueProjectionItemV1, ...],
    LosslessOwnershipAuthorityV1,
]:
    rectangular_item = _item(
        item_ordinal=0,
        partition_ordinal=0,
        partition_item_ordinal=0,
        observation_ordinal=0,
        representation_kind="rectangular_result_cells_v1",
        unit_kind="result_occurrence",
        unit_ordinal=0,
        record_kind="cell",
        coordinate=_coordinate(
            result_name="Rows",
            result_duplicate_ordinal=0,
            provider_result_ordinal=0,
            expected_result_ordinal=0,
            canonical_result_ordinal=0,
            result_path="$.results[0]",
            container_kind="nba_api_result_set",
            result_presence="present",
            header_name="A",
            header_ordinal=0,
            header_duplicate_ordinal=0,
            row_ordinal=0,
            row_duplicate_ordinal=0,
            row_value_sha256=_sha("rect-row-0"),
            cell_ordinal=0,
            value_duplicate_ordinal=0,
        ),
        value=1,
    )
    stats_header = _item(
        item_ordinal=1,
        partition_ordinal=2,
        partition_item_ordinal=0,
        observation_ordinal=1,
        representation_kind="stats_lossless_records_v1",
        unit_kind="result_occurrence",
        unit_ordinal=1,
        record_kind="header",
        coordinate=_coordinate(
            result_name="Stats",
            result_duplicate_ordinal=0,
            provider_result_ordinal=0,
            expected_result_ordinal=0,
            canonical_result_ordinal=0,
            result_path="$.results[1]",
            container_kind="nba_api_result_set",
            result_presence="present",
            header_reference_kind="named",
            header_name="B",
            header_ordinal=0,
            header_value_sha256=_canonical_value_sha("B"),
            header_duplicate_ordinal=0,
        ),
        value="B",
    )
    stats_cell = _item(
        item_ordinal=2,
        partition_ordinal=2,
        partition_item_ordinal=1,
        observation_ordinal=1,
        representation_kind="stats_lossless_records_v1",
        unit_kind="result_occurrence",
        unit_ordinal=1,
        record_kind="cell",
        coordinate=_coordinate(
            result_name="Stats",
            result_duplicate_ordinal=0,
            provider_result_ordinal=0,
            expected_result_ordinal=0,
            canonical_result_ordinal=0,
            result_path="$.results[1]",
            container_kind="nba_api_result_set",
            result_presence="present",
            header_reference_kind="named",
            header_name="B",
            header_ordinal=0,
            header_value_sha256=_canonical_value_sha("B"),
            header_duplicate_ordinal=0,
            row_ordinal=0,
            row_duplicate_ordinal=0,
            row_value_sha256=_sha("stats-row-0"),
            cell_ordinal=0,
            value_duplicate_ordinal=0,
        ),
        value="x",
    )
    live_node = _item(
        item_ordinal=3,
        partition_ordinal=4,
        partition_item_ordinal=0,
        observation_ordinal=2,
        representation_kind="live_lossless_nodes_v1",
        unit_kind="result_occurrence",
        unit_ordinal=2,
        record_kind="node",
        coordinate=_coordinate(
            result_name="Live",
            result_duplicate_ordinal=0,
            provider_result_ordinal=0,
            expected_result_ordinal=0,
            canonical_result_ordinal=0,
            result_path="$.results[2]",
            container_kind="nba_api_live_json_object",
            result_presence="present",
            node_ordinal=0,
            json_path="$",
            depth=0,
            context_result_name="Live",
            context_result_ordinal=0,
            context_result_occurrence=0,
            row_ordinal=0,
        ),
        value={},
    )
    live_missing_node = _item(
        item_ordinal=4,
        partition_ordinal=4,
        partition_item_ordinal=1,
        observation_ordinal=2,
        representation_kind="live_lossless_nodes_v1",
        unit_kind="result_occurrence",
        unit_ordinal=2,
        record_kind="node",
        coordinate=_coordinate(
            result_name="Live",
            result_duplicate_ordinal=0,
            provider_result_ordinal=0,
            expected_result_ordinal=0,
            canonical_result_ordinal=0,
            result_path="$.results[2]",
            container_kind="nba_api_live_json_object",
            result_presence="present",
            node_ordinal=1,
            parent_node_ordinal=0,
            json_path='$["F"]',
            parent_json_path="$",
            depth=1,
            object_key="F",
            context_result_name="Live",
            context_result_ordinal=0,
            context_result_occurrence=0,
            known_contract_field=True,
            row_ordinal=0,
        ),
        value_state="missing",
        missing_presence_kind="missing",
    )
    live_missing_cell = _item(
        item_ordinal=5,
        partition_ordinal=4,
        partition_item_ordinal=2,
        observation_ordinal=2,
        representation_kind="live_lossless_nodes_v1",
        unit_kind="result_occurrence",
        unit_ordinal=2,
        record_kind="field_cell",
        coordinate=_coordinate(
            result_name="Live",
            result_duplicate_ordinal=0,
            provider_result_ordinal=0,
            expected_result_ordinal=0,
            canonical_result_ordinal=0,
            result_path="$.results[2]",
            container_kind="nba_api_live_json_object",
            result_presence="present",
            field_name="F",
            field_ordinal=0,
            row_ordinal=0,
            cell_ordinal=0,
            value_duplicate_ordinal=0,
            node_ordinal=1,
            json_path='$["F"]',
            key_presence="optional",
            owner_result_name="Live",
            owner_result_ordinal=0,
            owner_result_occurrence=0,
            context_result_name="Live",
            context_result_ordinal=0,
            context_result_occurrence=0,
            known_contract_field=True,
        ),
        value_state="missing",
        missing_presence_kind="missing",
    )
    response_item = _item(
        item_ordinal=6,
        partition_ordinal=6,
        partition_item_ordinal=0,
        observation_ordinal=3,
        representation_kind="response_lossless_records_v1",
        unit_kind="response_residual",
        unit_ordinal=3,
        record_kind="json_node",
        coordinate=_coordinate(node_ordinal=0, json_path="$", depth=0),
        value=[],
        source_input_kind="declared_bodyless_packet",
    )
    items = (
        rectangular_item,
        stats_header,
        stats_cell,
        live_node,
        live_missing_node,
        live_missing_cell,
        response_item,
    )
    partitions = (
        _result_partition(
            partition_ordinal=0,
            observation_ordinal=0,
            observation_partition_ordinal=0,
            unit_ordinal=0,
            representation_kind="rectangular_result_cells_v1",
            items=(rectangular_item,),
            result_name="Rows",
            ordered_headers=("A",),
            header_count=1,
            row_count=1,
            cell_count=1,
        ),
        _zero_residual_partition(
            partition_ordinal=1,
            observation_ordinal=0,
            observation_partition_ordinal=1,
        ),
        _result_partition(
            partition_ordinal=2,
            observation_ordinal=1,
            observation_partition_ordinal=0,
            unit_ordinal=1,
            representation_kind="stats_lossless_records_v1",
            items=(stats_header, stats_cell),
            result_name="Stats",
            ordered_headers=("B",),
            header_count=1,
            row_count=1,
            cell_count=1,
        ),
        _zero_residual_partition(
            partition_ordinal=3,
            observation_ordinal=1,
            observation_partition_ordinal=1,
        ),
        _result_partition(
            partition_ordinal=4,
            observation_ordinal=2,
            observation_partition_ordinal=0,
            unit_ordinal=2,
            representation_kind="live_lossless_nodes_v1",
            items=(live_node, live_missing_node, live_missing_cell),
            result_name="Live",
            ordered_headers=("F",),
            header_count=1,
            field_count=1,
            row_count=1,
            cell_count=1,
            node_count=2,
            container_kind="nba_api_live_json_object",
        ),
        _zero_residual_partition(
            partition_ordinal=5,
            observation_ordinal=2,
            observation_partition_ordinal=1,
        ),
        _positive_residual_partition(
            partition_ordinal=6,
            observation_ordinal=3,
            unit_ordinal=3,
            items=(response_item,),
            source_input_kind="declared_bodyless_packet",
        ),
        _fixed_zero_partition(partition_ordinal=7, observation_ordinal=4, unit_ordinal=4),
        _result_partition(
            partition_ordinal=8,
            observation_ordinal=5,
            observation_partition_ordinal=0,
            unit_ordinal=5,
            representation_kind="rectangular_result_cells_v1",
            items=(),
            result_name="Zero",
            ordered_headers=("Z",),
            result_presence="present_empty",
            header_count=1,
        ),
        _zero_residual_partition(
            partition_ordinal=9,
            observation_ordinal=5,
            observation_partition_ordinal=1,
        ),
    )
    return _seal_projection(partitions=partitions, items=items)


def _seal_live_projection(
    *,
    items: tuple[ValueProjectionItemV1, ...],
    result_name: str,
    ordered_headers: tuple[str, ...],
    container_kind: str,
    row_count: int,
    cell_count: int,
    node_count: int,
) -> tuple[
    ValueProjectionReceiptV1,
    tuple[ValueProjectionPartitionV1, ...],
    tuple[ValueProjectionItemV1, ...],
    LosslessOwnershipAuthorityV1,
]:
    result_partition = _result_partition(
        partition_ordinal=0,
        observation_ordinal=0,
        observation_partition_ordinal=0,
        unit_ordinal=0,
        representation_kind="live_lossless_nodes_v1",
        items=items,
        result_name=result_name,
        ordered_headers=ordered_headers,
        header_count=len(ordered_headers),
        field_count=len(ordered_headers),
        row_count=row_count,
        cell_count=cell_count,
        node_count=node_count,
        result_path="$",
        container_kind=container_kind,
    )
    residual_partition = _zero_residual_partition(
        partition_ordinal=1,
        observation_ordinal=0,
        observation_partition_ordinal=1,
    )
    return _seal_projection(
        partitions=(result_partition, residual_partition),
        items=items,
    )


def _two_row_live_projection() -> tuple[
    ValueProjectionReceiptV1,
    tuple[ValueProjectionPartitionV1, ...],
    tuple[ValueProjectionItemV1, ...],
    LosslessOwnershipAuthorityV1,
]:
    result = {
        "result_name": "Rows",
        "result_duplicate_ordinal": 0,
        "provider_result_ordinal": 0,
        "expected_result_ordinal": 0,
        "canonical_result_ordinal": 0,
        "result_path": "$",
        "container_kind": "nba_api_live_json_array",
        "result_presence": "present",
    }

    def node(
        *,
        ordinal: int,
        parent: int | None,
        path: str,
        parent_path: str | None,
        depth: int,
        row: int | None,
        array_ordinal: int | None = None,
        object_key: str | None = None,
        object_key_ordinal: int | None = None,
        structural_kind: str | None = None,
        value: object = None,
    ) -> ValueProjectionItemV1:
        kwargs: dict[str, object] = {
            "item_ordinal": ordinal,
            "partition_ordinal": 0,
            "partition_item_ordinal": ordinal,
            "observation_ordinal": 0,
            "representation_kind": "live_lossless_nodes_v1",
            "unit_kind": "result_occurrence",
            "unit_ordinal": 0,
            "record_kind": "node",
            "coordinate": _coordinate(
                **result,
                node_ordinal=ordinal,
                parent_node_ordinal=parent,
                json_path=path,
                parent_json_path=parent_path,
                depth=depth,
                object_key=object_key,
                object_key_ordinal=object_key_ordinal,
                array_ordinal=array_ordinal,
                context_result_name="Rows",
                context_result_ordinal=0,
                context_result_occurrence=0,
                known_contract_field=True if object_key is not None else None,
                row_ordinal=row,
            ),
        }
        if structural_kind is None:
            kwargs["value"] = value
        else:
            kwargs["value_state"] = "structural_container"
            kwargs["structural_value_kind"] = structural_kind
        return _item(**cast("Any", kwargs))

    nodes = (
        node(
            ordinal=0,
            parent=None,
            path="$",
            parent_path=None,
            depth=0,
            row=None,
            structural_kind="array",
        ),
        node(
            ordinal=1,
            parent=0,
            path="$[0]",
            parent_path="$",
            depth=1,
            row=0,
            array_ordinal=0,
            structural_kind="object",
        ),
        node(
            ordinal=2,
            parent=1,
            path='$[0]["F"]',
            parent_path="$[0]",
            depth=2,
            row=0,
            object_key="F",
            object_key_ordinal=0,
            value=1,
        ),
        node(
            ordinal=3,
            parent=1,
            path='$[0]["G"]',
            parent_path="$[0]",
            depth=2,
            row=0,
            object_key="G",
            object_key_ordinal=1,
            value=10,
        ),
        node(
            ordinal=4,
            parent=0,
            path="$[1]",
            parent_path="$",
            depth=1,
            row=1,
            array_ordinal=1,
            structural_kind="object",
        ),
        node(
            ordinal=5,
            parent=4,
            path='$[1]["F"]',
            parent_path="$[1]",
            depth=2,
            row=1,
            object_key="F",
            object_key_ordinal=0,
            value=1,
        ),
        node(
            ordinal=6,
            parent=4,
            path='$[1]["G"]',
            parent_path="$[1]",
            depth=2,
            row=1,
            object_key="G",
            object_key_ordinal=1,
            value=11,
        ),
    )
    field_nodes = ((2, 1), (3, 10), (5, 1), (6, 11))
    fields: list[ValueProjectionItemV1] = []
    for cell_ordinal, (node_ordinal, value) in enumerate(field_nodes):
        row_ordinal = cell_ordinal // 2
        field_ordinal = cell_ordinal % 2
        field_name = ("F", "G")[field_ordinal]
        fields.append(
            _item(
                item_ordinal=7 + cell_ordinal,
                partition_ordinal=0,
                partition_item_ordinal=7 + cell_ordinal,
                observation_ordinal=0,
                representation_kind="live_lossless_nodes_v1",
                unit_kind="result_occurrence",
                unit_ordinal=0,
                record_kind="field_cell",
                coordinate=_coordinate(
                    **result,
                    field_name=field_name,
                    field_ordinal=field_ordinal,
                    row_ordinal=row_ordinal,
                    cell_ordinal=cell_ordinal,
                    value_duplicate_ordinal=(row_ordinal if field_name == "F" else 0),
                    node_ordinal=node_ordinal,
                    json_path=f'$[{row_ordinal}]["{field_name}"]',
                    key_presence="required",
                    owner_result_name="Rows",
                    owner_result_ordinal=0,
                    owner_result_occurrence=0,
                    context_result_name="Rows",
                    context_result_ordinal=0,
                    context_result_occurrence=0,
                    known_contract_field=True,
                ),
                value=value,
            )
        )
    items = (*nodes, *fields)
    return _seal_live_projection(
        items=items,
        result_name="Rows",
        ordered_headers=("F", "G"),
        container_kind="nba_api_live_json_array",
        row_count=2,
        cell_count=4,
        node_count=7,
    )


def _two_occurrence_live_projection() -> tuple[
    ValueProjectionReceiptV1,
    tuple[ValueProjectionPartitionV1, ...],
    tuple[ValueProjectionItemV1, ...],
    LosslessOwnershipAuthorityV1,
]:
    result = {
        "result_name": "Rows",
        "result_duplicate_ordinal": 0,
        "provider_result_ordinal": 0,
        "expected_result_ordinal": 0,
        "canonical_result_ordinal": 0,
        "result_path": "$",
        "container_kind": "nba_api_live_json_object",
        "result_presence": "present",
    }
    root = _item(
        item_ordinal=0,
        partition_ordinal=0,
        partition_item_ordinal=0,
        observation_ordinal=0,
        representation_kind="live_lossless_nodes_v1",
        unit_kind="result_occurrence",
        unit_ordinal=0,
        record_kind="node",
        coordinate=_coordinate(
            **result,
            node_ordinal=0,
            json_path="$",
            depth=0,
            context_result_name="Rows",
            context_result_ordinal=0,
            context_result_occurrence=0,
            row_ordinal=0,
        ),
        value_state="structural_container",
        structural_value_kind="object",
    )
    nested = _item(
        item_ordinal=1,
        partition_ordinal=0,
        partition_item_ordinal=1,
        observation_ordinal=0,
        representation_kind="live_lossless_nodes_v1",
        unit_kind="result_occurrence",
        unit_ordinal=0,
        record_kind="node",
        coordinate=_coordinate(
            **result,
            node_ordinal=1,
            parent_node_ordinal=0,
            json_path='$["nested"]',
            parent_json_path="$",
            depth=1,
            object_key="nested",
            object_key_ordinal=0,
            context_result_name="Rows",
            context_result_ordinal=0,
            context_result_occurrence=1,
            row_ordinal=0,
        ),
        value_state="structural_container",
        structural_value_kind="object",
    )
    nested_value = _item(
        item_ordinal=2,
        partition_ordinal=0,
        partition_item_ordinal=2,
        observation_ordinal=0,
        representation_kind="live_lossless_nodes_v1",
        unit_kind="result_occurrence",
        unit_ordinal=0,
        record_kind="node",
        coordinate=_coordinate(
            **result,
            node_ordinal=2,
            parent_node_ordinal=1,
            json_path='$["nested"]["value"]',
            parent_json_path='$["nested"]',
            depth=2,
            object_key="value",
            object_key_ordinal=0,
            context_result_name="Rows",
            context_result_ordinal=0,
            context_result_occurrence=1,
            row_ordinal=0,
        ),
        value=7,
    )
    return _seal_live_projection(
        items=(root, nested, nested_value),
        result_name="Rows",
        ordered_headers=(),
        container_kind="nba_api_live_json_object",
        row_count=2,
        cell_count=0,
        node_count=3,
    )


def _reseal_row(
    row: dict[str, object],
    *,
    dto: type[object],
    digest_field: str,
) -> dict[str, object]:
    values = {
        key: value for key, value in row.items() if key not in {"schema_version", digest_field}
    }
    maximum = (
        value_projection._MAX_ROW_BYTES
        if dto is ValueProjectionItemV1
        else value_projection._MAX_RECEIPT_BYTES
    )
    row[digest_field] = value_projection._canonical_sha256(
        {
            "schema_version": BODY_VALUE_PROJECTION_SCHEMA_VERSION,
            "kind": cast("Any", dto).kind,
            **values,
        },
        maximum_bytes=maximum,
    )
    return row


def _reseal_semantic_row(
    row: dict[str, object],
    *,
    kind: str,
    digest_field: str,
) -> dict[str, object]:
    row[digest_field] = value_projection._canonical_sha256(
        {
            "schema_version": BODY_VALUE_PROJECTION_SCHEMA_VERSION,
            "kind": kind,
            **{
                key: value
                for key, value in row.items()
                if key not in {"schema_version", digest_field}
            },
        },
        maximum_bytes=64 * 1024,
    )
    return row


def _resealed_item_coordinate(
    item: ValueProjectionItemV1,
    **changes: object,
) -> ValueProjectionItemV1:
    row = item.to_row()
    coordinate = item.coordinate()
    coordinate.update(changes)
    encoded = value_projection._canonical_json_bytes(
        coordinate,
        maximum_bytes=value_projection.MAX_VALUE_PROJECTION_PATH_BYTES * 8,
    )
    row["coordinate_json"] = encoded.decode("utf-8")
    row["coordinate_sha256"] = hashlib.sha256(encoded).hexdigest()
    return ValueProjectionItemV1.from_row(
        _reseal_row(row, dto=ValueProjectionItemV1, digest_field="item_sha256")
    )


def _augment_live_fixture_items(
    *,
    partitions: tuple[ValueProjectionPartitionV1, ...],
    items: tuple[ValueProjectionItemV1, ...],
) -> tuple[ValueProjectionItemV1, ...]:
    live_partitions = {
        partition.partition_ordinal: partition
        for partition in partitions
        if partition.representation_kind == "live_lossless_nodes_v1"
    }
    if not live_partitions or any(
        item.record_kind in {"result_declaration", "result_occurrence"} for item in items
    ):
        return items

    exact_items = list(items)
    node_indexes: dict[tuple[int, int], int] = {}
    first_nodes: dict[tuple[int, int], tuple[int, ValueProjectionItemV1, dict[str, object]]] = {}
    for index, item in enumerate(items):
        if item.record_kind != "node":
            continue
        coordinate = item.coordinate()
        node_ordinal = cast("int", coordinate["node_ordinal"])
        node_indexes[(item.observation_ordinal, node_ordinal)] = index
        if item.representation_kind != "live_lossless_nodes_v1":
            continue
        occurrence = cast("int", coordinate["context_result_occurrence"])
        key = (item.partition_ordinal, occurrence)
        prior = first_nodes.get(key)
        if prior is None or node_ordinal < cast("int", prior[2]["node_ordinal"]):
            first_nodes[key] = (index, item, coordinate)

    for index, item, _coordinate_value in first_nodes.values():
        exact_items[index] = _resealed_item_coordinate(item, matches_result_occurrence=True)

    children_by_parent: dict[tuple[int, int], list[int]] = {}
    live_node_indexes: dict[tuple[int, int], int] = {}
    for index, item in enumerate(exact_items):
        if item.representation_kind != "live_lossless_nodes_v1" or item.record_kind != "node":
            continue
        coordinate = item.coordinate()
        node_ordinal = cast("int", coordinate["node_ordinal"])
        live_node_indexes[(item.observation_ordinal, node_ordinal)] = index
        parent_ordinal = cast("int | None", coordinate["parent_node_ordinal"])
        if parent_ordinal is not None:
            children_by_parent.setdefault((item.observation_ordinal, parent_ordinal), []).append(
                node_ordinal
            )

    reconstructed: dict[tuple[int, int], object] = {}
    for observation_ordinal in sorted({key[0] for key in live_node_indexes}):
        node_ordinals = sorted(
            (key[1] for key in live_node_indexes if key[0] == observation_ordinal),
            reverse=True,
        )
        for node_ordinal in node_ordinals:
            index = live_node_indexes[(observation_ordinal, node_ordinal)]
            item = exact_items[index]
            coordinate = item.coordinate()
            child_ordinals = children_by_parent.get((observation_ordinal, node_ordinal), [])
            if item.value_state == "missing":
                value = None
            elif item.value_state != "structural_container":
                value = item.value()
            elif item.value_kind == "array":
                value = [
                    reconstructed[(observation_ordinal, child_ordinal)]
                    for child_ordinal in child_ordinals
                    if exact_items[
                        live_node_indexes[(observation_ordinal, child_ordinal)]
                    ].value_state
                    != "missing"
                ]
            else:
                value = {
                    cast(
                        "str",
                        exact_items[
                            live_node_indexes[(observation_ordinal, child_ordinal)]
                        ].coordinate()["object_key"],
                    ): reconstructed[(observation_ordinal, child_ordinal)]
                    for child_ordinal in child_ordinals
                    if exact_items[
                        live_node_indexes[(observation_ordinal, child_ordinal)]
                    ].value_state
                    != "missing"
                }
            reconstructed[(observation_ordinal, node_ordinal)] = value
            digest_payload: object = (
                {"presence": "missing"}
                if item.presence_kind == "missing"
                else {"presence": item.presence_kind, "value": value}
            )
            decoder_value_sha256 = value_projection._canonical_sha256(
                digest_payload,
                maximum_bytes=value_projection.MAX_VALUE_PROJECTION_TOTAL_CANONICAL_BYTES,
            )
            exact_items[index] = _resealed_item_coordinate(
                item,
                decoder_value_sha256=decoder_value_sha256,
            )

    decoder_value_by_node = {
        (
            item.observation_ordinal,
            cast("int", item.coordinate()["node_ordinal"]),
        ): item.coordinate()["decoder_value_sha256"]
        for item in exact_items
        if item.representation_kind == "live_lossless_nodes_v1" and item.record_kind == "node"
    }
    for index, item in enumerate(exact_items):
        if item.representation_kind != "live_lossless_nodes_v1" or item.record_kind != "field_cell":
            continue
        coordinate = item.coordinate()
        exact_items[index] = _resealed_item_coordinate(
            item,
            decoder_value_sha256=decoder_value_by_node[
                (item.observation_ordinal, cast("int", coordinate["node_ordinal"]))
            ],
        )

    first_nodes = {
        key: (index, exact_items[index], exact_items[index].coordinate())
        for key, (index, _item_value, _coordinate_value) in first_nodes.items()
    }

    contract_field_ordinal_by_node = {
        (item.observation_ordinal, cast("int", item.coordinate()["node_ordinal"])): cast(
            "int", item.coordinate()["field_ordinal"]
        )
        for item in exact_items
        if item.representation_kind == "live_lossless_nodes_v1" and item.record_kind == "field_cell"
    }
    for index, item in enumerate(exact_items):
        if item.representation_kind != "live_lossless_nodes_v1" or item.record_kind != "node":
            continue
        coordinate = item.coordinate()
        partition = live_partitions[item.partition_ordinal]
        node_ordinal = cast("int", coordinate["node_ordinal"])
        contract_field_ordinal = (
            contract_field_ordinal_by_node.get((item.observation_ordinal, node_ordinal))
            if coordinate["object_key"] is not None
            else None
        )
        row = item.to_row()
        row["source_record_sha256"] = value_projection._live_node_source_item_sha256(
            item=item,
            coordinate=coordinate,
            partition=partition,
            contract_field_ordinal=contract_field_ordinal,
        )
        exact_items[index] = ValueProjectionItemV1.from_row(
            _reseal_row(row, dto=ValueProjectionItemV1, digest_field="item_sha256")
        )

    first_nodes = {
        key: (index, exact_items[index], exact_items[index].coordinate())
        for key, (index, _item_value, _coordinate_value) in first_nodes.items()
    }

    global_occurrence_ordinals: dict[tuple[int, int], int] = {}
    matched_by_observation: dict[int, list[int]] = {}
    for _index, item, coordinate in first_nodes.values():
        matched_by_observation.setdefault(item.observation_ordinal, []).append(
            cast("int", coordinate["node_ordinal"])
        )
    for observation_ordinal, node_ordinals in matched_by_observation.items():
        for global_ordinal, node_ordinal in enumerate(sorted(node_ordinals)):
            global_occurrence_ordinals[(observation_ordinal, node_ordinal)] = global_ordinal

    partition_names = {
        (partition.observation_ordinal, cast("str", partition.result_name)): partition
        for partition in live_partitions.values()
    }
    local_counts: dict[int, int] = {}
    for item in exact_items:
        local_counts[item.partition_ordinal] = local_counts.get(item.partition_ordinal, 0) + 1

    for partition_ordinal, partition in live_partitions.items():
        roots = tuple(
            first_nodes[key] for key in sorted(first_nodes) if key[0] == partition_ordinal
        )
        parent_identities: set[tuple[str | None, str | None]] = set()
        for _index, _item_value, coordinate in roots:
            parent_ordinal = cast("int | None", coordinate["parent_node_ordinal"])
            parent_coordinate = (
                None
                if parent_ordinal is None
                else exact_items[
                    node_indexes[(partition.observation_ordinal, parent_ordinal)]
                ].coordinate()
            )
            parent_name = (
                None
                if parent_coordinate is None
                else cast("str | None", parent_coordinate["context_result_name"])
            )
            if parent_name == partition.result_name:
                parent_name = None
            parent_identities.add(
                (
                    parent_name,
                    None if parent_name is None else cast("str", coordinate["object_key"]),
                )
            )
        if len(parent_identities) > 1:
            raise AssertionError("live fixture occurrences disagree on their declaration parent")
        declaration_parent_name, declaration_parent_field = (
            next(iter(parent_identities)) if parent_identities else (None, None)
        )
        result_coordinate = {
            "result_name": partition.result_name,
            "result_duplicate_ordinal": partition.result_duplicate_ordinal,
            "provider_result_ordinal": partition.provider_result_ordinal,
            "expected_result_ordinal": partition.expected_result_ordinal,
            "canonical_result_ordinal": partition.canonical_result_ordinal,
            "result_path": partition.result_path,
            "container_kind": partition.container_kind,
            "result_presence": partition.result_presence,
        }
        declaration_ordinal = len(exact_items)
        declaration_local_ordinal = local_counts.get(partition_ordinal, 0)
        exact_items.append(
            _item(
                item_ordinal=declaration_ordinal,
                partition_ordinal=partition_ordinal,
                partition_item_ordinal=declaration_local_ordinal,
                observation_ordinal=partition.observation_ordinal,
                representation_kind="live_lossless_nodes_v1",
                unit_kind="result_occurrence",
                unit_ordinal=cast("int", partition.unit_ordinal),
                record_kind="result_declaration",
                coordinate=_coordinate(
                    **result_coordinate,
                    declaration_parent_result_name=declaration_parent_name,
                    declaration_parent_field_name=declaration_parent_field,
                ),
                value_state="absent",
                occurrence_ordinal=cast("int", partition.occurrence_ordinal),
            )
        )
        local_counts[partition_ordinal] = declaration_local_ordinal + 1

        parent_partition = (
            None
            if declaration_parent_name is None
            else partition_names[(partition.observation_ordinal, declaration_parent_name)]
        )
        for _index, root_item, root_coordinate in roots:
            occurrence_ordinal = cast("int", root_coordinate["context_result_occurrence"])
            row_ordinals = {
                cast("int", item.coordinate()["row_ordinal"])
                for item in exact_items
                if item.record_kind == "node"
                and item.partition_ordinal == partition_ordinal
                and item.coordinate()["context_result_occurrence"] == occurrence_ordinal
                and item.coordinate()["row_ordinal"] is not None
            }
            item_ordinal = len(exact_items)
            partition_item_ordinal = local_counts[partition_ordinal]
            exact_items.append(
                _item(
                    item_ordinal=item_ordinal,
                    partition_ordinal=partition_ordinal,
                    partition_item_ordinal=partition_item_ordinal,
                    observation_ordinal=partition.observation_ordinal,
                    representation_kind="live_lossless_nodes_v1",
                    unit_kind="result_occurrence",
                    unit_ordinal=cast("int", partition.unit_ordinal),
                    record_kind="result_occurrence",
                    coordinate=_coordinate(
                        **result_coordinate,
                        node_ordinal=root_coordinate["node_ordinal"],
                        json_path=root_coordinate["json_path"],
                        result_occurrence_global_ordinal=global_occurrence_ordinals[
                            (
                                partition.observation_ordinal,
                                cast("int", root_coordinate["node_ordinal"]),
                            )
                        ],
                        result_occurrence_ordinal=occurrence_ordinal,
                        result_occurrence_parent_result_name=declaration_parent_name,
                        result_occurrence_parent_result_ordinal=(
                            None
                            if parent_partition is None
                            else parent_partition.canonical_result_ordinal
                        ),
                        result_occurrence_presence_kind=root_item.presence_kind,
                        result_occurrence_row_count=len(row_ordinals),
                        decoder_value_sha256=root_coordinate["decoder_value_sha256"],
                    ),
                    value_state="absent",
                    occurrence_ordinal=cast("int", partition.occurrence_ordinal),
                )
            )
            local_counts[partition_ordinal] = partition_item_ordinal + 1
    ordered_items = sorted(
        enumerate(exact_items),
        key=lambda pair: (pair[1].observation_ordinal, pair[0]),
    )
    resealed_items: list[ValueProjectionItemV1] = []
    for global_ordinal, (_prior_ordinal, item) in enumerate(ordered_items):
        row = item.to_row()
        row["ownership_binding_ordinal"] = global_ordinal
        row["global_item_ordinal"] = global_ordinal
        resealed_items.append(
            ValueProjectionItemV1.from_row(
                _reseal_row(row, dto=ValueProjectionItemV1, digest_field="item_sha256")
            )
        )
    return tuple(resealed_items)


def _resealed_item_value_shape(
    item: ValueProjectionItemV1,
    *,
    value_state: str,
    value: object = None,
    structural_value_kind: str | None = None,
) -> ValueProjectionItemV1:
    row = item.to_row()
    row["value_state"] = value_state
    if value_state == "structural_container":
        row["presence_kind"] = "present"
        row["value_kind"] = structural_value_kind
        row["canonical_json"] = None
        row["canonical_json_sha256"] = None
    else:
        encoded = value_projection._canonical_json_bytes(
            value,
            maximum_bytes=value_projection.MAX_VALUE_PROJECTION_CANONICAL_VALUE_BYTES,
        )
        row["presence_kind"] = value_projection._presence_kind(value)
        row["value_kind"] = value_projection._value_kind(value)
        row["canonical_json"] = encoded.decode("utf-8")
        row["canonical_json_sha256"] = hashlib.sha256(encoded).hexdigest()
    return ValueProjectionItemV1.from_row(
        _reseal_row(row, dto=ValueProjectionItemV1, digest_field="item_sha256")
    )


def _resealed_partition_items(
    partition: ValueProjectionPartitionV1,
    items: tuple[ValueProjectionItemV1, ...],
) -> ValueProjectionPartitionV1:
    row = partition.to_row()
    row["item_root_sha256"] = value_projection._length_framed_root(
        kind=value_projection._PARTITION_ITEM_ROOT_KIND,
        raw_authority_bundle_sha256=partition.raw_authority_bundle_sha256,
        item_sha256s=tuple(item.item_sha256 for item in items),
        maximum=value_projection.MAX_VALUE_PROJECTION_ITEMS,
    )
    return ValueProjectionPartitionV1.from_row(
        _reseal_row(
            row,
            dto=ValueProjectionPartitionV1,
            digest_field="partition_sha256",
        )
    )


def _resealed_partition_values(
    partition: ValueProjectionPartitionV1,
    items: tuple[ValueProjectionItemV1, ...],
) -> ValueProjectionPartitionV1:
    row = partition.to_row()
    row["item_root_sha256"] = value_projection._length_framed_root(
        kind=value_projection._PARTITION_ITEM_ROOT_KIND,
        raw_authority_bundle_sha256=partition.raw_authority_bundle_sha256,
        item_sha256s=tuple(item.item_sha256 for item in items),
        maximum=value_projection.MAX_VALUE_PROJECTION_ITEMS,
    )
    row.update(value_projection._item_presence_counts(items))
    row["structural_value_count"] = sum(
        item.value_state == "structural_container" for item in items
    )
    row["canonical_value_byte_count"] = sum(
        len(cast("str", item.canonical_json).encode("utf-8"))
        for item in items
        if item.value_state == "canonical"
    )
    return ValueProjectionPartitionV1.from_row(
        _reseal_row(
            row,
            dto=ValueProjectionPartitionV1,
            digest_field="partition_sha256",
        )
    )


def _partition_items(
    items: tuple[ValueProjectionItemV1, ...], partition_ordinal: int
) -> tuple[ValueProjectionItemV1, ...]:
    return tuple(item for item in items if item.partition_ordinal == partition_ordinal)


def _resealed_projection_partitions(
    partitions: tuple[ValueProjectionPartitionV1, ...],
    items: tuple[ValueProjectionItemV1, ...],
    *partition_ordinals: int,
) -> tuple[ValueProjectionPartitionV1, ...]:
    selected = set(partition_ordinals)
    return tuple(
        _resealed_partition_items(
            partition,
            _partition_items(items, partition.partition_ordinal),
        )
        if partition.partition_ordinal in selected
        else partition
        for partition in partitions
    )


def test_complete_projection_covers_every_representation_and_zero_shape() -> None:
    receipt, partitions, items, _authority = _complete_projection()

    assert receipt.expected_unit_count == 6
    assert receipt.observation_count == 6
    assert receipt.partition_count == 10
    assert receipt.item_count == 9
    assert receipt.rectangular_result_unit_count == 2
    assert receipt.stats_lossless_unit_count == 1
    assert receipt.live_lossless_unit_count == 1
    assert receipt.response_lossless_unit_count == 1
    assert receipt.response_fixed_zero_unit_count == 1
    assert receipt.zero_result_partition_count == 1
    assert receipt.zero_response_residual_partition_count == 4
    assert receipt.positive_response_residual_partition_count == 1
    assert receipt.fixed_zero_partition_count == 1
    assert receipt.parser_input_observation_count == 4
    assert receipt.bodyless_observation_count == 2
    assert receipt.absent_count == 2
    assert receipt.missing_count == 2
    assert receipt.mixed_absent_count == 0
    assert receipt.empty_object_count == 1
    assert receipt.empty_array_count == 1
    assert receipt.structural_value_count == 0
    assert receipt.canonical_value_byte_count == sum(
        len(cast("str", item.canonical_json).encode("utf-8"))
        for item in items
        if item.value_state == "canonical"
    )
    assert partitions[8].item_count == 0
    assert partitions[1].unit_sha256 is None


def test_all_dtos_round_trip_exact_rows_and_canonical_bytes() -> None:
    receipt, partitions, items, _authority = _complete_projection()
    body = _body_receipt(receipt)

    for value, dto in (
        (items[0], ValueProjectionItemV1),
        (partitions[0], ValueProjectionPartitionV1),
        (receipt, ValueProjectionReceiptV1),
        (body, BodyValueProjectionReceiptV1),
    ):
        assert cast("Any", dto).from_row(value.to_row()) == value
        assert cast("Any", dto).from_canonical_bytes(value.canonical_bytes()) == value


def test_strict_row_order_and_schema_version_reject_replay() -> None:
    _receipt_value, _partitions, items, _authority = _complete_projection()
    row = items[0].to_row()
    reversed_row = dict(reversed(tuple(row.items())))
    with pytest.raises(ValueProjectionError, match="exact ordered row shape"):
        ValueProjectionItemV1.from_row(reversed_row)
    row["schema_version"] = True
    with pytest.raises(ValueProjectionError, match="schema version"):
        ValueProjectionItemV1.from_row(row)


def test_canonical_byte_replay_rejects_duplicate_keys_and_whitespace() -> None:
    _receipt_value, _partitions, items, _authority = _complete_projection()
    canonical = items[0].canonical_bytes()
    duplicate = b'{"schema_version":1,' + canonical[1:]
    with pytest.raises(ValueProjectionError, match="duplicate object keys"):
        ValueProjectionItemV1.from_canonical_bytes(duplicate)
    pretty = json.dumps(items[0].to_row(), indent=2).encode("utf-8")
    with pytest.raises(ValueProjectionError, match="canonical byte form"):
        ValueProjectionItemV1.from_canonical_bytes(pretty)


@pytest.mark.parametrize("value", [True, 1.0, "0"])
def test_exact_integer_fields_reject_bool_float_and_text(value: object) -> None:
    with pytest.raises(ValueProjectionError, match="exact integer"):
        _item(
            item_ordinal=cast("Any", value),
            partition_ordinal=0,
            partition_item_ordinal=0,
            observation_ordinal=0,
            representation_kind="rectangular_result_cells_v1",
            unit_kind="result_occurrence",
            unit_ordinal=0,
            record_kind="cell",
            coordinate=_coordinate(),
            value=1,
        )


def test_foreign_subclasses_are_rejected() -> None:
    class ForeignInt(int):
        pass

    class ForeignDict(dict[str, object]):
        pass

    with pytest.raises(ValueProjectionError, match="exact integer"):
        _item(
            item_ordinal=ForeignInt(0),
            partition_ordinal=0,
            partition_item_ordinal=0,
            observation_ordinal=0,
            representation_kind="rectangular_result_cells_v1",
            unit_kind="result_occurrence",
            unit_ordinal=0,
            record_kind="cell",
            coordinate=_coordinate(),
            value=1,
        )
    with pytest.raises(ValueProjectionError, match="coordinate must be one exact object"):
        _item(
            item_ordinal=0,
            partition_ordinal=0,
            partition_item_ordinal=0,
            observation_ordinal=0,
            representation_kind="rectangular_result_cells_v1",
            unit_kind="result_occurrence",
            unit_ordinal=0,
            record_kind="cell",
            coordinate=ForeignDict(_coordinate()),
            value=1,
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_values_are_rejected(value: float) -> None:
    with pytest.raises(ValueProjectionError, match="nonfinite"):
        _item(
            item_ordinal=0,
            partition_ordinal=0,
            partition_item_ordinal=0,
            observation_ordinal=0,
            representation_kind="rectangular_result_cells_v1",
            unit_kind="result_occurrence",
            unit_ordinal=0,
            record_kind="cell",
            coordinate=_coordinate(),
            value=value,
        )


def test_foreign_json_value_type_and_invalid_unicode_are_rejected() -> None:
    base = {
        "item_ordinal": 0,
        "partition_ordinal": 0,
        "partition_item_ordinal": 0,
        "observation_ordinal": 0,
        "representation_kind": "rectangular_result_cells_v1",
        "unit_kind": "result_occurrence",
        "unit_ordinal": 0,
        "record_kind": "cell",
        "coordinate": _coordinate(),
    }
    with pytest.raises(ValueProjectionError, match="foreign exact type"):
        _item(**cast("Any", base), value=(1, 2))
    with pytest.raises(ValueProjectionError, match="invalid Unicode"):
        _item(**cast("Any", base), value="\ud800")
    bad_coordinate = _coordinate(result_name="\ud800")
    with pytest.raises(ValueProjectionError, match="invalid Unicode"):
        _item(**cast("Any", {**base, "coordinate": bad_coordinate}), value=1)


def test_coordinate_schema_and_bounds_are_closed() -> None:
    missing = _coordinate()
    missing.pop("result_path")
    with pytest.raises(ValueProjectionError, match="fixed V1 key schema"):
        value_projection._validate_coordinate(missing)
    extra = _coordinate(unknown="x")
    with pytest.raises(ValueProjectionError, match="fixed V1 key schema"):
        value_projection._validate_coordinate(extra)
    with pytest.raises(ValueProjectionError, match="UTF-8 byte bound"):
        value_projection._validate_coordinate(
            _coordinate(result_path="x" * (value_projection.MAX_VALUE_PROJECTION_PATH_BYTES + 1))
        )


def test_canonical_value_depth_is_bounded_before_encoding() -> None:
    value: object = 0
    for _ in range(value_projection.MAX_VALUE_PROJECTION_JSON_DEPTH + 1):
        value = [value]
    with pytest.raises(ValueProjectionError, match="depth bound"):
        _item(
            item_ordinal=0,
            partition_ordinal=0,
            partition_item_ordinal=0,
            observation_ordinal=0,
            representation_kind="rectangular_result_cells_v1",
            unit_kind="result_occurrence",
            unit_ordinal=0,
            record_kind="cell",
            coordinate=_coordinate(),
            value=value,
        )


def test_deep_canonical_json_and_unbounded_number_tokens_never_reach_json_loads() -> None:
    deep = ("[" * 10_000) + "0" + ("]" * 10_000)
    with pytest.raises(ValueProjectionError, match="structural bound"):
        value_projection._decode_canonical_json(deep, maximum_bytes=len(deep.encode("utf-8")))
    with pytest.raises(ValueProjectionError, match="over-bound integer"):
        value_projection._decode_canonical_json(
            str(1 << 63),
            maximum_bytes=128,
        )
    with pytest.raises(ValueProjectionError, match="over-bound integer token"):
        value_projection._decode_canonical_json("1" * 129, maximum_bytes=256)


def test_projection_builder_copies_mutable_coordinate_and_value_graphs() -> None:
    coordinate = _coordinate(result_name="before")
    value = {"nested": [1]}
    item = _item(
        item_ordinal=0,
        partition_ordinal=0,
        partition_item_ordinal=0,
        observation_ordinal=0,
        representation_kind="rectangular_result_cells_v1",
        unit_kind="result_occurrence",
        unit_ordinal=0,
        record_kind="cell",
        coordinate=coordinate,
        value=value,
    )
    coordinate["result_name"] = "after"
    value["nested"].append(2)

    assert item.coordinate()["result_name"] == "before"
    assert item.value() == {"nested": [1]}


def test_canonical_value_byte_bound_is_enforced_before_identity_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(value_projection, "MAX_VALUE_PROJECTION_CANONICAL_VALUE_BYTES", 8)
    with pytest.raises(ValueProjectionError, match="byte bound"):
        _item(
            item_ordinal=0,
            partition_ordinal=0,
            partition_item_ordinal=0,
            observation_ordinal=0,
            representation_kind="rectangular_result_cells_v1",
            unit_kind="result_occurrence",
            unit_ordinal=0,
            record_kind="cell",
            coordinate=_coordinate(),
            value="123456789",
        )


@pytest.mark.parametrize(
    ("value_state", "missing_presence", "expected_presence", "expected_kind"),
    [
        ("missing", "missing", "missing", "missing"),
        ("missing", "mixed_absent", "mixed_absent", "missing"),
        (
            "missing",
            "not_observed_parent_empty",
            "not_observed_parent_empty",
            "missing",
        ),
        ("absent", None, None, None),
    ],
)
def test_missing_and_absent_value_algebra(
    value_state: str,
    missing_presence: str | None,
    expected_presence: str | None,
    expected_kind: str | None,
) -> None:
    item = _item(
        item_ordinal=0,
        partition_ordinal=0,
        partition_item_ordinal=0,
        observation_ordinal=0,
        representation_kind="stats_lossless_records_v1",
        unit_kind="result_occurrence",
        unit_ordinal=0,
        record_kind="result_set",
        coordinate=_coordinate(),
        value_state=value_state,
        missing_presence_kind=missing_presence,
    )
    assert item.presence_kind == expected_presence
    assert item.value_kind == expected_kind
    assert item.canonical_json is None


def test_value_kind_presence_projection_preserves_exact_builtin_types() -> None:
    cases = (
        (None, "null", "null"),
        (True, "present", "boolean"),
        (1, "present", "integer"),
        (1.5, "present", "number"),
        ("x", "present", "string"),
        ([], "empty_array", "array"),
        ({}, "empty_object", "object"),
    )
    for ordinal, (value, presence, kind) in enumerate(cases):
        item = _item(
            item_ordinal=ordinal,
            partition_ordinal=0,
            partition_item_ordinal=ordinal,
            observation_ordinal=0,
            representation_kind="response_lossless_records_v1",
            unit_kind="response_residual",
            unit_ordinal=0,
            record_kind="json_node",
            coordinate=_coordinate(node_ordinal=ordinal, json_path=f"$[{ordinal}]"),
            value=value,
            source_input_kind="declared_bodyless_packet",
        )
        assert item.presence_kind == presence
        assert item.value_kind == kind
        assert item.value() == value


def test_structural_container_item_has_one_exact_noncanonical_shape() -> None:
    item = _item(
        item_ordinal=0,
        partition_ordinal=0,
        partition_item_ordinal=0,
        observation_ordinal=0,
        representation_kind="response_lossless_records_v1",
        unit_kind="response_residual",
        unit_ordinal=0,
        record_kind="json_node",
        coordinate=_coordinate(node_ordinal=0, json_path="$", depth=0),
        value_state="structural_container",
        structural_value_kind="object",
    )

    assert item.presence_kind == "present"
    assert item.value_kind == "object"
    assert item.canonical_json is None
    assert item.canonical_json_sha256 is None
    with pytest.raises(ValueProjectionError, match="noncanonical"):
        item.value()

    for changes in (
        {"presence_kind": "empty_object"},
        {"value_kind": "string"},
        {
            "canonical_json": "{}",
            "canonical_json_sha256": _canonical_value_sha({}),
        },
        {"record_kind": "response"},
    ):
        row = item.to_row()
        row.update(changes)
        with pytest.raises(ValueProjectionError, match="structural projection container"):
            ValueProjectionItemV1.from_row(
                _reseal_row(
                    row,
                    dto=ValueProjectionItemV1,
                    digest_field="item_sha256",
                )
            )


def test_structural_nodes_reconstruct_nested_object_and_array_once() -> None:
    root = _item(
        item_ordinal=0,
        partition_ordinal=0,
        partition_item_ordinal=0,
        observation_ordinal=0,
        representation_kind="response_lossless_records_v1",
        unit_kind="response_residual",
        unit_ordinal=0,
        record_kind="json_node",
        coordinate=_coordinate(node_ordinal=0, json_path="$", depth=0),
        value_state="structural_container",
        structural_value_kind="object",
    )
    array = _item(
        item_ordinal=1,
        partition_ordinal=0,
        partition_item_ordinal=1,
        observation_ordinal=0,
        representation_kind="response_lossless_records_v1",
        unit_kind="response_residual",
        unit_ordinal=0,
        record_kind="json_node",
        coordinate=_coordinate(
            node_ordinal=1,
            parent_node_ordinal=0,
            json_path='$["values"]',
            parent_json_path="$",
            depth=1,
            object_key="values",
            object_key_ordinal=0,
        ),
        value_state="structural_container",
        structural_value_kind="array",
    )
    leaf = _item(
        item_ordinal=2,
        partition_ordinal=0,
        partition_item_ordinal=2,
        observation_ordinal=0,
        representation_kind="response_lossless_records_v1",
        unit_kind="response_residual",
        unit_ordinal=0,
        record_kind="json_node",
        coordinate=_coordinate(
            node_ordinal=2,
            parent_node_ordinal=1,
            json_path='$["values"][0]',
            parent_json_path='$["values"]',
            depth=2,
            array_ordinal=0,
        ),
        value=7,
    )
    partition = _positive_residual_partition(
        partition_ordinal=0,
        observation_ordinal=0,
        unit_ordinal=0,
        items=(root, array, leaf),
        source_input_kind="parser_input_body",
    )
    receipt, rebuilt_partitions, _items, _authority = _seal_projection(
        partitions=(partition,),
        items=(root, array, leaf),
    )

    assert rebuilt_partitions[0].structural_value_count == 2
    assert rebuilt_partitions[0].canonical_value_byte_count == 1
    assert receipt.structural_value_count == 2
    assert receipt.canonical_value_byte_count == 1


def test_structural_state_is_exactly_equivalent_to_having_children() -> None:
    empty = _item(
        item_ordinal=0,
        partition_ordinal=0,
        partition_item_ordinal=0,
        observation_ordinal=0,
        representation_kind="response_lossless_records_v1",
        unit_kind="response_residual",
        unit_ordinal=0,
        record_kind="json_node",
        coordinate=_coordinate(node_ordinal=0, json_path="$", depth=0),
        value={},
    )
    _positive_residual_partition(
        partition_ordinal=0,
        observation_ordinal=0,
        unit_ordinal=0,
        items=(empty,),
        source_input_kind="parser_input_body",
    )

    structural_without_children = _item(
        item_ordinal=0,
        partition_ordinal=0,
        partition_item_ordinal=0,
        observation_ordinal=0,
        representation_kind="response_lossless_records_v1",
        unit_kind="response_residual",
        unit_ordinal=0,
        record_kind="json_node",
        coordinate=_coordinate(node_ordinal=0, json_path="$", depth=0),
        value_state="structural_container",
        structural_value_kind="object",
    )
    with pytest.raises(ValueProjectionError, match="exact children"):
        _positive_residual_partition(
            partition_ordinal=0,
            observation_ordinal=0,
            unit_ordinal=0,
            items=(structural_without_children,),
            source_input_kind="parser_input_body",
        )

    canonical_nonempty = _item(
        item_ordinal=0,
        partition_ordinal=0,
        partition_item_ordinal=0,
        observation_ordinal=0,
        representation_kind="response_lossless_records_v1",
        unit_kind="response_residual",
        unit_ordinal=0,
        record_kind="json_node",
        coordinate=_coordinate(node_ordinal=0, json_path="$", depth=0),
        value={"a": 1},
    )
    with pytest.raises(ValueProjectionError, match="not structurally materialized"):
        _positive_residual_partition(
            partition_ordinal=0,
            observation_ordinal=0,
            unit_ordinal=0,
            items=(canonical_nonempty,),
            source_input_kind="parser_input_body",
        )


@pytest.mark.parametrize(
    ("unit_kind", "representation_kind", "record_kind"),
    [
        ("result_occurrence", "response_lossless_records_v1", "json_node"),
        ("response_residual", "rectangular_result_cells_v1", "cell"),
        ("response_fixed_zero", "response_fixed_zero_v1", "response"),
        ("result_occurrence", "live_lossless_nodes_v1", "cell"),
    ],
)
def test_unit_representation_and_record_domains_are_exact(
    unit_kind: str,
    representation_kind: str,
    record_kind: str,
) -> None:
    with pytest.raises(ValueProjectionError):
        _item(
            item_ordinal=0,
            partition_ordinal=0,
            partition_item_ordinal=0,
            observation_ordinal=0,
            representation_kind=representation_kind,
            unit_kind=unit_kind,
            unit_ordinal=0,
            record_kind=record_kind,
            coordinate=_coordinate(),
            value=1,
        )


def test_partition_rejects_duplicate_source_and_binding_identities() -> None:
    first = _item(
        item_ordinal=0,
        partition_ordinal=0,
        partition_item_ordinal=0,
        observation_ordinal=0,
        representation_kind="stats_lossless_records_v1",
        unit_kind="result_occurrence",
        unit_ordinal=0,
        record_kind="result_set",
        coordinate=_coordinate(),
        value_state="absent",
    )
    row = first.to_row()
    row["item_sha256"] = _sha("different-item")
    row["ownership_binding_sha256"] = _sha("different-binding")
    row["ownership_binding_ordinal"] = 1
    row["global_item_ordinal"] = 1
    row["partition_item_ordinal"] = 1
    second = ValueProjectionItemV1.from_row(
        _reseal_row(row, dto=ValueProjectionItemV1, digest_field="item_sha256")
    )
    with pytest.raises(ValueProjectionError, match="dual-projects one source record"):
        _result_partition(
            partition_ordinal=0,
            observation_ordinal=0,
            observation_partition_ordinal=0,
            unit_ordinal=0,
            representation_kind="stats_lossless_records_v1",
            items=(first, second),
            result_name="R",
            ordered_headers=(),
        )


def test_header_row_and_value_duplicate_ordinals_are_canonical() -> None:
    first = _item(
        item_ordinal=0,
        partition_ordinal=0,
        partition_item_ordinal=0,
        observation_ordinal=0,
        representation_kind="rectangular_result_cells_v1",
        unit_kind="result_occurrence",
        unit_ordinal=0,
        record_kind="cell",
        coordinate=_coordinate(
            result_name="R",
            result_duplicate_ordinal=0,
            provider_result_ordinal=0,
            expected_result_ordinal=0,
            canonical_result_ordinal=0,
            result_path="$.results[0]",
            container_kind="nba_api_result_set",
            result_presence="present",
            header_name="DUP",
            header_ordinal=0,
            header_duplicate_ordinal=0,
            row_ordinal=0,
            row_duplicate_ordinal=0,
            row_value_sha256=_sha("same-row"),
            cell_ordinal=0,
            value_duplicate_ordinal=0,
        ),
        value=1,
    )
    second = _item(
        item_ordinal=1,
        partition_ordinal=0,
        partition_item_ordinal=1,
        observation_ordinal=0,
        representation_kind="rectangular_result_cells_v1",
        unit_kind="result_occurrence",
        unit_ordinal=0,
        record_kind="cell",
        coordinate=_coordinate(
            result_name="R",
            result_duplicate_ordinal=0,
            provider_result_ordinal=0,
            expected_result_ordinal=0,
            canonical_result_ordinal=0,
            result_path="$.results[0]",
            container_kind="nba_api_result_set",
            result_presence="present",
            header_name="DUP",
            header_ordinal=1,
            header_duplicate_ordinal=1,
            row_ordinal=0,
            row_duplicate_ordinal=0,
            row_value_sha256=_sha("same-row"),
            cell_ordinal=1,
            value_duplicate_ordinal=0,
        ),
        value=1,
    )
    _result_partition(
        partition_ordinal=0,
        observation_ordinal=0,
        observation_partition_ordinal=0,
        unit_ordinal=0,
        representation_kind="rectangular_result_cells_v1",
        items=(first, second),
        result_name="R",
        ordered_headers=("DUP", "DUP"),
        header_count=2,
        row_count=1,
        cell_count=2,
    )
    forged = _item(
        item_ordinal=1,
        partition_ordinal=0,
        partition_item_ordinal=1,
        observation_ordinal=0,
        representation_kind="rectangular_result_cells_v1",
        unit_kind="result_occurrence",
        unit_ordinal=0,
        record_kind="cell",
        coordinate=_coordinate(
            result_name="R",
            result_duplicate_ordinal=0,
            provider_result_ordinal=0,
            expected_result_ordinal=0,
            canonical_result_ordinal=0,
            result_path="$.results[0]",
            container_kind="nba_api_result_set",
            result_presence="present",
            header_name="DUP",
            header_ordinal=1,
            header_duplicate_ordinal=0,
            row_ordinal=0,
            row_duplicate_ordinal=0,
            row_value_sha256=_sha("same-row"),
            cell_ordinal=1,
            value_duplicate_ordinal=0,
        ),
        value=1,
    )
    with pytest.raises(ValueProjectionError, match="ordered headers"):
        _result_partition(
            partition_ordinal=0,
            observation_ordinal=0,
            observation_partition_ordinal=0,
            unit_ordinal=0,
            representation_kind="rectangular_result_cells_v1",
            items=(first, forged),
            result_name="R",
            ordered_headers=("DUP", "DUP"),
            header_count=2,
            row_count=1,
            cell_count=2,
        )


def test_stats_header_slots_preserve_non_string_duplicates_and_ragged_cells() -> None:
    result_coordinates = {
        "result_name": "R",
        "result_duplicate_ordinal": 0,
        "provider_result_ordinal": 0,
        "expected_result_ordinal": 0,
        "canonical_result_ordinal": 0,
        "result_path": "$.results[0]",
        "container_kind": "nba_api_result_set",
        "result_presence": "present",
    }
    slots = (
        {
            "header_reference_kind": "named",
            "header_name": "A",
            "header_value_sha256": _canonical_value_sha("A"),
        },
        {
            "header_reference_kind": "non_string",
            "header_name": None,
            "header_value_sha256": _canonical_value_sha(7),
        },
        {
            "header_reference_kind": "named",
            "header_name": "A",
            "header_value_sha256": _canonical_value_sha("A"),
        },
        {
            "header_reference_kind": "out_of_range",
            "header_name": None,
            "header_value_sha256": None,
        },
    )
    header_values = ("A", 7, "A")
    header_items = tuple(
        _item(
            item_ordinal=ordinal,
            partition_ordinal=0,
            partition_item_ordinal=ordinal,
            observation_ordinal=0,
            representation_kind="stats_lossless_records_v1",
            unit_kind="result_occurrence",
            unit_ordinal=0,
            record_kind="header",
            coordinate=_coordinate(
                **result_coordinates,
                header_reference_kind=slots[ordinal]["header_reference_kind"],
                header_name=slots[ordinal]["header_name"],
                header_ordinal=ordinal,
                header_value_sha256=slots[ordinal]["header_value_sha256"],
                header_duplicate_ordinal=(0, 0, 1)[ordinal],
            ),
            value=value,
        )
        for ordinal, value in enumerate(header_values)
    )
    ragged_cell = _item(
        item_ordinal=3,
        partition_ordinal=0,
        partition_item_ordinal=3,
        observation_ordinal=0,
        representation_kind="stats_lossless_records_v1",
        unit_kind="result_occurrence",
        unit_ordinal=0,
        record_kind="cell",
        coordinate=_coordinate(
            **result_coordinates,
            header_reference_kind="out_of_range",
            header_ordinal=3,
            row_ordinal=0,
            row_duplicate_ordinal=0,
            row_value_sha256=_sha("ragged-row"),
            cell_ordinal=0,
            value_duplicate_ordinal=0,
        ),
        value="ragged",
    )
    items = (*header_items, ragged_cell)
    partition = _result_partition(
        partition_ordinal=0,
        observation_ordinal=0,
        observation_partition_ordinal=0,
        unit_ordinal=0,
        representation_kind="stats_lossless_records_v1",
        items=items,
        result_name="R",
        ordered_headers=(),
        ordered_header_slots=slots,
        header_record_count=3,
        header_slot_count=4,
        row_count=1,
        cell_count=1,
    )

    assert partition.header_record_count == 3
    assert partition.header_slot_count == 4
    assert partition.header_count == 0
    assert json.loads(cast("str", partition.ordered_header_slots_json)) == list(slots)
    assert partition.ordered_header_slots_sha256 == _canonical_value_sha(list(slots))
    assert header_items[1].coordinate()["header_reference_kind"] == "non_string"
    assert ragged_cell.coordinate()["header_reference_kind"] == "out_of_range"

    forged_value = _resealed_item_value_shape(
        header_items[0],
        value_state="canonical",
        value="forged",
    )
    with pytest.raises(ValueProjectionError, match="header record differs"):
        _result_partition(
            partition_ordinal=0,
            observation_ordinal=0,
            observation_partition_ordinal=0,
            unit_ordinal=0,
            representation_kind="stats_lossless_records_v1",
            items=(forged_value, *items[1:]),
            result_name="R",
            ordered_headers=(),
            ordered_header_slots=slots,
            header_record_count=3,
            header_slot_count=4,
            row_count=1,
            cell_count=1,
        )

    forged_duplicate = _resealed_item_coordinate(
        header_items[2],
        header_duplicate_ordinal=0,
    )
    with pytest.raises(ValueProjectionError, match="exact slot"):
        _result_partition(
            partition_ordinal=0,
            observation_ordinal=0,
            observation_partition_ordinal=0,
            unit_ordinal=0,
            representation_kind="stats_lossless_records_v1",
            items=(*items[:2], forged_duplicate, ragged_cell),
            result_name="R",
            ordered_headers=(),
            ordered_header_slots=slots,
            header_record_count=3,
            header_slot_count=4,
            row_count=1,
            cell_count=1,
        )

    forged_ragged = _resealed_item_coordinate(
        ragged_cell,
        header_reference_kind="named",
        header_name="fabricated",
        header_value_sha256=_canonical_value_sha("fabricated"),
        header_duplicate_ordinal=0,
    )
    with pytest.raises(ValueProjectionError, match="exact slot"):
        _result_partition(
            partition_ordinal=0,
            observation_ordinal=0,
            observation_partition_ordinal=0,
            unit_ordinal=0,
            representation_kind="stats_lossless_records_v1",
            items=(*header_items, forged_ragged),
            result_name="R",
            ordered_headers=(),
            ordered_header_slots=slots,
            header_record_count=3,
            header_slot_count=4,
            row_count=1,
            cell_count=1,
        )

    fabricated_header = _resealed_item_coordinate(
        header_items[0],
        header_reference_kind="out_of_range",
        header_name=None,
        header_ordinal=3,
        header_value_sha256=None,
        header_duplicate_ordinal=None,
    )
    with pytest.raises(ValueProjectionError, match="out-of-range header record"):
        _result_partition(
            partition_ordinal=0,
            observation_ordinal=0,
            observation_partition_ordinal=0,
            unit_ordinal=0,
            representation_kind="stats_lossless_records_v1",
            items=(fabricated_header, *items[1:]),
            result_name="R",
            ordered_headers=(),
            ordered_header_slots=slots,
            header_record_count=3,
            header_slot_count=4,
            row_count=1,
            cell_count=1,
        )


def test_stats_header_slot_shapes_and_named_digest_are_exact() -> None:
    named = {
        "header_reference_kind": "named",
        "header_name": "A",
        "header_value_sha256": _canonical_value_sha("A"),
    }
    for slot, message in (
        (
            {**named, "header_value_sha256": _canonical_value_sha("B")},
            "named header digest",
        ),
        (
            {
                "header_reference_kind": "non_string",
                "header_name": "fabricated",
                "header_value_sha256": _canonical_value_sha(1),
            },
            "materialized header slot",
        ),
        (
            {
                "header_reference_kind": "out_of_range",
                "header_name": None,
                "header_value_sha256": None,
            },
            "lowercase full SHA-256",
        ),
    ):
        with pytest.raises(ValueProjectionError, match=message):
            _result_partition(
                partition_ordinal=0,
                observation_ordinal=0,
                observation_partition_ordinal=0,
                unit_ordinal=0,
                representation_kind="stats_lossless_records_v1",
                items=(),
                result_name="R",
                ordered_headers=(),
                ordered_header_slots=(slot,),
                header_record_count=1,
                header_slot_count=1,
            )


def test_repeated_cell_value_duplicate_ordinal_rejects_gap() -> None:
    items = tuple(
        _item(
            item_ordinal=ordinal,
            partition_ordinal=0,
            partition_item_ordinal=ordinal,
            observation_ordinal=0,
            representation_kind="rectangular_result_cells_v1",
            unit_kind="result_occurrence",
            unit_ordinal=0,
            record_kind="cell",
            coordinate=_coordinate(
                result_name="R",
                result_duplicate_ordinal=0,
                provider_result_ordinal=0,
                expected_result_ordinal=0,
                canonical_result_ordinal=0,
                result_path="$.results[0]",
                container_kind="nba_api_result_set",
                result_presence="present",
                header_name="A",
                header_ordinal=0,
                header_duplicate_ordinal=0,
                row_ordinal=ordinal,
                row_duplicate_ordinal=ordinal,
                row_value_sha256=_sha("same-row"),
                cell_ordinal=ordinal,
                value_duplicate_ordinal=ordinal + (1 if ordinal else 0),
            ),
            value=7,
        )
        for ordinal in range(2)
    )
    with pytest.raises(ValueProjectionError, match="value duplicate ordinal"):
        _result_partition(
            partition_ordinal=0,
            observation_ordinal=0,
            observation_partition_ordinal=0,
            unit_ordinal=0,
            representation_kind="rectangular_result_cells_v1",
            items=items,
            result_name="R",
            ordered_headers=("A",),
            header_count=1,
            row_count=2,
            cell_count=2,
        )


def test_zero_positive_and_fixed_partition_algebra_rejects_reseal() -> None:
    receipt, partitions, _items, _authority = _complete_projection()
    del receipt
    zero_row = partitions[1].to_row()
    zero_row["unit_sha256"] = _sha("unit-forge")
    zero_row["unit_ordinal"] = 0
    zero_row["assignment_sha256"] = _sha("assignment-forge")
    zero_row["representation_kind"] = "response_lossless_records_v1"
    zero_row["representation_output_sha256"] = _sha("output-forge")
    with pytest.raises(ValueProjectionError, match="zero response residual"):
        ValueProjectionPartitionV1.from_row(
            _reseal_row(
                zero_row,
                dto=ValueProjectionPartitionV1,
                digest_field="partition_sha256",
            )
        )
    fixed_row = partitions[7].to_row()
    fixed_row["representation_kind"] = "response_lossless_records_v1"
    with pytest.raises(ValueProjectionError, match="fixed-zero"):
        ValueProjectionPartitionV1.from_row(
            _reseal_row(
                fixed_row,
                dto=ValueProjectionPartitionV1,
                digest_field="partition_sha256",
            )
        )
    positive_row = partitions[6].to_row()
    positive_row["unit_sha256"] = None
    positive_row["unit_ordinal"] = None
    positive_row["assignment_sha256"] = None
    positive_row["representation_kind"] = None
    with pytest.raises(ValueProjectionError, match="positive response residual"):
        ValueProjectionPartitionV1.from_row(
            _reseal_row(
                positive_row,
                dto=ValueProjectionPartitionV1,
                digest_field="partition_sha256",
            )
        )


def test_aggregate_rejects_partition_item_root_reseal() -> None:
    _receipt_value, partitions, items, authority = _complete_projection()
    row = partitions[0].to_row()
    row["item_root_sha256"] = _sha("forged-root")
    forged = ValueProjectionPartitionV1.from_row(
        _reseal_row(row, dto=ValueProjectionPartitionV1, digest_field="partition_sha256")
    )
    with pytest.raises(ValueProjectionError, match="exact item reconstruction"):
        _receipt(partitions=(forged, *partitions[1:]), items=items, authority=authority)


def test_aggregate_rejects_item_coordinate_reseal_against_partition() -> None:
    _receipt_value, partitions, items, authority = _complete_projection()
    row = items[0].to_row()
    coordinate = items[0].coordinate()
    coordinate["result_path"] = "$.forged"
    encoded = value_projection._canonical_json_bytes(
        coordinate,
        maximum_bytes=value_projection.MAX_VALUE_PROJECTION_PATH_BYTES * 8,
    )
    row["coordinate_json"] = encoded.decode("utf-8")
    row["coordinate_sha256"] = hashlib.sha256(encoded).hexdigest()
    forged = ValueProjectionItemV1.from_row(
        _reseal_row(row, dto=ValueProjectionItemV1, digest_field="item_sha256")
    )
    with pytest.raises(ValueProjectionError, match="result coordinate"):
        _receipt(partitions=partitions, items=(forged, *items[1:]), authority=authority)


def test_aggregate_rejects_reorder_or_orphan_unit() -> None:
    _receipt_value, partitions, items, authority = _complete_projection()
    with pytest.raises(ValueProjectionError, match="exact ownership partition"):
        _receipt(
            partitions=(partitions[1], partitions[0], *partitions[2:]),
            items=items,
            authority=authority,
        )
    with pytest.raises(ValueProjectionError, match="denominators"):
        _receipt(partitions=partitions[:-2], items=items, authority=authority)


def test_aggregate_rejects_assignment_inventory_drift_even_with_resealed_root() -> None:
    _receipt_value, partitions, items, authority = _complete_projection()
    kwargs = _authority_kwargs(authority)
    assignments = cast("tuple[dict[str, object], ...]", kwargs["representation_assignment_rows"])
    kwargs["representation_assignment_rows"] = (
        assignments[1],
        assignments[0],
        *assignments[2:],
    )
    with pytest.raises(ValueProjectionError, match="foreign to its exact unit"):
        ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=_sha("bundle"),
            partitions=partitions,
            items=items,
            **cast("Any", kwargs),
        )


def test_global_binding_order_allows_interleaved_partition_members() -> None:
    first_a = _item(
        item_ordinal=0,
        partition_ordinal=0,
        partition_item_ordinal=0,
        observation_ordinal=0,
        representation_kind="stats_lossless_records_v1",
        unit_kind="result_occurrence",
        unit_ordinal=0,
        record_kind="result_set",
        coordinate=_coordinate(
            result_name="A",
            result_duplicate_ordinal=0,
            provider_result_ordinal=0,
            expected_result_ordinal=0,
            canonical_result_ordinal=0,
            result_path="$.results[0]",
            container_kind="nba_api_result_set",
            result_presence="present",
        ),
        value_state="absent",
    )
    first_b = _item(
        item_ordinal=1,
        partition_ordinal=1,
        partition_item_ordinal=0,
        observation_ordinal=0,
        representation_kind="stats_lossless_records_v1",
        unit_kind="result_occurrence",
        unit_ordinal=1,
        record_kind="result_set",
        coordinate=_coordinate(
            result_name="B",
            result_duplicate_ordinal=0,
            provider_result_ordinal=1,
            expected_result_ordinal=1,
            canonical_result_ordinal=1,
            result_path="$.results[1]",
            container_kind="nba_api_result_set",
            result_presence="present",
        ),
        value_state="absent",
        occurrence_ordinal=1,
    )
    second_a = _item(
        item_ordinal=2,
        partition_ordinal=0,
        partition_item_ordinal=1,
        observation_ordinal=0,
        representation_kind="stats_lossless_records_v1",
        unit_kind="result_occurrence",
        unit_ordinal=0,
        record_kind="raw_headers",
        coordinate=_coordinate(
            result_name="A",
            result_duplicate_ordinal=0,
            provider_result_ordinal=0,
            expected_result_ordinal=0,
            canonical_result_ordinal=0,
            result_path="$.results[0]",
            container_kind="nba_api_result_set",
            result_presence="present",
        ),
        value_state="absent",
    )
    second_b = _item(
        item_ordinal=3,
        partition_ordinal=1,
        partition_item_ordinal=1,
        observation_ordinal=0,
        representation_kind="stats_lossless_records_v1",
        unit_kind="result_occurrence",
        unit_ordinal=1,
        record_kind="raw_headers",
        coordinate=_coordinate(
            result_name="B",
            result_duplicate_ordinal=0,
            provider_result_ordinal=1,
            expected_result_ordinal=1,
            canonical_result_ordinal=1,
            result_path="$.results[1]",
            container_kind="nba_api_result_set",
            result_presence="present",
        ),
        value_state="absent",
        occurrence_ordinal=1,
    )
    partition_a = _result_partition(
        partition_ordinal=0,
        observation_ordinal=0,
        observation_partition_ordinal=0,
        unit_ordinal=0,
        representation_kind="stats_lossless_records_v1",
        items=(first_a, second_a),
        result_name="A",
        ordered_headers=(),
    )
    partition_b = _result_partition(
        partition_ordinal=1,
        observation_ordinal=0,
        observation_partition_ordinal=1,
        unit_ordinal=1,
        representation_kind="stats_lossless_records_v1",
        items=(first_b, second_b),
        result_name="B",
        ordered_headers=(),
        occurrence_ordinal=1,
        provider_result_ordinal=1,
        expected_result_ordinal=1,
        canonical_result_ordinal=1,
        result_path="$.results[1]",
    )
    response = _zero_residual_partition(
        partition_ordinal=2,
        observation_ordinal=0,
        observation_partition_ordinal=2,
    )
    receipt = _receipt(
        partitions=(partition_a, partition_b, response),
        items=(first_a, first_b, second_a, second_b),
    )
    assert receipt.item_count == 4
    assert partition_a.first_global_item_ordinal == 0
    assert partition_b.first_global_item_ordinal == 1


def test_aggregate_rejects_cross_observation_source_reseal() -> None:
    _receipt_value, partitions, items, authority = _complete_projection()
    row = partitions[1].to_row()
    row["source_input_kind"] = "declared_bodyless_packet"
    forged = ValueProjectionPartitionV1.from_row(
        _reseal_row(row, dto=ValueProjectionPartitionV1, digest_field="partition_sha256")
    )
    with pytest.raises(ValueProjectionError, match="exact ownership partition"):
        _receipt(
            partitions=(partitions[0], forged, *partitions[2:]),
            items=items,
            authority=authority,
        )


def test_aggregate_rejects_duplicate_result_ordinal() -> None:
    first = _result_partition(
        partition_ordinal=0,
        observation_ordinal=0,
        observation_partition_ordinal=0,
        unit_ordinal=0,
        representation_kind="rectangular_result_cells_v1",
        items=(),
        result_name="DUP",
        ordered_headers=(),
    )
    second = _result_partition(
        partition_ordinal=1,
        observation_ordinal=0,
        observation_partition_ordinal=1,
        unit_ordinal=1,
        representation_kind="rectangular_result_cells_v1",
        items=(),
        result_name="DUP",
        ordered_headers=(),
    )
    row = second.to_row()
    row["occurrence_sha256"] = _sha("occurrence-0-1")
    row["occurrence_ordinal"] = 1
    row["result_duplicate_ordinal"] = 0
    second = ValueProjectionPartitionV1.from_row(
        _reseal_row(row, dto=ValueProjectionPartitionV1, digest_field="partition_sha256")
    )
    response = _zero_residual_partition(
        partition_ordinal=2,
        observation_ordinal=0,
        observation_partition_ordinal=2,
    )
    with pytest.raises(ValueProjectionError, match="duplicate result ordinal"):
        _receipt(partitions=(first, second, response), items=())


def test_aggregate_requires_one_response_partition_per_observation() -> None:
    _receipt_value, partitions, items, authority = _complete_projection()
    with pytest.raises(ValueProjectionError, match="denominators"):
        _receipt(partitions=partitions[:-1], items=items, authority=authority)


def test_empty_projection_has_typed_bundle_bound_zero_roots() -> None:
    receipt = _receipt(partitions=(), items=())
    assert receipt.observation_count == 0
    assert receipt.partition_count == 0
    assert receipt.item_count == 0
    assert ValueProjectionReceiptV1.from_canonical_bytes(receipt.canonical_bytes()) == receipt


def test_semantic_authority_rejects_coordinated_representation_reseal() -> None:
    _receipt_value, partitions, items, authority = _complete_projection()
    assignments = list(authority.representation_assignments)
    assignments[0] = ValueRepresentationAssignmentV1.build(
        expected_unit=authority.expected_unit_inventory.units[0],
        source_input_kind="parser_input_body",
        representation_kind="stats_lossless_records_v1",
    )
    drifted = _rebuild_authority_with_assignments(authority, tuple(assignments))

    with pytest.raises(ValueProjectionError, match="exact ownership binding"):
        _receipt(partitions=partitions, items=items, authority=drifted)


@pytest.mark.parametrize("field_name", ["observation_sha256", "observation_record_sha256"])
def test_semantic_authority_tracks_observation_identities_independently(
    field_name: str,
) -> None:
    _receipt_value, partitions, items, authority = _complete_projection()
    kwargs = _authority_kwargs(authority)
    observations = [
        dict(row)
        for row in cast(
            "tuple[dict[str, object], ...]",
            kwargs["ownership_observation_rows"],
        )
    ]
    observations[1][field_name] = observations[0][field_name]
    observations[1] = _reseal_semantic_row(
        observations[1],
        kind=value_projection._OWNERSHIP_OBSERVATION_KIND,
        digest_field="observation_ownership_sha256",
    )
    kwargs["ownership_observation_rows"] = tuple(observations)

    with pytest.raises(ValueProjectionError, match="duplicate identity"):
        ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=_sha("bundle"),
            partitions=partitions,
            items=items,
            **cast("Any", kwargs),
        )


def test_semantic_authority_rejects_sole_empty_response_residual() -> None:
    _receipt_value, partitions, items, authority = _complete_projection()
    kwargs = _authority_kwargs(authority)
    observations = [
        dict(row)
        for row in cast(
            "tuple[dict[str, object], ...]",
            kwargs["ownership_observation_rows"],
        )
    ]
    observations[4]["response_partition_kind"] = "response_residual"
    observations[4]["fixed_zero_landing_sha256"] = None
    observations[4] = _reseal_semantic_row(
        observations[4],
        kind=value_projection._OWNERSHIP_OBSERVATION_KIND,
        digest_field="observation_ownership_sha256",
    )
    kwargs["ownership_observation_rows"] = tuple(observations)

    with pytest.raises(ValueProjectionError, match="mandatory fixed-zero"):
        ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=_sha("bundle"),
            partitions=partitions,
            items=items,
            **cast("Any", kwargs),
        )


@pytest.mark.parametrize("field_name", ["ownership_binding_sha256", "source_record_sha256"])
def test_projection_item_joins_binding_and_source_record_field_for_field(
    field_name: str,
) -> None:
    _receipt_value, partitions, items, authority = _complete_projection()
    row = items[0].to_row()
    row[field_name] = _sha(f"foreign-{field_name}")
    forged = ValueProjectionItemV1.from_row(
        _reseal_row(row, dto=ValueProjectionItemV1, digest_field="item_sha256")
    )

    with pytest.raises(ValueProjectionError, match="exact ownership binding"):
        _receipt(
            partitions=partitions,
            items=(forged, *items[1:]),
            authority=authority,
        )


def test_semantic_inventories_require_exact_builtin_tuples() -> None:
    class ForeignTuple(tuple[object, ...]):
        pass

    _receipt_value, partitions, items, authority = _complete_projection()
    kwargs = _authority_kwargs(authority)
    kwargs["expected_unit_rows"] = ForeignTuple(
        cast("tuple[dict[str, object], ...]", kwargs["expected_unit_rows"])
    )
    with pytest.raises(ValueProjectionError, match="semantic inventory is foreign"):
        ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=_sha("bundle"),
            partitions=partitions,
            items=items,
            **cast("Any", kwargs),
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"header_name": "forged"}, "ordered headers"),
        ({"cell_ordinal": 99}, "outside its declared inventory"),
    ],
)
def test_rectangular_header_and_cell_coordinates_are_structurally_joined(
    changes: dict[str, object],
    message: str,
) -> None:
    _receipt_value, partitions, items, authority = _complete_projection()
    forged = _resealed_item_coordinate(items[0], **changes)
    with pytest.raises(ValueProjectionError, match=message):
        _rebuild_partition(
            partitions[0],
            ownership_partition=authority.partitions[0],
            items=(forged,),
            assignments=authority.representation_assignments,
        )


def test_result_container_domain_and_live_field_inventory_are_closed() -> None:
    _receipt_value, partitions, items, authority = _complete_projection()
    row = partitions[0].to_row()
    row["container_kind"] = "foreign_container"
    with pytest.raises(ValueProjectionError, match="container contradicts"):
        ValueProjectionPartitionV1.from_row(
            _reseal_row(
                row,
                dto=ValueProjectionPartitionV1,
                digest_field="partition_sha256",
            )
        )

    for changes, message in (
        ({"field_name": "forged"}, "ordered headers"),
        ({"field_ordinal": 99}, "outside its declared inventory"),
    ):
        forged = _resealed_item_coordinate(items[5], **changes)
        forged_items = tuple(forged if item is items[5] else item for item in items)
        with pytest.raises(ValueProjectionError, match=message):
            _rebuild_partition(
                partitions[4],
                ownership_partition=authority.partitions[4],
                items=_partition_items(forged_items, 4),
                assignments=authority.representation_assignments,
            )


def test_row_identity_cannot_drift_between_cells_of_one_row() -> None:
    def cell(item_ordinal: int, header_ordinal: int, row_sha256: str) -> ValueProjectionItemV1:
        return _item(
            item_ordinal=item_ordinal,
            partition_ordinal=0,
            partition_item_ordinal=item_ordinal,
            observation_ordinal=0,
            representation_kind="rectangular_result_cells_v1",
            unit_kind="result_occurrence",
            unit_ordinal=0,
            record_kind="cell",
            coordinate=_coordinate(
                result_name="Rows",
                result_duplicate_ordinal=0,
                provider_result_ordinal=0,
                expected_result_ordinal=0,
                canonical_result_ordinal=0,
                result_path="$.results[0]",
                container_kind="nba_api_result_set",
                result_presence="present",
                header_name=("A", "B")[header_ordinal],
                header_ordinal=header_ordinal,
                header_duplicate_ordinal=0,
                row_ordinal=0,
                row_duplicate_ordinal=0,
                row_value_sha256=row_sha256,
                cell_ordinal=header_ordinal,
                value_duplicate_ordinal=0,
            ),
            value=item_ordinal,
        )

    with pytest.raises(ValueProjectionError, match="row ordinal changes"):
        _result_partition(
            partition_ordinal=0,
            observation_ordinal=0,
            observation_partition_ordinal=0,
            unit_ordinal=0,
            representation_kind="rectangular_result_cells_v1",
            items=(cell(0, 0, _sha("row-a")), cell(1, 1, _sha("row-b"))),
            result_name="Rows",
            ordered_headers=("A", "B"),
            header_count=2,
            row_count=1,
            cell_count=2,
        )


def test_duplicate_and_reordered_cell_coordinates_are_rejected() -> None:
    def cell(item_ordinal: int, row_ordinal: int, cell_ordinal: int) -> ValueProjectionItemV1:
        return _item(
            item_ordinal=item_ordinal,
            partition_ordinal=0,
            partition_item_ordinal=item_ordinal,
            observation_ordinal=0,
            representation_kind="rectangular_result_cells_v1",
            unit_kind="result_occurrence",
            unit_ordinal=0,
            record_kind="cell",
            coordinate=_coordinate(
                result_name="Rows",
                result_duplicate_ordinal=0,
                provider_result_ordinal=0,
                expected_result_ordinal=0,
                canonical_result_ordinal=0,
                result_path="$.results[0]",
                container_kind="nba_api_result_set",
                result_presence="present",
                header_name="A",
                header_ordinal=0,
                header_duplicate_ordinal=0,
                row_ordinal=row_ordinal,
                row_duplicate_ordinal=0,
                row_value_sha256=_sha(f"row-{row_ordinal}"),
                cell_ordinal=cell_ordinal,
                value_duplicate_ordinal=item_ordinal,
            ),
            value=1,
        )

    with pytest.raises(ValueProjectionError, match="coordinate inventory contains a duplicate"):
        _result_partition(
            partition_ordinal=0,
            observation_ordinal=0,
            observation_partition_ordinal=0,
            unit_ordinal=0,
            representation_kind="rectangular_result_cells_v1",
            items=(cell(0, 0, 0), cell(1, 0, 1)),
            result_name="Rows",
            ordered_headers=("A",),
            header_count=1,
            row_count=2,
            cell_count=2,
        )
    with pytest.raises(ValueProjectionError, match="row-major order"):
        _result_partition(
            partition_ordinal=0,
            observation_ordinal=0,
            observation_partition_ordinal=0,
            unit_ordinal=0,
            representation_kind="rectangular_result_cells_v1",
            items=(cell(0, 1, 0), cell(1, 0, 1)),
            result_name="Rows",
            ordered_headers=("A",),
            header_count=1,
            row_count=2,
            cell_count=2,
        )


def test_live_cell_structural_order_is_checked_in_one_forward_pass() -> None:
    _receipt_value, partitions, items, _authority = _two_row_live_projection()
    partition = partitions[0]
    reordered_items = (*items[:7], items[8], items[7], *items[9:])
    reordered: list[ValueProjectionItemV1] = []
    for ordinal, item in enumerate(reordered_items):
        row = item.to_row()
        row["ownership_binding_ordinal"] = ordinal
        row["global_item_ordinal"] = ordinal
        row["partition_item_ordinal"] = ordinal
        reordered.append(
            ValueProjectionItemV1.from_row(
                _reseal_row(row, dto=ValueProjectionItemV1, digest_field="item_sha256")
            )
        )

    with pytest.raises(ValueProjectionError, match="canonical structural order"):
        ValueProjectionPartitionV1.build(
            raw_authority_bundle_sha256=partition.raw_authority_bundle_sha256,
            ownership_partition_sha256=partition.ownership_partition_sha256,
            observation_record_sha256=partition.observation_record_sha256,
            observation_sha256=partition.observation_sha256,
            observation_ordinal=partition.observation_ordinal,
            partition_ordinal=partition.partition_ordinal,
            observation_partition_ordinal=partition.observation_partition_ordinal,
            partition_kind=partition.partition_kind,
            source_input_kind=partition.source_input_kind,
            items=tuple(reordered),
            occurrence_sha256=partition.occurrence_sha256,
            occurrence_ordinal=partition.occurrence_ordinal,
            unit_sha256=partition.unit_sha256,
            unit_ordinal=partition.unit_ordinal,
            assignment_sha256=partition.assignment_sha256,
            representation_kind=partition.representation_kind,
            result_name=partition.result_name,
            result_duplicate_ordinal=partition.result_duplicate_ordinal,
            provider_result_ordinal=partition.provider_result_ordinal,
            expected_result_ordinal=partition.expected_result_ordinal,
            canonical_result_ordinal=partition.canonical_result_ordinal,
            result_path=partition.result_path,
            container_kind=partition.container_kind,
            result_presence=partition.result_presence,
            ordered_headers=("F", "G"),
            header_count=2,
            field_count=2,
            row_count=2,
            cell_count=4,
            node_count=7,
            representation_output_sha256=partition.representation_output_sha256,
        )


def test_rectangular_cell_product_is_unconditional() -> None:
    _receipt_value, partitions, _items, _authority = _complete_projection()
    row = partitions[8].to_row()
    row["row_count"] = 1
    with pytest.raises(ValueProjectionError, match="exact cell rectangle"):
        ValueProjectionPartitionV1.from_row(
            _reseal_row(
                row,
                dto=ValueProjectionPartitionV1,
                digest_field="partition_sha256",
            )
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"depth": 2}, "path/depth"),
        ({"parent_json_path": '$["forged"]'}, "path/depth"),
        ({"object_key_ordinal": 1}, "sibling order"),
        ({"json_path": "$"}, "duplicate"),
        ({"json_path": '$["wrong"]'}, "exact parent edge"),
        ({"json_path": "$[0]"}, "exact parent edge"),
        ({"json_path": "$suffix"}, "noncanonical component"),
    ],
)
def test_node_path_parent_depth_and_sibling_algebra_is_exact(
    changes: dict[str, object],
    message: str,
) -> None:
    root = _item(
        item_ordinal=0,
        partition_ordinal=0,
        partition_item_ordinal=0,
        observation_ordinal=0,
        representation_kind="response_lossless_records_v1",
        unit_kind="response_residual",
        unit_ordinal=0,
        record_kind="json_node",
        coordinate=_coordinate(node_ordinal=0, json_path="$", depth=0),
        value_state="structural_container",
        structural_value_kind="object",
    )
    child = _item(
        item_ordinal=1,
        partition_ordinal=0,
        partition_item_ordinal=1,
        observation_ordinal=0,
        representation_kind="response_lossless_records_v1",
        unit_kind="response_residual",
        unit_ordinal=0,
        record_kind="json_node",
        coordinate=_coordinate(
            node_ordinal=1,
            parent_node_ordinal=0,
            json_path='$["a"]',
            parent_json_path="$",
            depth=1,
            object_key="a",
            object_key_ordinal=0,
        ),
        value=1,
    )
    _positive_residual_partition(
        partition_ordinal=0,
        observation_ordinal=0,
        unit_ordinal=0,
        items=(root, child),
        source_input_kind="parser_input_body",
    )
    forged = _resealed_item_coordinate(child, **changes)
    with pytest.raises(ValueProjectionError, match=message):
        _positive_residual_partition(
            partition_ordinal=0,
            observation_ordinal=0,
            unit_ordinal=0,
            items=(root, forged),
            source_input_kind="parser_input_body",
        )


def test_node_paths_accept_exact_escaped_object_keys_and_array_indices() -> None:
    root = _item(
        item_ordinal=0,
        partition_ordinal=0,
        partition_item_ordinal=0,
        observation_ordinal=0,
        representation_kind="response_lossless_records_v1",
        unit_kind="response_residual",
        unit_ordinal=0,
        record_kind="json_node",
        coordinate=_coordinate(node_ordinal=0, json_path="$", depth=0),
        value_state="structural_container",
        structural_value_kind="object",
    )
    escaped_key = 'quote" slash\\ newline\n snow 雪'
    escaped_component = json.dumps(
        escaped_key,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    object_child = _item(
        item_ordinal=1,
        partition_ordinal=0,
        partition_item_ordinal=1,
        observation_ordinal=0,
        representation_kind="response_lossless_records_v1",
        unit_kind="response_residual",
        unit_ordinal=0,
        record_kind="json_node",
        coordinate=_coordinate(
            node_ordinal=1,
            parent_node_ordinal=0,
            json_path=f"$[{escaped_component}]",
            parent_json_path="$",
            depth=1,
            object_key=escaped_key,
            object_key_ordinal=0,
        ),
        value=1,
    )
    _positive_residual_partition(
        partition_ordinal=0,
        observation_ordinal=0,
        unit_ordinal=0,
        items=(root, object_child),
        source_input_kind="parser_input_body",
    )

    array_root = _item(
        item_ordinal=0,
        partition_ordinal=0,
        partition_item_ordinal=0,
        observation_ordinal=0,
        representation_kind="response_lossless_records_v1",
        unit_kind="response_residual",
        unit_ordinal=0,
        record_kind="json_node",
        coordinate=_coordinate(node_ordinal=0, json_path="$", depth=0),
        value_state="structural_container",
        structural_value_kind="array",
    )
    array_child = _item(
        item_ordinal=1,
        partition_ordinal=0,
        partition_item_ordinal=1,
        observation_ordinal=0,
        representation_kind="response_lossless_records_v1",
        unit_kind="response_residual",
        unit_ordinal=0,
        record_kind="json_node",
        coordinate=_coordinate(
            node_ordinal=1,
            parent_node_ordinal=0,
            json_path="$[0]",
            parent_json_path="$",
            depth=1,
            array_ordinal=0,
        ),
        value=1,
    )
    _positive_residual_partition(
        partition_ordinal=0,
        observation_ordinal=0,
        unit_ordinal=0,
        items=(array_root, array_child),
        source_input_kind="parser_input_body",
    )
    forged = _resealed_item_coordinate(array_child, json_path="$[1]")
    with pytest.raises(ValueProjectionError, match="exact parent edge"):
        _positive_residual_partition(
            partition_ordinal=0,
            observation_ordinal=0,
            unit_ordinal=0,
            items=(array_root, forged),
            source_input_kind="parser_input_body",
        )


@pytest.mark.parametrize(
    ("value_state", "value", "structural_value_kind"),
    [
        ("canonical", 7, None),
        ("canonical", {}, None),
        ("structural_container", None, "array"),
    ],
)
def test_fully_resealed_receipt_rejects_parent_value_edge_contradictions(
    value_state: str,
    value: object,
    structural_value_kind: str | None,
) -> None:
    root = _item(
        item_ordinal=0,
        partition_ordinal=0,
        partition_item_ordinal=0,
        observation_ordinal=0,
        representation_kind="response_lossless_records_v1",
        unit_kind="response_residual",
        unit_ordinal=0,
        record_kind="json_node",
        coordinate=_coordinate(node_ordinal=0, json_path="$", depth=0),
        value_state="structural_container",
        structural_value_kind="object",
    )
    child = _item(
        item_ordinal=1,
        partition_ordinal=0,
        partition_item_ordinal=1,
        observation_ordinal=0,
        representation_kind="response_lossless_records_v1",
        unit_kind="response_residual",
        unit_ordinal=0,
        record_kind="json_node",
        coordinate=_coordinate(
            node_ordinal=1,
            parent_node_ordinal=0,
            json_path='$["a"]',
            parent_json_path="$",
            depth=1,
            object_key="a",
            object_key_ordinal=0,
        ),
        value=1,
    )
    source_partition = _positive_residual_partition(
        partition_ordinal=0,
        observation_ordinal=0,
        unit_ordinal=0,
        items=(root, child),
        source_input_kind="parser_input_body",
    )
    _receipt_value, partitions, items, authority = _seal_projection(
        partitions=(source_partition,),
        items=(root, child),
    )
    forged_root = _resealed_item_value_shape(
        items[0],
        value_state=value_state,
        value=value,
        structural_value_kind=structural_value_kind,
    )
    forged_items = (forged_root, items[1])
    forged_partition = _resealed_partition_values(partitions[0], forged_items)

    with pytest.raises(ValueProjectionError, match="parent container"):
        ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=_sha("bundle"),
            partitions=(forged_partition,),
            items=forged_items,
            **cast("Any", _authority_kwargs(authority)),
        )


def test_live_scalar_array_projection_joins_field_to_exact_value_node() -> None:
    root = _item(
        item_ordinal=0,
        partition_ordinal=0,
        partition_item_ordinal=0,
        observation_ordinal=0,
        representation_kind="live_lossless_nodes_v1",
        unit_kind="result_occurrence",
        unit_ordinal=0,
        record_kind="node",
        coordinate=_coordinate(
            result_name="Scalar",
            result_duplicate_ordinal=0,
            provider_result_ordinal=0,
            expected_result_ordinal=0,
            canonical_result_ordinal=0,
            result_path="$",
            container_kind="nba_api_live_json_array",
            result_presence="present",
            node_ordinal=0,
            json_path="$",
            depth=0,
            context_result_name="Scalar",
            context_result_ordinal=0,
            context_result_occurrence=0,
        ),
        value_state="structural_container",
        structural_value_kind="array",
    )
    value_node = _item(
        item_ordinal=1,
        partition_ordinal=0,
        partition_item_ordinal=1,
        observation_ordinal=0,
        representation_kind="live_lossless_nodes_v1",
        unit_kind="result_occurrence",
        unit_ordinal=0,
        record_kind="node",
        coordinate=_coordinate(
            result_name="Scalar",
            result_duplicate_ordinal=0,
            provider_result_ordinal=0,
            expected_result_ordinal=0,
            canonical_result_ordinal=0,
            result_path="$",
            container_kind="nba_api_live_json_array",
            result_presence="present",
            node_ordinal=1,
            parent_node_ordinal=0,
            json_path="$[0]",
            parent_json_path="$",
            depth=1,
            array_ordinal=0,
            context_result_name="Scalar",
            context_result_ordinal=0,
            context_result_occurrence=0,
            row_ordinal=0,
        ),
        value=7,
    )
    field = _item(
        item_ordinal=2,
        partition_ordinal=0,
        partition_item_ordinal=2,
        observation_ordinal=0,
        representation_kind="live_lossless_nodes_v1",
        unit_kind="result_occurrence",
        unit_ordinal=0,
        record_kind="field_cell",
        coordinate=_coordinate(
            result_name="Scalar",
            result_duplicate_ordinal=0,
            provider_result_ordinal=0,
            expected_result_ordinal=0,
            canonical_result_ordinal=0,
            result_path="$",
            container_kind="nba_api_live_json_array",
            result_presence="present",
            field_name="value",
            field_ordinal=0,
            row_ordinal=0,
            cell_ordinal=0,
            value_duplicate_ordinal=0,
            node_ordinal=1,
            json_path="$[0]",
            key_presence="required",
            owner_result_name="Scalar",
            owner_result_ordinal=0,
            owner_result_occurrence=0,
            context_result_name="Scalar",
            context_result_ordinal=0,
            context_result_occurrence=0,
            known_contract_field=True,
        ),
        value=7,
    )

    receipt, partitions, items, _authority = _seal_live_projection(
        items=(root, value_node, field),
        result_name="Scalar",
        ordered_headers=("value",),
        container_kind="nba_api_live_json_array",
        row_count=1,
        cell_count=1,
        node_count=2,
    )

    assert receipt.item_count == 5
    assert receipt.structural_value_count == 1
    assert partitions[0].node_count == 2
    assert items[2].coordinate()["node_ordinal"] == 1


@pytest.mark.parametrize("key_presence", ("required", "optional"))
def test_live_empty_object_missing_field_sidecars_are_value_free(
    key_presence: str,
) -> None:
    root = _item(
        item_ordinal=0,
        partition_ordinal=0,
        partition_item_ordinal=0,
        observation_ordinal=0,
        representation_kind="live_lossless_nodes_v1",
        unit_kind="result_occurrence",
        unit_ordinal=0,
        record_kind="node",
        coordinate=_coordinate(
            result_name="Empty",
            result_duplicate_ordinal=0,
            provider_result_ordinal=0,
            expected_result_ordinal=0,
            canonical_result_ordinal=0,
            result_path="$",
            container_kind="nba_api_live_json_object",
            result_presence="present",
            node_ordinal=0,
            json_path="$",
            depth=0,
            context_result_name="Empty",
            context_result_ordinal=0,
            context_result_occurrence=0,
            row_ordinal=0,
        ),
        value={},
    )
    missing_node = _item(
        item_ordinal=1,
        partition_ordinal=0,
        partition_item_ordinal=1,
        observation_ordinal=0,
        representation_kind="live_lossless_nodes_v1",
        unit_kind="result_occurrence",
        unit_ordinal=0,
        record_kind="node",
        coordinate=_coordinate(
            result_name="Empty",
            result_duplicate_ordinal=0,
            provider_result_ordinal=0,
            expected_result_ordinal=0,
            canonical_result_ordinal=0,
            result_path="$",
            container_kind="nba_api_live_json_object",
            result_presence="present",
            node_ordinal=1,
            parent_node_ordinal=0,
            json_path='$["F"]',
            parent_json_path="$",
            depth=1,
            object_key="F",
            context_result_name="Empty",
            context_result_ordinal=0,
            context_result_occurrence=0,
            known_contract_field=True,
            row_ordinal=0,
        ),
        value_state="missing",
        missing_presence_kind="missing",
    )
    missing_field = _item(
        item_ordinal=2,
        partition_ordinal=0,
        partition_item_ordinal=2,
        observation_ordinal=0,
        representation_kind="live_lossless_nodes_v1",
        unit_kind="result_occurrence",
        unit_ordinal=0,
        record_kind="field_cell",
        coordinate=_coordinate(
            result_name="Empty",
            result_duplicate_ordinal=0,
            provider_result_ordinal=0,
            expected_result_ordinal=0,
            canonical_result_ordinal=0,
            result_path="$",
            container_kind="nba_api_live_json_object",
            result_presence="present",
            field_name="F",
            field_ordinal=0,
            row_ordinal=0,
            cell_ordinal=0,
            value_duplicate_ordinal=0,
            node_ordinal=1,
            json_path='$["F"]',
            key_presence=key_presence,
            owner_result_name="Empty",
            owner_result_ordinal=0,
            owner_result_occurrence=0,
            context_result_name="Empty",
            context_result_ordinal=0,
            context_result_occurrence=0,
            known_contract_field=True,
        ),
        value_state="missing",
        missing_presence_kind="missing",
    )

    receipt, partitions, _items, _authority = _seal_live_projection(
        items=(root, missing_node, missing_field),
        result_name="Empty",
        ordered_headers=("F",),
        container_kind="nba_api_live_json_object",
        row_count=1,
        cell_count=1,
        node_count=2,
    )

    assert receipt.empty_object_count == 1
    assert receipt.missing_count == 2
    assert receipt.structural_value_count == 0
    assert partitions[0].canonical_value_byte_count == 2


def _nested_live_projection() -> tuple[
    ValueProjectionReceiptV1,
    tuple[ValueProjectionPartitionV1, ...],
    tuple[ValueProjectionItemV1, ...],
    LosslessOwnershipAuthorityV1,
]:
    result = {
        "result_name": "Parent",
        "result_duplicate_ordinal": 0,
        "provider_result_ordinal": 0,
        "expected_result_ordinal": 0,
        "canonical_result_ordinal": 0,
        "result_path": "$",
        "container_kind": "nba_api_live_json_object",
        "result_presence": "present",
    }
    child_result = {
        "result_name": "Child",
        "result_duplicate_ordinal": 0,
        "provider_result_ordinal": 1,
        "expected_result_ordinal": 1,
        "canonical_result_ordinal": 1,
        "result_path": '$["Child"]',
        "container_kind": "nba_api_live_json_object",
        "result_presence": "present",
    }
    root = _item(
        item_ordinal=0,
        partition_ordinal=0,
        partition_item_ordinal=0,
        observation_ordinal=0,
        representation_kind="live_lossless_nodes_v1",
        unit_kind="result_occurrence",
        unit_ordinal=0,
        record_kind="node",
        coordinate=_coordinate(
            **result,
            node_ordinal=0,
            json_path="$",
            depth=0,
            context_result_name="Parent",
            context_result_ordinal=0,
            context_result_occurrence=0,
            row_ordinal=0,
        ),
        value_state="structural_container",
        structural_value_kind="object",
    )
    child = _item(
        item_ordinal=1,
        partition_ordinal=1,
        partition_item_ordinal=0,
        observation_ordinal=0,
        representation_kind="live_lossless_nodes_v1",
        unit_kind="result_occurrence",
        unit_ordinal=1,
        record_kind="node",
        coordinate=_coordinate(
            **child_result,
            node_ordinal=1,
            parent_node_ordinal=0,
            json_path='$["Child"]',
            parent_json_path="$",
            depth=1,
            object_key="Child",
            object_key_ordinal=0,
            context_result_name="Child",
            context_result_ordinal=1,
            context_result_occurrence=0,
            known_contract_field=True,
            row_ordinal=0,
        ),
        value={},
        occurrence_ordinal=1,
    )
    field = _item(
        item_ordinal=2,
        partition_ordinal=0,
        partition_item_ordinal=1,
        observation_ordinal=0,
        representation_kind="live_lossless_nodes_v1",
        unit_kind="result_occurrence",
        unit_ordinal=0,
        record_kind="field_cell",
        coordinate=_coordinate(
            **result,
            field_name="Child",
            field_ordinal=0,
            row_ordinal=0,
            cell_ordinal=0,
            value_duplicate_ordinal=0,
            node_ordinal=1,
            json_path='$["Child"]',
            key_presence="required",
            owner_result_name="Parent",
            owner_result_ordinal=0,
            owner_result_occurrence=0,
            context_result_name="Child",
            context_result_ordinal=1,
            context_result_occurrence=0,
            known_contract_field=True,
        ),
        value={},
    )

    parent_partition = _result_partition(
        partition_ordinal=0,
        observation_ordinal=0,
        observation_partition_ordinal=0,
        unit_ordinal=0,
        representation_kind="live_lossless_nodes_v1",
        items=(root, field),
        result_name="Parent",
        ordered_headers=("Child",),
        header_count=1,
        field_count=1,
        row_count=1,
        cell_count=1,
        node_count=1,
        result_path="$",
        container_kind="nba_api_live_json_object",
    )
    child_partition = _result_partition(
        partition_ordinal=1,
        observation_ordinal=0,
        observation_partition_ordinal=1,
        unit_ordinal=1,
        representation_kind="live_lossless_nodes_v1",
        items=(child,),
        result_name="Child",
        ordered_headers=(),
        row_count=1,
        node_count=1,
        occurrence_ordinal=1,
        provider_result_ordinal=1,
        expected_result_ordinal=1,
        canonical_result_ordinal=1,
        result_path='$["Child"]',
        container_kind="nba_api_live_json_object",
    )
    residual_partition = _zero_residual_partition(
        partition_ordinal=2,
        observation_ordinal=0,
        observation_partition_ordinal=2,
    )
    return _seal_projection(
        partitions=(parent_partition, child_partition, residual_partition),
        items=(root, child, field),
    )


def test_live_nested_field_context_joins_parent_owner_and_value_node() -> None:
    receipt, _partitions, _items, _authority = _nested_live_projection()

    assert receipt.structural_value_count == 1
    assert receipt.empty_object_count == 2


def test_live_nonempty_container_field_is_one_structural_node_reference() -> None:
    result = {
        "result_name": "Parent",
        "result_duplicate_ordinal": 0,
        "provider_result_ordinal": 0,
        "expected_result_ordinal": 0,
        "canonical_result_ordinal": 0,
        "result_path": "$",
        "container_kind": "nba_api_live_json_object",
        "result_presence": "present",
    }
    child_result = {
        "result_name": "Child",
        "result_duplicate_ordinal": 0,
        "provider_result_ordinal": 1,
        "expected_result_ordinal": 1,
        "canonical_result_ordinal": 1,
        "result_path": '$["Child"]',
        "container_kind": "nba_api_live_json_object",
        "result_presence": "present",
    }
    root = _item(
        item_ordinal=0,
        partition_ordinal=0,
        partition_item_ordinal=0,
        observation_ordinal=0,
        representation_kind="live_lossless_nodes_v1",
        unit_kind="result_occurrence",
        unit_ordinal=0,
        record_kind="node",
        coordinate=_coordinate(
            **result,
            node_ordinal=0,
            json_path="$",
            depth=0,
            context_result_name="Parent",
            context_result_ordinal=0,
            context_result_occurrence=0,
            row_ordinal=0,
        ),
        value_state="structural_container",
        structural_value_kind="object",
    )
    child = _item(
        item_ordinal=1,
        partition_ordinal=1,
        partition_item_ordinal=0,
        observation_ordinal=0,
        representation_kind="live_lossless_nodes_v1",
        unit_kind="result_occurrence",
        unit_ordinal=1,
        record_kind="node",
        coordinate=_coordinate(
            **child_result,
            node_ordinal=1,
            parent_node_ordinal=0,
            json_path='$["Child"]',
            parent_json_path="$",
            depth=1,
            object_key="Child",
            object_key_ordinal=0,
            context_result_name="Child",
            context_result_ordinal=1,
            context_result_occurrence=0,
            known_contract_field=True,
            row_ordinal=0,
        ),
        value_state="structural_container",
        structural_value_kind="object",
        occurrence_ordinal=1,
    )
    leaf = _item(
        item_ordinal=2,
        partition_ordinal=1,
        partition_item_ordinal=1,
        observation_ordinal=0,
        representation_kind="live_lossless_nodes_v1",
        unit_kind="result_occurrence",
        unit_ordinal=1,
        record_kind="node",
        coordinate=_coordinate(
            **child_result,
            node_ordinal=2,
            parent_node_ordinal=1,
            json_path='$["Child"]["x"]',
            parent_json_path='$["Child"]',
            depth=2,
            object_key="x",
            object_key_ordinal=0,
            context_result_name="Child",
            context_result_ordinal=1,
            context_result_occurrence=0,
            row_ordinal=0,
        ),
        value=1,
        occurrence_ordinal=1,
    )
    field = _item(
        item_ordinal=3,
        partition_ordinal=0,
        partition_item_ordinal=1,
        observation_ordinal=0,
        representation_kind="live_lossless_nodes_v1",
        unit_kind="result_occurrence",
        unit_ordinal=0,
        record_kind="field_cell",
        coordinate=_coordinate(
            **result,
            field_name="Child",
            field_ordinal=0,
            row_ordinal=0,
            cell_ordinal=0,
            value_duplicate_ordinal=0,
            node_ordinal=1,
            json_path='$["Child"]',
            key_presence="required",
            owner_result_name="Parent",
            owner_result_ordinal=0,
            owner_result_occurrence=0,
            context_result_name="Child",
            context_result_ordinal=1,
            context_result_occurrence=0,
            known_contract_field=True,
        ),
        value_state="structural_container",
        structural_value_kind="object",
    )

    parent_partition = _result_partition(
        partition_ordinal=0,
        observation_ordinal=0,
        observation_partition_ordinal=0,
        unit_ordinal=0,
        representation_kind="live_lossless_nodes_v1",
        items=(root, field),
        result_name="Parent",
        ordered_headers=("Child",),
        header_count=1,
        field_count=1,
        row_count=1,
        cell_count=1,
        node_count=1,
        result_path="$",
        container_kind="nba_api_live_json_object",
    )
    child_partition = _result_partition(
        partition_ordinal=1,
        observation_ordinal=0,
        observation_partition_ordinal=1,
        unit_ordinal=1,
        representation_kind="live_lossless_nodes_v1",
        items=(child, leaf),
        result_name="Child",
        ordered_headers=(),
        row_count=1,
        node_count=2,
        occurrence_ordinal=1,
        provider_result_ordinal=1,
        expected_result_ordinal=1,
        canonical_result_ordinal=1,
        result_path='$["Child"]',
        container_kind="nba_api_live_json_object",
    )
    residual_partition = _zero_residual_partition(
        partition_ordinal=2,
        observation_ordinal=0,
        observation_partition_ordinal=2,
    )
    receipt, partitions, items, _authority = _seal_projection(
        partitions=(parent_partition, child_partition, residual_partition),
        items=(root, child, leaf, field),
    )

    assert receipt.structural_value_count == 3
    assert partitions[0].canonical_value_byte_count == 0
    assert partitions[1].canonical_value_byte_count == 1
    assert items[3].canonical_json is None


def test_live_cross_row_field_owner_swap_fails_after_full_receipt_reseal() -> None:
    _receipt_value, partitions, items, authority = _two_row_live_projection()
    row_zero_field = _resealed_item_coordinate(
        items[7],
        node_ordinal=5,
        json_path='$[1]["F"]',
    )
    row_one_field = _resealed_item_coordinate(
        items[9],
        node_ordinal=2,
        json_path='$[0]["F"]',
    )
    forged_items = (
        *items[:7],
        row_zero_field,
        items[8],
        row_one_field,
        items[10],
        *items[11:],
    )
    forged_partition = _resealed_partition_items(partitions[0], _partition_items(forged_items, 0))

    with pytest.raises(ValueProjectionError, match="value node or owner context"):
        ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=_sha("bundle"),
            partitions=(forged_partition, partitions[1]),
            items=forged_items,
            **cast("Any", _authority_kwargs(authority)),
        )


def test_live_row_identity_is_scoped_to_each_concrete_result_occurrence() -> None:
    receipt, partitions, items, _authority = _two_occurrence_live_projection()

    assert receipt.item_count == 6
    assert partitions[0].row_count == 2
    assert items[0].coordinate()["row_ordinal"] == 0
    assert items[1].coordinate()["row_ordinal"] == 0
    assert items[0].coordinate()["context_result_occurrence"] == 0
    assert items[1].coordinate()["context_result_occurrence"] == 1

    declaration = next(item for item in items if item.record_kind == "result_declaration")
    occurrences = sorted(
        (item for item in items if item.record_kind == "result_occurrence"),
        key=lambda item: cast("int", item.coordinate()["result_occurrence_global_ordinal"]),
    )
    nodes = {
        cast("int", item.coordinate()["node_ordinal"]): item
        for item in items
        if item.record_kind == "node"
    }
    assert declaration.coordinate()["declaration_parent_result_name"] is None
    assert declaration.coordinate()["declaration_parent_field_name"] is None
    assert [item.coordinate()["result_occurrence_global_ordinal"] for item in occurrences] == [
        0,
        1,
    ]
    assert [item.coordinate()["result_occurrence_ordinal"] for item in occurrences] == [0, 1]
    assert [item.coordinate()["result_occurrence_row_count"] for item in occurrences] == [1, 1]
    for occurrence in occurrences:
        coordinate = occurrence.coordinate()
        node = nodes[cast("int", coordinate["node_ordinal"])]
        node_coordinate = node.coordinate()
        assert coordinate["json_path"] == node_coordinate["json_path"]
        assert coordinate["decoder_value_sha256"] == node_coordinate["decoder_value_sha256"]
        assert coordinate["result_occurrence_presence_kind"] == node.presence_kind
        assert node_coordinate["matches_result_occurrence"] is True


def test_context_drift_full_reseal_cannot_detach_live_child_from_parent() -> None:
    _two_receipt, two_partitions, two_items, two_authority = _two_occurrence_live_projection()
    nested_descendant = next(
        item
        for item in two_items
        if item.record_kind == "node" and item.coordinate()["node_ordinal"] == 2
    )
    forged_descendant = _resealed_item_coordinate(
        nested_descendant,
        context_result_occurrence=0,
    )
    forged_items = tuple(
        forged_descendant
        if item.global_item_ordinal == nested_descendant.global_item_ordinal
        else item
        for item in two_items
    )
    forged_partitions = _resealed_projection_partitions(two_partitions, forged_items, 0)

    with pytest.raises(ValueProjectionError, match="inherit its exact parent context"):
        ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=_sha("bundle"),
            partitions=forged_partitions,
            items=forged_items,
            **cast("Any", _authority_kwargs(two_authority)),
        )


def test_value_digest_drift_full_reseal_cannot_change_live_node_commitment() -> None:
    _receipt_value, partitions, items, authority = _complete_projection()
    node = next(
        item
        for item in items
        if item.partition_ordinal == 4
        and item.record_kind == "node"
        and item.coordinate()["matches_result_occurrence"] is True
    )
    occurrence = next(
        item
        for item in items
        if item.partition_ordinal == 4 and item.record_kind == "result_occurrence"
    )
    drift = _sha("VALUE_DIGEST_DRIFT")
    forged_node = _resealed_item_coordinate(node, decoder_value_sha256=drift)
    forged_occurrence = _resealed_item_coordinate(occurrence, decoder_value_sha256=drift)
    replacements = {
        node.global_item_ordinal: forged_node,
        occurrence.global_item_ordinal: forged_occurrence,
    }
    forged_items = tuple(replacements.get(item.global_item_ordinal, item) for item in items)
    forged_partitions = _resealed_projection_partitions(partitions, forged_items, 4)

    with pytest.raises(ValueProjectionError, match="source-public commitment"):
        ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=_sha("bundle"),
            partitions=forged_partitions,
            items=forged_items,
            **cast("Any", _authority_kwargs(authority)),
        )


def test_live_source_record_identity_matches_independent_decoder_nodes() -> None:
    fixtures = (_complete_projection(), _two_occurrence_live_projection())
    for _receipt_value, partitions, items, _authority in fixtures:
        partition_by_ordinal = {partition.partition_ordinal: partition for partition in partitions}
        field_ordinal_by_node = {
            cast("int", item.coordinate()["node_ordinal"]): cast(
                "int", item.coordinate()["field_ordinal"]
            )
            for item in items
            if item.representation_kind == "live_lossless_nodes_v1"
            and item.record_kind == "field_cell"
        }
        for item in items:
            if item.representation_kind != "live_lossless_nodes_v1" or item.record_kind != "node":
                continue
            coordinate = item.coordinate()
            node_ordinal = cast("int", coordinate["node_ordinal"])
            partition = partition_by_ordinal[item.partition_ordinal]
            decoded = DecodedLiveNodeV1(
                node_ordinal=node_ordinal,
                parent_node_ordinal=cast("int | None", coordinate["parent_node_ordinal"]),
                json_path=cast("str", coordinate["json_path"]),
                parent_json_path=cast("str | None", coordinate["parent_json_path"]),
                depth=cast("int", coordinate["depth"]),
                object_key=cast("str | None", coordinate["object_key"]),
                object_key_ordinal=cast("int | None", coordinate["object_key_ordinal"]),
                array_ordinal=cast("int | None", coordinate["array_ordinal"]),
                result_set_name=cast("str | None", coordinate["context_result_name"]),
                result_set_ordinal=cast("int | None", coordinate["context_result_ordinal"]),
                result_set_occurrence=cast("int | None", coordinate["context_result_occurrence"]),
                result_set_row_ordinal=cast("int | None", coordinate["row_ordinal"]),
                contract_json_path=cast("str | None", partition.result_path),
                container_kind=cast(
                    "Any",
                    partition.container_kind
                    if coordinate["matches_result_occurrence"] is True
                    else None,
                ),
                contract_field_ordinal=(
                    field_ordinal_by_node.get(node_ordinal)
                    if coordinate["object_key"] is not None
                    else None
                ),
                known_contract_field=cast("bool | None", coordinate["known_contract_field"]),
                presence_kind=cast("Any", item.presence_kind),
                value_kind=cast("Any", item.value_kind),
                canonical_json=item.canonical_json,
                value_sha256=cast("str", coordinate["decoder_value_sha256"]),
                node_sha256=item.source_record_sha256,
            )
            assert decoded.node_sha256 == item.source_record_sha256


def test_field_digest_drift_full_reseal_cannot_detach_live_field_from_node() -> None:
    _receipt_value, partitions, items, authority = _complete_projection()
    field = next(
        item for item in items if item.partition_ordinal == 4 and item.record_kind == "field_cell"
    )
    forged_field = _resealed_item_coordinate(
        field,
        decoder_value_sha256=_sha("FIELD_DIGEST_DRIFT"),
    )
    forged_items = tuple(
        forged_field if item.global_item_ordinal == field.global_item_ordinal else item
        for item in items
    )
    forged_partitions = _resealed_projection_partitions(partitions, forged_items, 4)

    with pytest.raises(ValueProjectionError, match="exact value node or owner context"):
        ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=_sha("bundle"),
            partitions=forged_partitions,
            items=forged_items,
            **cast("Any", _authority_kwargs(authority)),
        )


def test_live_selector_coordinates_reject_bool_and_sha_subclasses() -> None:
    class ForeignStr(str):
        pass

    with pytest.raises(ValueProjectionError, match="matches_result_occurrence.*exact boolean"):
        _item(
            item_ordinal=0,
            partition_ordinal=0,
            partition_item_ordinal=0,
            observation_ordinal=0,
            representation_kind="live_lossless_nodes_v1",
            unit_kind="result_occurrence",
            unit_ordinal=0,
            record_kind="node",
            coordinate=_coordinate(
                matches_result_occurrence=1,
                decoder_value_sha256=_sha("value"),
            ),
            value={},
        )
    with pytest.raises(ValueProjectionError, match="decoder_value_sha256.*SHA-256"):
        _item(
            item_ordinal=0,
            partition_ordinal=0,
            partition_item_ordinal=0,
            observation_ordinal=0,
            representation_kind="live_lossless_nodes_v1",
            unit_kind="result_occurrence",
            unit_ordinal=0,
            record_kind="node",
            coordinate=_coordinate(
                matches_result_occurrence=False,
                decoder_value_sha256=ForeignStr(_sha("value")),
            ),
            value={},
        )


def test_live_occurrence_cannot_reselect_descendant_after_coordinated_reseal() -> None:
    _receipt_value, partitions, items, authority = _complete_projection()
    occurrence = next(
        item
        for item in items
        if item.partition_ordinal == 4 and item.record_kind == "result_occurrence"
    )
    matched = next(
        item
        for item in items
        if item.partition_ordinal == 4
        and item.record_kind == "node"
        and item.coordinate()["matches_result_occurrence"] is True
    )
    descendant = next(
        item
        for item in items
        if item.partition_ordinal == 4
        and item.record_kind == "node"
        and item.coordinate()["matches_result_occurrence"] is False
    )
    descendant_coordinate = descendant.coordinate()
    forged_matched = _resealed_item_coordinate(matched, matches_result_occurrence=False)
    forged_descendant = _resealed_item_coordinate(descendant, matches_result_occurrence=True)
    forged_occurrence = _resealed_item_coordinate(
        occurrence,
        node_ordinal=descendant_coordinate["node_ordinal"],
        json_path=descendant_coordinate["json_path"],
        decoder_value_sha256=descendant_coordinate["decoder_value_sha256"],
        result_occurrence_presence_kind=descendant.presence_kind,
    )
    replacements = {
        matched.global_item_ordinal: forged_matched,
        descendant.global_item_ordinal: forged_descendant,
        occurrence.global_item_ordinal: forged_occurrence,
    }
    forged_items = tuple(replacements.get(item.global_item_ordinal, item) for item in items)
    forged_partitions = _resealed_projection_partitions(partitions, forged_items, 4)

    with pytest.raises(
        ValueProjectionError,
        match="exact context root node|non-occurrence-root node has no exact parent",
    ):
        ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=_sha("bundle"),
            partitions=forged_partitions,
            items=forged_items,
            **cast("Any", _authority_kwargs(authority)),
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"result_occurrence_global_ordinal": 1},
        {"result_occurrence_ordinal": 1},
        {"json_path": '$["forged"]'},
        {"result_occurrence_presence_kind": "null"},
        {"result_occurrence_row_count": 0},
        {"decoder_value_sha256": _sha("foreign-decoder-value")},
        {"result_occurrence_parent_result_name": "Forged"},
    ],
)
def test_live_occurrence_selector_reseal_fails_closed(changes: dict[str, object]) -> None:
    _receipt_value, partitions, items, authority = _complete_projection()
    occurrence = next(
        item
        for item in items
        if item.partition_ordinal == 4 and item.record_kind == "result_occurrence"
    )
    forged_occurrence = _resealed_item_coordinate(occurrence, **changes)
    forged_items = tuple(
        forged_occurrence if item.global_item_ordinal == occurrence.global_item_ordinal else item
        for item in items
    )
    forged_partitions = _resealed_projection_partitions(partitions, forged_items, 4)

    with pytest.raises(ValueProjectionError):
        ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=_sha("bundle"),
            partitions=forged_partitions,
            items=forged_items,
            **cast("Any", _authority_kwargs(authority)),
        )


@pytest.mark.parametrize("field_name", ("result_occurrence_global_ordinal", "node_ordinal"))
def test_live_occurrences_cannot_share_global_or_node_owner(
    field_name: str,
) -> None:
    _receipt_value, partitions, items, authority = _two_occurrence_live_projection()
    occurrences = sorted(
        (item for item in items if item.record_kind == "result_occurrence"),
        key=lambda item: cast("int", item.coordinate()["result_occurrence_global_ordinal"]),
    )
    first_coordinate = occurrences[0].coordinate()
    changes: dict[str, object] = {field_name: first_coordinate[field_name]}
    if field_name == "node_ordinal":
        changes.update(
            json_path=first_coordinate["json_path"],
            decoder_value_sha256=first_coordinate["decoder_value_sha256"],
        )
    forged_second = _resealed_item_coordinate(occurrences[1], **changes)
    forged_items = tuple(
        forged_second if item.global_item_ordinal == occurrences[1].global_item_ordinal else item
        for item in items
    )
    forged_partitions = _resealed_projection_partitions(partitions, forged_items, 0)

    with pytest.raises(ValueProjectionError, match="repeats one global ordinal or node owner"):
        ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=_sha("bundle"),
            partitions=forged_partitions,
            items=forged_items,
            **cast("Any", _authority_kwargs(authority)),
        )


def test_live_occurrence_cannot_lose_its_exact_matched_node() -> None:
    _receipt_value, partitions, items, authority = _complete_projection()
    matched = next(
        item
        for item in items
        if item.partition_ordinal == 4
        and item.record_kind == "node"
        and item.coordinate()["matches_result_occurrence"] is True
    )
    forged_matched = _resealed_item_coordinate(matched, matches_result_occurrence=False)
    forged_items = tuple(
        forged_matched if item.global_item_ordinal == matched.global_item_ordinal else item
        for item in items
    )
    forged_partitions = _resealed_projection_partitions(partitions, forged_items, 4)

    with pytest.raises(ValueProjectionError, match="exact value node|matched nodes"):
        ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=_sha("bundle"),
            partitions=forged_partitions,
            items=forged_items,
            **cast("Any", _authority_kwargs(authority)),
        )


def test_live_nested_declaration_parent_cannot_be_erased_by_coordinated_reseal() -> None:
    _receipt_value, partitions, items, authority = _nested_live_projection()
    child_declaration = next(
        item
        for item in items
        if item.partition_ordinal == 1 and item.record_kind == "result_declaration"
    )
    child_occurrence = next(
        item
        for item in items
        if item.partition_ordinal == 1 and item.record_kind == "result_occurrence"
    )
    forged_declaration = _resealed_item_coordinate(
        child_declaration,
        declaration_parent_result_name=None,
        declaration_parent_field_name=None,
    )
    forged_occurrence = _resealed_item_coordinate(
        child_occurrence,
        result_occurrence_parent_result_name=None,
        result_occurrence_parent_result_ordinal=None,
    )
    replacements = {
        child_declaration.global_item_ordinal: forged_declaration,
        child_occurrence.global_item_ordinal: forged_occurrence,
    }
    forged_items = tuple(replacements.get(item.global_item_ordinal, item) for item in items)
    forged_partitions = _resealed_projection_partitions(partitions, forged_items, 1)

    with pytest.raises(ValueProjectionError, match="exact declaration parent edge"):
        ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=_sha("bundle"),
            partitions=forged_partitions,
            items=forged_items,
            **cast("Any", _authority_kwargs(authority)),
        )


def test_live_occurrence_selectors_cannot_swap_nodes_across_partitions() -> None:
    _receipt_value, partitions, items, authority = _nested_live_projection()
    occurrences = {
        item.partition_ordinal: item for item in items if item.record_kind == "result_occurrence"
    }
    nodes = {item.partition_ordinal: item for item in items if item.record_kind == "node"}
    replacements: dict[int, ValueProjectionItemV1] = {}
    for partition_ordinal, occurrence in occurrences.items():
        foreign_node = nodes[1 - partition_ordinal]
        coordinate = foreign_node.coordinate()
        replacements[occurrence.global_item_ordinal] = _resealed_item_coordinate(
            occurrence,
            node_ordinal=coordinate["node_ordinal"],
            json_path=coordinate["json_path"],
            decoder_value_sha256=coordinate["decoder_value_sha256"],
            result_occurrence_presence_kind=foreign_node.presence_kind,
        )
    forged_items = tuple(replacements.get(item.global_item_ordinal, item) for item in items)
    forged_partitions = _resealed_projection_partitions(partitions, forged_items, 0, 1)

    with pytest.raises(ValueProjectionError, match="foreign or cross-partition node"):
        ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=_sha("bundle"),
            partitions=forged_partitions,
            items=forged_items,
            **cast("Any", _authority_kwargs(authority)),
        )


def test_live_concrete_result_occurrence_gap_fails_after_full_receipt_reseal() -> None:
    _receipt_value, partitions, items, authority = _two_occurrence_live_projection()
    forged_nested = _resealed_item_coordinate(
        items[1],
        context_result_occurrence=2,
    )
    forged_items = (items[0], forged_nested, *items[2:])
    forged_partition = _resealed_partition_items(partitions[0], _partition_items(forged_items, 0))

    with pytest.raises(
        ValueProjectionError,
        match="occurrence inventory|exact value node|exact context root node",
    ):
        ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=_sha("bundle"),
            partitions=(forged_partition, partitions[1]),
            items=forged_items,
            **cast("Any", _authority_kwargs(authority)),
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"context_result_name": "Forged"}, "value node or owner context"),
        ({"owner_result_name": "Forged"}, "value node or owner context"),
        ({"row_ordinal": 1}, "outside its declared inventory|value node or owner context"),
    ],
)
def test_live_field_context_only_reseal_fails_closed(
    changes: dict[str, object],
    message: str,
) -> None:
    _receipt_value, partitions, items, authority = _complete_projection()
    forged_field = _resealed_item_coordinate(items[5], **changes)
    forged_items = (*items[:5], forged_field, *items[6:])
    forged_partition = _resealed_partition_items(
        partitions[4],
        _partition_items(forged_items, 4),
    )
    forged_partitions = (*partitions[:4], forged_partition, *partitions[5:])

    with pytest.raises(ValueProjectionError, match=message):
        ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=_sha("bundle"),
            partitions=forged_partitions,
            items=forged_items,
            **cast("Any", _authority_kwargs(authority)),
        )


def test_live_coordinated_parent_and_field_context_reseal_fails_result_join() -> None:
    _receipt_value, partitions, items, authority = _complete_projection()
    forged_root = _resealed_item_coordinate(
        items[3],
        context_result_name="Forged",
    )
    forged_field = _resealed_item_coordinate(
        items[5],
        owner_result_name="Forged",
    )
    forged_items = (
        *items[:3],
        forged_root,
        items[4],
        forged_field,
        *items[6:],
    )
    forged_partition = _resealed_partition_items(
        partitions[4],
        _partition_items(forged_items, 4),
    )
    forged_partitions = (*partitions[:4], forged_partition, *partitions[5:])

    with pytest.raises(ValueProjectionError, match="exact ownership result"):
        ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=_sha("bundle"),
            partitions=forged_partitions,
            items=forged_items,
            **cast("Any", _authority_kwargs(authority)),
        )


def test_live_coordinated_value_node_and_field_context_reseal_fails_result_join() -> None:
    _receipt_value, partitions, items, authority = _complete_projection()
    forged_value_node = _resealed_item_coordinate(
        items[4],
        context_result_name="Forged",
    )
    forged_field = _resealed_item_coordinate(
        items[5],
        context_result_name="Forged",
    )
    forged_items = (
        *items[:4],
        forged_value_node,
        forged_field,
        *items[6:],
    )
    forged_partition = _resealed_partition_items(
        partitions[4],
        _partition_items(forged_items, 4),
    )
    forged_partitions = (*partitions[:4], forged_partition, *partitions[5:])

    with pytest.raises(ValueProjectionError, match="exact ownership result"):
        ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=_sha("bundle"),
            partitions=forged_partitions,
            items=forged_items,
            **cast("Any", _authority_kwargs(authority)),
        )


@pytest.mark.parametrize(
    ("value_state", "value", "structural_value_kind"),
    [
        ("canonical", 7, None),
        ("canonical", {}, None),
        ("structural_container", None, "array"),
    ],
)
def test_fully_resealed_receipt_rejects_live_field_value_drift(
    value_state: str,
    value: object,
    structural_value_kind: str | None,
) -> None:
    _receipt_value, partitions, items, authority = _complete_projection()
    forged_field = _resealed_item_value_shape(
        items[5],
        value_state=value_state,
        value=value,
        structural_value_kind=structural_value_kind,
    )
    forged_items = (*items[:5], forged_field, *items[6:])
    forged_live_partition = _resealed_partition_values(
        partitions[4],
        _partition_items(forged_items, 4),
    )
    forged_partitions = (*partitions[:4], forged_live_partition, *partitions[5:])

    with pytest.raises(ValueProjectionError, match="exact value node"):
        ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=_sha("bundle"),
            partitions=forged_partitions,
            items=forged_items,
            **cast("Any", _authority_kwargs(authority)),
        )


@pytest.mark.parametrize("forged_path", ("$.liveevil", '$["live"]["not_F"]'))
def test_fully_resealed_receipt_rejects_live_field_path_forgery(
    forged_path: str,
) -> None:
    _receipt_value, partitions, items, authority = _complete_projection()
    forged_item = _resealed_item_coordinate(items[5], json_path=forged_path)
    forged_items = (*items[:5], forged_item, *items[6:])
    forged_partition = _resealed_partition_items(
        partitions[4],
        _partition_items(forged_items, 4),
    )
    forged_partitions = (*partitions[:4], forged_partition, *partitions[5:])
    with pytest.raises(ValueProjectionError, match="JSON path|exact value node"):
        ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=_sha("bundle"),
            partitions=forged_partitions,
            items=forged_items,
            **cast("Any", _authority_kwargs(authority)),
        )


def test_fully_resealed_receipt_rejects_shifted_live_root_path() -> None:
    _receipt_value, partitions, items, authority = _complete_projection()
    forged_root = _resealed_item_coordinate(items[3], json_path='$["live"]')
    forged_node = _resealed_item_coordinate(
        items[4],
        json_path='$["live"]["F"]',
        parent_json_path='$["live"]',
    )
    forged_field = _resealed_item_coordinate(items[5], json_path='$["live"]["F"]')
    forged_items = (
        *items[:3],
        forged_root,
        forged_node,
        forged_field,
        *items[6:],
    )
    forged_partition = _resealed_partition_items(
        partitions[4],
        _partition_items(forged_items, 4),
    )
    forged_partitions = (*partitions[:4], forged_partition, *partitions[5:])

    with pytest.raises(ValueProjectionError, match="root node coordinate"):
        ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=_sha("bundle"),
            partitions=forged_partitions,
            items=forged_items,
            **cast("Any", _authority_kwargs(authority)),
        )


def test_aggregate_item_index_has_one_global_item_scan_complexity_sentinel() -> None:
    tree = ast.parse(Path(value_projection.__file__).read_text(encoding="utf-8"))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_validate_aggregate_order"
    )
    partition_loop = next(
        node
        for node in ast.walk(function)
        if isinstance(node, ast.For)
        and any(
            isinstance(name, ast.Name) and name.id == "partitions" for name in ast.walk(node.iter)
        )
    )
    nested_item_scans = [
        node
        for node in ast.walk(partition_loop)
        if isinstance(node, (ast.For, ast.comprehension))
        and any(isinstance(name, ast.Name) and name.id == "items" for name in ast.walk(node.iter))
    ]
    assert nested_item_scans == []
    assert any(
        isinstance(node, ast.Name) and node.id == "partition_item_groups"
        for node in ast.walk(function)
    )


def test_live_semantic_validators_have_no_hidden_sorted_pass() -> None:
    tree = ast.parse(Path(value_projection.__file__).read_text(encoding="utf-8"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    for function_name in (
        "_validate_partition_item_structure",
        "_validate_live_observation_structure",
    ):
        sorted_calls = [
            node
            for node in ast.walk(functions[function_name])
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "sorted"
        ]
        assert sorted_calls == []

    live_function = functions["_validate_live_observation_structure"]
    item_scan_loops = [
        node
        for node in ast.walk(live_function)
        if isinstance(node, ast.For)
        and any(isinstance(name, ast.Name) and name.id == "items" for name in ast.walk(node.iter))
    ]
    for item_scan_loop in item_scan_loops:
        assert not [
            node
            for node in ast.walk(item_scan_loop)
            if node is not item_scan_loop
            and isinstance(node, (ast.For, ast.comprehension))
            and any(
                isinstance(name, ast.Name) and name.id in {"items", "node_items"}
                for name in ast.walk(node.iter)
            )
        ]

    parent_by_node = {
        child: parent
        for parent in ast.walk(live_function)
        for child in ast.iter_child_nodes(parent)
    }
    reconstructed_canonical_calls = [
        node
        for node in ast.walk(live_function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_canonical_json_bytes"
        and any(
            isinstance(name, ast.Name) and name.id == "reconstructed"
            for argument in node.args
            for name in ast.walk(argument)
        )
    ]
    assert len(reconstructed_canonical_calls) == 1
    for call in reconstructed_canonical_calls:
        ancestor = parent_by_node.get(call)
        while ancestor is not None:
            assert not isinstance(ancestor, (ast.For, ast.comprehension))
            ancestor = parent_by_node.get(ancestor)


def _body_receipt(projection: ValueProjectionReceiptV1) -> BodyValueProjectionReceiptV1:
    body_count = projection.parser_input_observation_count
    bodyless_count = projection.bodyless_observation_count
    return BodyValueProjectionReceiptV1.build(
        raw_authority_bundle_sha256=_sha("bundle"),
        body_projection_policy_sha256=_sha("body-policy"),
        body_blob_inventory_sha256=_sha("body-inventory"),
        declared_bodyless_authority_sha256=_sha("bodyless-authority"),
        expected_projection_sha256=projection.projection_sha256,
        projection=projection,
        body_blob_sha256s=tuple(_sha(f"body-{i}") for i in range(body_count)),
        body_blob_readback_sha256s=tuple(_sha(f"body-readback-{i}") for i in range(body_count)),
        parser_input_object_sha256s=tuple(_sha(f"parser-input-{i}") for i in range(body_count)),
        body_blob_byte_count=body_count * 10,
        bodyless_packet_sha256s=tuple(_sha(f"bodyless-{i}") for i in range(bodyless_count)),
        bodyless_readback_sha256s=tuple(
            _sha(f"bodyless-readback-{i}") for i in range(bodyless_count)
        ),
        bodyless_packet_byte_count=bodyless_count * 5,
        observation_source_sha256s=tuple(
            _sha(f"source-{i}") for i in range(projection.observation_count)
        ),
    )


def test_body_wrapper_binds_projection_source_counts_and_roots() -> None:
    projection, _partitions, _items, _authority = _complete_projection()
    body = _body_receipt(projection)

    assert body.body_blob_count == 4
    assert body.bodyless_packet_count == 2
    assert body.observation_source_count == 6
    assert body.projection_sha256 == projection.projection_sha256
    assert body.projection_partition_root_sha256 == projection.partition_root_sha256
    assert body.projection_item_root_sha256 == projection.item_root_sha256


def test_body_wrapper_rejects_foreign_projection_and_source_denominators() -> None:
    projection, _partitions, _items, _authority = _complete_projection()
    kwargs: dict[str, object] = {
        "raw_authority_bundle_sha256": _sha("bundle"),
        "body_projection_policy_sha256": _sha("body-policy"),
        "body_blob_inventory_sha256": _sha("body-inventory"),
        "declared_bodyless_authority_sha256": _sha("bodyless-authority"),
        "expected_projection_sha256": _sha("foreign-projection"),
        "projection": projection,
        "body_blob_sha256s": tuple(_sha(f"body-{i}") for i in range(4)),
        "body_blob_readback_sha256s": tuple(_sha(f"body-r-{i}") for i in range(4)),
        "parser_input_object_sha256s": tuple(_sha(f"input-{i}") for i in range(4)),
        "body_blob_byte_count": 4,
        "bodyless_packet_sha256s": (_sha("packet-0"), _sha("packet-1")),
        "bodyless_readback_sha256s": (_sha("packet-r-0"), _sha("packet-r-1")),
        "bodyless_packet_byte_count": 2,
        "observation_source_sha256s": tuple(_sha(f"source-{i}") for i in range(6)),
    }
    with pytest.raises(ValueProjectionError, match="sources differ"):
        BodyValueProjectionReceiptV1.build(**cast("Any", kwargs))
    kwargs["expected_projection_sha256"] = projection.projection_sha256
    kwargs["body_blob_readback_sha256s"] = tuple(_sha(f"body-r-{i}") for i in range(3))
    with pytest.raises(ValueProjectionError, match="sources differ"):
        BodyValueProjectionReceiptV1.build(**cast("Any", kwargs))


def test_body_wrapper_pin_preflight_precedes_projection_access() -> None:
    class Bomb:
        def __getattribute__(self, name: str) -> object:
            raise AssertionError(name)

    with pytest.raises(ValueProjectionError, match="lowercase full SHA-256"):
        BodyValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256="bad",
            body_projection_policy_sha256=_sha("body-policy"),
            body_blob_inventory_sha256=_sha("body-inventory"),
            declared_bodyless_authority_sha256=_sha("bodyless-authority"),
            expected_projection_sha256=_sha("projection"),
            projection=cast("Any", Bomb()),
            body_blob_sha256s=(),
            body_blob_readback_sha256s=(),
            parser_input_object_sha256s=(),
            body_blob_byte_count=0,
            bodyless_packet_sha256s=(),
            bodyless_readback_sha256s=(),
            bodyless_packet_byte_count=0,
            observation_source_sha256s=(),
        )


def test_all_shared_builders_preflight_external_pins_before_child_traversal() -> None:
    class Bomb(dict[str, object]):
        def __iter__(self) -> Any:
            raise AssertionError("coordinate traversed")

        def items(self) -> Any:
            raise AssertionError("coordinate traversed")

    with pytest.raises(ValueProjectionError, match="lowercase full SHA-256"):
        ValueProjectionItemV1.build(
            raw_authority_bundle_sha256="bad",
            ownership_binding_sha256=_sha("binding"),
            ownership_binding_ordinal=0,
            source_record_sha256=_sha("record"),
            observation_record_sha256=_sha("observation-record"),
            observation_sha256=_sha("observation"),
            observation_ordinal=0,
            ownership_partition_sha256=_sha("ownership-partition"),
            partition_ordinal=0,
            unit_sha256=_sha("unit"),
            unit_ordinal=0,
            assignment_sha256=_sha("assignment"),
            source_input_kind="parser_input_body",
            representation_kind="rectangular_result_cells_v1",
            unit_kind="result_occurrence",
            occurrence_sha256=_sha("occurrence"),
            occurrence_ordinal=0,
            global_item_ordinal=0,
            partition_item_ordinal=0,
            record_kind="cell",
            coordinate=cast("Any", Bomb()),
            value=1,
        )
    with pytest.raises(ValueProjectionError, match="lowercase full SHA-256"):
        ValueProjectionPartitionV1.build(
            raw_authority_bundle_sha256="bad",
            ownership_partition_sha256=_sha("ownership-partition"),
            observation_record_sha256=_sha("observation-record"),
            observation_sha256=_sha("observation"),
            observation_ordinal=0,
            partition_ordinal=0,
            observation_partition_ordinal=0,
            partition_kind="response_residual",
            source_input_kind="parser_input_body",
            items=cast("Any", (object(),)),
        )
    with pytest.raises(ValueProjectionError, match="lowercase full SHA-256"):
        ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256="bad",
            ownership_receipt_row=cast("Any", Bomb()),
            expected_unit_rows=cast("Any", (object(),)),
            representation_assignment_rows=(),
            ownership_observation_rows=(),
            ownership_partition_rows=(),
            ownership_binding_rows=(),
            partitions=cast("Any", (object(),)),
            items=(),
        )


def test_empty_body_wrapper_requires_zero_byte_counts() -> None:
    projection = _receipt(partitions=(), items=())
    body = _body_receipt(projection)
    assert body.body_blob_byte_count == 0
    assert body.bodyless_packet_byte_count == 0
    row = body.to_row()
    row["body_blob_byte_count"] = 1
    with pytest.raises(ValueProjectionError, match="body-byte zero proof"):
        BodyValueProjectionReceiptV1.from_row(
            _reseal_row(
                row,
                dto=BodyValueProjectionReceiptV1,
                digest_field="receipt_sha256",
            )
        )


def test_receipt_counter_and_root_reseals_fail_algebra() -> None:
    receipt, _partitions, _items, _authority = _complete_projection()
    row = receipt.to_row()
    row["response_fixed_zero_item_count"] = 1
    with pytest.raises(ValueProjectionError, match="aggregate denominators"):
        ValueProjectionReceiptV1.from_row(
            _reseal_row(row, dto=ValueProjectionReceiptV1, digest_field="projection_sha256")
        )
    empty = _receipt(partitions=(), items=())
    row = empty.to_row()
    row["item_root_sha256"] = _sha("foreign-empty-root")
    with pytest.raises(ValueProjectionError, match="zero root"):
        ValueProjectionReceiptV1.from_row(
            _reseal_row(row, dto=ValueProjectionReceiptV1, digest_field="projection_sha256")
        )


def test_structural_counts_reject_coordinated_partition_and_receipt_reseals() -> None:
    receipt, partitions, items, authority = _complete_projection()
    partition_row = partitions[4].to_row()
    partition_row["present_count"] = 1
    partition_row["empty_object_count"] = 0
    partition_row["structural_value_count"] = 1
    partition_row["canonical_value_byte_count"] = 0
    forged_partition = ValueProjectionPartitionV1.from_row(
        _reseal_row(
            partition_row,
            dto=ValueProjectionPartitionV1,
            digest_field="partition_sha256",
        )
    )
    forged_partitions = (*partitions[:4], forged_partition, *partitions[5:])
    with pytest.raises(ValueProjectionError, match="exact item reconstruction"):
        ValueProjectionReceiptV1.build(
            raw_authority_bundle_sha256=_sha("bundle"),
            partitions=forged_partitions,
            items=items,
            **cast("Any", _authority_kwargs(authority)),
        )

    receipt_row = receipt.to_row()
    receipt_row["structural_value_count"] = (
        receipt.array_value_count + receipt.object_value_count + 1
    )
    with pytest.raises(ValueProjectionError, match="aggregate denominators"):
        ValueProjectionReceiptV1.from_row(
            _reseal_row(
                receipt_row,
                dto=ValueProjectionReceiptV1,
                digest_field="projection_sha256",
            )
        )


def test_length_framed_roots_bind_kind_bundle_order_and_count() -> None:
    values = (_sha("a"), _sha("b"))
    base = value_projection._length_framed_root(
        kind="root-a",
        raw_authority_bundle_sha256=_sha("bundle"),
        item_sha256s=values,
        maximum=2,
    )
    assert base != value_projection._length_framed_root(
        kind="root-a",
        raw_authority_bundle_sha256=_sha("bundle"),
        item_sha256s=tuple(reversed(values)),
        maximum=2,
    )
    assert base != value_projection._length_framed_root(
        kind="root-b",
        raw_authority_bundle_sha256=_sha("bundle"),
        item_sha256s=values,
        maximum=2,
    )
    assert base != value_projection._length_framed_root(
        kind="root-a",
        raw_authority_bundle_sha256=_sha("other-bundle"),
        item_sha256s=values,
        maximum=2,
    )
    assert base != value_projection._length_framed_root(
        kind="root-a",
        raw_authority_bundle_sha256=_sha("bundle"),
        item_sha256s=values[:1],
        maximum=2,
    )


def test_source_is_a_stdlib_only_leaf_with_forbidden_import_and_attribute_gate() -> None:
    source_path = Path(value_projection.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    allowed_import_roots = {
        "__future__",
        "dataclasses",
        "hashlib",
        "json",
        "math",
        "re",
        "typing",
    }
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported_roots.add(cast("str", node.module).split(".", 1)[0])
    assert imported_roots <= allowed_import_roots
    forbidden_names = {
        "nbadb",
        "polars",
        "pandera",
        "pyarrow",
        "extract",
        "orchestrate",
        "staging",
        "value_receipts",
        "conditional_row_receipts",
    }
    assert imported_roots.isdisjoint(forbidden_names)
    assert not {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr in {"value_receipts", "conditional_row_receipts"}
    }
