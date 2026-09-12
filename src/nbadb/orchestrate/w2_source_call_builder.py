"""Build one exact W2 source-call candidate from persisted source authorities.

This module is the production composition boundary between already durable Raw
Authority V2/staging/body evidence and :mod:`w2_operation_coordinator`.  It
derives every public-value child independently; callers cannot supply a
prebuilt ownership, projection, equality, or W2 operation receipt.
"""

from __future__ import annotations

from dataclasses import fields
from typing import TYPE_CHECKING, Never, cast

if TYPE_CHECKING:
    from collections.abc import Callable

from nbadb.contracts.body_blob_inventory import BodyBlobInventoryV1
from nbadb.contracts.declared_bodyless_packet_types import (
    MAX_DECLARED_BODYLESS_PACKET_BYTES,
    DeclaredBodylessPacketReadbackReceiptV1,
    DeclaredBodylessPacketV1,
)
from nbadb.contracts.independent_body_value_projection_builder import (
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
    LIVE_LOSSLESS_NODE_SCHEMA_SHA256,
    LiveLosslessValueAuthorityV1,
    build_live_lossless_value_authority,
)
from nbadb.contracts.lossless_ownership import LosslessOwnershipAuthorityV1
from nbadb.contracts.public_table_value_projection import (
    RAW_NBA_API_RESULT_CELL_SCHEMA_SHA256,
    RAW_NBA_API_ROUTE_FIELD_LANDING_SCHEMA_SHA256,
    RAW_NBA_API_VALUE_REPRESENTATION_SCHEMA_SHA256,
    PublicTableValueProjectionV1,
    build_public_table_value_projection,
)
from nbadb.contracts.public_value_authority_adapter import (
    build_public_value_ownership_authority,
)
from nbadb.contracts.raw_request_authority import (
    MAX_AUTHORITY_ROWS,
    RawRequestAuthorityBundleV2,
    validate_logical_provider_parameter_join,
    validate_raw_request_authority_bundle,
)
from nbadb.contracts.raw_result_cell_authority import RawResultCellAuthorityReceiptV2
from nbadb.contracts.route_field_canonical_alias import (
    RouteFieldCanonicalAliasReceiptV1,
)
from nbadb.contracts.route_field_landing_builder import (
    RawNbaApiRouteFieldLandingAuthorityV1,
    build_raw_nba_api_route_field_landing_authority,
)
from nbadb.contracts.stats_lossless_value_authority import (
    STATS_LOSSLESS_RECORD_SCHEMA_SHA256,
    StatsLosslessValueAuthorityV1,
)
from nbadb.contracts.typed_field_value_receipt import RouteFieldLandingReceiptV2
from nbadb.contracts.value_projection import MAX_VALUE_PROJECTION_OBSERVATIONS
from nbadb.contracts.value_projection_equality import (
    ValueProjectionEqualityReceiptV1,
)
from nbadb.contracts.value_projection_plan import ValueProjectionPlanV1
from nbadb.contracts.value_projection_plan_builder import build_value_projection_plan
from nbadb.extract.bronze import LogicalCallReceiptBinding
from nbadb.orchestrate import w2_operation_coordinator as coordinator_module
from nbadb.orchestrate.body_blob_store import BodyBlobInventoryReadbackReceiptV1
from nbadb.orchestrate.raw_request_store import RawRequestAuthorityPersistenceReceiptV2
from nbadb.orchestrate.staging_batches import (
    CommittedStagingChunkReceiptV2,
    CommittedStagingFrameReadbackV2,
)
from nbadb.orchestrate.w2_operation_coordinator import (
    W2OperationBuildInputsV1,
    W2SourceCallCandidateV1,
)
from nbadb.schemas.raw.nba_api_w2_operation import (
    RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256,
)

__all__ = ["W2SourceCallBuilderError", "build_w2_source_call_candidate"]


class W2SourceCallBuilderError(ValueError):
    """Persisted source evidence cannot form one exact W2 candidate."""


_MAX_KNOWN_SECRETS = 128
_MAX_KNOWN_SECRET_BYTES = 4_096
_MAX_INT64 = (1 << 63) - 1


def _fail(message: str) -> Never:
    raise W2SourceCallBuilderError(message) from None


def _sha256(value: object, *, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        _fail(f"{label} must be one exact lowercase SHA-256")
    return value


def _sha_tuple(
    value: object,
    *,
    label: str,
    maximum: int,
    require_nonempty: bool = False,
) -> tuple[str, ...]:
    if type(value) is not tuple or len(value) > maximum or (require_nonempty and not value):
        _fail(f"{label} must be one bounded exact tuple")
    exact = tuple(_sha256(item, label=label) for item in value)
    if len(exact) != len(set(exact)):
        _fail(f"{label} repeats one identity")
    return exact


def _known_secret_inventory(value: object) -> tuple[str | bytes, ...]:
    if type(value) is not tuple or len(value) > _MAX_KNOWN_SECRETS:
        _fail("known-secret inventory must be one bounded exact tuple")
    result: list[str | bytes] = []
    for item in value:
        if type(item) is str:
            try:
                encoded = item.encode("utf-8", errors="strict")
            except UnicodeError:
                _fail("known-secret inventory contains invalid text")
        elif type(item) is bytes:
            encoded = item
        else:
            _fail("known-secret inventory contains a foreign exact type")
        if not encoded or len(encoded) > _MAX_KNOWN_SECRET_BYTES:
            _fail("known-secret inventory contains an invalid byte length")
        result.append(item)
    return tuple(result)


def _bounded_exact_tuple[T](
    value: object,
    *,
    expected_type: type[T],
    label: str,
    maximum: int,
    require_nonempty: bool = False,
) -> tuple[T, ...]:
    if type(value) is not tuple or len(value) > maximum or (require_nonempty and not value):
        _fail(f"{label} must be one bounded exact tuple")
    exact = value
    if any(type(item) is not expected_type for item in exact):
        _fail(f"{label} contains a foreign exact DTO")
    if len({id(item) for item in exact}) != len(exact):
        _fail(f"{label} repeats one object identity")
    return cast("tuple[T, ...]", exact)


def _packet_bytes_inventory(value: object) -> tuple[bytes, ...]:
    if type(value) is not tuple or len(value) > MAX_VALUE_PROJECTION_OBSERVATIONS:
        _fail("declared-bodyless packet bytes must be one bounded exact tuple")
    result: list[bytes] = []
    total_bytes = 0
    for item in value:
        if type(item) is not bytes or not item or len(item) > MAX_DECLARED_BODYLESS_PACKET_BYTES:
            _fail("declared-bodyless packet bytes contain a foreign or over-bound payload")
        total_bytes += len(item)
        if total_bytes > _MAX_INT64:
            _fail("declared-bodyless packet bytes exceed their cumulative byte bound")
        result.append(item)
    return tuple(result)


def _replay_exact_dataclass[T](
    value: object,
    expected_type: type[T],
    *,
    label: str,
) -> T:
    if type(value) is not expected_type:
        _fail(f"{label} has a foreign exact DTO")
    try:
        exact = expected_type(
            **{
                item.name: object.__getattribute__(value, item.name)
                for item in fields(expected_type)
            }
        )
        if exact != value:
            _fail(f"{label} differs from its exact DTO replay")
    except Exception:  # noqa: BLE001 - collapse the untrusted DTO boundary
        _fail(f"{label} failed exact DTO replay")
    return exact


def _derive_exact_child[T](
    *,
    label: str,
    expected_type: type[T],
    producer: Callable[[], object],
) -> T:
    try:
        value = producer()
    except Exception:  # noqa: BLE001 - child messages may contain hostile source data
        _fail(f"{label} derivation failed")
    return _replay_exact_dataclass(value, expected_type, label=label)


def _derive_exact_stats_children(
    producer: Callable[[], object],
) -> tuple[StatsLosslessValueAuthorityV1, ...]:
    try:
        value = producer()
    except Exception:  # noqa: BLE001 - child messages may contain hostile source data
        _fail("stats-lossless authority derivation failed")
    if type(value) is not tuple or len(value) > MAX_VALUE_PROJECTION_OBSERVATIONS:
        _fail("stats-lossless authority returned a foreign or over-bound inventory")
    result = tuple(
        _replay_exact_dataclass(
            item,
            StatsLosslessValueAuthorityV1,
            label="stats-lossless authority",
        )
        for item in value
    )
    try:
        identities = tuple(item.receipt.authority_sha256 for item in result)
    except Exception:  # noqa: BLE001 - sanitize hostile nested DTO behavior
        _fail("stats-lossless authority identity replay failed")
    if len(identities) != len(set(identities)):
        _fail("stats-lossless authority returned duplicate identities")
    return result


def _preflight_raw_bundle(value: object, *, expected_sha256: str) -> RawRequestAuthorityBundleV2:
    if type(value) is not RawRequestAuthorityBundleV2:
        _fail("Raw Authority V2 bundle has a foreign exact type")
    try:
        exact = validate_raw_request_authority_bundle(value)
        if (
            type(exact) is not RawRequestAuthorityBundleV2
            or exact != value
            or exact.bundle_sha256 != expected_sha256
        ):
            _fail("Raw Authority V2 bundle differs from exact replay")
    except Exception:  # noqa: BLE001 - sanitize untrusted bundle validation failures
        _fail("Raw Authority V2 bundle failed exact replay")
    return exact


def _preflight_logical_binding(
    value: object,
    *,
    bundle: RawRequestAuthorityBundleV2,
) -> LogicalCallReceiptBinding:
    exact = _replay_exact_dataclass(
        value,
        LogicalCallReceiptBinding,
        label="logical-call binding",
    )
    try:
        provider_calls = {item.attempt.provider_call_sha256 for item in bundle.observations}
        selected = tuple(
            item for item in bundle.observations if item.lifecycle == "selected_terminal"
        )
        if len(provider_calls) != 1 or len(selected) != 1:
            _fail("logical-call binding requires one completed provider call")
        observation = selected[0]
        selected_landings = tuple(
            item
            for item in bundle.landings
            if item.observation_sha256 == observation.attempt.observation_sha256
        )
        route_ids = tuple(item.route_id for item in selected_landings)
        endpoint_names = {item.split(":", 1)[0] for item in route_ids}
        joined = validate_logical_provider_parameter_join(
            observation,
            logical_endpoint_name=exact.endpoint_name,
            logical_parameters_sha256=exact.logical_parameters_sha256,
            result_route_ids=exact.result_route_ids,
        )
        if (
            joined != observation
            or observation.logical_receipt_sha256 != exact.logical_call_receipt_sha256
            or observation.attempt.provider_authority_sha256 != exact.provider_authority_sha256
            or tuple(sorted(route_ids)) != exact.result_route_ids
            or endpoint_names != {exact.endpoint_name}
        ):
            _fail("logical-call binding differs from selected Raw authority")
    except Exception:  # noqa: BLE001 - sanitize hostile nested DTO behavior
        _fail("logical-call binding failed exact Raw authority replay")
    return exact


def _preflight_raw_persistence(
    value: object,
    *,
    bundle: RawRequestAuthorityBundleV2,
    expected_sha256: str,
) -> RawRequestAuthorityPersistenceReceiptV2:
    exact = _replay_exact_dataclass(
        value,
        RawRequestAuthorityPersistenceReceiptV2,
        label="Raw Authority V2 persistence receipt",
    )
    try:
        expected = coordinator_module._expected_raw_persistence_receipt(  # noqa: SLF001
            bundle,
            replayed=exact.replayed,
        )
        if (
            exact != expected
            or exact.bundle_sha256 != bundle.bundle_sha256
            or exact.receipt_sha256 != expected_sha256
        ):
            _fail("Raw Authority V2 persistence receipt differs from exact bundle authority")
    except Exception:  # noqa: BLE001 - sanitize hostile nested DTO behavior
        _fail("Raw Authority V2 persistence receipt failed exact bundle replay")
    return exact


def _replay_readbacks(
    values: tuple[CommittedStagingFrameReadbackV2, ...],
    *,
    expected_sha256s: tuple[str, ...],
) -> tuple[CommittedStagingFrameReadbackV2, ...]:
    if len(values) != len(expected_sha256s):
        _fail("committed staging readback denominator differs from its external pins")
    result: list[CommittedStagingFrameReadbackV2] = []
    total_bytes = 0
    for value in values:
        try:
            receipt = _replay_exact_dataclass(
                value.committed_receipt,
                CommittedStagingChunkReceiptV2,
                label="committed staging receipt",
            )
            exact = CommittedStagingFrameReadbackV2(
                committed_receipt=receipt,
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
            if exact != value:
                _fail("committed staging readback differs from exact DTO replay")
            total_bytes += exact.canonical_frame_size_bytes
            if total_bytes > _MAX_INT64:
                _fail("committed staging readback bytes exceed the signed bound")
        except Exception:  # noqa: BLE001 - collapse the untrusted readback boundary
            _fail("committed staging readback failed exact DTO replay")
        result.append(exact)
    identities = tuple(item.readback_receipt_sha256 for item in result)
    if identities != expected_sha256s or len(identities) != len(set(identities)):
        _fail("committed staging readbacks are duplicated or reordered")
    return tuple(result)


def build_w2_source_call_candidate(
    *,
    logical_call_binding: object,
    raw_authority_persistence_receipt: object,
    expected_raw_authority_persistence_receipt_sha256: object,
    raw_bundle: object,
    expected_raw_authority_bundle_sha256: object,
    committed_staging_readbacks: object,
    expected_committed_staging_readback_sha256s: object,
    body_blob_inventory: object,
    expected_body_blob_inventory_sha256: object,
    body_blob_inventory_readback_receipt: object,
    expected_body_blob_inventory_readback_receipt_sha256: object,
    declared_bodyless_packets: object,
    expected_declared_bodyless_packet_authority_sha256s: object,
    declared_bodyless_readback_receipts: object,
    expected_declared_bodyless_readback_receipt_sha256s: object,
    declared_bodyless_packet_bytes: object,
    route_landing_receipts: object,
    expected_route_landing_receipt_sha256s: object,
    canonical_alias_receipts: object,
    expected_canonical_alias_receipt_sha256s: object,
    known_secrets: tuple[str | bytes, ...] = (),
) -> W2SourceCallCandidateV1:
    """Derive every pre-operation child and return a coordinator candidate.

    All durable inputs arrive with separate external pins.  The function emits
    no database or filesystem writes and never builds/persists the W2 operation
    itself; that remains the coordinator's second transactional boundary.
    """

    raw_pin = _sha256(
        expected_raw_authority_bundle_sha256,
        label="expected Raw Authority V2 bundle",
    )
    raw_persistence_pin = _sha256(
        expected_raw_authority_persistence_receipt_sha256,
        label="expected Raw Authority V2 persistence receipt",
    )
    readback_pins = _sha_tuple(
        expected_committed_staging_readback_sha256s,
        label="expected committed staging readback",
        maximum=MAX_AUTHORITY_ROWS,
        require_nonempty=True,
    )
    body_inventory_pin = _sha256(
        expected_body_blob_inventory_sha256,
        label="expected body-blob inventory",
    )
    body_readback_pin = _sha256(
        expected_body_blob_inventory_readback_receipt_sha256,
        label="expected body-blob readback receipt",
    )
    bodyless_packet_pins = _sha_tuple(
        expected_declared_bodyless_packet_authority_sha256s,
        label="expected declared-bodyless packet",
        maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
    )
    bodyless_readback_pins = _sha_tuple(
        expected_declared_bodyless_readback_receipt_sha256s,
        label="expected declared-bodyless readback receipt",
        maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
    )
    route_receipt_pins = _sha_tuple(
        expected_route_landing_receipt_sha256s,
        label="expected route-field landing receipt",
        maximum=MAX_AUTHORITY_ROWS,
    )
    alias_receipt_pins = _sha_tuple(
        expected_canonical_alias_receipt_sha256s,
        label="expected canonical-alias receipt",
        maximum=MAX_AUTHORITY_ROWS,
    )

    if type(body_blob_inventory) is not BodyBlobInventoryV1:
        _fail("body-blob inventory has a foreign exact type")
    if type(body_blob_inventory_readback_receipt) is not BodyBlobInventoryReadbackReceiptV1:
        _fail("body-blob readback receipt has a foreign exact type")
    secrets = _known_secret_inventory(known_secrets)
    readback_inputs = _bounded_exact_tuple(
        committed_staging_readbacks,
        expected_type=CommittedStagingFrameReadbackV2,
        label="committed staging readbacks",
        maximum=MAX_AUTHORITY_ROWS,
        require_nonempty=True,
    )
    packet_inputs = _bounded_exact_tuple(
        declared_bodyless_packets,
        expected_type=DeclaredBodylessPacketV1,
        label="declared-bodyless packets",
        maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
    )
    packet_readback_inputs = _bounded_exact_tuple(
        declared_bodyless_readback_receipts,
        expected_type=DeclaredBodylessPacketReadbackReceiptV1,
        label="declared-bodyless readbacks",
        maximum=MAX_VALUE_PROJECTION_OBSERVATIONS,
    )
    packet_bytes = _packet_bytes_inventory(declared_bodyless_packet_bytes)
    route_receipt_inputs = _bounded_exact_tuple(
        route_landing_receipts,
        expected_type=RouteFieldLandingReceiptV2,
        label="route-field landing receipts",
        maximum=MAX_AUTHORITY_ROWS,
    )
    alias_receipt_inputs = _bounded_exact_tuple(
        canonical_alias_receipts,
        expected_type=RouteFieldCanonicalAliasReceiptV1,
        label="canonical-alias receipts",
        maximum=MAX_AUTHORITY_ROWS,
    )

    if not (
        len(packet_inputs)
        == len(packet_readback_inputs)
        == len(packet_bytes)
        == len(bodyless_packet_pins)
        == len(bodyless_readback_pins)
    ):
        _fail("declared-bodyless source denominators differ")

    bundle = _preflight_raw_bundle(raw_bundle, expected_sha256=raw_pin)
    binding = _preflight_logical_binding(logical_call_binding, bundle=bundle)
    raw_persistence = _preflight_raw_persistence(
        raw_authority_persistence_receipt,
        bundle=bundle,
        expected_sha256=raw_persistence_pin,
    )
    readbacks = _replay_readbacks(
        readback_inputs,
        expected_sha256s=readback_pins,
    )
    inventory = _replay_exact_dataclass(
        body_blob_inventory,
        BodyBlobInventoryV1,
        label="body-blob inventory",
    )
    inventory_readback = _replay_exact_dataclass(
        body_blob_inventory_readback_receipt,
        BodyBlobInventoryReadbackReceiptV1,
        label="body-blob inventory readback receipt",
    )
    packets = tuple(
        _replay_exact_dataclass(
            item,
            DeclaredBodylessPacketV1,
            label="declared-bodyless packet",
        )
        for item in packet_inputs
    )
    packet_readbacks = tuple(
        _replay_exact_dataclass(
            item,
            DeclaredBodylessPacketReadbackReceiptV1,
            label="declared-bodyless packet readback receipt",
        )
        for item in packet_readback_inputs
    )
    # Route receipts deliberately expose a bounded identity-safe view to the
    # route authority builder; their value-bearing children are outside this
    # composition boundary and must not be traversed here.
    route_receipts = route_receipt_inputs
    alias_receipts = alias_receipt_inputs

    try:
        if (
            inventory.inventory_sha256 != body_inventory_pin
            or inventory.raw_authority_bundle_sha256 != raw_pin
            or inventory_readback.receipt_sha256 != body_readback_pin
            or tuple(item.packet_authority_sha256 for item in packets) != bodyless_packet_pins
            or tuple(item.receipt_sha256 for item in packet_readbacks) != bodyless_readback_pins
            or tuple(item.landing_receipt_sha256 for item in route_receipts) != route_receipt_pins
            or tuple(item.receipt_sha256 for item in alias_receipts) != alias_receipt_pins
        ):
            _fail("persisted W2 source evidence differs from its exact external pins")
    except Exception:  # noqa: BLE001 - sanitize hostile nested DTO behavior
        _fail("persisted W2 source evidence failed exact pin replay")

    result_authority = _derive_exact_child(
        label="result-cell authority",
        expected_type=RawResultCellAuthorityReceiptV2,
        producer=lambda: build_independent_result_cell_authority(
            bundle,
            expected_raw_authority_bundle_sha256=raw_pin,
            declared_bodyless_packets=packets,
            expected_declared_bodyless_packet_authority_sha256s=bodyless_packet_pins,
            declared_bodyless_packet_bytes=packet_bytes,
            known_secrets=secrets,
        ),
    )
    stats_authorities = _derive_exact_stats_children(
        lambda: build_independent_stats_lossless_authorities(
            bundle,
            expected_raw_authority_bundle_sha256=raw_pin,
        )
    )
    live_authority = _derive_exact_child(
        label="live-lossless authority",
        expected_type=LiveLosslessValueAuthorityV1,
        producer=lambda: build_live_lossless_value_authority(
            bundle,
            expected_raw_authority_bundle_sha256=raw_pin,
        ),
    )
    try:
        stats_pins = tuple(item.receipt.authority_sha256 for item in stats_authorities)
        result_authority_pin = result_authority.authority_sha256
        live_authority_pin = live_authority.receipt.receipt_sha256
    except Exception:  # noqa: BLE001 - sanitize hostile nested DTO behavior
        _fail("independent value authority identities failed exact replay")
    ownership = _derive_exact_child(
        label="public-value ownership authority",
        expected_type=LosslessOwnershipAuthorityV1,
        producer=lambda: build_public_value_ownership_authority(
            bundle,
            expected_raw_authority_bundle_sha256=raw_pin,
            result_cell_authority_receipt=result_authority,
            expected_result_cell_authority_sha256=result_authority_pin,
            stats_lossless_authorities=stats_authorities,
            expected_stats_lossless_authority_sha256s=stats_pins,
            live_lossless_authority=live_authority,
            expected_live_lossless_authority_receipt_sha256=live_authority_pin,
        ),
    )
    try:
        ownership_pin = ownership.receipt.receipt_sha256
    except Exception:  # noqa: BLE001 - sanitize hostile nested DTO behavior
        _fail("public-value ownership authority identity failed exact replay")
    plan = _derive_exact_child(
        label="value-projection plan",
        expected_type=ValueProjectionPlanV1,
        producer=lambda: build_value_projection_plan(
            bundle,
            expected_raw_authority_bundle_sha256=raw_pin,
            ownership_authority=ownership,
            expected_ownership_receipt_sha256=ownership_pin,
            result_cell_authority_receipt=result_authority,
            expected_result_cell_authority_sha256=result_authority_pin,
            stats_lossless_authorities=stats_authorities,
            expected_stats_lossless_authority_sha256s=stats_pins,
            live_lossless_authority=live_authority,
            expected_live_lossless_authority_receipt_sha256=live_authority_pin,
            body_blob_inventory_readback_receipt=inventory_readback,
            expected_body_blob_inventory_readback_receipt_sha256=body_readback_pin,
            declared_bodyless_packets=packets,
            expected_declared_bodyless_packet_authority_sha256s=bodyless_packet_pins,
            declared_bodyless_readback_receipts=packet_readbacks,
            expected_declared_bodyless_readback_receipt_sha256s=bodyless_readback_pins,
        ),
    )
    route_authority = _derive_exact_child(
        label="route-field landing authority",
        expected_type=RawNbaApiRouteFieldLandingAuthorityV1,
        producer=lambda: build_raw_nba_api_route_field_landing_authority(
            raw_authority_bundle=bundle,
            expected_unit_inventory=ownership.expected_unit_inventory,
            representation_assignments=ownership.representation_assignments,
            result_cell_authority_receipt=result_authority,
            lossless_ownership_authority=ownership,
            route_landing_receipts=route_receipts,
            canonical_alias_receipts=alias_receipts,
        ),
    )

    try:
        result_rows = tuple(item.to_row() for item in result_authority.public_table_proof.cells)
        stats_rows = tuple(
            row for authority in stats_authorities for row in authority.public_rows()
        )
        live_rows = live_authority.public_rows()
        assignment_rows = tuple(item.to_row() for item in plan.assignments)
        route_rows = tuple(item.to_row() for item in route_authority.rows)
        plan_pin = plan.plan_sha256
    except Exception:  # noqa: BLE001 - sanitize hostile nested DTO behavior
        _fail("public-value child rows failed exact materialization")
    public_projection = _derive_exact_child(
        label="public-table value projection",
        expected_type=PublicTableValueProjectionV1,
        producer=lambda: build_public_table_value_projection(
            plan=plan,
            expected_plan_sha256=plan_pin,
            expected_raw_authority_bundle_sha256=raw_pin,
            expected_ownership_receipt_sha256=ownership_pin,
            result_cell_schema_sha256=RAW_NBA_API_RESULT_CELL_SCHEMA_SHA256,
            result_cell_rows=result_rows,
            stats_lossless_schema_sha256=STATS_LOSSLESS_RECORD_SCHEMA_SHA256,
            stats_lossless_rows=stats_rows,
            live_lossless_schema_sha256=LIVE_LOSSLESS_NODE_SCHEMA_SHA256,
            live_lossless_rows=live_rows,
            value_representation_schema_sha256=(RAW_NBA_API_VALUE_REPRESENTATION_SCHEMA_SHA256),
            value_representation_rows=assignment_rows,
            route_field_landing_schema_sha256=(RAW_NBA_API_ROUTE_FIELD_LANDING_SCHEMA_SHA256),
            route_field_landing_rows=route_rows,
        ),
    )
    body_projection = _derive_exact_child(
        label="independent body-value projection",
        expected_type=IndependentBodyValueProjectionV1,
        producer=lambda: build_independent_body_value_projection(
            bundle,
            expected_raw_authority_bundle_sha256=raw_pin,
            ownership_authority=ownership,
            expected_ownership_receipt_sha256=ownership_pin,
            plan=plan,
            expected_plan_sha256=plan_pin,
            body_blob_inventory=inventory,
            expected_body_blob_inventory_sha256=body_inventory_pin,
            body_blob_inventory_readback_receipt=inventory_readback,
            expected_body_blob_inventory_readback_receipt_sha256=body_readback_pin,
            declared_bodyless_packets=packets,
            expected_declared_bodyless_packet_authority_sha256s=bodyless_packet_pins,
            declared_bodyless_readback_receipts=packet_readbacks,
            expected_declared_bodyless_readback_receipt_sha256s=bodyless_readback_pins,
            declared_bodyless_packet_bytes=packet_bytes,
            known_secrets=secrets,
        ),
    )
    equality = _derive_exact_child(
        label="value-projection equality receipt",
        expected_type=ValueProjectionEqualityReceiptV1,
        producer=lambda: ValueProjectionEqualityReceiptV1.build(
            expected_raw_authority_bundle_sha256=raw_pin,
            expected_ownership_receipt_sha256=ownership_pin,
            expected_plan_sha256=plan_pin,
            body_projection=body_projection.projection,
            expected_body_projection_sha256=(body_projection.projection.projection_sha256),
            body_partitions=body_projection.partitions,
            body_items=body_projection.items,
            public_projection=public_projection.projection,
            expected_public_projection_sha256=(public_projection.projection.projection_sha256),
            public_partitions=public_projection.partitions,
            public_items=public_projection.items,
        ),
    )

    inputs = W2OperationBuildInputsV1(
        raw_bundle=bundle,
        expected_raw_authority_bundle_sha256=raw_pin,
        raw_observations=bundle.observations,
        committed_staging_readbacks=readbacks,
        expected_committed_staging_readback_sha256s=readback_pins,
        body_value_projection_receipt=body_projection.receipt,
        expected_body_value_projection_receipt_sha256=body_projection.receipt.receipt_sha256,
        body_projection=body_projection.projection,
        expected_body_projection_sha256=body_projection.projection.projection_sha256,
        body_partitions=body_projection.partitions,
        body_items=body_projection.items,
        ownership_receipt=ownership.receipt,
        expected_ownership_receipt_sha256=ownership.receipt.receipt_sha256,
        expected_unit_inventory=ownership.expected_unit_inventory,
        representation_assignments=ownership.representation_assignments,
        ownership_observations=ownership.observations,
        ownership_partitions=ownership.partitions,
        ownership_bindings=ownership.bindings,
        result_cell_authority_receipt=result_authority,
        expected_result_cell_authority_sha256=result_authority.authority_sha256,
        stats_lossless_authorities=stats_authorities,
        expected_stats_lossless_authority_sha256s=stats_pins,
        live_lossless_authority=live_authority,
        expected_live_lossless_authority_receipt_sha256=(live_authority.receipt.receipt_sha256),
        body_blob_inventory=inventory,
        expected_body_blob_inventory_sha256=body_inventory_pin,
        body_blob_inventory_readback_receipt=inventory_readback,
        expected_body_blob_inventory_readback_receipt_sha256=body_readback_pin,
        declared_bodyless_packets=packets,
        expected_declared_bodyless_packet_authority_sha256s=bodyless_packet_pins,
        declared_bodyless_readback_receipts=packet_readbacks,
        expected_declared_bodyless_readback_receipt_sha256s=bodyless_readback_pins,
        declared_bodyless_packet_bytes=packet_bytes,
        plan=plan,
        expected_plan_sha256=plan.plan_sha256,
        route_field_landing_receipt=route_authority.receipt,
        expected_route_field_landing_receipt_sha256=route_authority.receipt.receipt_sha256,
        route_landing_receipts=route_receipts,
        expected_route_landing_receipt_sha256s=route_receipt_pins,
        canonical_alias_receipts=alias_receipts,
        expected_canonical_alias_receipt_sha256s=alias_receipt_pins,
        route_field_landing_authority_rows=route_authority.rows,
        public_table_value_projection_receipt=public_projection.receipt,
        expected_public_table_value_projection_receipt_sha256=(
            public_projection.receipt.receipt_sha256
        ),
        public_projection=public_projection.projection,
        expected_public_projection_sha256=public_projection.projection.projection_sha256,
        public_partitions=public_projection.partitions,
        public_items=public_projection.items,
        value_projection_equality_receipt=equality,
        expected_value_projection_equality_receipt_sha256=equality.receipt_sha256,
        result_cell_schema_sha256=RAW_NBA_API_RESULT_CELL_SCHEMA_SHA256,
        result_cell_rows=result_rows,
        stats_lossless_schema_sha256=STATS_LOSSLESS_RECORD_SCHEMA_SHA256,
        stats_lossless_rows=stats_rows,
        live_lossless_schema_sha256=LIVE_LOSSLESS_NODE_SCHEMA_SHA256,
        live_lossless_rows=live_rows,
        value_representation_schema_sha256=RAW_NBA_API_VALUE_REPRESENTATION_SCHEMA_SHA256,
        value_representation_rows=assignment_rows,
        route_field_landing_schema_sha256=RAW_NBA_API_ROUTE_FIELD_LANDING_SCHEMA_SHA256,
        route_field_landing_rows=route_rows,
        expected_w2_operation_schema_sha256=RAW_NBA_API_W2_OPERATION_SCHEMA_SHA256,
        known_secrets=secrets,
    )
    return W2SourceCallCandidateV1(
        logical_call_binding=binding,
        raw_authority_persistence_receipt=raw_persistence,
        expected_raw_authority_persistence_receipt_sha256=raw_persistence_pin,
        operation_inputs=inputs,
    )
