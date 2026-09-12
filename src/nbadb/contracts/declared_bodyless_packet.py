"""Provider admission for declared-bodyless static packet authority.

The dependency-pure DTOs, canonical decoder, projection derivation, byte
validation, and readback receipt live in ``declared_bodyless_packet_types``.
This module is intentionally limited to admitting one current provider
observation, freezing its pinned static schema, and joining those provider
facts to the pure packet authority.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from nbadb.contracts.declared_bodyless_packet_types import (
    MAX_DECLARED_BODYLESS_SCHEMA_BYTES as _MAX_DECLARED_BODYLESS_SCHEMA_BYTES,
)
from nbadb.contracts.declared_bodyless_packet_types import (
    DeclaredBodylessPacketError as _DeclaredBodylessPacketError,
)
from nbadb.contracts.declared_bodyless_packet_types import (
    DeclaredBodylessPacketV1 as _DeclaredBodylessPacketV1,
)
from nbadb.contracts.declared_bodyless_packet_types import (
    decode_public_canonical_packet as _decode_public_canonical_packet,
)
from nbadb.contracts.declared_bodyless_packet_types import (
    rederive_declared_bodyless_packet_projection as _rederive_packet_projection,
)
from nbadb.contracts.declared_bodyless_packet_types import (
    validate_declared_bodyless_packet_identity as _validate_packet_identity,
)
from nbadb.contracts.independent_static_value_decoder import decode_static_value_response
from nbadb.contracts.raw_request_authority import (
    RequestAttemptIdentityV2,
    RequestObservationV2,
    validate_request_observation,
)
from nbadb.contracts.raw_transport_contract import StaticSnapshotTransportV1
from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
from nbadb.core.nba_api_request_surface import pinned_request_surface_authority
from nbadb.core.nba_api_runtime_contract import pinned_static_dataset_contract

if TYPE_CHECKING:
    from collections.abc import Sequence

    from nbadb.core.nba_api_runtime_contract import StaticDatasetContract

__all__ = [
    "build_declared_bodyless_packet",
    "validate_declared_bodyless_packet",
]


_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def _fail(message: str) -> _DeclaredBodylessPacketError:
    return _DeclaredBodylessPacketError(message)


def _exact_sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise _fail(f"{label} must be one exact SHA-256")
    return value


def _preflight_static_observation(observation: RequestObservationV2) -> None:
    """Reject model-copy bypasses before invoking any nested model method."""

    if type(observation) is not RequestObservationV2:
        raise _fail("declared bodyless observation has a foreign type")
    try:
        attempt = observation.attempt
        transport = observation.transport
    except AttributeError:
        raise _fail("declared bodyless observation fields are invalid") from None
    if type(attempt) is not RequestAttemptIdentityV2:
        raise _fail("declared bodyless observation has a foreign attempt type")
    if type(transport) is not StaticSnapshotTransportV1:
        raise _fail("declared bodyless observation has a foreign transport type")

    try:
        attempt_strings = (
            attempt.observation_sha256,
            attempt.semantic_request_sha256,
            attempt.logical_invocation_sha256,
            attempt.provider_call_sha256,
            attempt.attempt_sha256,
            attempt.provider_call_role,
            attempt.source_family,
            attempt.endpoint_id,
            attempt.provider_request_sha256,
            attempt.request_surface_sha256,
            attempt.runtime_contract_sha256,
            attempt.provider_authority_sha256,
            attempt.endpoint_contract_sha256,
            attempt.safe_parameters_json,
            attempt.safe_parameters_sha256,
            attempt.scope_sha256,
            attempt.source_sha,
            attempt.chain_id,
            attempt.lane_id,
        )
        if type(attempt.schema_version) is not int or any(
            type(value) is not str for value in attempt_strings
        ):
            raise _fail("declared bodyless observation attempt fields are invalid")
        for value in (
            attempt.competition_id,
            attempt.competition_identity_sha256,
            attempt.pagination_sha256,
        ):
            if value is not None and type(value) is not str:
                raise _fail("declared bodyless observation attempt fields are invalid")
        for value in (
            attempt.provider_call_ordinal,
            attempt.retry_ordinal,
            attempt.request_ordinal,
            attempt.run_id,
            attempt.run_attempt,
        ):
            if type(value) is not int:
                raise _fail("declared bodyless observation attempt fields are invalid")
        if attempt.page_ordinal is not None and type(attempt.page_ordinal) is not int:
            raise _fail("declared bodyless observation attempt fields are invalid")

        observation_strings = (
            observation.observation_record_sha256,
            observation.lifecycle,
            observation.outcome,
            observation.body_disposition,
            observation.body_authority_receipt_sha256,
            observation.result_occurrences_sha256,
            observation.route_landings_sha256,
            observation.public_authority_receipt_sha256,
        )
        if type(observation.schema_version) is not int or any(
            type(value) is not str for value in observation_strings
        ):
            raise _fail("declared bodyless observation fields are invalid")
        for value in (
            observation.failure_class,
            observation.root_exception_class,
            observation.body_object_sha256,
            observation.bodyless_evidence_sha256,
            observation.capture_response_receipt_sha256,
            observation.logical_receipt_sha256,
        ):
            if value is not None and type(value) is not str:
                raise _fail("declared bodyless observation fields are invalid")
        if (
            type(transport.transport_kind) is not str
            or type(observation.started_at) is not datetime
            or observation.started_at.tzinfo is not UTC
        ):
            raise _fail("declared bodyless observation timestamps or transport are invalid")
        if observation.finished_at is not None and (
            type(observation.finished_at) is not datetime
            or observation.finished_at.tzinfo is not UTC
        ):
            raise _fail("declared bodyless observation timestamps are invalid")
        for value in (observation.result_occurrence_count, observation.route_landing_count):
            if type(value) is not int:
                raise _fail("declared bodyless observation fields are invalid")
        if observation.elapsed_ns is not None and type(observation.elapsed_ns) is not int:
            raise _fail("declared bodyless observation fields are invalid")
    except AttributeError:
        raise _fail("declared bodyless observation fields are invalid") from None


def _validated_static_observation(
    observation: RequestObservationV2,
    *,
    expected_observation_sha256: str,
    expected_observation_record_sha256: str,
) -> RequestObservationV2:
    expected_observation = _exact_sha256(
        expected_observation_sha256,
        label="expected observation identity",
    )
    expected_observation_record = _exact_sha256(
        expected_observation_record_sha256,
        label="expected observation record",
    )
    _preflight_static_observation(observation)
    try:
        rebuilt = RequestObservationV2.from_canonical_bytes(observation.to_canonical_bytes())
        validated = validate_request_observation(rebuilt)
    except Exception:
        raise _fail("declared bodyless observation is invalid") from None
    attempt = validated.attempt
    if (
        attempt.observation_sha256 != expected_observation
        or validated.observation_record_sha256 != expected_observation_record
        or attempt.source_family != "static"
        or validated.lifecycle != "selected_terminal"
        or validated.outcome != "static_snapshot_success"
        or validated.body_disposition != "declared_bodyless"
        or validated.body_object_sha256 is not None
        or validated.bodyless_evidence_sha256 is None
        or validated.capture_response_receipt_sha256 is None
        or validated.logical_receipt_sha256 is None
    ):
        raise _fail("declared bodyless observation differs from its external authority")
    try:
        contract = pinned_static_dataset_contract(attempt.endpoint_id)
        request_authority = pinned_request_surface_authority()
        route_authority = staging_route_contract_bundle()
        datasets = {item.dataset_id: item for item in request_authority.static_datasets}
        surface = datasets.get(attempt.endpoint_id)
    except Exception:
        raise _fail("declared bodyless static authority is unavailable") from None
    if (
        surface is None
        or attempt.endpoint_contract_sha256 != contract.contract_sha256
        or attempt.provider_authority_sha256 != route_authority.provider_authority_sha256
        or attempt.request_surface_sha256 != request_authority.surface_sha256
        or attempt.runtime_contract_sha256 != request_authority.runtime_contract_payload_sha256
        or surface.embedded_body_sha256 != contract.source_rows_sha256
    ):
        raise _fail("declared bodyless observation references foreign static authority")
    return validated


def _frozen_static_schema_json(contract: StaticDatasetContract) -> str:
    try:
        raw_fields = contract.raw_fields
        projected_fields = contract.projected_fields
    except AttributeError:
        raise _fail("declared bodyless frozen static schema is invalid") from None
    if type(raw_fields) is not tuple or type(projected_fields) is not tuple:
        raise _fail("declared bodyless frozen static schema is invalid")
    if any(type(value) is not str for value in projected_fields):
        raise _fail("declared bodyless frozen static schema is invalid")
    projected = set(projected_fields)
    rows: list[dict[str, object]] = []
    for ordinal, field in enumerate(raw_fields):
        try:
            name = field.name
            field_ordinal = field.ordinal
            sample_type = field.sample_type
        except AttributeError:
            raise _fail("declared bodyless frozen static field is invalid") from None
        if (
            type(name) is not str
            or type(field_ordinal) is not int
            or type(sample_type) is not str
            or field_ordinal != ordinal
        ):
            raise _fail("declared bodyless frozen static field is invalid")
        rows.append(
            {
                "name": name,
                "ordinal": field_ordinal,
                "projected": name in projected,
                "sample_type": sample_type,
            }
        )
    try:
        encoded = json.dumps(
            rows,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8", errors="strict")
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError):
        raise _fail("declared bodyless frozen static schema is invalid") from None
    if not encoded or len(encoded) > _MAX_DECLARED_BODYLESS_SCHEMA_BYTES:
        raise _fail("declared bodyless frozen static schema exceeds its byte bound")
    return encoded.decode("utf-8", errors="strict")


def build_declared_bodyless_packet(
    *,
    observation: RequestObservationV2,
    expected_observation_sha256: str,
    expected_observation_record_sha256: str,
    packet_bytes: bytes,
    known_secrets: Sequence[str | bytes] = (),
) -> _DeclaredBodylessPacketV1:
    """Build one leaf packet after exact provider and observation admission."""

    validated = _validated_static_observation(
        observation,
        expected_observation_sha256=expected_observation_sha256,
        expected_observation_record_sha256=expected_observation_record_sha256,
    )
    _decode_public_canonical_packet(packet_bytes, known_secrets=known_secrets)
    try:
        contract = pinned_static_dataset_contract(validated.attempt.endpoint_id)
        decoded = decode_static_value_response(
            packet_bytes,
            dataset_id=validated.attempt.endpoint_id,
            endpoint_contract_sha256=validated.attempt.endpoint_contract_sha256,
        )
        frozen_static_schema_json = _frozen_static_schema_json(contract)
        projection = _rederive_packet_projection(
            packet_bytes=packet_bytes,
            frozen_static_schema_json=frozen_static_schema_json,
            known_secrets=known_secrets,
        )
    except Exception:
        raise _fail("declared bodyless packet differs from pinned static authority") from None
    if (
        projection.field_count != decoded.field_count
        or projection.row_count != decoded.record_count
        or projection.cell_count != decoded.cell_count
        or projection.schema_root_sha256 != decoded.fields_sha256
        or projection.content_root_sha256 != decoded.normalized_output_sha256
        or projection.row_root_sha256 != decoded.records_sha256
        or projection.cell_root_sha256 != decoded.cells_sha256
    ):
        raise _fail("declared bodyless frozen projection differs from pinned decoding")
    return _DeclaredBodylessPacketV1.build(
        observation_sha256=validated.attempt.observation_sha256,
        observation_record_sha256=validated.observation_record_sha256,
        attempt_sha256=validated.attempt.attempt_sha256,
        logical_receipt_sha256=cast("str", validated.logical_receipt_sha256),
        endpoint_id=validated.attempt.endpoint_id,
        endpoint_contract_sha256=validated.attempt.endpoint_contract_sha256,
        provider_authority_sha256=validated.attempt.provider_authority_sha256,
        frozen_static_schema_json=frozen_static_schema_json,
        source_sha=validated.attempt.source_sha,
        run_id=validated.attempt.run_id,
        run_attempt=validated.attempt.run_attempt,
        chain_id=validated.attempt.chain_id,
        lane_id=validated.attempt.lane_id,
        packet_bytes=packet_bytes,
        expected_observation_sha256=expected_observation_sha256,
        expected_observation_record_sha256=expected_observation_record_sha256,
        known_secrets=known_secrets,
    )


def validate_declared_bodyless_packet(
    value: object,
    *,
    observation: RequestObservationV2,
    packet_bytes: bytes,
    expected_observation_sha256: str,
    expected_observation_record_sha256: str,
    expected_packet_authority_sha256: str,
    known_secrets: Sequence[str | bytes] = (),
) -> _DeclaredBodylessPacketV1:
    """Rebuild one packet from exact provider, observation, and byte authorities."""

    candidate = _validate_packet_identity(
        value,
        expected_packet_authority_sha256=expected_packet_authority_sha256,
    )
    rebuilt = build_declared_bodyless_packet(
        observation=observation,
        expected_observation_sha256=expected_observation_sha256,
        expected_observation_record_sha256=expected_observation_record_sha256,
        packet_bytes=packet_bytes,
        known_secrets=known_secrets,
    )
    try:
        candidate_bytes = candidate.to_canonical_bytes()
        rebuilt_bytes = rebuilt.to_canonical_bytes()
    except Exception:
        raise _fail("declared bodyless packet differs from exact byte reconstruction") from None
    if candidate_bytes != rebuilt_bytes:
        raise _fail("declared bodyless packet differs from exact byte reconstruction")
    return rebuilt
