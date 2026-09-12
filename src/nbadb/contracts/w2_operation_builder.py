"""Pure cross-child builder for one fully closed W2 operation receipt.

The builder performs no persistence and owns no database handle.  It admits
externally pinned authorities produced before the W2 operation row, replays or
reconstructs every value-bearing child for which actual rows are available,
and emits only the scalar :class:`W2OperationReceiptV1` leaf.
"""

from __future__ import annotations

import re
from dataclasses import fields
from typing import TYPE_CHECKING, Never, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

from nbadb.contracts.body_blob_inventory import (
    BodyBlobInventoryReadbackReceiptV1,
    BodyBlobInventoryV1,
)
from nbadb.contracts.declared_bodyless_packet_types import (
    MAX_DECLARED_BODYLESS_PACKET_BYTES,
    DeclaredBodylessPacketReadbackReceiptV1,
    DeclaredBodylessPacketV1,
)
from nbadb.contracts.independent_body_value_projection_builder import (
    INDEPENDENT_BODY_VALUE_PROJECTION_POLICY_SHA256,
    IndependentBodyValueProjectionV1,
    build_independent_body_value_projection,
)
from nbadb.contracts.independent_result_cell_builder import (
    build_independent_result_cell_authority,
)
from nbadb.contracts.independent_stats_lossless_authority_builder import (
    build_independent_stats_lossless_authorities,
)
from nbadb.contracts.live_lossless_value_authority import (
    MAX_LIVE_LOSSLESS_RECORDS,
    LiveLosslessValueAuthorityV1,
    build_live_lossless_value_authority,
)
from nbadb.contracts.lossless_ownership import (
    LosslessObservationOwnershipV1,
    LosslessOwnershipAuthorityV1,
    LosslessOwnershipBindingV1,
    LosslessOwnershipPartitionV1,
    LosslessOwnershipReceiptV1,
)
from nbadb.contracts.public_table_value_projection import (
    PublicTableValueProjectionReceiptV1,
    PublicTableValueProjectionV1,
    build_public_table_value_projection,
)
from nbadb.contracts.public_value_authority_adapter import (
    build_public_value_ownership_authority,
)
from nbadb.contracts.public_value_types import (
    MAX_PUBLIC_VALUE_EXPECTED_UNITS,
    ExpectedValueUnitInventoryV1,
    ValueRepresentationAssignmentV1,
)
from nbadb.contracts.raw_request_authority import (
    MAX_JSON_NODES,
    ObservationRouteLandingV2,
    RawRequestAuthorityBundleV2,
    RequestObservationV2,
    validate_raw_request_authority_bundle,
)
from nbadb.contracts.raw_request_observation_order import (
    canonical_raw_request_observations,
)
from nbadb.contracts.raw_result_cell_authority import RawResultCellAuthorityReceiptV2
from nbadb.contracts.route_field_canonical_alias import (
    RouteFieldCanonicalAliasReceiptV1,
)
from nbadb.contracts.route_field_landing_authority import (
    RawNbaApiRouteFieldLandingV1,
)
from nbadb.contracts.route_field_landing_builder import (
    RawNbaApiRouteFieldLandingAuthorityReceiptV1,
    RawNbaApiRouteFieldLandingAuthorityV1,
    build_raw_nba_api_route_field_landing_authority,
)
from nbadb.contracts.stats_lossless_value_authority import (
    MAX_STATS_LOSSLESS_RECORDS,
    StatsLosslessValueAuthorityV1,
)
from nbadb.contracts.typed_field_value_receipt import RouteFieldLandingReceiptV2
from nbadb.contracts.value_projection import (
    MAX_VALUE_PROJECTION_ITEMS,
    MAX_VALUE_PROJECTION_OBSERVATIONS,
    MAX_VALUE_PROJECTION_PARTITIONS,
    BodyValueProjectionReceiptV1,
    ValueProjectionItemV1,
    ValueProjectionPartitionV1,
    ValueProjectionReceiptV1,
)
from nbadb.contracts.value_projection_equality import (
    ValueProjectionEqualityReceiptV1,
)
from nbadb.contracts.value_projection_plan import ValueProjectionPlanV1
from nbadb.contracts.value_projection_plan_builder import build_value_projection_plan
from nbadb.contracts.w2_operation import (
    W2OperationKeyV1,
    W2OperationReceiptV1,
    w2_committed_staging_readback_root,
)
from nbadb.orchestrate.staging_batches import (
    CommittedStagingChunkReceiptV2,
    CommittedStagingFrameReadbackV2,
)
from nbadb.schemas.raw.nba_api_w2_operation import (
    RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256,
)

__all__ = ["W2OperationBuilderError", "build_w2_operation"]


_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_MAX_ROWS = 14_000_000
_MAX_ROUTE_FIELD_ROWS = 10_000_000
_MAX_KNOWN_SECRETS = 128
_MAX_KNOWN_SECRET_BYTES = 4_096
_MAX_INT64 = (1 << 63) - 1


class W2OperationBuilderError(ValueError):
    """One W2 child authority cannot close an exact operation."""


def _fail(message: str) -> Never:
    raise W2OperationBuilderError(message) from None


def _sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be one exact lowercase SHA-256")
    return value


def _sha256_tuple(
    value: object,
    *,
    label: str,
    maximum: int = _MAX_ROWS,
) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) > maximum:
        _fail(f"{label} must be one bounded exact tuple")
    result = value
    for item in result:
        _sha256(item, label=label)
    if len(set(cast("tuple[str, ...]", result))) != len(result):
        _fail(f"{label} contains a duplicate identity")
    return cast("tuple[str, ...]", result)


def _exact_tuple(value: object, *, label: str, maximum: int = _MAX_ROWS) -> tuple[object, ...]:
    if type(value) is not tuple or len(value) > maximum:
        _fail(f"{label} must be one bounded exact tuple")
    return value


def _packet_bytes_tuple(value: object) -> tuple[bytes, ...]:
    if type(value) is not tuple or len(value) > MAX_VALUE_PROJECTION_OBSERVATIONS:
        _fail("declared-bodyless packet bytes must be one bounded exact tuple")
    total = 0
    result: list[bytes] = []
    for item in value:
        if type(item) is not bytes or not item or len(item) > MAX_DECLARED_BODYLESS_PACKET_BYTES:
            _fail("declared-bodyless packet bytes contain a foreign or over-bound payload")
        total += len(item)
        if total > _MAX_INT64:
            _fail("declared-bodyless packet bytes exceed their cumulative byte bound")
        result.append(item)
    return tuple(result)


def _known_secret_inventory(value: object) -> tuple[str | bytes, ...]:
    if type(value) is not tuple or len(value) > _MAX_KNOWN_SECRETS:
        _fail("known-secret inventory must be one bounded exact tuple")
    result: list[str | bytes] = []
    for item in value:
        if type(item) is str:
            try:
                encoded = item.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                _fail("known-secret inventory contains invalid text")
        elif type(item) is bytes:
            encoded = item
        else:
            _fail("known-secret inventory contains a foreign exact type")
        if not encoded or len(encoded) > _MAX_KNOWN_SECRET_BYTES:
            _fail("known-secret inventory contains an invalid byte length")
        result.append(item)
    return tuple(result)


def _replay_ownership(
    *,
    receipt: LosslessOwnershipReceiptV1,
    inventory: ExpectedValueUnitInventoryV1,
    assignments: tuple[ValueRepresentationAssignmentV1, ...],
    observations: tuple[LosslessObservationOwnershipV1, ...],
    partitions: tuple[LosslessOwnershipPartitionV1, ...],
    bindings: tuple[LosslessOwnershipBindingV1, ...],
) -> LosslessOwnershipAuthorityV1:
    replayed_receipt = LosslessOwnershipReceiptV1.from_row(receipt.to_row())
    replayed_inventory = ExpectedValueUnitInventoryV1.from_row(inventory.to_row())
    replayed_assignments = tuple(
        ValueRepresentationAssignmentV1.from_row(item.to_row()) for item in assignments
    )
    replayed_observations = tuple(
        LosslessObservationOwnershipV1.from_row(item.to_row()) for item in observations
    )
    replayed_partitions = tuple(
        LosslessOwnershipPartitionV1.from_row(item.to_row()) for item in partitions
    )
    replayed_bindings = tuple(
        LosslessOwnershipBindingV1.from_row(item.to_row()) for item in bindings
    )
    authority = LosslessOwnershipAuthorityV1(
        receipt=replayed_receipt,
        expected_unit_inventory=replayed_inventory,
        representation_assignments=replayed_assignments,
        observations=replayed_observations,
        partitions=replayed_partitions,
        bindings=replayed_bindings,
    )
    if (
        authority.receipt != receipt
        or authority.expected_unit_inventory != inventory
        or authority.representation_assignments != assignments
        or authority.observations != observations
        or authority.partitions != partitions
        or authority.bindings != bindings
    ):
        _fail("ownership authority differs after exact reconstruction")
    return authority


def _rebuild_projection(
    *,
    projection: ValueProjectionReceiptV1,
    partitions: tuple[ValueProjectionPartitionV1, ...],
    items: tuple[ValueProjectionItemV1, ...],
    ownership: LosslessOwnershipAuthorityV1,
    label: str,
) -> tuple[
    ValueProjectionReceiptV1,
    tuple[ValueProjectionPartitionV1, ...],
    tuple[ValueProjectionItemV1, ...],
]:
    replayed_projection = ValueProjectionReceiptV1.from_row(projection.to_row())
    replayed_partitions = tuple(
        ValueProjectionPartitionV1.from_row(item.to_row()) for item in partitions
    )
    replayed_items = tuple(ValueProjectionItemV1.from_row(item.to_row()) for item in items)
    rebuilt = ValueProjectionReceiptV1.build(
        raw_authority_bundle_sha256=ownership.receipt.raw_authority_bundle_sha256,
        ownership_receipt_row=ownership.receipt.to_row(),
        expected_unit_rows=tuple(item.to_row() for item in ownership.expected_unit_inventory.units),
        representation_assignment_rows=tuple(
            item.to_row() for item in ownership.representation_assignments
        ),
        ownership_observation_rows=tuple(item.to_row() for item in ownership.observations),
        ownership_partition_rows=tuple(item.to_row() for item in ownership.partitions),
        ownership_binding_rows=tuple(item.to_row() for item in ownership.bindings),
        partitions=replayed_partitions,
        items=replayed_items,
    )
    if (
        replayed_projection != projection
        or replayed_partitions != partitions
        or replayed_items != items
        or rebuilt != replayed_projection
        or rebuilt.to_row() != projection.to_row()
        or rebuilt.canonical_bytes() != projection.canonical_bytes()
    ):
        _fail(f"{label} projection differs from its actual child reconstruction")
    return rebuilt, replayed_partitions, replayed_items


def _replay_readback(value: CommittedStagingFrameReadbackV2) -> CommittedStagingFrameReadbackV2:
    receipt = value.committed_receipt
    exact_receipt = CommittedStagingChunkReceiptV2(
        **{
            item.name: getattr(receipt, item.name)
            for item in fields(CommittedStagingChunkReceiptV2)
        }
    )
    return CommittedStagingFrameReadbackV2(
        committed_receipt=exact_receipt,
        canonical_frame_format=value.canonical_frame_format,
        frame_content_hash_contract=value.frame_content_hash_contract,
        frame_schema_hash_contract=value.frame_schema_hash_contract,
        canonical_frame_bytes=value.canonical_frame_bytes,
        canonical_frame_sha256=value.canonical_frame_sha256,
        canonical_frame_size_bytes=value.canonical_frame_size_bytes,
        recomputed_frame_schema_sha256=value.recomputed_frame_schema_sha256,
        recomputed_frame_content_hash=value.recomputed_frame_content_hash,
        recomputed_persisted_content_sha256=value.recomputed_persisted_content_sha256,
        row_count=value.row_count,
        readback_receipt_sha256=value.readback_receipt_sha256,
    )


def _expected_landings(
    bundle: RawRequestAuthorityBundleV2,
    selected: tuple[RequestObservationV2, ...],
) -> tuple[ObservationRouteLandingV2, ...]:
    selected_ids = {item.attempt.observation_sha256 for item in selected}
    groups: dict[str, list[ObservationRouteLandingV2 | None]] = {
        item.attempt.observation_sha256: [None] * item.route_landing_count for item in selected
    }
    for landing in bundle.landings:
        if landing.observation_sha256 not in selected_ids:
            continue
        slots = groups[landing.observation_sha256]
        if landing.route_ordinal >= len(slots) or slots[landing.route_ordinal] is not None:
            _fail("Raw route landing order is sparse or duplicated")
        slots[landing.route_ordinal] = landing
    result: list[ObservationRouteLandingV2] = []
    for observation in selected:
        slots = groups[observation.attempt.observation_sha256]
        if any(item is None for item in slots):
            _fail("selected Raw observation lacks a complete route landing inventory")
        result.extend(cast("list[ObservationRouteLandingV2]", slots))
    return tuple(result)


def _validate_readbacks(
    *,
    bundle: RawRequestAuthorityBundleV2,
    selected: tuple[RequestObservationV2, ...],
    readbacks: tuple[CommittedStagingFrameReadbackV2, ...],
    expected_pins: tuple[str, ...],
) -> tuple[CommittedStagingFrameReadbackV2, ...]:
    landings = _expected_landings(bundle, selected)
    if len(readbacks) != len(expected_pins) or len(readbacks) != len(landings):
        _fail("committed staging readback denominator differs from Raw route authority")
    replayed: list[CommittedStagingFrameReadbackV2] = []
    for ordinal, (value, expected_pin, landing) in enumerate(
        zip(readbacks, expected_pins, landings, strict=True)
    ):
        if value.readback_receipt_sha256 != expected_pin:
            _fail("committed staging readback differs from its external pin")
        item = _replay_readback(value)
        receipt = item.committed_receipt
        if (
            item != value
            or landing.route_ordinal < 0
            or receipt.receipt_root_sha256 != landing.receipt_root_sha256
            or receipt.staging_key != landing.staging_key
            or receipt.result_route_id != landing.route_id
            or receipt.chunk_id != landing.chunk_id
            or receipt.persisted_row_count != landing.persisted_row_count
            or receipt.persisted_content_sha256 != landing.persisted_content_sha256
            or receipt.persisted_schema_sha256 != landing.persisted_schema_sha256
            or receipt.logical_call_receipt_sha256 != landing.logical_call_receipt_sha256
            or receipt.provider_authority_sha256 != landing.provider_authority_sha256
            or receipt.logical_parameters_sha256 != landing.logical_parameters_sha256
        ):
            _fail(f"committed staging readback {ordinal} differs from its Raw landing")
        replayed.append(item)
    return tuple(replayed)


def _validate_plan_sources(
    *,
    plan: ValueProjectionPlanV1,
    selected: tuple[RequestObservationV2, ...],
    bundle: RawRequestAuthorityBundleV2,
) -> None:
    if len(plan.observation_sources) != len(selected):
        _fail("projection plan source denominator differs from selected Raw observations")
    objects = {item.object_sha256: item for item in bundle.objects}
    for ordinal, (source, observation) in enumerate(
        zip(plan.observation_sources, selected, strict=True)
    ):
        parser_source = observation.body_object_sha256 is not None
        if (
            source.observation_ordinal != ordinal
            or source.observation_sha256 != observation.attempt.observation_sha256
            or source.observation_record_sha256 != observation.observation_record_sha256
            or source.source_family != observation.attempt.source_family
            or parser_source != (source.source_input_kind == "parser_input_body")
        ):
            _fail("projection plan source differs from canonical Raw observation order")
        if parser_source:
            body_sha = observation.body_object_sha256
            body = objects.get(body_sha)
            if (
                body is None
                or source.parser_input_object_sha256 != body_sha
                or source.payload_sha256 != body.response_sha256
                or source.payload_byte_count != body.uncompressed_bytes
            ):
                _fail("projection plan parser-input source differs from Raw body authority")


def _same_rows(left: tuple[object, ...], right: tuple[object, ...]) -> bool:
    if len(left) != len(right):
        return False
    return all(
        type(a) is dict and type(b) is dict and a == b for a, b in zip(left, right, strict=True)
    )


def _result_authority_evidence_ids(value: RawResultCellAuthorityReceiptV2) -> set[int]:
    proof = value.public_table_proof
    return {id(value), id(proof), *(id(item) for item in proof.cells)}


def _stats_authority_evidence_ids(
    values: tuple[StatsLosslessValueAuthorityV1, ...],
) -> set[int]:
    identities: set[int] = set()
    for authority in values:
        identities.update(
            (
                id(authority),
                id(authority.receipt),
                id(authority.manifest),
                id(authority.expected_unit_inventory),
            )
        )
        identities.update(id(item) for item in authority.expected_unit_inventory.units)
        identities.update(id(item) for item in authority.representation_assignments)
        identities.update(id(item) for item in authority.results)
        identities.update(id(item) for item in authority.records)
    return identities


def _live_authority_evidence_ids(value: LiveLosslessValueAuthorityV1) -> set[int]:
    return {
        id(value),
        id(value.receipt),
        id(value.expected_units),
        *(id(item) for item in value.expected_units.units),
        *(id(item) for item in value.representation_assignments),
        *(id(item) for item in value.records),
    }


def _ownership_authority_evidence_ids(value: LosslessOwnershipAuthorityV1) -> set[int]:
    return {
        id(value),
        id(value.receipt),
        id(value.expected_unit_inventory),
        *(id(item) for item in value.expected_unit_inventory.units),
        *(id(item) for item in value.representation_assignments),
        *(id(item) for item in value.observations),
        *(id(item) for item in value.partitions),
        *(id(item) for item in value.bindings),
    }


def _plan_evidence_ids(value: ValueProjectionPlanV1) -> set[int]:
    return {
        id(value),
        *(id(item) for item in value.expected_units),
        *(id(item) for item in value.assignments),
        *(id(item) for item in value.ownership_observations),
        *(id(item) for item in value.ownership_partitions),
        *(id(item) for item in value.ownership_bindings),
        *(id(item) for item in value.observation_sources),
        *(id(item) for item in value.occurrence_plans),
        *(id(item) for item in value.source_record_plans),
    }


def _route_authority_evidence_ids(value: RawNbaApiRouteFieldLandingAuthorityV1) -> set[int]:
    return {id(value), id(value.receipt), *(id(item) for item in value.rows)}


def build_w2_operation(
    raw_bundle: object,
    *,
    expected_raw_authority_bundle_sha256: object,
    raw_observations: object,
    committed_staging_readbacks: object,
    expected_committed_staging_readback_sha256s: object,
    body_value_projection_receipt: object,
    expected_body_value_projection_receipt_sha256: object,
    body_projection: object,
    expected_body_projection_sha256: object,
    body_partitions: object,
    body_items: object,
    ownership_receipt: object,
    expected_ownership_receipt_sha256: object,
    expected_unit_inventory: object,
    representation_assignments: object,
    ownership_observations: object,
    ownership_partitions: object,
    ownership_bindings: object,
    result_cell_authority_receipt: object,
    expected_result_cell_authority_sha256: object,
    stats_lossless_authorities: object,
    expected_stats_lossless_authority_sha256s: object,
    live_lossless_authority: object,
    expected_live_lossless_authority_receipt_sha256: object,
    body_blob_inventory: object,
    expected_body_blob_inventory_sha256: object,
    body_blob_inventory_readback_receipt: object,
    expected_body_blob_inventory_readback_receipt_sha256: object,
    declared_bodyless_packets: object,
    expected_declared_bodyless_packet_authority_sha256s: object,
    declared_bodyless_readback_receipts: object,
    expected_declared_bodyless_readback_receipt_sha256s: object,
    declared_bodyless_packet_bytes: object,
    plan: object,
    expected_plan_sha256: object,
    route_field_landing_receipt: object,
    expected_route_field_landing_receipt_sha256: object,
    route_landing_receipts: object,
    expected_route_landing_receipt_sha256s: object,
    canonical_alias_receipts: object,
    expected_canonical_alias_receipt_sha256s: object,
    route_field_landing_authority_rows: object,
    public_table_value_projection_receipt: object,
    expected_public_table_value_projection_receipt_sha256: object,
    public_projection: object,
    expected_public_projection_sha256: object,
    public_partitions: object,
    public_items: object,
    value_projection_equality_receipt: object,
    expected_value_projection_equality_receipt_sha256: object,
    result_cell_schema_sha256: object,
    result_cell_rows: object,
    stats_lossless_schema_sha256: object,
    stats_lossless_rows: object,
    live_lossless_schema_sha256: object,
    live_lossless_rows: object,
    value_representation_schema_sha256: object,
    value_representation_rows: object,
    route_field_landing_schema_sha256: object,
    route_field_landing_rows: object,
    expected_w2_operation_schema_sha256: object,
    known_secrets: Sequence[str | bytes] = (),
) -> W2OperationReceiptV1:
    """Reconstruct every pre-operation authority and seal one W2 receipt."""

    # Every caller-supplied authority pin is checked before any child member access.
    raw_pin = _sha256(expected_raw_authority_bundle_sha256, label="expected Raw bundle")
    body_receipt_pin = _sha256(
        expected_body_value_projection_receipt_sha256,
        label="expected body projection receipt",
    )
    body_projection_pin = _sha256(expected_body_projection_sha256, label="expected body projection")
    ownership_pin = _sha256(expected_ownership_receipt_sha256, label="expected ownership receipt")
    result_authority_pin = _sha256(
        expected_result_cell_authority_sha256,
        label="expected result-cell authority",
    )
    live_authority_pin = _sha256(
        expected_live_lossless_authority_receipt_sha256,
        label="expected live-lossless authority",
    )
    body_inventory_pin = _sha256(
        expected_body_blob_inventory_sha256,
        label="expected body-blob inventory",
    )
    body_readback_pin = _sha256(
        expected_body_blob_inventory_readback_receipt_sha256,
        label="expected body-blob inventory readback",
    )
    plan_pin = _sha256(expected_plan_sha256, label="expected projection plan")
    route_receipt_pin = _sha256(
        expected_route_field_landing_receipt_sha256,
        label="expected route-field landing receipt",
    )
    public_receipt_pin = _sha256(
        expected_public_table_value_projection_receipt_sha256,
        label="expected public-table projection receipt",
    )
    public_projection_pin = _sha256(
        expected_public_projection_sha256, label="expected public projection"
    )
    equality_pin = _sha256(
        expected_value_projection_equality_receipt_sha256,
        label="expected projection-equality receipt",
    )
    result_schema = _sha256(result_cell_schema_sha256, label="result-cell schema")
    stats_schema = _sha256(stats_lossless_schema_sha256, label="stats-lossless schema")
    live_schema = _sha256(live_lossless_schema_sha256, label="live-lossless schema")
    representation_schema = _sha256(
        value_representation_schema_sha256, label="value-representation schema"
    )
    route_schema = _sha256(route_field_landing_schema_sha256, label="route-field landing schema")
    operation_schema = _sha256(
        expected_w2_operation_schema_sha256, label="expected W2 operation schema"
    )
    if operation_schema != RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256:
        _fail("expected W2 operation schema differs from the public schema authority")
    readback_pins = _sha256_tuple(
        expected_committed_staging_readback_sha256s,
        label="expected committed staging readback pin",
    )
    stats_authority_pins = _sha256_tuple(
        expected_stats_lossless_authority_sha256s,
        label="expected stats-lossless authority pin",
        maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
    )
    bodyless_packet_pins = _sha256_tuple(
        expected_declared_bodyless_packet_authority_sha256s,
        label="expected declared-bodyless packet pin",
        maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
    )
    bodyless_readback_pins = _sha256_tuple(
        expected_declared_bodyless_readback_receipt_sha256s,
        label="expected declared-bodyless readback pin",
        maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
    )
    route_source_pins = _sha256_tuple(
        expected_route_landing_receipt_sha256s,
        label="expected route landing receipt pin",
    )
    alias_source_pins = _sha256_tuple(
        expected_canonical_alias_receipt_sha256s,
        label="expected canonical-alias receipt pin",
    )
    packet_byte_values = _packet_bytes_tuple(declared_bodyless_packet_bytes)
    secret_values = _known_secret_inventory(known_secrets)

    # Exact types are admitted before any caller child method or attribute access.
    exact_type_inputs = (
        (raw_bundle, RawRequestAuthorityBundleV2, "Raw bundle"),
        (body_value_projection_receipt, BodyValueProjectionReceiptV1, "body receipt"),
        (body_projection, ValueProjectionReceiptV1, "body projection"),
        (ownership_receipt, LosslessOwnershipReceiptV1, "ownership receipt"),
        (expected_unit_inventory, ExpectedValueUnitInventoryV1, "expected-unit inventory"),
        (
            result_cell_authority_receipt,
            RawResultCellAuthorityReceiptV2,
            "result-cell authority receipt",
        ),
        (
            live_lossless_authority,
            LiveLosslessValueAuthorityV1,
            "live-lossless authority",
        ),
        (body_blob_inventory, BodyBlobInventoryV1, "body-blob inventory"),
        (
            body_blob_inventory_readback_receipt,
            BodyBlobInventoryReadbackReceiptV1,
            "body-blob inventory readback",
        ),
        (plan, ValueProjectionPlanV1, "projection plan"),
        (
            route_field_landing_receipt,
            RawNbaApiRouteFieldLandingAuthorityReceiptV1,
            "route-field receipt",
        ),
        (
            public_table_value_projection_receipt,
            PublicTableValueProjectionReceiptV1,
            "public-table receipt",
        ),
        (public_projection, ValueProjectionReceiptV1, "public projection"),
        (
            value_projection_equality_receipt,
            ValueProjectionEqualityReceiptV1,
            "projection equality receipt",
        ),
    )
    for value, expected_type, label in exact_type_inputs:
        if type(value) is not expected_type:
            _fail(f"{label} has a foreign exact type")
    tuple_inputs = (
        (
            raw_observations,
            RequestObservationV2,
            "Raw observation",
            MAX_VALUE_PROJECTION_OBSERVATIONS,
        ),
        (
            committed_staging_readbacks,
            CommittedStagingFrameReadbackV2,
            "staging readback",
            _MAX_ROWS,
        ),
        (
            representation_assignments,
            ValueRepresentationAssignmentV1,
            "assignment",
            MAX_PUBLIC_VALUE_EXPECTED_UNITS,
        ),
        (
            ownership_observations,
            LosslessObservationOwnershipV1,
            "ownership observation",
            MAX_VALUE_PROJECTION_OBSERVATIONS,
        ),
        (
            ownership_partitions,
            LosslessOwnershipPartitionV1,
            "ownership partition",
            MAX_VALUE_PROJECTION_PARTITIONS,
        ),
        (
            ownership_bindings,
            LosslessOwnershipBindingV1,
            "ownership binding",
            MAX_VALUE_PROJECTION_ITEMS,
        ),
        (
            stats_lossless_authorities,
            StatsLosslessValueAuthorityV1,
            "stats-lossless authority",
            MAX_VALUE_PROJECTION_OBSERVATIONS,
        ),
        (
            declared_bodyless_packets,
            DeclaredBodylessPacketV1,
            "declared-bodyless packet",
            MAX_VALUE_PROJECTION_OBSERVATIONS,
        ),
        (
            declared_bodyless_readback_receipts,
            DeclaredBodylessPacketReadbackReceiptV1,
            "declared-bodyless readback",
            MAX_VALUE_PROJECTION_OBSERVATIONS,
        ),
        (
            route_field_landing_authority_rows,
            RawNbaApiRouteFieldLandingV1,
            "route-field authority row",
            _MAX_ROUTE_FIELD_ROWS,
        ),
        (
            route_landing_receipts,
            RouteFieldLandingReceiptV2,
            "route landing receipt",
            _MAX_ROWS,
        ),
        (
            canonical_alias_receipts,
            RouteFieldCanonicalAliasReceiptV1,
            "canonical-alias receipt",
            _MAX_ROWS,
        ),
        (
            body_partitions,
            ValueProjectionPartitionV1,
            "body partition",
            MAX_VALUE_PROJECTION_PARTITIONS,
        ),
        (
            body_items,
            ValueProjectionItemV1,
            "body item",
            MAX_VALUE_PROJECTION_ITEMS,
        ),
        (
            public_partitions,
            ValueProjectionPartitionV1,
            "public partition",
            MAX_VALUE_PROJECTION_PARTITIONS,
        ),
        (
            public_items,
            ValueProjectionItemV1,
            "public item",
            MAX_VALUE_PROJECTION_ITEMS,
        ),
    )
    exact_tuples: dict[str, tuple[object, ...]] = {}
    for value, expected_type, label, maximum in tuple_inputs:
        inventory = _exact_tuple(value, label=label, maximum=maximum)
        if any(type(item) is not expected_type for item in inventory):
            _fail(f"{label} inventory contains a foreign exact type")
        exact_tuples[label] = inventory
    relation_rows = (
        (result_cell_rows, "result-cell row", MAX_JSON_NODES),
        (stats_lossless_rows, "stats-lossless row", MAX_STATS_LOSSLESS_RECORDS),
        (live_lossless_rows, "live-lossless row", MAX_LIVE_LOSSLESS_RECORDS),
        (
            value_representation_rows,
            "value-representation row",
            MAX_PUBLIC_VALUE_EXPECTED_UNITS,
        ),
        (route_field_landing_rows, "route-field landing row", _MAX_ROUTE_FIELD_ROWS),
    )
    for value, label, maximum in relation_rows:
        inventory = _exact_tuple(value, label=label, maximum=maximum)
        if any(type(item) is not dict for item in inventory):
            _fail(f"{label} inventory contains a foreign exact row type")
    if not (
        len(exact_tuples["stats-lossless authority"]) == len(stats_authority_pins)
        and len(exact_tuples["declared-bodyless packet"])
        == len(bodyless_packet_pins)
        == len(exact_tuples["declared-bodyless readback"])
        == len(bodyless_readback_pins)
        == len(packet_byte_values)
    ):
        _fail("W2 source authority and external-pin denominators differ")
    body_evidence_ids = {
        id(body_projection),
        *(id(item) for item in exact_tuples["body partition"]),
        *(id(item) for item in exact_tuples["body item"]),
    }
    public_evidence_ids = {
        id(public_projection),
        *(id(item) for item in exact_tuples["public partition"]),
        *(id(item) for item in exact_tuples["public item"]),
    }
    if body_evidence_ids & public_evidence_ids:
        _fail("body and public projection evidence aliases one child object")

    try:
        raw = cast("RawRequestAuthorityBundleV2", raw_bundle)
        if raw.bundle_sha256 != raw_pin:
            _fail("Raw bundle differs from its external pin")
        supplied_observations = cast(
            "tuple[RequestObservationV2, ...]", exact_tuples["Raw observation"]
        )
        exact_raw = validate_raw_request_authority_bundle(raw)
        exact_raw.require_complete_terminal_selection()
        if supplied_observations != exact_raw.observations:
            _fail("supplied Raw observations differ from the exact bundle")
        selected = canonical_raw_request_observations(
            supplied_observations,
            selection="selected_terminal",
        )
        operation_key = W2OperationKeyV1.build(supplied_observations)

        body_receipt_value = cast("BodyValueProjectionReceiptV1", body_value_projection_receipt)
        ownership_receipt_value = cast("LosslessOwnershipReceiptV1", ownership_receipt)
        plan_value = cast("ValueProjectionPlanV1", plan)
        route_receipt_value = cast(
            "RawNbaApiRouteFieldLandingAuthorityReceiptV1", route_field_landing_receipt
        )
        public_receipt_value = cast(
            "PublicTableValueProjectionReceiptV1", public_table_value_projection_receipt
        )
        equality_value = cast("ValueProjectionEqualityReceiptV1", value_projection_equality_receipt)
        pin_checks = (
            (body_receipt_value.receipt_sha256, body_receipt_pin, "body receipt"),
            (
                cast("ValueProjectionReceiptV1", body_projection).projection_sha256,
                body_projection_pin,
                "body projection",
            ),
            (ownership_receipt_value.receipt_sha256, ownership_pin, "ownership receipt"),
            (plan_value.plan_sha256, plan_pin, "projection plan"),
            (route_receipt_value.receipt_sha256, route_receipt_pin, "route-field receipt"),
            (public_receipt_value.receipt_sha256, public_receipt_pin, "public receipt"),
            (
                cast("ValueProjectionReceiptV1", public_projection).projection_sha256,
                public_projection_pin,
                "public projection",
            ),
            (equality_value.receipt_sha256, equality_pin, "projection equality"),
        )
        if any(actual != expected for actual, expected, _label in pin_checks):
            _fail("one W2 child differs from its external authority pin")
        route_source_values = cast(
            "tuple[RouteFieldLandingReceiptV2, ...]",
            exact_tuples["route landing receipt"],
        )
        alias_source_values = cast(
            "tuple[RouteFieldCanonicalAliasReceiptV1, ...]",
            exact_tuples["canonical-alias receipt"],
        )
        if (
            len(route_source_values) != len(route_source_pins)
            or len(alias_source_values) != len(alias_source_pins)
            or tuple(item.landing_receipt_sha256 for item in route_source_values)
            != route_source_pins
            or tuple(item.receipt_sha256 for item in alias_source_values) != alias_source_pins
        ):
            _fail("route source authorities differ from their external pins")

        packet_values = cast(
            "tuple[DeclaredBodylessPacketV1, ...]",
            exact_tuples["declared-bodyless packet"],
        )
        bodyless_readback_values = cast(
            "tuple[DeclaredBodylessPacketReadbackReceiptV1, ...]",
            exact_tuples["declared-bodyless readback"],
        )
        supplied_stats_authorities = cast(
            "tuple[StatsLosslessValueAuthorityV1, ...]",
            exact_tuples["stats-lossless authority"],
        )
        supplied_result_authority = cast(
            "RawResultCellAuthorityReceiptV2",
            result_cell_authority_receipt,
        )
        supplied_live_authority = cast(
            "LiveLosslessValueAuthorityV1",
            live_lossless_authority,
        )
        supplied_inventory = cast("ExpectedValueUnitInventoryV1", expected_unit_inventory)
        caller_result_evidence_ids = _result_authority_evidence_ids(supplied_result_authority)
        caller_stats_evidence_ids = _stats_authority_evidence_ids(supplied_stats_authorities)
        caller_live_evidence_ids = _live_authority_evidence_ids(supplied_live_authority)
        caller_ownership_evidence_ids = {
            id(ownership_receipt_value),
            id(supplied_inventory),
            *(id(item) for item in supplied_inventory.units),
            *(id(item) for item in exact_tuples["assignment"]),
            *(id(item) for item in exact_tuples["ownership observation"]),
            *(id(item) for item in exact_tuples["ownership partition"]),
            *(id(item) for item in exact_tuples["ownership binding"]),
        }
        caller_plan_evidence_ids = _plan_evidence_ids(plan_value)
        caller_route_evidence_ids = {
            id(route_receipt_value),
            *(id(item) for item in exact_tuples["route-field authority row"]),
        }

        independent_result_authority = build_independent_result_cell_authority(
            exact_raw,
            expected_raw_authority_bundle_sha256=raw_pin,
            declared_bodyless_packets=packet_values,
            expected_declared_bodyless_packet_authority_sha256s=bodyless_packet_pins,
            declared_bodyless_packet_bytes=packet_byte_values,
            known_secrets=secret_values,
        )
        if (
            type(independent_result_authority) is not RawResultCellAuthorityReceiptV2
            or _result_authority_evidence_ids(independent_result_authority)
            & caller_result_evidence_ids
            or independent_result_authority.authority_sha256 != result_authority_pin
            or independent_result_authority != supplied_result_authority
        ):
            _fail("result-cell authority differs from detached independent source-byte replay")
        independent_stats_authorities = build_independent_stats_lossless_authorities(
            exact_raw,
            expected_raw_authority_bundle_sha256=raw_pin,
        )
        if (
            type(independent_stats_authorities) is not tuple
            or len(independent_stats_authorities) > MAX_VALUE_PROJECTION_OBSERVATIONS
            or any(
                type(item) is not StatsLosslessValueAuthorityV1
                for item in independent_stats_authorities
            )
            or _stats_authority_evidence_ids(independent_stats_authorities)
            & caller_stats_evidence_ids
            or tuple(item.receipt.authority_sha256 for item in independent_stats_authorities)
            != stats_authority_pins
            or independent_stats_authorities != supplied_stats_authorities
        ):
            _fail("stats-lossless authorities differ from independent source-byte replay")
        independent_live_authority = build_live_lossless_value_authority(
            exact_raw,
            expected_raw_authority_bundle_sha256=raw_pin,
        )
        if (
            type(independent_live_authority) is not LiveLosslessValueAuthorityV1
            or _live_authority_evidence_ids(independent_live_authority) & caller_live_evidence_ids
            or independent_live_authority.receipt.receipt_sha256 != live_authority_pin
            or independent_live_authority != supplied_live_authority
        ):
            _fail("live-lossless authority differs from independent source-byte replay")

        ownership = build_public_value_ownership_authority(
            exact_raw,
            expected_raw_authority_bundle_sha256=raw_pin,
            result_cell_authority_receipt=independent_result_authority,
            expected_result_cell_authority_sha256=result_authority_pin,
            stats_lossless_authorities=independent_stats_authorities,
            expected_stats_lossless_authority_sha256s=stats_authority_pins,
            live_lossless_authority=independent_live_authority,
            expected_live_lossless_authority_receipt_sha256=live_authority_pin,
        )
        if (
            type(ownership) is not LosslessOwnershipAuthorityV1
            or _ownership_authority_evidence_ids(ownership) & caller_ownership_evidence_ids
        ):
            _fail("independent ownership builder returned a foreign authority")
        supplied_ownership = _replay_ownership(
            receipt=ownership_receipt_value,
            inventory=supplied_inventory,
            assignments=cast(
                "tuple[ValueRepresentationAssignmentV1, ...]",
                exact_tuples["assignment"],
            ),
            observations=cast(
                "tuple[LosslessObservationOwnershipV1, ...]",
                exact_tuples["ownership observation"],
            ),
            partitions=cast(
                "tuple[LosslessOwnershipPartitionV1, ...]",
                exact_tuples["ownership partition"],
            ),
            bindings=cast(
                "tuple[LosslessOwnershipBindingV1, ...]",
                exact_tuples["ownership binding"],
            ),
        )
        if (
            ownership.receipt.raw_authority_bundle_sha256 != raw_pin
            or ownership.receipt.receipt_sha256 != ownership_pin
            or ownership.receipt != supplied_ownership.receipt
            or ownership.expected_unit_inventory != supplied_ownership.expected_unit_inventory
            or ownership.representation_assignments != supplied_ownership.representation_assignments
            or ownership.observations != supplied_ownership.observations
            or ownership.partitions != supplied_ownership.partitions
            or ownership.bindings != supplied_ownership.bindings
        ):
            _fail("ownership witness differs from independent source authorities")
        exact_plan = build_value_projection_plan(
            exact_raw,
            expected_raw_authority_bundle_sha256=raw_pin,
            ownership_authority=ownership,
            expected_ownership_receipt_sha256=ownership_pin,
            result_cell_authority_receipt=independent_result_authority,
            expected_result_cell_authority_sha256=result_authority_pin,
            stats_lossless_authorities=independent_stats_authorities,
            expected_stats_lossless_authority_sha256s=stats_authority_pins,
            live_lossless_authority=independent_live_authority,
            expected_live_lossless_authority_receipt_sha256=live_authority_pin,
            body_blob_inventory_readback_receipt=cast(
                "BodyBlobInventoryReadbackReceiptV1",
                body_blob_inventory_readback_receipt,
            ),
            expected_body_blob_inventory_readback_receipt_sha256=body_readback_pin,
            declared_bodyless_packets=packet_values,
            expected_declared_bodyless_packet_authority_sha256s=bodyless_packet_pins,
            declared_bodyless_readback_receipts=bodyless_readback_values,
            expected_declared_bodyless_readback_receipt_sha256s=bodyless_readback_pins,
        )
        if (
            type(exact_plan) is not ValueProjectionPlanV1
            or _plan_evidence_ids(exact_plan) & caller_plan_evidence_ids
        ):
            _fail("independent projection-plan builder returned a foreign authority")
        ownership_row_vectors = (
            tuple(item.to_row() for item in ownership.expected_unit_inventory.units),
            tuple(item.to_row() for item in ownership.representation_assignments),
            tuple(item.to_row() for item in ownership.observations),
            tuple(item.to_row() for item in ownership.partitions),
            tuple(item.to_row() for item in ownership.bindings),
        )
        plan_row_vectors = (
            tuple(item.to_row() for item in exact_plan.expected_units),
            tuple(item.to_row() for item in exact_plan.assignments),
            tuple(item.to_row() for item in exact_plan.ownership_observations),
            tuple(item.to_row() for item in exact_plan.ownership_partitions),
            tuple(item.to_row() for item in exact_plan.ownership_bindings),
        )
        if (
            ownership_row_vectors != plan_row_vectors
            or (
                exact_plan.expected_unit_inventory_sha256
                != ownership.expected_unit_inventory.inventory_sha256
            )
            or exact_plan != plan_value
            or exact_plan.canonical_bytes() != plan_value.canonical_bytes()
        ):
            _fail("projection plan relabels its exact ownership authority")
        _validate_plan_sources(plan=exact_plan, selected=selected, bundle=exact_raw)

        readbacks = _validate_readbacks(
            bundle=exact_raw,
            selected=selected,
            readbacks=cast(
                "tuple[CommittedStagingFrameReadbackV2, ...]",
                exact_tuples["staging readback"],
            ),
            expected_pins=readback_pins,
        )

        supplied_body_projection, supplied_body_partitions, supplied_body_items = (
            _rebuild_projection(
                projection=cast("ValueProjectionReceiptV1", body_projection),
                partitions=cast(
                    "tuple[ValueProjectionPartitionV1, ...]",
                    exact_tuples["body partition"],
                ),
                items=cast(
                    "tuple[ValueProjectionItemV1, ...]",
                    exact_tuples["body item"],
                ),
                ownership=ownership,
                label="body witness",
            )
        )
        exact_body = build_independent_body_value_projection(
            exact_raw,
            expected_raw_authority_bundle_sha256=raw_pin,
            ownership_authority=ownership,
            expected_ownership_receipt_sha256=ownership_pin,
            plan=exact_plan,
            expected_plan_sha256=plan_pin,
            body_blob_inventory=cast("BodyBlobInventoryV1", body_blob_inventory),
            expected_body_blob_inventory_sha256=body_inventory_pin,
            body_blob_inventory_readback_receipt=cast(
                "BodyBlobInventoryReadbackReceiptV1",
                body_blob_inventory_readback_receipt,
            ),
            expected_body_blob_inventory_readback_receipt_sha256=body_readback_pin,
            declared_bodyless_packets=packet_values,
            expected_declared_bodyless_packet_authority_sha256s=bodyless_packet_pins,
            declared_bodyless_readback_receipts=bodyless_readback_values,
            expected_declared_bodyless_readback_receipt_sha256s=bodyless_readback_pins,
            declared_bodyless_packet_bytes=packet_byte_values,
            known_secrets=secret_values,
        )
        if (
            type(exact_body) is not IndependentBodyValueProjectionV1
            or exact_body.receipt is body_receipt_value
            or id(exact_body.projection) in body_evidence_ids
            or any(id(item) in body_evidence_ids for item in exact_body.partitions)
            or any(id(item) in body_evidence_ids for item in exact_body.items)
        ):
            _fail("independent body builder returned aliased or foreign evidence")
        supplied_body_receipt = BodyValueProjectionReceiptV1.from_row(body_receipt_value.to_row())
        if (
            exact_body.receipt.receipt_sha256 != body_receipt_pin
            or exact_body.projection.projection_sha256 != body_projection_pin
            or exact_body.receipt.body_projection_policy_sha256
            != INDEPENDENT_BODY_VALUE_PROJECTION_POLICY_SHA256
            or exact_body.receipt.body_blob_inventory_sha256 != body_inventory_pin
            or exact_body.receipt.declared_bodyless_authority_sha256
            != exact_body.declared_bodyless_authority.authority_sha256
            or exact_body.receipt != supplied_body_receipt
            or exact_body.receipt.canonical_bytes() != body_receipt_value.canonical_bytes()
            or exact_body.projection != supplied_body_projection
            or exact_body.partitions != supplied_body_partitions
            or exact_body.items != supplied_body_items
        ):
            _fail("body projection witness differs from independent source-byte replay")
        body_projection_value = exact_body.projection
        body_partition_values = exact_body.partitions
        body_item_values = exact_body.items

        route_rows_value = cast(
            "tuple[RawNbaApiRouteFieldLandingV1, ...]",
            exact_tuples["route-field authority row"],
        )
        route_authority = build_raw_nba_api_route_field_landing_authority(
            raw_authority_bundle=exact_raw,
            expected_unit_inventory=ownership.expected_unit_inventory,
            representation_assignments=ownership.representation_assignments,
            result_cell_authority_receipt=independent_result_authority,
            lossless_ownership_authority=ownership,
            route_landing_receipts=route_source_values,
            canonical_alias_receipts=alias_source_values,
        )
        if (
            type(route_authority) is not RawNbaApiRouteFieldLandingAuthorityV1
            or _route_authority_evidence_ids(route_authority) & caller_route_evidence_ids
            or route_authority.receipt != route_receipt_value
            or route_authority.receipt.canonical_bytes() != route_receipt_value.canonical_bytes()
            or route_authority.rows != route_rows_value
        ):
            _fail("route-field authority differs from Raw/ownership closure")

        exact_result_rows = tuple(
            item.to_row() for item in independent_result_authority.public_table_proof.cells
        )
        exact_stats_rows = tuple(
            row for authority in independent_stats_authorities for row in authority.public_rows()
        )
        exact_live_rows = independent_live_authority.public_rows()
        exact_representation_rows = tuple(
            item.to_row() for item in ownership.representation_assignments
        )
        exact_route_rows = tuple(item.to_row() for item in route_authority.rows)
        source_public_rows = (
            (
                exact_result_rows,
                cast("tuple[object, ...]", result_cell_rows),
                "result-cell",
            ),
            (
                exact_stats_rows,
                cast("tuple[object, ...]", stats_lossless_rows),
                "stats-lossless",
            ),
            (
                exact_live_rows,
                cast("tuple[object, ...]", live_lossless_rows),
                "live-lossless",
            ),
            (
                exact_representation_rows,
                cast("tuple[object, ...]", value_representation_rows),
                "value-representation",
            ),
            (
                exact_route_rows,
                cast("tuple[object, ...]", route_field_landing_rows),
                "route-field",
            ),
        )
        if any(
            not _same_rows(expected, supplied) for expected, supplied, _label in source_public_rows
        ):
            _fail("one public relation differs from independent source authority")
        rebuilt_public = build_public_table_value_projection(
            plan=exact_plan,
            expected_plan_sha256=plan_pin,
            expected_raw_authority_bundle_sha256=raw_pin,
            expected_ownership_receipt_sha256=ownership_pin,
            result_cell_schema_sha256=result_schema,
            result_cell_rows=exact_result_rows,
            stats_lossless_schema_sha256=stats_schema,
            stats_lossless_rows=exact_stats_rows,
            live_lossless_schema_sha256=live_schema,
            live_lossless_rows=exact_live_rows,
            value_representation_schema_sha256=representation_schema,
            value_representation_rows=exact_representation_rows,
            route_field_landing_schema_sha256=route_schema,
            route_field_landing_rows=exact_route_rows,
        )
        if (
            type(rebuilt_public) is not PublicTableValueProjectionV1
            or rebuilt_public.receipt is public_receipt_value
            or id(rebuilt_public.projection) in public_evidence_ids
            or any(id(item) in public_evidence_ids for item in rebuilt_public.partitions)
            or any(id(item) in public_evidence_ids for item in rebuilt_public.items)
        ):
            _fail("independent public builder returned aliased or foreign evidence")
        supplied_public_projection, public_partition_values, public_item_values = (
            _rebuild_projection(
                projection=cast("ValueProjectionReceiptV1", public_projection),
                partitions=cast(
                    "tuple[ValueProjectionPartitionV1, ...]",
                    exact_tuples["public partition"],
                ),
                items=cast("tuple[ValueProjectionItemV1, ...]", exact_tuples["public item"]),
                ownership=ownership,
                label="public",
            )
        )
        if (
            PublicTableValueProjectionReceiptV1.from_row(public_receipt_value.to_row())
            != rebuilt_public.receipt
            or rebuilt_public.receipt != public_receipt_value
            or rebuilt_public.receipt.canonical_bytes() != public_receipt_value.canonical_bytes()
            or rebuilt_public.projection != supplied_public_projection
            or rebuilt_public.partitions != public_partition_values
            or rebuilt_public.items != public_item_values
        ):
            _fail("public-table receipt or projection differs from actual public rows")

        rebuilt_equality = ValueProjectionEqualityReceiptV1.build(
            expected_raw_authority_bundle_sha256=raw_pin,
            expected_ownership_receipt_sha256=ownership_pin,
            expected_plan_sha256=plan_pin,
            body_projection=body_projection_value,
            expected_body_projection_sha256=body_projection_pin,
            body_partitions=body_partition_values,
            body_items=body_item_values,
            public_projection=rebuilt_public.projection,
            expected_public_projection_sha256=public_projection_pin,
            public_partitions=rebuilt_public.partitions,
            public_items=rebuilt_public.items,
        )
        exact_equality = ValueProjectionEqualityReceiptV1.from_row(
            equality_value.to_row(), expected_receipt_sha256=equality_pin
        )
        if (
            rebuilt_equality != exact_equality
            or rebuilt_equality.to_row() != equality_value.to_row()
            or rebuilt_equality.canonical_bytes() != equality_value.canonical_bytes()
        ):
            _fail("projection-equality receipt differs from actual body/public children")

        own = ownership.receipt
        body = exact_body.receipt
        public = rebuilt_public.receipt
        equality = exact_equality
        values: dict[str, object] = {
            "raw_authority_bundle_sha256": raw_pin,
            "committed_staging_readback_count": len(readbacks),
            "committed_staging_readback_root_sha256": w2_committed_staging_readback_root(
                raw_authority_bundle_sha256=raw_pin,
                readback_receipt_sha256s=tuple(item.readback_receipt_sha256 for item in readbacks),
            ),
            "body_value_projection_receipt_sha256": body.receipt_sha256,
            "body_projection_policy_sha256": body.body_projection_policy_sha256,
            "body_blob_inventory_sha256": body.body_blob_inventory_sha256,
            "body_blob_count": body.body_blob_count,
            "body_blob_root_sha256": body.body_blob_root_sha256,
            "body_blob_readback_count": body.body_blob_readback_count,
            "body_blob_readback_root_sha256": body.body_blob_readback_root_sha256,
            "body_blob_byte_count": body.body_blob_byte_count,
            "parser_input_object_count": body.parser_input_object_count,
            "parser_input_object_root_sha256": body.parser_input_object_root_sha256,
            "declared_bodyless_authority_sha256": body.declared_bodyless_authority_sha256,
            "bodyless_packet_count": body.bodyless_packet_count,
            "bodyless_packet_root_sha256": body.bodyless_packet_root_sha256,
            "bodyless_readback_count": body.bodyless_readback_count,
            "bodyless_readback_root_sha256": body.bodyless_readback_root_sha256,
            "bodyless_packet_byte_count": body.bodyless_packet_byte_count,
            "observation_source_count": body.observation_source_count,
            "observation_source_root_sha256": body.observation_source_root_sha256,
            "lossless_ownership_receipt_sha256": own.receipt_sha256,
            "ownership_observation_count": own.observation_count,
            "ownership_observation_root_sha256": own.observation_root_sha256,
            "ownership_partition_count": own.partition_count,
            "ownership_partition_root_sha256": own.partition_root_sha256,
            "ownership_fixed_zero_landing_root_sha256": own.fixed_zero_landing_root_sha256,
            "ownership_binding_count": own.binding_count,
            "ownership_binding_root_sha256": own.binding_root_sha256,
            "ownership_source_record_count": own.source_record_count,
            "ownership_source_record_root_sha256": own.source_record_root_sha256,
            "expected_unit_inventory_sha256": own.expected_unit_inventory_sha256,
            "expected_unit_count": own.expected_unit_count,
            "expected_unit_root_sha256": own.expected_unit_root_sha256,
            "representation_assignment_count": own.representation_assignment_count,
            "representation_assignment_root_sha256": own.representation_assignment_root_sha256,
            "route_field_landing_receipt_sha256": route_authority.receipt.receipt_sha256,
            "route_field_landing_count": route_authority.receipt.landing_field_count,
            "route_field_landing_root_sha256": route_authority.receipt.landing_field_root_sha256,
            "value_projection_plan_sha256": exact_plan.plan_sha256,
            "public_table_value_projection_receipt_sha256": public.receipt_sha256,
            "value_projection_equality_receipt_sha256": equality.receipt_sha256,
            "projection_sha256": body_projection_value.projection_sha256,
            "projection_partition_count": body_projection_value.partition_count,
            "projection_partition_root_sha256": body_projection_value.partition_root_sha256,
            "projection_item_count": body_projection_value.item_count,
            "projection_item_root_sha256": body_projection_value.item_root_sha256,
            "partition_equality_count": equality.partition_equality_count,
            "partition_equality_root_sha256": equality.partition_equality_root_sha256,
            "item_equality_count": equality.item_equality_count,
            "item_equality_root_sha256": equality.item_equality_root_sha256,
            "equality_root_sha256": equality.equality_root_sha256,
            "result_cell_schema_sha256": public.result_cell_schema_sha256,
            "result_cell_row_count": public.result_cell_row_count,
            "result_cell_row_root_sha256": public.result_cell_row_root_sha256,
            "stats_lossless_schema_sha256": public.stats_lossless_schema_sha256,
            "stats_lossless_row_count": public.stats_lossless_row_count,
            "stats_lossless_row_root_sha256": public.stats_lossless_row_root_sha256,
            "live_lossless_schema_sha256": public.live_lossless_schema_sha256,
            "live_lossless_row_count": public.live_lossless_row_count,
            "live_lossless_row_root_sha256": public.live_lossless_row_root_sha256,
            "value_representation_schema_sha256": public.value_representation_schema_sha256,
            "value_representation_row_count": public.value_representation_row_count,
            "value_representation_row_root_sha256": public.value_representation_row_root_sha256,
            "route_field_landing_schema_sha256": public.route_field_landing_schema_sha256,
            "route_field_landing_row_count": public.route_field_landing_row_count,
            "route_field_landing_row_root_sha256": public.route_field_landing_row_root_sha256,
            "w2_operation_schema_sha256": operation_schema,
        }
        operation = W2OperationReceiptV1.build(operation_key=operation_key, **values)
        return W2OperationReceiptV1.from_row(
            operation.to_row(),
            expected_operation_receipt_sha256=operation.operation_receipt_sha256,
            expected_operation_key_sha256=operation.operation_key_sha256,
            expected_raw_authority_bundle_sha256=raw_pin,
            expected_w2_operation_schema_sha256=operation_schema,
        )
    except Exception:
        raise W2OperationBuilderError(
            "W2 operation children failed exact cross-authority reconstruction"
        ) from None
