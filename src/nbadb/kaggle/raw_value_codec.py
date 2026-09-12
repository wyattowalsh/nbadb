"""Canonical scalar codec for public raw-table convenience projections.

DuckDB and Parquet retain native scalar types. CSV and SQLite use the ASCII
JSON envelope defined here for raw binary-capable fields so that a logical null,
empty bytes, and empty text remain distinct after either convenience projection.

The version-1 semantic digest is SHA-256 over::

    b"nbadb.raw.scalar\\x00v1\\x00" + kind.encode("ascii") + b"\\x00" + payload

For ``null`` the digest payload is empty while the encoded ``payload_base64``
and ``byte_length`` fields are JSON null. Bytes and UTF-8 text use canonical
RFC 4648 base64 with padding where required.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from typing import Final, Literal, Never, cast

__all__ = [
    "RAW_VALUE_CODEC_SCHEMA_VERSION",
    "RAW_VALUE_CODEC_TAG",
    "RawScalarValue",
    "RawValueCodecError",
    "RawValueKind",
    "decode_raw_value",
    "encode_raw_value",
]

RAW_VALUE_CODEC_SCHEMA_VERSION: Final = 1
RAW_VALUE_CODEC_TAG: Final = "nbadb.raw.scalar"

type RawValueKind = Literal["null", "bytes", "text"]
type RawScalarValue = None | bytes | str

_ENVELOPE_KEYS = frozenset(
    {
        "byte_length",
        "kind",
        "payload_base64",
        "schema_version",
        "tag",
        "value_sha256",
    }
)
_VALUE_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_DIGEST_DOMAIN = f"{RAW_VALUE_CODEC_TAG}\x00v{RAW_VALUE_CODEC_SCHEMA_VERSION}\x00".encode("ascii")


class RawValueCodecError(ValueError):
    """A raw scalar or encoded envelope violates the public codec contract."""


def _semantic_sha256(kind: RawValueKind, payload: bytes) -> str:
    return hashlib.sha256(_DIGEST_DOMAIN + kind.encode("ascii") + b"\x00" + payload).hexdigest()


def _canonical_json(value: dict[str, object]) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def encode_raw_value(value: RawScalarValue) -> str:
    """Encode one null, byte string, or text string as canonical ASCII JSON."""

    if value is None:
        kind: RawValueKind = "null"
        payload = b""
        payload_base64: str | None = None
        byte_length: int | None = None
    elif type(value) is bytes:
        kind = "bytes"
        payload = value
        payload_base64 = base64.b64encode(payload).decode("ascii")
        byte_length = len(payload)
    elif type(value) is str:
        kind = "text"
        try:
            payload = value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise RawValueCodecError("raw text value is not valid UTF-8") from exc
        payload_base64 = base64.b64encode(payload).decode("ascii")
        byte_length = len(payload)
    else:
        raise RawValueCodecError("raw scalar must be exactly null, bytes, or text")

    return _canonical_json(
        {
            "byte_length": byte_length,
            "kind": kind,
            "payload_base64": payload_base64,
            "schema_version": RAW_VALUE_CODEC_SCHEMA_VERSION,
            "tag": RAW_VALUE_CODEC_TAG,
            "value_sha256": _semantic_sha256(kind, payload),
        }
    )


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, member in pairs:
        if key in value:
            raise RawValueCodecError("raw scalar envelope contains a duplicate key")
        value[key] = member
    return value


def _reject_json_constant(_value: str) -> Never:
    raise RawValueCodecError("raw scalar envelope contains a non-finite number")


def _parse_envelope(encoded: str) -> dict[str, object]:
    try:
        parsed = json.loads(
            encoded,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except RawValueCodecError:
        raise
    except (json.JSONDecodeError, RecursionError) as exc:
        raise RawValueCodecError("raw scalar envelope is not valid JSON") from exc
    if type(parsed) is not dict:
        raise RawValueCodecError("raw scalar envelope must be a JSON object")
    envelope = cast("dict[str, object]", parsed)
    if set(envelope) != _ENVELOPE_KEYS:
        raise RawValueCodecError("raw scalar envelope fields do not match schema version 1")
    return envelope


def _validated_header(envelope: dict[str, object]) -> RawValueKind:
    schema_version = envelope["schema_version"]
    if type(schema_version) is not int or schema_version != RAW_VALUE_CODEC_SCHEMA_VERSION:
        raise RawValueCodecError("raw scalar envelope schema version is unsupported")
    tag = envelope["tag"]
    if type(tag) is not str or tag != RAW_VALUE_CODEC_TAG:
        raise RawValueCodecError("raw scalar envelope tag is invalid")
    kind = envelope["kind"]
    if type(kind) is not str or kind not in {"null", "bytes", "text"}:
        raise RawValueCodecError("raw scalar envelope kind is invalid")
    return cast("RawValueKind", kind)


def _validated_digest(envelope: dict[str, object]) -> str:
    value_sha256 = envelope["value_sha256"]
    if type(value_sha256) is not str or _VALUE_SHA256_RE.fullmatch(value_sha256) is None:
        raise RawValueCodecError("raw scalar envelope digest is invalid")
    return value_sha256


def _decode_payload(envelope: dict[str, object], kind: RawValueKind) -> bytes:
    payload_base64 = envelope["payload_base64"]
    byte_length = envelope["byte_length"]
    if kind == "null":
        if payload_base64 is not None or byte_length is not None:
            raise RawValueCodecError("raw null envelope must not contain a payload")
        return b""
    if type(payload_base64) is not str:
        raise RawValueCodecError("raw scalar payload must be canonical base64 text")
    if type(byte_length) is not int or byte_length < 0:
        raise RawValueCodecError("raw scalar byte length is invalid")
    try:
        payload = base64.b64decode(payload_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RawValueCodecError("raw scalar payload is not valid base64") from exc
    if base64.b64encode(payload).decode("ascii") != payload_base64:
        raise RawValueCodecError("raw scalar payload is not canonical base64")
    if len(payload) != byte_length:
        raise RawValueCodecError("raw scalar payload length does not match its envelope")
    return payload


def decode_raw_value(encoded: str) -> RawScalarValue:
    """Decode and fully revalidate one canonical version-1 scalar envelope."""

    if type(encoded) is not str:
        raise RawValueCodecError("encoded raw scalar must be exactly text")
    envelope = _parse_envelope(encoded)
    kind = _validated_header(envelope)
    value_sha256 = _validated_digest(envelope)
    payload = _decode_payload(envelope, kind)
    if _semantic_sha256(kind, payload) != value_sha256:
        raise RawValueCodecError("raw scalar semantic digest does not match")

    if kind == "null":
        value: RawScalarValue = None
    elif kind == "bytes":
        value = payload
    else:
        try:
            value = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise RawValueCodecError("raw text payload is not valid UTF-8") from exc

    if encode_raw_value(value) != encoded:
        raise RawValueCodecError("raw scalar envelope is not canonical JSON")
    return value
