"""Production adapter from frozen value authorities to a projection plan.

This module contains joins only.  It does not decode provider payloads and it
does not import extraction, orchestration, schema, or publication surfaces.
All supplied authorities are externally pinned and replayed before their
children are used to allocate the value-free plan.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from typing import Final, Literal, Never, cast

from nbadb.contracts.body_blob_inventory import (
    BodyBlobFileReadbackReceiptV1,
    BodyBlobInventoryReadbackReceiptV1,
    BodyBlobObservationReadbackReceiptV1,
)
from nbadb.contracts.declared_bodyless_packet_types import (
    DeclaredBodylessPacketReadbackReceiptV1,
    DeclaredBodylessPacketV1,
    validate_declared_bodyless_packet_identity,
)
from nbadb.contracts.live_lossless_value_authority import (
    LiveLosslessNodeRecordV1,
    LiveLosslessValueAuthorityReceiptV1,
    LiveLosslessValueAuthorityV1,
)
from nbadb.contracts.lossless_ownership import (
    LosslessObservationOwnershipV1,
    LosslessOwnershipAuthorityV1,
    LosslessOwnershipBindingV1,
    LosslessOwnershipPartitionV1,
    LosslessOwnershipReceiptV1,
)
from nbadb.contracts.public_value_authority_adapter import (
    build_public_value_ownership_authority,
)
from nbadb.contracts.public_value_types import (
    ExpectedValueUnitInventoryV1,
    ExpectedValueUnitV1,
    ValueRepresentationAssignmentV1,
)
from nbadb.contracts.raw_request_authority import (
    MAX_AUTHORITY_ROWS,
    MAX_JSON_NODES,
    ObservationRouteLandingV2,
    ParserInputObjectV2,
    RawRequestAuthorityBundleV2,
    RequestAttemptIdentityV2,
    RequestObservationV2,
    ResultOccurrenceV2,
    validate_raw_request_authority_bundle,
)
from nbadb.contracts.raw_result_cell_authority import (
    RawNbaApiResultCellV2,
    RawResultCellAuthorityReceiptV2,
    RawResultCellPublicTableProofV2,
    validate_raw_result_cell_authority_receipt,
)
from nbadb.contracts.stats_lossless_value_authority import (
    StatsLosslessManifestV1,
    StatsLosslessRecordV1,
    StatsLosslessResultV1,
    StatsLosslessValueAuthorityReceiptV1,
    StatsLosslessValueAuthorityV1,
)
from nbadb.contracts.value_projection_plan import (
    ValueProjectionPlanAssignmentV1,
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

__all__ = [
    "ValueProjectionPlanBuilderError",
    "build_value_projection_plan",
]


_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_MAX_AUTHORITIES: Final = 100_000
_MAX_PARTITIONS: Final = _MAX_AUTHORITIES * 2
_MAX_SOURCE_RECORDS: Final = 14_000_000


class ValueProjectionPlanBuilderError(ValueError):
    """The frozen authorities cannot form one exact projection plan."""


def _fail(message: str) -> Never:
    raise ValueProjectionPlanBuilderError(message)


def _sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be one exact lowercase SHA-256")
    return value


def _pin_tuple(value: object, *, label: str) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) > _MAX_AUTHORITIES:
        _fail(f"{label} must be one bounded exact tuple")
    return tuple(_sha256(item, label=label) for item in value)


def _semantic_key(observation: RequestObservationV2) -> tuple[object, ...]:
    attempt = observation.attempt
    return (
        attempt.logical_invocation_sha256,
        attempt.semantic_request_sha256,
        attempt.provider_call_ordinal,
        0 if attempt.page_ordinal is None else 1,
        0 if attempt.page_ordinal is None else attempt.page_ordinal,
        attempt.provider_call_role,
        attempt.provider_call_sha256,
        attempt.retry_ordinal,
        attempt.request_ordinal,
        attempt.observation_sha256,
    )


def _preflight_raw(value: RawRequestAuthorityBundleV2) -> None:
    if (
        type(value.objects) is not tuple
        or len(value.objects) > MAX_AUTHORITY_ROWS
        or any(type(item) is not ParserInputObjectV2 for item in value.objects)
        or type(value.observations) is not tuple
        or len(value.observations) > MAX_AUTHORITY_ROWS
        or any(type(item) is not RequestObservationV2 for item in value.observations)
        or any(type(item.attempt) is not RequestAttemptIdentityV2 for item in value.observations)
        or type(value.occurrences) is not tuple
        or len(value.occurrences) > MAX_AUTHORITY_ROWS
        or any(
            type(item) is not ResultOccurrenceV2
            or type(item.ordered_headers_json) is not str
            or type(item.ordered_headers_sha256) is not str
            or type(item.header_count) is not int
            for item in value.occurrences
        )
        or type(value.landings) is not tuple
        or len(value.landings) > MAX_AUTHORITY_ROWS
        or any(type(item) is not ObservationRouteLandingV2 for item in value.landings)
    ):
        _fail("Raw Authority V2 contains a foreign exact child type")


def _preflight_result_receipt(value: RawResultCellAuthorityReceiptV2) -> None:
    if (
        type(value.public_table_proof) is not RawResultCellPublicTableProofV2
        or type(value.public_table_proof.cells) is not tuple
        or len(value.public_table_proof.cells) > MAX_JSON_NODES
        or any(type(item) is not RawNbaApiResultCellV2 for item in value.public_table_proof.cells)
    ):
        _fail("result-cell authority contains a foreign exact child type")


def _preflight_stats(value: StatsLosslessValueAuthorityV1) -> None:
    if (
        type(value.receipt) is not StatsLosslessValueAuthorityReceiptV1
        or type(value.manifest) is not StatsLosslessManifestV1
        or type(value.expected_unit_inventory) is not ExpectedValueUnitInventoryV1
        or type(value.expected_unit_inventory.units) is not tuple
        or len(value.expected_unit_inventory.units) > _MAX_AUTHORITIES
        or any(
            type(item) is not ExpectedValueUnitV1 for item in value.expected_unit_inventory.units
        )
        or type(value.representation_assignments) is not tuple
        or len(value.representation_assignments) > _MAX_AUTHORITIES
        or any(
            type(item) is not ValueRepresentationAssignmentV1
            for item in value.representation_assignments
        )
        or type(value.results) is not tuple
        or len(value.results) > _MAX_AUTHORITIES
        or any(type(item) is not StatsLosslessResultV1 for item in value.results)
        or type(value.records) is not tuple
        or len(value.records) > _MAX_SOURCE_RECORDS
        or any(type(item) is not StatsLosslessRecordV1 for item in value.records)
    ):
        _fail("stats-lossless authority contains a foreign exact child type")


def _preflight_live(value: LiveLosslessValueAuthorityV1) -> None:
    if (
        type(value.receipt) is not LiveLosslessValueAuthorityReceiptV1
        or type(value.expected_units) is not ExpectedValueUnitInventoryV1
        or type(value.expected_units.units) is not tuple
        or len(value.expected_units.units) > _MAX_AUTHORITIES
        or any(type(item) is not ExpectedValueUnitV1 for item in value.expected_units.units)
        or type(value.representation_assignments) is not tuple
        or len(value.representation_assignments) > _MAX_AUTHORITIES
        or any(
            type(item) is not ValueRepresentationAssignmentV1
            for item in value.representation_assignments
        )
        or type(value.records) is not tuple
        or len(value.records) > _MAX_SOURCE_RECORDS
        or any(type(item) is not LiveLosslessNodeRecordV1 for item in value.records)
    ):
        _fail("live-lossless authority contains a foreign exact child type")


def _preflight_ownership(value: LosslessOwnershipAuthorityV1) -> None:
    if (
        type(value.receipt) is not LosslessOwnershipReceiptV1
        or type(value.expected_unit_inventory) is not ExpectedValueUnitInventoryV1
        or type(value.expected_unit_inventory.units) is not tuple
        or len(value.expected_unit_inventory.units) > _MAX_AUTHORITIES
        or any(
            type(item) is not ExpectedValueUnitV1 for item in value.expected_unit_inventory.units
        )
        or type(value.representation_assignments) is not tuple
        or len(value.representation_assignments) > _MAX_AUTHORITIES
        or any(
            type(item) is not ValueRepresentationAssignmentV1
            for item in value.representation_assignments
        )
        or type(value.observations) is not tuple
        or len(value.observations) > _MAX_AUTHORITIES
        or any(type(item) is not LosslessObservationOwnershipV1 for item in value.observations)
        or type(value.partitions) is not tuple
        or len(value.partitions) > _MAX_PARTITIONS
        or any(type(item) is not LosslessOwnershipPartitionV1 for item in value.partitions)
        or type(value.bindings) is not tuple
        or len(value.bindings) > _MAX_SOURCE_RECORDS
        or any(type(item) is not LosslessOwnershipBindingV1 for item in value.bindings)
    ):
        _fail("lossless-ownership authority contains a foreign exact child type")


def _preflight_body_readback(value: BodyBlobInventoryReadbackReceiptV1) -> None:
    if (
        type(value.file_readbacks) is not tuple
        or len(value.file_readbacks) > _MAX_AUTHORITIES
        or any(type(item) is not BodyBlobFileReadbackReceiptV1 for item in value.file_readbacks)
        or type(value.observation_readbacks) is not tuple
        or len(value.observation_readbacks) > _MAX_AUTHORITIES
        or any(
            type(item) is not BodyBlobObservationReadbackReceiptV1
            for item in value.observation_readbacks
        )
    ):
        _fail("body-blob readback contains a foreign exact child type")


def _replay_dataclass[T](value: T, exact_type: type[T]) -> T:
    return exact_type(**{item.name: getattr(value, item.name) for item in fields(exact_type)})


def _replay_ownership(value: LosslessOwnershipAuthorityV1) -> LosslessOwnershipAuthorityV1:
    return LosslessOwnershipAuthorityV1(
        receipt=LosslessOwnershipReceiptV1.from_row(value.receipt.to_row()),
        expected_unit_inventory=ExpectedValueUnitInventoryV1.from_row(
            value.expected_unit_inventory.to_row()
        ),
        representation_assignments=tuple(
            ValueRepresentationAssignmentV1.from_row(item.to_row())
            for item in value.representation_assignments
        ),
        observations=tuple(
            LosslessObservationOwnershipV1.from_row(item.to_row()) for item in value.observations
        ),
        partitions=tuple(
            LosslessOwnershipPartitionV1.from_row(item.to_row()) for item in value.partitions
        ),
        bindings=tuple(
            LosslessOwnershipBindingV1.from_row(item.to_row()) for item in value.bindings
        ),
    )


def _replay_body_readback(
    value: BodyBlobInventoryReadbackReceiptV1,
) -> BodyBlobInventoryReadbackReceiptV1:
    return BodyBlobInventoryReadbackReceiptV1(
        schema_version=value.schema_version,
        kind=value.kind,
        raw_authority_bundle_sha256=value.raw_authority_bundle_sha256,
        inventory_sha256=value.inventory_sha256,
        store_namespace_sha256=value.store_namespace_sha256,
        file_readbacks=tuple(
            _replay_dataclass(child, BodyBlobFileReadbackReceiptV1)
            for child in value.file_readbacks
        ),
        file_readback_count=value.file_readback_count,
        file_readback_root_sha256=value.file_readback_root_sha256,
        observation_readbacks=tuple(
            _replay_dataclass(child, BodyBlobObservationReadbackReceiptV1)
            for child in value.observation_readbacks
        ),
        observation_readback_count=value.observation_readback_count,
        observation_readback_root_sha256=value.observation_readback_root_sha256,
        selected_observation_readback_count=value.selected_observation_readback_count,
        selected_observation_readback_root_sha256=(value.selected_observation_readback_root_sha256),
        incomplete_observation_readback_count=value.incomplete_observation_readback_count,
        incomplete_observation_readback_root_sha256=(
            value.incomplete_observation_readback_root_sha256
        ),
        total_readback_bytes=value.total_readback_bytes,
        receipt_sha256=value.receipt_sha256,
    )


@dataclass(frozen=True, slots=True)
class _SourceDescriptor:
    observation_record_sha256: str
    observation_sha256: str
    owner_kind: Literal["result_occurrence", "response_residual"]
    occurrence_sha256: str | None
    representation_kind: str
    source_relation_kind: Literal[
        "result_cell_v1", "stats_lossless_record_v1", "live_lossless_node_v1"
    ]
    projection_record_kind: str


def _add_source(
    index: dict[str, _SourceDescriptor],
    source_record_sha256: str,
    descriptor: _SourceDescriptor,
) -> None:
    if source_record_sha256 in index:
        _fail("public source authorities duplicate one source-record identity")
    if len(index) >= _MAX_SOURCE_RECORDS:
        _fail("public source-record denominator exceeds its bound")
    index[source_record_sha256] = descriptor


def _source_index(
    *,
    result_receipt: RawResultCellAuthorityReceiptV2,
    stats_authorities: tuple[StatsLosslessValueAuthorityV1, ...],
    live_authority: LiveLosslessValueAuthorityV1,
    occurrence_to_observation: dict[str, RequestObservationV2],
) -> tuple[dict[str, _SourceDescriptor], dict[str, StatsLosslessResultV1]]:
    index: dict[str, _SourceDescriptor] = {}
    stats_results: dict[str, StatsLosslessResultV1] = {}
    for cell in result_receipt.public_table_proof.cells:
        observation = occurrence_to_observation.get(cell.occurrence_sha256)
        if observation is None or cell.observation_sha256 != observation.attempt.observation_sha256:
            _fail("result-cell source references a foreign Raw occurrence")
        _add_source(
            index,
            cell.cell_sha256,
            _SourceDescriptor(
                observation_record_sha256=observation.observation_record_sha256,
                observation_sha256=cell.observation_sha256,
                owner_kind="result_occurrence",
                occurrence_sha256=cell.occurrence_sha256,
                representation_kind="rectangular_result_cells_v1",
                source_relation_kind="result_cell_v1",
                projection_record_kind="cell",
            ),
        )
    for authority in stats_authorities:
        for result in authority.results:
            if result.occurrence_sha256 in stats_results:
                _fail("stats-lossless authorities duplicate one result occurrence")
            if len(stats_results) >= _MAX_AUTHORITIES:
                _fail("stats-lossless result denominator exceeds its bound")
            stats_results[result.occurrence_sha256] = result
        for record in authority.records:
            _add_source(
                index,
                record.record_sha256,
                _SourceDescriptor(
                    observation_record_sha256=record.observation_record_sha256,
                    observation_sha256=record.observation_sha256,
                    owner_kind=record.owner_kind,
                    occurrence_sha256=record.occurrence_sha256,
                    representation_kind=record.representation_kind,
                    source_relation_kind="stats_lossless_record_v1",
                    projection_record_kind=record.record_kind,
                ),
            )
    for record in live_authority.records:
        _add_source(
            index,
            record.source_item_sha256,
            _SourceDescriptor(
                observation_record_sha256=record.observation_record_sha256,
                observation_sha256=record.observation_sha256,
                owner_kind=record.ownership_kind,
                occurrence_sha256=record.raw_occurrence_sha256,
                representation_kind=record.representation_kind,
                source_relation_kind="live_lossless_node_v1",
                projection_record_kind=record.record_kind,
            ),
        )
    if len(index) > _MAX_SOURCE_RECORDS:
        _fail("public source-record denominator exceeds its bound")
    return index, stats_results


def _observation_sources(
    *,
    bundle: RawRequestAuthorityBundleV2,
    ownership: LosslessOwnershipAuthorityV1,
    body_readback: BodyBlobInventoryReadbackReceiptV1,
    packets: tuple[DeclaredBodylessPacketV1, ...],
    bodyless_readbacks: tuple[DeclaredBodylessPacketReadbackReceiptV1, ...],
) -> tuple[ValueProjectionPlanObservationSourceV1, ...]:
    expected_bodyless_order = tuple(
        item.observation_sha256
        for item in ownership.observations
        if item.source_input_kind == "declared_bodyless_packet"
    )
    if tuple(item.observation_sha256 for item in packets) != expected_bodyless_order:
        _fail("declared-bodyless packets differ from canonical bundle observation order")
    if tuple(item.observation_sha256 for item in bodyless_readbacks) != expected_bodyless_order:
        _fail("declared-bodyless readbacks differ from canonical bundle observation order")
    raw_order = tuple(sorted(bundle.observations, key=_semantic_key))
    raw_position = {
        item.attempt.observation_sha256: ordinal for ordinal, item in enumerate(raw_order)
    }
    raw_by_observation = {item.attempt.observation_sha256: item for item in bundle.observations}
    object_by_sha = {item.object_sha256: item for item in bundle.objects}
    file_by_receipt = {item.receipt_sha256: item for item in body_readback.file_readbacks}
    parser_sources: dict[
        str,
        tuple[BodyBlobObservationReadbackReceiptV1, BodyBlobFileReadbackReceiptV1],
    ] = {}
    for readback in body_readback.observation_readbacks:
        observation = raw_by_observation.get(readback.observation_sha256)
        file_readback = file_by_receipt.get(readback.file_readback_receipt_sha256)
        if observation is not None and observation.lifecycle == "selected_terminal":
            expected_selection = "selected_terminal"
        elif (
            observation is not None
            and observation.lifecycle == "incomplete"
            and observation.outcome == "downstream_incomplete"
        ):
            expected_selection = "downstream_incomplete"
        else:
            _fail("body-blob readback references a non-admissible Raw observation")
        if (
            observation is None
            or file_readback is None
            or readback.observation_record_sha256 != observation.observation_record_sha256
            or readback.observation_ordinal != raw_position[readback.observation_sha256]
            or readback.selection != expected_selection
            or observation.body_disposition != "public_parser_input"
            or observation.body_object_sha256 != file_readback.parser_input_object_sha256
            or readback.blob_sha256 != file_readback.blob_sha256
        ):
            _fail("body-blob readback differs from its exact Raw observation")
        parser_object = object_by_sha.get(file_readback.parser_input_object_sha256)
        if (
            parser_object is None
            or file_readback.raw_authority_bundle_sha256 != bundle.bundle_sha256
            or file_readback.response_sha256 != parser_object.response_sha256
            or file_readback.uncompressed_bytes != parser_object.uncompressed_bytes
            or file_readback.stored_sha256 != parser_object.stored_sha256
            or file_readback.stored_bytes != parser_object.stored_bytes
            or file_readback.readback_sha256 != parser_object.stored_sha256
            or file_readback.readback_bytes != parser_object.stored_bytes
        ):
            _fail("body-blob file readback differs from its Raw parser-input object")
        if readback.selection == "selected_terminal":
            if readback.observation_sha256 in parser_sources:
                _fail("body-blob readback duplicates one selected observation")
            parser_sources[readback.observation_sha256] = (readback, file_readback)

    packet_sources: dict[
        str, tuple[DeclaredBodylessPacketV1, DeclaredBodylessPacketReadbackReceiptV1]
    ] = {}
    for packet, readback in zip(packets, bodyless_readbacks, strict=True):
        observation = raw_by_observation.get(packet.observation_sha256)
        if (
            observation is None
            or observation.lifecycle != "selected_terminal"
            or observation.body_disposition != "declared_bodyless"
            or observation.attempt.source_family != "static"
            or packet.observation_record_sha256 != observation.observation_record_sha256
            or packet.attempt_sha256 != observation.attempt.attempt_sha256
            or packet.logical_receipt_sha256 != observation.logical_receipt_sha256
            or packet.endpoint_id != observation.attempt.endpoint_id
            or packet.endpoint_contract_sha256 != observation.attempt.endpoint_contract_sha256
            or packet.provider_authority_sha256 != observation.attempt.provider_authority_sha256
            or packet.source_sha != observation.attempt.source_sha
            or packet.run_id != observation.attempt.run_id
            or packet.run_attempt != observation.attempt.run_attempt
            or packet.chain_id != observation.attempt.chain_id
            or packet.lane_id != observation.attempt.lane_id
            or readback.observation_sha256 != packet.observation_sha256
            or readback.observation_record_sha256 != packet.observation_record_sha256
            or readback.packet_authority_sha256 != packet.packet_authority_sha256
            or readback.public_resource_name != packet.public_resource_name
            or readback.frozen_static_schema_sha256 != packet.frozen_static_schema_sha256
            or readback.stored_payload_sha256 != packet.stored_payload_sha256
            or readback.stored_payload_length != packet.stored_payload_length
            or readback.readback_payload_sha256 != packet.stored_payload_sha256
            or readback.readback_payload_length != packet.stored_payload_length
            or (
                readback.field_count,
                readback.row_count,
                readback.cell_count,
                readback.schema_root_sha256,
                readback.content_root_sha256,
                readback.row_root_sha256,
                readback.cell_root_sha256,
            )
            != (
                packet.field_count,
                packet.row_count,
                packet.cell_count,
                packet.schema_root_sha256,
                packet.content_root_sha256,
                packet.row_root_sha256,
                packet.cell_root_sha256,
            )
        ):
            _fail("declared-bodyless readback differs from its exact Raw observation")
        if packet.observation_sha256 in packet_sources:
            _fail("declared-bodyless authority duplicates one selected observation")
        packet_sources[packet.observation_sha256] = (packet, readback)

    sources: list[ValueProjectionPlanObservationSourceV1] = []
    for owner in ownership.observations:
        observation = raw_by_observation.get(owner.observation_sha256)
        if (
            observation is None
            or observation.observation_record_sha256 != owner.observation_record_sha256
            or observation.attempt.source_family not in {"stats", "live", "static"}
        ):
            _fail("ownership observation differs from its Raw source")
        if owner.source_input_kind == "parser_input_body":
            admitted = parser_sources.pop(owner.observation_sha256, None)
            if admitted is None:
                _fail("selected parser-input observation lacks one body-blob readback")
            observation_readback, file_readback = admitted
            source = ValueProjectionPlanObservationSourceV1.build(
                raw_authority_bundle_sha256=bundle.bundle_sha256,
                observation_record_sha256=owner.observation_record_sha256,
                observation_sha256=owner.observation_sha256,
                observation_ordinal=owner.observation_ordinal,
                source_input_kind="parser_input_body",
                source_family=observation.attempt.source_family,
                body_blob_sha256=file_readback.blob_sha256,
                body_blob_readback_sha256=observation_readback.receipt_sha256,
                parser_input_object_sha256=file_readback.parser_input_object_sha256,
                payload_sha256=file_readback.response_sha256,
                payload_byte_count=file_readback.uncompressed_bytes,
            )
        else:
            admitted_packet = packet_sources.pop(owner.observation_sha256, None)
            if admitted_packet is None:
                _fail("selected bodyless observation lacks one packet readback")
            packet, readback = admitted_packet
            source = ValueProjectionPlanObservationSourceV1.build(
                raw_authority_bundle_sha256=bundle.bundle_sha256,
                observation_record_sha256=owner.observation_record_sha256,
                observation_sha256=owner.observation_sha256,
                observation_ordinal=owner.observation_ordinal,
                source_input_kind="declared_bodyless_packet",
                source_family="static",
                bodyless_packet_sha256=packet.packet_authority_sha256,
                bodyless_readback_sha256=readback.receipt_sha256,
                payload_sha256=packet.uncompressed_packet_sha256,
                payload_byte_count=packet.uncompressed_packet_length,
            )
        sources.append(source)
    if parser_sources or packet_sources:
        _fail("observation source authorities contain an orphan selected source")
    return tuple(sources)


def _occurrence_plans(
    *,
    bundle: RawRequestAuthorityBundleV2,
    ownership: LosslessOwnershipAuthorityV1,
    stats_results: dict[str, StatsLosslessResultV1],
) -> tuple[ValueProjectionPlanOccurrenceV1, ...]:
    selected_observations = {item.observation_sha256 for item in ownership.observations}
    raw_occurrences = {
        item.occurrence_sha256: item
        for item in bundle.occurrences
        if item.observation_sha256 in selected_observations
    }
    assignments = {item.assignment_sha256: item for item in ownership.representation_assignments}
    plans: list[ValueProjectionPlanOccurrenceV1] = []
    for partition in ownership.partitions:
        if partition.partition_kind != "result_occurrence":
            continue
        occurrence = raw_occurrences.pop(cast("str", partition.occurrence_sha256), None)
        assignment = assignments.get(cast("str", partition.assignment_sha256))
        if occurrence is None or assignment is None:
            _fail("result partition lacks its exact Raw occurrence or assignment")
        stats_result = stats_results.pop(occurrence.occurrence_sha256, None)
        expected_result_ordinal = None
        if assignment.representation_kind == "stats_lossless_records_v1":
            if stats_result is None:
                _fail("stats-lossless occurrence lacks its exact result authority")
            expected_result_ordinal = stats_result.expected_result_ordinal
        elif stats_result is not None:
            _fail("stats-lossless result authority owns a differently represented occurrence")
        plans.append(
            ValueProjectionPlanOccurrenceV1.build(
                raw_authority_bundle_sha256=bundle.bundle_sha256,
                occurrence_plan_ordinal=len(plans),
                observation_record_sha256=partition.observation_record_sha256,
                observation_sha256=partition.observation_sha256,
                observation_ordinal=partition.observation_ordinal,
                partition_sha256=partition.partition_sha256,
                partition_ordinal=partition.partition_ordinal,
                occurrence_sha256=occurrence.occurrence_sha256,
                occurrence_ordinal=occurrence.occurrence_ordinal,
                unit_sha256=cast("str", partition.unit_sha256),
                unit_ordinal=cast("int", partition.unit_ordinal),
                assignment_sha256=cast("str", partition.assignment_sha256),
                source_input_kind=assignment.source_input_kind,
                representation_kind=assignment.representation_kind,
                result_name=occurrence.result_name,
                result_duplicate_ordinal=occurrence.duplicate_name_ordinal,
                provider_result_ordinal=occurrence.provider_result_ordinal,
                expected_result_ordinal=expected_result_ordinal,
                canonical_result_ordinal=occurrence.canonical_result_ordinal,
                result_path=occurrence.json_path,
                container_kind=occurrence.container_kind,
                result_presence=occurrence.presence,
                ordered_headers_json=occurrence.ordered_headers_json,
                ordered_headers_sha256=occurrence.ordered_headers_sha256,
                header_count=occurrence.header_count,
                row_count=occurrence.row_count,
                cell_count=occurrence.cell_count,
                node_count=occurrence.node_count,
                container_count=occurrence.container_count,
                missing_count=occurrence.missing_count,
                null_count=occurrence.null_count,
                parent_state_sha256=occurrence.parent_state_sha256,
                representation_output_sha256=occurrence.output_sha256,
            )
        )
    if raw_occurrences:
        _fail("Raw occurrence denominator contains an unplanned selected occurrence")
    if stats_results:
        _fail("stats-lossless result authority contains an orphan occurrence")
    return tuple(plans)


def _source_record_plans(
    *,
    ownership: LosslessOwnershipAuthorityV1,
    source_index: dict[str, _SourceDescriptor],
) -> tuple[ValueProjectionPlanSourceRecordV1, ...]:
    partitions = {item.partition_ordinal: item for item in ownership.partitions}
    assignments = {item.assignment_sha256: item for item in ownership.representation_assignments}
    plans: list[ValueProjectionPlanSourceRecordV1] = []
    for binding in ownership.bindings:
        descriptor = source_index.pop(binding.source_record_sha256, None)
        partition = partitions.get(binding.partition_ordinal)
        assignment = assignments.get(binding.assignment_sha256)
        if descriptor is None or partition is None or assignment is None:
            _fail("ownership binding lacks one exact source, partition, or assignment")
        if (
            descriptor.observation_record_sha256 != binding.observation_record_sha256
            or descriptor.observation_sha256 != binding.observation_sha256
            or descriptor.owner_kind != binding.ownership_kind
            or descriptor.occurrence_sha256 != binding.occurrence_sha256
            or descriptor.representation_kind != assignment.representation_kind
            or partition.unit_sha256 != binding.unit_sha256
            or partition.assignment_sha256 != binding.assignment_sha256
        ):
            _fail("public source record differs from its exact ownership binding")
        plans.append(
            ValueProjectionPlanSourceRecordV1.build(
                raw_authority_bundle_sha256=binding.raw_authority_bundle_sha256,
                source_record_plan_ordinal=len(plans),
                observation_record_sha256=binding.observation_record_sha256,
                observation_sha256=binding.observation_sha256,
                observation_ordinal=binding.observation_ordinal,
                partition_sha256=partition.partition_sha256,
                partition_ordinal=binding.partition_ordinal,
                binding_sha256=binding.binding_sha256,
                binding_ordinal=binding.binding_ordinal,
                observation_record_ordinal=binding.observation_record_ordinal,
                source_record_sha256=binding.source_record_sha256,
                unit_sha256=binding.unit_sha256,
                unit_ordinal=binding.unit_ordinal,
                assignment_sha256=binding.assignment_sha256,
                unit_kind=binding.ownership_kind,
                occurrence_sha256=binding.occurrence_sha256,
                occurrence_ordinal=binding.occurrence_ordinal,
                source_input_kind=assignment.source_input_kind,
                representation_kind=assignment.representation_kind,
                source_relation_kind=descriptor.source_relation_kind,
                projection_record_kind=descriptor.projection_record_kind,
            )
        )
    if source_index:
        _fail("public source authorities contain an unowned source record")
    return tuple(plans)


def build_value_projection_plan(
    raw_bundle: object,
    *,
    expected_raw_authority_bundle_sha256: str,
    ownership_authority: object,
    expected_ownership_receipt_sha256: str,
    result_cell_authority_receipt: object,
    expected_result_cell_authority_sha256: str,
    stats_lossless_authorities: object,
    expected_stats_lossless_authority_sha256s: tuple[str, ...],
    live_lossless_authority: object,
    expected_live_lossless_authority_receipt_sha256: str,
    body_blob_inventory_readback_receipt: object,
    expected_body_blob_inventory_readback_receipt_sha256: str,
    declared_bodyless_packets: object,
    expected_declared_bodyless_packet_authority_sha256s: tuple[str, ...],
    declared_bodyless_readback_receipts: object,
    expected_declared_bodyless_readback_receipt_sha256s: tuple[str, ...],
) -> ValueProjectionPlanV1:
    """Build one exact, value-free, bundle-global projection plan."""

    raw_pin = _sha256(expected_raw_authority_bundle_sha256, label="expected Raw bundle")
    ownership_pin = _sha256(expected_ownership_receipt_sha256, label="expected ownership receipt")
    result_pin = _sha256(
        expected_result_cell_authority_sha256, label="expected result-cell authority"
    )
    live_pin = _sha256(
        expected_live_lossless_authority_receipt_sha256,
        label="expected live-lossless receipt",
    )
    body_pin = _sha256(
        expected_body_blob_inventory_readback_receipt_sha256,
        label="expected body-blob inventory readback receipt",
    )
    stats_pins = _pin_tuple(
        expected_stats_lossless_authority_sha256s,
        label="expected stats-lossless authority pin",
    )
    packet_pins = _pin_tuple(
        expected_declared_bodyless_packet_authority_sha256s,
        label="expected bodyless packet pin",
    )
    bodyless_readback_pins = _pin_tuple(
        expected_declared_bodyless_readback_receipt_sha256s,
        label="expected bodyless readback pin",
    )
    if type(raw_bundle) is not RawRequestAuthorityBundleV2:
        _fail("projection-plan Raw authority has a foreign exact type")
    if type(ownership_authority) is not LosslessOwnershipAuthorityV1:
        _fail("projection-plan ownership authority has a foreign exact type")
    if type(result_cell_authority_receipt) is not RawResultCellAuthorityReceiptV2:
        _fail("projection-plan result-cell authority has a foreign exact type")
    if type(stats_lossless_authorities) is not tuple:
        _fail("projection-plan stats authorities have a foreign exact type")
    if type(live_lossless_authority) is not LiveLosslessValueAuthorityV1:
        _fail("projection-plan live authority has a foreign exact type")
    if type(body_blob_inventory_readback_receipt) is not BodyBlobInventoryReadbackReceiptV1:
        _fail("projection-plan body-blob readback has a foreign exact type")
    if type(declared_bodyless_packets) is not tuple:
        _fail("projection-plan bodyless packets have a foreign exact type")
    if type(declared_bodyless_readback_receipts) is not tuple:
        _fail("projection-plan bodyless readbacks have a foreign exact type")
    stats_values = cast("tuple[StatsLosslessValueAuthorityV1, ...]", stats_lossless_authorities)
    packets = cast("tuple[DeclaredBodylessPacketV1, ...]", declared_bodyless_packets)
    bodyless_readbacks = cast(
        "tuple[DeclaredBodylessPacketReadbackReceiptV1, ...]",
        declared_bodyless_readback_receipts,
    )
    if (
        len(stats_values) > _MAX_AUTHORITIES
        or len(packets) > _MAX_AUTHORITIES
        or len(bodyless_readbacks) > _MAX_AUTHORITIES
        or len(stats_values) != len(stats_pins)
        or len(packets) != len(packet_pins)
        or len(bodyless_readbacks) != len(bodyless_readback_pins)
        or len(packets) != len(bodyless_readbacks)
    ):
        _fail("projection-plan authority and external-pin denominators differ")
    if any(type(item) is not StatsLosslessValueAuthorityV1 for item in stats_values):
        _fail("projection-plan stats authorities have a foreign exact type")
    if any(type(item) is not DeclaredBodylessPacketV1 for item in packets):
        _fail("projection-plan bodyless packets have a foreign exact type")
    if any(
        type(item) is not DeclaredBodylessPacketReadbackReceiptV1 for item in bodyless_readbacks
    ):
        _fail("projection-plan bodyless readbacks have a foreign exact type")
    try:
        if (
            type(ownership_authority.receipt) is not LosslessOwnershipReceiptV1
            or type(live_lossless_authority.receipt) is not LiveLosslessValueAuthorityReceiptV1
            or any(
                type(item.receipt) is not StatsLosslessValueAuthorityReceiptV1
                for item in stats_values
            )
        ):
            _fail("projection-plan external-pin receipt has a foreign exact type")
        if raw_bundle.bundle_sha256 != raw_pin:
            _fail("Raw bundle differs from its external pin")
        if ownership_authority.receipt.receipt_sha256 != ownership_pin:
            _fail("ownership authority differs from its external pin")
        if result_cell_authority_receipt.authority_sha256 != result_pin:
            _fail("result-cell authority differs from its external pin")
        if live_lossless_authority.receipt.receipt_sha256 != live_pin:
            _fail("live-lossless authority differs from its external pin")
        if body_blob_inventory_readback_receipt.receipt_sha256 != body_pin:
            _fail("body-blob readback differs from its external pin")
        if tuple(item.receipt.authority_sha256 for item in stats_values) != stats_pins:
            _fail("stats-lossless authorities differ from their external pins")
        if tuple(item.packet_authority_sha256 for item in packets) != packet_pins:
            _fail("bodyless packets differ from their external pins")
        if tuple(item.receipt_sha256 for item in bodyless_readbacks) != bodyless_readback_pins:
            _fail("bodyless readbacks differ from their external pins")
        _preflight_raw(raw_bundle)
        _preflight_ownership(ownership_authority)
        _preflight_result_receipt(result_cell_authority_receipt)
        for item in stats_values:
            _preflight_stats(item)
        _preflight_live(live_lossless_authority)
        _preflight_body_readback(body_blob_inventory_readback_receipt)

        bundle = validate_raw_request_authority_bundle(raw_bundle)
        bundle.require_complete_terminal_selection()
        result_receipt = validate_raw_result_cell_authority_receipt(
            bundle, result_cell_authority_receipt
        )
        ownership = _replay_ownership(ownership_authority)
        body_readback = _replay_body_readback(body_blob_inventory_readback_receipt)
        replayed_packets = tuple(
            validate_declared_bodyless_packet_identity(
                packet,
                expected_packet_authority_sha256=pin,
            )
            for packet, pin in zip(packets, packet_pins, strict=True)
        )
        replayed_bodyless_readbacks = tuple(
            _replay_dataclass(item, DeclaredBodylessPacketReadbackReceiptV1)
            for item in bodyless_readbacks
        )
        derived_ownership = build_public_value_ownership_authority(
            bundle,
            expected_raw_authority_bundle_sha256=raw_pin,
            result_cell_authority_receipt=result_receipt,
            expected_result_cell_authority_sha256=result_pin,
            stats_lossless_authorities=stats_values,
            expected_stats_lossless_authority_sha256s=stats_pins,
            live_lossless_authority=live_lossless_authority,
            expected_live_lossless_authority_receipt_sha256=live_pin,
        )
        if ownership != derived_ownership:
            _fail("ownership authority differs from exact source-authority reconstruction")

        raw_observations = {
            item.attempt.observation_sha256: item
            for item in bundle.observations
            if item.lifecycle == "selected_terminal"
        }
        occurrence_to_observation = {
            item.occurrence_sha256: raw_observations[item.observation_sha256]
            for item in bundle.occurrences
            if item.observation_sha256 in raw_observations
        }
        source_index, stats_results = _source_index(
            result_receipt=result_receipt,
            stats_authorities=stats_values,
            live_authority=live_lossless_authority,
            occurrence_to_observation=occurrence_to_observation,
        )
        expected_units = tuple(
            ValueProjectionPlanExpectedUnitV1.from_row(item.to_row())
            for item in ownership.expected_unit_inventory.units
        )
        assignments = tuple(
            ValueProjectionPlanAssignmentV1.from_row(item.to_row())
            for item in ownership.representation_assignments
        )
        ownership_observations = tuple(
            ValueProjectionPlanOwnershipObservationV1.from_row(item.to_row())
            for item in ownership.observations
        )
        ownership_partitions = tuple(
            ValueProjectionPlanOwnershipPartitionV1.from_row(item.to_row())
            for item in ownership.partitions
        )
        ownership_bindings = tuple(
            ValueProjectionPlanOwnershipBindingV1.from_row(item.to_row())
            for item in ownership.bindings
        )
        observation_sources = _observation_sources(
            bundle=bundle,
            ownership=ownership,
            body_readback=body_readback,
            packets=replayed_packets,
            bodyless_readbacks=replayed_bodyless_readbacks,
        )
        occurrence_plans = _occurrence_plans(
            bundle=bundle,
            ownership=ownership,
            stats_results=stats_results,
        )
        source_record_plans = _source_record_plans(
            ownership=ownership,
            source_index=source_index,
        )
        plan = ValueProjectionPlanV1.build(
            raw_authority_bundle_sha256=raw_pin,
            ownership_receipt_sha256=ownership_pin,
            expected_unit_inventory_sha256=(ownership.expected_unit_inventory.inventory_sha256),
            expected_units=expected_units,
            assignments=assignments,
            ownership_observations=ownership_observations,
            ownership_partitions=ownership_partitions,
            ownership_bindings=ownership_bindings,
            observation_sources=observation_sources,
            occurrence_plans=occurrence_plans,
            source_record_plans=source_record_plans,
        )
        return validate_value_projection_plan(
            plan,
            expected_plan_sha256=plan.plan_sha256,
            expected_raw_authority_bundle_sha256=raw_pin,
            expected_ownership_receipt_sha256=ownership_pin,
        )
    except ValueProjectionPlanBuilderError:
        raise
    except Exception:
        raise ValueProjectionPlanBuilderError(
            "projection-plan authorities failed exact canonical replay"
        ) from None
