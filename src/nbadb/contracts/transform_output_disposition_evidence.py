"""Replayable evidence primitives for transform-output disposition authority.

This module owns only the bounded canonical codec and the immutable evidence
descriptors needed by the transform-output disposition verifier.  It does not
construct dispositions, infer capabilities, admit proof, or read mutable
checkout state.  Source bytes and typed projections are embedded directly so a
later verifier can replay them without following filesystem references.

Author and reviewer task/role strings intentionally live in a separate audit
DTO.  They are not part of :class:`TransformOutputDispositionProofPackV1` or
its digest and therefore cannot establish independence or admission.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal, Never, Self, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "AUTHORED_SOURCE_BUNDLE_MAX_PROJECTION_MEMBERS_V1",
    "AUTHORED_SOURCE_BUNDLE_RESERVED_MEMBER_COUNT_V1",
    "CANONICAL_JSON_MAX_BYTES",
    "REQUIRED_SOURCE_MEMBER_ROLES_V1",
    "SOURCE_BUNDLE_CANONICAL_MAX_BYTES_V1",
    "SOURCE_BUNDLE_MAX_MEMBER_BYTES_V1",
    "SOURCE_BUNDLE_MAX_MEMBERS_V1",
    "DispositionEvidenceError",
    "SourceMemberRepresentation",
    "SourceMemberRole",
    "TransformOutputDispositionAuditMetadataV1",
    "TransformOutputDispositionProofPackV1",
    "TransformOutputDispositionSourceBundleV1",
    "TransformOutputDispositionSourceMemberV1",
    "TransformOutputDispositionValidationEvidenceV1",
    "ValidationClass",
    "ValidationOutcome",
    "canonical_json_bytes_v1",
    "canonical_json_sha256_v1",
    "decode_canonical_json_bytes_v1",
    "persisted_canonical_json_bytes_v1",
    "validate_authored_source_bundle_representability_v1",
]

type SourceMemberRepresentation = Literal["embedded_bytes", "typed_projection"]
type SourceMemberRole = Literal[
    "authored_entries",
    "dependencies",
    "prior_or_initial_history",
    "proof_inputs",
    "star_projection",
    "structural_discovery",
    "validation_evidence",
    "verifier_source",
]
type ValidationClass = Literal["mutation", "negative", "positive"]
type ValidationOutcome = Literal["accepted", "rejected"]

CANONICAL_JSON_MAX_BYTES = 32 * 1024 * 1024
SOURCE_BUNDLE_CANONICAL_MAX_BYTES_V1 = CANONICAL_JSON_MAX_BYTES
SOURCE_BUNDLE_MAX_MEMBER_BYTES_V1 = 2 * 1024 * 1024
SOURCE_BUNDLE_MAX_MEMBERS_V1 = 4_096
_CANONICAL_JSON_MAX_DEPTH = 48
_CANONICAL_JSON_MAX_NODES = 200_000
_CANONICAL_JSON_MAX_COLLECTION_ITEMS = 20_000
_CANONICAL_JSON_MAX_STRING_BYTES = 4 * 1024 * 1024
_CANONICAL_JSON_MAX_TOTAL_STRING_BYTES = 24 * 1024 * 1024
_CANONICAL_JSON_MAX_NUMBER_TOKEN_BYTES = 128
_CANONICAL_JSON_MAX_INTEGER = (1 << 63) - 1
_MAX_SOURCE_MEMBER_BYTES = SOURCE_BUNDLE_MAX_MEMBER_BYTES_V1
_MAX_SOURCE_MEMBERS = SOURCE_BUNDLE_MAX_MEMBERS_V1
_MAX_VALIDATION_EVIDENCE_ROWS = 20_000
_MAX_MEMBER_PATH_BYTES = 1_024
_MAX_MEMBER_PATH_PARTS = 32
_MAX_MEDIA_TYPE_BYTES = 128
_MAX_AUDIT_ID_BYTES = 512

REQUIRED_SOURCE_MEMBER_ROLES_V1: frozenset[SourceMemberRole] = frozenset(
    {
        "authored_entries",
        "dependencies",
        "prior_or_initial_history",
        "proof_inputs",
        "star_projection",
        "structural_discovery",
        "validation_evidence",
        "verifier_source",
    }
)

# One authored corpus member and one member for each of its table-local evidence
# projections must coexist with at least one member for every other required
# role.  The projection ceiling deliberately retains more than seven evidence
# references per each of the 261 current transform outputs while leaving ample
# graph-node headroom below the general 4,096-member codec ceiling.
AUTHORED_SOURCE_BUNDLE_RESERVED_MEMBER_COUNT_V1 = len(REQUIRED_SOURCE_MEMBER_ROLES_V1)
AUTHORED_SOURCE_BUNDLE_MAX_PROJECTION_MEMBERS_V1 = 2_048
if (
    AUTHORED_SOURCE_BUNDLE_RESERVED_MEMBER_COUNT_V1
    + AUTHORED_SOURCE_BUNDLE_MAX_PROJECTION_MEMBERS_V1
    > SOURCE_BUNDLE_MAX_MEMBERS_V1
):  # pragma: no cover - import-time contract invariant
    raise RuntimeError("authored source-bundle member bounds are inconsistent")

_SOURCE_MEMBER_ROLES = frozenset(REQUIRED_SOURCE_MEMBER_ROLES_V1)
_SOURCE_REPRESENTATIONS = frozenset({"embedded_bytes", "typed_projection"})
_VALIDATION_CLASSES = frozenset({"mutation", "negative", "positive"})
_VALIDATION_OUTCOMES = frozenset({"accepted", "rejected"})
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_SAFE_PATH_PART_RE = re.compile(r"[A-Za-z0-9._-]{1,128}\Z", flags=re.ASCII)
_MEDIA_TYPE_RE = re.compile(
    r"[a-z0-9][a-z0-9!#$&^_.+-]{0,62}/[a-z0-9][a-z0-9!#$&^_.+-]{0,62}\Z",
    flags=re.ASCII,
)
_SAFE_AUDIT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,511}\Z", flags=re.ASCII)
_CANONICAL_BASE64_RE = re.compile(
    r"(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?\Z"
)

_SOURCE_MEMBER_DOMAIN = b"nbadb:transform-output-disposition:source-member:v1"
_SOURCE_MEMBER_INVENTORY_DOMAIN = b"nbadb:transform-output-disposition:source-members:v1"
_SOURCE_BUNDLE_DOMAIN = b"nbadb:transform-output-disposition:source-bundle:v1"
_VALIDATION_EVIDENCE_DOMAIN = b"nbadb:transform-output-disposition:validation-evidence:v1"
_VALIDATION_EVIDENCE_INVENTORY_DOMAIN = (
    b"nbadb:transform-output-disposition:validation-evidence-inventory:v1"
)
_PROOF_PACK_DOMAIN = b"nbadb:transform-output-disposition:proof-pack:v1"
_AUDIT_METADATA_DOMAIN = b"nbadb:transform-output-disposition:audit-metadata:v1"


class DispositionEvidenceError(ValueError):
    """A canonical evidence value is unsafe, incomplete, or inconsistent."""


def _fail(message: str) -> Never:
    raise DispositionEvidenceError(message)


def _validate_json_graph(value: object) -> None:
    stack: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    total_string_bytes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > _CANONICAL_JSON_MAX_NODES:
            _fail("canonical JSON exceeds its node bound")
        if depth > _CANONICAL_JSON_MAX_DEPTH:
            _fail("canonical JSON exceeds its depth bound")
        if item is None or type(item) is bool:
            continue
        if type(item) is int:
            integer = cast("int", item)
            if integer < -_CANONICAL_JSON_MAX_INTEGER or integer > _CANONICAL_JSON_MAX_INTEGER:
                _fail("canonical JSON contains an over-bound integer")
            continue
        if type(item) is float:
            number = cast("float", item)
            if not math.isfinite(number):
                _fail("canonical JSON contains a non-finite number")
            continue
        if type(item) is str:
            try:
                encoded = item.encode("utf-8", errors="strict")
            except UnicodeEncodeError as exc:
                raise DispositionEvidenceError("canonical JSON contains invalid Unicode") from exc
            if len(encoded) > _CANONICAL_JSON_MAX_STRING_BYTES:
                _fail("canonical JSON contains an over-bound string")
            total_string_bytes += len(encoded)
            if total_string_bytes > _CANONICAL_JSON_MAX_TOTAL_STRING_BYTES:
                _fail("canonical JSON exceeds its total string-byte bound")
            continue
        if type(item) is list:
            sequence = cast("list[object]", item)
            if len(sequence) > _CANONICAL_JSON_MAX_COLLECTION_ITEMS:
                _fail("canonical JSON contains an over-bound array")
            stack.extend((child, depth + 1) for child in reversed(sequence))
            continue
        if type(item) is dict:
            mapping = cast("dict[object, object]", item)
            if len(mapping) > _CANONICAL_JSON_MAX_COLLECTION_ITEMS:
                _fail("canonical JSON contains an over-bound object")
            for key, child in reversed(tuple(mapping.items())):
                if type(key) is not str:
                    _fail("canonical JSON object keys must be exact strings")
                try:
                    key_bytes = key.encode("utf-8", errors="strict")
                except UnicodeEncodeError as exc:
                    raise DispositionEvidenceError(
                        "canonical JSON contains an invalid Unicode key"
                    ) from exc
                if len(key_bytes) > _CANONICAL_JSON_MAX_STRING_BYTES:
                    _fail("canonical JSON contains an over-bound object key")
                total_string_bytes += len(key_bytes)
                if total_string_bytes > _CANONICAL_JSON_MAX_TOTAL_STRING_BYTES:
                    _fail("canonical JSON exceeds its total string-byte bound")
                stack.append((child, depth + 1))
            continue
        _fail("canonical JSON contains a foreign exact type")


def canonical_json_bytes_v1(value: object) -> bytes:
    """Encode one bounded exact JSON value without a trailing newline."""

    _validate_json_graph(value)
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8", errors="strict")
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError) as exc:
        raise DispositionEvidenceError("value is not exact canonical JSON") from exc
    if not encoded or len(encoded) > CANONICAL_JSON_MAX_BYTES:
        _fail("canonical JSON byte length is invalid")
    return encoded


def persisted_canonical_json_bytes_v1(value: object) -> bytes:
    """Encode one bounded canonical JSON value with exactly one final LF."""

    return canonical_json_bytes_v1(value) + b"\n"


def canonical_json_sha256_v1(value: object) -> str:
    """Return the SHA-256 of the non-persisted canonical JSON representation."""

    return hashlib.sha256(canonical_json_bytes_v1(value)).hexdigest()


def _preflight_json_bytes(raw: bytes) -> None:
    depth = 0
    structural_tokens = 1
    in_string = False
    escaped = False
    current_string_bytes = 0
    index = 0
    while index < len(raw):
        byte = raw[index]
        if in_string:
            if escaped:
                escaped = False
                current_string_bytes += 1
            elif byte == 0x5C:
                escaped = True
                current_string_bytes += 1
            elif byte == 0x22:
                in_string = False
                if current_string_bytes > _CANONICAL_JSON_MAX_STRING_BYTES:
                    _fail("canonical JSON contains an over-bound string token")
                current_string_bytes = 0
            else:
                current_string_bytes += 1
            index += 1
            continue
        if byte == 0x22:
            in_string = True
        elif byte in (0x7B, 0x5B):
            depth += 1
            structural_tokens += 1
        elif byte in (0x7D, 0x5D):
            depth -= 1
            if depth < 0:
                _fail("canonical JSON is structurally invalid")
        elif byte in (0x2C, 0x3A):
            structural_tokens += 1
        elif byte == 0x2D or 0x30 <= byte <= 0x39:
            end = index + 1
            while end < len(raw) and raw[end] not in b" \t\r\n,]}:":
                end += 1
            if end - index > _CANONICAL_JSON_MAX_NUMBER_TOKEN_BYTES:
                _fail("canonical JSON contains an over-bound number token")
            index = end - 1
        if depth > _CANONICAL_JSON_MAX_DEPTH:
            _fail("canonical JSON exceeds its lexical depth bound")
        if structural_tokens > _CANONICAL_JSON_MAX_NODES * 2:
            _fail("canonical JSON exceeds its lexical structure bound")
        index += 1
    if in_string or escaped or depth != 0:
        _fail("canonical JSON is structurally invalid")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    decoded: dict[str, object] = {}
    for key, value in pairs:
        if key in decoded:
            _fail("canonical JSON contains a duplicate object key")
        decoded[key] = value
    return decoded


def _parse_integer(token: str) -> int:
    if len(token.encode("ascii")) > _CANONICAL_JSON_MAX_NUMBER_TOKEN_BYTES:
        _fail("canonical JSON contains an over-bound integer token")
    value = int(token)
    if value < -_CANONICAL_JSON_MAX_INTEGER or value > _CANONICAL_JSON_MAX_INTEGER:
        _fail("canonical JSON contains an over-bound integer")
    return value


def _parse_float(token: str) -> float:
    if len(token.encode("ascii")) > _CANONICAL_JSON_MAX_NUMBER_TOKEN_BYTES:
        _fail("canonical JSON contains an over-bound float token")
    value = float(token)
    if not math.isfinite(value):
        _fail("canonical JSON contains a non-finite number")
    return value


def _reject_constant(_token: str) -> Never:
    _fail("canonical JSON contains a non-finite constant")


def decode_canonical_json_bytes_v1(raw: object, *, persisted: bool = False) -> object:
    """Decode bounded canonical UTF-8 JSON, optionally requiring one final LF."""

    if type(raw) is not bytes:
        _fail("canonical JSON input must be exact bytes")
    if type(persisted) is not bool:
        _fail("persisted flag must be an exact boolean")
    encoded = raw
    if not encoded or len(encoded) > CANONICAL_JSON_MAX_BYTES + (1 if persisted else 0):
        _fail("canonical JSON input is empty or over-bound")
    if persisted:
        if not encoded.endswith(b"\n"):
            _fail("persisted canonical JSON must end in exactly one LF")
        encoded = encoded[:-1]
        if not encoded:
            _fail("persisted canonical JSON payload is empty")
    _preflight_json_bytes(encoded)
    try:
        text = encoded.decode("utf-8", errors="strict")
        decoded = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_int=_parse_integer,
            parse_float=_parse_float,
            parse_constant=_reject_constant,
        )
    except DispositionEvidenceError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, TypeError, ValueError) as exc:
        raise DispositionEvidenceError("canonical JSON input is invalid") from exc
    _validate_json_graph(decoded)
    if canonical_json_bytes_v1(decoded) != encoded:
        _fail("JSON input is not in exact canonical byte form")
    return decoded


def _domain_sha256(domain: bytes, value: object) -> str:
    digest = hashlib.sha256()
    digest.update(domain)
    digest.update(b"\x00")
    digest.update(canonical_json_bytes_v1(value))
    return digest.hexdigest()


def _require_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{field_name} must be an exact lowercase SHA-256")
    return value


def _require_safe_id(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SAFE_AUDIT_ID_RE.fullmatch(value) is None:
        _fail(f"{field_name} must be an exact bounded safe identifier")
    encoded = value.encode("ascii")
    if len(encoded) > _MAX_AUDIT_ID_BYTES:
        _fail(f"{field_name} exceeds its byte bound")
    return value


def _require_mapping(value: object, *, label: str) -> Mapping[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in cast("dict", value)):
        _fail(f"{label} must be one exact string-keyed object")
    return cast("Mapping[str, object]", value)


def _require_exact_keys(
    value: Mapping[str, object], *, expected: frozenset[str], label: str
) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = ",".join(sorted(expected - actual))
        unexpected = ",".join(sorted(actual - expected))
        _fail(f"{label} fields differ (missing={missing}; unexpected={unexpected})")


def _require_schema_identity(
    value: Mapping[str, object],
    *,
    schema_version: int,
    kind: str,
    label: str,
) -> None:
    if type(value["schema_version"]) is not int or value["schema_version"] != schema_version:
        _fail(f"{label} schema version is invalid")
    if type(value["kind"]) is not str or value["kind"] != kind:
        _fail(f"{label} kind is invalid")


def _require_list(value: object, *, field_name: str, maximum: int) -> list[object]:
    if type(value) is not list or len(cast("list", value)) > maximum:
        _fail(f"{field_name} must be an exact bounded array")
    return cast("list[object]", value)


def _require_normalized_path(value: object) -> str:
    if type(value) is not str:
        _fail("source member path must be an exact string")
    path = value
    try:
        encoded = path.encode("ascii", errors="strict")
    except UnicodeEncodeError as exc:
        raise DispositionEvidenceError("source member path must use safe ASCII") from exc
    if not encoded or len(encoded) > _MAX_MEMBER_PATH_BYTES:
        _fail("source member path length is invalid")
    if path.startswith("/") or path.endswith("/") or "\\" in path or "//" in path:
        _fail("source member path is not a normalized relative POSIX path")
    parts = path.split("/")
    if len(parts) > _MAX_MEMBER_PATH_PARTS:
        _fail("source member path exceeds its component bound")
    if any(part in {"", ".", ".."} or _SAFE_PATH_PART_RE.fullmatch(part) is None for part in parts):
        _fail("source member path contains an unsafe component")
    return path


def _require_media_type(value: object) -> str:
    if type(value) is not str or _MEDIA_TYPE_RE.fullmatch(value) is None:
        _fail("source member media_type must be one normalized media type")
    media_type = value
    if len(media_type.encode("ascii")) > _MAX_MEDIA_TYPE_BYTES:
        _fail("source member media_type exceeds its byte bound")
    return media_type


def _decode_base64(value: object) -> bytes:
    if type(value) is not str or _CANONICAL_BASE64_RE.fullmatch(value) is None:
        _fail("embedded source bytes are not canonical base64")
    text = value
    try:
        decoded = base64.b64decode(text.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError, ValueError) as exc:
        raise DispositionEvidenceError("embedded source bytes are invalid base64") from exc
    if base64.b64encode(decoded).decode("ascii") != text:
        _fail("embedded source bytes are not canonical base64")
    return decoded


@dataclass(frozen=True, slots=True)
class TransformOutputDispositionSourceMemberV1:
    """One safe replay member with embedded exact bytes or a typed projection."""

    normalized_path: str
    role: SourceMemberRole
    media_type: str
    representation: SourceMemberRepresentation
    byte_length: int
    content_sha256: str
    embedded_bytes_base64: str | None
    typed_projection_json: str | None

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_transform_output_disposition_source_member"

    def __post_init__(self) -> None:
        _require_normalized_path(self.normalized_path)
        if type(self.role) is not str or self.role not in _SOURCE_MEMBER_ROLES:
            _fail("source member role is invalid")
        _require_media_type(self.media_type)
        if type(self.representation) is not str or self.representation not in (
            _SOURCE_REPRESENTATIONS
        ):
            _fail("source member representation is invalid")
        if (
            type(self.byte_length) is not int
            or self.byte_length <= 0
            or self.byte_length > _MAX_SOURCE_MEMBER_BYTES
        ):
            _fail("source member byte_length is invalid")
        _require_sha256(self.content_sha256, field_name="source member content_sha256")
        content: bytes
        if self.representation == "embedded_bytes":
            if self.typed_projection_json is not None:
                _fail("embedded source bytes cannot also contain a typed projection")
            content = _decode_base64(self.embedded_bytes_base64)
        else:
            if self.embedded_bytes_base64 is not None:
                _fail("typed source projection cannot also contain embedded bytes")
            if type(self.typed_projection_json) is not str:
                _fail("typed source projection must contain canonical JSON text")
            try:
                content = self.typed_projection_json.encode("utf-8", errors="strict")
            except UnicodeEncodeError as exc:
                raise DispositionEvidenceError(
                    "typed source projection contains invalid Unicode"
                ) from exc
            decode_canonical_json_bytes_v1(content)
        if not content or len(content) != self.byte_length:
            _fail("source member content length differs from byte_length")
        if hashlib.sha256(content).hexdigest() != self.content_sha256:
            _fail("source member content digest differs from content_sha256")

    @classmethod
    def from_embedded_bytes(
        cls,
        *,
        normalized_path: str,
        role: SourceMemberRole,
        media_type: str,
        content: bytes,
    ) -> Self:
        if type(content) is not bytes or not content or len(content) > _MAX_SOURCE_MEMBER_BYTES:
            _fail("embedded source content must be exact nonempty bounded bytes")
        return cls(
            normalized_path=normalized_path,
            role=role,
            media_type=media_type,
            representation="embedded_bytes",
            byte_length=len(content),
            content_sha256=hashlib.sha256(content).hexdigest(),
            embedded_bytes_base64=base64.b64encode(content).decode("ascii"),
            typed_projection_json=None,
        )

    @classmethod
    def from_typed_projection(
        cls,
        *,
        normalized_path: str,
        role: SourceMemberRole,
        media_type: str,
        projection: object,
    ) -> Self:
        content = canonical_json_bytes_v1(projection)
        if len(content) > _MAX_SOURCE_MEMBER_BYTES:
            _fail("typed source projection exceeds its member byte bound")
        return cls(
            normalized_path=normalized_path,
            role=role,
            media_type=media_type,
            representation="typed_projection",
            byte_length=len(content),
            content_sha256=hashlib.sha256(content).hexdigest(),
            embedded_bytes_base64=None,
            typed_projection_json=content.decode("utf-8"),
        )

    @property
    def content_bytes(self) -> bytes:
        if self.representation == "embedded_bytes":
            return _decode_base64(self.embedded_bytes_base64)
        if type(self.typed_projection_json) is not str:  # pragma: no cover - constructor guard
            _fail("typed source projection is absent")
        return self.typed_projection_json.encode("utf-8")

    @property
    def typed_projection(self) -> object:
        if self.representation != "typed_projection":
            _fail("embedded source bytes do not expose a typed projection")
        return decode_canonical_json_bytes_v1(self.content_bytes)

    def _digest_preimage(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "normalized_path": self.normalized_path,
            "role": self.role,
            "media_type": self.media_type,
            "representation": self.representation,
            "byte_length": self.byte_length,
            "content_sha256": self.content_sha256,
            "embedded_bytes_base64": self.embedded_bytes_base64,
            "typed_projection_json": self.typed_projection_json,
        }

    @property
    def member_sha256(self) -> str:
        return _domain_sha256(_SOURCE_MEMBER_DOMAIN, self._digest_preimage())

    def to_dict(self) -> dict[str, object]:
        return {**self._digest_preimage(), "member_sha256": self.member_sha256}

    @property
    def canonical_bytes(self) -> bytes:
        return persisted_canonical_json_bytes_v1(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="source member")
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "normalized_path",
                    "role",
                    "media_type",
                    "representation",
                    "byte_length",
                    "content_sha256",
                    "embedded_bytes_base64",
                    "typed_projection_json",
                    "member_sha256",
                }
            ),
            label="source member",
        )
        _require_schema_identity(
            payload,
            schema_version=cls.schema_version,
            kind=cls.kind,
            label="source member",
        )
        member = cls(
            normalized_path=cast("str", payload["normalized_path"]),
            role=cast("SourceMemberRole", payload["role"]),
            media_type=cast("str", payload["media_type"]),
            representation=cast("SourceMemberRepresentation", payload["representation"]),
            byte_length=cast("int", payload["byte_length"]),
            content_sha256=cast("str", payload["content_sha256"]),
            embedded_bytes_base64=cast("str | None", payload["embedded_bytes_base64"]),
            typed_projection_json=cast("str | None", payload["typed_projection_json"]),
        )
        if payload["member_sha256"] != member.member_sha256:
            _fail("source member digest is invalid")
        return member

    @classmethod
    def from_canonical_bytes(cls, raw: object) -> Self:
        return cls.from_dict(decode_canonical_json_bytes_v1(raw, persisted=True))


@dataclass(frozen=True, slots=True)
class TransformOutputDispositionSourceBundleV1:
    """Complete ordered replay bundle covering every required evidence role."""

    members: tuple[TransformOutputDispositionSourceMemberV1, ...]

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_transform_output_disposition_source_bundle"

    def __post_init__(self) -> None:
        if (
            type(self.members) is not tuple
            or not self.members
            or len(self.members) > _MAX_SOURCE_MEMBERS
            or any(
                type(item) is not TransformOutputDispositionSourceMemberV1 for item in self.members
            )
        ):
            _fail("source bundle members must be one nonempty bounded typed tuple")
        if self.members != tuple(sorted(self.members, key=lambda item: item.normalized_path)):
            _fail("source bundle members must be sorted by normalized path")
        paths = tuple(item.normalized_path for item in self.members)
        if len(set(paths)) != len(paths):
            _fail("source bundle contains a duplicate normalized path")
        roles = frozenset(item.role for item in self.members)
        if roles != REQUIRED_SOURCE_MEMBER_ROLES_V1:
            missing = ",".join(sorted(REQUIRED_SOURCE_MEMBER_ROLES_V1 - roles))
            unexpected = ",".join(sorted(roles - REQUIRED_SOURCE_MEMBER_ROLES_V1))
            _fail(
                f"source bundle roles are incomplete (missing={missing}; unexpected={unexpected})"
            )
        # A constructed bundle must already be persistable.  Deferring this
        # check to ``canonical_bytes`` would permit an immutable DTO whose
        # mandatory root cannot be derived under the canonical graph bounds.
        canonical = canonical_json_bytes_v1(self.to_dict())
        if len(canonical) > SOURCE_BUNDLE_CANONICAL_MAX_BYTES_V1:
            _fail("source bundle exceeds its versioned canonical byte bound")

    @property
    def member_count(self) -> int:
        return len(self.members)

    @property
    def member_inventory_root_sha256(self) -> str:
        return _domain_sha256(
            _SOURCE_MEMBER_INVENTORY_DOMAIN,
            [item.member_sha256 for item in self.members],
        )

    def _digest_preimage(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "members": [item.to_dict() for item in self.members],
            "member_count": self.member_count,
            "member_inventory_root_sha256": self.member_inventory_root_sha256,
        }

    @property
    def source_bundle_root_sha256(self) -> str:
        return _domain_sha256(_SOURCE_BUNDLE_DOMAIN, self._digest_preimage())

    def to_dict(self) -> dict[str, object]:
        return {
            **self._digest_preimage(),
            "source_bundle_root_sha256": self.source_bundle_root_sha256,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return persisted_canonical_json_bytes_v1(self.to_dict())

    def members_for_role(
        self, role: SourceMemberRole
    ) -> tuple[TransformOutputDispositionSourceMemberV1, ...]:
        if type(role) is not str or role not in _SOURCE_MEMBER_ROLES:
            _fail("source member role projection is invalid")
        return tuple(item for item in self.members if item.role == role)

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="source bundle")
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "members",
                    "member_count",
                    "member_inventory_root_sha256",
                    "source_bundle_root_sha256",
                }
            ),
            label="source bundle",
        )
        _require_schema_identity(
            payload,
            schema_version=cls.schema_version,
            kind=cls.kind,
            label="source bundle",
        )
        rows = _require_list(
            payload["members"], field_name="source bundle members", maximum=_MAX_SOURCE_MEMBERS
        )
        bundle = cls(
            members=tuple(TransformOutputDispositionSourceMemberV1.from_dict(row) for row in rows)
        )
        if (
            type(payload["member_count"]) is not int
            or payload["member_count"] != bundle.member_count
        ):
            _fail("source bundle member count is invalid")
        if payload["member_inventory_root_sha256"] != bundle.member_inventory_root_sha256:
            _fail("source bundle member inventory root is invalid")
        if payload["source_bundle_root_sha256"] != bundle.source_bundle_root_sha256:
            _fail("source bundle root is invalid")
        return bundle

    @classmethod
    def from_canonical_bytes(cls, raw: object) -> Self:
        return cls.from_dict(decode_canonical_json_bytes_v1(raw, persisted=True))


_AUTHORED_CORPUS_SOURCE_PATH_V1 = "transform-output-disposition/authored-entries-v1.json"
_AUTHORED_REPRESENTABILITY_OTHER_MEMBERS_V1: tuple[
    tuple[str, SourceMemberRole, str, bytes], ...
] = (
    (
        "transform-output-disposition/dependencies-v1.json",
        "dependencies",
        "application/json",
        b"{}",
    ),
    (
        "transform-output-disposition/prior-or-initial-history-v1.json",
        "prior_or_initial_history",
        "application/json",
        b"{}",
    ),
    (
        "transform-output-disposition/proof-inputs-v1.json",
        "proof_inputs",
        "application/json",
        b"{}",
    ),
    (
        "transform-output-disposition/star-projection-v1.json",
        "star_projection",
        "application/json",
        b"{}",
    ),
    (
        "transform-output-disposition/structural-discovery-v1.json",
        "structural_discovery",
        "application/json",
        b"{}",
    ),
    (
        "transform-output-disposition/validation-evidence-v1.json",
        "validation_evidence",
        "application/json",
        b"{}",
    ),
    (
        "src/nbadb/contracts/transform_output_disposition_verifier.py",
        "verifier_source",
        "text/x-python",
        b"#\n",
    ),
)


def validate_authored_source_bundle_representability_v1(
    *,
    corpus_bytes: bytes,
    evidence_projection_members: tuple[tuple[str, bytes], ...],
) -> int:
    """Construct the minimum complete bundle for one authored corpus.

    The returned length excludes the persisted final LF.  Construction is the
    proof: it accounts for the corpus and every table-local projection being
    duplicated as embedded base64 members, all member metadata and digests, the
    seven other mandatory roles, graph bounds, member bounds, and the canonical
    32 MiB bundle bound.
    """

    if type(corpus_bytes) is not bytes or not corpus_bytes:
        _fail("authored corpus source bytes must be exact nonempty bytes")
    if (
        type(evidence_projection_members) is not tuple
        or len(evidence_projection_members) > AUTHORED_SOURCE_BUNDLE_MAX_PROJECTION_MEMBERS_V1
    ):
        _fail("authored evidence projection member count is unrepresentable")
    projection_members: list[TransformOutputDispositionSourceMemberV1] = []
    for item in evidence_projection_members:
        if (
            type(item) is not tuple
            or len(item) != 2
            or type(item[0]) is not str
            or type(item[1]) is not bytes
        ):
            _fail("authored evidence projection member descriptor is invalid")
        projection_members.append(
            TransformOutputDispositionSourceMemberV1.from_embedded_bytes(
                normalized_path=item[0],
                role="authored_entries",
                media_type="application/json",
                content=item[1],
            )
        )
    members = [
        TransformOutputDispositionSourceMemberV1.from_embedded_bytes(
            normalized_path=_AUTHORED_CORPUS_SOURCE_PATH_V1,
            role="authored_entries",
            media_type="application/json",
            content=corpus_bytes,
        ),
        *projection_members,
        *(
            TransformOutputDispositionSourceMemberV1.from_embedded_bytes(
                normalized_path=path,
                role=role,
                media_type=media_type,
                content=content,
            )
            for path, role, media_type, content in (_AUTHORED_REPRESENTABILITY_OTHER_MEMBERS_V1)
        ),
    ]
    expected_member_count = (
        len(evidence_projection_members) + AUTHORED_SOURCE_BUNDLE_RESERVED_MEMBER_COUNT_V1
    )
    if len(members) != expected_member_count or len(members) > SOURCE_BUNDLE_MAX_MEMBERS_V1:
        _fail("authored source-bundle member count is unrepresentable")
    bundle = TransformOutputDispositionSourceBundleV1(
        members=tuple(sorted(members, key=lambda member: member.normalized_path))
    )
    canonical_byte_length = len(bundle.canonical_bytes) - 1
    if canonical_byte_length > SOURCE_BUNDLE_CANONICAL_MAX_BYTES_V1:
        _fail("authored source bundle exceeds its canonical byte bound")
    return canonical_byte_length


@dataclass(frozen=True, slots=True, order=True)
class TransformOutputDispositionValidationEvidenceV1:
    """One replay case proving a positive, negative, or mutation outcome."""

    case_id: str
    validation_class: ValidationClass
    proof_input_member_sha256: str
    evidence_member_sha256s: tuple[str, ...]
    expected_outcome: ValidationOutcome
    observed_outcome: ValidationOutcome

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_transform_output_disposition_validation_evidence"

    def __post_init__(self) -> None:
        _require_safe_id(self.case_id, field_name="validation evidence case_id")
        if type(self.validation_class) is not str or self.validation_class not in (
            _VALIDATION_CLASSES
        ):
            _fail("validation evidence class is invalid")
        _require_sha256(
            self.proof_input_member_sha256,
            field_name="validation evidence proof_input_member_sha256",
        )
        if (
            type(self.evidence_member_sha256s) is not tuple
            or not self.evidence_member_sha256s
            or len(self.evidence_member_sha256s) > _MAX_SOURCE_MEMBERS
        ):
            _fail("validation evidence member digests must be one nonempty tuple")
        if self.evidence_member_sha256s != tuple(sorted(set(self.evidence_member_sha256s))):
            _fail("validation evidence member digests must be sorted and unique")
        for digest in self.evidence_member_sha256s:
            _require_sha256(digest, field_name="validation evidence member digest")
        if type(self.expected_outcome) is not str or self.expected_outcome not in (
            _VALIDATION_OUTCOMES
        ):
            _fail("validation evidence expected outcome is invalid")
        if type(self.observed_outcome) is not str or self.observed_outcome not in (
            _VALIDATION_OUTCOMES
        ):
            _fail("validation evidence observed outcome is invalid")
        required_expected = "accepted" if self.validation_class == "positive" else "rejected"
        if self.expected_outcome != required_expected:
            _fail("validation evidence class has an incompatible expected outcome")

    @property
    def passed(self) -> bool:
        return self.expected_outcome == self.observed_outcome

    def _digest_preimage(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "case_id": self.case_id,
            "validation_class": self.validation_class,
            "proof_input_member_sha256": self.proof_input_member_sha256,
            "evidence_member_sha256s": list(self.evidence_member_sha256s),
            "expected_outcome": self.expected_outcome,
            "observed_outcome": self.observed_outcome,
            "passed": self.passed,
        }

    @property
    def evidence_sha256(self) -> str:
        return _domain_sha256(_VALIDATION_EVIDENCE_DOMAIN, self._digest_preimage())

    def to_dict(self) -> dict[str, object]:
        return {**self._digest_preimage(), "evidence_sha256": self.evidence_sha256}

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="validation evidence")
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "case_id",
                    "validation_class",
                    "proof_input_member_sha256",
                    "evidence_member_sha256s",
                    "expected_outcome",
                    "observed_outcome",
                    "passed",
                    "evidence_sha256",
                }
            ),
            label="validation evidence",
        )
        _require_schema_identity(
            payload,
            schema_version=cls.schema_version,
            kind=cls.kind,
            label="validation evidence",
        )
        evidence_member_sha256s = _require_list(
            payload["evidence_member_sha256s"],
            field_name="validation evidence member digests",
            maximum=_MAX_SOURCE_MEMBERS,
        )
        evidence = cls(
            case_id=cast("str", payload["case_id"]),
            validation_class=cast("ValidationClass", payload["validation_class"]),
            proof_input_member_sha256=cast("str", payload["proof_input_member_sha256"]),
            evidence_member_sha256s=tuple(cast("list[str]", evidence_member_sha256s)),
            expected_outcome=cast("ValidationOutcome", payload["expected_outcome"]),
            observed_outcome=cast("ValidationOutcome", payload["observed_outcome"]),
        )
        if type(payload["passed"]) is not bool or payload["passed"] != evidence.passed:
            _fail("validation evidence passed flag is invalid")
        if payload["evidence_sha256"] != evidence.evidence_sha256:
            _fail("validation evidence digest is invalid")
        return evidence


@dataclass(frozen=True, slots=True)
class TransformOutputDispositionProofPackV1:
    """Complete typed proof input; structural validity is not admission."""

    source_bundle: TransformOutputDispositionSourceBundleV1
    claimed_reconstructed_result_sha256: str
    validation_evidence: tuple[TransformOutputDispositionValidationEvidenceV1, ...]

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_transform_output_disposition_proof_pack"

    def __post_init__(self) -> None:
        if type(self.source_bundle) is not TransformOutputDispositionSourceBundleV1:
            _fail("proof pack source bundle is not the exact typed DTO")
        _require_sha256(
            self.claimed_reconstructed_result_sha256,
            field_name="proof pack claimed reconstructed result digest",
        )
        if (
            type(self.validation_evidence) is not tuple
            or not self.validation_evidence
            or len(self.validation_evidence) > _MAX_VALIDATION_EVIDENCE_ROWS
            or any(
                type(item) is not TransformOutputDispositionValidationEvidenceV1
                for item in self.validation_evidence
            )
        ):
            _fail("proof pack validation evidence must be one nonempty bounded typed tuple")
        expected_order = tuple(
            sorted(self.validation_evidence, key=lambda item: (item.case_id, item.validation_class))
        )
        if self.validation_evidence != expected_order:
            _fail("proof pack validation evidence must be canonically ordered")
        if len({item.case_id for item in self.validation_evidence}) != len(
            self.validation_evidence
        ):
            _fail("proof pack validation evidence case identities must be unique")
        if {item.validation_class for item in self.validation_evidence} != _VALIDATION_CLASSES:
            _fail("proof pack requires positive, negative, and mutation evidence")
        if any(not item.passed for item in self.validation_evidence):
            _fail("proof pack contains validation evidence that did not pass")

        proof_input_members = frozenset(
            item.member_sha256 for item in self.source_bundle.members_for_role("proof_inputs")
        )
        validation_members = frozenset(
            item.member_sha256
            for item in self.source_bundle.members_for_role("validation_evidence")
        )
        used_proof_inputs = frozenset(
            item.proof_input_member_sha256 for item in self.validation_evidence
        )
        used_validation_members = frozenset(
            digest for item in self.validation_evidence for digest in item.evidence_member_sha256s
        )
        if used_proof_inputs != proof_input_members:
            _fail("proof pack validation rows do not close the exact proof-input inventory")
        if used_validation_members != validation_members:
            _fail("proof pack validation rows do not close the exact evidence inventory")
        # As with the source bundle, prove eagerly that the complete immutable
        # proof pack (including nested source and validation rows) fits every
        # canonical byte/node/collection/string bound.
        canonical_json_bytes_v1(self.to_dict())

    @property
    def verifier_source_member_sha256s(self) -> tuple[str, ...]:
        return tuple(
            item.member_sha256 for item in self.source_bundle.members_for_role("verifier_source")
        )

    @property
    def proof_input_member_sha256s(self) -> tuple[str, ...]:
        return tuple(
            item.member_sha256 for item in self.source_bundle.members_for_role("proof_inputs")
        )

    @property
    def validation_evidence_member_sha256s(self) -> tuple[str, ...]:
        return tuple(
            item.member_sha256
            for item in self.source_bundle.members_for_role("validation_evidence")
        )

    @property
    def validation_evidence_root_sha256(self) -> str:
        return _domain_sha256(
            _VALIDATION_EVIDENCE_INVENTORY_DOMAIN,
            [item.evidence_sha256 for item in self.validation_evidence],
        )

    def _digest_preimage(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "source_bundle": self.source_bundle.to_dict(),
            "source_bundle_root_sha256": self.source_bundle.source_bundle_root_sha256,
            "verifier_source_member_sha256s": list(self.verifier_source_member_sha256s),
            "proof_input_member_sha256s": list(self.proof_input_member_sha256s),
            "validation_evidence_member_sha256s": list(self.validation_evidence_member_sha256s),
            "claimed_reconstructed_result_sha256": (self.claimed_reconstructed_result_sha256),
            "validation_evidence": [item.to_dict() for item in self.validation_evidence],
            "validation_evidence_root_sha256": self.validation_evidence_root_sha256,
        }

    @property
    def proof_pack_root_sha256(self) -> str:
        return _domain_sha256(_PROOF_PACK_DOMAIN, self._digest_preimage())

    def to_dict(self) -> dict[str, object]:
        return {**self._digest_preimage(), "proof_pack_root_sha256": self.proof_pack_root_sha256}

    @property
    def canonical_bytes(self) -> bytes:
        return persisted_canonical_json_bytes_v1(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="proof pack")
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "source_bundle",
                    "source_bundle_root_sha256",
                    "verifier_source_member_sha256s",
                    "proof_input_member_sha256s",
                    "validation_evidence_member_sha256s",
                    "claimed_reconstructed_result_sha256",
                    "validation_evidence",
                    "validation_evidence_root_sha256",
                    "proof_pack_root_sha256",
                }
            ),
            label="proof pack",
        )
        _require_schema_identity(
            payload,
            schema_version=cls.schema_version,
            kind=cls.kind,
            label="proof pack",
        )
        source_bundle = TransformOutputDispositionSourceBundleV1.from_dict(payload["source_bundle"])
        rows = _require_list(
            payload["validation_evidence"],
            field_name="proof pack validation evidence",
            maximum=_MAX_VALIDATION_EVIDENCE_ROWS,
        )
        proof_pack = cls(
            source_bundle=source_bundle,
            claimed_reconstructed_result_sha256=cast(
                "str", payload["claimed_reconstructed_result_sha256"]
            ),
            validation_evidence=tuple(
                TransformOutputDispositionValidationEvidenceV1.from_dict(row) for row in rows
            ),
        )
        exact_fields: tuple[tuple[str, object], ...] = (
            ("source_bundle_root_sha256", proof_pack.source_bundle.source_bundle_root_sha256),
            (
                "verifier_source_member_sha256s",
                list(proof_pack.verifier_source_member_sha256s),
            ),
            ("proof_input_member_sha256s", list(proof_pack.proof_input_member_sha256s)),
            (
                "validation_evidence_member_sha256s",
                list(proof_pack.validation_evidence_member_sha256s),
            ),
            ("validation_evidence_root_sha256", proof_pack.validation_evidence_root_sha256),
            ("proof_pack_root_sha256", proof_pack.proof_pack_root_sha256),
        )
        for field_name, expected in exact_fields:
            if payload[field_name] != expected:
                _fail(f"proof pack {field_name} is invalid")
        return proof_pack

    @classmethod
    def from_canonical_bytes(cls, raw: object) -> Self:
        return cls.from_dict(decode_canonical_json_bytes_v1(raw, persisted=True))


@dataclass(frozen=True, slots=True)
class TransformOutputDispositionAuditMetadataV1:
    """Non-admitting author/reviewer labels bound separately to one proof pack."""

    proof_pack_root_sha256: str
    author_task_id: str
    author_role: str
    reviewer_task_id: str
    reviewer_role: str

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "nbadb_transform_output_disposition_audit_metadata"
    establishes_independence: ClassVar[bool] = False

    def __post_init__(self) -> None:
        _require_sha256(
            self.proof_pack_root_sha256,
            field_name="audit metadata proof_pack_root_sha256",
        )
        _require_safe_id(self.author_task_id, field_name="audit metadata author_task_id")
        _require_safe_id(self.author_role, field_name="audit metadata author_role")
        _require_safe_id(self.reviewer_task_id, field_name="audit metadata reviewer_task_id")
        _require_safe_id(self.reviewer_role, field_name="audit metadata reviewer_role")

    def _digest_preimage(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "proof_pack_root_sha256": self.proof_pack_root_sha256,
            "author_task_id": self.author_task_id,
            "author_role": self.author_role,
            "reviewer_task_id": self.reviewer_task_id,
            "reviewer_role": self.reviewer_role,
            "establishes_independence": self.establishes_independence,
        }

    @property
    def audit_metadata_sha256(self) -> str:
        return _domain_sha256(_AUDIT_METADATA_DOMAIN, self._digest_preimage())

    def to_dict(self) -> dict[str, object]:
        return {
            **self._digest_preimage(),
            "audit_metadata_sha256": self.audit_metadata_sha256,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return persisted_canonical_json_bytes_v1(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> Self:
        payload = _require_mapping(value, label="audit metadata")
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "proof_pack_root_sha256",
                    "author_task_id",
                    "author_role",
                    "reviewer_task_id",
                    "reviewer_role",
                    "establishes_independence",
                    "audit_metadata_sha256",
                }
            ),
            label="audit metadata",
        )
        _require_schema_identity(
            payload,
            schema_version=cls.schema_version,
            kind=cls.kind,
            label="audit metadata",
        )
        if payload["establishes_independence"] is not False:
            _fail("audit metadata cannot establish independence")
        metadata = cls(
            proof_pack_root_sha256=cast("str", payload["proof_pack_root_sha256"]),
            author_task_id=cast("str", payload["author_task_id"]),
            author_role=cast("str", payload["author_role"]),
            reviewer_task_id=cast("str", payload["reviewer_task_id"]),
            reviewer_role=cast("str", payload["reviewer_role"]),
        )
        if payload["audit_metadata_sha256"] != metadata.audit_metadata_sha256:
            _fail("audit metadata digest is invalid")
        return metadata

    @classmethod
    def from_canonical_bytes(cls, raw: object) -> Self:
        return cls.from_dict(decode_canonical_json_bytes_v1(raw, persisted=True))
