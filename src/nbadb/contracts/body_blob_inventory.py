"""Bundle-scoped public authority for exact Raw-v2 parser-input body blobs.

The DTOs in this module are path-free and filesystem-free.  They describe the
content-addressed objects and exact observation references which a separate
store must persist and read back.  Physical file operations deliberately live
outside this contract boundary.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields, replace
from typing import TYPE_CHECKING, Any, Final, Literal, Never, cast

if TYPE_CHECKING:
    from collections.abc import Sequence

from nbadb.contracts.raw_request_authority import (
    DETERMINISTIC_GZIP_CODEC,
    DETERMINISTIC_GZIP_CONTRACT_SHA256,
    MAX_AUTHORITY_ROWS,
    MAX_PARSER_INPUT_BYTES,
    MAX_PARSER_INPUT_STORED_BYTES,
    PUBLIC_PARSER_INPUT_REPRESENTATION,
    ParserInputObjectV2,
    RawRequestAuthorityBundleV2,
    RequestObservationV2,
    decode_parser_input_object,
    validate_parser_input_object,
    validate_raw_request_authority_bundle,
)
from nbadb.contracts.raw_request_observation_order import (
    RawRequestObservationOrderError,
    canonical_raw_request_observations,
)

__all__ = [
    "BODY_BLOB_AUTHORITY_SCHEMA_VERSION",
    "BODY_BLOB_RESOURCE_PREFIX",
    "MAX_BODY_BLOB_CANONICAL_BYTES",
    "BodyBlobAuthorityError",
    "BodyBlobDescriptorV1",
    "BodyBlobFileReadbackReceiptV1",
    "BodyBlobInventoryReadbackReceiptV1",
    "BodyBlobInventoryV1",
    "BodyBlobObservationReadbackReceiptV1",
    "BodyBlobObservationReferenceV1",
    "build_body_blob_inventory",
    "replay_body_blob_inventory",
    "validate_body_blob_inventory",
]

BODY_BLOB_AUTHORITY_SCHEMA_VERSION: Final = 1
BODY_BLOB_RESOURCE_PREFIX: Final = "body-blobs/sha256"
MAX_BODY_BLOB_CANONICAL_BYTES: Final = 128 * 1024 * 1024
MAX_BODY_BLOB_JSON_DEPTH: Final = 64
MAX_BODY_BLOB_JSON_NODES: Final = 2_000_000
MAX_BODY_BLOB_JSON_STRING_BYTES: Final = 4 * 1024 * 1024
MAX_BODY_BLOB_JSON_TOTAL_STRING_BYTES: Final = MAX_BODY_BLOB_CANONICAL_BYTES
MAX_BODY_BLOB_NUMBER_TOKEN_BYTES: Final = 128
MAX_BODY_BLOB_KNOWN_SECRETS: Final = 128
MAX_BODY_BLOB_KNOWN_SECRET_BYTES: Final = 4096

_DESCRIPTOR_KIND: Final = "nbadb_body_blob_descriptor_v1"
_REFERENCE_KIND: Final = "nbadb_body_blob_observation_reference_v1"
_INVENTORY_KIND: Final = "nbadb_body_blob_inventory_v1"
_FILE_READBACK_KIND: Final = "nbadb_body_blob_file_readback_receipt_v1"
_OBSERVATION_READBACK_KIND: Final = "nbadb_body_blob_observation_readback_receipt_v1"
_INVENTORY_READBACK_KIND: Final = "nbadb_body_blob_inventory_readback_receipt_v1"
_DESCRIPTOR_ROOT_KIND: Final = "nbadb_body_blob_descriptor_root_v1"
_REFERENCE_ROOT_KIND: Final = "nbadb_body_blob_observation_reference_root_v1"
_SELECTED_REFERENCE_ROOT_KIND: Final = "nbadb_body_blob_selected_reference_root_v1"
_INCOMPLETE_REFERENCE_ROOT_KIND: Final = "nbadb_body_blob_incomplete_reference_root_v1"
_FILE_READBACK_ROOT_KIND: Final = "nbadb_body_blob_file_readback_root_v1"
_OBSERVATION_READBACK_ROOT_KIND: Final = "nbadb_body_blob_observation_readback_root_v1"
_SELECTED_READBACK_ROOT_KIND: Final = "nbadb_body_blob_selected_readback_root_v1"
_INCOMPLETE_READBACK_ROOT_KIND: Final = "nbadb_body_blob_incomplete_readback_root_v1"
_MAX_ORDINAL: Final = 2**63 - 1

_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_AUTH_VALUE_RE: Final = re.compile(
    rb"(?i)(?:authorization\s*:\s*(?:bearer|basic)\s+"
    rb"[A-Za-z0-9._~+/=-]{8,}|\bbearer\s+[A-Za-z0-9._~+/=-]{12,}|"
    rb"\bbasic\s+[A-Za-z0-9+/=]{12,})"
)
_KNOWN_TOKEN_RE: Final = re.compile(
    rb"(?:gh[pousr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}|"
    rb"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"
)
_LOCAL_PATH_RE: Final = re.compile(
    rb"(?:/Users/[^/\x00\s]+(?=/|\s|\"|\Z)|"
    rb"/home/[^/\x00\s]+(?=/|\s|\"|\Z)|"
    rb"/private/var(?![A-Za-z0-9_])|[A-Za-z]:\\Users\\)"
)
_URL_USERINFO_RE: Final = re.compile(rb"(?i)https?://[^/\s:@]+:[^/\s@]+@")

BodyBlobReferenceSelection = Literal["selected_terminal", "downstream_incomplete"]


class BodyBlobAuthorityError(ValueError):
    """Raised when body-blob authority is unsafe, foreign, or inconsistent."""


def _fail(message: str) -> Never:
    raise BodyBlobAuthorityError(message)


def _exact_sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be one lowercase full SHA-256")
    return value


def _exact_integer(
    value: object,
    *,
    label: str,
    maximum: int = _MAX_ORDINAL,
    minimum: int = 0,
) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        _fail(f"{label} must be one bounded exact integer")
    return value


def _exact_text(value: object, *, label: str, maximum_bytes: int) -> str:
    if type(value) is not str:
        _fail(f"{label} must be exact text")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _fail(f"{label} must be strict UTF-8")
    if not encoded or len(encoded) > maximum_bytes:
        _fail(f"{label} violates its byte bound")
    return value


def _admitted_secret_bytes(known_secrets: Sequence[str | bytes]) -> tuple[bytes, ...]:
    if type(known_secrets) not in {tuple, list} or len(known_secrets) > MAX_BODY_BLOB_KNOWN_SECRETS:
        _fail("body-blob known-secret inventory is foreign or over-bound")
    output: list[bytes] = []
    for secret in known_secrets:
        if type(secret) is bytes:
            encoded = secret
        elif type(secret) is str:
            try:
                encoded = secret.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                _fail("body-blob known-secret inventory is invalid")
        else:
            _fail("body-blob known-secret inventory is invalid")
        if not encoded or len(encoded) > MAX_BODY_BLOB_KNOWN_SECRET_BYTES:
            _fail("body-blob known-secret inventory is invalid")
        output.append(encoded)
    return tuple(output)


def _reject_sensitive_bytes(value: bytes, *, known_secrets: Sequence[str | bytes] = ()) -> None:
    secrets = _admitted_secret_bytes(known_secrets)
    if (
        _AUTH_VALUE_RE.search(value)
        or _KNOWN_TOKEN_RE.search(value)
        or _LOCAL_PATH_RE.search(value)
        or _URL_USERINFO_RE.search(value)
        or any(secret in value for secret in secrets)
    ):
        _fail("body-blob authority contains prohibited secret or local material")


def _preflight_json_bytes(value: bytes, *, maximum_bytes: int) -> None:
    if type(value) is not bytes or not value or len(value) > maximum_bytes:
        _fail("body-blob canonical JSON violates its byte bound")
    depth = 0
    maximum_depth = 0
    structural_nodes = 1
    in_string = False
    escaped = False
    string_bytes = 0
    total_string_bytes = 0
    number_bytes = 0
    for byte in value:
        if in_string:
            if escaped:
                escaped = False
                string_bytes += 1
            elif byte == 0x5C:
                escaped = True
                string_bytes += 1
            elif byte == 0x22:
                in_string = False
                total_string_bytes += string_bytes
                if (
                    string_bytes > MAX_BODY_BLOB_JSON_STRING_BYTES
                    or total_string_bytes > MAX_BODY_BLOB_JSON_TOTAL_STRING_BYTES
                ):
                    _fail("body-blob canonical JSON exceeds its string bound")
                string_bytes = 0
            else:
                string_bytes += 1
            continue
        if number_bytes:
            if byte in b"0123456789.eE+-":
                number_bytes += 1
                if number_bytes > MAX_BODY_BLOB_NUMBER_TOKEN_BYTES:
                    _fail("body-blob canonical JSON contains an oversized number")
                continue
            number_bytes = 0
        elif byte == 0x2D or 0x30 <= byte <= 0x39:
            number_bytes = 1
            continue
        if byte == 0x22:
            in_string = True
        elif byte in (0x7B, 0x5B):
            depth += 1
            maximum_depth = max(maximum_depth, depth)
            structural_nodes += 1
        elif byte in (0x7D, 0x5D):
            depth -= 1
            if depth < 0:
                _fail("body-blob canonical JSON is invalid")
        elif byte in (0x2C, 0x3A):
            structural_nodes += 1
        if maximum_depth > MAX_BODY_BLOB_JSON_DEPTH or structural_nodes > MAX_BODY_BLOB_JSON_NODES:
            _fail("body-blob canonical JSON exceeds its structural bound")
    if in_string or escaped or depth != 0:
        _fail("body-blob canonical JSON is invalid")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    output: dict[str, object] = {}
    for key, item in pairs:
        if key in output:
            _fail("body-blob canonical JSON contains duplicate object keys")
        output[key] = item
    return output


def _bounded_integer(token: str) -> int:
    if len(token) > MAX_BODY_BLOB_NUMBER_TOKEN_BYTES:
        _fail("body-blob canonical JSON contains an oversized integer")
    try:
        value = int(token)
    except ValueError:
        _fail("body-blob canonical JSON contains an invalid integer")
    if value < -_MAX_ORDINAL or value > _MAX_ORDINAL:
        _fail("body-blob canonical JSON contains an out-of-range integer")
    return value


def _reject_json_number(_token: str) -> Never:
    _fail("body-blob canonical JSON contains a non-integer number")


def _canonical_json_bytes(value: object, *, maximum_bytes: int) -> bytes:
    if type(maximum_bytes) is not int or maximum_bytes < 1:
        _fail("body-blob canonical JSON maximum is invalid")
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8", errors="strict")
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("body-blob authority is not canonical JSON")
    if not encoded or len(encoded) > maximum_bytes:
        _fail("body-blob canonical JSON exceeds its byte bound")
    return encoded


def _decode_canonical_json(
    encoded: bytes,
    *,
    maximum_bytes: int,
    known_secrets: Sequence[str | bytes] = (),
) -> object:
    _preflight_json_bytes(encoded, maximum_bytes=maximum_bytes)
    _reject_sensitive_bytes(encoded, known_secrets=known_secrets)
    try:
        text = encoded.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_int=_bounded_integer,
            parse_float=_reject_json_number,
            parse_constant=_reject_json_number,
        )
    except BodyBlobAuthorityError:
        raise
    except (RecursionError, TypeError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        _fail("body-blob canonical JSON cannot be decoded")
    if _canonical_json_bytes(value, maximum_bytes=maximum_bytes) != encoded:
        _fail("body-blob authority bytes are not canonical JSON")
    return value


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: object, *, maximum_bytes: int = 64 * 1024) -> str:
    return _sha256_bytes(_canonical_json_bytes(value, maximum_bytes=maximum_bytes))


def _ordered_root(
    *,
    kind: str,
    raw_authority_bundle_sha256: str,
    item_sha256s: tuple[str, ...],
    maximum: int = MAX_AUTHORITY_ROWS,
) -> str:
    _exact_text(kind, label="body-blob root kind", maximum_bytes=256)
    _exact_sha256(raw_authority_bundle_sha256, label="body-blob root bundle")
    if type(item_sha256s) is not tuple or len(item_sha256s) > maximum:
        _fail("body-blob ordered-root inventory is foreign or over-bound")
    digest = hashlib.sha256()
    digest.update(b"nbadb-body-blob-length-framed-root-v1\x00")

    def feed(item: bytes) -> None:
        digest.update(len(item).to_bytes(8, byteorder="big", signed=False))
        digest.update(item)

    feed(str(BODY_BLOB_AUTHORITY_SCHEMA_VERSION).encode("ascii"))
    feed(kind.encode("ascii"))
    feed(raw_authority_bundle_sha256.encode("ascii"))
    feed(str(len(item_sha256s)).encode("ascii"))
    for ordinal, item_sha256 in enumerate(item_sha256s):
        _exact_sha256(item_sha256, label="body-blob ordered-root item")
        feed(str(ordinal).encode("ascii"))
        feed(item_sha256.encode("ascii"))
    return digest.hexdigest()


def _relative_resource_name(blob_sha256: str) -> str:
    digest = _exact_sha256(blob_sha256, label="body-blob resource identity")
    return f"{BODY_BLOB_RESOURCE_PREFIX}/{digest[:2]}/{digest}.payload.gz"


def _validate_schema_and_kind(schema_version: object, kind: object, *, expected: str) -> None:
    if type(schema_version) is not int or schema_version != BODY_BLOB_AUTHORITY_SCHEMA_VERSION:
        _fail("body-blob schema version is invalid")
    if type(kind) is not str or kind != expected:
        _fail("body-blob contract kind is invalid")


@dataclass(frozen=True, slots=True)
class BodyBlobDescriptorV1:
    """One deduplicated content-addressed deterministic-gzip body object."""

    schema_version: int
    kind: str
    raw_authority_bundle_sha256: str
    descriptor_sha256: str
    blob_sha256: str
    parser_input_object_sha256: str
    representation: str
    media_type: str
    text_encoding: str
    codec: str
    codec_contract_sha256: str
    response_sha256: str
    uncompressed_bytes: int
    stored_sha256: str
    stored_bytes: int
    relative_resource_name: str

    def __post_init__(self) -> None:
        _validate_schema_and_kind(self.schema_version, self.kind, expected=_DESCRIPTOR_KIND)
        for value, label in (
            (self.raw_authority_bundle_sha256, "descriptor raw bundle"),
            (self.descriptor_sha256, "descriptor identity"),
            (self.blob_sha256, "descriptor blob identity"),
            (self.parser_input_object_sha256, "descriptor parser-input object"),
            (self.codec_contract_sha256, "descriptor codec contract"),
            (self.response_sha256, "descriptor response digest"),
            (self.stored_sha256, "descriptor stored digest"),
        ):
            _exact_sha256(value, label=label)
        _exact_integer(
            self.uncompressed_bytes,
            label="descriptor uncompressed bytes",
            maximum=MAX_PARSER_INPUT_BYTES,
            minimum=1,
        )
        _exact_integer(
            self.stored_bytes,
            label="descriptor stored bytes",
            maximum=MAX_PARSER_INPUT_STORED_BYTES,
            minimum=1,
        )
        if (
            type(self.representation) is not str
            or self.representation != PUBLIC_PARSER_INPUT_REPRESENTATION
            or type(self.media_type) is not str
            or self.media_type != "application/json"
            or type(self.text_encoding) is not str
            or self.text_encoding != "utf-8"
            or type(self.codec) is not str
            or self.codec != DETERMINISTIC_GZIP_CODEC
            or self.codec_contract_sha256 != DETERMINISTIC_GZIP_CONTRACT_SHA256
            or self.blob_sha256 != self.stored_sha256
            or type(self.relative_resource_name) is not str
            or self.relative_resource_name != _relative_resource_name(self.blob_sha256)
            or self.descriptor_sha256 != _sha256_json(self.identity_payload())
        ):
            _fail("body-blob descriptor identity is inconsistent")

    @classmethod
    def build(
        cls,
        *,
        raw_authority_bundle_sha256: str,
        parser_input_object: ParserInputObjectV2,
    ) -> BodyBlobDescriptorV1:
        bundle_sha256 = _exact_sha256(
            raw_authority_bundle_sha256,
            label="descriptor raw bundle",
        )
        if type(parser_input_object) is not ParserInputObjectV2:
            _fail("body-blob descriptor parser-input object has a foreign type")
        try:
            rebuilt = ParserInputObjectV2.from_canonical_bytes(
                parser_input_object.to_canonical_bytes()
            )
        except (RecursionError, TypeError, ValueError):
            _fail("body-blob descriptor parser-input object is invalid")
        if rebuilt != parser_input_object:
            _fail("body-blob descriptor parser-input object differs on replay")
        payload: dict[str, object] = {
            "blob_sha256": rebuilt.stored_sha256,
            "codec": rebuilt.codec,
            "codec_contract_sha256": rebuilt.codec_contract_sha256,
            "kind": _DESCRIPTOR_KIND,
            "media_type": rebuilt.media_type,
            "parser_input_object_sha256": rebuilt.object_sha256,
            "raw_authority_bundle_sha256": bundle_sha256,
            "relative_resource_name": _relative_resource_name(rebuilt.stored_sha256),
            "representation": rebuilt.representation,
            "response_sha256": rebuilt.response_sha256,
            "schema_version": BODY_BLOB_AUTHORITY_SCHEMA_VERSION,
            "stored_bytes": rebuilt.stored_bytes,
            "stored_sha256": rebuilt.stored_sha256,
            "text_encoding": rebuilt.text_encoding,
            "uncompressed_bytes": rebuilt.uncompressed_bytes,
        }
        return cls(**payload, descriptor_sha256=_sha256_json(payload))

    def identity_payload(self) -> dict[str, object]:
        return {
            "blob_sha256": self.blob_sha256,
            "codec": self.codec,
            "codec_contract_sha256": self.codec_contract_sha256,
            "kind": self.kind,
            "media_type": self.media_type,
            "parser_input_object_sha256": self.parser_input_object_sha256,
            "raw_authority_bundle_sha256": self.raw_authority_bundle_sha256,
            "relative_resource_name": self.relative_resource_name,
            "representation": self.representation,
            "response_sha256": self.response_sha256,
            "schema_version": self.schema_version,
            "stored_bytes": self.stored_bytes,
            "stored_sha256": self.stored_sha256,
            "text_encoding": self.text_encoding,
            "uncompressed_bytes": self.uncompressed_bytes,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "descriptor_sha256": self.descriptor_sha256}


@dataclass(frozen=True, slots=True)
class BodyBlobObservationReferenceV1:
    """One logical body reference for one body-bearing Raw-v2 observation."""

    schema_version: int
    kind: str
    raw_authority_bundle_sha256: str
    reference_sha256: str
    reference_ordinal: int
    observation_ordinal: int
    observation_sha256: str
    observation_record_sha256: str
    attempt_sha256: str
    provider_call_sha256: str
    selection: BodyBlobReferenceSelection
    body_authority_receipt_sha256: str
    capture_response_receipt_sha256: str
    logical_receipt_sha256: str | None
    result_occurrence_count: int
    result_occurrences_sha256: str
    route_landing_count: int
    route_landings_sha256: str
    parser_input_object_sha256: str
    descriptor_sha256: str
    blob_sha256: str
    response_sha256: str

    def __post_init__(self) -> None:
        _validate_schema_and_kind(self.schema_version, self.kind, expected=_REFERENCE_KIND)
        for value, label in (
            (self.raw_authority_bundle_sha256, "reference raw bundle"),
            (self.reference_sha256, "reference identity"),
            (self.observation_sha256, "reference observation"),
            (self.observation_record_sha256, "reference observation record"),
            (self.attempt_sha256, "reference attempt"),
            (self.provider_call_sha256, "reference provider call"),
            (self.body_authority_receipt_sha256, "reference body receipt"),
            (self.capture_response_receipt_sha256, "reference capture receipt"),
            (self.result_occurrences_sha256, "reference result root"),
            (self.route_landings_sha256, "reference route root"),
            (self.parser_input_object_sha256, "reference parser-input object"),
            (self.descriptor_sha256, "reference descriptor"),
            (self.blob_sha256, "reference blob"),
            (self.response_sha256, "reference response"),
        ):
            _exact_sha256(value, label=label)
        _exact_integer(
            self.reference_ordinal,
            label="reference ordinal",
            maximum=MAX_AUTHORITY_ROWS,
        )
        _exact_integer(
            self.observation_ordinal,
            label="reference observation ordinal",
            maximum=MAX_AUTHORITY_ROWS,
        )
        _exact_integer(
            self.result_occurrence_count,
            label="reference result count",
            maximum=MAX_AUTHORITY_ROWS,
        )
        _exact_integer(
            self.route_landing_count,
            label="reference route count",
            maximum=MAX_AUTHORITY_ROWS,
        )
        if type(self.selection) is not str:
            _fail("body-blob reference selection is invalid")
        if self.selection not in {"selected_terminal", "downstream_incomplete"}:
            _fail("body-blob reference selection is invalid")
        if self.selection == "selected_terminal":
            if self.logical_receipt_sha256 is None:
                _fail("selected body-blob reference lacks its logical receipt")
            _exact_sha256(self.logical_receipt_sha256, label="reference logical receipt")
        elif self.logical_receipt_sha256 is not None:
            _fail("incomplete body-blob reference fabricated a logical receipt")
        if self.reference_sha256 != _sha256_json(self.identity_payload()):
            _fail("body-blob observation reference identity is inconsistent")

    @classmethod
    def build(
        cls,
        *,
        raw_authority_bundle_sha256: str,
        reference_ordinal: int,
        observation_ordinal: int,
        observation: RequestObservationV2,
        descriptor: BodyBlobDescriptorV1,
    ) -> BodyBlobObservationReferenceV1:
        bundle_sha256 = _exact_sha256(raw_authority_bundle_sha256, label="reference raw bundle")
        _exact_integer(reference_ordinal, label="reference ordinal", maximum=MAX_AUTHORITY_ROWS)
        _exact_integer(
            observation_ordinal,
            label="reference observation ordinal",
            maximum=MAX_AUTHORITY_ROWS,
        )
        if type(observation) is not RequestObservationV2:
            _fail("body-blob reference observation has a foreign type")
        try:
            rebuilt_observation = RequestObservationV2.from_canonical_bytes(
                observation.to_canonical_bytes()
            )
        except (RecursionError, TypeError, ValueError):
            _fail("body-blob reference observation is invalid")
        if rebuilt_observation != observation:
            _fail("body-blob reference observation differs on replay")
        if type(descriptor) is not BodyBlobDescriptorV1:
            _fail("body-blob reference descriptor has a foreign type")
        rebuilt_descriptor = replace(descriptor)
        if (
            rebuilt_observation.body_disposition != "public_parser_input"
            or rebuilt_observation.body_object_sha256
            != rebuilt_descriptor.parser_input_object_sha256
            or rebuilt_descriptor.raw_authority_bundle_sha256 != bundle_sha256
            or rebuilt_observation.capture_response_receipt_sha256 is None
        ):
            _fail("body-blob reference does not match its body-bearing observation")
        if rebuilt_observation.lifecycle == "selected_terminal":
            selection: BodyBlobReferenceSelection = "selected_terminal"
        elif (
            rebuilt_observation.lifecycle == "incomplete"
            and rebuilt_observation.outcome == "downstream_incomplete"
        ):
            selection = "downstream_incomplete"
        else:
            _fail("body-blob reference observation is not selected or downstream-incomplete")
        payload: dict[str, object] = {
            "attempt_sha256": rebuilt_observation.attempt.attempt_sha256,
            "blob_sha256": rebuilt_descriptor.blob_sha256,
            "body_authority_receipt_sha256": rebuilt_observation.body_authority_receipt_sha256,
            "capture_response_receipt_sha256": rebuilt_observation.capture_response_receipt_sha256,
            "descriptor_sha256": rebuilt_descriptor.descriptor_sha256,
            "kind": _REFERENCE_KIND,
            "logical_receipt_sha256": rebuilt_observation.logical_receipt_sha256,
            "observation_ordinal": observation_ordinal,
            "observation_record_sha256": rebuilt_observation.observation_record_sha256,
            "observation_sha256": rebuilt_observation.attempt.observation_sha256,
            "parser_input_object_sha256": rebuilt_descriptor.parser_input_object_sha256,
            "provider_call_sha256": rebuilt_observation.attempt.provider_call_sha256,
            "raw_authority_bundle_sha256": bundle_sha256,
            "reference_ordinal": reference_ordinal,
            "response_sha256": rebuilt_descriptor.response_sha256,
            "result_occurrence_count": rebuilt_observation.result_occurrence_count,
            "result_occurrences_sha256": rebuilt_observation.result_occurrences_sha256,
            "route_landing_count": rebuilt_observation.route_landing_count,
            "route_landings_sha256": rebuilt_observation.route_landings_sha256,
            "schema_version": BODY_BLOB_AUTHORITY_SCHEMA_VERSION,
            "selection": selection,
        }
        return cls(**payload, reference_sha256=_sha256_json(payload))

    def identity_payload(self) -> dict[str, object]:
        return {
            "attempt_sha256": self.attempt_sha256,
            "blob_sha256": self.blob_sha256,
            "body_authority_receipt_sha256": self.body_authority_receipt_sha256,
            "capture_response_receipt_sha256": self.capture_response_receipt_sha256,
            "descriptor_sha256": self.descriptor_sha256,
            "kind": self.kind,
            "logical_receipt_sha256": self.logical_receipt_sha256,
            "observation_ordinal": self.observation_ordinal,
            "observation_record_sha256": self.observation_record_sha256,
            "observation_sha256": self.observation_sha256,
            "parser_input_object_sha256": self.parser_input_object_sha256,
            "provider_call_sha256": self.provider_call_sha256,
            "raw_authority_bundle_sha256": self.raw_authority_bundle_sha256,
            "reference_ordinal": self.reference_ordinal,
            "response_sha256": self.response_sha256,
            "result_occurrence_count": self.result_occurrence_count,
            "result_occurrences_sha256": self.result_occurrences_sha256,
            "route_landing_count": self.route_landing_count,
            "route_landings_sha256": self.route_landings_sha256,
            "schema_version": self.schema_version,
            "selection": self.selection,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "reference_sha256": self.reference_sha256}


def _inventory_identity(value: BodyBlobInventoryV1) -> dict[str, object]:
    return {
        "descriptor_count": value.descriptor_count,
        "descriptor_root_sha256": value.descriptor_root_sha256,
        "descriptors": [item.to_dict() for item in value.descriptors],
        "incomplete_reference_count": value.incomplete_reference_count,
        "incomplete_reference_root_sha256": value.incomplete_reference_root_sha256,
        "kind": value.kind,
        "raw_authority_bundle_sha256": value.raw_authority_bundle_sha256,
        "reference_count": value.reference_count,
        "reference_root_sha256": value.reference_root_sha256,
        "references": [item.to_dict() for item in value.references],
        "schema_version": value.schema_version,
        "selected_reference_count": value.selected_reference_count,
        "selected_reference_root_sha256": value.selected_reference_root_sha256,
        "total_stored_bytes": value.total_stored_bytes,
        "total_uncompressed_bytes": value.total_uncompressed_bytes,
    }


@dataclass(frozen=True, slots=True)
class BodyBlobInventoryV1:
    """Complete deduplicated body/object and logical-reference inventory."""

    schema_version: int
    kind: str
    raw_authority_bundle_sha256: str
    descriptors: tuple[BodyBlobDescriptorV1, ...]
    descriptor_count: int
    descriptor_root_sha256: str
    references: tuple[BodyBlobObservationReferenceV1, ...]
    reference_count: int
    reference_root_sha256: str
    selected_reference_count: int
    selected_reference_root_sha256: str
    incomplete_reference_count: int
    incomplete_reference_root_sha256: str
    total_stored_bytes: int
    total_uncompressed_bytes: int
    inventory_sha256: str

    def __post_init__(self) -> None:
        _validate_schema_and_kind(self.schema_version, self.kind, expected=_INVENTORY_KIND)
        for value, label in (
            (self.raw_authority_bundle_sha256, "inventory raw bundle"),
            (self.descriptor_root_sha256, "inventory descriptor root"),
            (self.reference_root_sha256, "inventory reference root"),
            (self.selected_reference_root_sha256, "inventory selected root"),
            (self.incomplete_reference_root_sha256, "inventory incomplete root"),
            (self.inventory_sha256, "inventory identity"),
        ):
            _exact_sha256(value, label=label)
        for value, label in (
            (self.descriptor_count, "inventory descriptor count"),
            (self.reference_count, "inventory reference count"),
            (self.selected_reference_count, "inventory selected count"),
            (self.incomplete_reference_count, "inventory incomplete count"),
        ):
            _exact_integer(value, label=label, maximum=MAX_AUTHORITY_ROWS)
        _exact_integer(self.total_stored_bytes, label="inventory stored-byte total")
        _exact_integer(self.total_uncompressed_bytes, label="inventory raw-byte total")
        if type(self.descriptors) is not tuple or type(self.references) is not tuple:
            _fail("body-blob inventory children must be exact tuples")
        if len(self.descriptors) > MAX_AUTHORITY_ROWS or len(self.references) > MAX_AUTHORITY_ROWS:
            _fail("body-blob inventory exceeds its row bound")
        if any(type(item) is not BodyBlobDescriptorV1 for item in self.descriptors):
            _fail("body-blob inventory contains a foreign descriptor type")
        if any(type(item) is not BodyBlobObservationReferenceV1 for item in self.references):
            _fail("body-blob inventory contains a foreign reference type")
        descriptors = tuple(replace(item) for item in self.descriptors)
        references = tuple(replace(item) for item in self.references)
        if descriptors != tuple(
            sorted(
                descriptors,
                key=lambda item: (item.blob_sha256, item.parser_input_object_sha256),
            )
        ):
            _fail("body-blob descriptors are not in canonical content order")
        descriptor_by_sha: dict[str, BodyBlobDescriptorV1] = {}
        object_ids: set[str] = set()
        blob_ids: set[str] = set()
        for descriptor in descriptors:
            if descriptor.raw_authority_bundle_sha256 != self.raw_authority_bundle_sha256:
                _fail("body-blob inventory contains a foreign descriptor scope")
            if (
                descriptor.descriptor_sha256 in descriptor_by_sha
                or descriptor.parser_input_object_sha256 in object_ids
                or descriptor.blob_sha256 in blob_ids
            ):
                _fail("body-blob inventory contains a duplicate descriptor identity")
            descriptor_by_sha[descriptor.descriptor_sha256] = descriptor
            object_ids.add(descriptor.parser_input_object_sha256)
            blob_ids.add(descriptor.blob_sha256)
        referenced_descriptors: set[str] = set()
        observation_ids: set[str] = set()
        prior_observation_ordinal = -1
        for expected_ordinal, reference in enumerate(references):
            if (
                reference.raw_authority_bundle_sha256 != self.raw_authority_bundle_sha256
                or reference.reference_ordinal != expected_ordinal
                or reference.observation_ordinal <= prior_observation_ordinal
            ):
                _fail("body-blob references violate canonical scope or order")
            prior_observation_ordinal = reference.observation_ordinal
            descriptor = descriptor_by_sha.get(reference.descriptor_sha256)
            if (
                descriptor is None
                or reference.parser_input_object_sha256 != descriptor.parser_input_object_sha256
                or reference.blob_sha256 != descriptor.blob_sha256
                or reference.response_sha256 != descriptor.response_sha256
            ):
                _fail("body-blob reference points to a foreign descriptor")
            if reference.observation_sha256 in observation_ids:
                _fail("body-blob observation reference is duplicated")
            observation_ids.add(reference.observation_sha256)
            referenced_descriptors.add(reference.descriptor_sha256)
        if referenced_descriptors != set(descriptor_by_sha):
            _fail("body-blob inventory contains an orphan descriptor")
        selected = tuple(
            item.reference_sha256 for item in references if item.selection == "selected_terminal"
        )
        incomplete = tuple(
            item.reference_sha256
            for item in references
            if item.selection == "downstream_incomplete"
        )
        descriptor_ids = tuple(item.descriptor_sha256 for item in descriptors)
        reference_ids = tuple(item.reference_sha256 for item in references)
        if (
            self.descriptor_count != len(descriptors)
            or self.reference_count != len(references)
            or self.selected_reference_count != len(selected)
            or self.incomplete_reference_count != len(incomplete)
            or self.selected_reference_count + self.incomplete_reference_count
            != self.reference_count
            or self.descriptor_root_sha256
            != _ordered_root(
                kind=_DESCRIPTOR_ROOT_KIND,
                raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                item_sha256s=descriptor_ids,
            )
            or self.reference_root_sha256
            != _ordered_root(
                kind=_REFERENCE_ROOT_KIND,
                raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                item_sha256s=reference_ids,
            )
            or self.selected_reference_root_sha256
            != _ordered_root(
                kind=_SELECTED_REFERENCE_ROOT_KIND,
                raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                item_sha256s=selected,
            )
            or self.incomplete_reference_root_sha256
            != _ordered_root(
                kind=_INCOMPLETE_REFERENCE_ROOT_KIND,
                raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                item_sha256s=incomplete,
            )
            or self.total_stored_bytes != sum(item.stored_bytes for item in descriptors)
            or self.total_uncompressed_bytes != sum(item.uncompressed_bytes for item in descriptors)
            or self.inventory_sha256
            != _sha256_json(_inventory_identity(self), maximum_bytes=MAX_BODY_BLOB_CANONICAL_BYTES)
        ):
            _fail("body-blob inventory identity or denominator is inconsistent")

    def to_dict(self) -> dict[str, object]:
        return {**_inventory_identity(self), "inventory_sha256": self.inventory_sha256}

    def to_canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict(), maximum_bytes=MAX_BODY_BLOB_CANONICAL_BYTES)

    @classmethod
    def from_canonical_bytes(
        cls,
        encoded: bytes,
        *,
        bundle: RawRequestAuthorityBundleV2,
        expected_raw_authority_bundle_sha256: str,
        expected_inventory_sha256: str,
        known_secrets: Sequence[str | bytes] = (),
    ) -> BodyBlobInventoryV1:
        return replay_body_blob_inventory(
            encoded,
            bundle=bundle,
            expected_raw_authority_bundle_sha256=expected_raw_authority_bundle_sha256,
            expected_inventory_sha256=expected_inventory_sha256,
            known_secrets=known_secrets,
        )


def _file_readback_identity(value: BodyBlobFileReadbackReceiptV1) -> dict[str, object]:
    return {
        "blob_sha256": value.blob_sha256,
        "descriptor_sha256": value.descriptor_sha256,
        "kind": value.kind,
        "parser_input_object_sha256": value.parser_input_object_sha256,
        "raw_authority_bundle_sha256": value.raw_authority_bundle_sha256,
        "readback_bytes": value.readback_bytes,
        "readback_sha256": value.readback_sha256,
        "relative_resource_name": value.relative_resource_name,
        "response_sha256": value.response_sha256,
        "schema_version": value.schema_version,
        "store_namespace_sha256": value.store_namespace_sha256,
        "stored_bytes": value.stored_bytes,
        "stored_sha256": value.stored_sha256,
        "uncompressed_bytes": value.uncompressed_bytes,
    }


@dataclass(frozen=True, slots=True)
class BodyBlobFileReadbackReceiptV1:
    """Path-free proof that one immutable regular-file payload was read back."""

    schema_version: int
    kind: str
    raw_authority_bundle_sha256: str
    store_namespace_sha256: str
    descriptor_sha256: str
    blob_sha256: str
    parser_input_object_sha256: str
    relative_resource_name: str
    response_sha256: str
    uncompressed_bytes: int
    stored_sha256: str
    stored_bytes: int
    readback_sha256: str
    readback_bytes: int
    receipt_sha256: str

    def __post_init__(self) -> None:
        _validate_schema_and_kind(self.schema_version, self.kind, expected=_FILE_READBACK_KIND)
        for value, label in (
            (self.raw_authority_bundle_sha256, "file readback raw bundle"),
            (self.store_namespace_sha256, "file readback store namespace"),
            (self.descriptor_sha256, "file readback descriptor"),
            (self.blob_sha256, "file readback blob"),
            (self.parser_input_object_sha256, "file readback parser-input object"),
            (self.response_sha256, "file readback response"),
            (self.stored_sha256, "file readback stored digest"),
            (self.readback_sha256, "file readback digest"),
            (self.receipt_sha256, "file readback receipt"),
        ):
            _exact_sha256(value, label=label)
        _exact_integer(
            self.uncompressed_bytes,
            label="file readback uncompressed bytes",
            maximum=MAX_PARSER_INPUT_BYTES,
            minimum=1,
        )
        _exact_integer(
            self.stored_bytes,
            label="file readback stored bytes",
            maximum=MAX_PARSER_INPUT_STORED_BYTES,
            minimum=1,
        )
        _exact_integer(
            self.readback_bytes,
            label="file readback bytes",
            maximum=MAX_PARSER_INPUT_STORED_BYTES,
            minimum=1,
        )
        if (
            type(self.relative_resource_name) is not str
            or self.relative_resource_name != _relative_resource_name(self.blob_sha256)
            or self.blob_sha256 != self.stored_sha256
            or self.readback_sha256 != self.stored_sha256
            or self.readback_bytes != self.stored_bytes
            or self.receipt_sha256 != _sha256_json(_file_readback_identity(self))
        ):
            _fail("body-blob file readback identity is inconsistent")

    @classmethod
    def build(
        cls,
        *,
        descriptor: BodyBlobDescriptorV1,
        parser_input_object: ParserInputObjectV2,
        readback_bytes: bytes,
        store_namespace_sha256: str,
        expected_raw_authority_bundle_sha256: str,
        expected_descriptor_sha256: str,
        known_secrets: Sequence[str | bytes] = (),
    ) -> BodyBlobFileReadbackReceiptV1:
        bundle_sha256 = _exact_sha256(
            expected_raw_authority_bundle_sha256,
            label="expected file-readback raw bundle",
        )
        namespace_sha256 = _exact_sha256(
            store_namespace_sha256,
            label="expected file-readback store namespace",
        )
        descriptor_sha256 = _exact_sha256(
            expected_descriptor_sha256,
            label="expected file-readback descriptor",
        )
        _admitted_secret_bytes(known_secrets)
        if type(descriptor) is not BodyBlobDescriptorV1:
            _fail("body-blob file readback descriptor has a foreign type")
        candidate_descriptor = replace(descriptor)
        if (
            candidate_descriptor.raw_authority_bundle_sha256 != bundle_sha256
            or candidate_descriptor.descriptor_sha256 != descriptor_sha256
        ):
            _fail("body-blob file readback descriptor differs from external pins")
        if type(parser_input_object) is not ParserInputObjectV2:
            _fail("body-blob file readback parser-input object has a foreign type")
        try:
            body_object = validate_parser_input_object(parser_input_object)
            raw = decode_parser_input_object(body_object)
        except (RecursionError, TypeError, ValueError):
            _fail("body-blob file readback parser-input object is invalid")
        if type(body_object) is not ParserInputObjectV2 or body_object != parser_input_object:
            _fail("body-blob file readback parser-input object differs on validation")
        _reject_sensitive_bytes(raw, known_secrets=known_secrets)
        if type(readback_bytes) is not bytes:
            _fail("body-blob file readback must be exact built-in bytes")
        if (
            candidate_descriptor.parser_input_object_sha256 != body_object.object_sha256
            or candidate_descriptor.response_sha256 != body_object.response_sha256
            or candidate_descriptor.uncompressed_bytes != len(raw)
            or candidate_descriptor.stored_sha256 != body_object.stored_sha256
            or candidate_descriptor.stored_bytes != body_object.stored_bytes
            or len(readback_bytes) != candidate_descriptor.stored_bytes
            or _sha256_bytes(readback_bytes) != candidate_descriptor.stored_sha256
            or readback_bytes != body_object.stored_payload
        ):
            _fail("body-blob file readback differs from exact object authority")
        payload: dict[str, object] = {
            "blob_sha256": candidate_descriptor.blob_sha256,
            "descriptor_sha256": candidate_descriptor.descriptor_sha256,
            "kind": _FILE_READBACK_KIND,
            "parser_input_object_sha256": candidate_descriptor.parser_input_object_sha256,
            "raw_authority_bundle_sha256": bundle_sha256,
            "readback_bytes": len(readback_bytes),
            "readback_sha256": _sha256_bytes(readback_bytes),
            "relative_resource_name": candidate_descriptor.relative_resource_name,
            "response_sha256": candidate_descriptor.response_sha256,
            "schema_version": BODY_BLOB_AUTHORITY_SCHEMA_VERSION,
            "store_namespace_sha256": namespace_sha256,
            "stored_bytes": candidate_descriptor.stored_bytes,
            "stored_sha256": candidate_descriptor.stored_sha256,
            "uncompressed_bytes": candidate_descriptor.uncompressed_bytes,
        }
        return cls(**payload, receipt_sha256=_sha256_json(payload))

    def to_dict(self) -> dict[str, object]:
        return {**_file_readback_identity(self), "receipt_sha256": self.receipt_sha256}

    def to_canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict(), maximum_bytes=64 * 1024)

    @classmethod
    def from_canonical_bytes(
        cls,
        encoded: bytes,
        *,
        descriptor: BodyBlobDescriptorV1,
        parser_input_object: ParserInputObjectV2,
        readback_bytes: bytes,
        store_namespace_sha256: str,
        expected_raw_authority_bundle_sha256: str,
        expected_descriptor_sha256: str,
        expected_receipt_sha256: str,
        known_secrets: Sequence[str | bytes] = (),
    ) -> BodyBlobFileReadbackReceiptV1:
        expected_receipt = _exact_sha256(
            expected_receipt_sha256,
            label="expected file-readback receipt",
        )
        row = _strict_row(
            _decode_canonical_json(encoded, maximum_bytes=64 * 1024, known_secrets=known_secrets),
            cls,
            label="file readback receipt",
        )
        candidate = _construct_exact(cls, row, label="file readback receipt")
        if candidate.receipt_sha256 != expected_receipt:
            _fail("body-blob file readback differs from its external receipt pin")
        rebuilt = cls.build(
            descriptor=descriptor,
            parser_input_object=parser_input_object,
            readback_bytes=readback_bytes,
            store_namespace_sha256=store_namespace_sha256,
            expected_raw_authority_bundle_sha256=expected_raw_authority_bundle_sha256,
            expected_descriptor_sha256=expected_descriptor_sha256,
            known_secrets=known_secrets,
        )
        if candidate.to_canonical_bytes() != rebuilt.to_canonical_bytes():
            _fail("body-blob file readback differs from exact byte replay")
        return rebuilt


def _observation_readback_identity(
    value: BodyBlobObservationReadbackReceiptV1,
) -> dict[str, object]:
    return {
        "blob_sha256": value.blob_sha256,
        "descriptor_sha256": value.descriptor_sha256,
        "file_readback_receipt_sha256": value.file_readback_receipt_sha256,
        "kind": value.kind,
        "observation_ordinal": value.observation_ordinal,
        "observation_record_sha256": value.observation_record_sha256,
        "observation_sha256": value.observation_sha256,
        "raw_authority_bundle_sha256": value.raw_authority_bundle_sha256,
        "reference_ordinal": value.reference_ordinal,
        "reference_sha256": value.reference_sha256,
        "schema_version": value.schema_version,
        "selection": value.selection,
        "store_namespace_sha256": value.store_namespace_sha256,
    }


@dataclass(frozen=True, slots=True)
class BodyBlobObservationReadbackReceiptV1:
    """Logical proof that one observation reference resolves to one read-back file."""

    schema_version: int
    kind: str
    raw_authority_bundle_sha256: str
    store_namespace_sha256: str
    reference_sha256: str
    reference_ordinal: int
    observation_ordinal: int
    observation_sha256: str
    observation_record_sha256: str
    selection: BodyBlobReferenceSelection
    descriptor_sha256: str
    blob_sha256: str
    file_readback_receipt_sha256: str
    receipt_sha256: str

    def __post_init__(self) -> None:
        _validate_schema_and_kind(
            self.schema_version,
            self.kind,
            expected=_OBSERVATION_READBACK_KIND,
        )
        for value, label in (
            (self.raw_authority_bundle_sha256, "observation readback raw bundle"),
            (self.store_namespace_sha256, "observation readback namespace"),
            (self.reference_sha256, "observation readback reference"),
            (self.observation_sha256, "observation readback observation"),
            (self.observation_record_sha256, "observation readback record"),
            (self.descriptor_sha256, "observation readback descriptor"),
            (self.blob_sha256, "observation readback blob"),
            (self.file_readback_receipt_sha256, "observation readback file receipt"),
            (self.receipt_sha256, "observation readback receipt"),
        ):
            _exact_sha256(value, label=label)
        _exact_integer(
            self.reference_ordinal,
            label="observation readback reference ordinal",
            maximum=MAX_AUTHORITY_ROWS,
        )
        _exact_integer(
            self.observation_ordinal,
            label="observation readback observation ordinal",
            maximum=MAX_AUTHORITY_ROWS,
        )
        if type(self.selection) is not str:
            _fail("body-blob observation readback selection is invalid")
        if self.selection not in {"selected_terminal", "downstream_incomplete"}:
            _fail("body-blob observation readback selection is invalid")
        if self.receipt_sha256 != _sha256_json(_observation_readback_identity(self)):
            _fail("body-blob observation readback identity is inconsistent")

    @classmethod
    def build(
        cls,
        *,
        reference: BodyBlobObservationReferenceV1,
        file_readback: BodyBlobFileReadbackReceiptV1,
        expected_raw_authority_bundle_sha256: str,
        expected_reference_sha256: str,
        expected_file_readback_receipt_sha256: str,
    ) -> BodyBlobObservationReadbackReceiptV1:
        bundle_sha256 = _exact_sha256(
            expected_raw_authority_bundle_sha256,
            label="expected observation-readback raw bundle",
        )
        reference_sha256 = _exact_sha256(
            expected_reference_sha256,
            label="expected observation-readback reference",
        )
        file_receipt_sha256 = _exact_sha256(
            expected_file_readback_receipt_sha256,
            label="expected observation-readback file receipt",
        )
        if type(reference) is not BodyBlobObservationReferenceV1:
            _fail("body-blob observation readback reference has a foreign type")
        if type(file_readback) is not BodyBlobFileReadbackReceiptV1:
            _fail("body-blob observation readback file receipt has a foreign type")
        candidate_reference = replace(reference)
        candidate_file = replace(file_readback)
        if (
            candidate_reference.raw_authority_bundle_sha256 != bundle_sha256
            or candidate_reference.reference_sha256 != reference_sha256
            or candidate_file.raw_authority_bundle_sha256 != bundle_sha256
            or candidate_file.receipt_sha256 != file_receipt_sha256
            or candidate_reference.descriptor_sha256 != candidate_file.descriptor_sha256
            or candidate_reference.blob_sha256 != candidate_file.blob_sha256
            or candidate_reference.parser_input_object_sha256
            != candidate_file.parser_input_object_sha256
            or candidate_reference.response_sha256 != candidate_file.response_sha256
        ):
            _fail("body-blob observation readback does not resolve its reference")
        payload: dict[str, object] = {
            "blob_sha256": candidate_reference.blob_sha256,
            "descriptor_sha256": candidate_reference.descriptor_sha256,
            "file_readback_receipt_sha256": candidate_file.receipt_sha256,
            "kind": _OBSERVATION_READBACK_KIND,
            "observation_ordinal": candidate_reference.observation_ordinal,
            "observation_record_sha256": candidate_reference.observation_record_sha256,
            "observation_sha256": candidate_reference.observation_sha256,
            "raw_authority_bundle_sha256": bundle_sha256,
            "reference_ordinal": candidate_reference.reference_ordinal,
            "reference_sha256": candidate_reference.reference_sha256,
            "schema_version": BODY_BLOB_AUTHORITY_SCHEMA_VERSION,
            "selection": candidate_reference.selection,
            "store_namespace_sha256": candidate_file.store_namespace_sha256,
        }
        return cls(**payload, receipt_sha256=_sha256_json(payload))

    def to_dict(self) -> dict[str, object]:
        return {**_observation_readback_identity(self), "receipt_sha256": self.receipt_sha256}

    def to_canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict(), maximum_bytes=64 * 1024)

    @classmethod
    def from_canonical_bytes(
        cls,
        encoded: bytes,
        *,
        reference: BodyBlobObservationReferenceV1,
        file_readback: BodyBlobFileReadbackReceiptV1,
        expected_raw_authority_bundle_sha256: str,
        expected_reference_sha256: str,
        expected_file_readback_receipt_sha256: str,
        expected_receipt_sha256: str,
        known_secrets: Sequence[str | bytes] = (),
    ) -> BodyBlobObservationReadbackReceiptV1:
        expected_receipt = _exact_sha256(
            expected_receipt_sha256,
            label="expected observation-readback receipt",
        )
        row = _strict_row(
            _decode_canonical_json(
                encoded,
                maximum_bytes=64 * 1024,
                known_secrets=known_secrets,
            ),
            cls,
            label="observation readback receipt",
        )
        candidate = cast(
            "BodyBlobObservationReadbackReceiptV1",
            _construct_exact(cls, row, label="observation readback receipt"),
        )
        if candidate.receipt_sha256 != expected_receipt:
            _fail("body-blob observation readback differs from its external receipt pin")
        rebuilt = cls.build(
            reference=reference,
            file_readback=file_readback,
            expected_raw_authority_bundle_sha256=expected_raw_authority_bundle_sha256,
            expected_reference_sha256=expected_reference_sha256,
            expected_file_readback_receipt_sha256=(expected_file_readback_receipt_sha256),
        )
        if candidate.to_canonical_bytes() != rebuilt.to_canonical_bytes():
            _fail("body-blob observation readback differs from exact reference replay")
        return rebuilt


def _inventory_readback_identity(value: BodyBlobInventoryReadbackReceiptV1) -> dict[str, object]:
    return {
        "file_readback_count": value.file_readback_count,
        "file_readback_root_sha256": value.file_readback_root_sha256,
        "file_readbacks": [item.to_dict() for item in value.file_readbacks],
        "incomplete_observation_readback_count": value.incomplete_observation_readback_count,
        "incomplete_observation_readback_root_sha256": (
            value.incomplete_observation_readback_root_sha256
        ),
        "inventory_sha256": value.inventory_sha256,
        "kind": value.kind,
        "observation_readback_count": value.observation_readback_count,
        "observation_readback_root_sha256": value.observation_readback_root_sha256,
        "observation_readbacks": [item.to_dict() for item in value.observation_readbacks],
        "raw_authority_bundle_sha256": value.raw_authority_bundle_sha256,
        "schema_version": value.schema_version,
        "selected_observation_readback_count": value.selected_observation_readback_count,
        "selected_observation_readback_root_sha256": (
            value.selected_observation_readback_root_sha256
        ),
        "store_namespace_sha256": value.store_namespace_sha256,
        "total_readback_bytes": value.total_readback_bytes,
    }


@dataclass(frozen=True, slots=True)
class BodyBlobInventoryReadbackReceiptV1:
    """Complete path-free readback closure for one bundle-scoped inventory."""

    schema_version: int
    kind: str
    raw_authority_bundle_sha256: str
    inventory_sha256: str
    store_namespace_sha256: str
    file_readbacks: tuple[BodyBlobFileReadbackReceiptV1, ...]
    file_readback_count: int
    file_readback_root_sha256: str
    observation_readbacks: tuple[BodyBlobObservationReadbackReceiptV1, ...]
    observation_readback_count: int
    observation_readback_root_sha256: str
    selected_observation_readback_count: int
    selected_observation_readback_root_sha256: str
    incomplete_observation_readback_count: int
    incomplete_observation_readback_root_sha256: str
    total_readback_bytes: int
    receipt_sha256: str

    def __post_init__(self) -> None:
        _validate_schema_and_kind(
            self.schema_version,
            self.kind,
            expected=_INVENTORY_READBACK_KIND,
        )
        for value, label in (
            (self.raw_authority_bundle_sha256, "inventory readback raw bundle"),
            (self.inventory_sha256, "inventory readback inventory"),
            (self.store_namespace_sha256, "inventory readback namespace"),
            (self.file_readback_root_sha256, "inventory readback file root"),
            (self.observation_readback_root_sha256, "inventory readback observation root"),
            (
                self.selected_observation_readback_root_sha256,
                "inventory readback selected root",
            ),
            (
                self.incomplete_observation_readback_root_sha256,
                "inventory readback incomplete root",
            ),
            (self.receipt_sha256, "inventory readback receipt"),
        ):
            _exact_sha256(value, label=label)
        for value, label in (
            (self.file_readback_count, "inventory readback file count"),
            (self.observation_readback_count, "inventory readback observation count"),
            (self.selected_observation_readback_count, "inventory readback selected count"),
            (self.incomplete_observation_readback_count, "inventory readback incomplete count"),
        ):
            _exact_integer(value, label=label, maximum=MAX_AUTHORITY_ROWS)
        _exact_integer(self.total_readback_bytes, label="inventory readback byte total")
        if type(self.file_readbacks) is not tuple or type(self.observation_readbacks) is not tuple:
            _fail("body-blob inventory readback children must be exact tuples")
        if any(type(item) is not BodyBlobFileReadbackReceiptV1 for item in self.file_readbacks):
            _fail("body-blob inventory readback contains a foreign file receipt")
        if any(
            type(item) is not BodyBlobObservationReadbackReceiptV1
            for item in self.observation_readbacks
        ):
            _fail("body-blob inventory readback contains a foreign observation receipt")
        files = tuple(replace(item) for item in self.file_readbacks)
        observations = tuple(replace(item) for item in self.observation_readbacks)
        if any(
            item.raw_authority_bundle_sha256 != self.raw_authority_bundle_sha256
            or item.store_namespace_sha256 != self.store_namespace_sha256
            for item in (*files, *observations)
        ):
            _fail("body-blob inventory readback contains a foreign scope")
        if files != tuple(
            sorted(
                files,
                key=lambda item: (item.blob_sha256, item.parser_input_object_sha256),
            )
        ):
            _fail("body-blob file readbacks are not in canonical content order")
        file_by_descriptor: dict[str, BodyBlobFileReadbackReceiptV1] = {}
        file_blob_ids: set[str] = set()
        for item in files:
            if item.descriptor_sha256 in file_by_descriptor or item.blob_sha256 in file_blob_ids:
                _fail("body-blob inventory readback contains a duplicate file receipt")
            file_by_descriptor[item.descriptor_sha256] = item
            file_blob_ids.add(item.blob_sha256)
        observation_ids: set[str] = set()
        reference_ids: set[str] = set()
        referenced_files: set[str] = set()
        prior_observation_ordinal = -1
        for expected_ordinal, item in enumerate(observations):
            file_receipt = file_by_descriptor.get(item.descriptor_sha256)
            if (
                item.reference_ordinal != expected_ordinal
                or item.observation_ordinal <= prior_observation_ordinal
                or file_receipt is None
                or item.file_readback_receipt_sha256 != file_receipt.receipt_sha256
                or item.blob_sha256 != file_receipt.blob_sha256
            ):
                _fail("body-blob observation readbacks violate canonical order or binding")
            if item.observation_sha256 in observation_ids or item.reference_sha256 in reference_ids:
                _fail("body-blob inventory readback contains a duplicate observation receipt")
            prior_observation_ordinal = item.observation_ordinal
            observation_ids.add(item.observation_sha256)
            reference_ids.add(item.reference_sha256)
            referenced_files.add(item.descriptor_sha256)
        if referenced_files != set(file_by_descriptor):
            _fail("body-blob inventory readback contains an orphan file receipt")
        selected = tuple(
            item.receipt_sha256 for item in observations if item.selection == "selected_terminal"
        )
        incomplete = tuple(
            item.receipt_sha256
            for item in observations
            if item.selection == "downstream_incomplete"
        )
        if (
            self.file_readback_count != len(files)
            or self.observation_readback_count != len(observations)
            or self.selected_observation_readback_count != len(selected)
            or self.incomplete_observation_readback_count != len(incomplete)
            or self.selected_observation_readback_count + self.incomplete_observation_readback_count
            != self.observation_readback_count
            or self.file_readback_root_sha256
            != _ordered_root(
                kind=_FILE_READBACK_ROOT_KIND,
                raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                item_sha256s=tuple(item.receipt_sha256 for item in files),
            )
            or self.observation_readback_root_sha256
            != _ordered_root(
                kind=_OBSERVATION_READBACK_ROOT_KIND,
                raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                item_sha256s=tuple(item.receipt_sha256 for item in observations),
            )
            or self.selected_observation_readback_root_sha256
            != _ordered_root(
                kind=_SELECTED_READBACK_ROOT_KIND,
                raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                item_sha256s=selected,
            )
            or self.incomplete_observation_readback_root_sha256
            != _ordered_root(
                kind=_INCOMPLETE_READBACK_ROOT_KIND,
                raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                item_sha256s=incomplete,
            )
            or self.total_readback_bytes != sum(item.readback_bytes for item in files)
            or self.receipt_sha256
            != _sha256_json(
                _inventory_readback_identity(self),
                maximum_bytes=MAX_BODY_BLOB_CANONICAL_BYTES,
            )
        ):
            _fail("body-blob inventory readback identity is inconsistent")

    @classmethod
    def build(
        cls,
        *,
        inventory: BodyBlobInventoryV1,
        file_readbacks: tuple[BodyBlobFileReadbackReceiptV1, ...],
        observation_readbacks: tuple[BodyBlobObservationReadbackReceiptV1, ...],
        store_namespace_sha256: str,
        expected_raw_authority_bundle_sha256: str,
        expected_inventory_sha256: str,
    ) -> BodyBlobInventoryReadbackReceiptV1:
        bundle_sha256 = _exact_sha256(
            expected_raw_authority_bundle_sha256,
            label="expected inventory-readback raw bundle",
        )
        inventory_sha256 = _exact_sha256(
            expected_inventory_sha256,
            label="expected inventory-readback inventory",
        )
        namespace_sha256 = _exact_sha256(
            store_namespace_sha256,
            label="expected inventory-readback namespace",
        )
        if type(inventory) is not BodyBlobInventoryV1:
            _fail("body-blob inventory readback inventory has a foreign type")
        candidate_inventory = replace(inventory)
        if (
            candidate_inventory.raw_authority_bundle_sha256 != bundle_sha256
            or candidate_inventory.inventory_sha256 != inventory_sha256
        ):
            _fail("body-blob inventory readback differs from external pins")
        if type(file_readbacks) is not tuple or type(observation_readbacks) is not tuple:
            _fail("body-blob inventory readback inputs must be exact tuples")
        if len(file_readbacks) != len(candidate_inventory.descriptors) or len(
            observation_readbacks
        ) != len(candidate_inventory.references):
            _fail("body-blob inventory readback denominator is incomplete")
        files: list[BodyBlobFileReadbackReceiptV1] = []
        for descriptor, receipt in zip(
            candidate_inventory.descriptors,
            file_readbacks,
            strict=True,
        ):
            if type(receipt) is not BodyBlobFileReadbackReceiptV1:
                _fail("body-blob inventory readback contains a foreign file receipt")
            candidate = replace(receipt)
            if (
                candidate.raw_authority_bundle_sha256 != bundle_sha256
                or candidate.store_namespace_sha256 != namespace_sha256
                or candidate.descriptor_sha256 != descriptor.descriptor_sha256
                or candidate.blob_sha256 != descriptor.blob_sha256
            ):
                _fail("body-blob inventory file readback order or binding is invalid")
            files.append(candidate)
        file_by_descriptor = {item.descriptor_sha256: item for item in files}
        observations: list[BodyBlobObservationReadbackReceiptV1] = []
        for reference, receipt in zip(
            candidate_inventory.references,
            observation_readbacks,
            strict=True,
        ):
            if type(receipt) is not BodyBlobObservationReadbackReceiptV1:
                _fail("body-blob inventory readback contains a foreign observation receipt")
            candidate = replace(receipt)
            file_receipt = file_by_descriptor.get(reference.descriptor_sha256)
            if (
                file_receipt is None
                or candidate.raw_authority_bundle_sha256 != bundle_sha256
                or candidate.store_namespace_sha256 != namespace_sha256
                or candidate.reference_sha256 != reference.reference_sha256
                or candidate.reference_ordinal != reference.reference_ordinal
                or candidate.file_readback_receipt_sha256 != file_receipt.receipt_sha256
            ):
                _fail("body-blob inventory observation readback order or binding is invalid")
            observations.append(candidate)
        file_ids = tuple(item.receipt_sha256 for item in files)
        observation_ids = tuple(item.receipt_sha256 for item in observations)
        selected_ids = tuple(
            item.receipt_sha256 for item in observations if item.selection == "selected_terminal"
        )
        incomplete_ids = tuple(
            item.receipt_sha256
            for item in observations
            if item.selection == "downstream_incomplete"
        )
        payload: dict[str, object] = {
            "file_readback_count": len(files),
            "file_readback_root_sha256": _ordered_root(
                kind=_FILE_READBACK_ROOT_KIND,
                raw_authority_bundle_sha256=bundle_sha256,
                item_sha256s=file_ids,
            ),
            "file_readbacks": [item.to_dict() for item in files],
            "incomplete_observation_readback_count": len(incomplete_ids),
            "incomplete_observation_readback_root_sha256": _ordered_root(
                kind=_INCOMPLETE_READBACK_ROOT_KIND,
                raw_authority_bundle_sha256=bundle_sha256,
                item_sha256s=incomplete_ids,
            ),
            "inventory_sha256": inventory_sha256,
            "kind": _INVENTORY_READBACK_KIND,
            "observation_readback_count": len(observations),
            "observation_readback_root_sha256": _ordered_root(
                kind=_OBSERVATION_READBACK_ROOT_KIND,
                raw_authority_bundle_sha256=bundle_sha256,
                item_sha256s=observation_ids,
            ),
            "observation_readbacks": [item.to_dict() for item in observations],
            "raw_authority_bundle_sha256": bundle_sha256,
            "schema_version": BODY_BLOB_AUTHORITY_SCHEMA_VERSION,
            "selected_observation_readback_count": len(selected_ids),
            "selected_observation_readback_root_sha256": _ordered_root(
                kind=_SELECTED_READBACK_ROOT_KIND,
                raw_authority_bundle_sha256=bundle_sha256,
                item_sha256s=selected_ids,
            ),
            "store_namespace_sha256": namespace_sha256,
            "total_readback_bytes": sum(item.readback_bytes for item in files),
        }
        return cls(
            schema_version=cast("int", payload["schema_version"]),
            kind=cast("str", payload["kind"]),
            raw_authority_bundle_sha256=bundle_sha256,
            inventory_sha256=inventory_sha256,
            store_namespace_sha256=namespace_sha256,
            file_readbacks=tuple(files),
            file_readback_count=len(files),
            file_readback_root_sha256=payload["file_readback_root_sha256"],
            observation_readbacks=tuple(observations),
            observation_readback_count=len(observations),
            observation_readback_root_sha256=payload["observation_readback_root_sha256"],
            selected_observation_readback_count=len(selected_ids),
            selected_observation_readback_root_sha256=payload[
                "selected_observation_readback_root_sha256"
            ],
            incomplete_observation_readback_count=len(incomplete_ids),
            incomplete_observation_readback_root_sha256=payload[
                "incomplete_observation_readback_root_sha256"
            ],
            total_readback_bytes=payload["total_readback_bytes"],
            receipt_sha256=_sha256_json(
                payload,
                maximum_bytes=MAX_BODY_BLOB_CANONICAL_BYTES,
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {**_inventory_readback_identity(self), "receipt_sha256": self.receipt_sha256}

    def to_canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict(), maximum_bytes=MAX_BODY_BLOB_CANONICAL_BYTES)

    @classmethod
    def from_canonical_bytes(
        cls,
        encoded: bytes,
        *,
        inventory: BodyBlobInventoryV1,
        file_readbacks: tuple[BodyBlobFileReadbackReceiptV1, ...],
        observation_readbacks: tuple[BodyBlobObservationReadbackReceiptV1, ...],
        store_namespace_sha256: str,
        expected_raw_authority_bundle_sha256: str,
        expected_inventory_sha256: str,
        expected_receipt_sha256: str,
        known_secrets: Sequence[str | bytes] = (),
    ) -> BodyBlobInventoryReadbackReceiptV1:
        expected_receipt = _exact_sha256(
            expected_receipt_sha256,
            label="expected inventory-readback receipt",
        )
        row = _strict_row(
            _decode_canonical_json(
                encoded,
                maximum_bytes=MAX_BODY_BLOB_CANONICAL_BYTES,
                known_secrets=known_secrets,
            ),
            cls,
            label="inventory readback receipt",
        )
        file_values = row["file_readbacks"]
        observation_values = row["observation_readbacks"]
        if type(file_values) is not list or len(file_values) > MAX_AUTHORITY_ROWS:
            _fail("body-blob encoded file-readback inventory is foreign or over-bound")
        if type(observation_values) is not list or len(observation_values) > MAX_AUTHORITY_ROWS:
            _fail("body-blob encoded observation-readback inventory is foreign or over-bound")
        rebuilt_row = dict(row)
        rebuilt_row["file_readbacks"] = tuple(
            cast(
                "BodyBlobFileReadbackReceiptV1",
                _construct_exact(
                    BodyBlobFileReadbackReceiptV1,
                    _strict_row(
                        item,
                        BodyBlobFileReadbackReceiptV1,
                        label="file readback receipt",
                    ),
                    label="file readback receipt",
                ),
            )
            for item in cast("list[object]", file_values)
        )
        rebuilt_row["observation_readbacks"] = tuple(
            cast(
                "BodyBlobObservationReadbackReceiptV1",
                _construct_exact(
                    BodyBlobObservationReadbackReceiptV1,
                    _strict_row(
                        item,
                        BodyBlobObservationReadbackReceiptV1,
                        label="observation readback receipt",
                    ),
                    label="observation readback receipt",
                ),
            )
            for item in cast("list[object]", observation_values)
        )
        candidate = cast(
            "BodyBlobInventoryReadbackReceiptV1",
            _construct_exact(cls, rebuilt_row, label="inventory readback receipt"),
        )
        if candidate.receipt_sha256 != expected_receipt:
            _fail("body-blob inventory readback differs from its external receipt pin")
        rebuilt = cls.build(
            inventory=inventory,
            file_readbacks=file_readbacks,
            observation_readbacks=observation_readbacks,
            store_namespace_sha256=store_namespace_sha256,
            expected_raw_authority_bundle_sha256=expected_raw_authority_bundle_sha256,
            expected_inventory_sha256=expected_inventory_sha256,
        )
        if candidate.to_canonical_bytes() != rebuilt.to_canonical_bytes():
            _fail("body-blob inventory readback differs from exact inventory replay")
        return rebuilt


def _strict_row(value: object, model: type[Any], *, label: str) -> dict[str, object]:
    if type(value) is not dict:
        _fail(f"body-blob {label} must be one exact object")
    row = cast("dict[object, object]", value)
    expected = {field.name for field in fields(model)}
    if any(type(key) is not str for key in row) or set(row) != expected:
        _fail(f"body-blob {label} fields are invalid")
    return cast("dict[str, object]", value)


def _construct_exact(model: type[Any], row: dict[str, object], *, label: str) -> Any:
    try:
        candidate = model(**row)
    except (RecursionError, TypeError, ValueError):
        _fail(f"body-blob {label} fields are invalid")
    if type(candidate) is not model:
        _fail(f"body-blob {label} construction returned a foreign type")
    return candidate


def _descriptor_from_value(value: object) -> BodyBlobDescriptorV1:
    row = _strict_row(value, BodyBlobDescriptorV1, label="descriptor")
    return cast(
        "BodyBlobDescriptorV1",
        _construct_exact(BodyBlobDescriptorV1, row, label="descriptor"),
    )


def _reference_from_value(value: object) -> BodyBlobObservationReferenceV1:
    row = _strict_row(value, BodyBlobObservationReferenceV1, label="reference")
    return cast(
        "BodyBlobObservationReferenceV1",
        _construct_exact(BodyBlobObservationReferenceV1, row, label="reference"),
    )


def _inventory_from_value(value: object) -> BodyBlobInventoryV1:
    row = _strict_row(value, BodyBlobInventoryV1, label="inventory")
    descriptor_values = row["descriptors"]
    reference_values = row["references"]
    if type(descriptor_values) is not list or len(descriptor_values) > MAX_AUTHORITY_ROWS:
        _fail("body-blob descriptor inventory is foreign or over-bound")
    if type(reference_values) is not list or len(reference_values) > MAX_AUTHORITY_ROWS:
        _fail("body-blob reference inventory is foreign or over-bound")
    rebuilt_row = dict(row)
    rebuilt_row["descriptors"] = tuple(
        _descriptor_from_value(item) for item in cast("list[object]", descriptor_values)
    )
    rebuilt_row["references"] = tuple(
        _reference_from_value(item) for item in cast("list[object]", reference_values)
    )
    return cast(
        "BodyBlobInventoryV1",
        _construct_exact(BodyBlobInventoryV1, rebuilt_row, label="inventory"),
    )


def _validated_bundle(
    bundle: RawRequestAuthorityBundleV2,
    *,
    expected_raw_authority_bundle_sha256: str,
) -> RawRequestAuthorityBundleV2:
    expected = _exact_sha256(
        expected_raw_authority_bundle_sha256,
        label="expected raw authority bundle",
    )
    if type(bundle) is not RawRequestAuthorityBundleV2:
        _fail("body-blob builder requires one exact Raw-v2 bundle DTO")
    candidate_pin = _exact_sha256(bundle.bundle_sha256, label="candidate raw authority bundle")
    if candidate_pin != expected:
        _fail("body-blob Raw-v2 bundle differs from its external pin")
    try:
        validated = validate_raw_request_authority_bundle(bundle)
    except (RecursionError, TypeError, ValueError):
        _fail("body-blob Raw-v2 bundle is invalid")
    if type(validated) is not RawRequestAuthorityBundleV2 or validated != bundle:
        _fail("body-blob Raw-v2 bundle differs on exact validation")
    return validated


def build_body_blob_inventory(
    bundle: RawRequestAuthorityBundleV2,
    *,
    expected_raw_authority_bundle_sha256: str,
    known_secrets: Sequence[str | bytes] = (),
) -> BodyBlobInventoryV1:
    """Build the complete physical-object and logical-reference inventory."""

    bundle_sha256 = _exact_sha256(
        expected_raw_authority_bundle_sha256,
        label="expected raw authority bundle",
    )
    _admitted_secret_bytes(known_secrets)
    validated = _validated_bundle(
        bundle,
        expected_raw_authority_bundle_sha256=bundle_sha256,
    )
    try:
        observations = canonical_raw_request_observations(validated.observations)
    except RawRequestObservationOrderError:
        _fail("body-blob observations lack one canonical semantic order")

    descriptors: list[BodyBlobDescriptorV1] = []
    descriptor_by_object: dict[str, BodyBlobDescriptorV1] = {}
    for body_object in validated.objects:
        if type(body_object) is not ParserInputObjectV2:
            _fail("body-blob Raw-v2 object inventory contains a foreign DTO")
        try:
            rebuilt_object = ParserInputObjectV2.from_canonical_bytes(
                body_object.to_canonical_bytes()
            )
            raw = decode_parser_input_object(rebuilt_object)
        except (RecursionError, TypeError, ValueError):
            _fail("body-blob Raw-v2 object failed exact replay")
        if rebuilt_object != body_object:
            _fail("body-blob Raw-v2 object differs on exact replay")
        _reject_sensitive_bytes(raw, known_secrets=known_secrets)
        descriptor = BodyBlobDescriptorV1.build(
            raw_authority_bundle_sha256=bundle_sha256,
            parser_input_object=rebuilt_object,
        )
        if rebuilt_object.object_sha256 in descriptor_by_object:
            _fail("body-blob Raw-v2 object inventory is duplicated")
        descriptor_by_object[rebuilt_object.object_sha256] = descriptor
        descriptors.append(descriptor)
    descriptors.sort(key=lambda item: (item.blob_sha256, item.parser_input_object_sha256))

    references: list[BodyBlobObservationReferenceV1] = []
    for observation_ordinal, observation in enumerate(observations):
        if observation.body_disposition != "public_parser_input":
            continue
        object_sha256 = observation.body_object_sha256
        if object_sha256 is None:
            _fail("body-blob body-bearing observation lacks its Raw-v2 object identity")
        descriptor = descriptor_by_object.get(object_sha256)
        if descriptor is None:
            _fail("body-blob body-bearing observation references a foreign object")
        references.append(
            BodyBlobObservationReferenceV1.build(
                raw_authority_bundle_sha256=bundle_sha256,
                reference_ordinal=len(references),
                observation_ordinal=observation_ordinal,
                observation=observation,
                descriptor=descriptor,
            )
        )

    descriptor_tuple = tuple(descriptors)
    reference_tuple = tuple(references)
    descriptor_ids = tuple(item.descriptor_sha256 for item in descriptor_tuple)
    reference_ids = tuple(item.reference_sha256 for item in reference_tuple)
    selected_ids = tuple(
        item.reference_sha256 for item in reference_tuple if item.selection == "selected_terminal"
    )
    incomplete_ids = tuple(
        item.reference_sha256
        for item in reference_tuple
        if item.selection == "downstream_incomplete"
    )
    payload: dict[str, object] = {
        "descriptor_count": len(descriptor_tuple),
        "descriptor_root_sha256": _ordered_root(
            kind=_DESCRIPTOR_ROOT_KIND,
            raw_authority_bundle_sha256=bundle_sha256,
            item_sha256s=descriptor_ids,
        ),
        "descriptors": [item.to_dict() for item in descriptor_tuple],
        "incomplete_reference_count": len(incomplete_ids),
        "incomplete_reference_root_sha256": _ordered_root(
            kind=_INCOMPLETE_REFERENCE_ROOT_KIND,
            raw_authority_bundle_sha256=bundle_sha256,
            item_sha256s=incomplete_ids,
        ),
        "kind": _INVENTORY_KIND,
        "raw_authority_bundle_sha256": bundle_sha256,
        "reference_count": len(reference_tuple),
        "reference_root_sha256": _ordered_root(
            kind=_REFERENCE_ROOT_KIND,
            raw_authority_bundle_sha256=bundle_sha256,
            item_sha256s=reference_ids,
        ),
        "references": [item.to_dict() for item in reference_tuple],
        "schema_version": BODY_BLOB_AUTHORITY_SCHEMA_VERSION,
        "selected_reference_count": len(selected_ids),
        "selected_reference_root_sha256": _ordered_root(
            kind=_SELECTED_REFERENCE_ROOT_KIND,
            raw_authority_bundle_sha256=bundle_sha256,
            item_sha256s=selected_ids,
        ),
        "total_stored_bytes": sum(item.stored_bytes for item in descriptor_tuple),
        "total_uncompressed_bytes": sum(item.uncompressed_bytes for item in descriptor_tuple),
    }
    return BodyBlobInventoryV1(
        schema_version=BODY_BLOB_AUTHORITY_SCHEMA_VERSION,
        kind=_INVENTORY_KIND,
        raw_authority_bundle_sha256=bundle_sha256,
        descriptors=descriptor_tuple,
        descriptor_count=len(descriptor_tuple),
        descriptor_root_sha256=payload["descriptor_root_sha256"],
        references=reference_tuple,
        reference_count=len(reference_tuple),
        reference_root_sha256=payload["reference_root_sha256"],
        selected_reference_count=len(selected_ids),
        selected_reference_root_sha256=payload["selected_reference_root_sha256"],
        incomplete_reference_count=len(incomplete_ids),
        incomplete_reference_root_sha256=payload["incomplete_reference_root_sha256"],
        total_stored_bytes=payload["total_stored_bytes"],
        total_uncompressed_bytes=payload["total_uncompressed_bytes"],
        inventory_sha256=_sha256_json(
            payload,
            maximum_bytes=MAX_BODY_BLOB_CANONICAL_BYTES,
        ),
    )


def validate_body_blob_inventory(
    value: object,
    *,
    bundle: RawRequestAuthorityBundleV2,
    expected_raw_authority_bundle_sha256: str,
    expected_inventory_sha256: str,
    known_secrets: Sequence[str | bytes] = (),
) -> BodyBlobInventoryV1:
    """Rebuild one frozen inventory from its exact externally pinned Raw-v2 source."""

    bundle_sha256 = _exact_sha256(
        expected_raw_authority_bundle_sha256,
        label="expected raw authority bundle",
    )
    inventory_sha256 = _exact_sha256(
        expected_inventory_sha256,
        label="expected body-blob inventory",
    )
    _admitted_secret_bytes(known_secrets)
    if type(value) is not BodyBlobInventoryV1:
        _fail("body-blob inventory has a foreign structured type")
    candidate_pin = _exact_sha256(value.inventory_sha256, label="candidate body-blob inventory")
    candidate_bundle = _exact_sha256(
        value.raw_authority_bundle_sha256,
        label="candidate body-blob raw bundle",
    )
    if candidate_pin != inventory_sha256 or candidate_bundle != bundle_sha256:
        _fail("body-blob inventory differs from its external pins")
    candidate = replace(value)
    rebuilt = build_body_blob_inventory(
        bundle,
        expected_raw_authority_bundle_sha256=bundle_sha256,
        known_secrets=known_secrets,
    )
    if candidate.to_canonical_bytes() != rebuilt.to_canonical_bytes():
        _fail("body-blob inventory differs from exact Raw-v2 reconstruction")
    return rebuilt


def replay_body_blob_inventory(
    encoded: bytes,
    *,
    bundle: RawRequestAuthorityBundleV2,
    expected_raw_authority_bundle_sha256: str,
    expected_inventory_sha256: str,
    known_secrets: Sequence[str | bytes] = (),
) -> BodyBlobInventoryV1:
    """Decode canonical inventory bytes and rederive them from exact Raw-v2 authority."""

    bundle_sha256 = _exact_sha256(
        expected_raw_authority_bundle_sha256,
        label="expected raw authority bundle",
    )
    inventory_sha256 = _exact_sha256(
        expected_inventory_sha256,
        label="expected body-blob inventory",
    )
    _admitted_secret_bytes(known_secrets)
    decoded = _decode_canonical_json(
        encoded,
        maximum_bytes=MAX_BODY_BLOB_CANONICAL_BYTES,
        known_secrets=known_secrets,
    )
    if type(decoded) is not dict:
        _fail("body-blob inventory canonical root must be one exact object")
    raw_row = cast("dict[object, object]", decoded)
    candidate_pin = _exact_sha256(
        raw_row.get("inventory_sha256"),
        label="encoded body-blob inventory",
    )
    candidate_bundle = _exact_sha256(
        raw_row.get("raw_authority_bundle_sha256"),
        label="encoded body-blob raw bundle",
    )
    if candidate_pin != inventory_sha256 or candidate_bundle != bundle_sha256:
        _fail("body-blob inventory bytes differ from external pins")
    candidate = _inventory_from_value(decoded)
    return validate_body_blob_inventory(
        candidate,
        bundle=bundle,
        expected_raw_authority_bundle_sha256=bundle_sha256,
        expected_inventory_sha256=inventory_sha256,
        known_secrets=known_secrets,
    )
