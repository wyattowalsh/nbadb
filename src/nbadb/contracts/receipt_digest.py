"""Bounded canonical encoding and digests for the new assurance receipts.

This module owns only the narrow canonical codec used by the new receipt
family (operation authority, hard DATA receipts, dispositions, handoffs, and
recovery evidence).  It deliberately does not migrate or share state with the
existing contract-local digest encoders such as
:func:`nbadb.contracts.transform_output_disposition_evidence.canonical_json_bytes_v1`.

Encoding is deterministic: mappings sort by key, strings escape to ASCII, and
separators are compact.  Validation happens before encoding so an unencodable
or oversized receipt never produces partial bytes.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import fields, is_dataclass
from typing import Any, Final

__all__ = [
    "CANONICAL_RECEIPT_MAX_BYTES",
    "RECEIPT_MAX_COLLECTION_ENTRIES",
    "RECEIPT_MAX_NESTING_DEPTH",
    "RECEIPT_MAX_STRING_CHARS",
    "CanonicalReceiptError",
    "canonical_receipt_bytes",
    "canonical_receipt_digest",
    "dataclass_receipt_payload",
    "verify_receipt_digest",
]

#: Hard bound for one canonical receipt (8 MiB).
CANONICAL_RECEIPT_MAX_BYTES: Final = 8 * 1024 * 1024

#: Hard bound for a single string value (1 MiB of characters).
RECEIPT_MAX_STRING_CHARS: Final = 1024 * 1024

#: Hard bound for one mapping or sequence (100,000 entries).
RECEIPT_MAX_COLLECTION_ENTRIES: Final = 100_000

#: Maximum nesting depth of mappings/sequences.
RECEIPT_MAX_NESTING_DEPTH: Final = 32


class CanonicalReceiptError(ValueError):
    """A value cannot be canonically encoded as a bounded receipt."""


def canonical_receipt_bytes(value: object) -> bytes:
    """Return the deterministic canonical JSON bytes for ``value``.

    The value must be JSON-shaped (None, bool, int, float, str, list/dict of
    the same).  Mappings require string keys.  Floats must be finite.  Strings,
    collections, nesting, and the encoded total are bounded, and every bound
    is enforced before encoding.
    """
    _validate(value, depth=0)
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CanonicalReceiptError(f"value is not canonically encodable: {exc}") from exc
    if len(encoded) > CANONICAL_RECEIPT_MAX_BYTES:
        raise CanonicalReceiptError(
            f"canonical receipt exceeds {CANONICAL_RECEIPT_MAX_BYTES} bytes: {len(encoded)}"
        )
    return encoded


def dataclass_receipt_payload(
    receipt: Any, *, digest_field: str | None = None
) -> dict[str, object]:
    """Return the exact-key mapping for a dataclass receipt.

    When ``digest_field`` names the receipt's self-digest field it is excluded
    from the payload.  Nested dataclasses are converted recursively so callers
    can canonicalize a whole receipt without hand-mapping each level.
    """
    if not is_dataclass(receipt):
        raise CanonicalReceiptError(f"receipt must be a dataclass, got {type(receipt)!r}")
    payload: dict[str, object] = {}
    for field in fields(receipt):
        if digest_field is not None and field.name == digest_field:
            continue
        payload[field.name] = _plain(getattr(receipt, field.name))
    return payload


def canonical_receipt_digest(receipt: Any, *, digest_field: str) -> str:
    """Compute ``SHA256(canonical bytes excluding the receipt's digest field)``."""
    return hashlib.sha256(
        canonical_receipt_bytes(dataclass_receipt_payload(receipt, digest_field=digest_field))
    ).hexdigest()


def verify_receipt_digest(receipt: Any, *, digest_field: str) -> str:
    """Recompute and check a receipt's self digest; return the digest.

    Raises :class:`CanonicalReceiptError` when the stored digest is missing or
    disagrees with the recomputed value.  The stored literal never confers
    authority; only agreement with the recomputed digest does.
    """
    if not is_dataclass(receipt):
        raise CanonicalReceiptError(f"receipt must be a dataclass, got {type(receipt)!r}")
    stored = getattr(receipt, digest_field, None)
    if not isinstance(stored, str):
        raise CanonicalReceiptError(f"receipt field {digest_field!r} must be a digest string")
    recomputed = canonical_receipt_digest(receipt, digest_field=digest_field)
    if stored != recomputed:
        raise CanonicalReceiptError(
            f"receipt digest mismatch: stored {stored!r} != recomputed {recomputed!r}"
        )
    return recomputed


def _plain(value: object) -> object:
    """Convert nested dataclasses to plain JSON-shaped values."""
    if is_dataclass(value):
        return {field.name: _plain(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise CanonicalReceiptError(
        f"unsupported receipt value type {type(value)!r}; convert to JSON shapes first"
    )


def _validate(value: object, *, depth: int) -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        return
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise CanonicalReceiptError("NaN and Infinity are not canonically encodable")
        return
    if isinstance(value, str):
        if len(value) > RECEIPT_MAX_STRING_CHARS:
            raise CanonicalReceiptError(
                f"receipt string exceeds {RECEIPT_MAX_STRING_CHARS} characters: {len(value)}"
            )
        return
    if isinstance(value, (list, tuple)):
        if depth >= RECEIPT_MAX_NESTING_DEPTH:
            raise CanonicalReceiptError(
                f"receipt nesting exceeds depth {RECEIPT_MAX_NESTING_DEPTH}"
            )
        if len(value) > RECEIPT_MAX_COLLECTION_ENTRIES:
            raise CanonicalReceiptError(
                f"receipt sequence exceeds {RECEIPT_MAX_COLLECTION_ENTRIES} entries: {len(value)}"
            )
        for item in value:
            _validate(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        if depth >= RECEIPT_MAX_NESTING_DEPTH:
            raise CanonicalReceiptError(
                f"receipt nesting exceeds depth {RECEIPT_MAX_NESTING_DEPTH}"
            )
        if len(value) > RECEIPT_MAX_COLLECTION_ENTRIES:
            raise CanonicalReceiptError(
                f"receipt mapping exceeds {RECEIPT_MAX_COLLECTION_ENTRIES} entries: {len(value)}"
            )
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalReceiptError(
                    f"receipt mapping keys must be strings, got {type(key)!r}"
                )
            _validate(item, depth=depth + 1)
        return
    raise CanonicalReceiptError(
        f"unsupported receipt value type {type(value)!r}; convert to JSON shapes first"
    )
