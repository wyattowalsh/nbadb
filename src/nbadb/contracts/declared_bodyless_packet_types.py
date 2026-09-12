"""Dependency-pure exact authority types for declared-bodyless static packets.

The provider-facing construction layer deliberately lives elsewhere.  This
module accepts only exact built-in public identity fields, a frozen canonical
field schema, and canonical packet bytes.  It can therefore be used by body
replay and independent verification without importing runtime registries,
transport models, staging routes, extraction code, or third-party packages.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Final, Never, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "DECLARED_BODYLESS_PACKET_CODEC_CONTRACT_SHA256",
    "DECLARED_BODYLESS_PACKET_CODEC_ID",
    "DECLARED_BODYLESS_PACKET_ENCODING_ID",
    "DECLARED_BODYLESS_PACKET_KIND",
    "DECLARED_BODYLESS_PACKET_MEDIA_TYPE",
    "DECLARED_BODYLESS_PACKET_RECEIPT_KIND",
    "DECLARED_BODYLESS_PACKET_REPRESENTATION_ID",
    "DECLARED_BODYLESS_PACKET_RESOURCE_PREFIX",
    "DECLARED_BODYLESS_PACKET_SCHEMA_VERSION",
    "MAX_DECLARED_BODYLESS_PACKET_BYTES",
    "MAX_DECLARED_BODYLESS_SCHEMA_BYTES",
    "DeclaredBodylessPacketError",
    "DeclaredBodylessPacketProjectionV1",
    "DeclaredBodylessPacketReadbackReceiptV1",
    "DeclaredBodylessPacketV1",
    "decode_public_canonical_packet",
    "rederive_declared_bodyless_packet_projection",
    "validate_declared_bodyless_packet_bytes",
    "validate_declared_bodyless_packet_identity",
    "validate_declared_bodyless_packet_readback_receipt",
]


DECLARED_BODYLESS_PACKET_SCHEMA_VERSION: Final = 1
DECLARED_BODYLESS_PACKET_KIND: Final = "nbadb_declared_bodyless_packet_v1"
DECLARED_BODYLESS_PACKET_RECEIPT_KIND: Final = "nbadb_declared_bodyless_packet_readback_receipt_v1"
DECLARED_BODYLESS_PACKET_REPRESENTATION_ID: Final = "nbadb_static_source_rows_canonical_json_v1"
DECLARED_BODYLESS_PACKET_MEDIA_TYPE: Final = "application/json"
DECLARED_BODYLESS_PACKET_ENCODING_ID: Final = "utf-8-strict-v1"
DECLARED_BODYLESS_PACKET_CODEC_ID: Final = "identity-bytes-v1"
DECLARED_BODYLESS_PACKET_RESOURCE_PREFIX: Final = "declared-static-packet-sha256-"

MAX_DECLARED_BODYLESS_PACKET_BYTES: Final = 64 * 1024 * 1024
MAX_DECLARED_BODYLESS_JSON_DEPTH: Final = 64
MAX_DECLARED_BODYLESS_JSON_NODES: Final = 2_000_000
MAX_DECLARED_BODYLESS_STRING_BYTES: Final = 4 * 1024 * 1024
MAX_DECLARED_BODYLESS_TOTAL_STRING_BYTES: Final = 64 * 1024 * 1024
MAX_DECLARED_BODYLESS_NUMBER_TOKEN_BYTES: Final = 128
MAX_DECLARED_BODYLESS_KNOWN_SECRETS: Final = 128
MAX_DECLARED_BODYLESS_KNOWN_SECRET_BYTES: Final = 4096
MAX_DECLARED_BODYLESS_SCHEMA_BYTES: Final = 4 * 1024 * 1024

_MAX_IDENTITY_BYTES: Final = 16 * 1024 * 1024
_MAX_FIELDS: Final = 1_000_000
_MAX_ROWS: Final = 1_000_000
_MAX_CELLS: Final = 10_000_000
_MAX_INT64: Final = (1 << 63) - 1

_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_SOURCE_SHA_RE: Final = re.compile(r"[0-9a-f]{40}\Z")
_SAFE_ID_RE: Final = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,199}\Z")
_CAMEL_ACRONYM_BOUNDARY_RE: Final = re.compile(r"([A-Z]+)([A-Z][a-z])", re.ASCII)
_CAMEL_WORD_BOUNDARY_RE: Final = re.compile(r"([a-z0-9])([A-Z])", re.ASCII)
_KEY_SEPARATOR_RE: Final = re.compile(r"[^A-Za-z0-9]+", re.ASCII)
_FORBIDDEN_KEY_RE: Final = re.compile(
    r"(?:authorization|cookie|set_cookie|credential|client_secret|access_token|"
    r"refresh_token|api_key|password|proxy_url|proxy_host|vpn_server|vpn_ip|"
    r"request_headers|response_headers|runner_path|workspace_path|local_path|file_path|"
    r"github_token|private_key|secret_key|personal_access_token|ssh_private_key|"
    r"token|secret|auth|authentication|session|auth_token|auth_key|session_key|"
    r"session_token|api_token)\Z",
    re.IGNORECASE,
)
_AUTH_VALUE_RE: Final = re.compile(
    r"(?:authorization\s*:\s*(?:bearer|basic)\s+"
    r"[A-Za-z0-9._~+/=-]{8,}(?![A-Za-z0-9._~+/=-])|"
    r"bearer\s+[A-Za-z0-9._~+/=-]{12,}(?![A-Za-z0-9._~+/=-])|"
    r"basic\s+[A-Za-z0-9+/=]{12,}(?![A-Za-z0-9+/=]))",
    re.ASCII | re.IGNORECASE,
)
_KNOWN_TOKEN_VALUE_RE: Final = re.compile(
    r"(?:gh[pousr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}|"
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"
)
_LOCAL_PATH_VALUE_RE: Final = re.compile(
    r"(?:/Users/[^/\x00\s]+(?=/|\s|\Z)|/home/[^/\x00\s]+(?=/|\s|\Z)|"
    r"/private/var(?![A-Za-z0-9_])|[A-Za-z]:\\Users\\)"
)
_URL_USERINFO_VALUE_RE: Final = re.compile(r"(?i)https?://[^/\s:@]+:[^/\s@]+@")

_CODEC_CONTRACT: Final = {
    "codec_id": DECLARED_BODYLESS_PACKET_CODEC_ID,
    "encoded_representation": DECLARED_BODYLESS_PACKET_REPRESENTATION_ID,
    "identity": True,
    "stored_bytes_equal_uncompressed_bytes": True,
    "trailing_bytes_allowed": False,
}
_STATIC_SAMPLE_TYPES: Final = frozenset({"bool", "dict", "float", "int", "list", "str"})

_PROJECTION_ROW_FIELDS: Final = (
    "field_count",
    "row_count",
    "cell_count",
    "schema_root_sha256",
    "content_root_sha256",
    "row_root_sha256",
    "cell_root_sha256",
)
_PACKET_ROW_FIELDS: Final = (
    "schema_version",
    "kind",
    "observation_sha256",
    "observation_record_sha256",
    "attempt_sha256",
    "logical_receipt_sha256",
    "endpoint_id",
    "endpoint_contract_sha256",
    "provider_authority_sha256",
    "public_resource_name",
    "frozen_static_schema_json",
    "frozen_static_schema_sha256",
    "source_sha",
    "run_id",
    "run_attempt",
    "chain_id",
    "lane_id",
    "representation_id",
    "media_type",
    "encoding_id",
    "codec_contract_id",
    "codec_contract_sha256",
    "uncompressed_packet_sha256",
    "uncompressed_packet_length",
    "stored_payload_sha256",
    "stored_payload_length",
    "field_count",
    "row_count",
    "cell_count",
    "schema_root_sha256",
    "content_root_sha256",
    "row_root_sha256",
    "cell_root_sha256",
    "packet_authority_sha256",
)
_READBACK_ROW_FIELDS: Final = (
    "schema_version",
    "kind",
    "observation_sha256",
    "observation_record_sha256",
    "packet_authority_sha256",
    "public_resource_name",
    "frozen_static_schema_sha256",
    "store_namespace_sha256",
    "stored_payload_sha256",
    "stored_payload_length",
    "readback_payload_sha256",
    "readback_payload_length",
    "field_count",
    "row_count",
    "cell_count",
    "schema_root_sha256",
    "content_root_sha256",
    "row_root_sha256",
    "cell_root_sha256",
    "receipt_sha256",
)


class DeclaredBodylessPacketError(ValueError):
    """One declared-bodyless public authority is unsafe or inconsistent."""


def _fail(message: str) -> Never:
    raise DeclaredBodylessPacketError(message) from None


def _canonical_json_bytes(value: object, *, maximum: int) -> bytes:
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8", errors="strict")
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("declared bodyless authority is not canonical JSON")
    if not encoded or len(encoded) > maximum:
        _fail("declared bodyless authority exceeds its byte bound")
    return encoded


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: object, *, maximum: int = _MAX_IDENTITY_BYTES) -> str:
    return _sha256_bytes(_canonical_json_bytes(value, maximum=maximum))


DECLARED_BODYLESS_PACKET_CODEC_CONTRACT_SHA256: Final = _sha256_json(_CODEC_CONTRACT)


def _exact_sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be one exact SHA-256")
    return value


def _exact_safe_id(value: object, *, label: str) -> str:
    if type(value) is not str or _SAFE_ID_RE.fullmatch(value) is None:
        _fail(f"{label} must be one exact public-safe identifier")
    return value


def _exact_source_sha(value: object) -> str:
    if type(value) is not str or _SOURCE_SHA_RE.fullmatch(value) is None:
        _fail("packet source identity is invalid")
    return value


def _exact_integer(value: object, *, label: str, maximum: int, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        _fail(f"{label} must be one bounded exact integer")
    return value


def _strict_row(
    value: object,
    *,
    expected_fields: tuple[str, ...],
    label: str,
) -> dict[str, object]:
    if type(value) is not dict:
        _fail(f"{label} does not have its exact ordered row shape")
    mapping = cast("dict[object, object]", value)
    if (
        len(mapping) != len(expected_fields)
        or any(type(key) is not str for key in mapping)
        or tuple(mapping) != expected_fields
    ):
        _fail(f"{label} does not have its exact ordered row shape")
    return cast("dict[str, object]", value)


def _strict_canonical_object(
    value: object,
    *,
    expected_fields: tuple[str, ...],
    label: str,
) -> dict[str, object]:
    if type(value) is not dict:
        _fail(f"{label} does not have its exact canonical object shape")
    mapping = cast("dict[object, object]", value)
    if (
        len(mapping) != len(expected_fields)
        or any(type(key) is not str for key in mapping)
        or tuple(mapping) != tuple(sorted(expected_fields))
    ):
        _fail(f"{label} does not have its exact canonical object shape")
    return cast("dict[str, object]", value)


def _normalized_public_key(value: str) -> str:
    separated = _CAMEL_ACRONYM_BOUNDARY_RE.sub(r"\1_\2", value)
    separated = _CAMEL_WORD_BOUNDARY_RE.sub(r"\1_\2", separated)
    return _KEY_SEPARATOR_RE.sub("_", separated).strip("_").lower()


def _preflight_json_structure(packet_bytes: bytes) -> None:
    """Bound lexical JSON work before UTF-8 decoding or decoder allocation."""

    depth = 0
    maximum_depth = 0
    structural_nodes = 1
    in_string = False
    escaped = False
    string_bytes = 0
    total_string_bytes = 0
    scalar_token_bytes = 0
    for byte in packet_bytes:
        if in_string:
            if escaped:
                escaped = False
                string_bytes += 1
            elif byte == 0x5C:  # backslash
                escaped = True
                string_bytes += 1
            elif byte == 0x22:  # quote
                in_string = False
                total_string_bytes += string_bytes
                if (
                    string_bytes > MAX_DECLARED_BODYLESS_STRING_BYTES
                    or total_string_bytes > MAX_DECLARED_BODYLESS_TOTAL_STRING_BYTES
                ):
                    _fail("declared bodyless packet exceeds its string bound")
                string_bytes = 0
            else:
                string_bytes += 1
            continue

        if byte == 0x22:
            scalar_token_bytes = 0
            in_string = True
        elif byte in (0x7B, 0x5B):  # { [
            scalar_token_bytes = 0
            depth += 1
            maximum_depth = max(maximum_depth, depth)
            structural_nodes += 1
        elif byte in (0x7D, 0x5D):  # } ]
            scalar_token_bytes = 0
            depth -= 1
            if depth < 0:
                _fail("declared bodyless packet is invalid")
        elif byte in (0x2C, 0x3A):  # , :
            scalar_token_bytes = 0
            structural_nodes += 1
        elif byte in (0x20, 0x09, 0x0A, 0x0D):
            scalar_token_bytes = 0
        else:
            scalar_token_bytes += 1
            if scalar_token_bytes > MAX_DECLARED_BODYLESS_NUMBER_TOKEN_BYTES:
                _fail("declared bodyless packet contains an oversized scalar token")
        if (
            maximum_depth > MAX_DECLARED_BODYLESS_JSON_DEPTH
            or structural_nodes > MAX_DECLARED_BODYLESS_JSON_NODES
        ):
            _fail("declared bodyless packet exceeds its structure bound")
    if in_string or escaped or depth != 0:
        _fail("declared bodyless packet is invalid")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, value in pairs:
        if key in output:
            _fail("declared bodyless packet contains duplicate object keys")
        output[key] = value
    return output


def _bounded_integer_token(token: str) -> int:
    if len(token) > MAX_DECLARED_BODYLESS_NUMBER_TOKEN_BYTES:
        _fail("declared bodyless packet contains an oversized number")
    try:
        value = int(token)
    except ValueError:
        _fail("declared bodyless packet contains an invalid number")
    if abs(value) > _MAX_INT64:
        _fail("declared bodyless packet contains an out-of-range number")
    return value


def _bounded_float_token(token: str) -> float:
    if len(token) > MAX_DECLARED_BODYLESS_NUMBER_TOKEN_BYTES:
        _fail("declared bodyless packet contains an oversized number")
    try:
        value = float(token)
    except ValueError:
        _fail("declared bodyless packet contains an invalid number")
    if not math.isfinite(value):
        _fail("declared bodyless packet contains a non-finite number")
    return value


def _reject_nonfinite_constant(_token: str) -> object:
    _fail("declared bodyless packet contains a non-finite number")


def _secret_bytes(value: str | bytes) -> bytes:
    if type(value) is bytes:
        encoded = value
    elif type(value) is str:
        try:
            encoded = value.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            _fail("declared bodyless secret inventory is invalid")
    else:
        _fail("declared bodyless secret inventory is invalid")
    if not encoded or len(encoded) > MAX_DECLARED_BODYLESS_KNOWN_SECRET_BYTES:
        _fail("declared bodyless secret inventory is invalid")
    return encoded


def _admitted_secret_bytes(known_secrets: Sequence[str | bytes]) -> tuple[bytes, ...]:
    if (
        type(known_secrets) not in (tuple, list)
        or len(known_secrets) > MAX_DECLARED_BODYLESS_KNOWN_SECRETS
    ):
        _fail("declared bodyless secret inventory is invalid")
    return tuple(_secret_bytes(item) for item in known_secrets)


def _public_text_bytes(value: str, *, secret_bytes: tuple[bytes, ...]) -> bytes:
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _fail("declared bodyless packet contains invalid text")
    if (
        len(encoded) > MAX_DECLARED_BODYLESS_STRING_BYTES
        or _AUTH_VALUE_RE.search(value)
        or _KNOWN_TOKEN_VALUE_RE.search(value)
        or _LOCAL_PATH_VALUE_RE.search(value)
        or _URL_USERINFO_VALUE_RE.search(value)
        or any(secret in encoded for secret in secret_bytes)
    ):
        _fail("declared bodyless packet contains prohibited material")
    return encoded


def _scan_public_value(value: object, *, secret_bytes: tuple[bytes, ...]) -> None:
    stack: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    total_string_bytes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_DECLARED_BODYLESS_JSON_NODES or depth > MAX_DECLARED_BODYLESS_JSON_DEPTH:
            _fail("declared bodyless packet exceeds its structure bound")
        if type(item) is dict:
            for key, child in cast("dict[str, object]", item).items():
                if type(key) is not str or _FORBIDDEN_KEY_RE.fullmatch(_normalized_public_key(key)):
                    _fail("declared bodyless packet contains prohibited material")
                total_string_bytes += len(_public_text_bytes(key, secret_bytes=secret_bytes))
                if total_string_bytes > MAX_DECLARED_BODYLESS_TOTAL_STRING_BYTES:
                    _fail("declared bodyless packet contains prohibited material")
                stack.append((child, depth + 1))
        elif type(item) is list:
            stack.extend((child, depth + 1) for child in cast("list[object]", item))
        elif type(item) is str:
            total_string_bytes += len(_public_text_bytes(item, secret_bytes=secret_bytes))
            if total_string_bytes > MAX_DECLARED_BODYLESS_TOTAL_STRING_BYTES:
                _fail("declared bodyless packet contains prohibited material")


def decode_public_canonical_packet(
    packet_bytes: bytes,
    *,
    known_secrets: Sequence[str | bytes] = (),
) -> object:
    """Decode bounded canonical public JSON without echoing rejected content."""

    if type(packet_bytes) is not bytes:
        _fail("declared bodyless packet must be exact built-in bytes")
    if not packet_bytes or len(packet_bytes) > MAX_DECLARED_BODYLESS_PACKET_BYTES:
        _fail("declared bodyless packet exceeds its byte bound")
    secret_bytes = _admitted_secret_bytes(known_secrets)
    _preflight_json_structure(packet_bytes)
    try:
        text = packet_bytes.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
            parse_float=_bounded_float_token,
            parse_int=_bounded_integer_token,
        )
    except DeclaredBodylessPacketError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
        _fail("declared bodyless packet is invalid")
    _scan_public_value(value, secret_bytes=secret_bytes)
    if _canonical_json_bytes(value, maximum=MAX_DECLARED_BODYLESS_PACKET_BYTES) != packet_bytes:
        _fail("declared bodyless packet is not canonical JSON")
    return value


@dataclass(frozen=True, slots=True)
class DeclaredBodylessPacketProjectionV1:
    """Registry-independent roots rederived from packet bytes and frozen fields."""

    field_count: int
    row_count: int
    cell_count: int
    schema_root_sha256: str
    content_root_sha256: str
    row_root_sha256: str
    cell_root_sha256: str

    def __post_init__(self) -> None:
        _exact_integer(
            self.field_count,
            label="projection field count",
            maximum=_MAX_FIELDS,
            minimum=1,
        )
        _exact_integer(self.row_count, label="projection row count", maximum=_MAX_ROWS)
        _exact_integer(self.cell_count, label="projection cell count", maximum=_MAX_CELLS)
        for value, label in (
            (self.schema_root_sha256, "projection schema root"),
            (self.content_root_sha256, "projection content root"),
            (self.row_root_sha256, "projection row root"),
            (self.cell_root_sha256, "projection cell root"),
        ):
            _exact_sha256(value, label=label)
        if self.cell_count != self.field_count * self.row_count:
            _fail("declared bodyless projection denominators are inconsistent")

    def to_row(self) -> dict[str, object]:
        return {field: getattr(self, field) for field in _PROJECTION_ROW_FIELDS}

    @classmethod
    def from_row(cls, value: object) -> DeclaredBodylessPacketProjectionV1:
        if cls is not DeclaredBodylessPacketProjectionV1:
            _fail("declared bodyless projection has a foreign DTO type")
        row = _strict_row(
            value,
            expected_fields=_PROJECTION_ROW_FIELDS,
            label="declared bodyless projection",
        )
        return _construct_projection(row)

    def to_canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_row(), maximum=8 * 1024)

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> DeclaredBodylessPacketProjectionV1:
        if cls is not DeclaredBodylessPacketProjectionV1:
            _fail("declared bodyless projection has a foreign DTO type")
        if type(encoded) is not bytes or not encoded or len(encoded) > 8 * 1024:
            _fail("declared bodyless projection bytes exceed their exact bound")
        payload = decode_public_canonical_packet(encoded)
        row = _strict_canonical_object(
            payload,
            expected_fields=_PROJECTION_ROW_FIELDS,
            label="declared bodyless projection",
        )
        candidate = _construct_projection(row)
        if encoded != candidate.to_canonical_bytes():
            _fail("declared bodyless projection bytes are noncanonical")
        return candidate


def _construct_projection(row: dict[str, object]) -> DeclaredBodylessPacketProjectionV1:
    try:
        return DeclaredBodylessPacketProjectionV1(**cast("dict[str, Any]", row))
    except DeclaredBodylessPacketError:
        raise
    except (AttributeError, TypeError, ValueError):
        _fail("declared bodyless projection fields are invalid")


@dataclass(frozen=True, slots=True)
class _FrozenStaticField:
    name: str
    ordinal: int
    projected: bool
    sample_type: str


def _ordered_sha256_root(values: Sequence[str]) -> str:
    digest = hashlib.sha256()
    digest.update(b"[")
    for ordinal, value in enumerate(values):
        _exact_sha256(value, label="ordered projection member")
        if ordinal:
            digest.update(b",")
        digest.update(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    digest.update(b"]")
    return digest.hexdigest()


def _decode_frozen_static_schema(
    value: object,
    *,
    known_secrets: Sequence[str | bytes] = (),
) -> tuple[_FrozenStaticField, ...]:
    if type(value) is not str:
        _fail("declared bodyless frozen static schema must be exact text")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _fail("declared bodyless frozen static schema is invalid")
    if not encoded or len(encoded) > MAX_DECLARED_BODYLESS_SCHEMA_BYTES:
        _fail("declared bodyless frozen static schema exceeds its byte bound")
    decoded = decode_public_canonical_packet(encoded, known_secrets=known_secrets)
    if type(decoded) is not list:
        _fail("declared bodyless frozen static schema is not an exact field array")
    rows = cast("list[object]", decoded)
    if not rows or len(rows) > _MAX_FIELDS or any(type(item) is not dict for item in rows):
        _fail("declared bodyless frozen static schema field inventory is invalid")
    fields: list[_FrozenStaticField] = []
    seen_names: set[str] = set()
    expected_keys = ("name", "ordinal", "projected", "sample_type")
    for ordinal, item in enumerate(rows):
        row = cast("dict[object, object]", item)
        if any(type(key) is not str for key in row) or tuple(row) != expected_keys:
            _fail("declared bodyless frozen static field has foreign keys")
        name = row["name"]
        field_ordinal = row["ordinal"]
        projected = row["projected"]
        sample_type = row["sample_type"]
        if (
            type(name) is not str
            or not name
            or len(name.encode("utf-8", errors="strict")) > 1024
            or type(field_ordinal) is not int
            or type(projected) is not bool
            or type(sample_type) is not str
        ):
            _fail("declared bodyless frozen static field values are invalid")
        if (
            field_ordinal != ordinal
            or sample_type not in _STATIC_SAMPLE_TYPES
            or name in seen_names
        ):
            _fail("declared bodyless frozen static field semantics are invalid")
        if _FORBIDDEN_KEY_RE.fullmatch(_normalized_public_key(name)):
            _fail("declared bodyless frozen static field is prohibited")
        seen_names.add(name)
        fields.append(
            _FrozenStaticField(
                name=name,
                ordinal=field_ordinal,
                projected=projected,
                sample_type=sample_type,
            )
        )
    return tuple(fields)


def _projection_presence_kind(value: object) -> str:
    if value is None:
        return "null"
    if type(value) is list and not value:
        return "empty_array"
    if type(value) is dict and not value:
        return "empty_object"
    return "present"


def _projection_value_kind(value: object) -> str:
    if value is None:
        return "null"
    if type(value) is bool:
        return "boolean"
    if type(value) is int:
        return "integer"
    if type(value) is float:
        return "number"
    if type(value) is str:
        return "string"
    if type(value) is list:
        return "array"
    if type(value) is dict:
        return "object"
    _fail("declared bodyless static value has a foreign type")


def rederive_declared_bodyless_packet_projection(
    *,
    packet_bytes: bytes,
    frozen_static_schema_json: str,
    known_secrets: Sequence[str | bytes] = (),
) -> DeclaredBodylessPacketProjectionV1:
    """Reconstruct exact value roots without consulting a runtime registry."""

    fields = _decode_frozen_static_schema(
        frozen_static_schema_json,
        known_secrets=known_secrets,
    )
    decoded = decode_public_canonical_packet(packet_bytes, known_secrets=known_secrets)
    if type(decoded) is not list:
        _fail("declared bodyless static packet root must be an exact row array")
    raw_rows = cast("list[object]", decoded)
    if len(raw_rows) > _MAX_ROWS or any(type(row) is not list for row in raw_rows):
        _fail("declared bodyless static packet rows are invalid")
    rows = cast("list[list[object]]", raw_rows)
    if len(rows) * len(fields) > _MAX_CELLS:
        _fail("declared bodyless static packet exceeds its cell bound")

    field_sha256s = [
        _sha256_json(
            {
                "name": field.name,
                "ordinal": field.ordinal,
                "projected": field.projected,
                "sample_type": field.sample_type,
            }
        )
        for field in fields
    ]

    record_sha256s: list[str] = []
    cell_sha256s: list[str] = []
    value_duplicates: Counter[tuple[int, str]] = Counter()
    record_duplicates: Counter[str] = Counter()
    for record_ordinal, row in enumerate(rows):
        if len(row) != len(fields):
            _fail("declared bodyless static row width differs from its frozen schema")
        for field, value in zip(fields, row, strict=True):
            if type(value).__name__ != field.sample_type:
                _fail("declared bodyless static value type differs from its frozen schema")
        if not row or type(row[0]) is not int or row[0] <= 0:
            _fail("declared bodyless static identifier is invalid")

        start = len(cell_sha256s)
        for field, value in zip(fields, row, strict=True):
            canonical_value = _canonical_json_bytes(
                value,
                maximum=MAX_DECLARED_BODYLESS_PACKET_BYTES,
            ).decode("utf-8")
            value_sha256 = _sha256_bytes(canonical_value.encode("utf-8"))
            duplicate_value_ordinal = value_duplicates[(field.ordinal, value_sha256)]
            value_duplicates[(field.ordinal, value_sha256)] += 1
            cell_sha256s.append(
                _sha256_json(
                    {
                        "canonical_json": canonical_value,
                        "cell_ordinal": len(cell_sha256s),
                        "duplicate_value_ordinal": duplicate_value_ordinal,
                        "field_name": field.name,
                        "field_ordinal": field.ordinal,
                        "presence_kind": _projection_presence_kind(value),
                        "record_ordinal": record_ordinal,
                        "value_kind": _projection_value_kind(value),
                        "value_sha256": value_sha256,
                    },
                    maximum=MAX_DECLARED_BODYLESS_PACKET_BYTES,
                )
            )

        values_sha256 = _sha256_json(row, maximum=MAX_DECLARED_BODYLESS_PACKET_BYTES)
        duplicate_record_ordinal = record_duplicates[values_sha256]
        record_duplicates[values_sha256] += 1
        record_sha256s.append(
            _sha256_json(
                {
                    "cell_count": len(fields),
                    "cell_start_ordinal": start,
                    "container_value_count": sum(type(value) in {list, dict} for value in row),
                    "duplicate_record_ordinal": duplicate_record_ordinal,
                    "identifier": row[0],
                    "missing_value_count": 0,
                    "null_value_count": sum(value is None for value in row),
                    "present_empty_value_count": sum(
                        (type(value) is list and not value) or (type(value) is dict and not value)
                        for value in row
                    ),
                    "record_ordinal": record_ordinal,
                    "scalar_value_count": sum(
                        type(value) in {bool, int, float, str} for value in row
                    ),
                    "values_sha256": values_sha256,
                }
            )
        )

    headers = [field.name for field in fields]
    return DeclaredBodylessPacketProjectionV1(
        field_count=len(fields),
        row_count=len(rows),
        cell_count=len(cell_sha256s),
        schema_root_sha256=_ordered_sha256_root(field_sha256s),
        content_root_sha256=_sha256_json(
            {"headers": headers, "rows": rows},
            maximum=MAX_DECLARED_BODYLESS_PACKET_BYTES + MAX_DECLARED_BODYLESS_SCHEMA_BYTES,
        ),
        row_root_sha256=_ordered_sha256_root(record_sha256s),
        cell_root_sha256=_ordered_sha256_root(cell_sha256s),
    )


def _packet_identity(value: DeclaredBodylessPacketV1) -> dict[str, object]:
    return {
        "attempt_sha256": value.attempt_sha256,
        "cell_count": value.cell_count,
        "cell_root_sha256": value.cell_root_sha256,
        "chain_id": value.chain_id,
        "codec_contract_id": value.codec_contract_id,
        "codec_contract_sha256": value.codec_contract_sha256,
        "content_root_sha256": value.content_root_sha256,
        "encoding_id": value.encoding_id,
        "endpoint_contract_sha256": value.endpoint_contract_sha256,
        "endpoint_id": value.endpoint_id,
        "field_count": value.field_count,
        "frozen_static_schema_json": value.frozen_static_schema_json,
        "frozen_static_schema_sha256": value.frozen_static_schema_sha256,
        "kind": value.kind,
        "lane_id": value.lane_id,
        "logical_receipt_sha256": value.logical_receipt_sha256,
        "media_type": value.media_type,
        "observation_record_sha256": value.observation_record_sha256,
        "observation_sha256": value.observation_sha256,
        "provider_authority_sha256": value.provider_authority_sha256,
        "public_resource_name": value.public_resource_name,
        "representation_id": value.representation_id,
        "row_count": value.row_count,
        "row_root_sha256": value.row_root_sha256,
        "run_attempt": value.run_attempt,
        "run_id": value.run_id,
        "schema_root_sha256": value.schema_root_sha256,
        "schema_version": value.schema_version,
        "source_sha": value.source_sha,
        "stored_payload_length": value.stored_payload_length,
        "stored_payload_sha256": value.stored_payload_sha256,
        "uncompressed_packet_length": value.uncompressed_packet_length,
        "uncompressed_packet_sha256": value.uncompressed_packet_sha256,
    }


@dataclass(frozen=True, slots=True)
class DeclaredBodylessPacketV1:
    """One selected static observation bound to exact canonical packet bytes."""

    schema_version: int
    kind: str
    observation_sha256: str
    observation_record_sha256: str
    attempt_sha256: str
    logical_receipt_sha256: str
    endpoint_id: str
    endpoint_contract_sha256: str
    provider_authority_sha256: str
    public_resource_name: str
    frozen_static_schema_json: str
    frozen_static_schema_sha256: str
    source_sha: str
    run_id: int
    run_attempt: int
    chain_id: str
    lane_id: str
    representation_id: str
    media_type: str
    encoding_id: str
    codec_contract_id: str
    codec_contract_sha256: str
    uncompressed_packet_sha256: str
    uncompressed_packet_length: int
    stored_payload_sha256: str
    stored_payload_length: int
    field_count: int
    row_count: int
    cell_count: int
    schema_root_sha256: str
    content_root_sha256: str
    row_root_sha256: str
    cell_root_sha256: str
    packet_authority_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != DECLARED_BODYLESS_PACKET_SCHEMA_VERSION
            or type(self.kind) is not str
            or self.kind != DECLARED_BODYLESS_PACKET_KIND
            or type(self.representation_id) is not str
            or self.representation_id != DECLARED_BODYLESS_PACKET_REPRESENTATION_ID
            or type(self.media_type) is not str
            or self.media_type != DECLARED_BODYLESS_PACKET_MEDIA_TYPE
            or type(self.encoding_id) is not str
            or self.encoding_id != DECLARED_BODYLESS_PACKET_ENCODING_ID
            or type(self.codec_contract_id) is not str
            or self.codec_contract_id != DECLARED_BODYLESS_PACKET_CODEC_ID
            or type(self.codec_contract_sha256) is not str
            or self.codec_contract_sha256 != DECLARED_BODYLESS_PACKET_CODEC_CONTRACT_SHA256
        ):
            _fail("declared bodyless packet contract identity is invalid")
        for value, label in (
            (self.observation_sha256, "packet observation identity"),
            (self.observation_record_sha256, "packet observation record"),
            (self.attempt_sha256, "packet attempt identity"),
            (self.logical_receipt_sha256, "packet logical receipt"),
            (self.endpoint_contract_sha256, "packet endpoint contract"),
            (self.provider_authority_sha256, "packet provider authority"),
            (self.frozen_static_schema_sha256, "packet frozen static schema"),
            (self.uncompressed_packet_sha256, "packet uncompressed digest"),
            (self.stored_payload_sha256, "packet stored digest"),
            (self.schema_root_sha256, "packet schema root"),
            (self.content_root_sha256, "packet content root"),
            (self.row_root_sha256, "packet row root"),
            (self.cell_root_sha256, "packet cell root"),
            (self.packet_authority_sha256, "packet authority"),
        ):
            _exact_sha256(value, label=label)
        _exact_source_sha(self.source_sha)
        for value, label in (
            (self.endpoint_id, "packet endpoint"),
            (self.chain_id, "packet chain"),
            (self.lane_id, "packet lane"),
        ):
            _exact_safe_id(value, label=label)
        for value, label, maximum, minimum in (
            (self.run_id, "packet run ID", _MAX_INT64, 1),
            (self.run_attempt, "packet run attempt", _MAX_INT64, 1),
            (
                self.uncompressed_packet_length,
                "packet uncompressed length",
                MAX_DECLARED_BODYLESS_PACKET_BYTES,
                1,
            ),
            (
                self.stored_payload_length,
                "packet stored length",
                MAX_DECLARED_BODYLESS_PACKET_BYTES,
                1,
            ),
            (self.field_count, "packet field count", _MAX_FIELDS, 1),
            (self.row_count, "packet row count", _MAX_ROWS, 0),
            (self.cell_count, "packet cell count", _MAX_CELLS, 0),
        ):
            _exact_integer(value, label=label, maximum=maximum, minimum=minimum)
        fields = _decode_frozen_static_schema(self.frozen_static_schema_json)
        schema_root_sha256 = _ordered_sha256_root(
            [
                _sha256_json(
                    {
                        "name": field.name,
                        "ordinal": field.ordinal,
                        "projected": field.projected,
                        "sample_type": field.sample_type,
                    }
                )
                for field in fields
            ]
        )
        if (
            self.observation_sha256 != self.attempt_sha256
            or self.frozen_static_schema_sha256
            != _sha256_bytes(self.frozen_static_schema_json.encode("utf-8"))
            or self.field_count != len(fields)
            or self.schema_root_sha256 != schema_root_sha256
            or type(self.public_resource_name) is not str
            or self.public_resource_name
            != f"{DECLARED_BODYLESS_PACKET_RESOURCE_PREFIX}{self.uncompressed_packet_sha256}.json"
            or self.stored_payload_sha256 != self.uncompressed_packet_sha256
            or self.stored_payload_length != self.uncompressed_packet_length
            or self.cell_count != self.field_count * self.row_count
            or self.packet_authority_sha256 != _sha256_json(_packet_identity(self))
        ):
            _fail("declared bodyless packet identity is inconsistent")

    @classmethod
    def build(
        cls,
        *,
        observation_sha256: str,
        observation_record_sha256: str,
        attempt_sha256: str,
        logical_receipt_sha256: str,
        endpoint_id: str,
        endpoint_contract_sha256: str,
        provider_authority_sha256: str,
        frozen_static_schema_json: str,
        source_sha: str,
        run_id: int,
        run_attempt: int,
        chain_id: str,
        lane_id: str,
        packet_bytes: bytes,
        expected_observation_sha256: str,
        expected_observation_record_sha256: str,
        known_secrets: Sequence[str | bytes] = (),
    ) -> DeclaredBodylessPacketV1:
        """Build from already admitted scalar observation and frozen-schema inputs."""

        if cls is not DeclaredBodylessPacketV1:
            _fail("declared bodyless packet has a foreign DTO type")
        expected_observation = _exact_sha256(
            expected_observation_sha256,
            label="expected observation identity",
        )
        expected_observation_record = _exact_sha256(
            expected_observation_record_sha256,
            label="expected observation record",
        )
        observation = _exact_sha256(observation_sha256, label="packet observation identity")
        observation_record = _exact_sha256(
            observation_record_sha256,
            label="packet observation record",
        )
        attempt = _exact_sha256(attempt_sha256, label="packet attempt identity")
        _exact_sha256(logical_receipt_sha256, label="packet logical receipt")
        _exact_sha256(endpoint_contract_sha256, label="packet endpoint contract")
        _exact_sha256(provider_authority_sha256, label="packet provider authority")
        _exact_safe_id(endpoint_id, label="packet endpoint")
        _exact_safe_id(chain_id, label="packet chain")
        _exact_safe_id(lane_id, label="packet lane")
        _exact_source_sha(source_sha)
        _exact_integer(run_id, label="packet run ID", maximum=_MAX_INT64, minimum=1)
        _exact_integer(run_attempt, label="packet run attempt", maximum=_MAX_INT64, minimum=1)
        if type(packet_bytes) is not bytes:
            _fail("declared bodyless packet must be exact built-in bytes")
        secret_bytes = _admitted_secret_bytes(known_secrets)
        if (
            observation != expected_observation
            or observation_record != expected_observation_record
            or attempt != observation
        ):
            _fail("declared bodyless packet differs from its external observation authority")

        projection = rederive_declared_bodyless_packet_projection(
            packet_bytes=packet_bytes,
            frozen_static_schema_json=frozen_static_schema_json,
            known_secrets=known_secrets,
        )
        packet_sha256 = _sha256_bytes(packet_bytes)
        payload = {
            "attempt_sha256": attempt,
            "cell_count": projection.cell_count,
            "cell_root_sha256": projection.cell_root_sha256,
            "chain_id": chain_id,
            "codec_contract_id": DECLARED_BODYLESS_PACKET_CODEC_ID,
            "codec_contract_sha256": DECLARED_BODYLESS_PACKET_CODEC_CONTRACT_SHA256,
            "content_root_sha256": projection.content_root_sha256,
            "encoding_id": DECLARED_BODYLESS_PACKET_ENCODING_ID,
            "endpoint_contract_sha256": endpoint_contract_sha256,
            "endpoint_id": endpoint_id,
            "field_count": projection.field_count,
            "frozen_static_schema_json": frozen_static_schema_json,
            "frozen_static_schema_sha256": _sha256_bytes(frozen_static_schema_json.encode("utf-8")),
            "kind": DECLARED_BODYLESS_PACKET_KIND,
            "lane_id": lane_id,
            "logical_receipt_sha256": logical_receipt_sha256,
            "media_type": DECLARED_BODYLESS_PACKET_MEDIA_TYPE,
            "observation_record_sha256": observation_record,
            "observation_sha256": observation,
            "provider_authority_sha256": provider_authority_sha256,
            "public_resource_name": (
                f"{DECLARED_BODYLESS_PACKET_RESOURCE_PREFIX}{packet_sha256}.json"
            ),
            "representation_id": DECLARED_BODYLESS_PACKET_REPRESENTATION_ID,
            "row_count": projection.row_count,
            "row_root_sha256": projection.row_root_sha256,
            "run_attempt": run_attempt,
            "run_id": run_id,
            "schema_root_sha256": projection.schema_root_sha256,
            "schema_version": DECLARED_BODYLESS_PACKET_SCHEMA_VERSION,
            "source_sha": source_sha,
            "stored_payload_length": len(packet_bytes),
            "stored_payload_sha256": packet_sha256,
            "uncompressed_packet_length": len(packet_bytes),
            "uncompressed_packet_sha256": packet_sha256,
        }
        _scan_public_value(payload, secret_bytes=secret_bytes)
        return DeclaredBodylessPacketV1(
            **payload,
            packet_authority_sha256=_sha256_json(payload),
        )

    def to_row(self) -> dict[str, object]:
        try:
            return {field: getattr(self, field) for field in _PACKET_ROW_FIELDS}
        except AttributeError:
            _fail("declared bodyless packet fields are invalid")

    def to_canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_row(), maximum=_MAX_IDENTITY_BYTES)

    @classmethod
    def from_row(
        cls,
        value: object,
        *,
        packet_bytes: bytes,
        expected_observation_sha256: str,
        expected_observation_record_sha256: str,
        expected_packet_authority_sha256: str,
        known_secrets: Sequence[str | bytes] = (),
    ) -> DeclaredBodylessPacketV1:
        if cls is not DeclaredBodylessPacketV1:
            _fail("declared bodyless packet has a foreign DTO type")
        _exact_sha256(expected_observation_sha256, label="expected observation identity")
        _exact_sha256(expected_observation_record_sha256, label="expected observation record")
        _exact_sha256(expected_packet_authority_sha256, label="expected packet authority")
        if type(packet_bytes) is not bytes:
            _fail("declared bodyless packet must be exact built-in bytes")
        secret_bytes = _admitted_secret_bytes(known_secrets)
        row = _strict_row(
            value,
            expected_fields=_PACKET_ROW_FIELDS,
            label="declared bodyless packet",
        )
        _scan_public_value(row, secret_bytes=secret_bytes)
        candidate = _packet_from_mapping(
            row,
            expected_packet_authority_sha256=expected_packet_authority_sha256,
        )
        return validate_declared_bodyless_packet_bytes(
            candidate,
            packet_bytes=packet_bytes,
            expected_observation_sha256=expected_observation_sha256,
            expected_observation_record_sha256=expected_observation_record_sha256,
            expected_packet_authority_sha256=expected_packet_authority_sha256,
            known_secrets=known_secrets,
        )

    @classmethod
    def from_canonical_bytes(
        cls,
        encoded: bytes,
        *,
        packet_bytes: bytes,
        expected_observation_sha256: str,
        expected_observation_record_sha256: str,
        expected_packet_authority_sha256: str,
        known_secrets: Sequence[str | bytes] = (),
    ) -> DeclaredBodylessPacketV1:
        if cls is not DeclaredBodylessPacketV1:
            _fail("declared bodyless packet has a foreign DTO type")
        _exact_sha256(expected_observation_sha256, label="expected observation identity")
        _exact_sha256(expected_observation_record_sha256, label="expected observation record")
        _exact_sha256(expected_packet_authority_sha256, label="expected packet authority")
        if type(packet_bytes) is not bytes:
            _fail("declared bodyless packet must be exact built-in bytes")
        _admitted_secret_bytes(known_secrets)
        if type(encoded) is not bytes or not encoded or len(encoded) > _MAX_IDENTITY_BYTES:
            _fail("declared bodyless packet identity bytes exceed their exact bound")
        payload = decode_public_canonical_packet(encoded, known_secrets=known_secrets)
        row = _strict_canonical_object(
            payload,
            expected_fields=_PACKET_ROW_FIELDS,
            label="declared bodyless packet",
        )
        candidate = _packet_from_mapping(
            row,
            expected_packet_authority_sha256=expected_packet_authority_sha256,
        )
        if encoded != candidate.to_canonical_bytes():
            _fail("declared bodyless packet identity bytes are noncanonical")
        return validate_declared_bodyless_packet_bytes(
            candidate,
            packet_bytes=packet_bytes,
            expected_observation_sha256=expected_observation_sha256,
            expected_observation_record_sha256=expected_observation_record_sha256,
            expected_packet_authority_sha256=expected_packet_authority_sha256,
            known_secrets=known_secrets,
        )


def _packet_from_mapping(
    row: dict[str, object],
    *,
    expected_packet_authority_sha256: str,
) -> DeclaredBodylessPacketV1:
    expected_authority = _exact_sha256(
        expected_packet_authority_sha256,
        label="expected packet authority",
    )
    encoded_authority = _exact_sha256(
        row.get("packet_authority_sha256"),
        label="encoded packet authority",
    )
    if encoded_authority != expected_authority:
        _fail("declared bodyless packet differs from its external authority")
    try:
        return DeclaredBodylessPacketV1(**cast("dict[str, Any]", row))
    except DeclaredBodylessPacketError:
        raise
    except (AttributeError, TypeError, ValueError):
        _fail("declared bodyless packet identity fields are invalid")


def _readback_identity(value: DeclaredBodylessPacketReadbackReceiptV1) -> dict[str, object]:
    return {
        "cell_count": value.cell_count,
        "cell_root_sha256": value.cell_root_sha256,
        "content_root_sha256": value.content_root_sha256,
        "field_count": value.field_count,
        "frozen_static_schema_sha256": value.frozen_static_schema_sha256,
        "kind": value.kind,
        "observation_record_sha256": value.observation_record_sha256,
        "observation_sha256": value.observation_sha256,
        "packet_authority_sha256": value.packet_authority_sha256,
        "public_resource_name": value.public_resource_name,
        "readback_payload_length": value.readback_payload_length,
        "readback_payload_sha256": value.readback_payload_sha256,
        "row_count": value.row_count,
        "row_root_sha256": value.row_root_sha256,
        "schema_root_sha256": value.schema_root_sha256,
        "schema_version": value.schema_version,
        "store_namespace_sha256": value.store_namespace_sha256,
        "stored_payload_length": value.stored_payload_length,
        "stored_payload_sha256": value.stored_payload_sha256,
    }


@dataclass(frozen=True, slots=True)
class DeclaredBodylessPacketReadbackReceiptV1:
    """Path-free proof that exact immutable packet bytes were read back."""

    schema_version: int
    kind: str
    observation_sha256: str
    observation_record_sha256: str
    packet_authority_sha256: str
    public_resource_name: str
    frozen_static_schema_sha256: str
    store_namespace_sha256: str
    stored_payload_sha256: str
    stored_payload_length: int
    readback_payload_sha256: str
    readback_payload_length: int
    field_count: int
    row_count: int
    cell_count: int
    schema_root_sha256: str
    content_root_sha256: str
    row_root_sha256: str
    cell_root_sha256: str
    receipt_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != DECLARED_BODYLESS_PACKET_SCHEMA_VERSION
            or type(self.kind) is not str
            or self.kind != DECLARED_BODYLESS_PACKET_RECEIPT_KIND
        ):
            _fail("declared bodyless readback contract identity is invalid")
        for value, label in (
            (self.observation_sha256, "readback observation identity"),
            (self.observation_record_sha256, "readback observation record"),
            (self.packet_authority_sha256, "readback packet authority"),
            (self.frozen_static_schema_sha256, "readback frozen static schema"),
            (self.store_namespace_sha256, "readback store namespace"),
            (self.stored_payload_sha256, "readback stored payload"),
            (self.readback_payload_sha256, "readback payload"),
            (self.schema_root_sha256, "readback schema root"),
            (self.content_root_sha256, "readback content root"),
            (self.row_root_sha256, "readback row root"),
            (self.cell_root_sha256, "readback cell root"),
            (self.receipt_sha256, "readback receipt"),
        ):
            _exact_sha256(value, label=label)
        for value, label in (
            (self.stored_payload_length, "readback stored length"),
            (self.readback_payload_length, "readback byte length"),
        ):
            _exact_integer(
                value,
                label=label,
                maximum=MAX_DECLARED_BODYLESS_PACKET_BYTES,
                minimum=1,
            )
        _exact_integer(
            self.field_count,
            label="readback field count",
            maximum=_MAX_FIELDS,
            minimum=1,
        )
        _exact_integer(self.row_count, label="readback row count", maximum=_MAX_ROWS)
        _exact_integer(self.cell_count, label="readback cell count", maximum=_MAX_CELLS)
        if (
            self.stored_payload_sha256 != self.readback_payload_sha256
            or self.stored_payload_length != self.readback_payload_length
            or self.cell_count != self.field_count * self.row_count
            or type(self.public_resource_name) is not str
            or self.public_resource_name
            != f"{DECLARED_BODYLESS_PACKET_RESOURCE_PREFIX}{self.stored_payload_sha256}.json"
            or self.receipt_sha256 != _sha256_json(_readback_identity(self))
        ):
            _fail("declared bodyless readback identity is inconsistent")

    @classmethod
    def build(
        cls,
        *,
        packet: DeclaredBodylessPacketV1,
        readback_bytes: bytes,
        store_namespace_sha256: str,
        expected_packet_authority_sha256: str,
        known_secrets: Sequence[str | bytes] = (),
    ) -> DeclaredBodylessPacketReadbackReceiptV1:
        if cls is not DeclaredBodylessPacketReadbackReceiptV1:
            _fail("declared bodyless readback receipt has a foreign DTO type")
        store_namespace = _exact_sha256(
            store_namespace_sha256,
            label="expected store namespace",
        )
        expected_authority = _exact_sha256(
            expected_packet_authority_sha256,
            label="expected packet authority",
        )
        secret_bytes = _admitted_secret_bytes(known_secrets)
        if type(packet) is not DeclaredBodylessPacketV1:
            _fail("declared bodyless packet has a foreign type")
        if type(readback_bytes) is not bytes:
            _fail("declared bodyless readback must be exact built-in bytes")
        try:
            observation_sha256 = packet.observation_sha256
            observation_record_sha256 = packet.observation_record_sha256
        except AttributeError:
            _fail("declared bodyless packet fields are invalid")
        validated = validate_declared_bodyless_packet_bytes(
            packet,
            packet_bytes=readback_bytes,
            expected_observation_sha256=_exact_sha256(
                observation_sha256,
                label="readback packet observation identity",
            ),
            expected_observation_record_sha256=_exact_sha256(
                observation_record_sha256,
                label="readback packet observation record",
            ),
            expected_packet_authority_sha256=expected_authority,
            known_secrets=known_secrets,
        )
        payload = {
            "cell_count": validated.cell_count,
            "cell_root_sha256": validated.cell_root_sha256,
            "content_root_sha256": validated.content_root_sha256,
            "field_count": validated.field_count,
            "frozen_static_schema_sha256": validated.frozen_static_schema_sha256,
            "kind": DECLARED_BODYLESS_PACKET_RECEIPT_KIND,
            "observation_record_sha256": validated.observation_record_sha256,
            "observation_sha256": validated.observation_sha256,
            "packet_authority_sha256": validated.packet_authority_sha256,
            "public_resource_name": validated.public_resource_name,
            "readback_payload_length": len(readback_bytes),
            "readback_payload_sha256": _sha256_bytes(readback_bytes),
            "row_count": validated.row_count,
            "row_root_sha256": validated.row_root_sha256,
            "schema_root_sha256": validated.schema_root_sha256,
            "schema_version": DECLARED_BODYLESS_PACKET_SCHEMA_VERSION,
            "store_namespace_sha256": store_namespace,
            "stored_payload_length": validated.stored_payload_length,
            "stored_payload_sha256": validated.stored_payload_sha256,
        }
        _scan_public_value(payload, secret_bytes=secret_bytes)
        return DeclaredBodylessPacketReadbackReceiptV1(
            **payload,
            receipt_sha256=_sha256_json(payload),
        )

    def to_row(self) -> dict[str, object]:
        try:
            return {field: getattr(self, field) for field in _READBACK_ROW_FIELDS}
        except AttributeError:
            _fail("declared bodyless readback receipt fields are invalid")

    def to_canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_row(), maximum=_MAX_IDENTITY_BYTES)

    @classmethod
    def from_row(
        cls,
        value: object,
        *,
        packet: DeclaredBodylessPacketV1,
        readback_bytes: bytes,
        store_namespace_sha256: str,
        expected_packet_authority_sha256: str,
        expected_receipt_sha256: str,
        known_secrets: Sequence[str | bytes] = (),
    ) -> DeclaredBodylessPacketReadbackReceiptV1:
        if cls is not DeclaredBodylessPacketReadbackReceiptV1:
            _fail("declared bodyless readback receipt has a foreign DTO type")
        _exact_sha256(store_namespace_sha256, label="expected store namespace")
        _exact_sha256(expected_packet_authority_sha256, label="expected packet authority")
        _exact_sha256(expected_receipt_sha256, label="expected readback receipt")
        secret_bytes = _admitted_secret_bytes(known_secrets)
        if type(packet) is not DeclaredBodylessPacketV1:
            _fail("declared bodyless packet has a foreign type")
        if type(readback_bytes) is not bytes:
            _fail("declared bodyless readback must be exact built-in bytes")
        row = _strict_row(
            value,
            expected_fields=_READBACK_ROW_FIELDS,
            label="declared bodyless readback receipt",
        )
        _scan_public_value(row, secret_bytes=secret_bytes)
        candidate = _readback_from_mapping(
            row,
            expected_receipt_sha256=expected_receipt_sha256,
        )
        return validate_declared_bodyless_packet_readback_receipt(
            candidate,
            packet=packet,
            readback_bytes=readback_bytes,
            store_namespace_sha256=store_namespace_sha256,
            expected_packet_authority_sha256=expected_packet_authority_sha256,
            expected_receipt_sha256=expected_receipt_sha256,
            known_secrets=known_secrets,
        )

    @classmethod
    def from_canonical_bytes(
        cls,
        encoded: bytes,
        *,
        packet: DeclaredBodylessPacketV1,
        readback_bytes: bytes,
        store_namespace_sha256: str,
        expected_packet_authority_sha256: str,
        expected_receipt_sha256: str,
        known_secrets: Sequence[str | bytes] = (),
    ) -> DeclaredBodylessPacketReadbackReceiptV1:
        if cls is not DeclaredBodylessPacketReadbackReceiptV1:
            _fail("declared bodyless readback receipt has a foreign DTO type")
        _exact_sha256(store_namespace_sha256, label="expected store namespace")
        _exact_sha256(expected_packet_authority_sha256, label="expected packet authority")
        _exact_sha256(expected_receipt_sha256, label="expected readback receipt")
        _admitted_secret_bytes(known_secrets)
        if type(packet) is not DeclaredBodylessPacketV1:
            _fail("declared bodyless packet has a foreign type")
        if type(readback_bytes) is not bytes:
            _fail("declared bodyless readback must be exact built-in bytes")
        if type(encoded) is not bytes or not encoded or len(encoded) > _MAX_IDENTITY_BYTES:
            _fail("declared bodyless readback receipt bytes exceed their exact bound")
        payload = decode_public_canonical_packet(encoded, known_secrets=known_secrets)
        row = _strict_canonical_object(
            payload,
            expected_fields=_READBACK_ROW_FIELDS,
            label="declared bodyless readback receipt",
        )
        candidate = _readback_from_mapping(
            row,
            expected_receipt_sha256=expected_receipt_sha256,
        )
        if encoded != candidate.to_canonical_bytes():
            _fail("declared bodyless readback receipt bytes are noncanonical")
        return validate_declared_bodyless_packet_readback_receipt(
            candidate,
            packet=packet,
            readback_bytes=readback_bytes,
            store_namespace_sha256=store_namespace_sha256,
            expected_packet_authority_sha256=expected_packet_authority_sha256,
            expected_receipt_sha256=expected_receipt_sha256,
            known_secrets=known_secrets,
        )


def _readback_from_mapping(
    row: dict[str, object],
    *,
    expected_receipt_sha256: str,
) -> DeclaredBodylessPacketReadbackReceiptV1:
    expected_receipt = _exact_sha256(
        expected_receipt_sha256,
        label="expected readback receipt",
    )
    encoded_receipt = _exact_sha256(
        row.get("receipt_sha256"),
        label="encoded readback receipt",
    )
    if encoded_receipt != expected_receipt:
        _fail("declared bodyless readback receipt differs from exact reconstruction")
    try:
        return DeclaredBodylessPacketReadbackReceiptV1(**cast("dict[str, Any]", row))
    except DeclaredBodylessPacketError:
        raise
    except (AttributeError, TypeError, ValueError):
        _fail("declared bodyless readback receipt fields are invalid")


def _packet_storage_identity(packet: DeclaredBodylessPacketV1) -> tuple[str, int, str]:
    try:
        packet_authority = packet.packet_authority_sha256
        stored_length = packet.stored_payload_length
        stored_sha256 = packet.stored_payload_sha256
    except AttributeError:
        _fail("declared bodyless packet fields are invalid")
    return (
        _exact_sha256(packet_authority, label="candidate packet authority"),
        _exact_integer(
            stored_length,
            label="candidate stored packet length",
            maximum=MAX_DECLARED_BODYLESS_PACKET_BYTES,
            minimum=1,
        ),
        _exact_sha256(stored_sha256, label="candidate stored packet digest"),
    )


def _rebuild_packet(value: DeclaredBodylessPacketV1) -> DeclaredBodylessPacketV1:
    try:
        return replace(value)
    except DeclaredBodylessPacketError:
        raise
    except (AttributeError, TypeError, ValueError):
        _fail("declared bodyless packet fields are invalid")


def _rebuild_readback(
    value: DeclaredBodylessPacketReadbackReceiptV1,
) -> DeclaredBodylessPacketReadbackReceiptV1:
    try:
        return replace(value)
    except DeclaredBodylessPacketError:
        raise
    except (AttributeError, TypeError, ValueError):
        _fail("declared bodyless readback receipt fields are invalid")


def validate_declared_bodyless_packet_identity(
    value: object,
    *,
    expected_packet_authority_sha256: str,
) -> DeclaredBodylessPacketV1:
    """Reconstruct one sealed packet identity against an external authority pin."""

    expected_authority = _exact_sha256(
        expected_packet_authority_sha256,
        label="expected packet authority",
    )
    if type(value) is not DeclaredBodylessPacketV1:
        _fail("declared bodyless packet has a foreign type")
    try:
        candidate_authority_value = value.packet_authority_sha256
    except AttributeError:
        _fail("declared bodyless packet fields are invalid")
    candidate_authority = _exact_sha256(
        candidate_authority_value,
        label="candidate packet authority",
    )
    if candidate_authority != expected_authority:
        _fail("declared bodyless packet differs from its external authority")
    return _rebuild_packet(value)


def validate_declared_bodyless_packet_bytes(
    value: object,
    *,
    packet_bytes: bytes,
    expected_observation_sha256: str,
    expected_observation_record_sha256: str,
    expected_packet_authority_sha256: str,
    known_secrets: Sequence[str | bytes] = (),
) -> DeclaredBodylessPacketV1:
    """Validate one frozen packet DTO and exact bytes without mutable registries."""

    expected_observation = _exact_sha256(
        expected_observation_sha256,
        label="expected observation identity",
    )
    expected_observation_record = _exact_sha256(
        expected_observation_record_sha256,
        label="expected observation record",
    )
    expected_authority = _exact_sha256(
        expected_packet_authority_sha256,
        label="expected packet authority",
    )
    if type(value) is not DeclaredBodylessPacketV1:
        _fail("declared bodyless packet has a foreign type")
    if type(packet_bytes) is not bytes:
        _fail("declared bodyless packet must be exact built-in bytes")
    secret_bytes = _admitted_secret_bytes(known_secrets)
    try:
        candidate_authority_value = value.packet_authority_sha256
        candidate_observation_value = value.observation_sha256
        candidate_observation_record_value = value.observation_record_sha256
        uncompressed_length_value = value.uncompressed_packet_length
        stored_length_value = value.stored_payload_length
        uncompressed_sha256_value = value.uncompressed_packet_sha256
        stored_sha256_value = value.stored_payload_sha256
    except AttributeError:
        _fail("declared bodyless packet fields are invalid")
    candidate_authority = _exact_sha256(
        candidate_authority_value,
        label="candidate packet authority",
    )
    candidate_observation = _exact_sha256(
        candidate_observation_value,
        label="candidate observation identity",
    )
    candidate_observation_record = _exact_sha256(
        candidate_observation_record_value,
        label="candidate observation record",
    )
    uncompressed_length = _exact_integer(
        uncompressed_length_value,
        label="candidate uncompressed packet length",
        maximum=MAX_DECLARED_BODYLESS_PACKET_BYTES,
        minimum=1,
    )
    stored_length = _exact_integer(
        stored_length_value,
        label="candidate stored packet length",
        maximum=MAX_DECLARED_BODYLESS_PACKET_BYTES,
        minimum=1,
    )
    uncompressed_sha256 = _exact_sha256(
        uncompressed_sha256_value,
        label="candidate uncompressed packet digest",
    )
    stored_sha256 = _exact_sha256(
        stored_sha256_value,
        label="candidate stored packet digest",
    )
    if (
        candidate_authority != expected_authority
        or candidate_observation != expected_observation
        or candidate_observation_record != expected_observation_record
        or len(packet_bytes) != uncompressed_length
        or len(packet_bytes) != stored_length
    ):
        _fail("declared bodyless packet bytes differ from frozen authority")
    packet_sha256 = _sha256_bytes(packet_bytes)
    if packet_sha256 != uncompressed_sha256 or packet_sha256 != stored_sha256:
        _fail("declared bodyless packet bytes differ from frozen authority")
    candidate = validate_declared_bodyless_packet_identity(
        value,
        expected_packet_authority_sha256=expected_authority,
    )
    _scan_public_value(candidate.to_row(), secret_bytes=secret_bytes)
    projection = rederive_declared_bodyless_packet_projection(
        packet_bytes=packet_bytes,
        frozen_static_schema_json=candidate.frozen_static_schema_json,
        known_secrets=known_secrets,
    )
    if (
        candidate.field_count != projection.field_count
        or candidate.row_count != projection.row_count
        or candidate.cell_count != projection.cell_count
        or candidate.schema_root_sha256 != projection.schema_root_sha256
        or candidate.content_root_sha256 != projection.content_root_sha256
        or candidate.row_root_sha256 != projection.row_root_sha256
        or candidate.cell_root_sha256 != projection.cell_root_sha256
    ):
        _fail("declared bodyless packet bytes differ from frozen authority")
    return candidate


def validate_declared_bodyless_packet_readback_receipt(
    value: object,
    *,
    packet: DeclaredBodylessPacketV1,
    readback_bytes: bytes,
    store_namespace_sha256: str,
    expected_packet_authority_sha256: str,
    expected_receipt_sha256: str,
    known_secrets: Sequence[str | bytes] = (),
) -> DeclaredBodylessPacketReadbackReceiptV1:
    """Rebuild one path-free receipt from exact public inputs."""

    store_namespace = _exact_sha256(
        store_namespace_sha256,
        label="expected store namespace",
    )
    expected_authority = _exact_sha256(
        expected_packet_authority_sha256,
        label="expected packet authority",
    )
    expected_receipt = _exact_sha256(
        expected_receipt_sha256,
        label="expected readback receipt",
    )
    _admitted_secret_bytes(known_secrets)
    if type(packet) is not DeclaredBodylessPacketV1:
        _fail("declared bodyless packet has a foreign type")
    if type(readback_bytes) is not bytes:
        _fail("declared bodyless readback must be exact built-in bytes")
    if type(value) is not DeclaredBodylessPacketReadbackReceiptV1:
        _fail("declared bodyless readback receipt has a foreign type")
    try:
        candidate_receipt_value = value.receipt_sha256
    except AttributeError:
        _fail("declared bodyless readback receipt fields are invalid")
    candidate_receipt = _exact_sha256(
        candidate_receipt_value,
        label="candidate readback receipt",
    )
    if candidate_receipt != expected_receipt:
        _fail("declared bodyless readback receipt differs from exact reconstruction")
    candidate = _rebuild_readback(value)
    rebuilt = DeclaredBodylessPacketReadbackReceiptV1.build(
        packet=packet,
        readback_bytes=readback_bytes,
        store_namespace_sha256=store_namespace,
        expected_packet_authority_sha256=expected_authority,
        known_secrets=known_secrets,
    )
    if candidate.to_canonical_bytes() != rebuilt.to_canonical_bytes():
        _fail("declared bodyless readback receipt differs from exact reconstruction")
    return rebuilt
