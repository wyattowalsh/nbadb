"""Bounded canonical values for the Arrow types used by nbadb.

The public functions in this module deliberately operate on Arrow arrays and
scalars instead of routing values through ``repr`` or ``default=str``.  The
result preserves type-sensitive details such as signed zero, non-finite float
bits, decimal scale, temporal units, nested nulls, and dictionary inventories.

Parsing canonical bytes is a structural boundary.  Callers that need source
or route authority must still replay the resulting value against those
authorities; a locally valid digest is not an authority grant.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import ClassVar, Literal, Self, cast

import pyarrow as pa

__all__ = [
    "ArrowFieldV1",
    "ArrowLogicalTypeV1",
    "CanonicalArrowValueError",
    "CanonicalArrowValueV1",
    "ValueBudget",
    "ValueBudgetLimits",
    "canonical_arrow_array_scalar",
    "canonical_arrow_scalar",
    "canonical_arrow_type",
    "checked_add",
    "checked_product",
    "compare_canonical_arrow_values",
    "decode_canonical_arrow_value",
]

ArrowTypeKind = Literal[
    "null",
    "bool",
    "integer",
    "float",
    "decimal",
    "utf8",
    "binary",
    "date",
    "timestamp",
    "time",
    "duration",
    "list",
    "list_view",
    "fixed_size_list",
    "struct",
    "dictionary",
]

MAX_CANONICAL_BYTES = 8 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 200_000
MAX_STRING_TOKEN_BYTES = 4 * 1024 * 1024
MAX_TYPE_CHILDREN = 4_096
MAX_FIELD_NAME_BYTES = 16 * 1024
MAX_VALUE_NODES = 100_000
MAX_VALUE_UTF8_BYTES = 4 * 1024 * 1024
MAX_VALUE_BINARY_BYTES = 4 * 1024 * 1024
MAX_VALUE_CONTAINER_ITEMS = 100_000
MAX_VALUE_CANONICAL_BYTES = 8 * 1024 * 1024
MAX_CHECKED_INTEGER = 2**63 - 1
MAX_JSON_INTEGER_TOKEN_BYTES = 20
# The canonical null/null-type receipt is the shortest possible V1 wire value.
MIN_CANONICAL_ARROW_VALUE_BYTES = 437

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_LOWER_HEX_RE = re.compile(r"(?:[0-9a-f]{2})*\Z")
_INTEGER_TEXT_RE = re.compile(r"(?:0|-[1-9][0-9]*|[1-9][0-9]*)\Z")
_TEMPORAL_UNITS = frozenset({"s", "ms", "us", "ns"})
_TYPE_KINDS = frozenset(
    {
        "null",
        "bool",
        "integer",
        "float",
        "decimal",
        "utf8",
        "binary",
        "date",
        "timestamp",
        "time",
        "duration",
        "list",
        "list_view",
        "fixed_size_list",
        "struct",
        "dictionary",
    }
)


class CanonicalArrowValueError(ValueError):
    """Raised when an Arrow type or value has no exact bounded encoding."""


def _exact_nonnegative(value: object, *, label: str, maximum: int) -> int:
    if type(value) is not int or value < 0 or value > maximum:
        raise CanonicalArrowValueError(f"{label} must be a bounded nonnegative exact integer")
    return value


def checked_add(
    left: object,
    right: object,
    *,
    maximum: int = MAX_CHECKED_INTEGER,
    label: str = "sum",
) -> int:
    """Add two exact nonnegative integers without exceeding ``maximum``."""

    _exact_nonnegative(maximum, label=f"{label} maximum", maximum=MAX_CHECKED_INTEGER)
    lhs = _exact_nonnegative(left, label=f"{label} left operand", maximum=maximum)
    rhs = _exact_nonnegative(right, label=f"{label} right operand", maximum=maximum)
    if lhs > maximum - rhs:
        raise CanonicalArrowValueError(f"{label} exceeds its bounded contract")
    return lhs + rhs


def checked_product(
    left: object,
    right: object,
    *,
    maximum: int = MAX_CHECKED_INTEGER,
    label: str = "product",
) -> int:
    """Multiply two exact nonnegative integers without exceeding ``maximum``."""

    _exact_nonnegative(maximum, label=f"{label} maximum", maximum=MAX_CHECKED_INTEGER)
    lhs = _exact_nonnegative(left, label=f"{label} left operand", maximum=maximum)
    rhs = _exact_nonnegative(right, label=f"{label} right operand", maximum=maximum)
    if lhs and rhs > maximum // lhs:
        raise CanonicalArrowValueError(f"{label} exceeds its bounded contract")
    return lhs * rhs


@dataclass(frozen=True, slots=True)
class ValueBudgetLimits:
    """Resource ceilings for one value or a cumulative caller-owned budget."""

    max_nodes: int = MAX_VALUE_NODES
    max_depth: int = MAX_JSON_DEPTH
    max_utf8_bytes: int = MAX_VALUE_UTF8_BYTES
    max_binary_bytes: int = MAX_VALUE_BINARY_BYTES
    max_container_items: int = MAX_VALUE_CONTAINER_ITEMS
    max_canonical_bytes: int = MAX_VALUE_CANONICAL_BYTES

    def __post_init__(self) -> None:
        for name in (
            "max_nodes",
            "max_depth",
            "max_utf8_bytes",
            "max_binary_bytes",
            "max_container_items",
            "max_canonical_bytes",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 1 or value > MAX_CHECKED_INTEGER:
                raise CanonicalArrowValueError(f"{name} must be a bounded positive exact integer")


@dataclass(slots=True)
class ValueBudget:
    """Cumulative, pre-allocation accounting for canonical Arrow values."""

    limits: ValueBudgetLimits = field(default_factory=ValueBudgetLimits)
    nodes: int = 0
    max_depth_observed: int = 0
    utf8_bytes: int = 0
    binary_bytes: int = 0
    container_items: int = 0
    canonical_bytes: int = 0

    def __post_init__(self) -> None:
        if type(self.limits) is not ValueBudgetLimits:
            raise CanonicalArrowValueError("value budget limits require the exact limits type")
        for name, maximum in (
            ("nodes", self.limits.max_nodes),
            ("max_depth_observed", self.limits.max_depth),
            ("utf8_bytes", self.limits.max_utf8_bytes),
            ("binary_bytes", self.limits.max_binary_bytes),
            ("container_items", self.limits.max_container_items),
            ("canonical_bytes", self.limits.max_canonical_bytes),
        ):
            _exact_nonnegative(getattr(self, name), label=name, maximum=maximum)

    def reserve(
        self,
        *,
        nodes: int = 0,
        depth: int = 0,
        utf8_bytes: int = 0,
        binary_bytes: int = 0,
        container_items: int = 0,
        canonical_bytes: int = 0,
    ) -> None:
        """Atomically reserve resources; counters are unchanged on failure."""

        new_nodes = checked_add(
            self.nodes,
            nodes,
            maximum=self.limits.max_nodes,
            label="value nodes",
        )
        exact_depth = _exact_nonnegative(
            depth,
            label="value depth",
            maximum=self.limits.max_depth,
        )
        new_utf8 = checked_add(
            self.utf8_bytes,
            utf8_bytes,
            maximum=self.limits.max_utf8_bytes,
            label="value UTF-8 bytes",
        )
        new_binary = checked_add(
            self.binary_bytes,
            binary_bytes,
            maximum=self.limits.max_binary_bytes,
            label="value binary bytes",
        )
        new_items = checked_add(
            self.container_items,
            container_items,
            maximum=self.limits.max_container_items,
            label="value container items",
        )
        new_canonical = checked_add(
            self.canonical_bytes,
            canonical_bytes,
            maximum=self.limits.max_canonical_bytes,
            label="value canonical bytes",
        )
        self.nodes = new_nodes
        self.max_depth_observed = max(self.max_depth_observed, exact_depth)
        self.utf8_bytes = new_utf8
        self.binary_bytes = new_binary
        self.container_items = new_items
        self.canonical_bytes = new_canonical


@dataclass(slots=True)
class _PairedValueBudget:
    """Reserve against a local receipt and an atomic caller-budget probe."""

    local: ValueBudget
    caller_probe: ValueBudget

    @property
    def limits(self) -> ValueBudgetLimits:
        return self.local.limits

    def reserve(
        self,
        *,
        nodes: int = 0,
        depth: int = 0,
        utf8_bytes: int = 0,
        binary_bytes: int = 0,
        container_items: int = 0,
        canonical_bytes: int = 0,
    ) -> None:
        self.caller_probe.reserve(
            nodes=nodes,
            depth=depth,
            utf8_bytes=utf8_bytes,
            binary_bytes=binary_bytes,
            container_items=container_items,
            canonical_bytes=canonical_bytes,
        )
        self.local.reserve(
            nodes=nodes,
            depth=depth,
            utf8_bytes=utf8_bytes,
            binary_bytes=binary_bytes,
            container_items=container_items,
            canonical_bytes=canonical_bytes,
        )


_ActiveValueBudget = ValueBudget | _PairedValueBudget


def _copy_budget(value: ValueBudget) -> ValueBudget:
    return ValueBudget(
        limits=value.limits,
        nodes=value.nodes,
        max_depth_observed=value.max_depth_observed,
        utf8_bytes=value.utf8_bytes,
        binary_bytes=value.binary_bytes,
        container_items=value.container_items,
        canonical_bytes=value.canonical_bytes,
    )


def _active_value_budget(
    local: ValueBudget,
    caller: ValueBudget | None,
) -> _ActiveValueBudget:
    if caller is None:
        return local
    return _PairedValueBudget(local=local, caller_probe=_copy_budget(caller))


def _remaining_canonical_bytes(budget: ValueBudget | None) -> int:
    if budget is None:
        return MAX_VALUE_CANONICAL_BYTES
    remaining = budget.limits.max_canonical_bytes - budget.canonical_bytes
    if remaining < 1:
        raise CanonicalArrowValueError("value canonical bytes exceeds its bounded contract")
    return min(MAX_VALUE_CANONICAL_BYTES, remaining)


def _utf8_byte_length(value: str, *, label: str) -> int:
    """Count strict UTF-8 bytes without first allocating the encoded value."""

    total = 0
    for character in value:
        codepoint = ord(character)
        if codepoint <= 0x7F:
            width = 1
        elif codepoint <= 0x7FF:
            width = 2
        elif 0xD800 <= codepoint <= 0xDFFF:
            raise CanonicalArrowValueError(f"{label} must be exact UTF-8")
        elif codepoint <= 0xFFFF:
            width = 3
        else:
            width = 4
        total = checked_add(
            total,
            width,
            maximum=MAX_CHECKED_INTEGER,
            label=f"{label} UTF-8 length",
        )
    return total


def _bounded_json_size_add(current: int, added: int, *, maximum_bytes: int) -> int:
    try:
        return checked_add(
            current,
            added,
            maximum=maximum_bytes,
            label="canonical JSON byte size",
        )
    except CanonicalArrowValueError as exc:
        raise CanonicalArrowValueError("canonical JSON exceeds its byte bound") from exc


def _canonical_json_string_size(
    value: str,
    *,
    maximum_bytes: int,
) -> int:
    size = 2  # surrounding quotes
    for character in value:
        codepoint = ord(character)
        if character in {'"', "\\"} or character in {"\b", "\f", "\n", "\r", "\t"}:
            width = 2
        elif codepoint <= 0x1F:
            width = 6
        elif codepoint <= 0x7F:
            width = 1
        elif codepoint <= 0x7FF:
            width = 2
        elif 0xD800 <= codepoint <= 0xDFFF:
            raise CanonicalArrowValueError("canonical JSON text must be exact UTF-8")
        elif codepoint <= 0xFFFF:
            width = 3
        else:
            width = 4
        size = _bounded_json_size_add(size, width, maximum_bytes=maximum_bytes)
    return size


def _canonical_json_size(
    value: object,
    *,
    maximum_bytes: int,
    depth: int = 0,
) -> int:
    if depth > MAX_JSON_DEPTH:
        raise CanonicalArrowValueError("canonical JSON exceeds its depth bound")
    if value is None:
        return 4
    if type(value) is bool:
        return 4 if value else 5
    if type(value) is int:
        magnitude = -value if value < 0 else value
        digits = 1
        while magnitude >= 10:
            magnitude //= 10
            digits += 1
            if digits > maximum_bytes:
                raise CanonicalArrowValueError("canonical JSON exceeds its byte bound")
        return _bounded_json_size_add(
            digits,
            1 if value < 0 else 0,
            maximum_bytes=maximum_bytes,
        )
    if type(value) is float:
        try:
            scalar = json.dumps(value, allow_nan=False, separators=(",", ":"))
        except (OverflowError, ValueError) as exc:
            raise CanonicalArrowValueError("value is not bounded canonical JSON") from exc
        return len(scalar)
    if type(value) is str:
        return _canonical_json_string_size(value, maximum_bytes=maximum_bytes)
    if type(value) is list:
        size = 2
        for index, child in enumerate(value):
            if index:
                size = _bounded_json_size_add(size, 1, maximum_bytes=maximum_bytes)
            size = _bounded_json_size_add(
                size,
                _canonical_json_size(
                    child,
                    maximum_bytes=maximum_bytes,
                    depth=depth + 1,
                ),
                maximum_bytes=maximum_bytes,
            )
        return size
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise CanonicalArrowValueError("canonical JSON object keys must be exact text")
        size = 2
        for index, key in enumerate(sorted(value)):
            if index:
                size = _bounded_json_size_add(size, 1, maximum_bytes=maximum_bytes)
            size = _bounded_json_size_add(
                size,
                _canonical_json_string_size(key, maximum_bytes=maximum_bytes),
                maximum_bytes=maximum_bytes,
            )
            size = _bounded_json_size_add(size, 1, maximum_bytes=maximum_bytes)
            size = _bounded_json_size_add(
                size,
                _canonical_json_size(
                    value[key],
                    maximum_bytes=maximum_bytes,
                    depth=depth + 1,
                ),
                maximum_bytes=maximum_bytes,
            )
        return size
    raise CanonicalArrowValueError("value is not bounded canonical JSON")


def _canonical_json_bytes(value: object, *, maximum_bytes: int) -> bytes:
    _exact_nonnegative(
        maximum_bytes,
        label="canonical JSON maximum",
        maximum=MAX_CHECKED_INTEGER,
    )
    if maximum_bytes == 0:
        raise CanonicalArrowValueError("canonical JSON maximum must be positive")
    try:
        expected_size = _canonical_json_size(value, maximum_bytes=maximum_bytes)
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8", errors="strict")
    except CanonicalArrowValueError:
        raise
    except (
        MemoryError,
        OverflowError,
        RecursionError,
        TypeError,
        UnicodeEncodeError,
        ValueError,
    ) as exc:
        raise CanonicalArrowValueError("value is not bounded canonical JSON") from exc
    if not encoded or len(encoded) != expected_size or len(encoded) > maximum_bytes:
        raise CanonicalArrowValueError("canonical JSON exceeds its byte bound")
    return encoded


def _reject_duplicate_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CanonicalArrowValueError("canonical JSON contains a duplicate object key")
        result[key] = value
    return result


def _reject_nonfinite_json_constant(value: str) -> object:
    raise CanonicalArrowValueError(f"canonical JSON contains forbidden number token {value}")


def _parse_bounded_json_integer(value: str) -> int:
    if len(value.encode("ascii", errors="strict")) > MAX_JSON_INTEGER_TOKEN_BYTES:
        raise CanonicalArrowValueError("canonical JSON integer token exceeds its byte bound")
    try:
        return int(value)
    except ValueError as exc:
        raise CanonicalArrowValueError("canonical JSON integer token is invalid") from exc


def _scan_json_shape(encoded: bytes, *, maximum_depth: int, maximum_nodes: int) -> None:
    """Bound JSON shape before ``json.loads`` allocates nested containers."""

    depth = 0
    nodes = 0
    index = 0
    length = len(encoded)
    while index < length:
        byte = encoded[index]
        if byte in b" \t\r\n,:}]":
            if byte in b"}]":
                depth -= 1
                if depth < 0:
                    raise CanonicalArrowValueError("canonical JSON nesting is malformed")
            index += 1
            continue
        if byte in b"[{":
            depth += 1
            nodes += 1
            if depth > maximum_depth or nodes > maximum_nodes:
                raise CanonicalArrowValueError("canonical JSON exceeds its shape bound")
            index += 1
            continue
        if byte == 0x22:
            start = index
            index += 1
            escaped = False
            while index < length:
                current = encoded[index]
                if escaped:
                    escaped = False
                elif current == 0x5C:
                    escaped = True
                elif current == 0x22:
                    break
                index += 1
            if index >= length:
                raise CanonicalArrowValueError("canonical JSON string is unterminated")
            if index - start - 1 > MAX_STRING_TOKEN_BYTES:
                raise CanonicalArrowValueError("canonical JSON string exceeds its byte bound")
            nodes += 1
            if nodes > maximum_nodes:
                raise CanonicalArrowValueError("canonical JSON exceeds its node bound")
            index += 1
            continue
        start = index
        while index < length and encoded[index] not in b" \t\r\n,]}:":
            index += 1
        if index == start:
            raise CanonicalArrowValueError("canonical JSON contains an invalid token")
        nodes += 1
        if nodes > maximum_nodes:
            raise CanonicalArrowValueError("canonical JSON exceeds its node bound")
    if depth != 0:
        raise CanonicalArrowValueError("canonical JSON nesting is malformed")


def _strict_canonical_json_object(
    encoded: object,
    *,
    maximum_bytes: int,
    maximum_depth: int = MAX_JSON_DEPTH,
    maximum_nodes: int = MAX_JSON_NODES,
) -> dict[str, object]:
    if type(encoded) is not bytes or not encoded or len(encoded) > maximum_bytes:
        raise CanonicalArrowValueError("canonical input must be nonempty bounded exact bytes")
    raw = cast("bytes", encoded)
    try:
        raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise CanonicalArrowValueError("canonical input must be exact UTF-8") from exc
    _scan_json_shape(raw, maximum_depth=maximum_depth, maximum_nodes=maximum_nodes)
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_object,
            parse_constant=_reject_nonfinite_json_constant,
            parse_int=_parse_bounded_json_integer,
        )
    except CanonicalArrowValueError:
        raise
    except (
        MemoryError,
        OverflowError,
        RecursionError,
        UnicodeDecodeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise CanonicalArrowValueError("canonical input is not bounded JSON") from exc
    if type(value) is not dict:
        raise CanonicalArrowValueError("canonical JSON root must be an object")
    if raw != _canonical_json_bytes(value, maximum_bytes=maximum_bytes):
        raise CanonicalArrowValueError("canonical JSON bytes are not exact")
    return cast("dict[str, object]", value)


def _sha256_payload(value: object, *, domain: bytes) -> str:
    digest = hashlib.sha256(domain + b"\0")
    digest.update(_canonical_json_bytes(value, maximum_bytes=MAX_CANONICAL_BYTES))
    return digest.hexdigest()


def _exact_text(value: object, *, label: str, maximum_bytes: int) -> str:
    if type(value) is not str:
        raise CanonicalArrowValueError(f"{label} must be exact text")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise CanonicalArrowValueError(f"{label} must be exact UTF-8") from exc
    if not value or len(encoded) > maximum_bytes:
        raise CanonicalArrowValueError(f"{label} must be nonempty bounded text")
    return value


@dataclass(frozen=True, slots=True)
class ArrowFieldV1:
    """One ordered child field inside a recursive Arrow type."""

    ordinal: int
    name: str
    nullable: bool
    logical_type: ArrowLogicalTypeV1

    def __post_init__(self) -> None:
        _exact_nonnegative(self.ordinal, label="Arrow field ordinal", maximum=MAX_TYPE_CHILDREN - 1)
        _exact_text(self.name, label="Arrow field name", maximum_bytes=MAX_FIELD_NAME_BYTES)
        if type(self.nullable) is not bool:
            raise CanonicalArrowValueError("Arrow field nullable must be an exact boolean")
        if type(self.logical_type) is not ArrowLogicalTypeV1:
            raise CanonicalArrowValueError("Arrow field logical type has a foreign concrete type")

    def to_dict(self) -> dict[str, object]:
        return {
            "ordinal": self.ordinal,
            "name": self.name,
            "nullable": self.nullable,
            "logical_type": self.logical_type.to_dict(),
        }

    def to_arrow_field(self) -> pa.Field:
        return pa.field(self.name, self.logical_type.to_arrow_type(), nullable=self.nullable)


@dataclass(frozen=True, slots=True)
class ArrowLogicalTypeV1:
    """Exact recursive descriptor for one supported Arrow logical type."""

    type_kind: ArrowTypeKind
    bit_width: int | None = None
    signed: bool | None = None
    offset_width: int | None = None
    byte_width: int | None = None
    precision: int | None = None
    scale: int | None = None
    unit: str | None = None
    timezone: str | None = None
    list_size: int | None = None
    ordered: bool | None = None
    children: tuple[ArrowFieldV1, ...] = ()

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "arrow_logical_type"

    def __post_init__(self) -> None:
        if type(self.type_kind) is not str or self.type_kind not in _TYPE_KINDS:
            raise CanonicalArrowValueError("Arrow logical type kind is unsupported")
        if type(self.children) is not tuple or any(
            type(child) is not ArrowFieldV1 for child in self.children
        ):
            raise CanonicalArrowValueError(
                "Arrow logical type children must be exact immutable fields"
            )
        if len(self.children) > MAX_TYPE_CHILDREN or tuple(
            child.ordinal for child in self.children
        ) != tuple(range(len(self.children))):
            raise CanonicalArrowValueError("Arrow logical type children are reordered or excessive")
        self._validate_shape()

    def _validate_shape(self) -> None:
        values = {
            "bit_width": self.bit_width,
            "signed": self.signed,
            "offset_width": self.offset_width,
            "byte_width": self.byte_width,
            "precision": self.precision,
            "scale": self.scale,
            "unit": self.unit,
            "timezone": self.timezone,
            "list_size": self.list_size,
            "ordered": self.ordered,
        }

        allowed: set[str]
        kind = self.type_kind
        if kind in {"null", "bool"}:
            allowed = set()
        elif kind == "struct":
            allowed = set()
            names = tuple(child.name for child in self.children)
            if len(set(names)) != len(names):
                raise CanonicalArrowValueError("struct field names must be unique")
        elif kind == "integer":
            allowed = {"bit_width", "signed"}
            if self.bit_width not in {8, 16, 32, 64} or type(self.signed) is not bool:
                raise CanonicalArrowValueError("integer descriptor width or signedness is invalid")
        elif kind == "float":
            allowed = {"bit_width"}
            if self.bit_width not in {16, 32, 64}:
                raise CanonicalArrowValueError("float descriptor width is invalid")
        elif kind == "decimal":
            allowed = {"bit_width", "precision", "scale"}
            maximum_precision = 38 if self.bit_width == 128 else 76 if self.bit_width == 256 else 0
            if (
                type(self.precision) is not int
                or self.precision < 1
                or self.precision > maximum_precision
                or type(self.scale) is not int
                or abs(self.scale) > maximum_precision
            ):
                raise CanonicalArrowValueError("decimal descriptor is invalid")
        elif kind == "utf8":
            allowed = {"offset_width"}
            if self.offset_width not in {32, 64}:
                raise CanonicalArrowValueError("UTF-8 offset width is invalid")
        elif kind == "binary":
            allowed = {"offset_width"} if self.offset_width is not None else {"byte_width"}
            if self.offset_width is not None:
                if self.offset_width not in {32, 64} or self.byte_width is not None:
                    raise CanonicalArrowValueError("binary offset descriptor is invalid")
            elif type(self.byte_width) is not int or self.byte_width < 0:
                raise CanonicalArrowValueError("fixed binary width is invalid")
        elif kind == "date":
            allowed = {"bit_width", "unit"}
            if (self.bit_width, self.unit) not in {(32, "day"), (64, "ms")}:
                raise CanonicalArrowValueError("date descriptor is invalid")
        elif kind == "timestamp":
            allowed = {"unit", "timezone"}
            if self.unit not in _TEMPORAL_UNITS:
                raise CanonicalArrowValueError("timestamp unit is invalid")
            if self.timezone is not None:
                _exact_text(
                    self.timezone,
                    label="timestamp timezone",
                    maximum_bytes=MAX_FIELD_NAME_BYTES,
                )
        elif kind == "time":
            allowed = {"bit_width", "unit"}
            valid = (self.bit_width == 32 and self.unit in {"s", "ms"}) or (
                self.bit_width == 64 and self.unit in {"us", "ns"}
            )
            if not valid:
                raise CanonicalArrowValueError("time descriptor is invalid")
        elif kind == "duration":
            allowed = {"unit"}
            if self.unit not in _TEMPORAL_UNITS:
                raise CanonicalArrowValueError("duration unit is invalid")
        elif kind in {"list", "list_view"}:
            allowed = {"offset_width"}
            if self.offset_width not in {32, 64} or len(self.children) != 1:
                raise CanonicalArrowValueError("list descriptor is invalid")
        elif kind == "fixed_size_list":
            allowed = {"list_size"}
            if type(self.list_size) is not int or self.list_size < 0 or len(self.children) != 1:
                raise CanonicalArrowValueError("fixed-size list descriptor is invalid")
        else:  # dictionary
            allowed = {"ordered"}
            if type(self.ordered) is not bool or len(self.children) != 2:
                raise CanonicalArrowValueError("dictionary descriptor is invalid")
            index_field, value_field = self.children
            if index_field.logical_type.type_kind != "integer":
                raise CanonicalArrowValueError("dictionary index type must be integer")
            if (
                index_field.name != "index"
                or index_field.nullable
                or value_field.name != "value"
                or not value_field.nullable
            ):
                raise CanonicalArrowValueError(
                    "dictionary child field identity or nullability is noncanonical"
                )

        if kind not in {"list", "list_view", "fixed_size_list", "struct", "dictionary"} and (
            self.children
        ):
            raise CanonicalArrowValueError("scalar Arrow type cannot contain child fields")
        for name, value in values.items():
            if name not in allowed and value is not None:
                raise CanonicalArrowValueError(
                    f"Arrow logical type {kind} contains foreign parameter {name}"
                )

    @property
    def type_sha256(self) -> str:
        return _sha256_payload(self.to_dict(), domain=b"nbadb-arrow-logical-type-v1")

    def descriptor(self) -> dict[str, object]:
        result: dict[str, object] = {"type_kind": self.type_kind}
        for name in (
            "bit_width",
            "signed",
            "offset_width",
            "byte_width",
            "precision",
            "scale",
            "unit",
            "timezone",
            "list_size",
            "ordered",
        ):
            value = getattr(self, name)
            if value is not None or (name == "timezone" and self.type_kind == "timestamp"):
                result[name] = value
        if self.children:
            result["children"] = [child.to_dict() for child in self.children]
        return result

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "descriptor": self.descriptor(),
        }

    def to_canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict(), maximum_bytes=MAX_CANONICAL_BYTES)

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> Self:
        payload = _strict_canonical_json_object(encoded, maximum_bytes=MAX_CANONICAL_BYTES)
        result = _logical_type_from_dict(payload)
        if result.to_canonical_bytes() != encoded:
            raise CanonicalArrowValueError("Arrow logical type bytes are not canonical")
        if canonical_arrow_type(result.to_arrow_type()) != result:
            raise CanonicalArrowValueError("Arrow logical type is not an exact Arrow fixed point")
        return cast("Self", result)

    def to_arrow_type(self) -> pa.DataType:
        kind = self.type_kind
        if kind == "null":
            return pa.null()
        if kind == "bool":
            return pa.bool_()
        if kind == "integer":
            assert self.bit_width is not None and self.signed is not None
            name = ("int" if self.signed else "uint") + str(self.bit_width)
            return cast("pa.DataType", getattr(pa, name)())
        if kind == "float":
            assert self.bit_width is not None
            name = "float16" if self.bit_width == 16 else f"float{self.bit_width}"
            return cast("pa.DataType", getattr(pa, name)())
        if kind == "decimal":
            assert (
                self.bit_width is not None and self.precision is not None and self.scale is not None
            )
            factory = pa.decimal128 if self.bit_width == 128 else pa.decimal256
            return factory(self.precision, self.scale)
        if kind == "utf8":
            return pa.string() if self.offset_width == 32 else pa.large_string()
        if kind == "binary":
            if self.byte_width is not None:
                return pa.binary(self.byte_width)
            return pa.binary() if self.offset_width == 32 else pa.large_binary()
        if kind == "date":
            return pa.date32() if self.bit_width == 32 else pa.date64()
        if kind == "timestamp":
            assert self.unit is not None
            return pa.timestamp(self.unit, tz=self.timezone)
        if kind == "time":
            assert self.unit is not None
            return pa.time32(self.unit) if self.bit_width == 32 else pa.time64(self.unit)
        if kind == "duration":
            assert self.unit is not None
            return pa.duration(self.unit)
        if kind in {"list", "list_view", "fixed_size_list"}:
            child = self.children[0].to_arrow_field()
            if kind == "fixed_size_list":
                assert self.list_size is not None
                return pa.list_(child, self.list_size)
            if kind == "list_view":
                return pa.list_view(child) if self.offset_width == 32 else pa.large_list_view(child)
            return pa.list_(child) if self.offset_width == 32 else pa.large_list(child)
        if kind == "struct":
            return pa.struct([child.to_arrow_field() for child in self.children])
        assert kind == "dictionary"
        return pa.dictionary(
            self.children[0].logical_type.to_arrow_type(),
            self.children[1].logical_type.to_arrow_type(),
            ordered=cast("bool", self.ordered),
        )


def _field_from_dict(payload: object) -> ArrowFieldV1:
    if type(payload) is not dict or set(payload) != {
        "ordinal",
        "name",
        "nullable",
        "logical_type",
    }:
        raise CanonicalArrowValueError("Arrow child field keys are invalid")
    item = cast("dict[str, object]", payload)
    return ArrowFieldV1(
        ordinal=cast("int", item["ordinal"]),
        name=cast("str", item["name"]),
        nullable=cast("bool", item["nullable"]),
        logical_type=_logical_type_from_dict(item["logical_type"]),
    )


def _logical_type_from_dict(payload: object) -> ArrowLogicalTypeV1:
    if type(payload) is not dict or set(payload) != {"schema_version", "kind", "descriptor"}:
        raise CanonicalArrowValueError("Arrow logical type keys are invalid")
    item = cast("dict[str, object]", payload)
    if type(item["schema_version"]) is not int or item["schema_version"] != 1:
        raise CanonicalArrowValueError("Arrow logical type schema version is invalid")
    if type(item["kind"]) is not str or item["kind"] != "arrow_logical_type":
        raise CanonicalArrowValueError("Arrow logical type kind is invalid")
    descriptor = item["descriptor"]
    if type(descriptor) is not dict:
        raise CanonicalArrowValueError("Arrow logical type descriptor must be an object")
    values = cast("dict[str, object]", descriptor)
    allowed = {
        "type_kind",
        "bit_width",
        "signed",
        "offset_width",
        "byte_width",
        "precision",
        "scale",
        "unit",
        "timezone",
        "list_size",
        "ordered",
        "children",
    }
    if not set(values) <= allowed or "type_kind" not in values:
        raise CanonicalArrowValueError("Arrow logical type descriptor keys are invalid")
    raw_children = values.get("children", [])
    if type(raw_children) is not list or len(raw_children) > MAX_TYPE_CHILDREN:
        raise CanonicalArrowValueError("Arrow logical type child inventory is invalid")
    return ArrowLogicalTypeV1(
        type_kind=cast("ArrowTypeKind", values["type_kind"]),
        bit_width=cast("int | None", values.get("bit_width")),
        signed=cast("bool | None", values.get("signed")),
        offset_width=cast("int | None", values.get("offset_width")),
        byte_width=cast("int | None", values.get("byte_width")),
        precision=cast("int | None", values.get("precision")),
        scale=cast("int | None", values.get("scale")),
        unit=cast("str | None", values.get("unit")),
        timezone=cast("str | None", values.get("timezone")),
        list_size=cast("int | None", values.get("list_size")),
        ordered=cast("bool | None", values.get("ordered")),
        children=tuple(_field_from_dict(child) for child in raw_children),
    )


def _arrow_field(field_value: pa.Field, ordinal: int) -> ArrowFieldV1:
    return ArrowFieldV1(
        ordinal=ordinal,
        name=field_value.name,
        nullable=field_value.nullable,
        logical_type=canonical_arrow_type(field_value.type),
    )


def canonical_arrow_type(dtype: pa.DataType) -> ArrowLogicalTypeV1:
    """Return the exact recursive descriptor for one supported Arrow type."""

    if not isinstance(dtype, pa.DataType):
        raise CanonicalArrowValueError("canonical Arrow type requires a PyArrow DataType")
    if pa.types.is_null(dtype):
        return ArrowLogicalTypeV1("null")
    if pa.types.is_boolean(dtype):
        return ArrowLogicalTypeV1("bool")
    if pa.types.is_integer(dtype):
        return ArrowLogicalTypeV1(
            "integer",
            bit_width=dtype.bit_width,
            signed=pa.types.is_signed_integer(dtype),
        )
    if pa.types.is_floating(dtype):
        return ArrowLogicalTypeV1("float", bit_width=dtype.bit_width)
    if pa.types.is_decimal(dtype):
        return ArrowLogicalTypeV1(
            "decimal",
            bit_width=dtype.bit_width,
            precision=dtype.precision,
            scale=dtype.scale,
        )
    if pa.types.is_string(dtype):
        return ArrowLogicalTypeV1("utf8", offset_width=32)
    if pa.types.is_large_string(dtype):
        return ArrowLogicalTypeV1("utf8", offset_width=64)
    if pa.types.is_binary(dtype):
        return ArrowLogicalTypeV1("binary", offset_width=32)
    if pa.types.is_large_binary(dtype):
        return ArrowLogicalTypeV1("binary", offset_width=64)
    if pa.types.is_fixed_size_binary(dtype):
        return ArrowLogicalTypeV1("binary", byte_width=dtype.byte_width)
    if pa.types.is_date32(dtype):
        return ArrowLogicalTypeV1("date", bit_width=32, unit="day")
    if pa.types.is_date64(dtype):
        return ArrowLogicalTypeV1("date", bit_width=64, unit="ms")
    if pa.types.is_timestamp(dtype):
        return ArrowLogicalTypeV1("timestamp", unit=dtype.unit, timezone=dtype.tz)
    if pa.types.is_time32(dtype):
        return ArrowLogicalTypeV1("time", bit_width=32, unit=dtype.unit)
    if pa.types.is_time64(dtype):
        return ArrowLogicalTypeV1("time", bit_width=64, unit=dtype.unit)
    if pa.types.is_duration(dtype):
        return ArrowLogicalTypeV1("duration", unit=dtype.unit)
    if pa.types.is_list(dtype):
        return ArrowLogicalTypeV1(
            "list",
            offset_width=32,
            children=(_arrow_field(dtype.value_field, 0),),
        )
    if pa.types.is_large_list(dtype):
        return ArrowLogicalTypeV1(
            "list",
            offset_width=64,
            children=(_arrow_field(dtype.value_field, 0),),
        )
    if pa.types.is_list_view(dtype):
        return ArrowLogicalTypeV1(
            "list_view",
            offset_width=32,
            children=(_arrow_field(dtype.value_field, 0),),
        )
    if pa.types.is_large_list_view(dtype):
        return ArrowLogicalTypeV1(
            "list_view",
            offset_width=64,
            children=(_arrow_field(dtype.value_field, 0),),
        )
    if pa.types.is_fixed_size_list(dtype):
        return ArrowLogicalTypeV1(
            "fixed_size_list",
            list_size=dtype.list_size,
            children=(_arrow_field(dtype.value_field, 0),),
        )
    if pa.types.is_struct(dtype):
        return ArrowLogicalTypeV1(
            "struct",
            children=tuple(_arrow_field(child, index) for index, child in enumerate(dtype)),
        )
    if pa.types.is_dictionary(dtype):
        return ArrowLogicalTypeV1(
            "dictionary",
            ordered=dtype.ordered,
            children=(
                ArrowFieldV1(0, "index", False, canonical_arrow_type(dtype.index_type)),
                ArrowFieldV1(1, "value", True, canonical_arrow_type(dtype.value_type)),
            ),
        )
    raise CanonicalArrowValueError(f"Arrow type {dtype.__class__.__name__} is unsupported")


def _canonical_integer_text(value: int) -> str:
    if type(value) is not int:
        raise CanonicalArrowValueError("integer payload requires an exact integer")
    return str(value)


def _parse_integer_text(value: object, *, minimum: int, maximum: int, label: str) -> int:
    if type(value) is not str or _INTEGER_TEXT_RE.fullmatch(value) is None:
        raise CanonicalArrowValueError(f"{label} is not canonical integer text")
    if len(value) > max(len(str(minimum)), len(str(maximum))):
        raise CanonicalArrowValueError(f"{label} exceeds its logical type")
    try:
        parsed = int(value)
    except ValueError as exc:
        raise CanonicalArrowValueError(f"{label} is not bounded integer text") from exc
    if parsed < minimum or parsed > maximum:
        raise CanonicalArrowValueError(f"{label} exceeds its logical type")
    return parsed


def _fixed_width_value_bytes(array: pa.Array, index: int, byte_width: int) -> bytes:
    buffers = array.buffers()
    if len(buffers) < 2 or buffers[1] is None:
        raise CanonicalArrowValueError("Arrow fixed-width value buffer is absent")
    physical_index = array.offset + index
    start = checked_product(
        physical_index,
        byte_width,
        maximum=MAX_CHECKED_INTEGER,
        label="Arrow fixed-width buffer offset",
    )
    try:
        raw = buffers[1].slice(start, byte_width).to_pybytes()
    except (ArrowError, MemoryError, OverflowError, ValueError) as exc:
        raise CanonicalArrowValueError("Arrow fixed-width value buffer is invalid") from exc
    if len(raw) != byte_width:
        raise CanonicalArrowValueError("Arrow fixed-width value buffer is truncated")
    return raw


def _variable_width_value_span(
    array: pa.Array,
    index: int,
    *,
    offset_width: int,
    label: str,
) -> tuple[pa.Buffer, int, int]:
    buffers = array.buffers()
    if len(buffers) < 3 or buffers[1] is None or buffers[2] is None:
        raise CanonicalArrowValueError(f"Arrow {label} buffers are absent")
    offset_byte_width = offset_width // 8
    physical_index = array.offset + index
    offset_position = checked_product(
        physical_index,
        offset_byte_width,
        maximum=MAX_CHECKED_INTEGER,
        label=f"Arrow {label} offset position",
    )
    required_offset_bytes = checked_product(
        2,
        offset_byte_width,
        maximum=MAX_CHECKED_INTEGER,
        label=f"Arrow {label} offset pair",
    )
    try:
        raw_offsets = buffers[1].slice(offset_position, required_offset_bytes).to_pybytes()
    except (ArrowError, MemoryError, OverflowError, ValueError) as exc:
        raise CanonicalArrowValueError(f"Arrow {label} offset buffer is invalid") from exc
    if len(raw_offsets) != required_offset_bytes:
        raise CanonicalArrowValueError(f"Arrow {label} offset buffer is truncated")
    start = int.from_bytes(raw_offsets[:offset_byte_width], byteorder="little", signed=True)
    end = int.from_bytes(raw_offsets[offset_byte_width:], byteorder="little", signed=True)
    if start < 0 or end < start or end > buffers[2].size:
        raise CanonicalArrowValueError(f"Arrow {label} offsets are invalid")
    return buffers[2], start, end - start


def _payload_from_array(
    array: pa.Array,
    index: int,
    *,
    budget: _ActiveValueBudget,
    depth: int,
) -> dict[str, object]:
    budget.reserve(nodes=1, depth=depth)
    dtype = array.type
    logical = canonical_arrow_type(dtype)

    if pa.types.is_dictionary(dtype):
        if not isinstance(array, pa.DictionaryArray):
            raise CanonicalArrowValueError("dictionary type requires a DictionaryArray")
        dictionary_size = len(array.dictionary)
        budget.reserve(container_items=dictionary_size, depth=depth)
        dictionary_payloads: list[dict[str, object]] = []
        for item_index in range(dictionary_size):
            dictionary_payloads.append(
                _payload_from_array(
                    array.dictionary,
                    item_index,
                    budget=budget,
                    depth=depth + 1,
                )
            )
        encoded_dictionary = [
            _canonical_json_bytes(item, maximum_bytes=MAX_VALUE_CANONICAL_BYTES)
            for item in dictionary_payloads
        ]
        if len(set(encoded_dictionary)) != len(encoded_dictionary):
            raise CanonicalArrowValueError("dictionary values must be unique")
        scalar = array[index]
        selection_valid = scalar.is_valid
        if not selection_valid:
            budget.reserve(nodes=1, depth=depth + 1)
            selected: dict[str, object] = {"tag": "null"}
        else:
            raw_index = array.indices[index].as_py()
            if type(raw_index) is not int or raw_index < 0 or raw_index >= len(dictionary_payloads):
                raise CanonicalArrowValueError("dictionary index is out of range")
            selected = _payload_from_array(
                array.dictionary,
                raw_index,
                budget=budget,
                depth=depth + 1,
            )
        return {
            "tag": "dictionary",
            "dictionary": dictionary_payloads,
            "selection_valid": selection_valid,
            "value": selected,
        }

    scalar = array[index]
    if not scalar.is_valid:
        return {"tag": "null"}

    kind = logical.type_kind
    if kind == "null":
        return {"tag": "null"}
    if kind == "bool":
        value = scalar.as_py()
        if type(value) is not bool:
            raise CanonicalArrowValueError("Arrow boolean scalar is invalid")
        return {"tag": "bool", "value": value}
    if kind == "integer":
        value = scalar.as_py()
        if type(value) is not int:
            raise CanonicalArrowValueError("Arrow integer scalar is invalid")
        return {"tag": "integer", "value": _canonical_integer_text(value)}
    if kind == "float":
        assert logical.bit_width is not None
        raw = _fixed_width_value_bytes(array, index, logical.bit_width // 8)
        return {"tag": "float", "bits": raw[::-1].hex()}
    if kind == "decimal":
        assert logical.bit_width is not None
        raw = _fixed_width_value_bytes(array, index, logical.bit_width // 8)
        unscaled = int.from_bytes(raw, byteorder="little", signed=True)
        return {"tag": "decimal", "unscaled": _canonical_integer_text(unscaled)}
    if kind == "utf8":
        assert logical.offset_width is not None
        data, start, byte_length = _variable_width_value_span(
            array,
            index,
            offset_width=logical.offset_width,
            label="UTF-8",
        )
        budget.reserve(utf8_bytes=byte_length, depth=depth)
        try:
            value = (
                data.slice(start, byte_length)
                .to_pybytes()
                .decode(
                    "utf-8",
                    errors="strict",
                )
            )
        except UnicodeDecodeError as exc:
            raise CanonicalArrowValueError("Arrow UTF-8 scalar is invalid") from exc
        return {"tag": "utf8", "value": value}
    if kind == "binary":
        if logical.byte_width is not None:
            byte_length = logical.byte_width
            budget.reserve(binary_bytes=byte_length, depth=depth)
            value = _fixed_width_value_bytes(array, index, byte_length)
        else:
            assert logical.offset_width is not None
            data, start, byte_length = _variable_width_value_span(
                array,
                index,
                offset_width=logical.offset_width,
                label="binary",
            )
            budget.reserve(binary_bytes=byte_length, depth=depth)
            value = data.slice(start, byte_length).to_pybytes()
        return {"tag": "binary", "byte_length": byte_length, "hex": value.hex()}
    if kind in {"date", "timestamp", "time", "duration"}:
        assert logical.bit_width in {32, 64} or kind in {"timestamp", "duration"}
        byte_width = 4 if logical.bit_width == 32 else 8
        raw = _fixed_width_value_bytes(array, index, byte_width)
        ticks = int.from_bytes(raw, byteorder="little", signed=True)
        return {"tag": kind, "ticks": _canonical_integer_text(ticks)}
    if kind in {"list", "list_view", "fixed_size_list"}:
        values = scalar.values
        item_count = len(values)
        budget.reserve(container_items=item_count, depth=depth)
        payloads: list[dict[str, object]] = []
        for item_index in range(item_count):
            payloads.append(_payload_from_array(values, item_index, budget=budget, depth=depth + 1))
        return {"tag": kind, "items": payloads}
    if kind == "struct":
        if not isinstance(array, pa.StructArray):
            raise CanonicalArrowValueError("struct type requires a StructArray")
        budget.reserve(container_items=len(logical.children), depth=depth)
        fields: list[dict[str, object]] = []
        for child in logical.children:
            fields.append(
                {
                    "ordinal": child.ordinal,
                    "name": child.name,
                    "value": _payload_from_array(
                        array.field(child.ordinal),
                        index,
                        budget=budget,
                        depth=depth + 1,
                    ),
                }
            )
        return {"tag": "struct", "fields": fields}
    raise CanonicalArrowValueError("Arrow scalar kind has no canonical payload")


def _strict_python_value(
    value: object,
    dtype: pa.DataType,
    *,
    budget: _ActiveValueBudget,
    depth: int = 0,
) -> None:
    budget.reserve(nodes=1, depth=depth)
    if value is None:
        return
    if isinstance(value, pa.Scalar):
        if not value.type.equals(dtype):
            raise CanonicalArrowValueError("Arrow scalar type differs from the requested type")
        return
    if pa.types.is_null(dtype):
        raise CanonicalArrowValueError("non-null value cannot inhabit Arrow null type")
    if pa.types.is_boolean(dtype):
        if type(value) is not bool:
            raise CanonicalArrowValueError("Arrow boolean requires an exact Python bool")
        return
    if pa.types.is_integer(dtype):
        if type(value) is not int:
            raise CanonicalArrowValueError("Arrow integer requires an exact Python int")
        return
    if pa.types.is_floating(dtype):
        if type(value) is not float:
            raise CanonicalArrowValueError("Arrow float requires an exact Python float")
        return
    if pa.types.is_decimal(dtype):
        if type(value) is not Decimal or not value.is_finite():
            raise CanonicalArrowValueError("Arrow decimal requires a finite exact Decimal")
        return
    if pa.types.is_string(dtype) or pa.types.is_large_string(dtype):
        if type(value) is not str:
            raise CanonicalArrowValueError("Arrow UTF-8 requires an exact Python str")
        budget.reserve(
            utf8_bytes=_utf8_byte_length(value, label="Python UTF-8 value"),
            depth=depth,
        )
        return
    if (
        pa.types.is_binary(dtype)
        or pa.types.is_large_binary(dtype)
        or pa.types.is_fixed_size_binary(dtype)
    ):
        if type(value) is not bytes:
            raise CanonicalArrowValueError("Arrow binary requires immutable exact bytes")
        budget.reserve(binary_bytes=len(value), depth=depth)
        return
    if pa.types.is_date(dtype):
        if type(value) is not date:
            raise CanonicalArrowValueError("Arrow date requires an exact Python date")
        return
    if pa.types.is_timestamp(dtype):
        if type(value) is not datetime:
            raise CanonicalArrowValueError("Arrow timestamp requires an exact Python datetime")
        aware = value.tzinfo is not None and value.utcoffset() is not None
        if dtype.tz is None and aware:
            raise CanonicalArrowValueError(
                "timezone-aware datetime cannot enter an unzoned timestamp"
            )
        if dtype.tz is not None and (not aware or str(value.tzinfo) != dtype.tz):
            raise CanonicalArrowValueError("datetime timezone differs from the Arrow timestamp")
        return
    if pa.types.is_time(dtype):
        if type(value) is not time or value.tzinfo is not None:
            raise CanonicalArrowValueError("Arrow time requires an exact naive Python time")
        return
    if pa.types.is_duration(dtype):
        if type(value) is not timedelta:
            raise CanonicalArrowValueError("Arrow duration requires an exact Python timedelta")
        return
    if pa.types.is_dictionary(dtype):
        budget.reserve(container_items=1, depth=depth)
        _strict_python_value(
            value,
            dtype.value_type,
            budget=budget,
            depth=depth + 1,
        )
        _strict_python_value(
            value,
            dtype.value_type,
            budget=budget,
            depth=depth + 1,
        )
        return
    if (
        pa.types.is_list(dtype)
        or pa.types.is_large_list(dtype)
        or pa.types.is_list_view(dtype)
        or pa.types.is_large_list_view(dtype)
        or pa.types.is_fixed_size_list(dtype)
    ):
        if type(value) is not list:
            raise CanonicalArrowValueError("Arrow list requires an exact Python list")
        if pa.types.is_fixed_size_list(dtype) and len(value) != dtype.list_size:
            raise CanonicalArrowValueError("fixed-size Arrow list has the wrong length")
        budget.reserve(container_items=len(value), depth=depth)
        for child in value:
            _strict_python_value(
                child,
                dtype.value_type,
                budget=budget,
                depth=depth + 1,
            )
        return
    if pa.types.is_struct(dtype):
        if type(value) is not dict:
            raise CanonicalArrowValueError("Arrow struct requires an exact field mapping")
        mapping = cast("dict[str, object]", value)
        budget.reserve(container_items=len(mapping), depth=depth)
        if len(mapping) != len(dtype) or any(child.name not in mapping for child in dtype):
            raise CanonicalArrowValueError("Arrow struct requires an exact field mapping")
        for child in dtype:
            _strict_python_value(
                mapping[child.name],
                child.type,
                budget=budget,
                depth=depth + 1,
            )
        return
    raise CanonicalArrowValueError("Python value targets an unsupported Arrow type")


def _signed_width(value: int, *, bit_width: int, label: str) -> int:
    minimum = -(2 ** (bit_width - 1))
    maximum = 2 ** (bit_width - 1) - 1
    if value < minimum or value > maximum:
        raise CanonicalArrowValueError(f"{label} exceeds its signed {bit_width}-bit storage")
    return value


def _microseconds_to_unit(value: int, *, unit: str, label: str) -> int:
    divisor = {"s": 1_000_000, "ms": 1_000, "us": 1}.get(unit)
    if divisor is not None:
        if value % divisor:
            raise CanonicalArrowValueError(
                f"{label} is not exactly representable in Arrow {unit} units"
            )
        return _signed_width(value // divisor, bit_width=64, label=label)
    if unit == "ns":
        return _signed_width(value * 1_000, bit_width=64, label=label)
    raise CanonicalArrowValueError(f"{label} uses an unsupported temporal unit")


def _timedelta_microseconds(value: timedelta) -> int:
    return ((value.days * 86_400) + value.seconds) * 1_000_000 + value.microseconds


def _python_temporal_storage(
    value: date | datetime | time | timedelta,
    dtype: pa.DataType,
) -> tuple[int, pa.DataType]:
    """Return exact physical ticks without PyArrow's process-global Python converter.

    Pandera currently installs a PyArrow compatibility shim whose datetime
    conversion can reinterpret a non-UTC aware value as UTC wall time.  The
    receipt boundary cannot depend on import order, so temporal Python values
    are reduced to their physical Arrow ticks before Arrow sees them.
    """

    if pa.types.is_date32(dtype):
        assert type(value) is date
        days = (value - date(1970, 1, 1)).days
        return _signed_width(days, bit_width=32, label="date32 value"), pa.int32()
    if pa.types.is_date64(dtype):
        assert type(value) is date
        milliseconds = (value - date(1970, 1, 1)).days * 86_400_000
        return _signed_width(milliseconds, bit_width=64, label="date64 value"), pa.int64()
    if pa.types.is_timestamp(dtype):
        assert type(value) is datetime
        if dtype.tz is None:
            epoch = datetime(1970, 1, 1)
            delta = value - epoch
        else:
            epoch = datetime(1970, 1, 1, tzinfo=UTC)
            delta = value.astimezone(UTC) - epoch
        ticks = _microseconds_to_unit(
            _timedelta_microseconds(delta),
            unit=dtype.unit,
            label="timestamp value",
        )
        return ticks, pa.int64()
    if pa.types.is_time(dtype):
        assert type(value) is time
        microseconds = (
            (value.hour * 60 + value.minute) * 60 + value.second
        ) * 1_000_000 + value.microsecond
        ticks = _microseconds_to_unit(
            microseconds,
            unit=dtype.unit,
            label="time value",
        )
        bit_width = 32 if pa.types.is_time32(dtype) else 64
        return _signed_width(ticks, bit_width=bit_width, label="time value"), (
            pa.int32() if bit_width == 32 else pa.int64()
        )
    if pa.types.is_duration(dtype):
        assert type(value) is timedelta
        ticks = _microseconds_to_unit(
            _timedelta_microseconds(value),
            unit=dtype.unit,
            label="duration value",
        )
        return ticks, pa.int64()
    raise CanonicalArrowValueError("Python value is not an Arrow temporal scalar")


def _array_from_scalar(value: object, dtype: pa.DataType) -> pa.Array:
    if isinstance(value, pa.DictionaryScalar):
        if not value.type.equals(dtype):
            raise CanonicalArrowValueError("dictionary scalar type differs from requested type")
        raw_index = None if not value.is_valid else value.index.as_py()
        indices = pa.array([raw_index], type=dtype.index_type)
        return pa.DictionaryArray.from_arrays(indices, value.dictionary, ordered=dtype.ordered)
    try:
        if value is not None and type(value) in {date, datetime, time, timedelta}:
            ticks, physical_type = _python_temporal_storage(
                cast("date | datetime | time | timedelta", value),
                dtype,
            )
            array = pa.array([ticks], type=physical_type).cast(dtype, safe=True)
        else:
            array = pa.array([value], type=dtype, safe=True)
        if pa.types.is_dictionary(dtype) and not array.type.equals(dtype):
            array = array.cast(dtype, safe=True)
    except (ArrowError, MemoryError, OverflowError, TypeError, ValueError) as exc:
        raise CanonicalArrowValueError(
            "Python value cannot be represented by the exact Arrow type"
        ) from exc
    if not array.type.equals(dtype):
        raise CanonicalArrowValueError(
            "constructed Arrow scalar changed its requested logical type"
        )
    return array


# PyArrow exposes exception classes under ``pa.ArrowException`` in some
# versions and ``pa.lib.ArrowException`` in others.  A module-level tuple keeps
# the catch site type-checkable without broad ``Exception`` handling.
ArrowError = cast("type[Exception]", getattr(pa, "ArrowException", pa.lib.ArrowException))


def _exact_dict(value: object, *, keys: set[str], label: str) -> dict[str, object]:
    if type(value) is not dict or set(value) != keys:
        raise CanonicalArrowValueError(f"{label} keys are invalid")
    return cast("dict[str, object]", value)


def _decimal_from_unscaled(unscaled: int, scale: int) -> Decimal:
    magnitude = str(abs(unscaled))
    return Decimal(
        (
            1 if unscaled < 0 else 0,
            tuple(int(character) for character in magnitude),
            -scale,
        )
    )


def _decode_temporal_ticks(
    ticks: int,
    logical_type: ArrowLogicalTypeV1,
) -> object:
    """Decode representable Python temporals, retaining an exact Arrow fallback."""

    bit_width = logical_type.bit_width or 64
    byte_width = bit_width // 8
    raw = ticks.to_bytes(byte_width, byteorder="little", signed=True)
    try:
        array = pa.Array.from_buffers(
            logical_type.to_arrow_type(),
            1,
            [None, pa.py_buffer(raw)],
        )
        scalar = array[0]
    except (ArrowError, MemoryError, OverflowError, TypeError, ValueError) as exc:
        raise CanonicalArrowValueError("temporal ticks cannot inhabit their Arrow type") from exc
    try:
        python_value = scalar.as_py()
    except (OverflowError, ValueError):
        return scalar
    expected_python_type: type[object]
    if logical_type.type_kind == "date":
        expected_python_type = date
    elif logical_type.type_kind == "timestamp":
        expected_python_type = datetime
    elif logical_type.type_kind == "time":
        expected_python_type = time
    else:
        expected_python_type = timedelta
    if type(python_value) is not expected_python_type:
        return scalar
    try:
        reconstructed_ticks, _ = _python_temporal_storage(
            cast("date | datetime | time | timedelta", python_value),
            logical_type.to_arrow_type(),
        )
    except (CanonicalArrowValueError, OverflowError, TypeError, ValueError):
        return scalar
    return python_value if reconstructed_ticks == ticks else scalar


def _validate_value_payload(
    payload: object,
    logical_type: ArrowLogicalTypeV1,
    *,
    budget: _ActiveValueBudget,
    depth: int,
) -> object:
    budget.reserve(nodes=1, depth=depth)
    if type(payload) is not dict or type(payload.get("tag")) is not str:
        raise CanonicalArrowValueError("canonical Arrow value payload is invalid")
    item = cast("dict[str, object]", payload)
    tag = cast("str", item["tag"])
    if tag == "null":
        _exact_dict(item, keys={"tag"}, label="null value")
        return None

    kind = logical_type.type_kind
    if tag != kind:
        raise CanonicalArrowValueError("canonical value tag differs from its Arrow type")
    if kind == "bool":
        exact = _exact_dict(item, keys={"tag", "value"}, label="boolean value")
        if type(exact["value"]) is not bool:
            raise CanonicalArrowValueError("boolean value must be an exact bool")
        return exact["value"]
    if kind == "integer":
        exact = _exact_dict(item, keys={"tag", "value"}, label="integer value")
        assert logical_type.bit_width is not None and logical_type.signed is not None
        minimum = -(2 ** (logical_type.bit_width - 1)) if logical_type.signed else 0
        maximum = (
            2 ** (logical_type.bit_width - 1) - 1
            if logical_type.signed
            else 2**logical_type.bit_width - 1
        )
        return _parse_integer_text(
            exact["value"], minimum=minimum, maximum=maximum, label="integer"
        )
    if kind == "float":
        exact = _exact_dict(item, keys={"tag", "bits"}, label="float value")
        bits = exact["bits"]
        assert logical_type.bit_width is not None
        if (
            type(bits) is not str
            or len(bits) != logical_type.bit_width // 4
            or _LOWER_HEX_RE.fullmatch(bits) is None
        ):
            raise CanonicalArrowValueError("float bits are not fixed-width lowercase hex")
        raw = bytes.fromhex(bits)
        format_code = {16: ">e", 32: ">f", 64: ">d"}[logical_type.bit_width]
        return struct.unpack(format_code, raw)[0]
    if kind == "decimal":
        exact = _exact_dict(item, keys={"tag", "unscaled"}, label="decimal value")
        assert logical_type.precision is not None and logical_type.scale is not None
        maximum = 10**logical_type.precision - 1
        unscaled = _parse_integer_text(
            exact["unscaled"],
            minimum=-maximum,
            maximum=maximum,
            label="decimal unscaled value",
        )
        return _decimal_from_unscaled(unscaled, logical_type.scale)
    if kind == "utf8":
        exact = _exact_dict(item, keys={"tag", "value"}, label="UTF-8 value")
        if type(exact["value"]) is not str:
            raise CanonicalArrowValueError("UTF-8 value must be exact text")
        budget.reserve(
            utf8_bytes=_utf8_byte_length(exact["value"], label="canonical UTF-8 value"),
            depth=depth,
        )
        return exact["value"]
    if kind == "binary":
        exact = _exact_dict(
            item,
            keys={"tag", "byte_length", "hex"},
            label="binary value",
        )
        byte_length = _exact_nonnegative(
            exact["byte_length"],
            label="binary byte length",
            maximum=budget.limits.max_binary_bytes,
        )
        hex_value = exact["hex"]
        if (
            type(hex_value) is not str
            or _LOWER_HEX_RE.fullmatch(hex_value) is None
            or len(hex_value)
            != checked_product(
                byte_length,
                2,
                maximum=budget.limits.max_binary_bytes * 2,
                label="binary hex length",
            )
        ):
            raise CanonicalArrowValueError("binary value is not exact lowercase hex")
        if logical_type.byte_width is not None and byte_length != logical_type.byte_width:
            raise CanonicalArrowValueError("fixed-size binary value has the wrong length")
        budget.reserve(binary_bytes=byte_length, depth=depth)
        return bytes.fromhex(hex_value)
    if kind in {"date", "timestamp", "time", "duration"}:
        exact = _exact_dict(item, keys={"tag", "ticks"}, label=f"{kind} value")
        bit_width = logical_type.bit_width or 64
        ticks = _parse_integer_text(
            exact["ticks"],
            minimum=-(2 ** (bit_width - 1)),
            maximum=2 ** (bit_width - 1) - 1,
            label=f"{kind} ticks",
        )
        if kind == "time":
            units_per_second = {"s": 1, "ms": 1_000, "us": 1_000_000, "ns": 1_000_000_000}
            assert logical_type.unit is not None
            maximum_ticks = 86_400 * units_per_second[logical_type.unit]
            if ticks < 0 or ticks >= maximum_ticks:
                raise CanonicalArrowValueError("time ticks are outside one day")
        return _decode_temporal_ticks(ticks, logical_type)
    if kind in {"list", "list_view", "fixed_size_list"}:
        exact = _exact_dict(item, keys={"tag", "items"}, label="list value")
        items = exact["items"]
        if type(items) is not list or len(items) > budget.limits.max_container_items:
            raise CanonicalArrowValueError("list item inventory exceeds its bound")
        if kind == "fixed_size_list" and len(items) != logical_type.list_size:
            raise CanonicalArrowValueError("fixed-size list payload has the wrong length")
        budget.reserve(container_items=len(items), depth=depth)
        child_type = logical_type.children[0].logical_type
        return [
            _validate_value_payload(child, child_type, budget=budget, depth=depth + 1)
            for child in items
        ]
    if kind == "struct":
        exact = _exact_dict(item, keys={"tag", "fields"}, label="struct value")
        fields = exact["fields"]
        if type(fields) is not list or len(fields) != len(logical_type.children):
            raise CanonicalArrowValueError("struct field inventory is incomplete")
        budget.reserve(container_items=len(fields), depth=depth)
        result: dict[str, object] = {}
        for child, raw_field in zip(logical_type.children, fields, strict=True):
            field_payload = _exact_dict(
                raw_field,
                keys={"ordinal", "name", "value"},
                label="struct field value",
            )
            if field_payload["ordinal"] != child.ordinal or field_payload["name"] != child.name:
                raise CanonicalArrowValueError(
                    "struct field order or identity differs from its type"
                )
            result[child.name] = _validate_value_payload(
                field_payload["value"],
                child.logical_type,
                budget=budget,
                depth=depth + 1,
            )
        return result
    if kind == "dictionary":
        exact = _exact_dict(
            item,
            keys={"tag", "dictionary", "selection_valid", "value"},
            label="dictionary value",
        )
        selection_valid = exact["selection_valid"]
        if type(selection_valid) is not bool:
            raise CanonicalArrowValueError("dictionary selection validity must be an exact bool")
        raw_dictionary = exact["dictionary"]
        if (
            type(raw_dictionary) is not list
            or len(raw_dictionary) > budget.limits.max_container_items
        ):
            raise CanonicalArrowValueError("dictionary inventory exceeds its bound")
        budget.reserve(container_items=len(raw_dictionary), depth=depth)
        value_type = logical_type.children[1].logical_type
        for child in raw_dictionary:
            _validate_value_payload(child, value_type, budget=budget, depth=depth + 1)
        canonical_items = [
            _canonical_json_bytes(child, maximum_bytes=MAX_VALUE_CANONICAL_BYTES)
            for child in raw_dictionary
        ]
        if len(set(canonical_items)) != len(canonical_items):
            raise CanonicalArrowValueError("dictionary payload contains duplicate values")
        selected = _validate_value_payload(
            exact["value"],
            value_type,
            budget=budget,
            depth=depth + 1,
        )
        selected_bytes = _canonical_json_bytes(
            exact["value"],
            maximum_bytes=MAX_VALUE_CANONICAL_BYTES,
        )
        if not selection_valid and exact["value"] != {"tag": "null"}:
            raise CanonicalArrowValueError("null dictionary index has a selected logical value")
        if selection_valid and selected_bytes not in canonical_items:
            raise CanonicalArrowValueError("dictionary selected value is absent from its inventory")
        return selected
    raise CanonicalArrowValueError("canonical value payload uses an unsupported kind")


@dataclass(frozen=True, slots=True)
class CanonicalArrowValueV1:
    """One bounded, type-sensitive canonical Arrow scalar."""

    logical_type: ArrowLogicalTypeV1
    logical_type_sha256: str
    tag: str
    value_json: str
    node_count: int
    max_depth: int
    utf8_bytes: int
    binary_bytes: int
    container_items: int
    value_sha256: str

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "canonical_arrow_value"

    def __post_init__(self) -> None:
        if type(self.logical_type) is not ArrowLogicalTypeV1:
            raise CanonicalArrowValueError("canonical value logical type has a foreign type")
        if (
            type(self.logical_type_sha256) is not str
            or _SHA256_RE.fullmatch(self.logical_type_sha256) is None
            or self.logical_type_sha256 != self.logical_type.type_sha256
        ):
            raise CanonicalArrowValueError("canonical value logical type digest is invalid")
        if type(self.tag) is not str or not self.tag:
            raise CanonicalArrowValueError("canonical value tag must be exact text")
        if type(self.value_json) is not str:
            raise CanonicalArrowValueError("canonical value JSON must be exact text")
        try:
            encoded_value = self.value_json.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise CanonicalArrowValueError("canonical value JSON must be exact UTF-8") from exc
        payload = _strict_canonical_json_object(
            encoded_value,
            maximum_bytes=MAX_VALUE_CANONICAL_BYTES,
            maximum_depth=MAX_JSON_DEPTH,
            maximum_nodes=MAX_JSON_NODES,
        )
        for name, maximum in (
            ("node_count", MAX_VALUE_NODES),
            ("max_depth", MAX_JSON_DEPTH),
            ("utf8_bytes", MAX_VALUE_UTF8_BYTES),
            ("binary_bytes", MAX_VALUE_BINARY_BYTES),
            ("container_items", MAX_VALUE_CONTAINER_ITEMS),
        ):
            _exact_nonnegative(getattr(self, name), label=name, maximum=maximum)
        local = ValueBudget()
        _validate_value_payload(payload, self.logical_type, budget=local, depth=0)
        if payload.get("tag") != self.tag:
            raise CanonicalArrowValueError("canonical value tag differs from its payload")
        expected_counts = (
            local.nodes,
            local.max_depth_observed,
            local.utf8_bytes,
            local.binary_bytes,
            local.container_items,
        )
        observed_counts = (
            self.node_count,
            self.max_depth,
            self.utf8_bytes,
            self.binary_bytes,
            self.container_items,
        )
        if expected_counts != observed_counts:
            raise CanonicalArrowValueError("canonical value resource counts are invalid")
        if type(self.value_sha256) is not str or _SHA256_RE.fullmatch(self.value_sha256) is None:
            raise CanonicalArrowValueError("canonical value digest must be a lowercase SHA-256")
        if self.value_sha256 != _sha256_payload(
            self.identity_payload(),
            domain=b"nbadb-canonical-arrow-value-v1",
        ):
            raise CanonicalArrowValueError("canonical value digest differs from its identity")

    def value_payload(self) -> dict[str, object]:
        return _strict_canonical_json_object(
            self.value_json.encode("utf-8", errors="strict"),
            maximum_bytes=MAX_VALUE_CANONICAL_BYTES,
        )

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "logical_type": self.logical_type.to_dict(),
            "logical_type_sha256": self.logical_type_sha256,
            "tag": self.tag,
            "value": self.value_payload(),
            "node_count": self.node_count,
            "max_depth": self.max_depth,
            "utf8_bytes": self.utf8_bytes,
            "binary_bytes": self.binary_bytes,
            "container_items": self.container_items,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "value_sha256": self.value_sha256}

    def to_canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict(), maximum_bytes=MAX_CANONICAL_BYTES)

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes, *, budget: ValueBudget | None = None) -> Self:
        if budget is not None and type(budget) is not ValueBudget:
            raise CanonicalArrowValueError("canonical parser budget has a foreign type")
        maximum_bytes = _remaining_canonical_bytes(budget)
        payload = _strict_canonical_json_object(encoded, maximum_bytes=maximum_bytes)
        expected_keys = {
            "schema_version",
            "kind",
            "logical_type",
            "logical_type_sha256",
            "tag",
            "value",
            "node_count",
            "max_depth",
            "utf8_bytes",
            "binary_bytes",
            "container_items",
            "value_sha256",
        }
        if set(payload) != expected_keys:
            raise CanonicalArrowValueError("canonical Arrow value keys are invalid")
        if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
            raise CanonicalArrowValueError("canonical Arrow value schema version is invalid")
        if type(payload["kind"]) is not str or payload["kind"] != "canonical_arrow_value":
            raise CanonicalArrowValueError("canonical Arrow value kind is invalid")
        if budget is not None:
            declared_probe = _copy_budget(budget)
            declared_probe.reserve(
                nodes=cast("int", payload["node_count"]),
                depth=cast("int", payload["max_depth"]),
                utf8_bytes=cast("int", payload["utf8_bytes"]),
                binary_bytes=cast("int", payload["binary_bytes"]),
                container_items=cast("int", payload["container_items"]),
                canonical_bytes=len(encoded),
            )
        logical_type = _logical_type_from_dict(payload["logical_type"])
        if canonical_arrow_type(logical_type.to_arrow_type()) != logical_type:
            raise CanonicalArrowValueError("canonical value Arrow type is not an exact fixed point")
        value_json = _canonical_json_bytes(
            payload["value"],
            maximum_bytes=MAX_VALUE_CANONICAL_BYTES,
        ).decode("utf-8")
        if budget is not None:
            local_probe = ValueBudget(limits=budget.limits)
            _validate_value_payload(
                payload["value"],
                logical_type,
                budget=_active_value_budget(local_probe, budget),
                depth=0,
            )
            if (
                local_probe.nodes,
                local_probe.max_depth_observed,
                local_probe.utf8_bytes,
                local_probe.binary_bytes,
                local_probe.container_items,
            ) != (
                payload["node_count"],
                payload["max_depth"],
                payload["utf8_bytes"],
                payload["binary_bytes"],
                payload["container_items"],
            ):
                raise CanonicalArrowValueError("canonical value resource counts are invalid")
        result = cls(
            logical_type=logical_type,
            logical_type_sha256=cast("str", payload["logical_type_sha256"]),
            tag=cast("str", payload["tag"]),
            value_json=value_json,
            node_count=cast("int", payload["node_count"]),
            max_depth=cast("int", payload["max_depth"]),
            utf8_bytes=cast("int", payload["utf8_bytes"]),
            binary_bytes=cast("int", payload["binary_bytes"]),
            container_items=cast("int", payload["container_items"]),
            value_sha256=cast("str", payload["value_sha256"]),
        )
        if result.to_canonical_bytes() != encoded:
            raise CanonicalArrowValueError("canonical Arrow value bytes are not exact")
        if budget is not None:
            budget.reserve(
                nodes=result.node_count,
                depth=result.max_depth,
                utf8_bytes=result.utf8_bytes,
                binary_bytes=result.binary_bytes,
                container_items=result.container_items,
                canonical_bytes=len(encoded),
            )
        return result


def _finish_canonical_value(
    payload: dict[str, object],
    logical_type: ArrowLogicalTypeV1,
    local: ValueBudget,
    *,
    budget: ValueBudget | None,
) -> CanonicalArrowValueV1:
    remaining_canonical_bytes = _remaining_canonical_bytes(budget)
    logical_type_payload = logical_type.to_dict()
    prospective_identity: dict[str, object] = {
        "schema_version": 1,
        "kind": "canonical_arrow_value",
        "logical_type": logical_type_payload,
        "logical_type_sha256": "0" * 64,
        "tag": payload["tag"],
        "value": payload,
        "node_count": local.nodes,
        "max_depth": local.max_depth_observed,
        "utf8_bytes": local.utf8_bytes,
        "binary_bytes": local.binary_bytes,
        "container_items": local.container_items,
    }
    prospective_wire = {**prospective_identity, "value_sha256": "0" * 64}
    _canonical_json_size(
        prospective_wire,
        maximum_bytes=remaining_canonical_bytes,
    )
    value_json = _canonical_json_bytes(
        payload,
        maximum_bytes=remaining_canonical_bytes,
    ).decode("utf-8")
    logical_type_sha256 = logical_type.type_sha256
    identity = {
        **prospective_identity,
        "logical_type_sha256": logical_type_sha256,
    }
    result = CanonicalArrowValueV1(
        logical_type=logical_type,
        logical_type_sha256=logical_type_sha256,
        tag=cast("str", payload["tag"]),
        value_json=value_json,
        node_count=local.nodes,
        max_depth=local.max_depth_observed,
        utf8_bytes=local.utf8_bytes,
        binary_bytes=local.binary_bytes,
        container_items=local.container_items,
        value_sha256=_sha256_payload(identity, domain=b"nbadb-canonical-arrow-value-v1"),
    )
    encoded_size = len(result.to_canonical_bytes())
    if encoded_size > remaining_canonical_bytes:
        raise CanonicalArrowValueError("canonical Arrow value exceeds its byte budget")
    if budget is not None:
        budget.reserve(
            nodes=local.nodes,
            depth=local.max_depth_observed,
            utf8_bytes=local.utf8_bytes,
            binary_bytes=local.binary_bytes,
            container_items=local.container_items,
            canonical_bytes=encoded_size,
        )
    return result


def _preflight_minimum_value_budget(budget: ValueBudget | None) -> None:
    if budget is None:
        return
    probe = _copy_budget(budget)
    probe.reserve(
        nodes=1,
        depth=0,
        canonical_bytes=MIN_CANONICAL_ARROW_VALUE_BYTES,
    )


def _build_canonical_value(
    array: pa.Array,
    index: int,
    *,
    budget: ValueBudget | None,
) -> CanonicalArrowValueV1:
    _preflight_minimum_value_budget(budget)
    limits = budget.limits if budget is not None else ValueBudgetLimits()
    local = ValueBudget(limits=limits)
    active = _active_value_budget(local, budget)
    payload = _payload_from_array(array, index, budget=active, depth=0)
    return _finish_canonical_value(
        payload,
        canonical_arrow_type(array.type),
        local,
        budget=budget,
    )


def _exact_dictionary_context(
    context: pa.Array | pa.ChunkedArray,
    dtype: pa.DataType,
) -> pa.DictionaryArray:
    candidate: pa.Array
    if isinstance(context, pa.ChunkedArray):
        if context.num_chunks != 1:
            raise CanonicalArrowValueError(
                "dictionary context must be one materialized unified Arrow chunk"
            )
        candidate = context.chunk(0)
    elif isinstance(context, pa.Array):
        candidate = context
    else:
        raise CanonicalArrowValueError("dictionary context requires an exact Arrow array")
    if not isinstance(candidate, pa.DictionaryArray) or not candidate.type.equals(dtype):
        raise CanonicalArrowValueError("dictionary context type differs from the requested type")
    return candidate


def _dictionary_selection_payload(
    value: object,
    dtype: pa.DataType,
    *,
    budget: _ActiveValueBudget,
    depth: int,
) -> tuple[bool, dict[str, object]]:
    if isinstance(value, pa.DictionaryScalar):
        if not value.type.equals(dtype):
            raise CanonicalArrowValueError("dictionary scalar type differs from requested type")
        if not value.is_valid:
            budget.reserve(nodes=1, depth=depth)
            return False, {"tag": "null"}
        raw_index = value.index.as_py()
        if type(raw_index) is not int or raw_index < 0 or raw_index >= len(value.dictionary):
            raise CanonicalArrowValueError("dictionary scalar index is out of range")
        return True, _payload_from_array(
            value.dictionary,
            raw_index,
            budget=budget,
            depth=depth,
        )
    if value is None:
        budget.reserve(nodes=1, depth=depth)
        return False, {"tag": "null"}
    candidate = _array_from_scalar(value, dtype.value_type)
    return True, _payload_from_array(candidate, 0, budget=budget, depth=depth)


def _build_dictionary_context_value(
    value: object,
    dtype: pa.DataType,
    context: pa.Array | pa.ChunkedArray,
    *,
    budget: ValueBudget | None,
) -> CanonicalArrowValueV1:
    _preflight_minimum_value_budget(budget)
    dictionary_array = _exact_dictionary_context(context, dtype)
    limits = budget.limits if budget is not None else ValueBudgetLimits()
    local = ValueBudget(limits=limits)
    active = _active_value_budget(local, budget)
    active.reserve(nodes=1, depth=0)
    dictionary_size = len(dictionary_array.dictionary)
    active.reserve(container_items=dictionary_size, depth=0)
    dictionary_payloads: list[dict[str, object]] = []
    for item_index in range(dictionary_size):
        dictionary_payloads.append(
            _payload_from_array(
                dictionary_array.dictionary,
                item_index,
                budget=active,
                depth=1,
            )
        )
    canonical_items = [
        _canonical_json_bytes(item, maximum_bytes=MAX_VALUE_CANONICAL_BYTES)
        for item in dictionary_payloads
    ]
    if len(set(canonical_items)) != len(canonical_items):
        raise CanonicalArrowValueError("dictionary values must be unique")
    selection_valid, selected = _dictionary_selection_payload(
        value,
        dtype,
        budget=active,
        depth=1,
    )
    selected_bytes = _canonical_json_bytes(
        selected,
        maximum_bytes=MAX_VALUE_CANONICAL_BYTES,
    )
    if selection_valid and selected_bytes not in canonical_items:
        raise CanonicalArrowValueError(
            "decoder value is absent from the committed dictionary context"
        )
    payload: dict[str, object] = {
        "tag": "dictionary",
        "dictionary": dictionary_payloads,
        "selection_valid": selection_valid,
        "value": selected,
    }
    return _finish_canonical_value(
        payload,
        canonical_arrow_type(dtype),
        local,
        budget=budget,
    )


def canonical_arrow_array_scalar(
    array: pa.Array | pa.ChunkedArray,
    index: int,
    *,
    budget: ValueBudget | None = None,
) -> CanonicalArrowValueV1:
    """Canonicalize one exact scalar from an Arrow array or chunked array."""

    if type(index) is not int or index < 0:
        raise CanonicalArrowValueError("Arrow scalar index must be a nonnegative exact integer")
    if budget is not None and type(budget) is not ValueBudget:
        raise CanonicalArrowValueError("canonical Arrow value budget has a foreign type")
    _preflight_minimum_value_budget(budget)
    if isinstance(array, pa.ChunkedArray):
        if index >= len(array):
            raise CanonicalArrowValueError("Arrow scalar index exceeds the chunked array")
        cursor = index
        for chunk in array.chunks:
            if cursor < len(chunk):
                return _build_canonical_value(chunk, cursor, budget=budget)
            cursor -= len(chunk)
        raise CanonicalArrowValueError("Arrow chunk inventory is incomplete")
    if not isinstance(array, pa.Array):
        raise CanonicalArrowValueError("canonical Arrow value requires an Array")
    if index >= len(array):
        raise CanonicalArrowValueError("Arrow scalar index exceeds the array")
    return _build_canonical_value(array, index, budget=budget)


def canonical_arrow_scalar(
    value: object,
    dtype: pa.DataType,
    *,
    dictionary_context: pa.Array | pa.ChunkedArray | None = None,
    budget: ValueBudget | None = None,
) -> CanonicalArrowValueV1:
    """Canonicalize a strict scalar, optionally under a committed dictionary."""

    if budget is not None and type(budget) is not ValueBudget:
        raise CanonicalArrowValueError("canonical Arrow value budget has a foreign type")
    _preflight_minimum_value_budget(budget)
    canonical_arrow_type(dtype)  # validates the closed type family before allocation
    if dictionary_context is not None:
        if not pa.types.is_dictionary(dtype):
            raise CanonicalArrowValueError(
                "dictionary context cannot be applied to a non-dictionary Arrow type"
            )
        preflight_local = ValueBudget(
            limits=budget.limits if budget is not None else ValueBudgetLimits()
        )
        preflight = _active_value_budget(preflight_local, budget)
        if not isinstance(value, pa.DictionaryScalar) and value is not None:
            _strict_python_value(
                value,
                dtype.value_type,
                budget=preflight,
            )
        return _build_dictionary_context_value(
            value,
            dtype,
            dictionary_context,
            budget=budget,
        )
    preflight_local = ValueBudget(
        limits=budget.limits if budget is not None else ValueBudgetLimits()
    )
    _strict_python_value(
        value,
        dtype,
        budget=_active_value_budget(preflight_local, budget),
    )
    array = _array_from_scalar(value, dtype)
    return canonical_arrow_array_scalar(array, 0, budget=budget)


def decode_canonical_arrow_value(value: CanonicalArrowValueV1 | bytes) -> object:
    """Decode the logical scalar while preserving exact validation at the boundary."""

    parsed = CanonicalArrowValueV1.from_canonical_bytes(value) if type(value) is bytes else value
    if type(parsed) is not CanonicalArrowValueV1:
        raise CanonicalArrowValueError("canonical Arrow value has a foreign concrete type")
    local = ValueBudget()
    return _validate_value_payload(
        parsed.value_payload(),
        parsed.logical_type,
        budget=local,
        depth=0,
    )


def compare_canonical_arrow_values(
    left: CanonicalArrowValueV1 | bytes,
    right: CanonicalArrowValueV1 | bytes,
) -> bool:
    """Return exact type-and-value equality for two independently validated values."""

    first = CanonicalArrowValueV1.from_canonical_bytes(left) if type(left) is bytes else left
    second = CanonicalArrowValueV1.from_canonical_bytes(right) if type(right) is bytes else right
    if type(first) is not CanonicalArrowValueV1 or type(second) is not CanonicalArrowValueV1:
        raise CanonicalArrowValueError("canonical Arrow comparison requires exact receipt types")
    return (
        first.logical_type_sha256 == second.logical_type_sha256
        and first.value_json == second.value_json
    )
