"""Strict V2 public authority contracts for raw ``nba_api`` request evidence.

The four relations in this module are the control-plane counterparts of the
fixed public raw tables.  They intentionally do not reuse the private Bronze
representation identifiers or its path-based receipt layout: public parser
input bytes live directly in a representation-aware, content-addressed row.

Only successfully parser-consumed UTF-8 JSON objects may become public body
objects.  Calls that fail before successful parsing retain typed, bodyless
observations.  A later staging or schema failure keeps the successfully parsed
body but marks its observation incomplete.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import re
import zlib
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Annotated, Any, Literal, Self, cast

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    model_validator,
)

from nbadb.contracts.raw_transport_contract import (
    RawTransportV1,
    canonical_transport_payload,
    source_family_for_transport,
    validate_raw_transport,
)
from nbadb.core.extraction_failures import SAFE_ROOT_ERROR_NAMES
from nbadb.core.nba_api_request_surface import (
    NbaApiRequestSurfaceError,
    materialize_provider_request,
    pinned_request_surface_authority,
)

__all__ = [
    "BODYLESS_RESULT_OCCURRENCES_SHA256",
    "BODYLESS_ROUTE_LANDINGS_SHA256",
    "DETERMINISTIC_GZIP_CODEC",
    "DETERMINISTIC_GZIP_CONTRACT_SHA256",
    "MAX_PARSER_INPUT_BYTES",
    "MAX_PARSER_INPUT_STORED_BYTES",
    "PARSER_INPUT_OBJECT_ADAPTER",
    "PUBLIC_PARSER_INPUT_REPRESENTATION",
    "RAW_REQUEST_AUTHORITY_BUNDLE_ADAPTER",
    "RAW_REQUEST_AUTHORITY_SCHEMA_VERSION",
    "REQUEST_ATTEMPT_IDENTITY_ADAPTER",
    "REQUEST_OBSERVATION_ADAPTER",
    "RESULT_OCCURRENCE_ADAPTER",
    "OBSERVATION_ROUTE_LANDING_ADAPTER",
    "FailureClass",
    "LandingDisposition",
    "RouteAuthorityKind",
    "RouteLandingSemantic",
    "ObservationBodyDisposition",
    "ObservationLifecycle",
    "ObservationOutcome",
    "ObservationRouteLandingV2",
    "ParserInputObjectV2",
    "RawRequestAuthorityBundleV2",
    "RawRequestAuthorityError",
    "RequestAttemptIdentityV2",
    "RequestObservationV2",
    "ResultContainerKind",
    "ResultOccurrenceV2",
    "ResultPresence",
    "canonical_json_bytes",
    "canonical_semantic_parameters",
    "decode_parser_input_object",
    "validate_parser_input_object",
    "validate_raw_request_authority_bundle",
    "validate_request_attempt_identity",
    "validate_logical_provider_parameter_join",
    "validate_request_observation",
    "validate_result_occurrence",
    "validate_observation_route_landing",
]

RAW_REQUEST_AUTHORITY_SCHEMA_VERSION = 2
PUBLIC_PARSER_INPUT_REPRESENTATION = "nbadb_public_exact_decoded_response_text_utf8_v1"
DETERMINISTIC_GZIP_CODEC = "gzip-6-public-v1"
MAX_PARSER_INPUT_BYTES = 64 * 1024 * 1024
MAX_PARSER_INPUT_STORED_BYTES = MAX_PARSER_INPUT_BYTES + 64 * 1024
MAX_CANONICAL_JSON_BYTES = 16 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 2_000_000
MAX_PARAMETER_JSON_BYTES = 256 * 1024
MAX_RESULT_JSON_BYTES = 4 * 1024 * 1024
MAX_AUTHORITY_ROWS = 1_000_000

_DETERMINISTIC_GZIP_CONTRACT = {
    "schema_version": 1,
    "codec": DETERMINISTIC_GZIP_CODEC,
    "format": "gzip",
    "compresslevel": 6,
    "mtime": 0,
    "os_header_byte": 255,
    "multi_member_allowed": False,
    "trailing_data_allowed": False,
    "identity_basis": "public_representation_and_uncompressed_bytes",
}

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_GIT_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,199}\Z")
_SAFE_RESULT_NAME_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,255}\Z")
_FORBIDDEN_PARAMETER_KEY_RE = re.compile(
    r"(?:authorization|cookie|credential|header|password|proxy|secret|timeout|token|vpn)",
    re.IGNORECASE,
)
_FORBIDDEN_IDENTITY_RE = re.compile(
    r"(?:authorization|cookie|credential|header|password|proxy|secret|token|vpn|"
    r"(?:^|[._:-])(?:path|host|ip)(?:$|[._:-]))",
    re.IGNORECASE,
)
_FORBIDDEN_BODY_KEY_RE = re.compile(
    r"(?:authorization|cookie|set_cookie|proxy_url|proxy_host|vpn_server|vpn_ip|"
    r"client_secret|access_token|refresh_token|api_key|password|request_headers|"
    r"response_headers|runner_path|workspace_path|local_path|file_path)\Z",
    re.IGNORECASE,
)
_CAMEL_ACRONYM_BOUNDARY_RE = re.compile(r"([A-Z]+)([A-Z][a-z])", flags=re.ASCII)
_CAMEL_WORD_BOUNDARY_RE = re.compile(r"([a-z0-9])([A-Z])", flags=re.ASCII)
_KEY_SEPARATOR_RE = re.compile(r"[^A-Za-z0-9]+", flags=re.ASCII)
_AUTH_HEADER_RE = re.compile(
    rb"(?i)(?:authorization\s*:\s*(?:bearer|basic)\s+|(?:set-)?cookie\s*:)",
)
_LOCAL_PATH_RE = re.compile(
    rb"(?:/Users/[^/\x00\s]+/|/home/[^/\x00\s]+/|/private/var/|[A-Za-z]:\\Users\\)",
)
_VPN_SENTINEL_RE = re.compile(
    rb"(?i)(?:[A-Za-z0-9-]+\.nordvpn\.com\b|\b(?:vpn_server|vpn_ip)\b)",
)
_URL_USERINFO_RE = re.compile(rb"(?i)https?://[^/\s:@]+:[^/\s@]+@")

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
GitSha = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]
SafeId = Annotated[
    str,
    StringConstraints(
        pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,199}$",
        min_length=1,
        max_length=200,
    ),
]
ResultName = Annotated[
    str,
    StringConstraints(
        pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.:-]{0,255}$",
        min_length=1,
        max_length=256,
    ),
]
NonNegativeInt = Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)]
PositiveInt = Annotated[int, Field(strict=True, ge=1, le=2**63 - 1)]


def _strict_schema_version(value: object) -> int:
    if type(value) is not int or value != RAW_REQUEST_AUTHORITY_SCHEMA_VERSION:
        raise ValueError("schema_version must be the exact integer 2")
    return value


SchemaVersion = Annotated[int, BeforeValidator(_strict_schema_version)]

ObservationLifecycle = Literal["allocated", "incomplete", "selected_terminal"]
ObservationOutcome = Literal[
    "allocated",
    "success_nonempty",
    "success_empty",
    "downstream_incomplete",
    "static_snapshot_success",
    "http_transient_error",
    "http_application_error",
    "malformed_json",
    "application_error_envelope",
    "contract_mismatch",
    "parser_failure",
    "transport_failure_no_response",
    "cancelled_before_response",
]
ObservationBodyDisposition = Literal[
    "public_parser_input",
    "declared_bodyless",
    "no_response",
    "excluded_failure_body",
]
FailureClass = Literal[
    "transport_transient",
    "response_contract",
    "application",
    "vpn_egress",
    "runner_infrastructure",
    "timeout_progress",
    "timeout_stalled",
    "contract_blocked",
]
ResultPresence = Literal[
    "present",
    "missing",
    "null",
    "mixed_absent",
    "present_empty",
    "empty_object",
    "empty_array",
    "not_observed_parent_empty",
]
ResultContainerKind = Literal[
    "nba_api_result_set",
    "nba_api_static_records",
    "nba_api_live_json_array",
    "nba_api_live_json_object",
]
LandingDisposition = Literal[
    "wide_only",
    "lossless_only",
    "wide_plus_lossless",
    "presence_only",
]
RouteAuthorityKind = Literal[
    "staging_route_contract_v1",
    "conditional_staging_route_admission_v1",
]
RouteLandingSemantic = Literal[
    "occurrence_bound",
    "conditional_lossless",
    "response_fixed_zero",
    "response_canonical_alias",
]


class RawRequestAuthorityError(ValueError):
    """Raised when public raw request authority is unsafe or inconsistent."""


class _StrictFrozenModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        validate_default=True,
        revalidate_instances="always",
    )


def canonical_json_bytes(value: object, *, maximum_bytes: int = MAX_CANONICAL_JSON_BYTES) -> bytes:
    """Encode one bounded JSON value with the repository canonical rules."""

    if type(maximum_bytes) is not int or maximum_bytes < 1:
        raise RawRequestAuthorityError("maximum_bytes must be a positive integer")
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise RawRequestAuthorityError(
            f"authority value is not canonical JSON: {type(exc).__name__}"
        ) from exc
    if len(encoded) > maximum_bytes:
        raise RawRequestAuthorityError("canonical JSON exceeds its bounded contract")
    return encoded


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: object, *, maximum_bytes: int = MAX_CANONICAL_JSON_BYTES) -> str:
    return _sha256_bytes(canonical_json_bytes(value, maximum_bytes=maximum_bytes))


DETERMINISTIC_GZIP_CONTRACT_SHA256 = _sha256_json(_DETERMINISTIC_GZIP_CONTRACT)
BODYLESS_RESULT_OCCURRENCES_SHA256 = _sha256_json([])
BODYLESS_ROUTE_LANDINGS_SHA256 = _sha256_json([])


def _reject_duplicate_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RawRequestAuthorityError("authority JSON contains a duplicate object key")
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> object:
    raise RawRequestAuthorityError("authority JSON contains a non-finite number")


def _bounded_json_value(encoded: bytes, *, maximum_bytes: int) -> object:
    if not encoded or len(encoded) > maximum_bytes:
        raise RawRequestAuthorityError("authority JSON bytes violate the bounded contract")
    try:
        value = json.loads(
            encoded.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_object,
            parse_constant=_reject_nonfinite_constant,
        )
    except RawRequestAuthorityError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RawRequestAuthorityError("authority JSON cannot be decoded") from exc

    nodes = 0
    stack: list[tuple[object, int]] = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            raise RawRequestAuthorityError("authority JSON exceeds its depth or node bound")
        if isinstance(item, dict):
            stack.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item)
    return value


def _decode_canonical_json_object(encoded: bytes, *, maximum_bytes: int) -> dict[str, object]:
    value = _bounded_json_value(encoded, maximum_bytes=maximum_bytes)
    if not isinstance(value, dict):
        raise RawRequestAuthorityError("authority JSON root must be an object")
    if encoded != canonical_json_bytes(value, maximum_bytes=maximum_bytes):
        raise RawRequestAuthorityError("authority JSON bytes are not canonical")
    return cast("dict[str, object]", value)


def _canonical_timestamp(value: datetime, *, field_name: str) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise RawRequestAuthorityError(f"{field_name} must be an aware UTC datetime")
    if value.utcoffset() != UTC.utcoffset(value):
        raise RawRequestAuthorityError(f"{field_name} must be an aware UTC datetime")
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _deterministic_gzip(raw: bytes) -> bytes:
    if len(raw) > MAX_PARSER_INPUT_BYTES:
        raise RawRequestAuthorityError("parser input exceeds the public body bound")
    stored = bytearray(gzip.compress(raw, compresslevel=6, mtime=0))
    if len(stored) < 18 or stored[:4] != b"\x1f\x8b\x08\x00":
        raise RawRequestAuthorityError("deterministic gzip encoder returned an invalid member")
    stored[9] = 255
    encoded = bytes(stored)
    if len(encoded) > MAX_PARSER_INPUT_STORED_BYTES:
        raise RawRequestAuthorityError("compressed parser input exceeds the public body bound")
    return encoded


def _bounded_gzip_decompress(stored: bytes) -> bytes:
    if not stored or len(stored) > MAX_PARSER_INPUT_STORED_BYTES:
        raise RawRequestAuthorityError("stored parser input violates the public body bound")
    decompressor = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
    try:
        raw = decompressor.decompress(stored, MAX_PARSER_INPUT_BYTES + 1)
    except zlib.error as exc:
        raise RawRequestAuthorityError("stored parser input is not valid gzip") from exc
    if (
        len(raw) > MAX_PARSER_INPUT_BYTES
        or not decompressor.eof
        or decompressor.unused_data
        or decompressor.unconsumed_tail
    ):
        raise RawRequestAuthorityError(
            "stored parser input is truncated, concatenated, trailing, or over limit"
        )
    return raw


def _normalized_public_key(value: str) -> str:
    """Normalize ASCII camel/Pascal/separator spellings for policy matching."""

    separated = _CAMEL_ACRONYM_BOUNDARY_RE.sub(r"\1_\2", value)
    separated = _CAMEL_WORD_BOUNDARY_RE.sub(r"\1_\2", separated)
    return _KEY_SEPARATOR_RE.sub("_", separated).strip("_").lower()


def _scan_json_keys(value: object) -> None:
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise RawRequestAuthorityError("parser input contains a non-text key")
                normalized = _normalized_public_key(key)
                if _FORBIDDEN_BODY_KEY_RE.fullmatch(normalized):
                    raise RawRequestAuthorityError(
                        "parser input contains prohibited transport or secret material"
                    )
                stack.append(child)
        elif isinstance(item, list):
            stack.extend(item)


def _reject_sensitive_bytes(
    raw: bytes,
    *,
    known_secrets: Sequence[str | bytes] = (),
) -> None:
    if (
        _AUTH_HEADER_RE.search(raw)
        or _LOCAL_PATH_RE.search(raw)
        or _VPN_SENTINEL_RE.search(raw)
        or _URL_USERINFO_RE.search(raw)
    ):
        raise RawRequestAuthorityError(
            "public authority contains prohibited transport or secret material"
        )
    if len(known_secrets) > 128:
        raise RawRequestAuthorityError("known secret inventory exceeds its bound")
    for secret in known_secrets:
        if isinstance(secret, str):
            try:
                candidate = secret.encode("utf-8", errors="strict")
            except UnicodeEncodeError as exc:
                raise RawRequestAuthorityError("known secret inventory is invalid") from exc
        elif isinstance(secret, bytes):
            candidate = secret
        else:
            raise RawRequestAuthorityError("known secret inventory is invalid")
        if candidate and candidate in raw:
            raise RawRequestAuthorityError("public authority contains a known secret value")


def _validate_public_parser_input(
    raw: bytes,
    *,
    known_secrets: Sequence[str | bytes] = (),
) -> None:
    if not raw or len(raw) > MAX_PARSER_INPUT_BYTES:
        raise RawRequestAuthorityError("parser input must be nonempty and bounded")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RawRequestAuthorityError("parser input must be exact UTF-8 text") from exc
    if text.encode("utf-8", errors="strict") != raw:
        raise RawRequestAuthorityError("parser input UTF-8 round trip is not exact")
    value = _bounded_json_value(raw, maximum_bytes=MAX_PARSER_INPUT_BYTES)
    if not isinstance(value, dict):
        raise RawRequestAuthorityError("public parser input must be a JSON object")
    _scan_json_keys(value)
    _reject_sensitive_bytes(raw, known_secrets=known_secrets)


def _parser_object_identity_payload(
    *,
    response_sha256: str,
    uncompressed_bytes: int,
) -> dict[str, object]:
    return {
        "schema_version": RAW_REQUEST_AUTHORITY_SCHEMA_VERSION,
        "representation": PUBLIC_PARSER_INPUT_REPRESENTATION,
        "media_type": "application/json",
        "text_encoding": "utf-8",
        "response_sha256": response_sha256,
        "uncompressed_bytes": uncompressed_bytes,
    }


class ParserInputObjectV2(_StrictFrozenModel):
    """One exact, public, representation-aware parser-input body object."""

    schema_version: SchemaVersion
    object_sha256: Sha256
    representation: Literal["nbadb_public_exact_decoded_response_text_utf8_v1"]
    media_type: Literal["application/json"]
    text_encoding: Literal["utf-8"]
    codec: Literal["gzip-6-public-v1"]
    codec_contract_sha256: Sha256
    response_sha256: Sha256
    uncompressed_bytes: PositiveInt
    stored_sha256: Sha256
    stored_bytes: PositiveInt
    stored_payload: Annotated[
        bytes,
        Field(strict=True, min_length=1, max_length=MAX_PARSER_INPUT_STORED_BYTES),
    ]

    @model_validator(mode="after")
    def _validate_complete_object(self) -> Self:
        if self.codec_contract_sha256 != DETERMINISTIC_GZIP_CONTRACT_SHA256:
            raise ValueError("parser-input codec contract digest is invalid")
        if self.stored_bytes != len(self.stored_payload):
            raise ValueError("stored parser-input length is invalid")
        if self.stored_sha256 != _sha256_bytes(self.stored_payload):
            raise ValueError("stored parser-input digest is invalid")
        raw = _bounded_gzip_decompress(self.stored_payload)
        _validate_public_parser_input(raw)
        if self.uncompressed_bytes != len(raw):
            raise ValueError("uncompressed parser-input length is invalid")
        if self.response_sha256 != _sha256_bytes(raw):
            raise ValueError("uncompressed parser-input digest is invalid")
        expected_object = _sha256_json(
            _parser_object_identity_payload(
                response_sha256=self.response_sha256,
                uncompressed_bytes=self.uncompressed_bytes,
            )
        )
        if self.object_sha256 != expected_object:
            raise ValueError("representation-aware parser-input object digest is invalid")
        if self.stored_payload != _deterministic_gzip(raw):
            raise ValueError("stored parser input is not the deterministic gzip representation")
        return self

    @classmethod
    def from_parser_input(
        cls,
        parser_input: str,
        *,
        known_secrets: Sequence[str | bytes] = (),
    ) -> Self:
        if not isinstance(parser_input, str):
            raise RawRequestAuthorityError("parser input must be the decoded provider string")
        try:
            raw = parser_input.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise RawRequestAuthorityError("parser input must be exact UTF-8 text") from exc
        _validate_public_parser_input(raw, known_secrets=known_secrets)
        response_sha256 = _sha256_bytes(raw)
        stored_payload = _deterministic_gzip(raw)
        return cls(
            schema_version=RAW_REQUEST_AUTHORITY_SCHEMA_VERSION,
            object_sha256=_sha256_json(
                _parser_object_identity_payload(
                    response_sha256=response_sha256,
                    uncompressed_bytes=len(raw),
                )
            ),
            representation=PUBLIC_PARSER_INPUT_REPRESENTATION,
            media_type="application/json",
            text_encoding="utf-8",
            codec=DETERMINISTIC_GZIP_CODEC,
            codec_contract_sha256=DETERMINISTIC_GZIP_CONTRACT_SHA256,
            response_sha256=response_sha256,
            uncompressed_bytes=len(raw),
            stored_sha256=_sha256_bytes(stored_payload),
            stored_bytes=len(stored_payload),
            stored_payload=stored_payload,
        )

    def to_row(self) -> dict[str, object]:
        return dict(self.model_dump(mode="python", round_trip=True))

    def to_canonical_bytes(self) -> bytes:
        payload = self.to_row()
        stored = cast("bytes", payload.pop("stored_payload"))
        payload["stored_payload_base64"] = base64.b64encode(stored).decode("ascii")
        return canonical_json_bytes(payload, maximum_bytes=MAX_PARSER_INPUT_STORED_BYTES * 2)

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> Self:
        payload = _decode_canonical_json_object(
            encoded,
            maximum_bytes=MAX_PARSER_INPUT_STORED_BYTES * 2,
        )
        expected = set(cls.model_fields) - {"stored_payload"}
        if set(payload) != expected | {"stored_payload_base64"}:
            raise RawRequestAuthorityError("parser-input object fields are invalid")
        raw_base64 = payload.pop("stored_payload_base64")
        if not isinstance(raw_base64, str):
            raise RawRequestAuthorityError("parser-input object base64 is invalid")
        try:
            stored_payload = base64.b64decode(raw_base64, validate=True)
        except (ValueError, TypeError) as exc:
            raise RawRequestAuthorityError("parser-input object base64 is invalid") from exc
        if base64.b64encode(stored_payload).decode("ascii") != raw_base64:
            raise RawRequestAuthorityError("parser-input object base64 is not canonical")
        payload["stored_payload"] = stored_payload
        return cast("Self", validate_parser_input_object(payload))


def decode_parser_input_object(value: object) -> bytes:
    """Return the exact verified parser bytes from one strict public object."""

    parsed = validate_parser_input_object(value)
    return _bounded_gzip_decompress(parsed.stored_payload)


def canonical_semantic_parameters(
    source_family: Literal["stats", "live", "static"],
    endpoint_id: str,
    parameters: Mapping[str, object],
    *,
    known_secrets: Sequence[str | bytes] = (),
) -> tuple[str, str, str]:
    """Return allowlisted canonical parameters, digest, and provider request key.

    The pinned request surface is the allowlist.  URL, query-string, headers,
    timeout, proxy, and other transport details are never returned.
    """

    if source_family not in {"stats", "live", "static"}:
        raise RawRequestAuthorityError("semantic parameter source family is invalid")
    if not isinstance(endpoint_id, str) or _SAFE_ID_RE.fullmatch(endpoint_id) is None:
        raise RawRequestAuthorityError("semantic parameter endpoint is invalid")
    if not isinstance(parameters, Mapping) or any(not isinstance(key, str) for key in parameters):
        raise RawRequestAuthorityError("semantic parameters must be a string-keyed object")
    if any(_FORBIDDEN_PARAMETER_KEY_RE.search(key) for key in parameters):
        raise RawRequestAuthorityError("semantic parameters contain a transport-only key")

    authority = pinned_request_surface_authority()
    if source_family == "static":
        static_ids = {item.dataset_id for item in authority.static_datasets}
        if endpoint_id not in static_ids or parameters:
            raise RawRequestAuthorityError(
                "static authority accepts only a known bodyless dataset with no parameters"
            )
        safe_json = "{}"
        request_sha256 = _sha256_json(
            {
                "request_surface_sha256": authority.surface_sha256,
                "runtime_contract_payload_sha256": authority.runtime_contract_payload_sha256,
                "source_family": source_family,
                "endpoint_id": endpoint_id,
                "materialized_parameters": {},
            }
        )
        return safe_json, _sha256_bytes(safe_json.encode("utf-8")), request_sha256

    try:
        endpoint = authority.endpoint(source_family, endpoint_id)
        request = materialize_provider_request(
            endpoint,
            parameters,
            request_surface_sha256=authority.surface_sha256,
            runtime_contract_payload_sha256=authority.runtime_contract_payload_sha256,
        )
    except NbaApiRequestSurfaceError as exc:
        raise RawRequestAuthorityError(
            "semantic parameters differ from the pinned allowlist"
        ) from exc
    materialized = dict(request.materialized_parameters)
    safe_bytes = canonical_json_bytes(
        materialized,
        maximum_bytes=MAX_PARAMETER_JSON_BYTES,
    )
    _reject_sensitive_bytes(safe_bytes, known_secrets=known_secrets)
    safe_json = safe_bytes.decode("utf-8")
    return safe_json, _sha256_bytes(safe_bytes), request.provider_request_sha256


class RequestAttemptIdentityV2(_StrictFrozenModel):
    """Immutable identity for one allocated provider retry attempt."""

    schema_version: SchemaVersion
    observation_sha256: Sha256
    semantic_request_sha256: Sha256
    logical_invocation_sha256: Sha256
    provider_call_sha256: Sha256
    attempt_sha256: Sha256
    provider_call_role: SafeId
    provider_call_ordinal: NonNegativeInt
    retry_ordinal: NonNegativeInt
    request_ordinal: NonNegativeInt
    source_family: Literal["stats", "live", "static"]
    endpoint_id: SafeId
    provider_request_sha256: Sha256
    request_surface_sha256: Sha256
    runtime_contract_sha256: Sha256
    provider_authority_sha256: Sha256
    endpoint_contract_sha256: Sha256
    safe_parameters_json: Annotated[str, StringConstraints(min_length=2, max_length=262_144)]
    safe_parameters_sha256: Sha256
    competition_id: SafeId | None
    competition_identity_sha256: Sha256 | None
    scope_sha256: Sha256
    pagination_sha256: Sha256 | None
    page_ordinal: NonNegativeInt | None
    source_sha: GitSha
    run_id: PositiveInt
    run_attempt: PositiveInt
    chain_id: SafeId
    lane_id: SafeId

    @model_validator(mode="after")
    def _validate_identity(self) -> Self:
        public_ids = (
            self.provider_call_role,
            self.endpoint_id,
            self.competition_id,
            self.chain_id,
            self.lane_id,
        )
        if any(value is not None and _FORBIDDEN_IDENTITY_RE.search(value) for value in public_ids):
            raise ValueError("request attempt contains a prohibited public identifier")
        if (self.competition_id is None) != (self.competition_identity_sha256 is None):
            raise ValueError("competition identity fields must be both present or both absent")
        if (self.pagination_sha256 is None) != (self.page_ordinal is None):
            raise ValueError("pagination identity fields must be both present or both absent")
        parameters = _decode_canonical_json_object(
            self.safe_parameters_json.encode("utf-8"),
            maximum_bytes=MAX_PARAMETER_JSON_BYTES,
        )
        safe_json, parameters_sha256, provider_request_sha256 = canonical_semantic_parameters(
            self.source_family,
            self.endpoint_id,
            parameters,
        )
        if (
            self.safe_parameters_json != safe_json
            or self.safe_parameters_sha256 != parameters_sha256
            or self.provider_request_sha256 != provider_request_sha256
        ):
            raise ValueError("safe semantic parameter authority is invalid")
        authority = pinned_request_surface_authority()
        if (
            self.request_surface_sha256 != authority.surface_sha256
            or self.runtime_contract_sha256 != authority.runtime_contract_payload_sha256
        ):
            raise ValueError("attempt identity references a foreign request surface")
        call_payload = {
            "semantic_request_sha256": self.semantic_request_sha256,
            "logical_invocation_sha256": self.logical_invocation_sha256,
            "provider_call_role": self.provider_call_role,
            "provider_call_ordinal": self.provider_call_ordinal,
            "source_family": self.source_family,
            "endpoint_id": self.endpoint_id,
            "provider_request_sha256": self.provider_request_sha256,
            "competition_identity_sha256": self.competition_identity_sha256,
            "scope_sha256": self.scope_sha256,
            "pagination_sha256": self.pagination_sha256,
            "page_ordinal": self.page_ordinal,
        }
        if self.provider_call_sha256 != _sha256_json(call_payload):
            raise ValueError("provider-call identity digest is invalid")
        attempt_payload = {
            "provider_call_sha256": self.provider_call_sha256,
            "retry_ordinal": self.retry_ordinal,
            "request_ordinal": self.request_ordinal,
            "source_sha": self.source_sha,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "chain_id": self.chain_id,
            "lane_id": self.lane_id,
        }
        expected_attempt = _sha256_json(attempt_payload)
        if self.attempt_sha256 != expected_attempt or self.observation_sha256 != expected_attempt:
            raise ValueError("provider attempt or observation identity digest is invalid")
        return self

    @classmethod
    def build(
        cls,
        *,
        semantic_request_sha256: str,
        logical_invocation_sha256: str,
        provider_call_role: str,
        provider_call_ordinal: int,
        retry_ordinal: int,
        request_ordinal: int,
        source_family: Literal["stats", "live", "static"],
        endpoint_id: str,
        parameters: Mapping[str, object],
        provider_authority_sha256: str,
        endpoint_contract_sha256: str,
        competition_id: str | None,
        competition_identity_sha256: str | None,
        scope_sha256: str,
        pagination_sha256: str | None,
        page_ordinal: int | None,
        source_sha: str,
        run_id: int,
        run_attempt: int,
        chain_id: str,
        lane_id: str,
        known_secrets: Sequence[str | bytes] = (),
    ) -> Self:
        authority = pinned_request_surface_authority()
        safe_json, safe_sha256, provider_request_sha256 = canonical_semantic_parameters(
            source_family,
            endpoint_id,
            parameters,
            known_secrets=known_secrets,
        )
        call_payload = {
            "semantic_request_sha256": semantic_request_sha256,
            "logical_invocation_sha256": logical_invocation_sha256,
            "provider_call_role": provider_call_role,
            "provider_call_ordinal": provider_call_ordinal,
            "source_family": source_family,
            "endpoint_id": endpoint_id,
            "provider_request_sha256": provider_request_sha256,
            "competition_identity_sha256": competition_identity_sha256,
            "scope_sha256": scope_sha256,
            "pagination_sha256": pagination_sha256,
            "page_ordinal": page_ordinal,
        }
        provider_call_sha256 = _sha256_json(call_payload)
        attempt_sha256 = _sha256_json(
            {
                "provider_call_sha256": provider_call_sha256,
                "retry_ordinal": retry_ordinal,
                "request_ordinal": request_ordinal,
                "source_sha": source_sha,
                "run_id": run_id,
                "run_attempt": run_attempt,
                "chain_id": chain_id,
                "lane_id": lane_id,
            }
        )
        return cls(
            schema_version=RAW_REQUEST_AUTHORITY_SCHEMA_VERSION,
            observation_sha256=attempt_sha256,
            semantic_request_sha256=semantic_request_sha256,
            logical_invocation_sha256=logical_invocation_sha256,
            provider_call_sha256=provider_call_sha256,
            attempt_sha256=attempt_sha256,
            provider_call_role=provider_call_role,
            provider_call_ordinal=provider_call_ordinal,
            retry_ordinal=retry_ordinal,
            request_ordinal=request_ordinal,
            source_family=source_family,
            endpoint_id=endpoint_id,
            provider_request_sha256=provider_request_sha256,
            request_surface_sha256=authority.surface_sha256,
            runtime_contract_sha256=authority.runtime_contract_payload_sha256,
            provider_authority_sha256=provider_authority_sha256,
            endpoint_contract_sha256=endpoint_contract_sha256,
            safe_parameters_json=safe_json,
            safe_parameters_sha256=safe_sha256,
            competition_id=competition_id,
            competition_identity_sha256=competition_identity_sha256,
            scope_sha256=scope_sha256,
            pagination_sha256=pagination_sha256,
            page_ordinal=page_ordinal,
            source_sha=source_sha,
            run_id=run_id,
            run_attempt=run_attempt,
            chain_id=chain_id,
            lane_id=lane_id,
        )

    def to_dict(self) -> dict[str, object]:
        return dict(self.model_dump(mode="python", round_trip=True))

    def to_canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> Self:
        return cast(
            "Self",
            validate_request_attempt_identity(
                _decode_canonical_json_object(
                    encoded,
                    maximum_bytes=MAX_CANONICAL_JSON_BYTES,
                )
            ),
        )


def _transport_statuses(transport: RawTransportV1) -> tuple[int | None, int | None]:
    if transport.transport_kind == "static_snapshot":
        return None, None
    return transport.status_code, transport.effective_status_code


def _is_exact_unknown_dynamic_video_attempt(attempt: RequestAttemptIdentityV2) -> bool:
    """Return whether one attempt is bound to an exact pinned zero-result Video route."""

    if attempt.source_family != "stats":
        return False
    try:
        from nbadb.contracts.staging_route_contract import staging_route_contract_bundle
        from nbadb.core.nba_api_runtime_contract import pinned_runtime_contracts

        contract = pinned_runtime_contracts().get(attempt.endpoint_id)
        routes = tuple(
            route
            for route in staging_route_contract_bundle().routes
            if route.source_family == "stats"
            and route.provider_endpoint_id == attempt.endpoint_id
            and route.endpoint_contract_sha256 == attempt.endpoint_contract_sha256
            and route.provider_authority_sha256 == attempt.provider_authority_sha256
        )
    except (ImportError, RuntimeError, TypeError, ValueError):
        return False
    response_contract = None if contract is None else contract.response_contract
    return bool(
        contract is not None
        and response_contract is not None
        and response_contract.response_mode == "unknown_dynamic_response"
        and response_contract.endpoint_contract_sha256 == attempt.endpoint_contract_sha256
        and not contract.result_sets
        and len(routes) == 1
        and routes[0].provider_result_set_name is None
        and routes[0].provider_result_set_ordinal is None
    )


def _body_authority_receipt_payload(
    *,
    observation_sha256: str,
    body_disposition: ObservationBodyDisposition,
    body_object_sha256: str | None,
    bodyless_evidence_sha256: str | None,
) -> dict[str, object]:
    return {
        "schema_version": RAW_REQUEST_AUTHORITY_SCHEMA_VERSION,
        "observation_sha256": observation_sha256,
        "body_disposition": body_disposition,
        "body_object_sha256": body_object_sha256,
        "bodyless_evidence_sha256": bodyless_evidence_sha256,
    }


def _observation_record_payload(
    *,
    attempt: RequestAttemptIdentityV2,
    transport: RawTransportV1,
    started_at: datetime,
    finished_at: datetime | None,
    elapsed_ns: int | None,
    lifecycle: ObservationLifecycle,
    outcome: ObservationOutcome,
    failure_class: FailureClass | None,
    root_exception_class: str | None,
    body_disposition: ObservationBodyDisposition,
    body_object_sha256: str | None,
    bodyless_evidence_sha256: str | None,
    body_authority_receipt_sha256: str,
    result_occurrence_count: int,
    result_occurrences_sha256: str,
    route_landing_count: int,
    route_landings_sha256: str,
    capture_response_receipt_sha256: str | None,
    logical_receipt_sha256: str | None,
    logical_provider_parameter_binding_sha256: str | None,
    logical_provider_parameter_binding_json: str | None,
    public_authority_receipt_sha256: str,
) -> dict[str, object]:
    return {
        "schema_version": RAW_REQUEST_AUTHORITY_SCHEMA_VERSION,
        "attempt": attempt.to_dict(),
        "transport": canonical_transport_payload(transport),
        "started_at": _canonical_timestamp(started_at, field_name="started_at"),
        "finished_at": (
            None
            if finished_at is None
            else _canonical_timestamp(finished_at, field_name="finished_at")
        ),
        "elapsed_ns": elapsed_ns,
        "lifecycle": lifecycle,
        "outcome": outcome,
        "failure_class": failure_class,
        "root_exception_class": root_exception_class,
        "body_disposition": body_disposition,
        "body_object_sha256": body_object_sha256,
        "bodyless_evidence_sha256": bodyless_evidence_sha256,
        "body_authority_receipt_sha256": body_authority_receipt_sha256,
        "result_occurrence_count": result_occurrence_count,
        "result_occurrences_sha256": result_occurrences_sha256,
        "route_landing_count": route_landing_count,
        "route_landings_sha256": route_landings_sha256,
        "capture_response_receipt_sha256": capture_response_receipt_sha256,
        "logical_receipt_sha256": logical_receipt_sha256,
        "logical_provider_parameter_binding_sha256": (logical_provider_parameter_binding_sha256),
        "logical_provider_parameter_binding_json": logical_provider_parameter_binding_json,
        "public_authority_receipt_sha256": public_authority_receipt_sha256,
    }


class RequestObservationV2(_StrictFrozenModel):
    """One public-safe observation for exactly one allocated provider attempt."""

    schema_version: SchemaVersion
    observation_record_sha256: Sha256
    attempt: RequestAttemptIdentityV2
    transport: RawTransportV1
    started_at: datetime
    finished_at: datetime | None
    elapsed_ns: NonNegativeInt | None
    lifecycle: ObservationLifecycle
    outcome: ObservationOutcome
    failure_class: FailureClass | None
    root_exception_class: SafeId | None
    body_disposition: ObservationBodyDisposition
    body_object_sha256: Sha256 | None
    bodyless_evidence_sha256: Sha256 | None
    body_authority_receipt_sha256: Sha256
    result_occurrence_count: NonNegativeInt
    result_occurrences_sha256: Sha256
    route_landing_count: NonNegativeInt
    route_landings_sha256: Sha256
    capture_response_receipt_sha256: Sha256 | None
    logical_receipt_sha256: Sha256 | None
    logical_provider_parameter_binding_sha256: Sha256 | None
    logical_provider_parameter_binding_json: (
        Annotated[
            str,
            StringConstraints(min_length=2, max_length=2 * 1024 * 1024),
        ]
        | None
    )
    public_authority_receipt_sha256: Sha256

    @model_validator(mode="after")
    def _validate_observation(self) -> Self:
        if self.started_at.tzinfo is None or self.started_at.utcoffset() != UTC.utcoffset(
            self.started_at
        ):
            raise ValueError("started_at must be an aware UTC datetime")
        if (self.finished_at is None) != (self.elapsed_ns is None):
            raise ValueError("finished_at and elapsed_ns must be both present or both absent")
        if self.finished_at is not None:
            if self.finished_at.tzinfo is None or self.finished_at.utcoffset() != UTC.utcoffset(
                self.finished_at
            ):
                raise ValueError("finished_at must be an aware UTC datetime")
            if self.finished_at < self.started_at:
                raise ValueError("finished_at precedes started_at")

        transport = validate_raw_transport(self.transport)
        if source_family_for_transport(transport) != self.attempt.source_family:
            raise ValueError("transport discriminator disagrees with the request source")
        status_code, effective_status_code = _transport_statuses(transport)

        has_parameter_binding = self.logical_provider_parameter_binding_sha256 is not None
        if has_parameter_binding != (self.logical_provider_parameter_binding_json is not None):
            raise ValueError(
                "logical/provider parameter binding digest and canonical bytes must agree"
            )
        if has_parameter_binding:
            if self.lifecycle != "selected_terminal" or self.outcome not in {
                "success_nonempty",
                "success_empty",
                "static_snapshot_success",
            }:
                raise ValueError(
                    "logical/provider parameter binding is limited to terminal success"
                )
            try:
                from nbadb.contracts.logical_provider_parameter_binding import (
                    LogicalProviderParameterBindingV1,
                )

                encoded_binding = cast(
                    "str",
                    self.logical_provider_parameter_binding_json,
                ).encode("utf-8", errors="strict")
                parameter_binding = LogicalProviderParameterBindingV1.from_canonical_bytes(
                    encoded_binding
                )
            except (AttributeError, TypeError, UnicodeEncodeError, ValueError) as exc:
                raise ValueError(
                    "logical/provider parameter binding cannot be replayed exactly"
                ) from exc
            if (
                parameter_binding.binding_sha256 != self.logical_provider_parameter_binding_sha256
                or parameter_binding.canonical_bytes() != encoded_binding
            ):
                raise ValueError(
                    "logical/provider parameter binding digest differs from canonical bytes"
                )

        if self.lifecycle == "allocated":
            if (
                self.outcome != "allocated"
                or self.finished_at is not None
                or self.failure_class is not None
                or self.root_exception_class is not None
                or self.body_disposition != "no_response"
                or self.body_object_sha256 is not None
                or self.bodyless_evidence_sha256 is None
                or status_code is not None
                or effective_status_code is not None
                or self.result_occurrence_count != 0
                or self.result_occurrences_sha256 != BODYLESS_RESULT_OCCURRENCES_SHA256
                or self.route_landing_count != 0
                or self.route_landings_sha256 != BODYLESS_ROUTE_LANDINGS_SHA256
                or self.capture_response_receipt_sha256 is not None
                or self.logical_receipt_sha256 is not None
            ):
                raise ValueError("allocated observation has completed-attempt evidence")
        else:
            if self.outcome == "allocated" or self.finished_at is None:
                raise ValueError("finished observation lacks a completed outcome or timing")

        if (self.failure_class is None) != (self.root_exception_class is None):
            raise ValueError("failure class and root exception class must agree")
        if (
            self.root_exception_class is not None
            and self.root_exception_class not in SAFE_ROOT_ERROR_NAMES
        ):
            raise ValueError("root exception class is outside the public allowlist")

        success_outcomes = {
            "success_nonempty",
            "success_empty",
            "static_snapshot_success",
        }
        failed_response_outcomes = {
            "http_transient_error",
            "http_application_error",
            "malformed_json",
            "application_error_envelope",
            "contract_mismatch",
            "parser_failure",
        }
        no_response_outcomes = {
            "transport_failure_no_response",
            "cancelled_before_response",
        }

        if self.outcome in success_outcomes:
            if self.lifecycle != "selected_terminal" or self.failure_class is not None:
                raise ValueError("successful outcome must be a failure-free terminal selection")
            if self.capture_response_receipt_sha256 is None:
                raise ValueError("successful terminal selection lacks its capture receipt")
            if self.logical_receipt_sha256 is None:
                raise ValueError("successful terminal selection lacks its logical receipt")
            if self.route_landing_count < 1:
                raise ValueError("successful outcome lacks a response-level route landing")
            if self.result_occurrence_count < 1 and not _is_exact_unknown_dynamic_video_attempt(
                self.attempt
            ):
                raise ValueError("successful outcome lacks a declared result occurrence")
        elif self.outcome == "downstream_incomplete":
            if self.lifecycle != "incomplete" or self.failure_class is None:
                raise ValueError("downstream failure must remain typed incomplete")
            if self.capture_response_receipt_sha256 is None:
                raise ValueError("downstream-incomplete observation lacks its capture receipt")
            if self.logical_receipt_sha256 is not None:
                raise ValueError("downstream-incomplete observation cannot close logically")
        elif self.outcome in failed_response_outcomes | no_response_outcomes:
            if self.lifecycle != "incomplete":
                raise ValueError("failed observation must remain incomplete")
            if self.failure_class is None:
                raise ValueError("failed observation lacks typed public-safe failure evidence")
            if self.logical_receipt_sha256 is not None:
                raise ValueError("failed observation cannot close logically")

        if self.outcome not in success_outcomes and (
            self.route_landing_count != 0
            or self.route_landings_sha256 != BODYLESS_ROUTE_LANDINGS_SHA256
        ):
            raise ValueError("nonterminal observation cannot carry route landings")

        if self.capture_response_receipt_sha256 is not None and self.outcome not in (
            success_outcomes | {"downstream_incomplete"}
        ):
            raise ValueError("capture receipt cannot be fabricated for this outcome")

        if self.body_disposition == "public_parser_input":
            if (
                self.attempt.source_family == "static"
                or self.body_object_sha256 is None
                or self.bodyless_evidence_sha256 is not None
                or self.outcome
                not in {"success_nonempty", "success_empty", "downstream_incomplete"}
            ):
                raise ValueError("public parser-input disposition is inconsistent")
            if status_code is None or effective_status_code is None:
                raise ValueError("successful parser input requires observed HTTP status")
            if not (200 <= status_code <= 299 and 200 <= effective_status_code <= 299):
                raise ValueError("successful parser input requires successful HTTP status")
        elif self.body_disposition == "declared_bodyless":
            if (
                self.attempt.source_family != "static"
                or transport.transport_kind != "static_snapshot"
                or self.outcome != "static_snapshot_success"
                or self.body_object_sha256 is not None
                or self.bodyless_evidence_sha256 is None
                or status_code is not None
                or effective_status_code is not None
            ):
                raise ValueError("declared-bodyless disposition is inconsistent")
        elif self.body_disposition == "no_response":
            if (
                self.body_object_sha256 is not None
                or self.bodyless_evidence_sha256 is None
                or self.result_occurrence_count != 0
                or self.result_occurrences_sha256 != BODYLESS_RESULT_OCCURRENCES_SHA256
                or self.route_landing_count != 0
                or self.route_landings_sha256 != BODYLESS_ROUTE_LANDINGS_SHA256
                or status_code is not None
                or effective_status_code is not None
                or self.outcome not in no_response_outcomes | {"allocated"}
            ):
                raise ValueError("no-response disposition is inconsistent")
        else:
            if (
                self.body_object_sha256 is not None
                or self.bodyless_evidence_sha256 is None
                or self.result_occurrence_count != 0
                or self.result_occurrences_sha256 != BODYLESS_RESULT_OCCURRENCES_SHA256
                or self.route_landing_count != 0
                or self.route_landings_sha256 != BODYLESS_ROUTE_LANDINGS_SHA256
                or self.outcome not in failed_response_outcomes
                or status_code is None
            ):
                raise ValueError("excluded-failure-body disposition is inconsistent")
            if self.outcome == "http_transient_error" and not (
                status_code == 429 or status_code >= 500
            ):
                raise ValueError("transient HTTP outcome requires HTTP 429 or 5xx")
            if self.outcome == "http_application_error" and not (
                400 <= status_code <= 499 and status_code != 429
            ):
                raise ValueError("application HTTP outcome requires non-429 HTTP 4xx")

        expected_body_receipt = _sha256_json(
            _body_authority_receipt_payload(
                observation_sha256=self.attempt.observation_sha256,
                body_disposition=self.body_disposition,
                body_object_sha256=self.body_object_sha256,
                bodyless_evidence_sha256=self.bodyless_evidence_sha256,
            )
        )
        if self.body_authority_receipt_sha256 != expected_body_receipt:
            raise ValueError("body authority receipt digest is invalid")
        expected_public_receipt = _sha256_json(
            {
                "schema_version": RAW_REQUEST_AUTHORITY_SCHEMA_VERSION,
                "observation_sha256": self.attempt.observation_sha256,
                "attempt_sha256": self.attempt.attempt_sha256,
                "body_authority_receipt_sha256": self.body_authority_receipt_sha256,
                "result_occurrence_count": self.result_occurrence_count,
                "result_occurrences_sha256": self.result_occurrences_sha256,
                "route_landing_count": self.route_landing_count,
                "route_landings_sha256": self.route_landings_sha256,
                "capture_response_receipt_sha256": self.capture_response_receipt_sha256,
                "logical_receipt_sha256": self.logical_receipt_sha256,
                "logical_provider_parameter_binding_sha256": (
                    self.logical_provider_parameter_binding_sha256
                ),
                "logical_provider_parameter_binding_json": (
                    self.logical_provider_parameter_binding_json
                ),
                "lifecycle": self.lifecycle,
                "outcome": self.outcome,
            }
        )
        if self.public_authority_receipt_sha256 != expected_public_receipt:
            raise ValueError("public authority receipt digest is invalid")
        expected_record = _sha256_json(
            _observation_record_payload(
                attempt=self.attempt,
                transport=transport,
                started_at=self.started_at,
                finished_at=self.finished_at,
                elapsed_ns=self.elapsed_ns,
                lifecycle=self.lifecycle,
                outcome=self.outcome,
                failure_class=self.failure_class,
                root_exception_class=self.root_exception_class,
                body_disposition=self.body_disposition,
                body_object_sha256=self.body_object_sha256,
                bodyless_evidence_sha256=self.bodyless_evidence_sha256,
                body_authority_receipt_sha256=self.body_authority_receipt_sha256,
                result_occurrence_count=self.result_occurrence_count,
                result_occurrences_sha256=self.result_occurrences_sha256,
                route_landing_count=self.route_landing_count,
                route_landings_sha256=self.route_landings_sha256,
                capture_response_receipt_sha256=self.capture_response_receipt_sha256,
                logical_receipt_sha256=self.logical_receipt_sha256,
                logical_provider_parameter_binding_sha256=(
                    self.logical_provider_parameter_binding_sha256
                ),
                logical_provider_parameter_binding_json=(
                    self.logical_provider_parameter_binding_json
                ),
                public_authority_receipt_sha256=self.public_authority_receipt_sha256,
            )
        )
        if self.observation_record_sha256 != expected_record:
            raise ValueError("request-observation record digest is invalid")
        return self

    @classmethod
    def build(
        cls,
        *,
        attempt: RequestAttemptIdentityV2,
        transport: object,
        started_at: datetime,
        finished_at: datetime | None,
        elapsed_ns: int | None,
        lifecycle: ObservationLifecycle,
        outcome: ObservationOutcome,
        failure_class: FailureClass | None,
        root_exception_class: str | None,
        body_disposition: ObservationBodyDisposition,
        body_object_sha256: str | None,
        bodyless_evidence_sha256: str | None,
        result_occurrence_sha256s: Sequence[str],
        route_landing_sha256s: Sequence[str],
        capture_response_receipt_sha256: str | None,
        logical_receipt_sha256: str | None,
        logical_provider_parameter_binding_sha256: str | None = None,
        logical_provider_parameter_binding_json: str | None = None,
    ) -> Self:
        attempt = validate_request_attempt_identity(attempt)
        parsed_transport = validate_raw_transport(transport)
        if len(result_occurrence_sha256s) > MAX_AUTHORITY_ROWS:
            raise RawRequestAuthorityError("result occurrence inventory exceeds its bound")
        result_ids = list(result_occurrence_sha256s)
        if any(
            not isinstance(item, str) or _SHA256_RE.fullmatch(item) is None for item in result_ids
        ):
            raise RawRequestAuthorityError("result occurrence inventory is invalid")
        result_occurrences_sha256 = _sha256_json(
            result_ids,
            maximum_bytes=MAX_RESULT_JSON_BYTES,
        )
        if len(route_landing_sha256s) > MAX_AUTHORITY_ROWS:
            raise RawRequestAuthorityError("route landing inventory exceeds its bound")
        landing_ids = list(route_landing_sha256s)
        if any(type(item) is not str or _SHA256_RE.fullmatch(item) is None for item in landing_ids):
            raise RawRequestAuthorityError("route landing inventory is invalid")
        route_landings_sha256 = _sha256_json(
            landing_ids,
            maximum_bytes=MAX_RESULT_JSON_BYTES,
        )
        body_authority_receipt_sha256 = _sha256_json(
            _body_authority_receipt_payload(
                observation_sha256=attempt.observation_sha256,
                body_disposition=body_disposition,
                body_object_sha256=body_object_sha256,
                bodyless_evidence_sha256=bodyless_evidence_sha256,
            )
        )
        public_authority_receipt_sha256 = _sha256_json(
            {
                "schema_version": RAW_REQUEST_AUTHORITY_SCHEMA_VERSION,
                "observation_sha256": attempt.observation_sha256,
                "attempt_sha256": attempt.attempt_sha256,
                "body_authority_receipt_sha256": body_authority_receipt_sha256,
                "result_occurrence_count": len(result_ids),
                "result_occurrences_sha256": result_occurrences_sha256,
                "route_landing_count": len(landing_ids),
                "route_landings_sha256": route_landings_sha256,
                "capture_response_receipt_sha256": capture_response_receipt_sha256,
                "logical_receipt_sha256": logical_receipt_sha256,
                "logical_provider_parameter_binding_sha256": (
                    logical_provider_parameter_binding_sha256
                ),
                "logical_provider_parameter_binding_json": (
                    logical_provider_parameter_binding_json
                ),
                "lifecycle": lifecycle,
                "outcome": outcome,
            }
        )
        record_payload = _observation_record_payload(
            attempt=attempt,
            transport=parsed_transport,
            started_at=started_at,
            finished_at=finished_at,
            elapsed_ns=elapsed_ns,
            lifecycle=lifecycle,
            outcome=outcome,
            failure_class=failure_class,
            root_exception_class=root_exception_class,
            body_disposition=body_disposition,
            body_object_sha256=body_object_sha256,
            bodyless_evidence_sha256=bodyless_evidence_sha256,
            body_authority_receipt_sha256=body_authority_receipt_sha256,
            result_occurrence_count=len(result_ids),
            result_occurrences_sha256=result_occurrences_sha256,
            route_landing_count=len(landing_ids),
            route_landings_sha256=route_landings_sha256,
            capture_response_receipt_sha256=capture_response_receipt_sha256,
            logical_receipt_sha256=logical_receipt_sha256,
            logical_provider_parameter_binding_sha256=(logical_provider_parameter_binding_sha256),
            logical_provider_parameter_binding_json=(logical_provider_parameter_binding_json),
            public_authority_receipt_sha256=public_authority_receipt_sha256,
        )
        return cls(
            schema_version=RAW_REQUEST_AUTHORITY_SCHEMA_VERSION,
            observation_record_sha256=_sha256_json(record_payload),
            attempt=attempt,
            transport=parsed_transport,
            started_at=started_at,
            finished_at=finished_at,
            elapsed_ns=elapsed_ns,
            lifecycle=lifecycle,
            outcome=outcome,
            failure_class=failure_class,
            root_exception_class=root_exception_class,
            body_disposition=body_disposition,
            body_object_sha256=body_object_sha256,
            bodyless_evidence_sha256=bodyless_evidence_sha256,
            body_authority_receipt_sha256=body_authority_receipt_sha256,
            result_occurrence_count=len(result_ids),
            result_occurrences_sha256=result_occurrences_sha256,
            route_landing_count=len(landing_ids),
            route_landings_sha256=route_landings_sha256,
            capture_response_receipt_sha256=capture_response_receipt_sha256,
            logical_receipt_sha256=logical_receipt_sha256,
            logical_provider_parameter_binding_sha256=(logical_provider_parameter_binding_sha256),
            logical_provider_parameter_binding_json=(logical_provider_parameter_binding_json),
            public_authority_receipt_sha256=public_authority_receipt_sha256,
        )

    def to_row(self) -> dict[str, object]:
        attempt = self.attempt.to_dict()
        transport = canonical_transport_payload(self.transport)
        return {
            "schema_version": self.schema_version,
            "observation_sha256": attempt.pop("observation_sha256"),
            "observation_record_sha256": self.observation_record_sha256,
            **attempt,
            "transport_kind": transport["transport_kind"],
            "status_code": transport.get("status_code"),
            "effective_status_code": transport.get("effective_status_code"),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_ns": self.elapsed_ns,
            "lifecycle": self.lifecycle,
            "outcome": self.outcome,
            "failure_class": self.failure_class,
            "root_exception_class": self.root_exception_class,
            "body_disposition": self.body_disposition,
            "body_object_sha256": self.body_object_sha256,
            "bodyless_evidence_sha256": self.bodyless_evidence_sha256,
            "body_authority_receipt_sha256": self.body_authority_receipt_sha256,
            "result_occurrence_count": self.result_occurrence_count,
            "result_occurrences_sha256": self.result_occurrences_sha256,
            "route_landing_count": self.route_landing_count,
            "route_landings_sha256": self.route_landings_sha256,
            "capture_response_receipt_sha256": self.capture_response_receipt_sha256,
            "logical_receipt_sha256": self.logical_receipt_sha256,
            "logical_provider_parameter_binding_sha256": (
                self.logical_provider_parameter_binding_sha256
            ),
            "logical_provider_parameter_binding_json": (
                self.logical_provider_parameter_binding_json
            ),
            "public_authority_receipt_sha256": self.public_authority_receipt_sha256,
        }

    def to_canonical_bytes(self) -> bytes:
        return canonical_json_bytes(
            _observation_record_payload(
                attempt=self.attempt,
                transport=self.transport,
                started_at=self.started_at,
                finished_at=self.finished_at,
                elapsed_ns=self.elapsed_ns,
                lifecycle=self.lifecycle,
                outcome=self.outcome,
                failure_class=self.failure_class,
                root_exception_class=self.root_exception_class,
                body_disposition=self.body_disposition,
                body_object_sha256=self.body_object_sha256,
                bodyless_evidence_sha256=self.bodyless_evidence_sha256,
                body_authority_receipt_sha256=self.body_authority_receipt_sha256,
                result_occurrence_count=self.result_occurrence_count,
                result_occurrences_sha256=self.result_occurrences_sha256,
                route_landing_count=self.route_landing_count,
                route_landings_sha256=self.route_landings_sha256,
                capture_response_receipt_sha256=self.capture_response_receipt_sha256,
                logical_receipt_sha256=self.logical_receipt_sha256,
                logical_provider_parameter_binding_sha256=(
                    self.logical_provider_parameter_binding_sha256
                ),
                logical_provider_parameter_binding_json=(
                    self.logical_provider_parameter_binding_json
                ),
                public_authority_receipt_sha256=self.public_authority_receipt_sha256,
            )
            | {"observation_record_sha256": self.observation_record_sha256}
        )

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> Self:
        payload = _decode_canonical_json_object(
            encoded,
            maximum_bytes=MAX_CANONICAL_JSON_BYTES,
        )
        expected_fields = {
            "schema_version",
            "attempt",
            "transport",
            "started_at",
            "finished_at",
            "elapsed_ns",
            "lifecycle",
            "outcome",
            "failure_class",
            "root_exception_class",
            "body_disposition",
            "body_object_sha256",
            "bodyless_evidence_sha256",
            "body_authority_receipt_sha256",
            "result_occurrence_count",
            "result_occurrences_sha256",
            "route_landing_count",
            "route_landings_sha256",
            "capture_response_receipt_sha256",
            "logical_receipt_sha256",
            "logical_provider_parameter_binding_sha256",
            "logical_provider_parameter_binding_json",
            "public_authority_receipt_sha256",
            "observation_record_sha256",
        }
        if set(payload) != expected_fields:
            raise RawRequestAuthorityError("request-observation fields are invalid")
        for field_name in ("started_at", "finished_at"):
            value = payload[field_name]
            if value is None and field_name == "finished_at":
                continue
            if not isinstance(value, str) or not value.endswith("Z"):
                raise RawRequestAuthorityError("request-observation timestamp is invalid")
            try:
                parsed = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
            except ValueError as exc:
                raise RawRequestAuthorityError("request-observation timestamp is invalid") from exc
            if _canonical_timestamp(parsed, field_name=field_name) != value:
                raise RawRequestAuthorityError("request-observation timestamp is noncanonical")
            payload[field_name] = parsed
        payload["attempt"] = validate_request_attempt_identity(payload["attempt"])
        payload["transport"] = validate_raw_transport(payload["transport"])
        return cast("Self", validate_request_observation(payload))


def _canonical_list_text(
    value: Sequence[object],
    *,
    maximum_bytes: int,
) -> tuple[str, str, list[object]]:
    if isinstance(value, (str, bytes, bytearray)):
        raise RawRequestAuthorityError("canonical list value must be a sequence")
    materialized = list(value)
    encoded = canonical_json_bytes(materialized, maximum_bytes=maximum_bytes)
    return encoded.decode("utf-8"), _sha256_bytes(encoded), materialized


def _decode_canonical_json_list(encoded: str, *, maximum_bytes: int) -> list[object]:
    if not isinstance(encoded, str):
        raise RawRequestAuthorityError("authority list JSON must be text")
    raw = encoded.encode("utf-8", errors="strict")
    value = _bounded_json_value(raw, maximum_bytes=maximum_bytes)
    if not isinstance(value, list):
        raise RawRequestAuthorityError("authority JSON root must be a list")
    if raw != canonical_json_bytes(value, maximum_bytes=maximum_bytes):
        raise RawRequestAuthorityError("authority JSON bytes are not canonical")
    return cast("list[object]", value)


def _validate_json_path(value: str | None) -> None:
    if value is None:
        return
    if (
        not isinstance(value, str)
        or not value.startswith("$")
        or len(value) > 1_024
        or ".." in value
        or "/" in value
        or "\\" in value
        or "@" in value
        or _LOCAL_PATH_RE.search(value.encode("utf-8"))
    ):
        raise RawRequestAuthorityError("result JSON path is unsafe or noncanonical")


def _result_occurrence_payload(
    *,
    observation_sha256: str,
    occurrence_ordinal: int,
    result_name: str,
    duplicate_name_ordinal: int,
    provider_result_ordinal: int | None,
    canonical_result_ordinal: int | None,
    json_path: str | None,
    container_kind: ResultContainerKind,
    presence: ResultPresence,
    ordered_headers_json: str,
    ordered_headers_sha256: str,
    header_count: int,
    row_count: int,
    cell_count: int,
    node_count: int,
    container_count: int,
    missing_count: int,
    null_count: int,
    parent_state_sha256: str | None,
    output_sha256: str,
    canonical_route_ids_json: str,
    canonical_route_ids_sha256: str,
    committed_staging_receipts_json: str,
    committed_staging_receipts_sha256: str,
    landing_disposition: LandingDisposition,
    logical_result_receipt_sha256: str,
    route_receipt_sha256: str,
) -> dict[str, object]:
    return {
        "schema_version": RAW_REQUEST_AUTHORITY_SCHEMA_VERSION,
        "observation_sha256": observation_sha256,
        "occurrence_ordinal": occurrence_ordinal,
        "result_name": result_name,
        "duplicate_name_ordinal": duplicate_name_ordinal,
        "provider_result_ordinal": provider_result_ordinal,
        "canonical_result_ordinal": canonical_result_ordinal,
        "json_path": json_path,
        "container_kind": container_kind,
        "presence": presence,
        "ordered_headers_json": ordered_headers_json,
        "ordered_headers_sha256": ordered_headers_sha256,
        "header_count": header_count,
        "row_count": row_count,
        "cell_count": cell_count,
        "node_count": node_count,
        "container_count": container_count,
        "missing_count": missing_count,
        "null_count": null_count,
        "parent_state_sha256": parent_state_sha256,
        "output_sha256": output_sha256,
        "canonical_route_ids_json": canonical_route_ids_json,
        "canonical_route_ids_sha256": canonical_route_ids_sha256,
        "committed_staging_receipts_json": committed_staging_receipts_json,
        "committed_staging_receipts_sha256": committed_staging_receipts_sha256,
        "landing_disposition": landing_disposition,
        "logical_result_receipt_sha256": logical_result_receipt_sha256,
        "route_receipt_sha256": route_receipt_sha256,
    }


class ResultOccurrenceV2(_StrictFrozenModel):
    """One ordered result occurrence; duplicate provider names remain distinct."""

    schema_version: SchemaVersion
    occurrence_sha256: Sha256
    observation_sha256: Sha256
    occurrence_ordinal: NonNegativeInt
    result_name: ResultName
    duplicate_name_ordinal: NonNegativeInt
    provider_result_ordinal: NonNegativeInt | None
    canonical_result_ordinal: NonNegativeInt | None
    json_path: Annotated[str, StringConstraints(min_length=1, max_length=1_024)] | None
    container_kind: ResultContainerKind
    presence: ResultPresence
    ordered_headers_json: Annotated[str, StringConstraints(min_length=2, max_length=4_194_304)]
    ordered_headers_sha256: Sha256
    header_count: NonNegativeInt
    row_count: NonNegativeInt
    cell_count: NonNegativeInt
    node_count: NonNegativeInt
    container_count: NonNegativeInt
    missing_count: NonNegativeInt
    null_count: NonNegativeInt
    parent_state_sha256: Sha256 | None
    output_sha256: Sha256
    canonical_route_ids_json: Annotated[str, StringConstraints(min_length=3, max_length=4_194_304)]
    canonical_route_ids_sha256: Sha256
    committed_staging_receipts_json: Annotated[
        str,
        StringConstraints(min_length=2, max_length=4_194_304),
    ]
    committed_staging_receipts_sha256: Sha256
    landing_disposition: LandingDisposition
    logical_result_receipt_sha256: Sha256
    route_receipt_sha256: Sha256

    @model_validator(mode="after")
    def _validate_occurrence(self) -> Self:
        _validate_json_path(self.json_path)
        headers = _decode_canonical_json_list(
            self.ordered_headers_json,
            maximum_bytes=MAX_RESULT_JSON_BYTES,
        )
        if len(headers) != self.header_count or any(
            not isinstance(item, str)
            or not item
            or len(item) > 256
            or _FORBIDDEN_BODY_KEY_RE.fullmatch(_normalized_public_key(item)) is not None
            for item in headers
        ):
            raise ValueError("ordered result headers are invalid")
        if self.ordered_headers_sha256 != _sha256_bytes(self.ordered_headers_json.encode("utf-8")):
            raise ValueError("ordered result headers digest is invalid")

        route_values = _decode_canonical_json_list(
            self.canonical_route_ids_json,
            maximum_bytes=MAX_RESULT_JSON_BYTES,
        )
        if not route_values or any(
            not isinstance(item, str) or _SAFE_ID_RE.fullmatch(item) is None
            for item in route_values
        ):
            raise ValueError("canonical result route inventory is invalid")
        route_ids = cast("list[str]", route_values)
        if len(set(route_ids)) != len(route_ids):
            raise ValueError("canonical result route inventory is invalid")
        if any(_FORBIDDEN_IDENTITY_RE.search(route_id) for route_id in route_ids):
            raise ValueError("canonical result route inventory is unsafe")
        if self.canonical_route_ids_sha256 != _sha256_bytes(
            self.canonical_route_ids_json.encode("utf-8")
        ):
            raise ValueError("canonical result route digest is invalid")

        receipt_values = _decode_canonical_json_list(
            self.committed_staging_receipts_json,
            maximum_bytes=MAX_RESULT_JSON_BYTES,
        )
        receipt_routes: list[str] = []
        for receipt in receipt_values:
            if not isinstance(receipt, dict) or set(receipt) != {
                "receipt_sha256",
                "route_id",
            }:
                raise ValueError("committed staging receipt inventory is invalid")
            receipt_mapping = cast("dict[str, object]", receipt)
            route_id = receipt_mapping["route_id"]
            receipt_sha256 = receipt_mapping["receipt_sha256"]
            if (
                not isinstance(route_id, str)
                or route_id not in route_ids
                or not isinstance(receipt_sha256, str)
                or _SHA256_RE.fullmatch(receipt_sha256) is None
            ):
                raise ValueError("committed staging receipt inventory is invalid")
            receipt_routes.append(route_id)
        if len(receipt_routes) != len(set(receipt_routes)):
            raise ValueError("committed staging receipt routes must be unique")
        if self.committed_staging_receipts_sha256 != _sha256_bytes(
            self.committed_staging_receipts_json.encode("utf-8")
        ):
            raise ValueError("committed staging receipt digest is invalid")

        if (
            self.presence
            not in {
                "missing",
                "mixed_absent",
                "not_observed_parent_empty",
            }
            and self.container_count < 1
        ):
            raise ValueError("result occurrence must declare its root container")
        if self.container_kind == "nba_api_result_set":
            if self.json_path is not None:
                raise ValueError("stats result sets do not use live JSON paths")
            if self.cell_count != self.header_count * self.row_count:
                raise ValueError("stats result cell count does not match rows and headers")
        elif self.json_path is None:
            raise ValueError("live/static result roots require a canonical JSON path")
        if self.presence == "not_observed_parent_empty":
            if (
                self.container_kind
                not in {
                    "nba_api_live_json_array",
                    "nba_api_live_json_object",
                }
                or self.parent_state_sha256 is None
                or any(
                    value != 0
                    for value in (
                        self.row_count,
                        self.cell_count,
                        self.node_count,
                        self.container_count,
                        self.missing_count,
                        self.null_count,
                    )
                )
            ):
                raise ValueError("parent-empty unobserved live result counts are inconsistent")
        elif self.presence == "missing":
            if (
                self.container_count != 0
                or self.missing_count < 1
                or any(
                    value != 0
                    for value in (
                        self.header_count,
                        self.row_count,
                        self.cell_count,
                        self.node_count,
                        self.null_count,
                    )
                )
            ):
                raise ValueError("missing result occurrence counts are inconsistent")
        elif self.presence == "null":
            if self.null_count < 1 or any(
                value != 0
                for value in (
                    self.header_count,
                    self.row_count,
                    self.cell_count,
                    self.missing_count,
                )
            ):
                raise ValueError("null result occurrence counts are inconsistent")
        elif self.presence == "mixed_absent":
            if (
                self.container_kind
                not in {
                    "nba_api_live_json_array",
                    "nba_api_live_json_object",
                }
                or self.container_count != self.null_count
                or self.missing_count < 1
                or self.null_count < 1
                or any(
                    value != 0
                    for value in (
                        self.header_count,
                        self.row_count,
                        self.cell_count,
                    )
                )
                or self.node_count != self.null_count
            ):
                raise ValueError("mixed-absent result occurrence counts are inconsistent")
        elif self.presence == "present_empty":
            if any(
                value != 0
                for value in (
                    self.row_count,
                    self.cell_count,
                    self.node_count,
                    self.missing_count,
                    self.null_count,
                )
            ):
                raise ValueError("present-empty result occurrence counts are inconsistent")
        elif self.presence == "empty_object":
            if (
                self.container_kind != "nba_api_live_json_object"
                or any(
                    value != 0
                    for value in (
                        self.header_count,
                        self.row_count,
                        self.cell_count,
                        self.missing_count,
                        self.null_count,
                    )
                )
                or self.node_count != 1
            ):
                raise ValueError("empty-object result occurrence counts are inconsistent")
        elif self.presence == "empty_array":
            if (
                self.container_kind
                not in {
                    "nba_api_static_records",
                    "nba_api_live_json_array",
                }
                or any(
                    value != 0
                    for value in (
                        self.header_count,
                        self.row_count,
                        self.cell_count,
                        self.missing_count,
                        self.null_count,
                    )
                )
                or self.node_count != 1
            ):
                raise ValueError("empty-array result occurrence counts are inconsistent")
        elif self.row_count == 0 and self.node_count == 0:
            raise ValueError("present result occurrence lacks rows or nodes")

        logical_payload = {
            "schema_version": RAW_REQUEST_AUTHORITY_SCHEMA_VERSION,
            "observation_sha256": self.observation_sha256,
            "occurrence_ordinal": self.occurrence_ordinal,
            "result_name": self.result_name,
            "duplicate_name_ordinal": self.duplicate_name_ordinal,
            "provider_result_ordinal": self.provider_result_ordinal,
            "canonical_result_ordinal": self.canonical_result_ordinal,
            "json_path": self.json_path,
            "container_kind": self.container_kind,
            "presence": self.presence,
            "ordered_headers_sha256": self.ordered_headers_sha256,
            "header_count": self.header_count,
            "row_count": self.row_count,
            "cell_count": self.cell_count,
            "node_count": self.node_count,
            "container_count": self.container_count,
            "missing_count": self.missing_count,
            "null_count": self.null_count,
            "parent_state_sha256": self.parent_state_sha256,
            "output_sha256": self.output_sha256,
        }
        if self.logical_result_receipt_sha256 != _sha256_json(logical_payload):
            raise ValueError("logical result receipt digest is invalid")
        expected_route_receipt = _sha256_json(
            {
                "logical_result_receipt_sha256": self.logical_result_receipt_sha256,
                "canonical_route_ids_sha256": self.canonical_route_ids_sha256,
                "landing_disposition": self.landing_disposition,
            }
        )
        if self.route_receipt_sha256 != expected_route_receipt:
            raise ValueError("result route receipt digest is invalid")
        expected_occurrence = _sha256_json(
            _result_occurrence_payload(
                observation_sha256=self.observation_sha256,
                occurrence_ordinal=self.occurrence_ordinal,
                result_name=self.result_name,
                duplicate_name_ordinal=self.duplicate_name_ordinal,
                provider_result_ordinal=self.provider_result_ordinal,
                canonical_result_ordinal=self.canonical_result_ordinal,
                json_path=self.json_path,
                container_kind=self.container_kind,
                presence=self.presence,
                ordered_headers_json=self.ordered_headers_json,
                ordered_headers_sha256=self.ordered_headers_sha256,
                header_count=self.header_count,
                row_count=self.row_count,
                cell_count=self.cell_count,
                node_count=self.node_count,
                container_count=self.container_count,
                missing_count=self.missing_count,
                null_count=self.null_count,
                parent_state_sha256=self.parent_state_sha256,
                output_sha256=self.output_sha256,
                canonical_route_ids_json=self.canonical_route_ids_json,
                canonical_route_ids_sha256=self.canonical_route_ids_sha256,
                committed_staging_receipts_json=self.committed_staging_receipts_json,
                committed_staging_receipts_sha256=self.committed_staging_receipts_sha256,
                landing_disposition=self.landing_disposition,
                logical_result_receipt_sha256=self.logical_result_receipt_sha256,
                route_receipt_sha256=self.route_receipt_sha256,
            )
        )
        if self.occurrence_sha256 != expected_occurrence:
            raise ValueError("result occurrence digest is invalid")
        return self

    @classmethod
    def build(
        cls,
        *,
        observation_sha256: str,
        occurrence_ordinal: int,
        result_name: str,
        duplicate_name_ordinal: int,
        provider_result_ordinal: int | None,
        canonical_result_ordinal: int | None,
        json_path: str | None,
        container_kind: ResultContainerKind,
        presence: ResultPresence,
        ordered_headers: Sequence[str],
        row_count: int,
        cell_count: int,
        node_count: int,
        container_count: int,
        missing_count: int,
        null_count: int,
        parent_state_sha256: str | None,
        output_sha256: str,
        canonical_route_ids: Sequence[str],
        committed_staging_receipts: Sequence[Mapping[str, str]],
        landing_disposition: LandingDisposition,
    ) -> Self:
        _validate_json_path(json_path)
        headers_json, headers_sha256, headers = _canonical_list_text(
            list(ordered_headers),
            maximum_bytes=MAX_RESULT_JSON_BYTES,
        )
        routes_json, routes_sha256, routes = _canonical_list_text(
            list(canonical_route_ids),
            maximum_bytes=MAX_RESULT_JSON_BYTES,
        )
        receipt_payloads = [dict(item) for item in committed_staging_receipts]
        receipts_json, receipts_sha256, _ = _canonical_list_text(
            receipt_payloads,
            maximum_bytes=MAX_RESULT_JSON_BYTES,
        )
        logical_payload = {
            "schema_version": RAW_REQUEST_AUTHORITY_SCHEMA_VERSION,
            "observation_sha256": observation_sha256,
            "occurrence_ordinal": occurrence_ordinal,
            "result_name": result_name,
            "duplicate_name_ordinal": duplicate_name_ordinal,
            "provider_result_ordinal": provider_result_ordinal,
            "canonical_result_ordinal": canonical_result_ordinal,
            "json_path": json_path,
            "container_kind": container_kind,
            "presence": presence,
            "ordered_headers_sha256": headers_sha256,
            "header_count": len(headers),
            "row_count": row_count,
            "cell_count": cell_count,
            "node_count": node_count,
            "container_count": container_count,
            "missing_count": missing_count,
            "null_count": null_count,
            "parent_state_sha256": parent_state_sha256,
            "output_sha256": output_sha256,
        }
        logical_result_receipt_sha256 = _sha256_json(logical_payload)
        route_receipt_sha256 = _sha256_json(
            {
                "logical_result_receipt_sha256": logical_result_receipt_sha256,
                "canonical_route_ids_sha256": routes_sha256,
                "landing_disposition": landing_disposition,
            }
        )
        payload = _result_occurrence_payload(
            observation_sha256=observation_sha256,
            occurrence_ordinal=occurrence_ordinal,
            result_name=result_name,
            duplicate_name_ordinal=duplicate_name_ordinal,
            provider_result_ordinal=provider_result_ordinal,
            canonical_result_ordinal=canonical_result_ordinal,
            json_path=json_path,
            container_kind=container_kind,
            presence=presence,
            ordered_headers_json=headers_json,
            ordered_headers_sha256=headers_sha256,
            header_count=len(headers),
            row_count=row_count,
            cell_count=cell_count,
            node_count=node_count,
            container_count=container_count,
            missing_count=missing_count,
            null_count=null_count,
            parent_state_sha256=parent_state_sha256,
            output_sha256=output_sha256,
            canonical_route_ids_json=routes_json,
            canonical_route_ids_sha256=routes_sha256,
            committed_staging_receipts_json=receipts_json,
            committed_staging_receipts_sha256=receipts_sha256,
            landing_disposition=landing_disposition,
            logical_result_receipt_sha256=logical_result_receipt_sha256,
            route_receipt_sha256=route_receipt_sha256,
        )
        return cls.model_validate(
            {"occurrence_sha256": _sha256_json(payload), **payload},
            strict=True,
        )

    def to_row(self) -> dict[str, object]:
        return dict(self.model_dump(mode="python", round_trip=True))

    def ordered_headers(self) -> tuple[str, ...]:
        """Return the exact provider header sequence bound by this occurrence."""

        occurrence = validate_result_occurrence(self)
        values = _decode_canonical_json_list(
            occurrence.ordered_headers_json,
            maximum_bytes=MAX_RESULT_JSON_BYTES,
        )
        if len(values) != occurrence.header_count or any(
            type(value) is not str for value in values
        ):
            raise RawRequestAuthorityError("ordered result header authority is invalid")
        return tuple(cast("list[str]", values))

    def canonical_route_ids(self) -> tuple[str, ...]:
        """Return the exact ordered canonical-route inventory for this occurrence."""

        occurrence = validate_result_occurrence(self)
        values = _decode_canonical_json_list(
            occurrence.canonical_route_ids_json,
            maximum_bytes=MAX_RESULT_JSON_BYTES,
        )
        if not values or any(type(value) is not str for value in values):
            raise RawRequestAuthorityError("canonical result route authority is invalid")
        route_ids = tuple(cast("list[str]", values))
        if len(route_ids) != len(set(route_ids)):
            raise RawRequestAuthorityError("canonical result route authority is duplicated")
        return route_ids

    def committed_staging_receipts_by_route(self) -> Mapping[str, str]:
        """Return a read-only exact route-to-committed-receipt authority mapping."""

        occurrence = validate_result_occurrence(self)
        values = _decode_canonical_json_list(
            occurrence.committed_staging_receipts_json,
            maximum_bytes=MAX_RESULT_JSON_BYTES,
        )
        receipts: dict[str, str] = {}
        for value in values:
            if type(value) is not dict or set(value) != {"receipt_sha256", "route_id"}:
                raise RawRequestAuthorityError("committed staging receipt authority is invalid")
            receipt = cast("dict[str, object]", value)
            route_id = receipt["route_id"]
            receipt_sha256 = receipt["receipt_sha256"]
            if type(route_id) is not str or type(receipt_sha256) is not str or route_id in receipts:
                raise RawRequestAuthorityError(
                    "committed staging receipt authority is invalid or duplicated"
                )
            receipts[route_id] = receipt_sha256
        if not set(receipts).issubset(occurrence.canonical_route_ids()):
            raise RawRequestAuthorityError(
                "committed staging receipt authority references a foreign route"
            )
        return MappingProxyType(receipts)

    def to_canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_row())

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> Self:
        return cast(
            "Self",
            validate_result_occurrence(
                _decode_canonical_json_object(
                    encoded,
                    maximum_bytes=MAX_CANONICAL_JSON_BYTES,
                )
            ),
        )


def _committed_staging_identity_payload(
    *,
    committed_receipt_schema_version: int,
    committed_receipt_kind: str,
    chunk_id: str,
    staging_key: str,
    canonical_frame_format: str,
    frame_content_hash_contract: str,
    frame_schema_hash_contract: str,
    content_hash: str,
    persisted_row_count: int,
    persisted_content_sha256: str,
    persisted_schema_sha256: str,
    logical_call_receipt_sha256: str,
    provider_authority_sha256: str,
    logical_parameters_sha256: str,
    result_route_id: str,
) -> dict[str, object]:
    return {
        "schema_version": committed_receipt_schema_version,
        "kind": committed_receipt_kind,
        "chunk_id": chunk_id,
        "staging_key": staging_key,
        "canonical_frame_format": canonical_frame_format,
        "frame_content_hash_contract": frame_content_hash_contract,
        "frame_schema_hash_contract": frame_schema_hash_contract,
        "content_hash": content_hash,
        "persisted_row_count": persisted_row_count,
        "persisted_content_sha256": persisted_content_sha256,
        "persisted_schema_sha256": persisted_schema_sha256,
        "logical_call_receipt_sha256": logical_call_receipt_sha256,
        "provider_authority_sha256": provider_authority_sha256,
        "logical_parameters_sha256": logical_parameters_sha256,
        "result_route_id": result_route_id,
    }


def _observation_route_landing_payload(
    *,
    observation_sha256: str,
    logical_receipt_sha256: str,
    route_ordinal: int,
    route_id: str,
    staging_key: str,
    route_authority_kind: RouteAuthorityKind,
    route_authority_sha256: str,
    landing_semantic: RouteLandingSemantic,
    conditional_lossless: bool,
    alias_target_route_id: str | None,
    live_snapshot_at: datetime | None,
    source_occurrence_count: int,
    source_occurrences_sha256: str,
    committed_receipt_schema_version: int,
    committed_receipt_kind: str,
    chunk_id: str,
    canonical_frame_format: str,
    frame_content_hash_contract: str,
    frame_schema_hash_contract: str,
    content_hash: str,
    persisted_row_count: int,
    persisted_content_sha256: str,
    persisted_schema_sha256: str,
    logical_call_receipt_sha256: str,
    provider_authority_sha256: str,
    logical_parameters_sha256: str,
    result_route_id: str,
    receipt_root_sha256: str,
) -> dict[str, object]:
    return {
        "schema_version": RAW_REQUEST_AUTHORITY_SCHEMA_VERSION,
        "observation_sha256": observation_sha256,
        "logical_receipt_sha256": logical_receipt_sha256,
        "route_ordinal": route_ordinal,
        "route_id": route_id,
        "staging_key": staging_key,
        "route_authority_kind": route_authority_kind,
        "route_authority_sha256": route_authority_sha256,
        "landing_semantic": landing_semantic,
        "conditional_lossless": conditional_lossless,
        "alias_target_route_id": alias_target_route_id,
        "live_snapshot_at": (
            None
            if live_snapshot_at is None
            else _canonical_timestamp(live_snapshot_at, field_name="live_snapshot_at")
        ),
        "source_occurrence_count": source_occurrence_count,
        "source_occurrences_sha256": source_occurrences_sha256,
        "committed_receipt_schema_version": committed_receipt_schema_version,
        "committed_receipt_kind": committed_receipt_kind,
        "chunk_id": chunk_id,
        "canonical_frame_format": canonical_frame_format,
        "frame_content_hash_contract": frame_content_hash_contract,
        "frame_schema_hash_contract": frame_schema_hash_contract,
        "content_hash": content_hash,
        "persisted_row_count": persisted_row_count,
        "persisted_content_sha256": persisted_content_sha256,
        "persisted_schema_sha256": persisted_schema_sha256,
        "logical_call_receipt_sha256": logical_call_receipt_sha256,
        "provider_authority_sha256": provider_authority_sha256,
        "logical_parameters_sha256": logical_parameters_sha256,
        "result_route_id": result_route_id,
        "receipt_root_sha256": receipt_root_sha256,
    }


class ObservationRouteLandingV2(_StrictFrozenModel):
    """One normalized response-level landing for one selected observation route."""

    schema_version: SchemaVersion
    landing_sha256: Sha256
    observation_sha256: Sha256
    logical_receipt_sha256: Sha256
    route_ordinal: NonNegativeInt
    route_id: SafeId
    staging_key: SafeId
    route_authority_kind: RouteAuthorityKind
    route_authority_sha256: Sha256
    landing_semantic: RouteLandingSemantic
    conditional_lossless: bool
    alias_target_route_id: SafeId | None
    live_snapshot_at: datetime | None
    source_occurrence_count: NonNegativeInt
    source_occurrences_sha256: Sha256
    committed_receipt_schema_version: Annotated[int, Field(strict=True, eq=2)]
    committed_receipt_kind: Literal["committed_staging_chunk_receipt_v2"]
    chunk_id: Annotated[str, StringConstraints(min_length=1, max_length=512)]
    canonical_frame_format: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    frame_content_hash_contract: Annotated[
        str,
        StringConstraints(min_length=1, max_length=200),
    ]
    frame_schema_hash_contract: Annotated[
        str,
        StringConstraints(min_length=1, max_length=200),
    ]
    content_hash: Sha256
    persisted_row_count: NonNegativeInt
    persisted_content_sha256: Sha256
    persisted_schema_sha256: Sha256
    logical_call_receipt_sha256: Sha256
    provider_authority_sha256: Sha256
    logical_parameters_sha256: Sha256
    result_route_id: SafeId
    receipt_root_sha256: Sha256

    @model_validator(mode="after")
    def _validate_route_landing(self) -> Self:
        from nbadb.orchestrate.staging_batches import CommittedStagingChunkReceiptV2

        if type(self.conditional_lossless) is not bool:
            raise ValueError("route landing conditional-lossless flag must be exact")
        if self.live_snapshot_at is not None:
            try:
                _canonical_timestamp(self.live_snapshot_at, field_name="live_snapshot_at")
            except RawRequestAuthorityError as exc:
                raise ValueError("route landing live snapshot time is invalid") from exc
        public_ids = (
            self.route_id,
            self.staging_key,
            self.alias_target_route_id,
            self.result_route_id,
        )
        if any(value is not None and _FORBIDDEN_IDENTITY_RE.search(value) for value in public_ids):
            raise ValueError("route landing contains a prohibited public identifier")
        receipt_payload = _committed_staging_identity_payload(
            committed_receipt_schema_version=self.committed_receipt_schema_version,
            committed_receipt_kind=self.committed_receipt_kind,
            chunk_id=self.chunk_id,
            staging_key=self.staging_key,
            canonical_frame_format=self.canonical_frame_format,
            frame_content_hash_contract=self.frame_content_hash_contract,
            frame_schema_hash_contract=self.frame_schema_hash_contract,
            content_hash=self.content_hash,
            persisted_row_count=self.persisted_row_count,
            persisted_content_sha256=self.persisted_content_sha256,
            persisted_schema_sha256=self.persisted_schema_sha256,
            logical_call_receipt_sha256=self.logical_call_receipt_sha256,
            provider_authority_sha256=self.provider_authority_sha256,
            logical_parameters_sha256=self.logical_parameters_sha256,
            result_route_id=self.result_route_id,
        )
        try:
            rebuilt_receipt = CommittedStagingChunkReceiptV2(
                chunk_id=self.chunk_id,
                staging_key=self.staging_key,
                canonical_frame_format=self.canonical_frame_format,
                frame_content_hash_contract=self.frame_content_hash_contract,
                frame_schema_hash_contract=self.frame_schema_hash_contract,
                content_hash=self.content_hash,
                persisted_row_count=self.persisted_row_count,
                persisted_content_sha256=self.persisted_content_sha256,
                persisted_schema_sha256=self.persisted_schema_sha256,
                logical_call_receipt_sha256=self.logical_call_receipt_sha256,
                provider_authority_sha256=self.provider_authority_sha256,
                logical_parameters_sha256=self.logical_parameters_sha256,
                result_route_id=self.result_route_id,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("route landing committed receipt is invalid") from exc
        if (
            rebuilt_receipt.identity_payload() != receipt_payload
            or self.receipt_root_sha256 != _sha256_json(receipt_payload)
        ):
            raise ValueError("route landing committed receipt root is invalid")
        if (
            self.route_id != self.result_route_id
            or self.logical_receipt_sha256 != self.logical_call_receipt_sha256
        ):
            raise ValueError("route landing receipt binding is invalid")
        if self.landing_semantic == "occurrence_bound":
            if (
                self.conditional_lossless
                or self.alias_target_route_id is not None
                or self.source_occurrence_count < 1
            ):
                raise ValueError("occurrence-bound landing denominator is invalid")
        elif self.landing_semantic == "conditional_lossless":
            if (
                not self.conditional_lossless
                or self.route_authority_kind != "conditional_staging_route_admission_v1"
                or self.alias_target_route_id is not None
                or self.persisted_row_count < 1
            ):
                raise ValueError("conditional lossless landing is invalid")
        elif self.landing_semantic == "response_fixed_zero":
            if (
                self.conditional_lossless
                or self.alias_target_route_id is not None
                or self.source_occurrence_count != 0
                or self.source_occurrences_sha256 != BODYLESS_RESULT_OCCURRENCES_SHA256
                or self.persisted_row_count != 0
            ):
                raise ValueError("response fixed-zero landing is invalid")
        else:
            if (
                self.conditional_lossless
                or self.alias_target_route_id is None
                or self.alias_target_route_id == self.route_id
                or self.source_occurrence_count != 0
                or self.source_occurrences_sha256 != BODYLESS_RESULT_OCCURRENCES_SHA256
            ):
                raise ValueError("response canonical-alias landing is invalid")
        if self.conditional_lossless != (
            self.route_authority_kind == "conditional_staging_route_admission_v1"
        ):
            raise ValueError("route landing authority kind differs from conditional policy")
        payload = _observation_route_landing_payload(
            observation_sha256=self.observation_sha256,
            logical_receipt_sha256=self.logical_receipt_sha256,
            route_ordinal=self.route_ordinal,
            route_id=self.route_id,
            staging_key=self.staging_key,
            route_authority_kind=self.route_authority_kind,
            route_authority_sha256=self.route_authority_sha256,
            landing_semantic=self.landing_semantic,
            conditional_lossless=self.conditional_lossless,
            alias_target_route_id=self.alias_target_route_id,
            live_snapshot_at=self.live_snapshot_at,
            source_occurrence_count=self.source_occurrence_count,
            source_occurrences_sha256=self.source_occurrences_sha256,
            committed_receipt_schema_version=self.committed_receipt_schema_version,
            committed_receipt_kind=self.committed_receipt_kind,
            chunk_id=self.chunk_id,
            canonical_frame_format=self.canonical_frame_format,
            frame_content_hash_contract=self.frame_content_hash_contract,
            frame_schema_hash_contract=self.frame_schema_hash_contract,
            content_hash=self.content_hash,
            persisted_row_count=self.persisted_row_count,
            persisted_content_sha256=self.persisted_content_sha256,
            persisted_schema_sha256=self.persisted_schema_sha256,
            logical_call_receipt_sha256=self.logical_call_receipt_sha256,
            provider_authority_sha256=self.provider_authority_sha256,
            logical_parameters_sha256=self.logical_parameters_sha256,
            result_route_id=self.result_route_id,
            receipt_root_sha256=self.receipt_root_sha256,
        )
        if self.landing_sha256 != _sha256_json(payload):
            raise ValueError("observation route landing digest is invalid")
        return self

    @classmethod
    def build(
        cls,
        *,
        observation_sha256: str,
        logical_receipt_sha256: str,
        route_ordinal: int,
        route_authority_kind: RouteAuthorityKind,
        route_authority_sha256: str,
        landing_semantic: RouteLandingSemantic,
        conditional_lossless: bool,
        alias_target_route_id: str | None,
        live_snapshot_at: datetime | None,
        source_occurrence_sha256s: Sequence[str],
        committed_receipt: object,
    ) -> Self:
        from nbadb.orchestrate.staging_batches import CommittedStagingChunkReceiptV2

        if type(committed_receipt) is not CommittedStagingChunkReceiptV2:
            raise RawRequestAuthorityError(
                "route landing requires the exact committed staging receipt type"
            )
        receipt = committed_receipt
        receipt_payload = receipt.identity_payload()
        expected_receipt_keys = {
            "schema_version",
            "kind",
            "chunk_id",
            "staging_key",
            "canonical_frame_format",
            "frame_content_hash_contract",
            "frame_schema_hash_contract",
            "content_hash",
            "persisted_row_count",
            "persisted_content_sha256",
            "persisted_schema_sha256",
            "logical_call_receipt_sha256",
            "provider_authority_sha256",
            "logical_parameters_sha256",
            "result_route_id",
        }
        if set(receipt_payload) != expected_receipt_keys:
            raise RawRequestAuthorityError("committed staging receipt identity is not exact")
        source_ids = list(source_occurrence_sha256s)
        if len(source_ids) > MAX_AUTHORITY_ROWS or any(
            type(item) is not str or _SHA256_RE.fullmatch(item) is None for item in source_ids
        ):
            raise RawRequestAuthorityError("route landing source occurrence inventory is invalid")
        payload = _observation_route_landing_payload(
            observation_sha256=observation_sha256,
            logical_receipt_sha256=logical_receipt_sha256,
            route_ordinal=route_ordinal,
            route_id=receipt.result_route_id,
            staging_key=receipt.staging_key,
            route_authority_kind=route_authority_kind,
            route_authority_sha256=route_authority_sha256,
            landing_semantic=landing_semantic,
            conditional_lossless=conditional_lossless,
            alias_target_route_id=alias_target_route_id,
            live_snapshot_at=live_snapshot_at,
            source_occurrence_count=len(source_ids),
            source_occurrences_sha256=_sha256_json(
                source_ids,
                maximum_bytes=MAX_RESULT_JSON_BYTES,
            ),
            committed_receipt_schema_version=cast("int", receipt_payload["schema_version"]),
            committed_receipt_kind=cast("str", receipt_payload["kind"]),
            chunk_id=receipt.chunk_id,
            canonical_frame_format=receipt.canonical_frame_format,
            frame_content_hash_contract=receipt.frame_content_hash_contract,
            frame_schema_hash_contract=receipt.frame_schema_hash_contract,
            content_hash=receipt.content_hash,
            persisted_row_count=receipt.persisted_row_count,
            persisted_content_sha256=receipt.persisted_content_sha256,
            persisted_schema_sha256=receipt.persisted_schema_sha256,
            logical_call_receipt_sha256=receipt.logical_call_receipt_sha256,
            provider_authority_sha256=receipt.provider_authority_sha256,
            logical_parameters_sha256=receipt.logical_parameters_sha256,
            result_route_id=receipt.result_route_id,
            receipt_root_sha256=_sha256_json(receipt_payload),
        )
        validation_payload = dict(payload)
        validation_payload["live_snapshot_at"] = live_snapshot_at
        return cls.model_validate(
            {"landing_sha256": _sha256_json(payload), **validation_payload},
            strict=True,
        )

    def to_row(self) -> dict[str, object]:
        return dict(self.model_dump(mode="python", round_trip=True))

    def to_canonical_bytes(self) -> bytes:
        payload = self.to_row()
        payload["live_snapshot_at"] = (
            None
            if self.live_snapshot_at is None
            else _canonical_timestamp(self.live_snapshot_at, field_name="live_snapshot_at")
        )
        return canonical_json_bytes(payload)

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> Self:
        payload = _decode_canonical_json_object(
            encoded,
            maximum_bytes=MAX_CANONICAL_JSON_BYTES,
        )
        timestamp = payload.get("live_snapshot_at")
        if timestamp is not None:
            if type(timestamp) is not str or not timestamp.endswith("Z"):
                raise RawRequestAuthorityError("route landing live snapshot time is invalid")
            try:
                parsed = datetime.fromisoformat(timestamp.removesuffix("Z") + "+00:00")
            except ValueError as exc:
                raise RawRequestAuthorityError(
                    "route landing live snapshot time is invalid"
                ) from exc
            if _canonical_timestamp(parsed, field_name="live_snapshot_at") != timestamp:
                raise RawRequestAuthorityError("route landing live snapshot time is noncanonical")
            payload["live_snapshot_at"] = parsed
        return cast(
            "Self",
            validate_observation_route_landing(payload),
        )


def _bundle_identity_payload(
    *,
    objects: Sequence[ParserInputObjectV2],
    observations: Sequence[RequestObservationV2],
    occurrences: Sequence[ResultOccurrenceV2],
    landings: Sequence[ObservationRouteLandingV2],
) -> dict[str, object]:
    return {
        "schema_version": RAW_REQUEST_AUTHORITY_SCHEMA_VERSION,
        "object_sha256s": sorted(item.object_sha256 for item in objects),
        "observation_record_sha256s": sorted(
            item.observation_record_sha256 for item in observations
        ),
        "occurrence_sha256s": sorted(item.occurrence_sha256 for item in occurrences),
        "landing_sha256s": sorted(item.landing_sha256 for item in landings),
    }


def _unknown_video_response_authority(
    *,
    observation: RequestObservationV2,
    body_object: ParserInputObjectV2,
) -> tuple[Any, Any | None]:
    """Reparse one exact Video body and rebuild its conditional frame, if any."""

    from nbadb.core.errors import ResponseContractError
    from nbadb.extract.nba_api_adapter import (
        rederive_raw_authority_unknown_stats_response,
    )
    from nbadb.extract.stats_lossless import build_unknown_stats_lossless_fallback

    capture_receipt = observation.capture_response_receipt_sha256
    if capture_receipt is None:
        raise ValueError("unknown Video observation lacks its capture receipt")
    try:
        unknown = rederive_raw_authority_unknown_stats_response(
            endpoint_id=observation.attempt.endpoint_id,
            parser_input=decode_parser_input_object(body_object),
            safe_parameters_json=observation.attempt.safe_parameters_json,
            provider_authority_sha256=observation.attempt.provider_authority_sha256,
            endpoint_contract_sha256_value=observation.attempt.endpoint_contract_sha256,
        )
        fallback = build_unknown_stats_lossless_fallback(
            unknown.bind_response_receipt(capture_receipt),
            expected_response_receipt_sha256=capture_receipt,
            expected_parameters_sha256=unknown.parameters_sha256,
            expected_parser_input_sha256=unknown.parser_input_sha256,
        )
    except (AttributeError, ResponseContractError, TypeError, ValueError) as exc:
        raise ValueError(
            "unknown Video response cannot be rederived from exact parser-input bytes"
        ) from exc
    return unknown, None if fallback is None else fallback.frame


def _require_exact_landing_frame(
    landing: ObservationRouteLandingV2,
    frame: Any,
    *,
    label: str,
) -> None:
    """Compare one public landing receipt with an independently rebuilt frame."""

    from nbadb.core.errors import ParserInputCaptureIntegrityError
    from nbadb.orchestrate.staging_batches import frame_content_hash, frame_schema_hash

    try:
        content_sha256 = frame_content_hash(frame)
        schema_sha256 = frame_schema_hash(frame)
        row_count = frame.height
    except (AttributeError, ParserInputCaptureIntegrityError, TypeError, ValueError) as exc:
        raise ValueError(f"{label} frame cannot be canonicalized") from exc
    if (
        landing.persisted_row_count != row_count
        or landing.content_hash != content_sha256
        or landing.persisted_content_sha256 != content_sha256
        or landing.persisted_schema_sha256 != schema_sha256
    ):
        raise ValueError(f"{label} receipt differs from exact parser-input reconstruction")


def _unknown_video_expected_occurrences(
    *,
    observation: RequestObservationV2,
    unknown: Any,
    conditional_landing: ObservationRouteLandingV2 | None,
) -> tuple[ResultOccurrenceV2, ...]:
    """Rebuild exact legacy occurrences without inventing a named result."""

    raw_occurrences = getattr(unknown, "occurrences", None)
    if type(raw_occurrences) is not tuple:
        raise ValueError("unknown Video response occurrence authority is invalid")
    occurrences = cast("tuple[Any, ...]", raw_occurrences)
    if occurrences and conditional_landing is None:
        raise ValueError("unknown Video named occurrences lack conditional lossless authority")
    duplicate_names: Counter[str] = Counter()
    expected: list[ResultOccurrenceV2] = []
    for occurrence_ordinal, item in enumerate(occurrences):
        receipt = item.receipt
        duplicate_name_ordinal = duplicate_names[item.name]
        duplicate_names[item.name] += 1
        route_ids: tuple[str, ...] = ()
        committed_receipts: list[dict[str, str]] = []
        if conditional_landing is not None:
            route_ids = (conditional_landing.route_id,)
            committed_receipts = [
                {
                    "route_id": conditional_landing.route_id,
                    "receipt_sha256": conditional_landing.receipt_root_sha256,
                }
            ]
        expected.append(
            ResultOccurrenceV2.build(
                observation_sha256=observation.attempt.observation_sha256,
                occurrence_ordinal=occurrence_ordinal,
                result_name=item.name,
                duplicate_name_ordinal=duplicate_name_ordinal,
                provider_result_ordinal=item.provider_index,
                canonical_result_ordinal=None,
                json_path=None,
                container_kind="nba_api_result_set",
                presence="present" if receipt.row_count > 0 else "present_empty",
                ordered_headers=item.headers,
                row_count=receipt.row_count,
                cell_count=receipt.row_count * len(item.headers),
                node_count=0,
                container_count=1,
                missing_count=0,
                null_count=0,
                parent_state_sha256=receipt.parent_occurrence_states_sha256,
                output_sha256=receipt.normalized_output_sha256,
                canonical_route_ids=route_ids,
                committed_staging_receipts=committed_receipts,
                landing_disposition="lossless_only",
            )
        )
    return tuple(expected)


def _rederived_presence_and_counts(
    derivation: Any,
) -> tuple[ResultPresence, tuple[str, ...], int, int, int, int, int, int]:
    """Project one adapter receipt into the exact public occurrence algebra."""

    receipt = derivation.result_set
    ordered_headers = derivation.ordered_headers
    if type(ordered_headers) is not tuple or any(type(item) is not str for item in ordered_headers):
        raise ValueError("rederived result headers are not an exact ordered tuple")
    present_containers = receipt.container_count
    missing_count = receipt.missing_count
    null_count = receipt.null_count
    if present_containers == 0:
        if receipt.parent_observation_count == 0:
            if (
                receipt.row_count
                or missing_count
                or null_count
                or receipt.json_path is None
                or receipt.container_kind
                not in {
                    "nba_api_live_json_array",
                    "nba_api_live_json_object",
                }
            ):
                raise ValueError("rederived zero-parent result state is invalid")
            return (
                "not_observed_parent_empty",
                ordered_headers,
                0,
                0,
                0,
                0,
                0,
                0,
            )
        if missing_count > 0 and null_count == 0:
            return "missing", (), 0, 0, 0, 0, missing_count, 0
        if null_count > 0 and missing_count == 0:
            return "null", (), 0, 0, null_count, null_count, 0, null_count
        if missing_count > 0 and null_count > 0:
            return (
                "mixed_absent",
                (),
                0,
                0,
                null_count,
                null_count,
                missing_count,
                null_count,
            )
        raise ValueError("rederived result has no exact absence state")

    row_count = receipt.row_count
    container_count = present_containers + null_count
    if row_count > 0:
        return (
            "present",
            ordered_headers,
            row_count,
            row_count * len(ordered_headers),
            0 if receipt.container_kind == "nba_api_result_set" else row_count,
            container_count,
            missing_count,
            null_count,
        )
    if receipt.container_kind == "nba_api_result_set":
        return (
            "present_empty",
            ordered_headers,
            0,
            0,
            0,
            container_count,
            missing_count,
            null_count,
        )
    if (
        receipt.container_kind in {"nba_api_live_json_array", "nba_api_static_records"}
        and present_containers == 1
        and missing_count == 0
        and null_count == 0
    ):
        return "empty_array", (), 0, 0, 1, 1, 0, 0
    return (
        "present",
        ordered_headers,
        0,
        0,
        present_containers,
        container_count,
        missing_count,
        null_count,
    )


def _rederive_ordinary_result_inventory(
    *,
    observation: RequestObservationV2,
    occurrences: Sequence[ResultOccurrenceV2],
    body_object: ParserInputObjectV2 | None,
) -> tuple[frozenset[int], tuple[Any, ...], bytes | None]:
    """Rebuild every ordinary terminal occurrence from exact public authority.

    The adapter import is deliberately function-local: it is a no-network pure
    replay dependency, while this contract remains importable during the V2
    producer migration.  The returned ordinals identify declared-stats fallback
    results whose wide membership must remain denominator evidence even when the
    committed wide frame contains zero rows.
    """

    from nbadb.extract.nba_api_adapter import rederive_raw_authority_result_sets

    parser_input: bytes | None
    if observation.attempt.source_family == "static":
        if body_object is not None or observation.body_disposition != "declared_bodyless":
            raise ValueError("ordinary static replay requires exact bodyless authority")
        parser_input = None
    else:
        if body_object is None or observation.body_disposition != "public_parser_input":
            raise ValueError("ordinary response replay requires exact parser-input authority")
        validated_body = validate_parser_input_object(body_object)
        if validated_body.object_sha256 != observation.body_object_sha256:
            raise ValueError("ordinary response body differs from observation authority")
        parser_input = decode_parser_input_object(validated_body)

    try:
        raw_derivations = rederive_raw_authority_result_sets(
            source_family=observation.attempt.source_family,
            endpoint_id=observation.attempt.endpoint_id,
            parser_input=parser_input,
            provider_authority_sha256=observation.attempt.provider_authority_sha256,
            endpoint_contract_sha256_value=observation.attempt.endpoint_contract_sha256,
        )
    except Exception as exc:  # noqa: BLE001 - any replay failure invalidates authority
        raise ValueError("ordinary result inventory cannot be rederived exactly") from exc
    if type(raw_derivations) is not tuple or len(raw_derivations) != len(occurrences):
        raise ValueError("ordinary result inventory cardinality differs from exact rederivation")

    fallback_ordinals: set[int] = set()
    for occurrence_ordinal, (occurrence, derivation) in enumerate(
        zip(occurrences, raw_derivations, strict=True)
    ):
        receipt = derivation.result_set
        (
            presence,
            ordered_headers,
            row_count,
            cell_count,
            node_count,
            container_count,
            missing_count,
            null_count,
        ) = _rederived_presence_and_counts(derivation)
        json_path = "$" if observation.attempt.source_family == "static" else receipt.json_path
        expected = (
            occurrence_ordinal,
            receipt.name,
            derivation.duplicate_name_ordinal,
            receipt.provider_index,
            receipt.canonical_index,
            json_path,
            receipt.container_kind,
            presence,
            ordered_headers,
            len(ordered_headers),
            row_count,
            cell_count,
            node_count,
            container_count,
            missing_count,
            null_count,
            receipt.parent_occurrence_states_sha256,
            receipt.normalized_output_sha256,
        )
        actual = (
            occurrence.occurrence_ordinal,
            occurrence.result_name,
            occurrence.duplicate_name_ordinal,
            occurrence.provider_result_ordinal,
            occurrence.canonical_result_ordinal,
            occurrence.json_path,
            occurrence.container_kind,
            occurrence.presence,
            occurrence.ordered_headers(),
            occurrence.header_count,
            occurrence.row_count,
            occurrence.cell_count,
            occurrence.node_count,
            occurrence.container_count,
            occurrence.missing_count,
            occurrence.null_count,
            occurrence.parent_state_sha256,
            occurrence.output_sha256,
        )
        if actual != expected:
            raise ValueError("ordinary result occurrence differs from exact rederivation")
        if receipt.canonical_index is None:
            fallback_ordinals.add(occurrence_ordinal)
    return frozenset(fallback_ordinals), raw_derivations, parser_input


_STATS_SEASON_SCOPE_KEYS = ("season", "season_nullable", "season_year")
_STATS_SEASON_TYPE_SCOPE_KEYS = (
    "season_type_all_star",
    "season_type_playoffs",
    "season_type",
    "season_type_nullable",
    "season_type_all_star_nullable",
)
_STATS_LEAGUE_SCOPE_KEYS = ("league_id", "league_id_nullable")


def _first_stats_scope_value(
    parameters: Mapping[str, object],
    keys: Sequence[str],
) -> object | None:
    for key in keys:
        value = parameters.get(key)
        if value is not None and value != "":
            return value
    return None


def _rebuild_stats_wide_frame(
    *,
    route: Any,
    result_rows: Any,
    safe_parameters_json: str,
) -> Any:
    """Rebuild the exact stats extractor frame without trusting receipt hashes."""

    import polars as pl

    from nbadb.extract.nba_api_adapter import rows_to_polars
    from nbadb.schemas.registry import get_input_schema

    if (
        result_rows.ordered_headers != route.provider_columns
        or tuple(mapping.provider_column for mapping in route.column_mappings)
        != result_rows.ordered_headers
        or any(mapping.transform not in {"identity", "rename"} for mapping in route.column_mappings)
    ):
        raise ValueError("stats route provider-column projection is not exact")
    canonical_columns = tuple(mapping.canonical_column for mapping in route.column_mappings)
    if len(set(canonical_columns)) != len(canonical_columns):
        raise ValueError("stats route canonical columns are ambiguous")
    try:
        values = tuple(
            tuple(json.loads(cell.canonical_json) for cell in row) for row in result_rows.rows
        )
        frame = rows_to_polars(result_rows.ordered_headers, values)
        frame = frame.rename(dict(zip(result_rows.ordered_headers, canonical_columns, strict=True)))
        parameters = json.loads(safe_parameters_json)
    except Exception as exc:  # noqa: BLE001 - exact reconstruction must fail closed
        raise ValueError("stats route frame cannot be reconstructed exactly") from exc
    schema_cls = get_input_schema(route.staging_key)
    if schema_cls is None:
        raise ValueError("stats route frame lacks its exact staging schema")
    try:
        schema = schema_cls.to_schema()
        schema_columns = tuple(schema.columns)
        if schema_columns != route.storage_columns:
            raise ValueError("staging schema columns differ from route authority")
        if any(column not in route.storage_columns for column in frame.columns):
            raise ValueError("provider projection contains a non-storage column")
        # A reviewed staging schema may retain nullable compatibility fields
        # that are absent from the pinned provider result.  They are not
        # provider evidence: reconstruct them as typed nulls so any persisted
        # non-null value still fails the exact parser-input comparison.
        frame = frame.select(
            [
                (
                    pl.col(column)
                    if column in frame.columns
                    else pl.lit(None).cast(schema.columns[column].dtype.type)
                ).alias(column)
                for column in route.storage_columns
            ]
        )
        frame = schema_cls.validate(frame)
    except Exception as exc:  # noqa: BLE001 - schema replay must fail closed
        raise ValueError("stats route frame differs from its exact storage schema") from exc
    if type(parameters) is not dict or any(type(key) is not str for key in parameters):
        raise ValueError("stats route safe parameters are not an exact object")
    typed_parameters = cast("dict[str, object]", parameters)
    additions: list[Any] = []
    for column_name, value in (
        (
            "season_year",
            _first_stats_scope_value(typed_parameters, _STATS_SEASON_SCOPE_KEYS),
        ),
        (
            "season_type",
            _first_stats_scope_value(typed_parameters, _STATS_SEASON_TYPE_SCOPE_KEYS),
        ),
        (
            "league_id",
            _first_stats_scope_value(typed_parameters, _STATS_LEAGUE_SCOPE_KEYS),
        ),
    ):
        if value is not None and column_name not in frame.columns:
            additions.append(pl.lit(value).alias(column_name))
    return frame.with_columns(additions) if additions else frame


def _validate_stats_landing_frames_and_membership(
    *,
    observation: RequestObservationV2,
    occurrences: Sequence[ResultOccurrenceV2],
    derivations: Sequence[Any],
    parser_input: bytes,
    fallback_ordinals: frozenset[int],
    ordered_fixed_routes: Sequence[Any],
    fixed_landings: Sequence[ObservationRouteLandingV2],
    conditional_landing: ObservationRouteLandingV2 | None,
) -> None:
    """Rebuild exact stats route membership and every reconstructable frame."""

    import polars as pl

    from nbadb.core.nba_api_runtime_contract import pinned_runtime_contracts
    from nbadb.extract.nba_api_adapter import (
        rederive_raw_authority_stats_fallback,
        rederive_raw_authority_stats_rows,
        rederive_raw_authority_stats_wide_rows,
    )

    contract = pinned_runtime_contracts().get(observation.attempt.endpoint_id)
    if contract is None or contract.response_mode == "unknown_dynamic_response":
        raise ValueError("ordinary stats landing lacks its exact pinned contract")
    fallback = bool(fallback_ordinals)
    try:
        safe_rows = (
            rederive_raw_authority_stats_wide_rows(
                endpoint_id=observation.attempt.endpoint_id,
                parser_input=parser_input,
                provider_authority_sha256=observation.attempt.provider_authority_sha256,
                endpoint_contract_sha256_value=observation.attempt.endpoint_contract_sha256,
            )
            if fallback
            else rederive_raw_authority_stats_rows(
                endpoint_id=observation.attempt.endpoint_id,
                parser_input=parser_input,
                provider_authority_sha256=observation.attempt.provider_authority_sha256,
                endpoint_contract_sha256_value=observation.attempt.endpoint_contract_sha256,
            )
        )
    except Exception as exc:  # noqa: BLE001 - any parser replay failure invalidates authority
        raise ValueError("stats wide route rows cannot be rederived exactly") from exc

    declared_by_result: dict[int, list[str]] = {index: [] for index in range(len(derivations))}
    wide_by_result: dict[int, list[str]] = {index: [] for index in range(len(derivations))}
    fixed_landing_by_route = {landing.route_id: landing for landing in fixed_landings}
    if len(fixed_landing_by_route) != len(fixed_landings):
        raise ValueError("stats fixed landing inventory is duplicated")

    for route in ordered_fixed_routes:
        identity_indexes: list[int] = []
        for result_index, derivation in enumerate(derivations):
            receipt = derivation.result_set
            if route.provider_result_set_name != receipt.name:
                continue
            if receipt.canonical_index is not None:
                matches = route.canonical_result_set_ordinal == receipt.canonical_index
            elif route.canonical_result_set_ordinal < len(contract.result_sets):
                expected = contract.result_sets[route.canonical_result_set_ordinal]
                duplicate_ordinal = sum(
                    prior.result_set_name == expected.result_set_name
                    for prior in contract.result_sets[: route.canonical_result_set_ordinal]
                )
                matches = (
                    expected.result_set_name == receipt.name
                    and derivation.duplicate_name_ordinal == duplicate_ordinal
                )
            else:
                matches = False
            if matches:
                identity_indexes.append(result_index)
        if len(identity_indexes) != 1:
            raise ValueError("stats fixed route lacks one exact result occurrence")
        declared_index = identity_indexes[0]
        declared_by_result[declared_index].append(route.route_id)

        candidates = tuple(
            item
            for item in safe_rows
            if item.result_set.name == route.provider_result_set_name
            and item.result_set.canonical_index == route.canonical_result_set_ordinal
            and item.ordered_headers == route.provider_columns
        )
        if not candidates:
            if safe_rows:
                raise ValueError("stats safe-wide authority omits a pinned staging route")
            expected_frame = pl.DataFrame()
        else:
            if len(candidates) != 1:
                raise ValueError("stats safe-wide route membership is ambiguous")
            candidate = candidates[0]
            matching_indexes = tuple(
                index
                for index, derivation in enumerate(derivations)
                if derivation.result_set.name == candidate.result_set.name
                and derivation.result_set.provider_index == candidate.result_set.provider_index
                and derivation.ordered_headers == candidate.ordered_headers
                and derivation.result_set.row_count == candidate.result_set.row_count
            )
            if matching_indexes != (declared_index,):
                raise ValueError("stats safe-wide packet differs from its declared occurrence")
            wide_by_result[declared_index].append(route.route_id)
            expected_frame = _rebuild_stats_wide_frame(
                route=route,
                result_rows=candidate,
                safe_parameters_json=observation.attempt.safe_parameters_json,
            )
        fixed_landing = fixed_landing_by_route.get(route.route_id)
        if fixed_landing is None:
            raise ValueError("stats fixed route lacks its response-level landing")
        _require_exact_landing_frame(
            fixed_landing,
            expected_frame,
            label="stats fixed route landing",
        )

    conditional_route_id: str | None = None
    if fallback:
        if conditional_landing is None:
            raise ValueError("stats fallback lacks its conditional lossless landing")
        capture_receipt = observation.capture_response_receipt_sha256
        if capture_receipt is None:
            raise ValueError("stats fallback lacks its capture receipt")
        try:
            fallback_frame = (
                rederive_raw_authority_stats_fallback(
                    endpoint_id=observation.attempt.endpoint_id,
                    parser_input=parser_input,
                    provider_authority_sha256=observation.attempt.provider_authority_sha256,
                    endpoint_contract_sha256_value=observation.attempt.endpoint_contract_sha256,
                )
                .bind_response_receipt(capture_receipt)
                .frame
            )
        except Exception as exc:  # noqa: BLE001 - exact fallback replay must fail closed
            raise ValueError("stats conditional frame cannot be rederived exactly") from exc
        _require_exact_landing_frame(
            conditional_landing,
            fallback_frame,
            label="stats conditional lossless landing",
        )
        conditional_route_id = conditional_landing.route_id
    elif conditional_landing is not None:
        raise ValueError("strict stats response fabricated a conditional lossless landing")

    for result_index, occurrence in enumerate(occurrences):
        expected_routes = tuple(
            sorted(
                (
                    *declared_by_result[result_index],
                    *((conditional_route_id,) if conditional_route_id is not None else ()),
                )
            )
        )
        expected_disposition: LandingDisposition = (
            "wide_plus_lossless"
            if conditional_route_id is not None and wide_by_result[result_index]
            else "lossless_only"
            if conditional_route_id is not None
            else "wide_only"
        )
        if (
            occurrence.canonical_route_ids() != expected_routes
            or tuple(occurrence.committed_staging_receipts_by_route()) != expected_routes
            or occurrence.landing_disposition != expected_disposition
        ):
            raise ValueError("stats occurrence route membership differs from exact rederivation")


def validate_logical_provider_parameter_join(
    observation: object,
    *,
    logical_endpoint_name: object,
    logical_parameters_sha256: object,
    result_route_ids: object,
) -> RequestObservationV2:
    """Replay one persisted logical/provider join without an external pin.

    Direct equality remains the canonical no-receipt path.  When the provider
    wrapper's safe semantic parameter identity intentionally differs, the
    observation must carry the exact pre-provider receipt bytes and digest.
    """

    if type(observation) is not RequestObservationV2:
        raise RawRequestAuthorityError(
            "logical/provider join requires one exact request observation"
        )
    parsed = validate_request_observation(observation)
    if (
        type(logical_endpoint_name) is not str
        or _SAFE_ID_RE.fullmatch(logical_endpoint_name) is None
        or type(logical_parameters_sha256) is not str
        or _SHA256_RE.fullmatch(logical_parameters_sha256) is None
        or type(result_route_ids) is not tuple
        or not result_route_ids
        or result_route_ids != tuple(sorted(result_route_ids))
        or len(result_route_ids) != len(set(result_route_ids))
        or any(
            type(route_id) is not str or _SAFE_ID_RE.fullmatch(route_id) is None
            for route_id in result_route_ids
        )
    ):
        raise RawRequestAuthorityError("logical/provider join received malformed logical authority")
    binding_sha256 = parsed.logical_provider_parameter_binding_sha256
    binding_json = parsed.logical_provider_parameter_binding_json
    if logical_parameters_sha256 == parsed.attempt.safe_parameters_sha256:
        if binding_sha256 is not None or binding_json is not None:
            raise RawRequestAuthorityError(
                "direct logical/provider parameter equality carries an alias binding"
            )
        return parsed
    if binding_sha256 is None or binding_json is None:
        raise RawRequestAuthorityError(
            "logical/provider parameter divergence lacks persisted alias authority"
        )
    try:
        from nbadb.contracts.logical_provider_parameter_binding import (
            LogicalProviderParameterBindingV1,
        )

        parameter_binding = LogicalProviderParameterBindingV1.from_canonical_bytes(
            binding_json.encode("utf-8", errors="strict")
        )
    except (AttributeError, TypeError, UnicodeEncodeError, ValueError) as exc:
        raise RawRequestAuthorityError(
            "persisted logical/provider parameter binding cannot be replayed"
        ) from exc
    if (
        parameter_binding.binding_sha256 != binding_sha256
        or parameter_binding.logical_endpoint_name != logical_endpoint_name
        or parameter_binding.logical_parameters_sha256 != logical_parameters_sha256
        or parameter_binding.result_route_ids != result_route_ids
    ):
        raise RawRequestAuthorityError(
            "persisted logical/provider parameter binding crosses logical authority"
        )
    matching_entries = tuple(
        entry
        for entry in parameter_binding.provider_entries
        if entry.provider_call_sha256 == parsed.attempt.provider_call_sha256
    )
    if len(matching_entries) != 1:
        raise RawRequestAuthorityError(
            "persisted logical/provider parameter binding is not bijective per call"
        )
    entry = matching_entries[0]
    attempt = parsed.attempt
    if (
        entry.request_ordinal != attempt.request_ordinal
        or entry.provider_call_ordinal != attempt.provider_call_ordinal
        or entry.provider_request_sha256 != attempt.provider_request_sha256
        or entry.safe_parameters_sha256 != attempt.safe_parameters_sha256
        or entry.source_family != attempt.source_family
        or entry.endpoint_id != attempt.endpoint_id
        or entry.endpoint_contract_sha256 != attempt.endpoint_contract_sha256
    ):
        raise RawRequestAuthorityError(
            "persisted logical/provider parameter binding crosses provider authority"
        )
    return parsed


def _validate_observation_route_landings(
    *,
    observation: RequestObservationV2,
    occurrences: Sequence[ResultOccurrenceV2],
    landings: Sequence[ObservationRouteLandingV2],
    body_object: ParserInputObjectV2 | None,
) -> None:
    """Close route registry, occurrence, and response-level policy joins."""

    import polars as pl

    from nbadb.contracts.staging_route_contract import (
        admit_conditional_lossless_route,
        admit_known_conditional_staging_route,
        staging_route_contract_bundle,
        validate_staging_route_contract_bundle,
    )
    from nbadb.core.nba_api_runtime_contract import pinned_runtime_contracts
    from nbadb.orchestrate.staging_map import LOSSLESS_FALLBACK_STAGING_KEY

    terminal_success = observation.outcome in {
        "success_nonempty",
        "success_empty",
        "static_snapshot_success",
    }
    if not terminal_success:
        if landings:
            raise ValueError("nonterminal observation carries a route landing")
        return
    logical_receipt_sha256 = observation.logical_receipt_sha256
    if logical_receipt_sha256 is None:
        raise ValueError("terminal observation lacks its logical receipt")

    route_bundle = staging_route_contract_bundle()
    try:
        validate_staging_route_contract_bundle(route_bundle)
    except ValueError as exc:
        raise ValueError("current staging route authority is invalid") from exc

    fixed_routes = []
    conditional_landings: list[ObservationRouteLandingV2] = []
    for landing in landings:
        if (
            landing.observation_sha256 != observation.attempt.observation_sha256
            or landing.logical_receipt_sha256 != logical_receipt_sha256
            or landing.logical_call_receipt_sha256 != logical_receipt_sha256
            or landing.provider_authority_sha256 != observation.attempt.provider_authority_sha256
        ):
            raise ValueError("route landing differs from its exact observation authority")
        if landing.route_authority_kind == "staging_route_contract_v1":
            route = route_bundle.by_route_id.get(landing.route_id)
            if route is None:
                raise ValueError("route landing references a foreign fixed route")
            if (
                landing.route_authority_sha256 != route.contract_sha256
                or landing.staging_key != route.staging_key
                or route.source_family != observation.attempt.source_family
                or route.provider_endpoint_id != observation.attempt.endpoint_id
                or route.provider_authority_sha256 != observation.attempt.provider_authority_sha256
                or route.endpoint_contract_sha256 != observation.attempt.endpoint_contract_sha256
            ):
                raise ValueError("fixed route landing differs from pinned route authority")
            fixed_routes.append(route)
        else:
            conditional_landings.append(landing)

    if not fixed_routes:
        raise ValueError("terminal observation lacks a fixed route landing")
    if len(conditional_landings) > 1:
        raise ValueError("observation carries multiple conditional route landings")
    endpoint_names = {route.endpoint_name for route in fixed_routes}
    if len(endpoint_names) != 1:
        raise ValueError("observation route landings span endpoint wrappers")
    ordered_fixed_routes = tuple(sorted(fixed_routes, key=lambda route: route.ordinal))
    if len({route.route_id for route in ordered_fixed_routes}) != len(ordered_fixed_routes):
        raise ValueError("observation route landing inventory duplicates a fixed route")
    actual_fixed_ids = tuple(
        landing.route_id
        for landing in landings
        if landing.route_authority_kind == "staging_route_contract_v1"
    )
    expected_fixed_ids = tuple(route.route_id for route in ordered_fixed_routes)
    if actual_fixed_ids != expected_fixed_ids:
        raise ValueError("fixed route landings are not in canonical route order")

    conditional_landing = conditional_landings[0] if conditional_landings else None
    conditional_admission = None
    if conditional_landing is not None:
        try:
            conditional_admission = admit_known_conditional_staging_route(
                endpoint_name=next(iter(endpoint_names)),
                static_route_ids=expected_fixed_ids,
                conditional_route_ids=(conditional_landing.route_id,),
                provider_authority_sha256=observation.attempt.provider_authority_sha256,
            )
        except ValueError as exc:
            raise ValueError("conditional route landing lacks exact admission") from exc
        if (
            conditional_landing.route_authority_sha256 != conditional_admission.contract_sha256
            or conditional_landing.staging_key != conditional_admission.staging_key
            or conditional_landing.route_id != conditional_admission.route_id
            or conditional_admission.endpoint_contract_sha256
            != observation.attempt.endpoint_contract_sha256
        ):
            raise ValueError("conditional route landing differs from exact admission")

    expected_route_order = expected_fixed_ids + (
        () if conditional_landing is None else (conditional_landing.route_id,)
    )
    if tuple(landing.route_id for landing in landings) != expected_route_order:
        raise ValueError("observation route landings are not in canonical route order")

    logical_parameter_digests = {landing.logical_parameters_sha256 for landing in landings}
    if len(logical_parameter_digests) != 1:
        raise ValueError("observation route landings span logical parameter identities")
    logical_parameters_sha256 = next(iter(logical_parameter_digests))
    binding_sha256 = observation.logical_provider_parameter_binding_sha256
    binding_json = observation.logical_provider_parameter_binding_json
    if logical_parameters_sha256 == observation.attempt.safe_parameters_sha256:
        if binding_sha256 is not None or binding_json is not None:
            raise ValueError("direct logical/provider parameter equality carries an alias binding")
    else:
        if binding_sha256 is None or binding_json is None:
            raise ValueError(
                "logical/provider parameter divergence lacks persisted alias authority"
            )
        try:
            from nbadb.contracts.logical_provider_parameter_binding import (
                LogicalProviderParameterBindingV1,
            )

            parameter_binding = LogicalProviderParameterBindingV1.from_canonical_bytes(
                binding_json.encode("utf-8", errors="strict")
            )
        except (AttributeError, TypeError, UnicodeEncodeError, ValueError) as exc:
            raise ValueError(
                "persisted logical/provider parameter binding cannot be replayed"
            ) from exc
        if (
            parameter_binding.binding_sha256 != binding_sha256
            or parameter_binding.logical_endpoint_name != next(iter(endpoint_names))
            or parameter_binding.logical_parameters_sha256 != logical_parameters_sha256
            or parameter_binding.result_route_ids != tuple(sorted(expected_route_order))
        ):
            raise ValueError(
                "persisted logical/provider parameter binding crosses logical authority"
            )
        matching_entries = tuple(
            entry
            for entry in parameter_binding.provider_entries
            if entry.provider_call_sha256 == observation.attempt.provider_call_sha256
        )
        if len(matching_entries) != 1:
            raise ValueError(
                "persisted logical/provider parameter binding is not bijective per call"
            )
        entry = matching_entries[0]
        attempt = observation.attempt
        if (
            entry.request_ordinal != attempt.request_ordinal
            or entry.provider_call_ordinal != attempt.provider_call_ordinal
            or entry.provider_request_sha256 != attempt.provider_request_sha256
            or entry.safe_parameters_sha256 != attempt.safe_parameters_sha256
            or entry.source_family != attempt.source_family
            or entry.endpoint_id != attempt.endpoint_id
            or entry.endpoint_contract_sha256 != attempt.endpoint_contract_sha256
        ):
            raise ValueError(
                "persisted logical/provider parameter binding crosses provider authority"
            )

    for landing in landings:
        source_rows = tuple(
            item for item in occurrences if landing.route_id in item.canonical_route_ids()
        )
        source_ids = [item.occurrence_sha256 for item in source_rows]
        if landing.source_occurrence_count != len(
            source_ids
        ) or landing.source_occurrences_sha256 != _sha256_json(
            source_ids, maximum_bytes=MAX_RESULT_JSON_BYTES
        ):
            raise ValueError("route landing source occurrence denominator is invalid")
        for item in source_rows:
            receipt_root = item.committed_staging_receipts_by_route().get(landing.route_id)
            if receipt_root != landing.receipt_root_sha256:
                raise ValueError("route landing source occurrence receipt root differs")
        if landing.landing_semantic == "occurrence_bound":
            if landing.route_authority_kind != "staging_route_contract_v1":
                raise ValueError("occurrence-bound landing is not a fixed route")
            persisted_source_rows = sum(
                item.row_count
                for item in source_rows
                if item.landing_disposition in {"wide_only", "wide_plus_lossless"}
            )
            if landing.persisted_row_count != persisted_source_rows:
                raise ValueError("occurrence-bound landing row count differs from sources")
        elif landing.landing_semantic == "conditional_lossless":
            if landing.route_authority_kind != "conditional_staging_route_admission_v1":
                raise ValueError("conditional landing lacks conditional route authority")
        elif source_rows:
            raise ValueError("response-level landing fabricated occurrence sources")

    is_unknown_video = _is_exact_unknown_dynamic_video_attempt(observation.attempt)
    if not is_unknown_video:
        fallback_ordinals, derivations, parser_input = _rederive_ordinary_result_inventory(
            observation=observation,
            occurrences=occurrences,
            body_object=body_object,
        )
        if observation.attempt.source_family == "stats":
            if parser_input is None:
                raise ValueError("ordinary stats replay omitted its parser-input bytes")
            _validate_stats_landing_frames_and_membership(
                observation=observation,
                occurrences=occurrences,
                derivations=derivations,
                parser_input=parser_input,
                fallback_ordinals=fallback_ordinals,
                ordered_fixed_routes=ordered_fixed_routes,
                fixed_landings=tuple(
                    landing
                    for landing in landings
                    if landing.route_authority_kind == "staging_route_contract_v1"
                ),
                conditional_landing=conditional_landing,
            )
        if any(
            landing.landing_semantic not in {"occurrence_bound", "conditional_lossless"}
            for landing in landings
        ):
            raise ValueError("response-level landing is outside exact Video authority")
        occurrence_route_ids = {
            route_id for item in occurrences for route_id in item.canonical_route_ids()
        }
        if occurrence_route_ids != {landing.route_id for landing in landings}:
            raise ValueError("ordinary route landing inventory differs from result occurrences")
        for landing in landings:
            if landing.landing_semantic != "occurrence_bound":
                continue
            lossless_only_sources = tuple(
                item
                for item in occurrences
                if landing.route_id in item.canonical_route_ids()
                and item.landing_disposition == "lossless_only"
            )
            if not lossless_only_sources:
                continue
            if conditional_landing is None:
                raise ValueError("lossless-only fixed source lacks conditional lossless authority")
            conditional_route_id = conditional_landing.route_id
            for item in lossless_only_sources:
                if (
                    item.occurrence_ordinal not in fallback_ordinals
                    or conditional_route_id not in item.canonical_route_ids()
                    or item.committed_staging_receipts_by_route().get(conditional_route_id)
                    != conditional_landing.receipt_root_sha256
                ):
                    raise ValueError(
                        "lossless-only fixed source differs from conditional receipt authority"
                    )
        return

    if body_object is None or observation.body_disposition != "public_parser_input":
        raise ValueError("unknown Video route policy lacks exact parser-input authority")
    if len(ordered_fixed_routes) != 1:
        raise ValueError("unknown Video response has multiple fixed routes")
    unknown, fallback_frame = _unknown_video_response_authority(
        observation=observation,
        body_object=body_object,
    )
    if unknown.outcome != observation.outcome:
        raise ValueError("unknown Video outcome differs from exact parser-input rederivation")
    has_drift = fallback_frame is not None

    fixed_route = ordered_fixed_routes[0]
    contract = pinned_runtime_contracts().get(observation.attempt.endpoint_id)
    if contract is None or contract.result_sets:
        raise ValueError("unknown Video endpoint lacks its zero-result contract")
    derived_conditional_id = (
        f"{fixed_route.endpoint_name}:{LOSSLESS_FALLBACK_STAGING_KEY}:{len(contract.result_sets)}"
    )
    try:
        derived_conditional_admission = admit_conditional_lossless_route(
            endpoint_name=fixed_route.endpoint_name,
            static_route_ids=(fixed_route.route_id,),
            conditional_route_ids=(derived_conditional_id,),
            provider_authority_sha256=observation.attempt.provider_authority_sha256,
        )
    except ValueError as exc:
        raise ValueError("unknown Video conditional policy cannot be derived") from exc
    alias_policy = fixed_route.storage_columns == derived_conditional_admission.storage_columns
    if has_drift != (conditional_landing is not None):
        raise ValueError("unknown Video conditional landing differs from observed drift")
    if conditional_landing is not None:
        if conditional_landing.route_id != derived_conditional_id:
            raise ValueError("unknown Video conditional landing identity differs")
        _require_exact_landing_frame(
            conditional_landing,
            fallback_frame,
            label="unknown Video conditional landing",
        )

    fixed_landing = landings[0]
    expected_fixed_semantic: RouteLandingSemantic
    expected_alias_target: str | None
    if has_drift and alias_policy:
        expected_fixed_semantic = "response_canonical_alias"
        expected_alias_target = derived_conditional_id
        _require_exact_landing_frame(
            fixed_landing,
            fallback_frame,
            label="unknown Video canonical-alias landing",
        )
    else:
        expected_fixed_semantic = "response_fixed_zero"
        expected_alias_target = None
        _require_exact_landing_frame(
            fixed_landing,
            pl.DataFrame(),
            label="unknown Video fixed-zero landing",
        )
    if (
        fixed_landing.landing_semantic != expected_fixed_semantic
        or fixed_landing.alias_target_route_id != expected_alias_target
    ):
        raise ValueError("unknown Video fixed-route landing policy differs")

    expected_occurrences = _unknown_video_expected_occurrences(
        observation=observation,
        unknown=unknown,
        conditional_landing=conditional_landing,
    )
    if tuple(occurrences) != expected_occurrences:
        raise ValueError("unknown Video result occurrences differ from exact rederivation")


class RawRequestAuthorityBundleV2(_StrictFrozenModel):
    """A closed, cross-table authority bundle ready for transactional landing."""

    schema_version: SchemaVersion
    bundle_sha256: Sha256
    objects: Annotated[
        tuple[ParserInputObjectV2, ...],
        Field(max_length=MAX_AUTHORITY_ROWS),
    ]
    observations: Annotated[
        tuple[RequestObservationV2, ...],
        Field(max_length=MAX_AUTHORITY_ROWS),
    ]
    occurrences: Annotated[
        tuple[ResultOccurrenceV2, ...],
        Field(max_length=MAX_AUTHORITY_ROWS),
    ]
    landings: Annotated[
        tuple[ObservationRouteLandingV2, ...],
        Field(max_length=MAX_AUTHORITY_ROWS),
    ]

    @model_validator(mode="after")
    def _validate_closed_bundle(self) -> Self:
        object_by_sha: dict[str, ParserInputObjectV2] = {}
        for item in self.objects:
            validated = validate_parser_input_object(item)
            if validated.object_sha256 in object_by_sha:
                raise ValueError("parser-input object keys must be unique")
            object_by_sha[validated.object_sha256] = validated

        observation_by_sha: dict[str, RequestObservationV2] = {}
        for item in self.observations:
            validated = validate_request_observation(item)
            key = validated.attempt.observation_sha256
            if key in observation_by_sha:
                raise ValueError("request-observation keys must be unique")
            observation_by_sha[key] = validated

        occurrence_by_sha: dict[str, ResultOccurrenceV2] = {}
        occurrences_by_observation: defaultdict[str, list[ResultOccurrenceV2]] = defaultdict(list)
        for item in self.occurrences:
            validated = validate_result_occurrence(item)
            if validated.occurrence_sha256 in occurrence_by_sha:
                raise ValueError("result-occurrence keys must be unique")
            if validated.observation_sha256 not in observation_by_sha:
                raise ValueError("result occurrence references a missing observation")
            occurrence_by_sha[validated.occurrence_sha256] = validated
            occurrences_by_observation[validated.observation_sha256].append(validated)

        landing_by_sha: dict[str, ObservationRouteLandingV2] = {}
        landings_by_observation: defaultdict[
            str,
            list[ObservationRouteLandingV2],
        ] = defaultdict(list)
        for item in self.landings:
            validated = validate_observation_route_landing(item)
            if validated.landing_sha256 in landing_by_sha:
                raise ValueError("observation-route landing keys must be unique")
            if validated.observation_sha256 not in observation_by_sha:
                raise ValueError("observation-route landing references a missing observation")
            landing_by_sha[validated.landing_sha256] = validated
            landings_by_observation[validated.observation_sha256].append(validated)
        expected_landing_order = tuple(
            sorted(
                self.landings,
                key=lambda item: (item.observation_sha256, item.route_ordinal),
            )
        )
        if self.landings != expected_landing_order:
            raise ValueError("observation-route landings are not canonically ordered")

        referenced_objects: set[str] = set()
        selections_by_call: defaultdict[str, list[RequestObservationV2]] = defaultdict(list)
        retries_by_call: defaultdict[str, set[int]] = defaultdict(set)
        call_payloads: dict[str, tuple[object, ...]] = {}
        alias_binding_json_by_sha256: dict[str, str] = {}
        alias_observations_by_sha256: defaultdict[
            str,
            list[RequestObservationV2],
        ] = defaultdict(list)
        for observation_sha256, observation in observation_by_sha.items():
            body_object_sha256 = observation.body_object_sha256
            if body_object_sha256 is not None:
                if body_object_sha256 not in object_by_sha:
                    raise ValueError("body-bearing observation references a missing object")
                referenced_objects.add(body_object_sha256)

            rows = sorted(
                occurrences_by_observation.get(observation_sha256, []),
                key=lambda item: item.occurrence_ordinal,
            )
            if [item.occurrence_ordinal for item in rows] != list(range(len(rows))):
                raise ValueError("result occurrence ordinals must be contiguous and ordered")
            if (
                len(rows) != observation.result_occurrence_count
                or _sha256_json(
                    [item.occurrence_sha256 for item in rows],
                    maximum_bytes=MAX_RESULT_JSON_BYTES,
                )
                != observation.result_occurrences_sha256
            ):
                raise ValueError("observation result occurrence inventory is invalid")
            landing_rows = sorted(
                landings_by_observation.get(observation_sha256, []),
                key=lambda item: item.route_ordinal,
            )
            if [item.route_ordinal for item in landing_rows] != list(range(len(landing_rows))):
                raise ValueError("observation route landing ordinals must be contiguous")
            if (
                len(landing_rows) != observation.route_landing_count
                or _sha256_json(
                    [item.landing_sha256 for item in landing_rows],
                    maximum_bytes=MAX_RESULT_JSON_BYTES,
                )
                != observation.route_landings_sha256
            ):
                raise ValueError("observation route landing inventory is invalid")
            if landing_rows:
                live_snapshot_values = {item.live_snapshot_at for item in landing_rows}
                if observation.attempt.source_family == "live":
                    if None in live_snapshot_values or len(live_snapshot_values) != 1:
                        raise ValueError(
                            "live observation landings lack one exact shared snapshot time"
                        )
                elif any(item.live_snapshot_at is not None for item in landing_rows):
                    raise ValueError("non-live observation fabricated a live snapshot time")
            if observation.attempt.source_family != "live" and any(
                item.presence == "not_observed_parent_empty" for item in rows
            ):
                raise ValueError(
                    "parent-empty unobserved result requires a live request observation"
                )

            terminal_success = observation.outcome in {
                "success_nonempty",
                "success_empty",
                "static_snapshot_success",
            }
            if observation.lifecycle == "selected_terminal" and not terminal_success:
                raise ValueError("non-success observation cannot be selected terminal")
            if terminal_success:
                for item in rows:
                    routes = _decode_canonical_json_list(
                        item.canonical_route_ids_json,
                        maximum_bytes=MAX_RESULT_JSON_BYTES,
                    )
                    receipts = _decode_canonical_json_list(
                        item.committed_staging_receipts_json,
                        maximum_bytes=MAX_RESULT_JSON_BYTES,
                    )
                    receipt_routes = {
                        cast("dict[str, object]", receipt)["route_id"] for receipt in receipts
                    }
                    if receipt_routes != set(routes):
                        raise ValueError(
                            "successful result occurrence lacks complete staging receipts"
                        )
            is_unknown_video = _is_exact_unknown_dynamic_video_attempt(observation.attempt)
            if (
                observation.outcome == "success_nonempty"
                and not is_unknown_video
                and not any(
                    item.presence == "present" and (item.row_count > 0 or item.node_count > 0)
                    for item in rows
                )
            ):
                raise ValueError("success-nonempty observation has no nonempty result")
            if observation.outcome == "success_empty":
                empty_states = {"present_empty", "empty_object", "empty_array"}
                if (
                    not is_unknown_video
                    and not any(item.presence in empty_states for item in rows)
                    or any(
                        item.presence == "present" and (item.row_count > 0 or item.node_count > 0)
                        for item in rows
                    )
                ):
                    raise ValueError("success-empty observation has nonempty result evidence")

            duplicate_ordinals: defaultdict[str, list[int]] = defaultdict(list)
            for item in rows:
                duplicate_ordinals[item.result_name].append(item.duplicate_name_ordinal)
            if any(
                sorted(values) != list(range(len(values))) for values in duplicate_ordinals.values()
            ):
                raise ValueError("duplicate result-name ordinals are not contiguous")

            body_object = None if body_object_sha256 is None else object_by_sha[body_object_sha256]
            _validate_observation_route_landings(
                observation=observation,
                occurrences=rows,
                landings=landing_rows,
                body_object=body_object,
            )
            alias_binding_sha256 = observation.logical_provider_parameter_binding_sha256
            alias_binding_json = observation.logical_provider_parameter_binding_json
            if alias_binding_sha256 is not None:
                if alias_binding_json is None:
                    raise ValueError("logical/provider alias binding lacks canonical bytes")
                prior_alias_json = alias_binding_json_by_sha256.setdefault(
                    alias_binding_sha256,
                    alias_binding_json,
                )
                if prior_alias_json != alias_binding_json:
                    raise ValueError("logical/provider alias binding digest collides across bytes")
                alias_observations_by_sha256[alias_binding_sha256].append(observation)

            call_key = observation.attempt.provider_call_sha256
            call_payload = (
                observation.attempt.semantic_request_sha256,
                observation.attempt.logical_invocation_sha256,
                observation.attempt.provider_call_role,
                observation.attempt.provider_call_ordinal,
                observation.attempt.source_family,
                observation.attempt.endpoint_id,
                observation.attempt.provider_request_sha256,
                observation.attempt.scope_sha256,
                observation.attempt.pagination_sha256,
                observation.attempt.page_ordinal,
            )
            prior_call_payload = call_payloads.setdefault(call_key, call_payload)
            if prior_call_payload != call_payload:
                raise ValueError("provider-call key collides across different call identities")
            retry_ordinal = observation.attempt.retry_ordinal
            if retry_ordinal in retries_by_call[call_key]:
                raise ValueError("provider-call retry ordinals must be unique")
            retries_by_call[call_key].add(retry_ordinal)
            if observation.lifecycle == "selected_terminal":
                selections_by_call[call_key].append(observation)

        if referenced_objects != set(object_by_sha):
            raise ValueError("parser-input object inventory contains an orphan object")
        if any(len(items) > 1 for items in selections_by_call.values()):
            raise ValueError("provider call has more than one selected terminal attempt")
        for binding_sha256, alias_observations in alias_observations_by_sha256.items():
            try:
                from nbadb.contracts.logical_provider_parameter_binding import (
                    LogicalProviderParameterBindingV1,
                )

                parameter_binding = LogicalProviderParameterBindingV1.from_canonical_bytes(
                    alias_binding_json_by_sha256[binding_sha256].encode(
                        "utf-8",
                        errors="strict",
                    )
                )
            except (AttributeError, TypeError, UnicodeEncodeError, ValueError) as exc:
                raise ValueError("logical/provider alias binding group cannot be replayed") from exc
            selected_calls = {
                observation.attempt.provider_call_sha256 for observation in alias_observations
            }
            binding_calls = {
                entry.provider_call_sha256 for entry in parameter_binding.provider_entries
            }
            if (
                parameter_binding.binding_sha256 != binding_sha256
                or len(selected_calls) != len(alias_observations)
                or len(binding_calls) != len(parameter_binding.provider_entries)
                or binding_calls != selected_calls
            ):
                raise ValueError(
                    "logical/provider alias binding is not bijective across observations"
                )
        if self.bundle_sha256 != _sha256_json(
            _bundle_identity_payload(
                objects=self.objects,
                observations=self.observations,
                occurrences=self.occurrences,
                landings=self.landings,
            )
        ):
            raise ValueError("raw request authority bundle digest is invalid")
        return self

    @classmethod
    def build(
        cls,
        *,
        objects: Sequence[ParserInputObjectV2],
        observations: Sequence[RequestObservationV2],
        occurrences: Sequence[ResultOccurrenceV2],
        landings: Sequence[ObservationRouteLandingV2],
    ) -> Self:
        parsed_objects = tuple(validate_parser_input_object(item) for item in objects)
        parsed_observations = tuple(validate_request_observation(item) for item in observations)
        parsed_occurrences = tuple(validate_result_occurrence(item) for item in occurrences)
        parsed_landings = tuple(validate_observation_route_landing(item) for item in landings)
        return cls(
            schema_version=RAW_REQUEST_AUTHORITY_SCHEMA_VERSION,
            bundle_sha256=_sha256_json(
                _bundle_identity_payload(
                    objects=parsed_objects,
                    observations=parsed_observations,
                    occurrences=parsed_occurrences,
                    landings=parsed_landings,
                )
            ),
            objects=parsed_objects,
            observations=parsed_observations,
            occurrences=parsed_occurrences,
            landings=parsed_landings,
        )

    def incomplete_provider_call_sha256s(self) -> tuple[str, ...]:
        selected = {
            item.attempt.provider_call_sha256
            for item in self.observations
            if item.lifecycle == "selected_terminal"
        }
        all_calls = {item.attempt.provider_call_sha256 for item in self.observations}
        return tuple(sorted(all_calls - selected))

    def require_complete_terminal_selection(self) -> None:
        incomplete = self.incomplete_provider_call_sha256s()
        if incomplete:
            raise RawRequestAuthorityError(
                "raw request authority has provider calls without a terminal selection"
            )

    def selected_terminal_occurrences_for_route(
        self,
        route_id: str,
        receipt_root_sha256: str,
    ) -> tuple[tuple[RequestObservationV2, ResultOccurrenceV2], ...]:
        """Select one route's exact terminal occurrence denominator.

        The supplied receipt root is an assertion over the selected denominator,
        never a filter.  Failed or otherwise non-selected retries are deliberately
        excluded, while terminal present-empty and zero-row occurrences remain in
        the returned inventory.
        """

        if (
            type(route_id) is not str
            or _SAFE_ID_RE.fullmatch(route_id) is None
            or _FORBIDDEN_IDENTITY_RE.search(route_id) is not None
        ):
            raise RawRequestAuthorityError("selected route identity is invalid or unsafe")
        if (
            type(receipt_root_sha256) is not str
            or _SHA256_RE.fullmatch(receipt_root_sha256) is None
        ):
            raise RawRequestAuthorityError("selected route receipt root is invalid")

        bundle = validate_raw_request_authority_bundle(self)
        observations_by_sha = {
            item.attempt.observation_sha256: item for item in bundle.observations
        }
        if len(observations_by_sha) != len(bundle.observations):
            raise RawRequestAuthorityError("selected route observation authority is duplicated")

        selected_observation_ids = {
            observation_sha256
            for observation_sha256, observation in observations_by_sha.items()
            if observation.lifecycle == "selected_terminal"
        }
        selected_landings = tuple(
            landing
            for landing in bundle.landings
            if landing.observation_sha256 in selected_observation_ids
            and landing.route_id == route_id
        )
        if not selected_landings:
            raise RawRequestAuthorityError("selected route lacks response-level landing authority")
        if any(landing.receipt_root_sha256 != receipt_root_sha256 for landing in selected_landings):
            raise RawRequestAuthorityError(
                "selected route landing has the wrong committed receipt root"
            )
        selected: list[tuple[RequestObservationV2, ResultOccurrenceV2]] = []
        seen_occurrences: set[str] = set()
        endpoint_identities: set[tuple[str, str]] = set()
        for occurrence in bundle.occurrences:
            observation = observations_by_sha.get(occurrence.observation_sha256)
            if observation is None:
                raise RawRequestAuthorityError(
                    "selected route contains a foreign result occurrence"
                )
            if occurrence.observation_sha256 not in selected_observation_ids:
                continue
            if route_id not in occurrence.canonical_route_ids():
                continue
            if occurrence.occurrence_sha256 in seen_occurrences:
                raise RawRequestAuthorityError(
                    "selected route contains duplicate occurrence membership"
                )
            seen_occurrences.add(occurrence.occurrence_sha256)
            receipts = occurrence.committed_staging_receipts_by_route()
            if receipts.get(route_id) != receipt_root_sha256:
                raise RawRequestAuthorityError(
                    "selected route occurrence has the wrong committed receipt root"
                )
            endpoint_identities.add(
                (observation.attempt.source_family, observation.attempt.endpoint_id)
            )
            selected.append((observation, occurrence))

        if len(endpoint_identities) > 1:
            raise RawRequestAuthorityError(
                "selected route mixes endpoint or source-family identities"
            )

        def authority_order(
            item: tuple[RequestObservationV2, ResultOccurrenceV2],
        ) -> tuple[object, ...]:
            observation, occurrence = item
            attempt = observation.attempt
            page_ordinal = -1 if attempt.page_ordinal is None else attempt.page_ordinal
            provider_result_ordinal = (
                -1
                if occurrence.provider_result_ordinal is None
                else occurrence.provider_result_ordinal
            )
            canonical_result_ordinal = (
                -1
                if occurrence.canonical_result_ordinal is None
                else occurrence.canonical_result_ordinal
            )
            return (
                attempt.logical_invocation_sha256,
                attempt.semantic_request_sha256,
                attempt.provider_call_ordinal,
                page_ordinal,
                attempt.provider_call_role,
                attempt.provider_call_sha256,
                attempt.retry_ordinal,
                attempt.request_ordinal,
                occurrence.occurrence_ordinal,
                provider_result_ordinal,
                canonical_result_ordinal,
                occurrence.occurrence_sha256,
            )

        return tuple(sorted(selected, key=authority_order))


PARSER_INPUT_OBJECT_ADAPTER = TypeAdapter(ParserInputObjectV2)
REQUEST_ATTEMPT_IDENTITY_ADAPTER = TypeAdapter(RequestAttemptIdentityV2)
REQUEST_OBSERVATION_ADAPTER = TypeAdapter(RequestObservationV2)
RESULT_OCCURRENCE_ADAPTER = TypeAdapter(ResultOccurrenceV2)
OBSERVATION_ROUTE_LANDING_ADAPTER = TypeAdapter(ObservationRouteLandingV2)
RAW_REQUEST_AUTHORITY_BUNDLE_ADAPTER = TypeAdapter(RawRequestAuthorityBundleV2)


def validate_parser_input_object(value: object) -> ParserInputObjectV2:
    """Strictly revalidate one untrusted public parser-input object."""

    return PARSER_INPUT_OBJECT_ADAPTER.validate_python(value, strict=True)


def validate_request_attempt_identity(value: object) -> RequestAttemptIdentityV2:
    """Strictly revalidate one untrusted request-attempt identity."""

    return REQUEST_ATTEMPT_IDENTITY_ADAPTER.validate_python(value, strict=True)


def validate_request_observation(value: object) -> RequestObservationV2:
    """Strictly revalidate one untrusted request observation."""

    return REQUEST_OBSERVATION_ADAPTER.validate_python(value, strict=True)


def validate_result_occurrence(value: object) -> ResultOccurrenceV2:
    """Strictly revalidate one untrusted result occurrence."""

    return RESULT_OCCURRENCE_ADAPTER.validate_python(value, strict=True)


def validate_observation_route_landing(value: object) -> ObservationRouteLandingV2:
    """Strictly revalidate one untrusted response-level route landing."""

    return OBSERVATION_ROUTE_LANDING_ADAPTER.validate_python(value, strict=True)


def validate_raw_request_authority_bundle(value: object) -> RawRequestAuthorityBundleV2:
    """Strictly revalidate one closed, cross-table raw authority bundle."""

    return RAW_REQUEST_AUTHORITY_BUNDLE_ADAPTER.validate_python(value, strict=True)
