"""Independent reconstruction of exact public raw-request authority.

This module deliberately consumes only the four immutable public object,
observation, result-occurrence, and route-landing contracts.  It does not query
staging, private Bronze receipts, provider clients, or the filesystem.  The
verifier reconstructs exact parser bytes when a public body exists and
otherwise keeps bodylessness explicit.  Result packets and route landings are
deterministic structural graphs; they never synthesize provider rows, parent
nodes, or route membership that was not observed.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field, fields, replace
from datetime import datetime
from typing import TYPE_CHECKING, ClassVar, Never, cast

from nbadb.contracts.raw_request_authority import (
    ObservationRouteLandingV2,
    ParserInputObjectV2,
    RawRequestAuthorityBundleV2,
    RawRequestAuthorityError,
    RequestAttemptIdentityV2,
    RequestObservationV2,
    ResultContainerKind,
    ResultOccurrenceV2,
    ResultPresence,
    RouteAuthorityKind,
    RouteLandingSemantic,
    canonical_json_bytes,
    decode_parser_input_object,
    validate_logical_provider_parameter_join,
    validate_observation_route_landing,
    validate_parser_input_object,
    validate_raw_request_authority_bundle,
    validate_request_attempt_identity,
    validate_request_observation,
    validate_result_occurrence,
)
from nbadb.core.nba_api_runtime_contract import (
    pinned_live_contracts,
    pinned_runtime_contracts,
    pinned_static_dataset_contract,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

__all__ = [
    "RawRequestReconstructionError",
    "RawRequestReconstructionV2",
    "LiveSnapshotPlanAuthorityV2",
    "ReconstructedParserInputV2",
    "ReconstructedProviderResultPacketV2",
    "ReconstructedRouteLandingV2",
    "reconstruct_parser_input_authority",
    "reconstruct_provider_result_packets",
    "reconstruct_route_landings",
    "reconstruct_raw_request_authority",
    "validate_raw_request_reconstruction",
]

_MAX_SEALED_PLAN_BYTES = 16 * 1024 * 1024


class RawRequestReconstructionError(RawRequestAuthorityError):
    """Raised when public authority cannot be reconstructed exactly."""


def _fail(message: str) -> Never:
    raise RawRequestReconstructionError(message)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha256(value: object) -> str:
    return _sha256(canonical_json_bytes(value))


def _safe_observation(value: object) -> RequestObservationV2:
    if type(value) is not RequestObservationV2:
        _fail("request observation does not have its exact contract type")
    try:
        return validate_request_observation(value)
    except (TypeError, ValueError) as exc:
        raise RawRequestReconstructionError(
            "request observation failed strict reconstruction validation"
        ) from exc


def _safe_object(value: object) -> ParserInputObjectV2:
    if type(value) is not ParserInputObjectV2:
        _fail("parser-input object does not have its exact contract type")
    try:
        return validate_parser_input_object(value)
    except (TypeError, ValueError) as exc:
        raise RawRequestReconstructionError(
            "parser-input object failed strict reconstruction validation"
        ) from exc


def _safe_occurrence(value: object) -> ResultOccurrenceV2:
    if type(value) is not ResultOccurrenceV2:
        _fail("result occurrence does not have its exact contract type")
    try:
        return validate_result_occurrence(value)
    except (TypeError, ValueError) as exc:
        raise RawRequestReconstructionError(
            "result occurrence failed strict reconstruction validation"
        ) from exc


def _safe_landing(value: object) -> ObservationRouteLandingV2:
    if type(value) is not ObservationRouteLandingV2:
        _fail("route landing does not have its exact contract type")
    try:
        return validate_observation_route_landing(value)
    except (TypeError, ValueError) as exc:
        raise RawRequestReconstructionError(
            "route landing failed strict reconstruction validation"
        ) from exc


def _safe_plan_authority(
    value: object,
    *,
    expected_authority_sha256: object,
) -> LiveSnapshotPlanAuthorityV2:
    if type(value) is not LiveSnapshotPlanAuthorityV2:
        _fail("live reconstruction lacks its exact plan-authority type")
    expected = _require_sha256(
        expected_authority_sha256,
        label="independent live plan authority",
    )
    try:
        rebuilt = LiveSnapshotPlanAuthorityV2(
            authority_sha256=value.authority_sha256,
            sealed_plan_bytes=value.sealed_plan_bytes,
            sealed_plan_sha256=value.sealed_plan_sha256,
            sealed_plan_length=value.sealed_plan_length,
            source_sha=value.source_sha,
            run_id=value.run_id,
            run_attempt=value.run_attempt,
            chain_id=value.chain_id,
            lane_id=value.lane_id,
            observation_sha256=value.observation_sha256,
            scope_sha256=value.scope_sha256,
            safe_parameters_sha256=value.safe_parameters_sha256,
            endpoint_id=value.endpoint_id,
            endpoint_contract_sha256=value.endpoint_contract_sha256,
            provider_authority_sha256=value.provider_authority_sha256,
            route_ids=value.route_ids,
            live_snapshot_at=value.live_snapshot_at,
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise RawRequestReconstructionError(
            "live plan authority failed strict reconstruction validation"
        ) from exc
    if rebuilt != value or rebuilt.authority_sha256 != expected:
        _fail("live plan authority differs from its independent sealed receipt")
    return rebuilt


def _validated_single_observation_bundle(
    body_object: ParserInputObjectV2 | None,
    observation: RequestObservationV2,
    occurrences: tuple[ResultOccurrenceV2, ...],
    landings: tuple[ObservationRouteLandingV2, ...],
) -> RawRequestAuthorityBundleV2:
    if body_object is not None and type(body_object) is not ParserInputObjectV2:
        _fail("parser-input object does not have its exact contract type")
    if type(observation) is not RequestObservationV2:
        _fail("request observation does not have its exact contract type")
    if type(occurrences) is not tuple:
        _fail("result occurrences must be supplied as an exact tuple")
    if type(landings) is not tuple:
        _fail("route landings must be supplied as an exact tuple")
    try:
        bundle = RawRequestAuthorityBundleV2.build(
            objects=() if body_object is None else (body_object,),
            observations=(observation,),
            occurrences=occurrences,
            landings=landings,
        )
        parsed = validate_raw_request_authority_bundle(bundle)
    except (TypeError, ValueError) as exc:
        raise RawRequestReconstructionError(
            "four-table raw authority cannot be reconstructed exactly"
        ) from exc
    if (
        type(parsed) is not RawRequestAuthorityBundleV2
        or len(parsed.observations) != 1
        or parsed.observations[0] != observation
        or parsed.objects != (() if body_object is None else (body_object,))
        or parsed.occurrences != occurrences
        or parsed.landings != landings
    ):
        _fail("four-table raw authority changed during strict reconstruction")
    return parsed


def _validated_live_plan_authority_sha256(
    bundle: RawRequestAuthorityBundleV2,
    *,
    live_plan_authority: LiveSnapshotPlanAuthorityV2 | None,
    expected_live_plan_authority_sha256: str | None,
) -> str | None:
    observation = bundle.observations[0]
    if observation.attempt.source_family != "live" or not bundle.landings:
        if live_plan_authority is not None or expected_live_plan_authority_sha256 is not None:
            _fail("non-live or bodyless reconstruction received live plan authority")
        return None
    parsed = _safe_plan_authority(
        live_plan_authority,
        expected_authority_sha256=expected_live_plan_authority_sha256,
    )
    attempt = observation.attempt
    snapshot_values = {landing.live_snapshot_at for landing in bundle.landings}
    if len(snapshot_values) != 1 or None in snapshot_values:
        _fail("live route landings lack one exact snapshot time")
    snapshot_at = next(iter(snapshot_values))
    if (
        parsed.source_sha != attempt.source_sha
        or parsed.run_id != attempt.run_id
        or parsed.run_attempt != attempt.run_attempt
        or parsed.chain_id != attempt.chain_id
        or parsed.lane_id != attempt.lane_id
        or parsed.observation_sha256 != attempt.observation_sha256
        or parsed.scope_sha256 != attempt.scope_sha256
        or parsed.safe_parameters_sha256 != attempt.safe_parameters_sha256
        or parsed.endpoint_id != attempt.endpoint_id
        or parsed.endpoint_contract_sha256 != attempt.endpoint_contract_sha256
        or parsed.provider_authority_sha256 != attempt.provider_authority_sha256
        or parsed.route_ids != tuple(landing.route_id for landing in bundle.landings)
        or parsed.live_snapshot_at != snapshot_at
    ):
        _fail("live plan authority crosses its exact request or route inventory")
    return parsed.authority_sha256


def _canonical_list(encoded: str, *, label: str) -> list[object]:
    if type(encoded) is not str:
        _fail(f"{label} is not exact canonical JSON text")
    try:
        value = json.loads(encoded)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RawRequestReconstructionError(f"{label} cannot be decoded") from exc
    if type(value) is not list or canonical_json_bytes(value).decode("utf-8") != encoded:
        _fail(f"{label} is not an exact canonical list")
    return cast("list[object]", value)


def _require_sha256(value: object, *, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        _fail(f"{label} is not a lowercase SHA-256")
    return value


def _require_source_sha(value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        _fail("live plan semantic source is not an exact commit SHA")
    return value


def _require_plan_id(value: object, *, label: str) -> str:
    if (
        type(value) is not str
        or not value
        or len(value) > 512
        or value.strip() != value
        or any(
            character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-"
            for character in value
        )
    ):
        _fail(f"{label} is not exact safe identity text")
    return value


@dataclass(frozen=True, slots=True)
class LiveSnapshotPlanAuthorityV2:
    """Exact sealed-plan projection required to trust one live as-of instant.

    ``expected_live_plan_authority_sha256`` is supplied separately to the
    reconstruction entry point from the sealed-plan/control-plane receipt.  A
    caller cannot promote this self-contained projection by reading its own
    digest back as independent authority.
    """

    authority_sha256: str
    sealed_plan_bytes: bytes = field(repr=False)
    sealed_plan_sha256: str
    sealed_plan_length: int
    source_sha: str
    run_id: int
    run_attempt: int
    chain_id: str
    lane_id: str
    observation_sha256: str
    scope_sha256: str
    safe_parameters_sha256: str
    endpoint_id: str
    endpoint_contract_sha256: str
    provider_authority_sha256: str
    route_ids: tuple[str, ...]
    live_snapshot_at: datetime

    schema_version: ClassVar[int] = 2
    kind: ClassVar[str] = "live_snapshot_plan_authority_v2"

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "sealed_plan_sha256": self.sealed_plan_sha256,
            "sealed_plan_length": self.sealed_plan_length,
            "source_sha": self.source_sha,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "chain_id": self.chain_id,
            "lane_id": self.lane_id,
            "observation_sha256": self.observation_sha256,
            "scope_sha256": self.scope_sha256,
            "safe_parameters_sha256": self.safe_parameters_sha256,
            "endpoint_id": self.endpoint_id,
            "endpoint_contract_sha256": self.endpoint_contract_sha256,
            "provider_authority_sha256": self.provider_authority_sha256,
            "route_ids": list(self.route_ids),
            "live_snapshot_at": _canonical_live_snapshot(self.live_snapshot_at),
        }

    def __post_init__(self) -> None:
        _require_sha256(self.authority_sha256, label="live plan authority digest")
        if (
            type(self.sealed_plan_bytes) is not bytes
            or not self.sealed_plan_bytes
            or len(self.sealed_plan_bytes) > _MAX_SEALED_PLAN_BYTES
        ):
            _fail("sealed plan bytes are absent or exceed their exact bound")
        _require_sha256(self.sealed_plan_sha256, label="sealed plan digest")
        if (
            type(self.sealed_plan_length) is not int
            or self.sealed_plan_length != len(self.sealed_plan_bytes)
            or _sha256(self.sealed_plan_bytes) != self.sealed_plan_sha256
        ):
            _fail("sealed plan bytes differ from their exact digest or length")
        _require_source_sha(self.source_sha)
        if type(self.run_id) is not int or self.run_id < 1:
            _fail("live plan run ID is not positive")
        if type(self.run_attempt) is not int or self.run_attempt < 1:
            _fail("live plan run attempt is not positive")
        _require_plan_id(self.chain_id, label="live plan chain ID")
        _require_plan_id(self.lane_id, label="live plan lane ID")
        _require_plan_id(self.endpoint_id, label="live plan endpoint ID")
        for label, value in (
            ("live plan observation", self.observation_sha256),
            ("live plan scope", self.scope_sha256),
            ("live plan parameters", self.safe_parameters_sha256),
            ("live plan endpoint contract", self.endpoint_contract_sha256),
            ("live plan provider authority", self.provider_authority_sha256),
        ):
            _require_sha256(value, label=label)
        if (
            type(self.route_ids) is not tuple
            or not self.route_ids
            or len(self.route_ids) != len(set(self.route_ids))
        ):
            _fail("live plan route inventory is absent or duplicate")
        for route_id in self.route_ids:
            _require_plan_id(route_id, label="live plan route ID")
        _canonical_live_snapshot(self.live_snapshot_at)
        if self.authority_sha256 != _canonical_sha256(self.identity_payload()):
            _fail("live plan authority digest differs from its exact projection")

    @classmethod
    def build(
        cls,
        *,
        sealed_plan_bytes: bytes,
        attempt: RequestAttemptIdentityV2,
        route_ids: tuple[str, ...],
        live_snapshot_at: datetime,
    ) -> LiveSnapshotPlanAuthorityV2:
        if type(attempt) is not RequestAttemptIdentityV2:
            _fail("live plan attempt does not have its exact contract type")
        try:
            parsed_attempt = validate_request_attempt_identity(attempt)
        except (TypeError, ValueError) as exc:
            raise RawRequestReconstructionError(
                "live plan attempt failed strict validation"
            ) from exc
        if parsed_attempt.source_family != "live":
            _fail("live plan authority requires a live request attempt")
        plan_digest = _sha256(sealed_plan_bytes)
        values = {
            "sealed_plan_bytes": sealed_plan_bytes,
            "sealed_plan_sha256": plan_digest,
            "sealed_plan_length": len(sealed_plan_bytes),
            "source_sha": parsed_attempt.source_sha,
            "run_id": parsed_attempt.run_id,
            "run_attempt": parsed_attempt.run_attempt,
            "chain_id": parsed_attempt.chain_id,
            "lane_id": parsed_attempt.lane_id,
            "observation_sha256": parsed_attempt.observation_sha256,
            "scope_sha256": parsed_attempt.scope_sha256,
            "safe_parameters_sha256": parsed_attempt.safe_parameters_sha256,
            "endpoint_id": parsed_attempt.endpoint_id,
            "endpoint_contract_sha256": parsed_attempt.endpoint_contract_sha256,
            "provider_authority_sha256": parsed_attempt.provider_authority_sha256,
            "route_ids": route_ids,
            "live_snapshot_at": live_snapshot_at,
        }
        identity_payload = {
            "schema_version": cls.schema_version,
            "kind": cls.kind,
            "sealed_plan_sha256": plan_digest,
            "sealed_plan_length": len(sealed_plan_bytes),
            "source_sha": parsed_attempt.source_sha,
            "run_id": parsed_attempt.run_id,
            "run_attempt": parsed_attempt.run_attempt,
            "chain_id": parsed_attempt.chain_id,
            "lane_id": parsed_attempt.lane_id,
            "observation_sha256": parsed_attempt.observation_sha256,
            "scope_sha256": parsed_attempt.scope_sha256,
            "safe_parameters_sha256": parsed_attempt.safe_parameters_sha256,
            "endpoint_id": parsed_attempt.endpoint_id,
            "endpoint_contract_sha256": parsed_attempt.endpoint_contract_sha256,
            "provider_authority_sha256": parsed_attempt.provider_authority_sha256,
            "route_ids": list(route_ids),
            "live_snapshot_at": _canonical_live_snapshot(live_snapshot_at),
        }
        return cls(
            authority_sha256=_canonical_sha256(identity_payload),
            **values,
        )


@dataclass(frozen=True, slots=True)
class ReconstructedParserInputV2:
    """Verified body authority for one observation.

    ``parser_input_bytes`` is exact immutable provider input when present.
    Bodyless authority uses ``None`` for bytes, digest, and length rather than
    pretending that an empty byte string was observed.
    """

    observation_sha256: str
    body_disposition: str
    body_authority_receipt_sha256: str
    body_object_sha256: str | None
    bodyless_evidence_sha256: str | None
    parser_input_bytes: bytes | None
    parser_input_sha256: str | None
    parser_input_length: int | None

    schema_version: ClassVar[int] = 2
    kind: ClassVar[str] = "reconstructed_parser_input_v2"

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "observation_sha256": self.observation_sha256,
            "body_disposition": self.body_disposition,
            "body_authority_receipt_sha256": self.body_authority_receipt_sha256,
            "body_object_sha256": self.body_object_sha256,
            "bodyless_evidence_sha256": self.bodyless_evidence_sha256,
            "parser_input_sha256": self.parser_input_sha256,
            "parser_input_length": self.parser_input_length,
        }


@dataclass(frozen=True, slots=True)
class ReconstructedProviderResultPacketV2:
    """One deterministic provider-result structural packet.

    ``declared_parent_result_ordinal`` records pinned live topology.
    ``observed_parent_result_ordinal`` is populated only when at least one
    parent provider row was observed; it stays ``None`` for roots and for the
    explicit parent-empty child state.
    """

    packet_sha256: str
    occurrence_sha256: str
    occurrence_ordinal: int
    result_name: str
    duplicate_name_ordinal: int
    provider_result_ordinal: int | None
    canonical_result_ordinal: int | None
    json_path: str | None
    container_kind: ResultContainerKind
    presence: ResultPresence
    ordered_headers: tuple[str, ...]
    row_count: int
    cell_count: int
    node_count: int
    container_count: int
    missing_count: int
    null_count: int
    parent_state_sha256: str | None
    output_sha256: str
    declared_parent_result_ordinal: int | None
    observed_parent_result_ordinal: int | None
    canonical_route_ids: tuple[str, ...]
    committed_staging_receipts: tuple[tuple[str, str], ...]
    landing_disposition: str

    schema_version: ClassVar[int] = 2
    kind: ClassVar[str] = "reconstructed_provider_result_packet_v2"

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "occurrence_sha256": self.occurrence_sha256,
            "occurrence_ordinal": self.occurrence_ordinal,
            "result_name": self.result_name,
            "duplicate_name_ordinal": self.duplicate_name_ordinal,
            "provider_result_ordinal": self.provider_result_ordinal,
            "canonical_result_ordinal": self.canonical_result_ordinal,
            "json_path": self.json_path,
            "container_kind": self.container_kind,
            "presence": self.presence,
            "ordered_headers": list(self.ordered_headers),
            "row_count": self.row_count,
            "cell_count": self.cell_count,
            "node_count": self.node_count,
            "container_count": self.container_count,
            "missing_count": self.missing_count,
            "null_count": self.null_count,
            "parent_state_sha256": self.parent_state_sha256,
            "output_sha256": self.output_sha256,
            "declared_parent_result_ordinal": self.declared_parent_result_ordinal,
            "observed_parent_result_ordinal": self.observed_parent_result_ordinal,
            "canonical_route_ids": list(self.canonical_route_ids),
            "committed_staging_receipts": [
                {"route_id": route_id, "receipt_sha256": receipt_sha256}
                for route_id, receipt_sha256 in self.committed_staging_receipts
            ],
            "landing_disposition": self.landing_disposition,
        }


@dataclass(frozen=True, slots=True)
class ReconstructedRouteLandingV2:
    """One independently joined response-level route landing.

    The original landing digest is retained, while ``reconstruction_sha256``
    additionally binds the occurrence membership rederived from the public
    result table.  This makes a response-level zero-occurrence route visible
    without pretending that it belongs to a provider result packet.
    """

    reconstruction_sha256: str
    landing_sha256: str
    route_ordinal: int
    route_id: str
    staging_key: str
    route_authority_kind: RouteAuthorityKind
    route_authority_sha256: str
    landing_semantic: RouteLandingSemantic
    conditional_lossless: bool
    alias_target_route_id: str | None
    live_snapshot_at: str | None
    source_occurrence_sha256s: tuple[str, ...]
    chunk_id: str
    canonical_frame_format: str
    frame_content_hash_contract: str
    frame_schema_hash_contract: str
    content_hash: str
    persisted_row_count: int
    persisted_content_sha256: str
    persisted_schema_sha256: str
    logical_call_receipt_sha256: str
    provider_authority_sha256: str
    logical_parameters_sha256: str
    receipt_root_sha256: str

    schema_version: ClassVar[int] = 2
    kind: ClassVar[str] = "reconstructed_route_landing_v2"

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "landing_sha256": self.landing_sha256,
            "route_ordinal": self.route_ordinal,
            "route_id": self.route_id,
            "staging_key": self.staging_key,
            "route_authority_kind": self.route_authority_kind,
            "route_authority_sha256": self.route_authority_sha256,
            "landing_semantic": self.landing_semantic,
            "conditional_lossless": self.conditional_lossless,
            "alias_target_route_id": self.alias_target_route_id,
            "live_snapshot_at": self.live_snapshot_at,
            "source_occurrence_sha256s": list(self.source_occurrence_sha256s),
            "chunk_id": self.chunk_id,
            "canonical_frame_format": self.canonical_frame_format,
            "frame_content_hash_contract": self.frame_content_hash_contract,
            "frame_schema_hash_contract": self.frame_schema_hash_contract,
            "content_hash": self.content_hash,
            "persisted_row_count": self.persisted_row_count,
            "persisted_content_sha256": self.persisted_content_sha256,
            "persisted_schema_sha256": self.persisted_schema_sha256,
            "logical_call_receipt_sha256": self.logical_call_receipt_sha256,
            "provider_authority_sha256": self.provider_authority_sha256,
            "logical_parameters_sha256": self.logical_parameters_sha256,
            "receipt_root_sha256": self.receipt_root_sha256,
        }


@dataclass(frozen=True, slots=True)
class RawRequestReconstructionV2:
    """Closed deterministic reconstruction for one request observation."""

    reconstruction_sha256: str
    observation_record_sha256: str
    public_authority_receipt_sha256: str
    parser_input: ReconstructedParserInputV2
    result_packets: tuple[ReconstructedProviderResultPacketV2, ...]
    route_landings: tuple[ReconstructedRouteLandingV2, ...]
    live_plan_authority_sha256: str | None

    schema_version: ClassVar[int] = 2
    kind: ClassVar[str] = "raw_request_reconstruction_v2"

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "observation_record_sha256": self.observation_record_sha256,
            "public_authority_receipt_sha256": self.public_authority_receipt_sha256,
            "parser_input": self.parser_input.identity_payload(),
            "result_packet_sha256s": [item.packet_sha256 for item in self.result_packets],
            "route_landing_sha256s": [item.reconstruction_sha256 for item in self.route_landings],
            "live_plan_authority_sha256": self.live_plan_authority_sha256,
        }


_RECONSTRUCTION_DATACLASS_METADATA: dict[type[object], tuple[int, str]] = {
    RawRequestReconstructionV2: (
        RawRequestReconstructionV2.schema_version,
        RawRequestReconstructionV2.kind,
    ),
    ReconstructedParserInputV2: (
        ReconstructedParserInputV2.schema_version,
        ReconstructedParserInputV2.kind,
    ),
    ReconstructedProviderResultPacketV2: (
        ReconstructedProviderResultPacketV2.schema_version,
        ReconstructedProviderResultPacketV2.kind,
    ),
    ReconstructedRouteLandingV2: (
        ReconstructedRouteLandingV2.schema_version,
        ReconstructedRouteLandingV2.kind,
    ),
}


def _require_exact_reconstruction_match(
    supplied: object,
    replayed: object,
    *,
    label: str,
) -> None:
    """Compare every exact DTO field without caller equality or byte expansion."""

    supplied_type = type(supplied)
    if supplied_type is not type(replayed):
        _fail(f"{label} contains a non-exact reconstruction field value")
    if supplied is None:
        return
    if supplied_type in {str, int, bool, bytes}:
        if supplied != replayed:
            _fail(f"{label} differs from exact four-table replay")
        return
    if supplied_type is tuple:
        supplied_items = cast("tuple[object, ...]", supplied)
        replayed_items = cast("tuple[object, ...]", replayed)
        if len(supplied_items) != len(replayed_items):
            _fail(f"{label} differs from exact four-table replay")
        for index, (supplied_item, replayed_item) in enumerate(
            zip(supplied_items, replayed_items, strict=True)
        ):
            _require_exact_reconstruction_match(
                supplied_item,
                replayed_item,
                label=f"{label}[{index}]",
            )
        return
    if supplied_type in _RECONSTRUCTION_DATACLASS_METADATA:
        for item in fields(supplied_type):
            _require_exact_reconstruction_match(
                getattr(supplied, item.name),
                getattr(replayed, item.name),
                label=f"{label}.{item.name}",
            )
        return
    _fail(f"{label} contains a non-exact reconstruction field value")


def _parser_input_for_observation(
    body_object: ParserInputObjectV2 | None,
    observation: RequestObservationV2,
) -> ReconstructedParserInputV2:
    observation_sha256 = observation.attempt.observation_sha256
    expected_object_sha256 = observation.body_object_sha256
    if expected_object_sha256 is None:
        if body_object is not None:
            _fail("bodyless observation was supplied an extra parser-input object")
        if observation.bodyless_evidence_sha256 is None:
            _fail("bodyless observation lacks its exact evidence digest")
        return ReconstructedParserInputV2(
            observation_sha256=observation_sha256,
            body_disposition=observation.body_disposition,
            body_authority_receipt_sha256=observation.body_authority_receipt_sha256,
            body_object_sha256=None,
            bodyless_evidence_sha256=observation.bodyless_evidence_sha256,
            parser_input_bytes=None,
            parser_input_sha256=None,
            parser_input_length=None,
        )

    if body_object is None:
        _fail("body-bearing observation is missing its parser-input object")
    parsed_object = _safe_object(body_object)
    if parsed_object.object_sha256 != expected_object_sha256:
        _fail("parser-input object differs from the observation body authority")
    try:
        parser_input = decode_parser_input_object(parsed_object)
    except (TypeError, ValueError) as exc:
        raise RawRequestReconstructionError(
            "parser-input bytes cannot be reconstructed exactly"
        ) from exc
    if (
        len(parser_input) != parsed_object.uncompressed_bytes
        or _sha256(parser_input) != parsed_object.response_sha256
    ):
        _fail("reconstructed parser-input digest or length differs")
    return ReconstructedParserInputV2(
        observation_sha256=observation_sha256,
        body_disposition=observation.body_disposition,
        body_authority_receipt_sha256=observation.body_authority_receipt_sha256,
        body_object_sha256=parsed_object.object_sha256,
        bodyless_evidence_sha256=None,
        parser_input_bytes=parser_input,
        parser_input_sha256=parsed_object.response_sha256,
        parser_input_length=parsed_object.uncompressed_bytes,
    )


def reconstruct_parser_input_authority(
    body_object: ParserInputObjectV2 | None,
    observation: RequestObservationV2,
    occurrences: tuple[ResultOccurrenceV2, ...],
    landings: tuple[ObservationRouteLandingV2, ...],
    *,
    live_plan_authority: LiveSnapshotPlanAuthorityV2 | None = None,
    expected_live_plan_authority_sha256: str | None = None,
) -> ReconstructedParserInputV2:
    """Close all four tables, then return exact bytes or bodyless authority."""

    return reconstruct_raw_request_authority(
        body_object,
        observation,
        occurrences,
        landings,
        live_plan_authority=live_plan_authority,
        expected_live_plan_authority_sha256=expected_live_plan_authority_sha256,
    ).parser_input


@dataclass(frozen=True, slots=True)
class _OccurrenceParts:
    occurrence: ResultOccurrenceV2
    headers: tuple[str, ...]
    routes: tuple[str, ...]
    receipts: tuple[tuple[str, str], ...]


def _parse_occurrence_parts(item: ResultOccurrenceV2) -> _OccurrenceParts:
    raw_headers = _canonical_list(item.ordered_headers_json, label="ordered headers")
    if any(type(header) is not str for header in raw_headers):
        _fail("ordered headers contain a non-string value")
    headers = tuple(cast("str", header) for header in raw_headers)
    if len(headers) != item.header_count:
        _fail("ordered-header length differs from occurrence authority")

    raw_routes = _canonical_list(item.canonical_route_ids_json, label="canonical routes")
    if any(type(route_id) is not str for route_id in raw_routes):
        _fail("canonical routes contain a non-string value")
    routes = tuple(cast("str", route_id) for route_id in raw_routes)
    if len(routes) != len(set(routes)):
        _fail("canonical route inventory contains duplicates")

    raw_receipts = _canonical_list(
        item.committed_staging_receipts_json,
        label="committed staging receipts",
    )
    receipts: list[tuple[str, str]] = []
    for raw_receipt in raw_receipts:
        if type(raw_receipt) is not dict or set(raw_receipt) != {
            "receipt_sha256",
            "route_id",
        }:
            _fail("committed staging receipt has a foreign structure")
        receipt = cast("dict[str, object]", raw_receipt)
        route_id = receipt["route_id"]
        receipt_sha256 = receipt["receipt_sha256"]
        if type(route_id) is not str or type(receipt_sha256) is not str:
            _fail("committed staging receipt has a foreign value type")
        receipts.append((route_id, receipt_sha256))
    receipt_tuple = tuple(receipts)
    if tuple(route_id for route_id, _digest in receipt_tuple) != routes:
        _fail("committed staging receipt inventory is missing, extra, or reordered")
    if len({digest for _route_id, digest in receipt_tuple}) != len(receipt_tuple):
        _fail("one result packet repeats a committed staging receipt digest")
    return _OccurrenceParts(
        occurrence=item,
        headers=headers,
        routes=routes,
        receipts=receipt_tuple,
    )


def _ordered_occurrence_parts(
    observation: RequestObservationV2,
    occurrences: object,
) -> tuple[_OccurrenceParts, ...]:
    if type(occurrences) is not tuple:
        _fail("result occurrences must be supplied as an exact tuple")
    parsed = tuple(_safe_occurrence(item) for item in occurrences)
    if len(parsed) != observation.result_occurrence_count:
        _fail("result occurrence inventory is missing or extra")
    if [item.occurrence_ordinal for item in parsed] != list(range(len(parsed))):
        _fail("result occurrence ordinals are not exact and contiguous")
    occurrence_sha256s = [item.occurrence_sha256 for item in parsed]
    if len(occurrence_sha256s) != len(set(occurrence_sha256s)):
        _fail("result occurrence inventory contains duplicate identities")
    expected_digest = _canonical_sha256(occurrence_sha256s)
    if expected_digest != observation.result_occurrences_sha256:
        _fail("result occurrence inventory digest differs from the observation")
    observation_sha256 = observation.attempt.observation_sha256
    if any(item.observation_sha256 != observation_sha256 for item in parsed):
        _fail("result occurrence crosses request-observation authority")

    duplicate_names: Counter[str] = Counter()
    for item in parsed:
        expected_duplicate_ordinal = duplicate_names[item.result_name]
        if item.duplicate_name_ordinal != expected_duplicate_ordinal:
            _fail("duplicate result-name ordinals are not exact and ordered")
        duplicate_names[item.result_name] += 1
    return tuple(_parse_occurrence_parts(item) for item in parsed)


def _canonical_live_snapshot(value: datetime | None) -> str | None:
    if value is None:
        return None
    try:
        encoded = value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (AttributeError, TypeError, ValueError) as exc:
        raise RawRequestReconstructionError(
            "route landing live snapshot cannot be reconstructed"
        ) from exc
    if not encoded.endswith("Z"):
        _fail("route landing live snapshot is not aware UTC")
    return encoded


def _reconstructed_landing(
    landing: ObservationRouteLandingV2,
    *,
    source_occurrence_sha256s: tuple[str, ...],
) -> ReconstructedRouteLandingV2:
    snapshot = _canonical_live_snapshot(landing.live_snapshot_at)
    provisional = ReconstructedRouteLandingV2(
        reconstruction_sha256="",
        landing_sha256=landing.landing_sha256,
        route_ordinal=landing.route_ordinal,
        route_id=landing.route_id,
        staging_key=landing.staging_key,
        route_authority_kind=landing.route_authority_kind,
        route_authority_sha256=landing.route_authority_sha256,
        landing_semantic=landing.landing_semantic,
        conditional_lossless=landing.conditional_lossless,
        alias_target_route_id=landing.alias_target_route_id,
        live_snapshot_at=snapshot,
        source_occurrence_sha256s=source_occurrence_sha256s,
        chunk_id=landing.chunk_id,
        canonical_frame_format=landing.canonical_frame_format,
        frame_content_hash_contract=landing.frame_content_hash_contract,
        frame_schema_hash_contract=landing.frame_schema_hash_contract,
        content_hash=landing.content_hash,
        persisted_row_count=landing.persisted_row_count,
        persisted_content_sha256=landing.persisted_content_sha256,
        persisted_schema_sha256=landing.persisted_schema_sha256,
        logical_call_receipt_sha256=landing.logical_call_receipt_sha256,
        provider_authority_sha256=landing.provider_authority_sha256,
        logical_parameters_sha256=landing.logical_parameters_sha256,
        receipt_root_sha256=landing.receipt_root_sha256,
    )
    return replace(
        provisional,
        reconstruction_sha256=_canonical_sha256(provisional.identity_payload()),
    )


def _landings_for_observation(
    observation: RequestObservationV2,
    occurrences: object,
    landings: object,
) -> tuple[ReconstructedRouteLandingV2, ...]:
    """Rejoin the fourth public table to its exact observation and results."""

    if type(landings) is not tuple:
        _fail("route landings must be supplied as an exact tuple")
    parsed = tuple(_safe_landing(item) for item in landings)
    if len(parsed) != observation.route_landing_count:
        _fail("route landing inventory is missing or extra")
    if [item.route_ordinal for item in parsed] != list(range(len(parsed))):
        _fail("route landing ordinals are not exact and contiguous")
    landing_sha256s = [item.landing_sha256 for item in parsed]
    if len(landing_sha256s) != len(set(landing_sha256s)):
        _fail("route landing inventory contains duplicate identities")
    if _canonical_sha256(landing_sha256s) != observation.route_landings_sha256:
        _fail("route landing inventory digest differs from the observation")

    parts = _ordered_occurrence_parts(observation, occurrences)
    observation_sha256 = observation.attempt.observation_sha256
    logical_receipt = observation.logical_receipt_sha256
    if not parsed:
        if observation.lifecycle == "selected_terminal":
            _fail("selected terminal observation lacks response-level route landings")
        return ()
    if logical_receipt is None:
        _fail("route landing observation lacks its exact logical receipt")

    fixed_landings: list[ObservationRouteLandingV2] = []
    conditional_landings: list[ObservationRouteLandingV2] = []
    for landing in parsed:
        if (
            landing.observation_sha256 != observation_sha256
            or landing.logical_receipt_sha256 != logical_receipt
            or landing.logical_call_receipt_sha256 != logical_receipt
            or landing.provider_authority_sha256 != observation.attempt.provider_authority_sha256
        ):
            _fail("route landing crosses its request-observation authority")
        if observation.attempt.source_family == "live":
            if landing.live_snapshot_at is None:
                _fail("live route landing omitted its exact snapshot time")
        elif landing.live_snapshot_at is not None:
            _fail("non-live route landing fabricated a live snapshot time")
        if landing.route_authority_kind == "staging_route_contract_v1":
            fixed_landings.append(landing)
        else:
            conditional_landings.append(landing)
    if (
        observation.attempt.source_family == "live"
        and len({landing.live_snapshot_at for landing in parsed}) != 1
    ):
        _fail("live route landings lack one exact shared snapshot time")

    from nbadb.contracts.staging_route_contract import (
        admit_known_conditional_staging_route,
        staging_route_contract_bundle,
    )

    route_bundle = staging_route_contract_bundle()
    fixed_routes = []
    for landing in fixed_landings:
        route = route_bundle.by_route_id.get(landing.route_id)
        if route is None or (
            landing.route_authority_sha256 != route.contract_sha256
            or landing.staging_key != route.staging_key
            or route.source_family != observation.attempt.source_family
            or route.provider_endpoint_id != observation.attempt.endpoint_id
            or route.provider_authority_sha256 != observation.attempt.provider_authority_sha256
            or route.endpoint_contract_sha256 != observation.attempt.endpoint_contract_sha256
        ):
            _fail("fixed route landing differs from pinned route authority")
        fixed_routes.append(route)
    if not fixed_routes:
        _fail("terminal observation lacks a fixed route landing")
    if len({landing.route_id for landing in fixed_landings}) != len(fixed_landings):
        _fail("route landing inventory duplicates a fixed route")
    if len(conditional_landings) > 1:
        _fail("observation carries multiple conditional route landings")
    ordered_routes = tuple(sorted(fixed_routes, key=lambda item: item.ordinal))
    expected_fixed_ids = tuple(item.route_id for item in ordered_routes)
    if tuple(item.route_id for item in fixed_landings) != expected_fixed_ids:
        _fail("fixed route landings are not in canonical route order")
    endpoint_names = {item.endpoint_name for item in ordered_routes}
    if len(endpoint_names) != 1:
        _fail("route landings span endpoint wrappers")

    conditional = conditional_landings[0] if conditional_landings else None
    conditional_admission = None
    if conditional is not None:
        try:
            conditional_admission = admit_known_conditional_staging_route(
                endpoint_name=next(iter(endpoint_names)),
                static_route_ids=expected_fixed_ids,
                conditional_route_ids=(conditional.route_id,),
                provider_authority_sha256=observation.attempt.provider_authority_sha256,
            )
        except ValueError as exc:
            raise RawRequestReconstructionError(
                "conditional route landing lacks exact admission"
            ) from exc
        if (
            conditional.route_authority_sha256 != conditional_admission.contract_sha256
            or conditional.staging_key != conditional_admission.staging_key
            or conditional.route_id != conditional_admission.route_id
            or conditional_admission.endpoint_contract_sha256
            != observation.attempt.endpoint_contract_sha256
        ):
            _fail("conditional route landing differs from exact admission")
    expected_route_order = expected_fixed_ids + (
        () if conditional is None else (conditional.route_id,)
    )
    if tuple(item.route_id for item in parsed) != expected_route_order:
        _fail("route landings are not in canonical route order")
    try:
        validate_logical_provider_parameter_join(
            observation,
            logical_endpoint_name=next(iter(endpoint_names)),
            logical_parameters_sha256=parsed[0].logical_parameters_sha256,
            result_route_ids=tuple(sorted(expected_route_order)),
        )
    except RawRequestAuthorityError as exc:
        raise RawRequestReconstructionError(
            "route landing logical/provider parameter authority is invalid"
        ) from exc

    reconstructed: list[ReconstructedRouteLandingV2] = []
    occurrence_route_ids = {route_id for part in parts for route_id in part.routes}
    for landing in parsed:
        sources = tuple(part for part in parts if landing.route_id in part.routes)
        source_ids = tuple(part.occurrence.occurrence_sha256 for part in sources)
        if landing.source_occurrence_count != len(
            source_ids
        ) or landing.source_occurrences_sha256 != _canonical_sha256(list(source_ids)):
            _fail("route landing source occurrence denominator differs")
        for source in sources:
            receipt = dict(source.receipts).get(landing.route_id)
            if receipt != landing.receipt_root_sha256:
                _fail("route landing source occurrence receipt root differs")
        if landing.landing_semantic == "occurrence_bound":
            expected_rows = sum(
                source.occurrence.row_count
                for source in sources
                if source.occurrence.landing_disposition in {"wide_only", "wide_plus_lossless"}
            )
            if landing.persisted_row_count != expected_rows:
                _fail("occurrence-bound landing row count differs from sources")
        elif (
            landing.landing_semantic
            in {
                "response_fixed_zero",
                "response_canonical_alias",
            }
            and sources
        ):
            _fail("response-level route landing fabricated result sources")
        reconstructed.append(
            _reconstructed_landing(
                landing,
                source_occurrence_sha256s=source_ids,
            )
        )

    contract = pinned_runtime_contracts().get(observation.attempt.endpoint_id)
    unknown_dynamic = bool(
        observation.attempt.source_family == "stats"
        and contract is not None
        and contract.response_mode == "unknown_dynamic_response"
        and not contract.result_sets
    )
    if unknown_dynamic:
        if len(ordered_routes) != 1:
            _fail("unknown dynamic response has multiple fixed routes")
        fixed_landing = fixed_landings[0]
        if conditional is None:
            if (
                fixed_landing.landing_semantic != "response_fixed_zero"
                or fixed_landing.alias_target_route_id is not None
            ):
                _fail("unknown dynamic fixed-route landing policy differs")
        else:
            if conditional_admission is None:
                _fail("unknown dynamic conditional admission is unavailable")
            alias_policy = (
                ordered_routes[0].storage_columns == conditional_admission.storage_columns
            )
            if alias_policy:
                if (
                    fixed_landing.landing_semantic != "response_canonical_alias"
                    or fixed_landing.alias_target_route_id != conditional.route_id
                    or (
                        fixed_landing.persisted_row_count,
                        fixed_landing.content_hash,
                        fixed_landing.persisted_content_sha256,
                        fixed_landing.persisted_schema_sha256,
                    )
                    != (
                        conditional.persisted_row_count,
                        conditional.content_hash,
                        conditional.persisted_content_sha256,
                        conditional.persisted_schema_sha256,
                    )
                ):
                    _fail("unknown dynamic canonical-alias landing differs")
            elif (
                fixed_landing.landing_semantic != "response_fixed_zero"
                or fixed_landing.alias_target_route_id is not None
            ):
                _fail("unknown dynamic fixed-zero landing policy differs")
    else:
        if occurrence_route_ids != set(expected_route_order):
            _fail("ordinary route landing inventory differs from result occurrences")
        if any(
            item.landing_semantic not in {"occurrence_bound", "conditional_lossless"}
            for item in parsed
        ):
            _fail("ordinary observation carries a response-only route semantic")
    return tuple(reconstructed)


def reconstruct_route_landings(
    body_object: ParserInputObjectV2 | None,
    observation: RequestObservationV2,
    occurrences: tuple[ResultOccurrenceV2, ...],
    landings: tuple[ObservationRouteLandingV2, ...],
    *,
    live_plan_authority: LiveSnapshotPlanAuthorityV2 | None = None,
    expected_live_plan_authority_sha256: str | None = None,
) -> tuple[ReconstructedRouteLandingV2, ...]:
    """Close all four tables, then return the ordered response-route inventory."""

    return reconstruct_raw_request_authority(
        body_object,
        observation,
        occurrences,
        landings,
        live_plan_authority=live_plan_authority,
        expected_live_plan_authority_sha256=expected_live_plan_authority_sha256,
    ).route_landings


_HEADERLESS_PRESENCES = frozenset(
    {"missing", "null", "mixed_absent", "empty_object", "empty_array"}
)
_EMPTY_PARENT_STATES_SHA256 = _canonical_sha256([])
_PRESENT_PARENT_STATE_SHA256 = _canonical_sha256(["present"])
_MISSING_PARENT_STATE_SHA256 = _canonical_sha256(["missing"])


def _validate_parent_state_authority(
    item: ResultOccurrenceV2,
    *,
    expected_parent_observation_count: int,
) -> None:
    if item.parent_state_sha256 is None:
        _fail("result packet lacks its parent-state authority")
    present_count = item.container_count - item.null_count
    if present_count < 0:
        _fail("result packet parent-state counts cannot be reconstructed")
    state_counts = {
        "present": present_count,
        "missing": item.missing_count,
        "null": item.null_count,
    }
    if sum(state_counts.values()) != expected_parent_observation_count:
        _fail("result packet parent-state count differs from its exact parent")
    populated = [(state, count) for state, count in state_counts.items() if count]
    if not populated:
        expected_digest = _EMPTY_PARENT_STATES_SHA256
    elif len(populated) == 1:
        state, count = populated[0]
        expected_digest = _canonical_sha256([state] * count)
    else:
        return
    if item.parent_state_sha256 != expected_digest:
        _fail("result packet parent-state digest differs from reconstructable authority")


def _live_parent_links(
    observation: RequestObservationV2,
    parts: Sequence[_OccurrenceParts],
) -> tuple[tuple[int | None, int | None], ...]:
    contract = pinned_live_contracts().get(observation.attempt.endpoint_id)
    if contract is None:
        _fail("live reconstruction has no exact pinned endpoint contract")
    if len(parts) != len(contract.result_sets):
        _fail("live result inventory is missing or extra against its pinned contract")
    result_ordinal_by_name = {item.name: item.ordinal for item in contract.result_sets}
    links: list[tuple[int | None, int | None]] = []
    for expected, part in zip(contract.result_sets, parts, strict=True):
        item = part.occurrence
        expected_headers = (
            ()
            if item.presence in _HEADERLESS_PRESENCES
            else tuple(field.name for field in expected.fields)
        )
        if (
            item.occurrence_ordinal != expected.ordinal
            or item.result_name != expected.name
            or item.duplicate_name_ordinal != 0
            or item.provider_result_ordinal is not None
            or item.canonical_result_ordinal != expected.ordinal
            or item.json_path != expected.json_path
            or item.container_kind != expected.container_kind
            or part.headers != expected_headers
        ):
            _fail("live result packet differs from its exact pinned result identity")

        if expected.parent_result_set_name is None:
            _validate_parent_state_authority(
                item,
                expected_parent_observation_count=1,
            )
            if (
                item.presence == "not_observed_parent_empty"
                or item.parent_state_sha256 != _PRESENT_PARENT_STATE_SHA256
            ):
                _fail("live root lacks its exact observed-root state")
            links.append((None, None))
            continue
        parent_ordinal = result_ordinal_by_name.get(expected.parent_result_set_name)
        if parent_ordinal is None or parent_ordinal >= item.occurrence_ordinal:
            _fail("live result packet has no prior exact pinned parent")
        parent = parts[parent_ordinal].occurrence
        if parent.row_count == 0:
            if (
                item.presence != "not_observed_parent_empty"
                or item.parent_state_sha256 != _EMPTY_PARENT_STATES_SHA256
            ):
                _fail("live child invents an observation under an empty parent")
            links.append((parent_ordinal, None))
        else:
            if item.presence == "not_observed_parent_empty":
                _fail("live child suppresses an observed parent packet")
            links.append((parent_ordinal, parent_ordinal))
        _validate_parent_state_authority(
            item,
            expected_parent_observation_count=parent.row_count,
        )
    return tuple(links)


def _stats_parent_links(
    observation: RequestObservationV2,
    parts: Sequence[_OccurrenceParts],
) -> tuple[tuple[int | None, int | None], ...]:
    items = tuple(part.occurrence for part in parts)
    if any(
        item.container_kind != "nba_api_result_set" or item.json_path is not None for item in items
    ):
        _fail("stats reconstruction contains a non-stats result packet")
    for item in items:
        _validate_parent_state_authority(
            item,
            expected_parent_observation_count=1,
        )
    fallback = any(item.canonical_result_ordinal is None for item in items)
    if fallback:
        if any(item.canonical_result_ordinal is not None for item in items):
            _fail("stats reconstruction mixes pinned and fallback packet identities")
        for item in items:
            if item.provider_result_ordinal is None:
                if (
                    item.presence != "missing"
                    or item.parent_state_sha256 != _MISSING_PARENT_STATE_SHA256
                ):
                    _fail("missing stats fallback packet has a foreign presence state")
            elif (
                item.presence not in {"present", "present_empty"}
                or item.parent_state_sha256 != _PRESENT_PARENT_STATE_SHA256
            ):
                _fail("present stats fallback packet has a foreign presence state")
        provider_ordinals = [
            item.provider_result_ordinal
            for item in items
            if item.provider_result_ordinal is not None
        ]
        if provider_ordinals != list(range(len(provider_ordinals))):
            _fail("stats fallback provider packet order is not exact")
    else:
        contract = pinned_runtime_contracts().get(observation.attempt.endpoint_id)
        if contract is None or len(items) != len(contract.result_sets):
            _fail("stats canonical packet inventory differs from its pinned endpoint")
        if [item.canonical_result_ordinal for item in items] != list(range(len(items))):
            _fail("stats canonical packet order is not exact")
        for expected, part in zip(contract.result_sets, parts, strict=True):
            if (
                expected.result_set_name is None
                or part.occurrence.result_name != expected.result_set_name
                or part.headers != expected.expected_columns
            ):
                _fail("stats canonical packet differs from its pinned result identity")
        if any(
            item.presence not in {"present", "present_empty"}
            or item.parent_state_sha256 != _PRESENT_PARENT_STATE_SHA256
            for item in items
        ):
            _fail("stats canonical packet has a foreign presence state")
        if any(item.provider_result_ordinal is None for item in items):
            _fail("stats canonical provider packet inventory is incomplete")
        provider_ordinals = [cast("int", item.provider_result_ordinal) for item in items]
        if sorted(provider_ordinals) != list(range(len(items))):
            _fail("stats provider packet inventory is missing or duplicate")
    return tuple((None, None) for _item in items)


def _static_parent_links(
    observation: RequestObservationV2,
    parts: Sequence[_OccurrenceParts],
) -> tuple[tuple[int | None, int | None], ...]:
    if len(parts) != 1:
        _fail("static reconstruction requires exactly one provider packet")
    try:
        contract = pinned_static_dataset_contract(observation.attempt.endpoint_id)
    except ValueError as exc:
        raise RawRequestReconstructionError(
            "static reconstruction has no exact pinned dataset contract"
        ) from exc
    part = parts[0]
    item = part.occurrence
    _validate_parent_state_authority(
        item,
        expected_parent_observation_count=1,
    )
    expected_name = f"{contract.source_symbol}_shape_1"
    expected_headers = (
        () if item.presence == "empty_array" else tuple(field.name for field in contract.raw_fields)
    )
    if (
        item.occurrence_ordinal != 0
        or item.result_name != expected_name
        or item.duplicate_name_ordinal != 0
        or item.provider_result_ordinal != 0
        or item.canonical_result_ordinal != 0
        or item.json_path != "$"
        or item.container_kind != "nba_api_static_records"
        or item.presence not in {"present", "empty_array"}
        or item.parent_state_sha256 != _PRESENT_PARENT_STATE_SHA256
        or part.headers != expected_headers
    ):
        _fail("static result packet differs from its exact pinned dataset identity")
    return ((None, None),)


def _packet_payload(
    *,
    part: _OccurrenceParts,
    declared_parent: int | None,
    observed_parent: int | None,
) -> dict[str, object]:
    item = part.occurrence
    return {
        "occurrence_sha256": item.occurrence_sha256,
        "occurrence_ordinal": item.occurrence_ordinal,
        "result_name": item.result_name,
        "duplicate_name_ordinal": item.duplicate_name_ordinal,
        "provider_result_ordinal": item.provider_result_ordinal,
        "canonical_result_ordinal": item.canonical_result_ordinal,
        "json_path": item.json_path,
        "container_kind": item.container_kind,
        "presence": item.presence,
        "ordered_headers": list(part.headers),
        "row_count": item.row_count,
        "cell_count": item.cell_count,
        "node_count": item.node_count,
        "container_count": item.container_count,
        "missing_count": item.missing_count,
        "null_count": item.null_count,
        "parent_state_sha256": item.parent_state_sha256,
        "output_sha256": item.output_sha256,
        "declared_parent_result_ordinal": declared_parent,
        "observed_parent_result_ordinal": observed_parent,
        "canonical_route_ids": list(part.routes),
        "committed_staging_receipts": [
            {"route_id": route_id, "receipt_sha256": receipt_sha256}
            for route_id, receipt_sha256 in part.receipts
        ],
        "landing_disposition": item.landing_disposition,
    }


def _packets_for_observation(
    observation: RequestObservationV2,
    occurrences: object,
) -> tuple[ReconstructedProviderResultPacketV2, ...]:
    parts = _ordered_occurrence_parts(observation, occurrences)
    if not parts:
        return ()
    if observation.attempt.source_family == "live":
        parent_links = _live_parent_links(observation, parts)
    elif observation.attempt.source_family == "stats":
        parent_links = _stats_parent_links(observation, parts)
    else:
        parent_links = _static_parent_links(observation, parts)

    packets: list[ReconstructedProviderResultPacketV2] = []
    for part, (declared_parent, observed_parent) in zip(parts, parent_links, strict=True):
        item = part.occurrence
        payload = _packet_payload(
            part=part,
            declared_parent=declared_parent,
            observed_parent=observed_parent,
        )
        packets.append(
            ReconstructedProviderResultPacketV2(
                packet_sha256=_canonical_sha256(payload),
                occurrence_sha256=item.occurrence_sha256,
                occurrence_ordinal=item.occurrence_ordinal,
                result_name=item.result_name,
                duplicate_name_ordinal=item.duplicate_name_ordinal,
                provider_result_ordinal=item.provider_result_ordinal,
                canonical_result_ordinal=item.canonical_result_ordinal,
                json_path=item.json_path,
                container_kind=item.container_kind,
                presence=item.presence,
                ordered_headers=part.headers,
                row_count=item.row_count,
                cell_count=item.cell_count,
                node_count=item.node_count,
                container_count=item.container_count,
                missing_count=item.missing_count,
                null_count=item.null_count,
                parent_state_sha256=item.parent_state_sha256,
                output_sha256=item.output_sha256,
                declared_parent_result_ordinal=declared_parent,
                observed_parent_result_ordinal=observed_parent,
                canonical_route_ids=part.routes,
                committed_staging_receipts=part.receipts,
                landing_disposition=item.landing_disposition,
            )
        )
    return tuple(packets)


def reconstruct_provider_result_packets(
    body_object: ParserInputObjectV2 | None,
    observation: RequestObservationV2,
    occurrences: tuple[ResultOccurrenceV2, ...],
    landings: tuple[ObservationRouteLandingV2, ...],
    *,
    live_plan_authority: LiveSnapshotPlanAuthorityV2 | None = None,
    expected_live_plan_authority_sha256: str | None = None,
) -> tuple[ReconstructedProviderResultPacketV2, ...]:
    """Close all four tables, then return the ordered provider packet structure."""

    return reconstruct_raw_request_authority(
        body_object,
        observation,
        occurrences,
        landings,
        live_plan_authority=live_plan_authority,
        expected_live_plan_authority_sha256=expected_live_plan_authority_sha256,
    ).result_packets


def reconstruct_raw_request_authority(
    body_object: ParserInputObjectV2 | None,
    observation: RequestObservationV2,
    occurrences: tuple[ResultOccurrenceV2, ...],
    landings: tuple[ObservationRouteLandingV2, ...],
    *,
    live_plan_authority: LiveSnapshotPlanAuthorityV2 | None = None,
    expected_live_plan_authority_sha256: str | None = None,
) -> RawRequestReconstructionV2:
    """Return a closed independent reconstruction for one observation."""

    bundle = _validated_single_observation_bundle(
        body_object,
        observation,
        occurrences,
        landings,
    )
    parsed_observation = bundle.observations[0]
    validated_plan_sha256 = _validated_live_plan_authority_sha256(
        bundle,
        live_plan_authority=live_plan_authority,
        expected_live_plan_authority_sha256=expected_live_plan_authority_sha256,
    )
    parsed_body = bundle.objects[0] if bundle.objects else None
    parser_input = _parser_input_for_observation(parsed_body, parsed_observation)
    packets = _packets_for_observation(parsed_observation, bundle.occurrences)
    reconstructed_landings = _landings_for_observation(
        parsed_observation,
        bundle.occurrences,
        bundle.landings,
    )
    payload = {
        "schema_version": RawRequestReconstructionV2.schema_version,
        "kind": RawRequestReconstructionV2.kind,
        "observation_record_sha256": parsed_observation.observation_record_sha256,
        "public_authority_receipt_sha256": (parsed_observation.public_authority_receipt_sha256),
        "parser_input": parser_input.identity_payload(),
        "result_packet_sha256s": [item.packet_sha256 for item in packets],
        "route_landing_sha256s": [item.reconstruction_sha256 for item in reconstructed_landings],
        "live_plan_authority_sha256": validated_plan_sha256,
    }
    return RawRequestReconstructionV2(
        reconstruction_sha256=_canonical_sha256(payload),
        observation_record_sha256=parsed_observation.observation_record_sha256,
        public_authority_receipt_sha256=(parsed_observation.public_authority_receipt_sha256),
        parser_input=parser_input,
        result_packets=packets,
        route_landings=reconstructed_landings,
        live_plan_authority_sha256=validated_plan_sha256,
    )


def validate_raw_request_reconstruction(
    value: RawRequestReconstructionV2,
    body_object: ParserInputObjectV2 | None,
    observation: RequestObservationV2,
    occurrences: tuple[ResultOccurrenceV2, ...],
    landings: tuple[ObservationRouteLandingV2, ...],
    *,
    live_plan_authority: LiveSnapshotPlanAuthorityV2 | None = None,
    expected_live_plan_authority_sha256: str | None = None,
) -> RawRequestReconstructionV2:
    """Replay all source authority and reject any forged reconstruction DTO.

    The reconstruction record is intentionally not self-authorizing: its
    digest proves deterministic identity, while these four public source
    tables and the independent live-plan receipt prove provenance.  Validation
    therefore re-runs the complete reconstruction and requires byte-for-byte
    dataclass equality, covering every nested identity payload and the top
    reconstruction digest.
    """

    if type(value) is not RawRequestReconstructionV2:
        _fail("raw reconstruction does not have its exact contract type")
    rebuilt = reconstruct_raw_request_authority(
        body_object,
        observation,
        occurrences,
        landings,
        live_plan_authority=live_plan_authority,
        expected_live_plan_authority_sha256=expected_live_plan_authority_sha256,
    )
    _require_exact_reconstruction_match(
        value,
        rebuilt,
        label="raw reconstruction",
    )
    return rebuilt
