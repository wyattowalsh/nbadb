from __future__ import annotations

from dataclasses import dataclass

import pytest

from nbadb.contracts.receipt_digest import (
    CANONICAL_RECEIPT_MAX_BYTES,
    RECEIPT_MAX_COLLECTION_ENTRIES,
    RECEIPT_MAX_NESTING_DEPTH,
    RECEIPT_MAX_STRING_CHARS,
    CanonicalReceiptError,
    canonical_receipt_bytes,
    canonical_receipt_digest,
    dataclass_receipt_payload,
    verify_receipt_digest,
)


class _Custom:
    """An unsupported object type."""


@dataclass(frozen=True, slots=True)
class _NestedReceipt:
    chain_id: str
    iteration: int
    items: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _SignedReceipt:
    chain_id: str
    payload: _NestedReceipt
    receipt_sha256: str


def _digest(receipt: _SignedReceipt) -> str:
    return canonical_receipt_digest(receipt, digest_field="receipt_sha256")


def _valid_receipt() -> _SignedReceipt:
    base = _SignedReceipt(
        chain_id="chain-1",
        payload=_NestedReceipt(chain_id="chain-1", iteration=2, items=(1, 2, 3)),
        receipt_sha256="0" * 64,
    )
    return _SignedReceipt(
        chain_id=base.chain_id,
        payload=base.payload,
        receipt_sha256=_digest(base),
    )


class TestCanonicalBytes:
    def test_deterministic_across_key_order(self) -> None:
        left = {"b": 1, "a": {"y": [1, 2], "x": "s"}}
        right = {"a": {"x": "s", "y": [1, 2]}, "b": 1}
        assert canonical_receipt_bytes(left) == canonical_receipt_bytes(right)

    def test_compact_separators_and_ascii(self) -> None:
        encoded = canonical_receipt_bytes({"k": "café"})
        assert encoded == b'{"k":"caf\\u00e9"}'
        assert b" " not in encoded

    def test_round_trip_through_json(self) -> None:
        import json

        value = {"z": [1, None, True, 1.5], "a": "text"}
        assert json.loads(canonical_receipt_bytes(value)) == value

    def test_rejects_non_string_keys(self) -> None:
        with pytest.raises(CanonicalReceiptError, match="string"):
            canonical_receipt_bytes({1: "value"})

    def test_rejects_nan_and_infinity(self) -> None:
        with pytest.raises(CanonicalReceiptError, match="NaN"):
            canonical_receipt_bytes({"x": float("nan")})
        with pytest.raises(CanonicalReceiptError, match="NaN"):
            canonical_receipt_bytes({"x": float("inf")})

    def test_rejects_unsupported_objects(self) -> None:
        with pytest.raises(CanonicalReceiptError, match="unsupported"):
            canonical_receipt_bytes({"x": _Custom()})
        with pytest.raises(CanonicalReceiptError, match="unsupported"):
            canonical_receipt_bytes({"x": b"bytes"})

    def test_rejects_oversized_string(self) -> None:
        with pytest.raises(CanonicalReceiptError, match="string exceeds"):
            canonical_receipt_bytes({"x": "a" * (RECEIPT_MAX_STRING_CHARS + 1)})

    def test_allows_string_at_bound(self) -> None:
        encoded = canonical_receipt_bytes({"x": "a" * RECEIPT_MAX_STRING_CHARS})
        assert len(encoded) > RECEIPT_MAX_STRING_CHARS

    def test_rejects_oversized_collection(self) -> None:
        with pytest.raises(CanonicalReceiptError, match="sequence exceeds"):
            canonical_receipt_bytes({"x": [0] * (RECEIPT_MAX_COLLECTION_ENTRIES + 1)})
        with pytest.raises(CanonicalReceiptError, match="mapping exceeds"):
            canonical_receipt_bytes(
                {"x": {str(i): 1 for i in range(RECEIPT_MAX_COLLECTION_ENTRIES + 1)}}
            )

    def test_rejects_excess_nesting(self) -> None:
        value: list[object] = []
        node = value
        for _ in range(RECEIPT_MAX_NESTING_DEPTH + 1):
            child: list[object] = []
            node.append(child)
            node = child
        with pytest.raises(CanonicalReceiptError, match="nesting"):
            canonical_receipt_bytes({"x": value})

    def test_rejects_receipt_over_total_bound(self) -> None:
        # 9 x 1 MiB strings exceeds the 8 MiB receipt cap while each string
        # stays inside its own bound.
        payload = {str(i): "a" * RECEIPT_MAX_STRING_CHARS for i in range(9)}
        with pytest.raises(CanonicalReceiptError, match="exceeds"):
            canonical_receipt_bytes(payload)

    def test_bound_constant_is_eight_mib(self) -> None:
        assert CANONICAL_RECEIPT_MAX_BYTES == 8 * 1024 * 1024


class TestReceiptDigest:
    def test_digest_excludes_own_field(self) -> None:
        receipt = _valid_receipt()
        payload = dataclass_receipt_payload(receipt, digest_field="receipt_sha256")
        assert "receipt_sha256" not in payload
        assert receipt.receipt_sha256 == canonical_receipt_digest(
            receipt, digest_field="receipt_sha256"
        )

    def test_verify_accepts_valid_digest(self) -> None:
        receipt = _valid_receipt()
        assert verify_receipt_digest(receipt, digest_field="receipt_sha256") == (
            receipt.receipt_sha256
        )

    def test_verify_rejects_tampered_digest(self) -> None:
        receipt = _valid_receipt()
        tampered = _SignedReceipt(
            chain_id=receipt.chain_id,
            payload=receipt.payload,
            receipt_sha256="f" * 64,
        )
        with pytest.raises(CanonicalReceiptError, match="digest mismatch"):
            verify_receipt_digest(tampered, digest_field="receipt_sha256")

    def test_verify_rejects_tampered_payload(self) -> None:
        receipt = _valid_receipt()
        tampered = _SignedReceipt(
            chain_id="chain-2",
            payload=receipt.payload,
            receipt_sha256=receipt.receipt_sha256,
        )
        with pytest.raises(CanonicalReceiptError, match="digest mismatch"):
            verify_receipt_digest(tampered, digest_field="receipt_sha256")

    def test_verify_rejects_missing_digest(self) -> None:
        with pytest.raises(CanonicalReceiptError, match="digest string"):
            verify_receipt_digest(_NestedReceipt("chain-1", 1, ()), digest_field="missing")

    def test_verify_rejects_non_dataclass(self) -> None:
        with pytest.raises(CanonicalReceiptError, match="dataclass"):
            verify_receipt_digest({"not": "a dataclass"}, digest_field="x")

    def test_nested_dataclasses_flatten_to_json_shapes(self) -> None:
        receipt = _valid_receipt()
        payload = dataclass_receipt_payload(receipt, digest_field="receipt_sha256")
        assert payload["payload"] == {
            "chain_id": "chain-1",
            "iteration": 2,
            "items": [1, 2, 3],
        }

    def test_payload_without_digest_field_keeps_all_keys(self) -> None:
        nested = _NestedReceipt("chain-1", 3, (4,))
        assert dataclass_receipt_payload(nested) == {
            "chain_id": "chain-1",
            "iteration": 3,
            "items": [4],
        }

    def test_digest_is_sha256_of_canonical_bytes(self) -> None:
        import hashlib

        receipt = _valid_receipt()
        expected = hashlib.sha256(
            canonical_receipt_bytes(
                dataclass_receipt_payload(receipt, digest_field="receipt_sha256")
            )
        ).hexdigest()
        assert receipt.receipt_sha256 == expected
