"""Separately sealed equality receipt for the two W2 value projections.

The body and public-table projectors are deliberately independent.  This leaf
only replays their exact projection DTOs, compares their complete canonical
partition and item rows, and seals the result.  It never reads either source.
The plan SHA is operation-bound metadata rather than an authority available to
this leaf: the W2 operation must cross-bind the actual plan, both projection
receipts and their children, and this complete equality receipt.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields
from typing import Any, ClassVar, Final, Never, Self, cast

from nbadb.contracts.value_projection import (
    MAX_VALUE_PROJECTION_ITEMS,
    MAX_VALUE_PROJECTION_PARTITIONS,
    ValueProjectionItemV1,
    ValueProjectionPartitionV1,
    ValueProjectionReceiptV1,
)

__all__ = [
    "VALUE_PROJECTION_EQUALITY_SCHEMA_VERSION",
    "ValueProjectionEqualityError",
    "ValueProjectionEqualityReceiptV1",
]


VALUE_PROJECTION_EQUALITY_SCHEMA_VERSION: Final = 1
_MAX_RECEIPT_BYTES: Final = 64 * 1024
_MAX_JSON_DEPTH: Final = 8
_MAX_JSON_NODES: Final = 256
_MAX_JSON_NUMBER_BYTES: Final = 128
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")

_RECEIPT_KIND: Final = "nbadb_value_projection_equality_receipt_v1"
_BODY_INPUT_ROOT_KIND: Final = "nbadb_value_projection_equality_body_inputs_v1"
_PUBLIC_INPUT_ROOT_KIND: Final = "nbadb_value_projection_equality_public_inputs_v1"
_PARTITION_MATCH_KIND: Final = "nbadb_value_projection_partition_equality_v1"
_PARTITION_MATCH_ROOT_KIND: Final = "nbadb_value_projection_partition_equalities_v1"
_ITEM_MATCH_KIND: Final = "nbadb_value_projection_item_equality_v1"
_ITEM_MATCH_ROOT_KIND: Final = "nbadb_value_projection_item_equalities_v1"
_EQUALITY_ROOT_KIND: Final = "nbadb_value_projection_equality_roots_v1"
_PROJECTION_PARTITION_ROOT_KIND: Final = "nbadb_value_projection_partitions_v1"
_PROJECTION_ITEM_ROOT_KIND: Final = "nbadb_value_projection_items_v1"
_PROJECTION_RECORD_ROOT_KIND: Final = "nbadb_value_projection_source_records_v1"
_PROJECTION_BINDING_ROOT_KIND: Final = "nbadb_value_projection_bindings_v1"


class ValueProjectionEqualityError(ValueError):
    """The two independently derived projections cannot be proven equal."""


def _fail(message: str) -> Never:
    raise ValueProjectionEqualityError(message)


def _require_exact_class(cls: type[object], expected: type[object], *, label: str) -> None:
    if cls is not expected:
        _fail(f"{label} has a foreign exact class")


def _exact_sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be one exact lowercase SHA-256")
    return value


def _exact_nonnegative(value: object, *, label: str, maximum: int) -> int:
    if type(value) is not int or value < 0 or value > maximum:
        _fail(f"{label} must be one bounded exact nonnegative integer")
    return value


def _canonical_bytes(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8", errors="strict")
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("projection-equality value is not exact canonical JSON")
    if not encoded or len(encoded) > _MAX_RECEIPT_BYTES:
        _fail("projection-equality canonical JSON is empty or over-bound")
    return encoded


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _ordered_root(
    *,
    kind: str,
    raw_authority_bundle_sha256: str,
    item_sha256s: tuple[str, ...],
    maximum: int,
) -> str:
    if type(item_sha256s) is not tuple or len(item_sha256s) > maximum:
        _fail("projection-equality ordered-root inventory is foreign or over-bound")
    bundle = _exact_sha256(raw_authority_bundle_sha256, label="ordered-root raw bundle")
    digest = hashlib.sha256()
    digest.update(b"nbadb-value-projection-length-framed-root-v1\x00")

    def feed(value: bytes) -> None:
        digest.update(len(value).to_bytes(8, byteorder="big", signed=False))
        digest.update(value)

    feed(b"1")
    feed(kind.encode("utf-8"))
    feed(bundle.encode("ascii"))
    feed(str(len(item_sha256s)).encode("ascii"))
    for ordinal, identity in enumerate(item_sha256s):
        feed(str(ordinal).encode("ascii"))
        feed(_exact_sha256(identity, label="ordered-root item").encode("ascii"))
    return digest.hexdigest()


def _row_fields(cls: type[object]) -> tuple[str, ...]:
    return ("schema_version", *(item.name for item in fields(cls)))


def _strict_row(value: object, *, cls: type[object]) -> dict[str, object]:
    if type(value) is not dict:
        _fail("projection-equality receipt row must be one exact built-in mapping")
    row = cast("dict[object, object]", value)
    expected = _row_fields(cls)
    if any(type(key) is not str for key in row) or tuple(row) != expected:
        _fail("projection-equality receipt fields or order differ from V1")
    if type(row["schema_version"]) is not int or row["schema_version"] != 1:
        _fail("projection-equality receipt schema version differs from V1")
    return {name: row[name] for name in expected}


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("projection-equality canonical JSON contains a duplicate key")
        result[key] = value
    return result


def _parse_int(token: str) -> int:
    if len(token.encode("ascii")) > _MAX_JSON_NUMBER_BYTES:
        _fail("projection-equality canonical JSON number is over-bound")
    value = int(token)
    if value < -(1 << 63) or value > (1 << 63) - 1:
        _fail("projection-equality canonical JSON integer is out of range")
    return value


def _reject_float(_token: str) -> Never:
    _fail("projection-equality canonical JSON contains a non-integer number")


def _lexical_preflight(value: bytes) -> None:
    depth = 0
    nodes = 0
    in_string = False
    escaped = False
    for byte in value:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:
                escaped = True
            elif byte == 0x22:
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte in (0x7B, 0x5B):
            depth += 1
            nodes += 1
            if depth > _MAX_JSON_DEPTH or nodes > _MAX_JSON_NODES:
                _fail("projection-equality canonical JSON is structurally over-bound")
        elif byte in (0x7D, 0x5D):
            depth -= 1
            if depth < 0:
                _fail("projection-equality canonical JSON has invalid structure")
        elif byte in (0x2C, 0x3A):
            nodes += 1
            if nodes > _MAX_JSON_NODES:
                _fail("projection-equality canonical JSON is structurally over-bound")
    if in_string or escaped or depth != 0:
        _fail("projection-equality canonical JSON has invalid structure")


def _decode_canonical_row(value: object) -> dict[str, object]:
    if type(value) is not bytes or not value or len(value) > _MAX_RECEIPT_BYTES:
        _fail("projection-equality canonical bytes are foreign, empty, or over-bound")
    encoded = cast("bytes", value)
    _lexical_preflight(encoded)
    try:
        decoded = json.loads(
            encoded.decode("utf-8", errors="strict"),
            object_pairs_hook=_json_object,
            parse_int=_parse_int,
            parse_float=_reject_float,
            parse_constant=_reject_float,
        )
    except ValueProjectionEqualityError:
        raise
    except (json.JSONDecodeError, RecursionError, TypeError, UnicodeDecodeError, ValueError):
        raise ValueProjectionEqualityError(
            "projection-equality canonical bytes failed exact decoding"
        ) from None
    if type(decoded) is not dict or _canonical_bytes(decoded) != encoded:
        _fail("projection-equality canonical bytes are not one canonical row")
    return cast("dict[str, object]", decoded)


def _exact_scalar_equal(left: object, right: object, *, label: str) -> None:
    if type(left) is not type(right):
        _fail(f"{label} differs in exact built-in type")
    if type(left) not in {str, int, type(None)}:
        _fail(f"{label} contains a foreign comparison value")
    if left != right:
        _fail(f"{label} differs")


def _compare_rows(left: object, right: object, *, label: str) -> None:
    if type(left) is not type(right):
        _fail(f"{label} DTO types differ")
    for item in fields(cast("Any", left)):
        _exact_scalar_equal(
            getattr(left, item.name),
            getattr(right, item.name),
            label=f"{label} {item.name}",
        )


def _replay_projection(
    value: object,
    *,
    expected_projection_sha256: str,
    expected_raw_authority_bundle_sha256: str,
    expected_ownership_receipt_sha256: str,
    label: str,
) -> ValueProjectionReceiptV1:
    if type(value) is not ValueProjectionReceiptV1:
        _fail(f"{label} projection is not one exact receipt DTO")
    projection = value
    if (
        _exact_sha256(projection.projection_sha256, label=f"candidate {label} projection")
        != expected_projection_sha256
        or projection.raw_authority_bundle_sha256 != expected_raw_authority_bundle_sha256
        or projection.ownership_receipt_sha256 != expected_ownership_receipt_sha256
    ):
        _fail(f"{label} projection differs from its external authority pins")
    try:
        return ValueProjectionReceiptV1.from_row(projection.to_row())
    except Exception:
        raise ValueProjectionEqualityError(f"{label} projection failed exact replay") from None


def _replay_partitions(value: object, *, label: str) -> tuple[ValueProjectionPartitionV1, ...]:
    if type(value) is not tuple or len(value) > MAX_VALUE_PROJECTION_PARTITIONS:
        _fail(f"{label} must be one bounded exact tuple")
    inventory = value
    if any(type(item) is not ValueProjectionPartitionV1 for item in inventory):
        _fail(f"{label} contains a foreign DTO")
    if len({id(item) for item in inventory}) != len(inventory):
        _fail(f"{label} aliases one DTO object")
    try:
        return tuple(
            ValueProjectionPartitionV1.from_row(cast("ValueProjectionPartitionV1", item).to_row())
            for item in inventory
        )
    except Exception:
        raise ValueProjectionEqualityError(f"{label} failed exact replay") from None


def _replay_items(value: object, *, label: str) -> tuple[ValueProjectionItemV1, ...]:
    if type(value) is not tuple or len(value) > MAX_VALUE_PROJECTION_ITEMS:
        _fail(f"{label} must be one bounded exact tuple")
    inventory = value
    if any(type(item) is not ValueProjectionItemV1 for item in inventory):
        _fail(f"{label} contains a foreign DTO")
    if len({id(item) for item in inventory}) != len(inventory):
        _fail(f"{label} aliases one DTO object")
    try:
        return tuple(
            ValueProjectionItemV1.from_row(cast("ValueProjectionItemV1", item).to_row())
            for item in inventory
        )
    except Exception:
        raise ValueProjectionEqualityError(f"{label} failed exact replay") from None


def _validate_children(
    receipt: ValueProjectionReceiptV1,
    partitions: tuple[ValueProjectionPartitionV1, ...],
    items: tuple[ValueProjectionItemV1, ...],
    *,
    label: str,
) -> None:
    bundle = receipt.raw_authority_bundle_sha256
    checks: tuple[tuple[str, object, object], ...] = (
        ("partition count", receipt.partition_count, len(partitions)),
        ("item count", receipt.item_count, len(items)),
        ("source-record count", receipt.source_record_count, len(items)),
        ("binding count", receipt.binding_count, len(items)),
        (
            "partition root",
            receipt.partition_root_sha256,
            _ordered_root(
                kind=_PROJECTION_PARTITION_ROOT_KIND,
                raw_authority_bundle_sha256=bundle,
                item_sha256s=tuple(item.partition_sha256 for item in partitions),
                maximum=MAX_VALUE_PROJECTION_PARTITIONS,
            ),
        ),
        (
            "item root",
            receipt.item_root_sha256,
            _ordered_root(
                kind=_PROJECTION_ITEM_ROOT_KIND,
                raw_authority_bundle_sha256=bundle,
                item_sha256s=tuple(item.item_sha256 for item in items),
                maximum=MAX_VALUE_PROJECTION_ITEMS,
            ),
        ),
        (
            "source-record root",
            receipt.source_record_root_sha256,
            _ordered_root(
                kind=_PROJECTION_RECORD_ROOT_KIND,
                raw_authority_bundle_sha256=bundle,
                item_sha256s=tuple(item.source_record_sha256 for item in items),
                maximum=MAX_VALUE_PROJECTION_ITEMS,
            ),
        ),
        (
            "binding root",
            receipt.binding_root_sha256,
            _ordered_root(
                kind=_PROJECTION_BINDING_ROOT_KIND,
                raw_authority_bundle_sha256=bundle,
                item_sha256s=tuple(item.ownership_binding_sha256 for item in items),
                maximum=MAX_VALUE_PROJECTION_ITEMS,
            ),
        ),
    )
    for name, actual, expected in checks:
        _exact_scalar_equal(actual, expected, label=f"{label} projection {name}")
    if any(partition.partition_ordinal != ordinal for ordinal, partition in enumerate(partitions)):
        _fail(f"{label} projection partition order is sparse or reordered")
    for ordinal, item in enumerate(items):
        if item.global_item_ordinal != ordinal:
            _fail(f"{label} projection item order is sparse or reordered")
        if item.partition_ordinal >= len(partitions):
            _fail(f"{label} projection item references a foreign partition")


def _side_root(
    *,
    kind: str,
    bundle: str,
    projection: ValueProjectionReceiptV1,
    partitions: tuple[ValueProjectionPartitionV1, ...],
    items: tuple[ValueProjectionItemV1, ...],
) -> tuple[int, str]:
    identities = (
        projection.projection_sha256,
        *(item.partition_sha256 for item in partitions),
        *(item.item_sha256 for item in items),
    )
    return len(identities), _ordered_root(
        kind=kind,
        raw_authority_bundle_sha256=bundle,
        item_sha256s=identities,
        maximum=1 + MAX_VALUE_PROJECTION_PARTITIONS + MAX_VALUE_PROJECTION_ITEMS,
    )


@dataclass(frozen=True, slots=True)
class ValueProjectionEqualityReceiptV1:
    """Exact leaf comparison proof over body and public projection rows."""

    receipt_sha256: str
    raw_authority_bundle_sha256: str
    ownership_receipt_sha256: str
    plan_sha256: str
    body_projection_sha256: str
    public_projection_sha256: str
    body_input_count: int
    body_input_root_sha256: str
    public_input_count: int
    public_input_root_sha256: str
    partition_equality_count: int
    partition_equality_root_sha256: str
    item_equality_count: int
    item_equality_root_sha256: str
    equality_root_sha256: str

    schema_version: ClassVar[int] = VALUE_PROJECTION_EQUALITY_SCHEMA_VERSION
    kind: ClassVar[str] = _RECEIPT_KIND

    def __post_init__(self) -> None:
        for name in (
            "receipt_sha256",
            "raw_authority_bundle_sha256",
            "ownership_receipt_sha256",
            "plan_sha256",
            "body_projection_sha256",
            "public_projection_sha256",
            "body_input_root_sha256",
            "public_input_root_sha256",
            "partition_equality_root_sha256",
            "item_equality_root_sha256",
            "equality_root_sha256",
        ):
            _exact_sha256(getattr(self, name), label=name)
        maximum_inputs = 1 + MAX_VALUE_PROJECTION_PARTITIONS + MAX_VALUE_PROJECTION_ITEMS
        for name, maximum in (
            ("body_input_count", maximum_inputs),
            ("public_input_count", maximum_inputs),
            ("partition_equality_count", MAX_VALUE_PROJECTION_PARTITIONS),
            ("item_equality_count", MAX_VALUE_PROJECTION_ITEMS),
        ):
            _exact_nonnegative(getattr(self, name), label=name, maximum=maximum)
        if (
            self.body_projection_sha256 != self.public_projection_sha256
            or self.body_input_count != self.public_input_count
            or self.body_input_count != 1 + self.partition_equality_count + self.item_equality_count
        ):
            _fail("projection-equality receipt denominators are inconsistent")
        empty_partition_root = _ordered_root(
            kind=_PARTITION_MATCH_ROOT_KIND,
            raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
            item_sha256s=(),
            maximum=MAX_VALUE_PROJECTION_PARTITIONS,
        )
        empty_item_root = _ordered_root(
            kind=_ITEM_MATCH_ROOT_KIND,
            raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
            item_sha256s=(),
            maximum=MAX_VALUE_PROJECTION_ITEMS,
        )
        if (self.partition_equality_count == 0) != (
            self.partition_equality_root_sha256 == empty_partition_root
        ):
            _fail("projection-equality partition zero root is inconsistent")
        if (self.item_equality_count == 0) != (self.item_equality_root_sha256 == empty_item_root):
            _fail("projection-equality item zero root is inconsistent")
        if self.body_input_root_sha256 == self.public_input_root_sha256:
            _fail("projection-equality side roots are not domain-separated")
        if self.partition_equality_count == 0 and self.item_equality_count == 0:
            maximum_inputs = 1 + MAX_VALUE_PROJECTION_PARTITIONS + MAX_VALUE_PROJECTION_ITEMS
            empty_side_roots = (
                (
                    self.body_input_root_sha256,
                    _BODY_INPUT_ROOT_KIND,
                    self.body_projection_sha256,
                ),
                (
                    self.public_input_root_sha256,
                    _PUBLIC_INPUT_ROOT_KIND,
                    self.public_projection_sha256,
                ),
            )
            for actual_root, kind, projection_sha256 in empty_side_roots:
                expected_side_root = _ordered_root(
                    kind=kind,
                    raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                    item_sha256s=(projection_sha256,),
                    maximum=maximum_inputs,
                )
                if actual_root != expected_side_root:
                    _fail("projection-equality empty side root differs from its projection")
        expected_root = _ordered_root(
            kind=_EQUALITY_ROOT_KIND,
            raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
            item_sha256s=(
                self.body_input_root_sha256,
                self.public_input_root_sha256,
                self.partition_equality_root_sha256,
                self.item_equality_root_sha256,
            ),
            maximum=4,
        )
        if self.equality_root_sha256 != expected_root:
            _fail("projection-equality root differs from its exact child roots")
        if self.receipt_sha256 != _canonical_sha256(self.identity_payload()):
            _fail("projection-equality receipt digest differs from its exact identity")

    @classmethod
    def build(
        cls,
        *,
        expected_raw_authority_bundle_sha256: str,
        expected_ownership_receipt_sha256: str,
        expected_plan_sha256: str,
        body_projection: ValueProjectionReceiptV1,
        expected_body_projection_sha256: str,
        body_partitions: tuple[ValueProjectionPartitionV1, ...],
        body_items: tuple[ValueProjectionItemV1, ...],
        public_projection: ValueProjectionReceiptV1,
        expected_public_projection_sha256: str,
        public_partitions: tuple[ValueProjectionPartitionV1, ...],
        public_items: tuple[ValueProjectionItemV1, ...],
    ) -> Self:
        _require_exact_class(cls, ValueProjectionEqualityReceiptV1, label="projection equality")
        bundle = _exact_sha256(
            expected_raw_authority_bundle_sha256,
            label="expected raw authority bundle",
        )
        ownership = _exact_sha256(
            expected_ownership_receipt_sha256,
            label="expected ownership receipt",
        )
        plan = _exact_sha256(expected_plan_sha256, label="expected projection plan")
        body_pin = _exact_sha256(expected_body_projection_sha256, label="expected body projection")
        public_pin = _exact_sha256(
            expected_public_projection_sha256,
            label="expected public projection",
        )
        if (
            body_projection is public_projection
            or (body_partitions and body_partitions is public_partitions)
            or (body_items and body_items is public_items)
        ):
            _fail("body and public projection evidence aliases the same object")
        body = _replay_projection(
            body_projection,
            expected_projection_sha256=body_pin,
            expected_raw_authority_bundle_sha256=bundle,
            expected_ownership_receipt_sha256=ownership,
            label="body",
        )
        public = _replay_projection(
            public_projection,
            expected_projection_sha256=public_pin,
            expected_raw_authority_bundle_sha256=bundle,
            expected_ownership_receipt_sha256=ownership,
            label="public",
        )
        body_partitions_replayed = _replay_partitions(
            body_partitions,
            label="body projection partitions",
        )
        public_partitions_replayed = _replay_partitions(
            public_partitions,
            label="public projection partitions",
        )
        body_items_replayed = _replay_items(body_items, label="body projection items")
        public_items_replayed = _replay_items(public_items, label="public projection items")
        body_ids = {
            id(body_projection),
            *(id(item) for item in body_partitions),
            *(id(item) for item in body_items),
        }
        public_ids = {
            id(public_projection),
            *(id(item) for item in public_partitions),
            *(id(item) for item in public_items),
        }
        if body_ids & public_ids:
            _fail("body and public projection evidence aliases one child object")
        _validate_children(body, body_partitions_replayed, body_items_replayed, label="body")
        _validate_children(
            public,
            public_partitions_replayed,
            public_items_replayed,
            label="public",
        )
        _compare_rows(body, public, label="projection receipt")
        if len(body_partitions_replayed) != len(public_partitions_replayed):
            _fail("body and public projection partition cardinalities differ")
        if len(body_items_replayed) != len(public_items_replayed):
            _fail("body and public projection item cardinalities differ")

        partition_matches: list[str] = []
        for ordinal, (left, right) in enumerate(
            zip(body_partitions_replayed, public_partitions_replayed, strict=True)
        ):
            _compare_rows(left, right, label=f"projection partition {ordinal}")
            partition_matches.append(
                _canonical_sha256(
                    {
                        "schema_version": cls.schema_version,
                        "kind": _PARTITION_MATCH_KIND,
                        "partition_ordinal": ordinal,
                        "body_partition_sha256": left.partition_sha256,
                        "public_partition_sha256": right.partition_sha256,
                    }
                )
            )

        item_matches: list[str] = []
        for ordinal, (left, right) in enumerate(
            zip(body_items_replayed, public_items_replayed, strict=True)
        ):
            _compare_rows(left, right, label=f"projection item {ordinal}")
            item_matches.append(
                _canonical_sha256(
                    {
                        "schema_version": cls.schema_version,
                        "kind": _ITEM_MATCH_KIND,
                        "global_item_ordinal": ordinal,
                        "source_record_sha256": left.source_record_sha256,
                        "coordinate_sha256": left.coordinate_sha256,
                        "value_state": left.value_state,
                        "presence_kind": left.presence_kind,
                        "value_kind": left.value_kind,
                        "canonical_json_sha256": left.canonical_json_sha256,
                        "body_item_sha256": left.item_sha256,
                        "public_item_sha256": right.item_sha256,
                    }
                )
            )

        body_count, body_root = _side_root(
            kind=_BODY_INPUT_ROOT_KIND,
            bundle=bundle,
            projection=body,
            partitions=body_partitions_replayed,
            items=body_items_replayed,
        )
        public_count, public_root = _side_root(
            kind=_PUBLIC_INPUT_ROOT_KIND,
            bundle=bundle,
            projection=public,
            partitions=public_partitions_replayed,
            items=public_items_replayed,
        )
        partition_root = _ordered_root(
            kind=_PARTITION_MATCH_ROOT_KIND,
            raw_authority_bundle_sha256=bundle,
            item_sha256s=tuple(partition_matches),
            maximum=MAX_VALUE_PROJECTION_PARTITIONS,
        )
        item_root = _ordered_root(
            kind=_ITEM_MATCH_ROOT_KIND,
            raw_authority_bundle_sha256=bundle,
            item_sha256s=tuple(item_matches),
            maximum=MAX_VALUE_PROJECTION_ITEMS,
        )
        values: dict[str, object] = {
            "raw_authority_bundle_sha256": bundle,
            "ownership_receipt_sha256": ownership,
            "plan_sha256": plan,
            "body_projection_sha256": body.projection_sha256,
            "public_projection_sha256": public.projection_sha256,
            "body_input_count": body_count,
            "body_input_root_sha256": body_root,
            "public_input_count": public_count,
            "public_input_root_sha256": public_root,
            "partition_equality_count": len(partition_matches),
            "partition_equality_root_sha256": partition_root,
            "item_equality_count": len(item_matches),
            "item_equality_root_sha256": item_root,
            "equality_root_sha256": _ordered_root(
                kind=_EQUALITY_ROOT_KIND,
                raw_authority_bundle_sha256=bundle,
                item_sha256s=(body_root, public_root, partition_root, item_root),
                maximum=4,
            ),
        }
        identity = {"schema_version": cls.schema_version, "kind": cls.kind, **values}
        return cls(receipt_sha256=_canonical_sha256(identity), **cast("Any", values))

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            **{
                item.name: getattr(self, item.name)
                for item in fields(self)
                if item.name != "receipt_sha256"
            },
        }

    def to_row(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            **{item.name: getattr(self, item.name) for item in fields(self)},
        }

    @classmethod
    def from_row(cls, value: object, *, expected_receipt_sha256: str) -> Self:
        _require_exact_class(cls, ValueProjectionEqualityReceiptV1, label="projection equality")
        expected = _exact_sha256(
            expected_receipt_sha256,
            label="expected projection-equality receipt",
        )
        row = _strict_row(value, cls=cls)
        if _exact_sha256(row["receipt_sha256"], label="candidate equality receipt") != expected:
            _fail("projection-equality receipt differs from its external pin")
        try:
            return cls(**cast("Any", {item.name: row[item.name] for item in fields(cls)}))
        except ValueProjectionEqualityError:
            raise
        except Exception:
            raise ValueProjectionEqualityError(
                "projection-equality receipt row failed exact replay"
            ) from None

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_row())

    @classmethod
    def from_canonical_bytes(cls, value: object, *, expected_receipt_sha256: str) -> Self:
        _require_exact_class(cls, ValueProjectionEqualityReceiptV1, label="projection equality")
        _exact_sha256(
            expected_receipt_sha256,
            label="expected projection-equality receipt",
        )
        decoded = _decode_canonical_row(value)
        expected_fields = _row_fields(cls)
        if any(type(key) is not str for key in decoded) or set(decoded) != set(expected_fields):
            _fail("projection-equality canonical row fields differ from V1")
        return cls.from_row(
            {name: decoded[name] for name in expected_fields},
            expected_receipt_sha256=expected_receipt_sha256,
        )
