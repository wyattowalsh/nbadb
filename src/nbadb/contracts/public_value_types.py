"""Value-free dependency types for Public Value Authority V1.

This module is intentionally a small dependency kernel.  It defines only the
closed public-value domains and the immutable identities needed to derive an
ordered expected-unit denominator and bind one representation to each unit.
It carries no provider values, headers, paths, local filesystem material, or
free-form metadata.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import ClassVar, Final, Literal, Never, Self, cast

__all__ = [
    "EXPECTED_VALUE_UNIT_KINDS_V1",
    "MAX_PUBLIC_VALUE_EXPECTED_UNITS",
    "PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION",
    "PUBLIC_VALUE_REPRESENTATION_KINDS_V1",
    "PUBLIC_VALUE_SOURCE_INPUT_KINDS_V1",
    "ExpectedValueUnitInventoryV1",
    "ExpectedValueUnitKindV1",
    "ExpectedValueUnitV1",
    "PublicValueRepresentationKindV1",
    "PublicValueSourceInputKindV1",
    "PublicValueTypesError",
    "ValueRepresentationAssignmentV1",
]


PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION: Final = 1

PublicValueRepresentationKindV1 = Literal[
    "rectangular_result_cells_v1",
    "stats_lossless_records_v1",
    "live_lossless_nodes_v1",
    "response_lossless_records_v1",
    "response_fixed_zero_v1",
]
PublicValueSourceInputKindV1 = Literal[
    "parser_input_body",
    "declared_bodyless_packet",
]
ExpectedValueUnitKindV1 = Literal[
    "result_occurrence",
    "response_residual",
    "response_fixed_zero",
]

PUBLIC_VALUE_REPRESENTATION_KINDS_V1: Final[tuple[PublicValueRepresentationKindV1, ...]] = (
    "rectangular_result_cells_v1",
    "stats_lossless_records_v1",
    "live_lossless_nodes_v1",
    "response_lossless_records_v1",
    "response_fixed_zero_v1",
)
PUBLIC_VALUE_SOURCE_INPUT_KINDS_V1: Final[tuple[PublicValueSourceInputKindV1, ...]] = (
    "parser_input_body",
    "declared_bodyless_packet",
)
EXPECTED_VALUE_UNIT_KINDS_V1: Final[tuple[ExpectedValueUnitKindV1, ...]] = (
    "result_occurrence",
    "response_residual",
    "response_fixed_zero",
)

MAX_PUBLIC_VALUE_EXPECTED_UNITS: Final = 100_000
_MAX_ORDINAL: Final = (1 << 63) - 1
_MAX_INVENTORY_JSON_BYTES: Final = 64 * 1024 * 1024
_MAX_CANONICAL_NODES: Final = (MAX_PUBLIC_VALUE_EXPECTED_UNITS * 24) + 128
_MAX_JSON_DEPTH: Final = 8
_MAX_JSON_STRING_BYTES: Final = 4_096
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")

_EXPECTED_UNIT_KIND: Final = "nbadb_expected_value_unit_v1"
_EXPECTED_UNIT_INVENTORY_KIND: Final = "nbadb_expected_value_unit_inventory_v1"
_VALUE_REPRESENTATION_ASSIGNMENT_KIND: Final = "nbadb_value_representation_assignment_v1"
_UNIT_ROOT_KIND: Final = "nbadb_expected_value_unit_ordered_root_v1"

_UNIT_ROW_FIELDS: Final = (
    "schema_version",
    "unit_sha256",
    "raw_authority_bundle_sha256",
    "unit_ordinal",
    "observation_sha256",
    "observation_ordinal",
    "unit_kind",
    "occurrence_sha256",
    "occurrence_ordinal",
)
_INVENTORY_ROW_FIELDS: Final = (
    "schema_version",
    "inventory_sha256",
    "raw_authority_bundle_sha256",
    "unit_count",
    "unit_root_sha256",
    "units_json",
)
_ASSIGNMENT_ROW_FIELDS: Final = (
    "schema_version",
    "assignment_sha256",
    "raw_authority_bundle_sha256",
    "unit_sha256",
    "unit_ordinal",
    "source_input_kind",
    "representation_kind",
)

_REPRESENTATION_KINDS = frozenset(PUBLIC_VALUE_REPRESENTATION_KINDS_V1)
_SOURCE_INPUT_KINDS = frozenset(PUBLIC_VALUE_SOURCE_INPUT_KINDS_V1)
_UNIT_KINDS = frozenset(EXPECTED_VALUE_UNIT_KINDS_V1)
_RESULT_REPRESENTATION_KINDS = frozenset(
    {
        "rectangular_result_cells_v1",
        "stats_lossless_records_v1",
        "live_lossless_nodes_v1",
    }
)


class PublicValueTypesError(ValueError):
    """One public-value dependency identity is unsafe or inconsistent."""


def _fail(message: str) -> Never:
    raise PublicValueTypesError(message)


def _exact_sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be one lowercase full SHA-256")
    return value


def _exact_ordinal(value: object, *, label: str) -> int:
    if type(value) is not int or value < 0 or value > _MAX_ORDINAL:
        _fail(f"{label} must be one bounded nonnegative exact integer")
    return value


def _exact_count(value: object, *, label: str) -> int:
    exact = _exact_ordinal(value, label=label)
    if exact > MAX_PUBLIC_VALUE_EXPECTED_UNITS:
        _fail(f"{label} exceeds the public-value unit bound")
    return exact


def _preflight_builtin_graph(value: object, *, maximum_string_bytes: int) -> None:
    """Bound and exact-type-check internal canonicalization before encoding."""

    stack: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    cumulative_string_bytes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_CANONICAL_NODES or depth > _MAX_JSON_DEPTH:
            _fail("public-value canonical input exceeds its structural bound")
        if item is None or type(item) is bool:
            continue
        if type(item) is int:
            if item < -_MAX_ORDINAL or item > _MAX_ORDINAL:
                _fail("public-value canonical input contains an unbounded integer")
            continue
        if type(item) is str:
            try:
                encoded_length = len(item.encode("utf-8", errors="strict"))
            except UnicodeEncodeError:
                _fail("public-value canonical input contains invalid Unicode")
            cumulative_string_bytes += encoded_length
            if cumulative_string_bytes > maximum_string_bytes:
                _fail("public-value canonical input exceeds its string-byte bound")
            continue
        if type(item) in {tuple, list}:
            sequence = cast("tuple[object, ...] | list[object]", item)
            stack.extend((child, depth + 1) for child in reversed(sequence))
            continue
        if type(item) is dict:
            mapping = cast("dict[object, object]", item)
            for key, child in reversed(tuple(mapping.items())):
                if type(key) is not str:
                    _fail("public-value canonical input contains a non-string key")
                try:
                    key_bytes = len(key.encode("utf-8", errors="strict"))
                except UnicodeEncodeError:
                    _fail("public-value canonical input contains invalid Unicode")
                cumulative_string_bytes += key_bytes
                if cumulative_string_bytes > maximum_string_bytes:
                    _fail("public-value canonical input exceeds its string-byte bound")
                stack.append((child, depth + 1))
            continue
        _fail("public-value canonical input contains a foreign exact type")


def _canonical_json_bytes(value: object, *, maximum_bytes: int) -> bytes:
    _preflight_builtin_graph(value, maximum_string_bytes=maximum_bytes)
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8", errors="strict")
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("public-value identity is not canonical JSON")
    if not encoded or len(encoded) > maximum_bytes:
        _fail("public-value canonical JSON exceeds its byte bound")
    return encoded


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha256(value: object, *, maximum_bytes: int = 64 * 1024) -> str:
    return _sha256_bytes(_canonical_json_bytes(value, maximum_bytes=maximum_bytes))


def _strict_row(
    value: object,
    *,
    expected_fields: tuple[str, ...],
    label: str,
) -> dict[str, object]:
    if type(value) is not dict:
        _fail(f"{label} does not have its exact ordered row shape")
    object_row = cast("dict[object, object]", value)
    if any(type(key) is not str for key in object_row) or tuple(object_row) != expected_fields:
        _fail(f"{label} does not have its exact ordered row shape")
    return cast("dict[str, object]", value)


def _exact_schema_version(value: object, *, label: str) -> None:
    if type(value) is not int or value != PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION:
        _fail(f"{label} schema version is invalid")


def _unit_identity_payload(
    *,
    raw_authority_bundle_sha256: str,
    unit_ordinal: int,
    observation_sha256: str,
    observation_ordinal: int,
    unit_kind: ExpectedValueUnitKindV1,
    occurrence_sha256: str | None,
    occurrence_ordinal: int | None,
) -> dict[str, object]:
    return {
        "kind": _EXPECTED_UNIT_KIND,
        "schema_version": PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
        "raw_authority_bundle_sha256": raw_authority_bundle_sha256,
        "unit_ordinal": unit_ordinal,
        "observation_sha256": observation_sha256,
        "observation_ordinal": observation_ordinal,
        "unit_kind": unit_kind,
        "occurrence_sha256": occurrence_sha256,
        "occurrence_ordinal": occurrence_ordinal,
    }


def _ordered_unit_root(
    *,
    raw_authority_bundle_sha256: str,
    units: tuple[ExpectedValueUnitV1, ...],
) -> str:
    digest = hashlib.sha256()
    digest.update(b'{"count":')
    digest.update(str(len(units)).encode("ascii"))
    digest.update(b',"items":[')
    for ordinal, unit in enumerate(units):
        if ordinal:
            digest.update(b",")
        digest.update(_canonical_json_bytes(unit.unit_sha256, maximum_bytes=256))
    digest.update(b'],"kind":')
    digest.update(_canonical_json_bytes(_UNIT_ROOT_KIND, maximum_bytes=256))
    digest.update(b',"raw_authority_bundle_sha256":')
    digest.update(_canonical_json_bytes(raw_authority_bundle_sha256, maximum_bytes=256))
    digest.update(b',"schema_version":1}')
    return digest.hexdigest()


def _inventory_identity_payload(
    *,
    raw_authority_bundle_sha256: str,
    units: tuple[ExpectedValueUnitV1, ...],
    unit_root_sha256: str,
) -> dict[str, object]:
    return {
        "kind": _EXPECTED_UNIT_INVENTORY_KIND,
        "schema_version": PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
        "raw_authority_bundle_sha256": raw_authority_bundle_sha256,
        "unit_count": len(units),
        "unit_root_sha256": unit_root_sha256,
        "units": [unit.to_row() for unit in units],
    }


def _assignment_identity_payload(
    *,
    raw_authority_bundle_sha256: str,
    unit_sha256: str,
    unit_ordinal: int,
    source_input_kind: PublicValueSourceInputKindV1,
    representation_kind: PublicValueRepresentationKindV1,
) -> dict[str, object]:
    return {
        "kind": _VALUE_REPRESENTATION_ASSIGNMENT_KIND,
        "schema_version": PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
        "raw_authority_bundle_sha256": raw_authority_bundle_sha256,
        "unit_sha256": unit_sha256,
        "unit_ordinal": unit_ordinal,
        "source_input_kind": source_input_kind,
        "representation_kind": representation_kind,
    }


def _preflight_json_bytes(value: bytes) -> None:
    depth = 0
    maximum_depth = 0
    structural_nodes = 1
    in_string = False
    escaped = False
    string_bytes = 0
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
                if string_bytes > _MAX_JSON_STRING_BYTES:
                    _fail("public-value inventory contains an over-bound string")
                string_bytes = 0
            else:
                string_bytes += 1
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
                _fail("public-value inventory JSON is invalid")
        elif byte in (0x2C, 0x3A):
            structural_nodes += 1
        if maximum_depth > _MAX_JSON_DEPTH or structural_nodes > _MAX_CANONICAL_NODES:
            _fail("public-value inventory JSON exceeds its structural bound")
    if in_string or escaped or depth != 0:
        _fail("public-value inventory JSON is invalid")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("public-value inventory JSON contains duplicate object keys")
        result[key] = value
    return result


def _bounded_json_integer(token: str) -> int:
    if len(token) > 20:
        _fail("public-value inventory contains an over-bound integer token")
    value = int(token)
    if value < -_MAX_ORDINAL or value > _MAX_ORDINAL:
        _fail("public-value inventory contains an over-bound integer")
    return value


def _reject_json_number(_token: str) -> Never:
    _fail("public-value inventory contains a non-integer number")


def _decode_units_json(value: object) -> tuple[ExpectedValueUnitV1, ...]:
    if type(value) is not str:
        _fail("public-value unit inventory JSON must be exact text")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _fail("public-value unit inventory JSON is not strict UTF-8")
    if len(encoded) < 2 or len(encoded) > _MAX_INVENTORY_JSON_BYTES:
        _fail("public-value unit inventory JSON exceeds its byte bound")
    _preflight_json_bytes(encoded)
    try:
        decoded = json.loads(
            encoded,
            object_pairs_hook=_reject_duplicate_keys,
            parse_int=_bounded_json_integer,
            parse_float=_reject_json_number,
            parse_constant=_reject_json_number,
        )
    except PublicValueTypesError:
        raise
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError, ValueError):
        _fail("public-value unit inventory JSON is invalid")
    if type(decoded) is not list:
        _fail("public-value unit inventory JSON must contain one exact array")
    values = cast("list[object]", decoded)
    if len(values) > MAX_PUBLIC_VALUE_EXPECTED_UNITS:
        _fail("public-value unit inventory exceeds its unit bound")
    if _canonical_json_bytes(decoded, maximum_bytes=_MAX_INVENTORY_JSON_BYTES) != encoded:
        _fail("public-value unit inventory JSON is not canonical")
    units: list[ExpectedValueUnitV1] = []
    sorted_fields = tuple(sorted(_UNIT_ROW_FIELDS))
    for value_row in values:
        if type(value_row) is not dict:
            _fail("public-value unit inventory contains a non-row member")
        object_row = cast("dict[object, object]", value_row)
        if any(type(key) is not str for key in object_row) or tuple(object_row) != sorted_fields:
            _fail("public-value unit inventory contains a noncanonical row")
        decoded_row = cast("dict[str, object]", value_row)
        ordered_row = {field_name: decoded_row[field_name] for field_name in _UNIT_ROW_FIELDS}
        units.append(ExpectedValueUnitV1.from_row(ordered_row))
    return tuple(units)


@dataclass(frozen=True, slots=True)
class ExpectedValueUnitV1:
    """One value-free occurrence, response-residual, or fixed-zero unit."""

    unit_sha256: str
    raw_authority_bundle_sha256: str
    unit_ordinal: int
    observation_sha256: str
    observation_ordinal: int
    unit_kind: ExpectedValueUnitKindV1
    occurrence_sha256: str | None
    occurrence_ordinal: int | None

    schema_version: ClassVar[int] = PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION
    kind: ClassVar[str] = _EXPECTED_UNIT_KIND

    def __post_init__(self) -> None:
        _exact_sha256(self.unit_sha256, label="expected-unit identity")
        _exact_sha256(
            self.raw_authority_bundle_sha256,
            label="expected-unit raw-authority bundle",
        )
        _exact_ordinal(self.unit_ordinal, label="expected-unit ordinal")
        _exact_sha256(self.observation_sha256, label="expected-unit observation")
        _exact_ordinal(self.observation_ordinal, label="expected-unit observation ordinal")
        if type(self.unit_kind) is not str or self.unit_kind not in _UNIT_KINDS:
            _fail("expected-unit kind is outside the closed V1 domain")
        if self.unit_kind == "result_occurrence":
            _exact_sha256(self.occurrence_sha256, label="expected-unit occurrence")
            _exact_ordinal(self.occurrence_ordinal, label="expected-unit occurrence ordinal")
        elif self.occurrence_sha256 is not None or self.occurrence_ordinal is not None:
            _fail("response expected units cannot carry occurrence identity or order")
        expected = _canonical_sha256(
            _unit_identity_payload(
                raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                unit_ordinal=self.unit_ordinal,
                observation_sha256=self.observation_sha256,
                observation_ordinal=self.observation_ordinal,
                unit_kind=self.unit_kind,
                occurrence_sha256=self.occurrence_sha256,
                occurrence_ordinal=self.occurrence_ordinal,
            )
        )
        if self.unit_sha256 != expected:
            _fail("expected-unit digest differs from its exact semantic identity")

    @classmethod
    def build(
        cls,
        *,
        raw_authority_bundle_sha256: str,
        unit_ordinal: int,
        observation_sha256: str,
        observation_ordinal: int,
        unit_kind: ExpectedValueUnitKindV1,
        occurrence_sha256: str | None = None,
        occurrence_ordinal: int | None = None,
    ) -> Self:
        payload = _unit_identity_payload(
            raw_authority_bundle_sha256=raw_authority_bundle_sha256,
            unit_ordinal=unit_ordinal,
            observation_sha256=observation_sha256,
            observation_ordinal=observation_ordinal,
            unit_kind=unit_kind,
            occurrence_sha256=occurrence_sha256,
            occurrence_ordinal=occurrence_ordinal,
        )
        return cls(
            unit_sha256=_canonical_sha256(payload),
            raw_authority_bundle_sha256=raw_authority_bundle_sha256,
            unit_ordinal=unit_ordinal,
            observation_sha256=observation_sha256,
            observation_ordinal=observation_ordinal,
            unit_kind=unit_kind,
            occurrence_sha256=occurrence_sha256,
            occurrence_ordinal=occurrence_ordinal,
        )

    def to_row(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "unit_sha256": self.unit_sha256,
            "raw_authority_bundle_sha256": self.raw_authority_bundle_sha256,
            "unit_ordinal": self.unit_ordinal,
            "observation_sha256": self.observation_sha256,
            "observation_ordinal": self.observation_ordinal,
            "unit_kind": self.unit_kind,
            "occurrence_sha256": self.occurrence_sha256,
            "occurrence_ordinal": self.occurrence_ordinal,
        }

    @classmethod
    def from_row(cls, value: object) -> Self:
        row = _strict_row(value, expected_fields=_UNIT_ROW_FIELDS, label="expected-unit row")
        _exact_schema_version(row["schema_version"], label="expected-unit row")
        try:
            return cls(
                unit_sha256=cast("str", row["unit_sha256"]),
                raw_authority_bundle_sha256=cast("str", row["raw_authority_bundle_sha256"]),
                unit_ordinal=cast("int", row["unit_ordinal"]),
                observation_sha256=cast("str", row["observation_sha256"]),
                observation_ordinal=cast("int", row["observation_ordinal"]),
                unit_kind=cast("ExpectedValueUnitKindV1", row["unit_kind"]),
                occurrence_sha256=cast("str | None", row["occurrence_sha256"]),
                occurrence_ordinal=cast("int | None", row["occurrence_ordinal"]),
            )
        except PublicValueTypesError:
            raise
        except (TypeError, ValueError) as exc:
            raise PublicValueTypesError(
                "expected-unit row failed exact semantic reconstruction"
            ) from exc

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_row(), maximum_bytes=4_096)


@dataclass(frozen=True, slots=True)
class ExpectedValueUnitInventoryV1:
    """One count- and order-bound expected-unit denominator."""

    inventory_sha256: str
    raw_authority_bundle_sha256: str
    unit_count: int
    unit_root_sha256: str
    units: tuple[ExpectedValueUnitV1, ...]

    schema_version: ClassVar[int] = PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION
    kind: ClassVar[str] = _EXPECTED_UNIT_INVENTORY_KIND

    def __post_init__(self) -> None:
        _exact_sha256(self.inventory_sha256, label="expected-unit inventory identity")
        _exact_sha256(
            self.raw_authority_bundle_sha256,
            label="expected-unit inventory raw-authority bundle",
        )
        _exact_count(self.unit_count, label="expected-unit inventory count")
        _exact_sha256(self.unit_root_sha256, label="expected-unit inventory root")
        if type(self.units) is not tuple or len(self.units) != self.unit_count:
            _fail("expected-unit inventory count differs from its exact tuple")
        if any(type(unit) is not ExpectedValueUnitV1 for unit in self.units):
            _fail("expected-unit inventory contains a foreign DTO type")

        seen_unit_sha256s: set[str] = set()
        seen_occurrences: set[tuple[str, str]] = set()
        seen_observations: set[str] = set()
        active_observation_sha256: str | None = None
        active_observation_ordinal = -1
        expected_occurrence_ordinal = 0
        response_seen = False
        for unit_ordinal, unit in enumerate(self.units):
            if ExpectedValueUnitV1.from_row(unit.to_row()) != unit:
                _fail("expected-unit inventory member fails exact row replay")
            if unit.raw_authority_bundle_sha256 != self.raw_authority_bundle_sha256:
                _fail("expected-unit inventory contains a foreign raw-authority bundle")
            if unit.unit_ordinal != unit_ordinal:
                _fail("expected-unit inventory order differs from its declared ordinals")
            if unit.unit_sha256 in seen_unit_sha256s:
                _fail("expected-unit inventory contains a duplicate unit identity")
            seen_unit_sha256s.add(unit.unit_sha256)

            if unit.observation_sha256 != active_observation_sha256:
                if unit.observation_sha256 in seen_observations:
                    _fail("expected-unit inventory reopens a completed observation")
                seen_observations.add(unit.observation_sha256)
                active_observation_sha256 = unit.observation_sha256
                active_observation_ordinal += 1
                expected_occurrence_ordinal = 0
                response_seen = False
            if unit.observation_ordinal != active_observation_ordinal:
                _fail("expected-unit observation order is not canonical and contiguous")

            if unit.unit_kind == "result_occurrence":
                if response_seen or unit.occurrence_ordinal != expected_occurrence_ordinal:
                    _fail("expected-unit occurrence order is not canonical and contiguous")
                occurrence_identity = (
                    unit.observation_sha256,
                    cast("str", unit.occurrence_sha256),
                )
                if occurrence_identity in seen_occurrences:
                    _fail("expected-unit inventory contains a duplicate occurrence")
                seen_occurrences.add(occurrence_identity)
                expected_occurrence_ordinal += 1
            else:
                if response_seen:
                    _fail("expected-unit observation contains several response units")
                if unit.unit_kind == "response_fixed_zero" and expected_occurrence_ordinal != 0:
                    _fail("fixed-zero response unit cannot follow a result occurrence")
                response_seen = True

        expected_root = _ordered_unit_root(
            raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
            units=self.units,
        )
        if self.unit_root_sha256 != expected_root:
            _fail("expected-unit inventory root differs from its ordered denominator")
        expected_inventory_sha256 = _canonical_sha256(
            _inventory_identity_payload(
                raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                units=self.units,
                unit_root_sha256=expected_root,
            ),
            maximum_bytes=_MAX_INVENTORY_JSON_BYTES,
        )
        if self.inventory_sha256 != expected_inventory_sha256:
            _fail("expected-unit inventory digest differs from its exact contents")

    @classmethod
    def build(
        cls,
        *,
        raw_authority_bundle_sha256: str,
        units: tuple[ExpectedValueUnitV1, ...],
    ) -> Self:
        _exact_sha256(
            raw_authority_bundle_sha256,
            label="expected-unit inventory raw-authority bundle",
        )
        if type(units) is not tuple:
            _fail("expected-unit inventory builder requires one exact tuple")
        if len(units) > MAX_PUBLIC_VALUE_EXPECTED_UNITS:
            _fail("expected-unit inventory exceeds its unit bound")
        if any(type(unit) is not ExpectedValueUnitV1 for unit in units):
            _fail("expected-unit inventory builder contains a foreign DTO type")
        unit_root_sha256 = _ordered_unit_root(
            raw_authority_bundle_sha256=raw_authority_bundle_sha256,
            units=units,
        )
        return cls(
            inventory_sha256=_canonical_sha256(
                _inventory_identity_payload(
                    raw_authority_bundle_sha256=raw_authority_bundle_sha256,
                    units=units,
                    unit_root_sha256=unit_root_sha256,
                ),
                maximum_bytes=_MAX_INVENTORY_JSON_BYTES,
            ),
            raw_authority_bundle_sha256=raw_authority_bundle_sha256,
            unit_count=len(units),
            unit_root_sha256=unit_root_sha256,
            units=units,
        )

    def to_row(self) -> dict[str, object]:
        units_json = _canonical_json_bytes(
            [unit.to_row() for unit in self.units],
            maximum_bytes=_MAX_INVENTORY_JSON_BYTES,
        ).decode("utf-8")
        return {
            "schema_version": self.schema_version,
            "inventory_sha256": self.inventory_sha256,
            "raw_authority_bundle_sha256": self.raw_authority_bundle_sha256,
            "unit_count": self.unit_count,
            "unit_root_sha256": self.unit_root_sha256,
            "units_json": units_json,
        }

    @classmethod
    def from_row(cls, value: object) -> Self:
        row = _strict_row(
            value,
            expected_fields=_INVENTORY_ROW_FIELDS,
            label="expected-unit inventory row",
        )
        _exact_schema_version(row["schema_version"], label="expected-unit inventory row")
        units = _decode_units_json(row["units_json"])
        try:
            return cls(
                inventory_sha256=cast("str", row["inventory_sha256"]),
                raw_authority_bundle_sha256=cast("str", row["raw_authority_bundle_sha256"]),
                unit_count=cast("int", row["unit_count"]),
                unit_root_sha256=cast("str", row["unit_root_sha256"]),
                units=units,
            )
        except PublicValueTypesError:
            raise
        except (TypeError, ValueError) as exc:
            raise PublicValueTypesError(
                "expected-unit inventory row failed exact semantic reconstruction"
            ) from exc

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(
            self.to_row(),
            maximum_bytes=(_MAX_INVENTORY_JSON_BYTES * 2) + 4_096,
        )


@dataclass(frozen=True, slots=True)
class ValueRepresentationAssignmentV1:
    """One value-free binding from an expected unit to one representation."""

    assignment_sha256: str
    raw_authority_bundle_sha256: str
    unit_sha256: str
    unit_ordinal: int
    source_input_kind: PublicValueSourceInputKindV1
    representation_kind: PublicValueRepresentationKindV1

    schema_version: ClassVar[int] = PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION
    kind: ClassVar[str] = _VALUE_REPRESENTATION_ASSIGNMENT_KIND

    def __post_init__(self) -> None:
        _exact_sha256(self.assignment_sha256, label="value-representation assignment")
        _exact_sha256(
            self.raw_authority_bundle_sha256,
            label="value-representation raw-authority bundle",
        )
        _exact_sha256(self.unit_sha256, label="value-representation assigned unit")
        _exact_ordinal(self.unit_ordinal, label="value-representation unit ordinal")
        if (
            type(self.source_input_kind) is not str
            or self.source_input_kind not in _SOURCE_INPUT_KINDS
        ):
            _fail("source-input kind is outside the closed V1 domain")
        if (
            type(self.representation_kind) is not str
            or self.representation_kind not in _REPRESENTATION_KINDS
        ):
            _fail("representation kind is outside the closed V1 domain")
        expected = _canonical_sha256(
            _assignment_identity_payload(
                raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
                unit_sha256=self.unit_sha256,
                unit_ordinal=self.unit_ordinal,
                source_input_kind=self.source_input_kind,
                representation_kind=self.representation_kind,
            )
        )
        if self.assignment_sha256 != expected:
            _fail("value-representation digest differs from its exact binding")

    @classmethod
    def build(
        cls,
        *,
        expected_unit: ExpectedValueUnitV1,
        source_input_kind: PublicValueSourceInputKindV1,
        representation_kind: PublicValueRepresentationKindV1,
    ) -> Self:
        if type(expected_unit) is not ExpectedValueUnitV1:
            _fail("value-representation assignment requires an exact expected-unit DTO")
        assignment = cls(
            assignment_sha256=_canonical_sha256(
                _assignment_identity_payload(
                    raw_authority_bundle_sha256=expected_unit.raw_authority_bundle_sha256,
                    unit_sha256=expected_unit.unit_sha256,
                    unit_ordinal=expected_unit.unit_ordinal,
                    source_input_kind=source_input_kind,
                    representation_kind=representation_kind,
                )
            ),
            raw_authority_bundle_sha256=expected_unit.raw_authority_bundle_sha256,
            unit_sha256=expected_unit.unit_sha256,
            unit_ordinal=expected_unit.unit_ordinal,
            source_input_kind=source_input_kind,
            representation_kind=representation_kind,
        )
        return assignment.validate_for_unit(expected_unit)

    def validate_for_unit(self, expected_unit: ExpectedValueUnitV1) -> Self:
        """Bind this row to its exact unit and enforce response/result shape."""

        if type(expected_unit) is not ExpectedValueUnitV1:
            _fail("value-representation validation requires an exact expected-unit DTO")
        if (
            self.raw_authority_bundle_sha256 != expected_unit.raw_authority_bundle_sha256
            or self.unit_sha256 != expected_unit.unit_sha256
            or self.unit_ordinal != expected_unit.unit_ordinal
        ):
            _fail("value-representation assignment references a foreign expected unit")
        if expected_unit.unit_kind == "result_occurrence":
            if self.representation_kind not in _RESULT_REPRESENTATION_KINDS:
                _fail("result-occurrence unit uses a response-level representation")
        elif expected_unit.unit_kind == "response_residual":
            if self.representation_kind != "response_lossless_records_v1":
                _fail("response-residual unit lacks its sole compatible representation")
        elif self.representation_kind != "response_fixed_zero_v1":
            _fail("fixed-zero unit lacks its sole compatible representation")
        return self

    def to_row(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "assignment_sha256": self.assignment_sha256,
            "raw_authority_bundle_sha256": self.raw_authority_bundle_sha256,
            "unit_sha256": self.unit_sha256,
            "unit_ordinal": self.unit_ordinal,
            "source_input_kind": self.source_input_kind,
            "representation_kind": self.representation_kind,
        }

    @classmethod
    def from_row(cls, value: object) -> Self:
        row = _strict_row(
            value,
            expected_fields=_ASSIGNMENT_ROW_FIELDS,
            label="value-representation assignment row",
        )
        _exact_schema_version(row["schema_version"], label="value-representation assignment row")
        try:
            return cls(
                assignment_sha256=cast("str", row["assignment_sha256"]),
                raw_authority_bundle_sha256=cast("str", row["raw_authority_bundle_sha256"]),
                unit_sha256=cast("str", row["unit_sha256"]),
                unit_ordinal=cast("int", row["unit_ordinal"]),
                source_input_kind=cast("PublicValueSourceInputKindV1", row["source_input_kind"]),
                representation_kind=cast(
                    "PublicValueRepresentationKindV1", row["representation_kind"]
                ),
            )
        except PublicValueTypesError:
            raise
        except (TypeError, ValueError) as exc:
            raise PublicValueTypesError(
                "value-representation row failed exact semantic reconstruction"
            ) from exc

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_row(), maximum_bytes=4_096)
