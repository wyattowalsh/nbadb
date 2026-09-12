"""Prepare one production W2 candidate from durable per-call authorities.

This boundary owns the effectful readback work which must happen after staging
and Raw Authority V2 commit but before a logical call may be marked complete.
It persists and re-reads body-bearing and declared-bodyless source bytes,
derives typed route receipts from committed Arrow bytes, and delegates the
final pure composition to :mod:`nbadb.orchestrate.w2_source_call_builder`.

The function deliberately accepts stores and pins explicitly.  It neither
constructs implicit filesystem roots nor mutates the Raw Authority manifest,
capture completion state, or pipeline journal.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Never, cast

from nbadb.contracts.body_blob_inventory import build_body_blob_inventory
from nbadb.contracts.declared_bodyless_packet import build_declared_bodyless_packet
from nbadb.contracts.field_fate_structure import (
    FieldFateStructureV1,
    derive_conditional_route_occurrence_authority,
    validate_field_fate_structure,
)
from nbadb.contracts.raw_request_authority import (
    RawRequestAuthorityBundleV2,
    RequestObservationV2,
    validate_raw_request_authority_bundle,
)
from nbadb.contracts.raw_request_observation_order import (
    canonical_raw_request_observations,
)
from nbadb.contracts.raw_request_reconstruction import LiveSnapshotPlanAuthorityV2
from nbadb.contracts.route_field_canonical_alias import (
    RouteFieldCanonicalAliasReceiptV1,
)
from nbadb.contracts.typed_field_value_receipt import (
    RouteFieldLandingReceiptV2,
)
from nbadb.extract.bronze import (
    STATIC_INPUT_REPRESENTATION,
    CapturedParserInput,
    LogicalCallReceiptBinding,
    RecordedParserInput,
)
from nbadb.orchestrate.body_blob_store import BodyBlobStore
from nbadb.orchestrate.declared_bodyless_packet_store import (
    DeclaredBodylessPacketStore,
)
from nbadb.orchestrate.raw_request_store import (
    RawRequestAuthorityPersistenceReceiptV2,
)
from nbadb.orchestrate.staging_batches import CommittedStagingFrameReadbackV2
from nbadb.orchestrate.w2_source_call_builder import build_w2_source_call_candidate

if TYPE_CHECKING:
    from nbadb.contracts.declared_bodyless_packet_types import (
        DeclaredBodylessPacketReadbackReceiptV1,
        DeclaredBodylessPacketV1,
    )
    from nbadb.orchestrate.w2_operation_coordinator import W2SourceCallCandidateV1

__all__ = [
    "W2SourceCallPreparationRuntime",
    "W2SourceCallPreparationError",
    "prepare_w2_source_call_candidate",
]


class W2SourceCallPreparationError(RuntimeError):
    """Durable source evidence cannot be prepared as one exact W2 call."""


def _fail(message: str) -> Never:
    raise W2SourceCallPreparationError(message) from None


@dataclass(frozen=True, slots=True)
class W2SourceCallPreparationRuntime:
    """Explicit run-owned stores and structural authority for W2 preparation."""

    body_blob_store: BodyBlobStore
    declared_bodyless_packet_store: DeclaredBodylessPacketStore
    field_fate: FieldFateStructureV1
    known_secrets: tuple[str | bytes, ...] = ()

    def __post_init__(self) -> None:
        if type(self.body_blob_store) is not BodyBlobStore:
            _fail("W2 runtime body-blob store has a foreign exact type")
        if type(self.declared_bodyless_packet_store) is not DeclaredBodylessPacketStore:
            _fail("W2 runtime declared-bodyless store has a foreign exact type")
        if type(self.field_fate) is not FieldFateStructureV1:
            _fail("W2 runtime field-fate structure has a foreign exact type")
        if type(self.known_secrets) is not tuple or any(
            type(item) not in {str, bytes} for item in self.known_secrets
        ):
            _fail("W2 runtime known-secret inventory has a foreign exact type")
        try:
            # A production runtime is bound to the already compiled structure
            # supplied by its caller.  Revalidation must not silently widen
            # that authority through an ambient developer-checkout variable.
            validate_field_fate_structure(self.field_fate, upstream_root="")
        except Exception:
            _fail("W2 runtime field-fate structure differs from current authority")

    def prepare(
        self,
        *,
        logical_call_binding: object,
        raw_authority_persistence_receipt: object,
        expected_raw_authority_persistence_receipt_sha256: object,
        raw_bundle: object,
        expected_raw_authority_bundle_sha256: object,
        committed_staging_readbacks: object,
        expected_committed_staging_readback_sha256s: object,
        recorded_static_attempts: object,
        live_plan_bindings: object = (),
    ) -> W2SourceCallCandidateV1:
        """Prepare one call without exposing the runtime's store roots."""

        return prepare_w2_source_call_candidate(
            logical_call_binding=logical_call_binding,
            raw_authority_persistence_receipt=raw_authority_persistence_receipt,
            expected_raw_authority_persistence_receipt_sha256=(
                expected_raw_authority_persistence_receipt_sha256
            ),
            raw_bundle=raw_bundle,
            expected_raw_authority_bundle_sha256=expected_raw_authority_bundle_sha256,
            committed_staging_readbacks=committed_staging_readbacks,
            expected_committed_staging_readback_sha256s=(
                expected_committed_staging_readback_sha256s
            ),
            body_blob_store=self.body_blob_store,
            declared_bodyless_packet_store=self.declared_bodyless_packet_store,
            recorded_static_attempts=recorded_static_attempts,
            field_fate=self.field_fate,
            live_plan_bindings=live_plan_bindings,
            known_secrets=self.known_secrets,
        )


def _sha256(value: object, *, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        _fail(f"{label} must be one exact lowercase SHA-256")
    return value


def _selected_observations(
    bundle: RawRequestAuthorityBundleV2,
) -> tuple[RequestObservationV2, ...]:
    try:
        ordered = canonical_raw_request_observations(bundle.observations)
    except Exception:
        _fail("Raw Authority V2 observations lack canonical order")
    selected = tuple(item for item in ordered if item.lifecycle == "selected_terminal")
    if not selected:
        _fail("W2 source call lacks one selected terminal observation")
    return selected


def _declared_bodyless_evidence(
    *,
    observations: tuple[RequestObservationV2, ...],
    recorded_static_attempts: tuple[RecordedParserInput, ...],
    store: DeclaredBodylessPacketStore,
    known_secrets: tuple[str | bytes, ...],
) -> tuple[
    tuple[DeclaredBodylessPacketV1, ...],
    tuple[DeclaredBodylessPacketReadbackReceiptV1, ...],
    tuple[bytes, ...],
]:
    selected = tuple(item for item in observations if item.body_disposition == "declared_bodyless")
    if any(item.attempt.source_family != "static" for item in selected):
        _fail("declared-bodyless authority is restricted to exact static observations")
    by_receipt: dict[str, RecordedParserInput] = {}
    for recorded in recorded_static_attempts:
        if type(recorded) is not RecordedParserInput:
            _fail("recorded static attempt inventory contains a foreign type")
        if recorded.receipt_sha256 in by_receipt:
            _fail("recorded static attempt inventory duplicates one receipt")
        by_receipt[recorded.receipt_sha256] = recorded

    packets: list[DeclaredBodylessPacketV1] = []
    readbacks: list[DeclaredBodylessPacketReadbackReceiptV1] = []
    packet_bytes: list[bytes] = []
    consumed: set[str] = set()
    for observation in selected:
        receipt_sha256 = observation.capture_response_receipt_sha256
        if receipt_sha256 is None:
            _fail("declared-bodyless observation lacks its capture receipt")
        recorded = by_receipt.get(receipt_sha256)
        if recorded is None:
            _fail("declared-bodyless observation lacks exact captured packet bytes")
        captured = recorded.captured
        raw = recorded.parser_input
        attempt = observation.attempt
        expected_private_outcome = (
            "success_nonempty"
            if any(item.row_count for item in recorded.result_sets)
            else "success_empty"
        )
        if (
            type(captured) is not CapturedParserInput
            or type(raw) is not bytes
            or recorded.transport_kind != "static_provider_snapshot"
            or recorded.source_family != "static"
            or recorded.endpoint_id != attempt.endpoint_id
            or recorded.parameters_sha256 != attempt.safe_parameters_sha256
            or recorded.provider_authority_sha256 != attempt.provider_authority_sha256
            or recorded.endpoint_contract_sha256 != attempt.endpoint_contract_sha256
            or recorded.status_code is not None
            or recorded.outcome != expected_private_outcome
            or captured.representation != STATIC_INPUT_REPRESENTATION
            or captured.response_sha256 != hashlib.sha256(raw).hexdigest()
            or captured.uncompressed_bytes != len(raw)
        ):
            _fail("recorded static packet differs from its selected observation authority")
        try:
            packet = build_declared_bodyless_packet(
                observation=observation,
                expected_observation_sha256=attempt.observation_sha256,
                expected_observation_record_sha256=observation.observation_record_sha256,
                packet_bytes=raw,
                known_secrets=known_secrets,
            )
            readback = store.persist(
                packet=packet,
                packet_bytes=raw,
                expected_observation_sha256=attempt.observation_sha256,
                expected_observation_record_sha256=observation.observation_record_sha256,
                expected_packet_authority_sha256=packet.packet_authority_sha256,
                known_secrets=known_secrets,
            )
            exact_bytes = store.readback(
                receipt=readback,
                packet=packet,
                packet_bytes=raw,
                expected_observation_sha256=attempt.observation_sha256,
                expected_observation_record_sha256=observation.observation_record_sha256,
                expected_packet_authority_sha256=packet.packet_authority_sha256,
                expected_receipt_sha256=readback.receipt_sha256,
                known_secrets=known_secrets,
            )
        except Exception:
            _fail("declared-bodyless packet persistence or readback failed")
        consumed.add(receipt_sha256)
        packets.append(packet)
        readbacks.append(readback)
        packet_bytes.append(exact_bytes)
    if consumed != set(by_receipt):
        _fail("recorded static attempt inventory contains a foreign or unselected receipt")
    return tuple(packets), tuple(readbacks), tuple(packet_bytes)


def _live_plan_index(
    value: object,
    *,
    observations: tuple[RequestObservationV2, ...],
) -> dict[str, tuple[LiveSnapshotPlanAuthorityV2, str]]:
    if type(value) is not tuple:
        _fail("live-plan bindings must be one exact tuple")
    indexed: dict[str, tuple[LiveSnapshotPlanAuthorityV2, str]] = {}
    for item in value:
        if type(item) is not tuple or len(item) != 2:
            _fail("live-plan binding has a foreign shape")
        plan, expected_sha256 = item
        if type(plan) is not LiveSnapshotPlanAuthorityV2:
            _fail("live-plan binding has a foreign authority type")
        expected = _sha256(expected_sha256, label="expected live-plan authority")
        exact_plan = plan
        if expected != exact_plan.authority_sha256:
            _fail("live-plan binding differs from its external pin")
        if exact_plan.observation_sha256 in indexed:
            _fail("live-plan binding inventory duplicates one observation")
        indexed[exact_plan.observation_sha256] = (exact_plan, expected)
    expected_observations = {
        item.attempt.observation_sha256
        for item in observations
        if item.attempt.source_family == "live"
    }
    if set(indexed) != expected_observations:
        _fail("live-plan bindings do not exactly cover selected live observations")
    return indexed


def _route_evidence(
    *,
    bundle: RawRequestAuthorityBundleV2,
    observations: tuple[RequestObservationV2, ...],
    committed_readbacks: tuple[CommittedStagingFrameReadbackV2, ...],
    field_fate: FieldFateStructureV1,
    live_plan_bindings: object,
) -> tuple[
    tuple[RouteFieldLandingReceiptV2, ...],
    tuple[RouteFieldCanonicalAliasReceiptV1, ...],
]:
    selected_ids = {item.attempt.observation_sha256 for item in observations}
    plan_index = _live_plan_index(live_plan_bindings, observations=observations)
    route_receipts: list[RouteFieldLandingReceiptV2] = []
    for readback in committed_readbacks:
        receipt = readback.committed_receipt
        landing_rows = tuple(
            item
            for item in bundle.landings
            if item.observation_sha256 in selected_ids
            and item.route_id == receipt.result_route_id
            and item.receipt_root_sha256 == receipt.receipt_root_sha256
        )
        if not landing_rows:
            _fail("committed readback lacks one exact selected Raw V2 route landing")
        semantics = {item.landing_semantic for item in landing_rows}
        if semantics == {"response_canonical_alias"}:
            continue
        if "response_canonical_alias" in semantics or len(semantics) != 1:
            _fail("committed route mixes direct and alias landing semantics")
        per_route_plans = tuple(
            plan_index[item.observation_sha256]
            for item in landing_rows
            if item.observation_sha256 in plan_index
        )
        conditional = None
        if semantics == {"conditional_lossless"}:
            try:
                conditional = derive_conditional_route_occurrence_authority(
                    structure=field_fate,
                    route_id=receipt.result_route_id,
                    raw_bundle=bundle,
                    readback=readback,
                )
            except Exception:
                _fail("conditional route occurrence authority cannot be derived")
        try:
            route_receipts.append(
                RouteFieldLandingReceiptV2.build_from_authorities(
                    readback=readback,
                    raw_bundle=bundle,
                    field_fate=field_fate,
                    conditional_authority=conditional,
                    live_plan_bindings=per_route_plans,
                )
            )
        except Exception:
            _fail("typed route-field landing authority cannot be derived")

    direct_landings = tuple(
        item
        for item in bundle.landings
        if item.observation_sha256 in selected_ids
        and item.landing_semantic != "response_canonical_alias"
    )
    aliases: list[RouteFieldCanonicalAliasReceiptV1] = []
    for landing in bundle.landings:
        if (
            landing.observation_sha256 not in selected_ids
            or landing.landing_semantic != "response_canonical_alias"
        ):
            continue
        try:
            aliases.append(
                RouteFieldCanonicalAliasReceiptV1.build(
                    raw_authority_bundle_sha256=bundle.bundle_sha256,
                    alias_landing=landing,
                    target_landings=direct_landings,
                    target_route_receipts=tuple(route_receipts),
                )
            )
        except Exception:
            _fail("canonical alias route authority cannot be derived")
    return tuple(route_receipts), tuple(aliases)


def prepare_w2_source_call_candidate(
    *,
    logical_call_binding: object,
    raw_authority_persistence_receipt: object,
    expected_raw_authority_persistence_receipt_sha256: object,
    raw_bundle: object,
    expected_raw_authority_bundle_sha256: object,
    committed_staging_readbacks: object,
    expected_committed_staging_readback_sha256s: object,
    body_blob_store: object,
    declared_bodyless_packet_store: object,
    recorded_static_attempts: object,
    field_fate: object,
    live_plan_bindings: object = (),
    known_secrets: tuple[str | bytes, ...] = (),
) -> W2SourceCallCandidateV1:
    """Prepare and independently derive every child of one W2 candidate."""

    if type(logical_call_binding) is not LogicalCallReceiptBinding:
        _fail("logical-call binding has a foreign exact type")
    if type(raw_authority_persistence_receipt) is not RawRequestAuthorityPersistenceReceiptV2:
        _fail("Raw Authority V2 persistence receipt has a foreign exact type")
    if type(raw_bundle) is not RawRequestAuthorityBundleV2:
        _fail("Raw Authority V2 bundle has a foreign exact type")
    if type(committed_staging_readbacks) is not tuple or any(
        type(item) is not CommittedStagingFrameReadbackV2 for item in committed_staging_readbacks
    ):
        _fail("committed staging readbacks have a foreign exact type")
    if type(expected_committed_staging_readback_sha256s) is not tuple:
        _fail("committed staging readback pins must be one exact tuple")
    if type(body_blob_store) is not BodyBlobStore:
        _fail("body-blob store has a foreign exact type")
    if type(declared_bodyless_packet_store) is not DeclaredBodylessPacketStore:
        _fail("declared-bodyless store has a foreign exact type")
    if type(recorded_static_attempts) is not tuple:
        _fail("recorded static attempts must be one exact tuple")
    if type(field_fate) is not FieldFateStructureV1:
        _fail("field-fate structure has a foreign exact type")
    if type(known_secrets) is not tuple or any(
        type(item) not in {str, bytes} for item in known_secrets
    ):
        _fail("known-secret inventory must be one exact string-or-bytes tuple")

    bundle_pin = _sha256(
        expected_raw_authority_bundle_sha256,
        label="expected Raw Authority V2 bundle",
    )
    persistence_pin = _sha256(
        expected_raw_authority_persistence_receipt_sha256,
        label="expected Raw Authority V2 persistence receipt",
    )
    readback_pins = tuple(
        _sha256(item, label="expected committed staging readback")
        for item in expected_committed_staging_readback_sha256s
    )
    bundle = raw_bundle
    persistence = raw_authority_persistence_receipt
    readbacks = cast(
        "tuple[CommittedStagingFrameReadbackV2, ...]",
        committed_staging_readbacks,
    )
    if (
        bundle.bundle_sha256 != bundle_pin
        or persistence.bundle_sha256 != bundle_pin
        or persistence.receipt_sha256 != persistence_pin
        or tuple(item.readback_receipt_sha256 for item in readbacks) != readback_pins
    ):
        _fail("committed W2 source roots differ from their external pins")
    try:
        if validate_raw_request_authority_bundle(bundle) != bundle:
            _fail("Raw Authority V2 bundle changes on exact validation")
        validate_field_fate_structure(field_fate, upstream_root="")
    except W2SourceCallPreparationError:
        raise
    except Exception:
        _fail("W2 source roots fail exact contract validation")

    observations = _selected_observations(bundle)
    try:
        inventory = build_body_blob_inventory(
            bundle,
            expected_raw_authority_bundle_sha256=bundle_pin,
            known_secrets=known_secrets,
        )
        inventory_readback = body_blob_store.seal_inventory(
            bundle=bundle,
            inventory=inventory,
            expected_raw_authority_bundle_sha256=bundle_pin,
            expected_inventory_sha256=inventory.inventory_sha256,
            known_secrets=known_secrets,
        )
        inventory_readback = body_blob_store.readback_inventory(
            bundle=bundle,
            inventory=inventory,
            receipt=inventory_readback,
            expected_raw_authority_bundle_sha256=bundle_pin,
            expected_inventory_sha256=inventory.inventory_sha256,
            expected_receipt_sha256=inventory_readback.receipt_sha256,
            known_secrets=known_secrets,
        )
    except Exception:
        _fail("body-blob inventory persistence or exact readback failed")

    packets, packet_readbacks, packet_bytes = _declared_bodyless_evidence(
        observations=observations,
        recorded_static_attempts=cast("tuple[RecordedParserInput, ...]", recorded_static_attempts),
        store=declared_bodyless_packet_store,
        known_secrets=known_secrets,
    )
    route_receipts, aliases = _route_evidence(
        bundle=bundle,
        observations=observations,
        committed_readbacks=readbacks,
        field_fate=field_fate,
        live_plan_bindings=live_plan_bindings,
    )
    return build_w2_source_call_candidate(
        logical_call_binding=logical_call_binding,
        raw_authority_persistence_receipt=persistence,
        expected_raw_authority_persistence_receipt_sha256=persistence_pin,
        raw_bundle=bundle,
        expected_raw_authority_bundle_sha256=bundle_pin,
        committed_staging_readbacks=readbacks,
        expected_committed_staging_readback_sha256s=readback_pins,
        body_blob_inventory=inventory,
        expected_body_blob_inventory_sha256=inventory.inventory_sha256,
        body_blob_inventory_readback_receipt=inventory_readback,
        expected_body_blob_inventory_readback_receipt_sha256=(inventory_readback.receipt_sha256),
        declared_bodyless_packets=packets,
        expected_declared_bodyless_packet_authority_sha256s=tuple(
            item.packet_authority_sha256 for item in packets
        ),
        declared_bodyless_readback_receipts=packet_readbacks,
        expected_declared_bodyless_readback_receipt_sha256s=tuple(
            item.receipt_sha256 for item in packet_readbacks
        ),
        declared_bodyless_packet_bytes=packet_bytes,
        route_landing_receipts=route_receipts,
        expected_route_landing_receipt_sha256s=tuple(
            item.landing_receipt_sha256 for item in route_receipts
        ),
        canonical_alias_receipts=aliases,
        expected_canonical_alias_receipt_sha256s=tuple(item.receipt_sha256 for item in aliases),
        known_secrets=known_secrets,
    )
