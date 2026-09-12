"""Value-free exhaustive ownership authority for W2 lossless public records.

The kernel consumes already-normalized identities.  It deliberately knows
nothing about stats/live parsers, Raw Authority builders, staging schemas, or
provider values.  Its only job is to prove that every normalized source-record
identity belongs to exactly one selected result occurrence or response
residual, including explicit zero-sized occurrence and response partitions.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, fields
from typing import Any, ClassVar, Final, Literal, Never, Self, cast

from nbadb.contracts.public_value_types import (
    MAX_PUBLIC_VALUE_EXPECTED_UNITS,
    PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION,
    ExpectedValueUnitInventoryV1,
    ExpectedValueUnitKindV1,
    ExpectedValueUnitV1,
    PublicValueSourceInputKindV1,
    PublicValueTypesError,
    ValueRepresentationAssignmentV1,
)

__all__ = [
    "LOSSLESS_OWNERSHIP_SCHEMA_VERSION",
    "MAX_LOSSLESS_OWNERSHIP_BINDINGS",
    "MAX_LOSSLESS_OWNERSHIP_OBSERVATIONS",
    "MAX_LOSSLESS_OWNERSHIP_PARTITIONS",
    "LosslessObservationOwnershipV1",
    "LosslessOwnershipAuthorityV1",
    "LosslessOwnershipBindingKindV1",
    "LosslessOwnershipBindingV1",
    "LosslessOwnershipError",
    "LosslessOwnershipPartitionV1",
    "LosslessOwnershipReceiptV1",
    "build_lossless_ownership_authority",
]


LOSSLESS_OWNERSHIP_SCHEMA_VERSION: Final = PUBLIC_VALUE_AUTHORITY_SCHEMA_VERSION
MAX_LOSSLESS_OWNERSHIP_OBSERVATIONS: Final = MAX_PUBLIC_VALUE_EXPECTED_UNITS
MAX_LOSSLESS_OWNERSHIP_PARTITIONS: Final = MAX_PUBLIC_VALUE_EXPECTED_UNITS * 2
MAX_LOSSLESS_OWNERSHIP_BINDINGS: Final = 14_000_000

LosslessOwnershipBindingKindV1 = Literal["result_occurrence", "response_residual"]

_MAX_ORDINAL: Final = (1 << 63) - 1
_MAX_CANONICAL_BYTES: Final = 64 * 1024
_MAX_CANONICAL_NODES: Final = 512
_MAX_CANONICAL_DEPTH: Final = 8
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")

_BINDING_KIND: Final = "nbadb_lossless_ownership_binding_v1"
_PARTITION_KIND: Final = "nbadb_lossless_ownership_partition_v1"
_OBSERVATION_KIND: Final = "nbadb_lossless_observation_ownership_v1"
_RECEIPT_KIND: Final = "nbadb_lossless_ownership_receipt_v1"

_PARTITION_BINDING_ROOT_KIND: Final = "nbadb_lossless_partition_bindings_v1"
_PARTITION_RECORD_ROOT_KIND: Final = "nbadb_lossless_partition_source_records_v1"
_OBSERVATION_PARTITION_ROOT_KIND: Final = "nbadb_lossless_observation_partitions_v1"
_OBSERVATION_BINDING_ROOT_KIND: Final = "nbadb_lossless_observation_bindings_v1"
_OBSERVATION_RECORD_ROOT_KIND: Final = "nbadb_lossless_observation_source_records_v1"
_ASSIGNMENT_ROOT_KIND: Final = "nbadb_lossless_representation_assignments_v1"
_AUTHORITY_OBSERVATION_ROOT_KIND: Final = "nbadb_lossless_owned_observations_v1"
_AUTHORITY_PARTITION_ROOT_KIND: Final = "nbadb_lossless_ownership_partitions_v1"
_AUTHORITY_BINDING_ROOT_KIND: Final = "nbadb_lossless_ownership_bindings_v1"
_AUTHORITY_RECORD_ROOT_KIND: Final = "nbadb_lossless_owned_source_records_v1"
_FIXED_ZERO_LANDING_ROOT_KIND: Final = "nbadb_lossless_fixed_zero_landings_v1"

_SOURCE_INPUT_KINDS: Final = frozenset(
    {
        "parser_input_body",
        "declared_bodyless_packet",
    }
)
_PARTITION_KINDS: Final = frozenset(
    {
        "result_occurrence",
        "response_residual",
        "response_fixed_zero",
    }
)
_BINDING_KINDS: Final = frozenset(
    {
        "result_occurrence",
        "response_residual",
    }
)


class LosslessOwnershipError(ValueError):
    """The normalized ownership authority is unsafe or internally inconsistent."""


def _fail(message: str) -> Never:
    raise LosslessOwnershipError(message)


def _exact_sha256(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{field_name} must be one lowercase full SHA-256")
    return value


def _optional_sha256(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _exact_sha256(value, field_name=field_name)


def _exact_nonnegative(value: object, *, field_name: str, maximum: int) -> int:
    if type(value) is not int or value < 0 or value > maximum:
        _fail(f"{field_name} must be one bounded nonnegative exact integer")
    return value


def _optional_nonnegative(
    value: object,
    *,
    field_name: str,
    maximum: int,
) -> int | None:
    if value is None:
        return None
    return _exact_nonnegative(value, field_name=field_name, maximum=maximum)


def _preflight_builtin_graph(value: object) -> None:
    stack: list[tuple[object, int]] = [(value, 0)]
    nodes = 0
    cumulative_string_bytes = 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > _MAX_CANONICAL_NODES or depth > _MAX_CANONICAL_DEPTH:
            _fail("lossless-ownership canonical input exceeds its structural bound")
        if item is None or type(item) is bool:
            continue
        if type(item) is int:
            if item < -_MAX_ORDINAL or item > _MAX_ORDINAL:
                _fail("lossless-ownership canonical input contains an unbounded integer")
            continue
        if type(item) is str:
            try:
                cumulative_string_bytes += len(item.encode("utf-8", errors="strict"))
            except UnicodeEncodeError:
                _fail("lossless-ownership canonical input contains invalid Unicode")
            if cumulative_string_bytes > _MAX_CANONICAL_BYTES:
                _fail("lossless-ownership canonical input exceeds its string-byte bound")
            continue
        if type(item) in {tuple, list}:
            sequence = cast("tuple[object, ...] | list[object]", item)
            stack.extend((child, depth + 1) for child in reversed(sequence))
            continue
        if type(item) is dict:
            mapping = cast("dict[object, object]", item)
            for key, child in reversed(tuple(mapping.items())):
                if type(key) is not str:
                    _fail("lossless-ownership canonical input contains a non-string key")
                try:
                    cumulative_string_bytes += len(key.encode("utf-8", errors="strict"))
                except UnicodeEncodeError:
                    _fail("lossless-ownership canonical input contains invalid Unicode")
                if cumulative_string_bytes > _MAX_CANONICAL_BYTES:
                    _fail("lossless-ownership canonical input exceeds its string-byte bound")
                stack.append((child, depth + 1))
            continue
        _fail("lossless-ownership canonical input contains a foreign exact type")


def _canonical_json_bytes(value: object) -> bytes:
    _preflight_builtin_graph(value)
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8", errors="strict")
    except (RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("lossless-ownership identity is not canonical JSON")
    if not encoded or len(encoded) > _MAX_CANONICAL_BYTES:
        _fail("lossless-ownership canonical JSON exceeds its byte bound")
    return encoded


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _ordered_root(
    *,
    kind: str,
    item_sha256s: tuple[str, ...],
    maximum: int,
) -> str:
    if type(item_sha256s) is not tuple or len(item_sha256s) > maximum:
        _fail("lossless-ownership ordered root has a foreign or over-bound inventory")
    digest = hashlib.sha256()
    digest.update(b'{"count":')
    digest.update(str(len(item_sha256s)).encode("ascii"))
    digest.update(b',"items":[')
    for ordinal, item_sha256 in enumerate(item_sha256s):
        _exact_sha256(item_sha256, field_name="ordered-root item")
        if ordinal:
            digest.update(b",")
        digest.update(_canonical_json_bytes(item_sha256))
    digest.update(b'],"kind":')
    digest.update(_canonical_json_bytes(kind))
    digest.update(b',"schema_version":1}')
    return digest.hexdigest()


def _strict_dataclass_row(
    value: object,
    *,
    cls: type[object],
    label: str,
) -> dict[str, object]:
    expected_fields = ("schema_version", *(item.name for item in fields(cls)))
    if type(value) is not dict:
        _fail(f"{label} does not have its exact ordered row shape")
    object_row = cast("dict[object, object]", value)
    if any(type(key) is not str for key in object_row) or tuple(object_row) != expected_fields:
        _fail(f"{label} does not have its exact ordered row shape")
    row = cast("dict[str, object]", value)
    if (
        type(row["schema_version"]) is not int
        or row["schema_version"] != LOSSLESS_OWNERSHIP_SCHEMA_VERSION
    ):
        _fail(f"{label} schema version is invalid")
    return row


def _to_row(value: object) -> dict[str, object]:
    dataclass_value = cast("Any", value)
    return {
        "schema_version": LOSSLESS_OWNERSHIP_SCHEMA_VERSION,
        **{item.name: getattr(dataclass_value, item.name) for item in fields(dataclass_value)},
    }


def _identity_payload(value: object, *, kind: str, digest_field: str) -> dict[str, object]:
    dataclass_value = cast("Any", value)
    return {
        "schema_version": LOSSLESS_OWNERSHIP_SCHEMA_VERSION,
        "kind": kind,
        **{
            item.name: getattr(dataclass_value, item.name)
            for item in fields(dataclass_value)
            if item.name != digest_field
        },
    }


@dataclass(frozen=True, slots=True)
class LosslessOwnershipBindingV1:
    """One exact normalized source-record identity assigned to one partition."""

    binding_sha256: str
    raw_authority_bundle_sha256: str
    observation_record_sha256: str
    observation_sha256: str
    observation_ordinal: int
    binding_ordinal: int
    observation_record_ordinal: int
    partition_ordinal: int
    source_record_sha256: str
    unit_sha256: str
    unit_ordinal: int
    assignment_sha256: str
    ownership_kind: LosslessOwnershipBindingKindV1
    occurrence_sha256: str | None
    occurrence_ordinal: int | None

    schema_version: ClassVar[int] = LOSSLESS_OWNERSHIP_SCHEMA_VERSION
    kind: ClassVar[str] = _BINDING_KIND

    def __post_init__(self) -> None:
        for field_name in (
            "binding_sha256",
            "raw_authority_bundle_sha256",
            "observation_record_sha256",
            "observation_sha256",
            "source_record_sha256",
            "unit_sha256",
            "assignment_sha256",
        ):
            _exact_sha256(getattr(self, field_name), field_name=field_name)
        for field_name, maximum in (
            ("observation_ordinal", MAX_LOSSLESS_OWNERSHIP_OBSERVATIONS - 1),
            ("binding_ordinal", MAX_LOSSLESS_OWNERSHIP_BINDINGS - 1),
            ("observation_record_ordinal", MAX_LOSSLESS_OWNERSHIP_BINDINGS - 1),
            ("partition_ordinal", MAX_LOSSLESS_OWNERSHIP_PARTITIONS - 1),
            ("unit_ordinal", MAX_PUBLIC_VALUE_EXPECTED_UNITS - 1),
        ):
            _exact_nonnegative(getattr(self, field_name), field_name=field_name, maximum=maximum)
        if type(self.ownership_kind) is not str or self.ownership_kind not in _BINDING_KINDS:
            _fail("lossless-ownership binding kind is outside its closed domain")
        if self.ownership_kind == "result_occurrence":
            _exact_sha256(self.occurrence_sha256, field_name="binding occurrence")
            _exact_nonnegative(
                self.occurrence_ordinal,
                field_name="binding occurrence ordinal",
                maximum=MAX_PUBLIC_VALUE_EXPECTED_UNITS - 1,
            )
        elif self.occurrence_sha256 is not None or self.occurrence_ordinal is not None:
            _fail("response-residual binding fabricates occurrence ownership")
        if self.binding_sha256 != _canonical_sha256(self.identity_payload()):
            _fail("lossless-ownership binding digest differs from its exact identity")

    @classmethod
    def build(
        cls,
        *,
        raw_authority_bundle_sha256: str,
        observation_record_sha256: str,
        observation_sha256: str,
        observation_ordinal: int,
        binding_ordinal: int,
        observation_record_ordinal: int,
        partition_ordinal: int,
        source_record_sha256: str,
        expected_unit: ExpectedValueUnitV1,
        assignment: ValueRepresentationAssignmentV1,
    ) -> Self:
        if type(expected_unit) is not ExpectedValueUnitV1:
            _fail("lossless-ownership binding requires an exact expected-unit DTO")
        if type(assignment) is not ValueRepresentationAssignmentV1:
            _fail("lossless-ownership binding requires an exact assignment DTO")
        try:
            assignment.validate_for_unit(expected_unit)
        except PublicValueTypesError as exc:
            raise LosslessOwnershipError(
                "lossless-ownership binding assignment is incompatible with its unit"
            ) from exc
        if expected_unit.unit_kind == "response_fixed_zero":
            _fail("fixed-zero expected units cannot own source records")
        if expected_unit.raw_authority_bundle_sha256 != raw_authority_bundle_sha256:
            _fail("lossless-ownership binding expected unit belongs to a foreign bundle")
        if (
            expected_unit.observation_sha256 != observation_sha256
            or expected_unit.observation_ordinal != observation_ordinal
        ):
            _fail("lossless-ownership binding expected unit belongs to a foreign observation")
        values: dict[str, object] = {
            "raw_authority_bundle_sha256": raw_authority_bundle_sha256,
            "observation_record_sha256": observation_record_sha256,
            "observation_sha256": observation_sha256,
            "observation_ordinal": observation_ordinal,
            "binding_ordinal": binding_ordinal,
            "observation_record_ordinal": observation_record_ordinal,
            "partition_ordinal": partition_ordinal,
            "source_record_sha256": source_record_sha256,
            "unit_sha256": expected_unit.unit_sha256,
            "unit_ordinal": expected_unit.unit_ordinal,
            "assignment_sha256": assignment.assignment_sha256,
            "ownership_kind": expected_unit.unit_kind,
            "occurrence_sha256": expected_unit.occurrence_sha256,
            "occurrence_ordinal": expected_unit.occurrence_ordinal,
        }
        payload = {
            "schema_version": cls.schema_version,
            "kind": cls.kind,
            **values,
        }
        return cls(binding_sha256=_canonical_sha256(payload), **cast("Any", values))

    def identity_payload(self) -> dict[str, object]:
        return _identity_payload(self, kind=self.kind, digest_field="binding_sha256")

    def to_row(self) -> dict[str, object]:
        return _to_row(self)

    @classmethod
    def from_row(cls, value: object) -> Self:
        row = _strict_dataclass_row(value, cls=cls, label="lossless-ownership binding row")
        try:
            return cls(**cast("Any", {item.name: row[item.name] for item in fields(cls)}))
        except LosslessOwnershipError:
            raise
        except (TypeError, ValueError, RecursionError):
            _fail("lossless-ownership binding row failed semantic reconstruction")

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_row())


@dataclass(frozen=True, slots=True)
class LosslessOwnershipPartitionV1:
    """One explicit occurrence, residual, or fixed-zero ownership partition."""

    partition_sha256: str
    raw_authority_bundle_sha256: str
    observation_record_sha256: str
    observation_sha256: str
    observation_ordinal: int
    partition_ordinal: int
    observation_partition_ordinal: int
    partition_kind: ExpectedValueUnitKindV1
    occurrence_sha256: str | None
    occurrence_ordinal: int | None
    unit_sha256: str | None
    unit_ordinal: int | None
    assignment_sha256: str | None
    record_count: int
    record_root_sha256: str
    binding_root_sha256: str
    fixed_zero_landing_sha256: str | None

    schema_version: ClassVar[int] = LOSSLESS_OWNERSHIP_SCHEMA_VERSION
    kind: ClassVar[str] = _PARTITION_KIND

    def __post_init__(self) -> None:
        for field_name in (
            "partition_sha256",
            "raw_authority_bundle_sha256",
            "observation_record_sha256",
            "observation_sha256",
            "record_root_sha256",
            "binding_root_sha256",
        ):
            _exact_sha256(getattr(self, field_name), field_name=field_name)
        for field_name, maximum in (
            ("observation_ordinal", MAX_LOSSLESS_OWNERSHIP_OBSERVATIONS - 1),
            ("partition_ordinal", MAX_LOSSLESS_OWNERSHIP_PARTITIONS - 1),
            ("observation_partition_ordinal", MAX_LOSSLESS_OWNERSHIP_PARTITIONS - 1),
            ("record_count", MAX_LOSSLESS_OWNERSHIP_BINDINGS),
        ):
            _exact_nonnegative(getattr(self, field_name), field_name=field_name, maximum=maximum)
        if type(self.partition_kind) is not str or self.partition_kind not in _PARTITION_KINDS:
            _fail("lossless-ownership partition kind is outside its closed domain")
        _optional_sha256(self.occurrence_sha256, field_name="partition occurrence")
        _optional_nonnegative(
            self.occurrence_ordinal,
            field_name="partition occurrence ordinal",
            maximum=MAX_PUBLIC_VALUE_EXPECTED_UNITS - 1,
        )
        _optional_sha256(self.unit_sha256, field_name="partition expected unit")
        _optional_nonnegative(
            self.unit_ordinal,
            field_name="partition unit ordinal",
            maximum=MAX_PUBLIC_VALUE_EXPECTED_UNITS - 1,
        )
        _optional_sha256(self.assignment_sha256, field_name="partition assignment")
        _optional_sha256(self.fixed_zero_landing_sha256, field_name="fixed-zero landing")
        unit_fields_present = (
            self.unit_sha256 is not None
            and self.unit_ordinal is not None
            and self.assignment_sha256 is not None
        )
        unit_fields_absent = (
            self.unit_sha256 is None
            and self.unit_ordinal is None
            and self.assignment_sha256 is None
        )
        if not unit_fields_present and not unit_fields_absent:
            _fail("lossless-ownership partition has a partial unit binding")
        if self.partition_kind == "result_occurrence":
            if (
                self.occurrence_sha256 is None
                or self.occurrence_ordinal is None
                or not unit_fields_present
                or self.fixed_zero_landing_sha256 is not None
            ):
                _fail("result-occurrence partition has an invalid ownership shape")
        elif self.partition_kind == "response_residual":
            if (
                self.occurrence_sha256 is not None
                or self.occurrence_ordinal is not None
                or self.fixed_zero_landing_sha256 is not None
                or (self.record_count > 0 and not unit_fields_present)
                or (self.record_count == 0 and not unit_fields_absent)
            ):
                _fail("response-residual partition has an invalid zero/unit shape")
        elif (
            self.occurrence_sha256 is not None
            or self.occurrence_ordinal is not None
            or not unit_fields_present
            or self.record_count != 0
            or self.fixed_zero_landing_sha256 is None
        ):
            _fail("fixed-zero response partition has an invalid ownership shape")
        empty_record_root = _ordered_root(
            kind=_PARTITION_RECORD_ROOT_KIND,
            item_sha256s=(),
            maximum=MAX_LOSSLESS_OWNERSHIP_BINDINGS,
        )
        empty_binding_root = _ordered_root(
            kind=_PARTITION_BINDING_ROOT_KIND,
            item_sha256s=(),
            maximum=MAX_LOSSLESS_OWNERSHIP_BINDINGS,
        )
        if (self.record_count == 0) != (self.record_root_sha256 == empty_record_root) or (
            self.record_count == 0
        ) != (self.binding_root_sha256 == empty_binding_root):
            _fail("lossless-ownership partition zero proof is inconsistent")
        if self.partition_sha256 != _canonical_sha256(self.identity_payload()):
            _fail("lossless-ownership partition digest differs from its exact identity")

    @classmethod
    def build(
        cls,
        *,
        raw_authority_bundle_sha256: str,
        observation_record_sha256: str,
        observation_sha256: str,
        observation_ordinal: int,
        partition_ordinal: int,
        observation_partition_ordinal: int,
        partition_kind: ExpectedValueUnitKindV1,
        bindings: tuple[LosslessOwnershipBindingV1, ...],
        expected_unit: ExpectedValueUnitV1 | None = None,
        assignment: ValueRepresentationAssignmentV1 | None = None,
        fixed_zero_landing_sha256: str | None = None,
    ) -> Self:
        if type(bindings) is not tuple or len(bindings) > MAX_LOSSLESS_OWNERSHIP_BINDINGS:
            _fail("lossless-ownership partition bindings are foreign or over-bound")
        if any(type(binding) is not LosslessOwnershipBindingV1 for binding in bindings):
            _fail("lossless-ownership partition contains a foreign binding DTO")
        if (expected_unit is None) != (assignment is None):
            _fail("lossless-ownership partition has a partial expected-unit assignment")
        if expected_unit is not None:
            if type(expected_unit) is not ExpectedValueUnitV1:
                _fail("lossless-ownership partition has a foreign expected-unit DTO")
            if type(assignment) is not ValueRepresentationAssignmentV1:
                _fail("lossless-ownership partition has a foreign assignment DTO")
            try:
                assignment.validate_for_unit(expected_unit)
            except PublicValueTypesError as exc:
                raise LosslessOwnershipError(
                    "lossless-ownership partition assignment is incompatible with its unit"
                ) from exc
            if expected_unit.raw_authority_bundle_sha256 != raw_authority_bundle_sha256:
                _fail("lossless-ownership partition expected unit belongs to a foreign bundle")
            if (
                expected_unit.observation_sha256 != observation_sha256
                or expected_unit.observation_ordinal != observation_ordinal
                or expected_unit.unit_kind != partition_kind
            ):
                _fail("lossless-ownership partition expected unit belongs to a foreign owner")
        occurrence_sha256 = None if expected_unit is None else expected_unit.occurrence_sha256
        occurrence_ordinal = None if expected_unit is None else expected_unit.occurrence_ordinal
        for binding in bindings:
            if (
                binding.raw_authority_bundle_sha256 != raw_authority_bundle_sha256
                or binding.observation_record_sha256 != observation_record_sha256
                or binding.observation_sha256 != observation_sha256
                or binding.observation_ordinal != observation_ordinal
                or binding.partition_ordinal != partition_ordinal
                or binding.ownership_kind != partition_kind
                or binding.occurrence_sha256 != occurrence_sha256
                or binding.occurrence_ordinal != occurrence_ordinal
                or expected_unit is None
                or assignment is None
                or binding.unit_sha256 != expected_unit.unit_sha256
                or binding.unit_ordinal != expected_unit.unit_ordinal
                or binding.assignment_sha256 != assignment.assignment_sha256
            ):
                _fail("lossless-ownership partition contains a cross-owner binding")
        record_root_sha256 = _ordered_root(
            kind=_PARTITION_RECORD_ROOT_KIND,
            item_sha256s=tuple(binding.source_record_sha256 for binding in bindings),
            maximum=MAX_LOSSLESS_OWNERSHIP_BINDINGS,
        )
        binding_root_sha256 = _ordered_root(
            kind=_PARTITION_BINDING_ROOT_KIND,
            item_sha256s=tuple(binding.binding_sha256 for binding in bindings),
            maximum=MAX_LOSSLESS_OWNERSHIP_BINDINGS,
        )
        values: dict[str, object] = {
            "raw_authority_bundle_sha256": raw_authority_bundle_sha256,
            "observation_record_sha256": observation_record_sha256,
            "observation_sha256": observation_sha256,
            "observation_ordinal": observation_ordinal,
            "partition_ordinal": partition_ordinal,
            "observation_partition_ordinal": observation_partition_ordinal,
            "partition_kind": partition_kind,
            "occurrence_sha256": occurrence_sha256,
            "occurrence_ordinal": occurrence_ordinal,
            "unit_sha256": None if expected_unit is None else expected_unit.unit_sha256,
            "unit_ordinal": None if expected_unit is None else expected_unit.unit_ordinal,
            "assignment_sha256": None if assignment is None else assignment.assignment_sha256,
            "record_count": len(bindings),
            "record_root_sha256": record_root_sha256,
            "binding_root_sha256": binding_root_sha256,
            "fixed_zero_landing_sha256": fixed_zero_landing_sha256,
        }
        payload = {
            "schema_version": cls.schema_version,
            "kind": cls.kind,
            **values,
        }
        return cls(partition_sha256=_canonical_sha256(payload), **cast("Any", values))

    def identity_payload(self) -> dict[str, object]:
        return _identity_payload(self, kind=self.kind, digest_field="partition_sha256")

    def to_row(self) -> dict[str, object]:
        return _to_row(self)

    @classmethod
    def from_row(cls, value: object) -> Self:
        row = _strict_dataclass_row(value, cls=cls, label="lossless-ownership partition row")
        try:
            return cls(**cast("Any", {item.name: row[item.name] for item in fields(cls)}))
        except LosslessOwnershipError:
            raise
        except (TypeError, ValueError, RecursionError):
            _fail("lossless-ownership partition row failed semantic reconstruction")

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_row())


def _validate_partition_binding_roots(
    partition: LosslessOwnershipPartitionV1,
    bindings: tuple[LosslessOwnershipBindingV1, ...],
) -> None:
    expected_record_root = _ordered_root(
        kind=_PARTITION_RECORD_ROOT_KIND,
        item_sha256s=tuple(binding.source_record_sha256 for binding in bindings),
        maximum=MAX_LOSSLESS_OWNERSHIP_BINDINGS,
    )
    expected_binding_root = _ordered_root(
        kind=_PARTITION_BINDING_ROOT_KIND,
        item_sha256s=tuple(binding.binding_sha256 for binding in bindings),
        maximum=MAX_LOSSLESS_OWNERSHIP_BINDINGS,
    )
    if (
        partition.record_count != len(bindings)
        or partition.record_root_sha256 != expected_record_root
        or partition.binding_root_sha256 != expected_binding_root
    ):
        _fail("lossless-ownership partition roots differ from its exact bindings")


@dataclass(frozen=True, slots=True)
class LosslessObservationOwnershipV1:
    """One selected observation's exhaustive ordered ownership partition."""

    observation_ownership_sha256: str
    raw_authority_bundle_sha256: str
    observation_record_sha256: str
    observation_sha256: str
    observation_ordinal: int
    source_input_kind: PublicValueSourceInputKindV1
    first_partition_ordinal: int
    partition_count: int
    partition_root_sha256: str
    result_occurrence_partition_count: int
    zero_result_occurrence_partition_count: int
    result_occurrence_record_count: int
    response_partition_kind: ExpectedValueUnitKindV1
    response_record_count: int
    fixed_zero_landing_sha256: str | None
    record_count: int
    record_root_sha256: str
    binding_count: int
    binding_root_sha256: str

    schema_version: ClassVar[int] = LOSSLESS_OWNERSHIP_SCHEMA_VERSION
    kind: ClassVar[str] = _OBSERVATION_KIND

    def __post_init__(self) -> None:
        for field_name in (
            "observation_ownership_sha256",
            "raw_authority_bundle_sha256",
            "observation_record_sha256",
            "observation_sha256",
            "partition_root_sha256",
            "record_root_sha256",
            "binding_root_sha256",
        ):
            _exact_sha256(getattr(self, field_name), field_name=field_name)
        if (
            type(self.source_input_kind) is not str
            or self.source_input_kind not in _SOURCE_INPUT_KINDS
        ):
            _fail("lossless observation has a foreign source-input kind")
        if type(self.response_partition_kind) is not str or self.response_partition_kind not in {
            "response_residual",
            "response_fixed_zero",
        }:
            _fail("lossless observation has a foreign response partition kind")
        for field_name, maximum in (
            ("observation_ordinal", MAX_LOSSLESS_OWNERSHIP_OBSERVATIONS - 1),
            ("first_partition_ordinal", MAX_LOSSLESS_OWNERSHIP_PARTITIONS - 1),
            ("partition_count", MAX_LOSSLESS_OWNERSHIP_PARTITIONS),
            ("result_occurrence_partition_count", MAX_PUBLIC_VALUE_EXPECTED_UNITS),
            ("zero_result_occurrence_partition_count", MAX_PUBLIC_VALUE_EXPECTED_UNITS),
            ("result_occurrence_record_count", MAX_LOSSLESS_OWNERSHIP_BINDINGS),
            ("response_record_count", MAX_LOSSLESS_OWNERSHIP_BINDINGS),
            ("record_count", MAX_LOSSLESS_OWNERSHIP_BINDINGS),
            ("binding_count", MAX_LOSSLESS_OWNERSHIP_BINDINGS),
        ):
            _exact_nonnegative(getattr(self, field_name), field_name=field_name, maximum=maximum)
        _optional_sha256(self.fixed_zero_landing_sha256, field_name="fixed-zero landing")
        if (
            self.partition_count != self.result_occurrence_partition_count + 1
            or self.zero_result_occurrence_partition_count > self.result_occurrence_partition_count
            or self.record_count != self.result_occurrence_record_count + self.response_record_count
            or self.binding_count != self.record_count
        ):
            _fail("lossless observation aggregate denominators are inconsistent")
        if self.result_occurrence_record_count < (
            self.result_occurrence_partition_count - self.zero_result_occurrence_partition_count
        ):
            _fail("lossless observation has a nonempty occurrence without a source record")
        if self.response_partition_kind == "response_fixed_zero":
            if (
                self.result_occurrence_partition_count != 0
                or self.zero_result_occurrence_partition_count != 0
                or self.result_occurrence_record_count != 0
                or self.response_record_count != 0
                or self.record_count != 0
                or self.fixed_zero_landing_sha256 is None
            ):
                _fail("fixed-zero observation contradicts its exact empty algebra")
        elif self.fixed_zero_landing_sha256 is not None:
            _fail("response-residual observation fabricates a fixed-zero landing")
        elif self.result_occurrence_partition_count == 0 and self.response_record_count == 0:
            _fail("empty observation lacks its mandatory fixed-zero response partition")
        if self.observation_ownership_sha256 != _canonical_sha256(self.identity_payload()):
            _fail("lossless observation digest differs from its exact identity")

    @classmethod
    def build(
        cls,
        *,
        raw_authority_bundle_sha256: str,
        observation_record_sha256: str,
        observation_sha256: str,
        observation_ordinal: int,
        source_input_kind: PublicValueSourceInputKindV1,
        partitions: tuple[LosslessOwnershipPartitionV1, ...],
        bindings: tuple[LosslessOwnershipBindingV1, ...],
    ) -> Self:
        if (
            type(partitions) is not tuple
            or not partitions
            or len(partitions) > MAX_LOSSLESS_OWNERSHIP_PARTITIONS
        ):
            _fail("lossless observation requires a bounded nonempty partition tuple")
        if any(type(partition) is not LosslessOwnershipPartitionV1 for partition in partitions):
            _fail("lossless observation contains a foreign partition DTO")
        if type(bindings) is not tuple or len(bindings) > MAX_LOSSLESS_OWNERSHIP_BINDINGS:
            _fail("lossless observation binding inventory is foreign or over-bound")
        if any(type(binding) is not LosslessOwnershipBindingV1 for binding in bindings):
            _fail("lossless observation contains a foreign binding DTO")
        first_partition_ordinal = partitions[0].partition_ordinal
        for ordinal, partition in enumerate(partitions):
            if (
                partition.raw_authority_bundle_sha256 != raw_authority_bundle_sha256
                or partition.observation_record_sha256 != observation_record_sha256
                or partition.observation_sha256 != observation_sha256
                or partition.observation_ordinal != observation_ordinal
                or partition.observation_partition_ordinal != ordinal
                or partition.partition_ordinal != first_partition_ordinal + ordinal
            ):
                _fail("lossless observation partition order or ownership is not exact")
        occurrence_partitions = partitions[:-1]
        response_partition = partitions[-1]
        for occurrence_ordinal, partition in enumerate(occurrence_partitions):
            if (
                partition.partition_kind != "result_occurrence"
                or partition.occurrence_ordinal != occurrence_ordinal
            ):
                _fail("lossless observation occurrence partitions are not contiguous")
        if response_partition.partition_kind not in {
            "response_residual",
            "response_fixed_zero",
        }:
            _fail("lossless observation does not end in exactly one response partition")
        for record_ordinal, binding in enumerate(bindings):
            if (
                binding.raw_authority_bundle_sha256 != raw_authority_bundle_sha256
                or binding.observation_record_sha256 != observation_record_sha256
                or binding.observation_sha256 != observation_sha256
                or binding.observation_ordinal != observation_ordinal
                or binding.observation_record_ordinal != record_ordinal
            ):
                _fail("lossless observation source-record order or ownership is not exact")
        partition_ordinals = {partition.partition_ordinal for partition in partitions}
        if any(binding.partition_ordinal not in partition_ordinals for binding in bindings):
            _fail("lossless observation contains an orphan binding")
        for partition in partitions:
            owned = tuple(
                binding
                for binding in bindings
                if binding.partition_ordinal == partition.partition_ordinal
            )
            _validate_partition_binding_roots(partition, owned)
        result_occurrence_record_count = sum(
            partition.record_count for partition in occurrence_partitions
        )
        partition_root_sha256 = _ordered_root(
            kind=_OBSERVATION_PARTITION_ROOT_KIND,
            item_sha256s=tuple(partition.partition_sha256 for partition in partitions),
            maximum=MAX_LOSSLESS_OWNERSHIP_PARTITIONS,
        )
        record_root_sha256 = _ordered_root(
            kind=_OBSERVATION_RECORD_ROOT_KIND,
            item_sha256s=tuple(binding.source_record_sha256 for binding in bindings),
            maximum=MAX_LOSSLESS_OWNERSHIP_BINDINGS,
        )
        binding_root_sha256 = _ordered_root(
            kind=_OBSERVATION_BINDING_ROOT_KIND,
            item_sha256s=tuple(binding.binding_sha256 for binding in bindings),
            maximum=MAX_LOSSLESS_OWNERSHIP_BINDINGS,
        )
        values: dict[str, object] = {
            "raw_authority_bundle_sha256": raw_authority_bundle_sha256,
            "observation_record_sha256": observation_record_sha256,
            "observation_sha256": observation_sha256,
            "observation_ordinal": observation_ordinal,
            "source_input_kind": source_input_kind,
            "first_partition_ordinal": first_partition_ordinal,
            "partition_count": len(partitions),
            "partition_root_sha256": partition_root_sha256,
            "result_occurrence_partition_count": len(occurrence_partitions),
            "zero_result_occurrence_partition_count": sum(
                partition.record_count == 0 for partition in occurrence_partitions
            ),
            "result_occurrence_record_count": result_occurrence_record_count,
            "response_partition_kind": response_partition.partition_kind,
            "response_record_count": response_partition.record_count,
            "fixed_zero_landing_sha256": response_partition.fixed_zero_landing_sha256,
            "record_count": len(bindings),
            "record_root_sha256": record_root_sha256,
            "binding_count": len(bindings),
            "binding_root_sha256": binding_root_sha256,
        }
        payload = {
            "schema_version": cls.schema_version,
            "kind": cls.kind,
            **values,
        }
        return cls(
            observation_ownership_sha256=_canonical_sha256(payload),
            **cast("Any", values),
        )

    def identity_payload(self) -> dict[str, object]:
        return _identity_payload(
            self,
            kind=self.kind,
            digest_field="observation_ownership_sha256",
        )

    def to_row(self) -> dict[str, object]:
        return _to_row(self)

    @classmethod
    def from_row(cls, value: object) -> Self:
        row = _strict_dataclass_row(
            value,
            cls=cls,
            label="lossless observation ownership row",
        )
        try:
            return cls(**cast("Any", {item.name: row[item.name] for item in fields(cls)}))
        except LosslessOwnershipError:
            raise
        except (TypeError, ValueError, RecursionError):
            _fail("lossless observation ownership row failed semantic reconstruction")

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_row())


@dataclass(frozen=True, slots=True)
class LosslessOwnershipReceiptV1:
    """Value-free aggregate root over one exhaustive normalized ownership authority."""

    receipt_sha256: str
    raw_authority_bundle_sha256: str
    expected_unit_count: int
    expected_unit_inventory_sha256: str
    expected_unit_root_sha256: str
    representation_assignment_count: int
    representation_assignment_root_sha256: str
    observation_count: int
    observation_root_sha256: str
    partition_count: int
    partition_root_sha256: str
    result_occurrence_partition_count: int
    zero_result_occurrence_partition_count: int
    result_occurrence_record_count: int
    response_residual_partition_count: int
    positive_response_residual_partition_count: int
    zero_response_residual_partition_count: int
    response_residual_record_count: int
    response_fixed_zero_partition_count: int
    fixed_zero_landing_root_sha256: str
    binding_count: int
    binding_root_sha256: str
    source_record_count: int
    source_record_root_sha256: str

    schema_version: ClassVar[int] = LOSSLESS_OWNERSHIP_SCHEMA_VERSION
    kind: ClassVar[str] = _RECEIPT_KIND

    def __post_init__(self) -> None:
        for field_name in (
            "receipt_sha256",
            "raw_authority_bundle_sha256",
            "expected_unit_inventory_sha256",
            "expected_unit_root_sha256",
            "representation_assignment_root_sha256",
            "observation_root_sha256",
            "partition_root_sha256",
            "fixed_zero_landing_root_sha256",
            "binding_root_sha256",
            "source_record_root_sha256",
        ):
            _exact_sha256(getattr(self, field_name), field_name=field_name)
        for field_name, maximum in (
            ("expected_unit_count", MAX_PUBLIC_VALUE_EXPECTED_UNITS),
            ("representation_assignment_count", MAX_PUBLIC_VALUE_EXPECTED_UNITS),
            ("observation_count", MAX_LOSSLESS_OWNERSHIP_OBSERVATIONS),
            ("partition_count", MAX_LOSSLESS_OWNERSHIP_PARTITIONS),
            ("result_occurrence_partition_count", MAX_PUBLIC_VALUE_EXPECTED_UNITS),
            ("zero_result_occurrence_partition_count", MAX_PUBLIC_VALUE_EXPECTED_UNITS),
            ("result_occurrence_record_count", MAX_LOSSLESS_OWNERSHIP_BINDINGS),
            ("response_residual_partition_count", MAX_LOSSLESS_OWNERSHIP_OBSERVATIONS),
            (
                "positive_response_residual_partition_count",
                MAX_LOSSLESS_OWNERSHIP_OBSERVATIONS,
            ),
            (
                "zero_response_residual_partition_count",
                MAX_LOSSLESS_OWNERSHIP_OBSERVATIONS,
            ),
            ("response_residual_record_count", MAX_LOSSLESS_OWNERSHIP_BINDINGS),
            ("response_fixed_zero_partition_count", MAX_LOSSLESS_OWNERSHIP_OBSERVATIONS),
            ("binding_count", MAX_LOSSLESS_OWNERSHIP_BINDINGS),
            ("source_record_count", MAX_LOSSLESS_OWNERSHIP_BINDINGS),
        ):
            _exact_nonnegative(getattr(self, field_name), field_name=field_name, maximum=maximum)
        if (
            self.representation_assignment_count != self.expected_unit_count
            or self.expected_unit_count
            != self.result_occurrence_partition_count
            + self.positive_response_residual_partition_count
            + self.response_fixed_zero_partition_count
            or self.partition_count
            != self.result_occurrence_partition_count
            + self.response_residual_partition_count
            + self.response_fixed_zero_partition_count
            or self.observation_count
            != self.response_residual_partition_count + self.response_fixed_zero_partition_count
            or self.response_residual_partition_count
            != self.positive_response_residual_partition_count
            + self.zero_response_residual_partition_count
            or self.zero_result_occurrence_partition_count > self.result_occurrence_partition_count
            or self.binding_count != self.source_record_count
            or self.binding_count
            != self.result_occurrence_record_count + self.response_residual_record_count
        ):
            _fail("lossless-ownership receipt aggregate denominators are inconsistent")
        if (
            self.zero_response_residual_partition_count > self.result_occurrence_partition_count
            or self.result_occurrence_record_count
            < self.result_occurrence_partition_count - self.zero_result_occurrence_partition_count
            or self.response_residual_record_count < self.positive_response_residual_partition_count
            or (self.observation_count > 0 and self.expected_unit_count == 0)
        ):
            _fail("lossless-ownership receipt child positivity is inconsistent")
        if (self.response_residual_record_count == 0) != (
            self.positive_response_residual_partition_count == 0
        ):
            _fail("lossless-ownership receipt residual positivity is inconsistent")
        self._validate_zero_roots()
        if self.receipt_sha256 != _canonical_sha256(self.identity_payload()):
            _fail("lossless-ownership receipt digest differs from its exact identity")

    def _validate_zero_roots(self) -> None:
        empty_inventory = ExpectedValueUnitInventoryV1.build(
            raw_authority_bundle_sha256=self.raw_authority_bundle_sha256,
            units=(),
        )
        empty_roots = {
            "representation_assignment_root_sha256": _ordered_root(
                kind=_ASSIGNMENT_ROOT_KIND,
                item_sha256s=(),
                maximum=MAX_PUBLIC_VALUE_EXPECTED_UNITS,
            ),
            "observation_root_sha256": _ordered_root(
                kind=_AUTHORITY_OBSERVATION_ROOT_KIND,
                item_sha256s=(),
                maximum=MAX_LOSSLESS_OWNERSHIP_OBSERVATIONS,
            ),
            "partition_root_sha256": _ordered_root(
                kind=_AUTHORITY_PARTITION_ROOT_KIND,
                item_sha256s=(),
                maximum=MAX_LOSSLESS_OWNERSHIP_PARTITIONS,
            ),
            "fixed_zero_landing_root_sha256": _ordered_root(
                kind=_FIXED_ZERO_LANDING_ROOT_KIND,
                item_sha256s=(),
                maximum=MAX_LOSSLESS_OWNERSHIP_OBSERVATIONS,
            ),
            "binding_root_sha256": _ordered_root(
                kind=_AUTHORITY_BINDING_ROOT_KIND,
                item_sha256s=(),
                maximum=MAX_LOSSLESS_OWNERSHIP_BINDINGS,
            ),
            "source_record_root_sha256": _ordered_root(
                kind=_AUTHORITY_RECORD_ROOT_KIND,
                item_sha256s=(),
                maximum=MAX_LOSSLESS_OWNERSHIP_BINDINGS,
            ),
        }
        count_root_pairs = (
            (
                self.representation_assignment_count,
                "representation_assignment_root_sha256",
            ),
            (self.observation_count, "observation_root_sha256"),
            (self.partition_count, "partition_root_sha256"),
            (
                self.response_fixed_zero_partition_count,
                "fixed_zero_landing_root_sha256",
            ),
            (self.binding_count, "binding_root_sha256"),
            (self.source_record_count, "source_record_root_sha256"),
        )
        for count, field_name in count_root_pairs:
            if (count == 0) != (getattr(self, field_name) == empty_roots[field_name]):
                _fail(f"lossless-ownership receipt {field_name} zero proof is inconsistent")
        if (self.expected_unit_count == 0) != (
            self.expected_unit_inventory_sha256 == empty_inventory.inventory_sha256
            and self.expected_unit_root_sha256 == empty_inventory.unit_root_sha256
        ):
            _fail("lossless-ownership receipt expected-unit zero proof is inconsistent")
        if self.observation_count == 0 and any(
            value != 0
            for value in (
                self.expected_unit_count,
                self.partition_count,
                self.result_occurrence_partition_count,
                self.zero_result_occurrence_partition_count,
                self.result_occurrence_record_count,
                self.response_residual_partition_count,
                self.positive_response_residual_partition_count,
                self.zero_response_residual_partition_count,
                self.response_residual_record_count,
                self.response_fixed_zero_partition_count,
                self.binding_count,
            )
        ):
            _fail("empty lossless-ownership receipt has a nonempty child denominator")

    @classmethod
    def build(cls, **values: object) -> Self:
        payload = {
            "schema_version": cls.schema_version,
            "kind": cls.kind,
            **values,
        }
        try:
            return cls(receipt_sha256=_canonical_sha256(payload), **cast("Any", values))
        except LosslessOwnershipError:
            raise
        except (TypeError, ValueError):
            _fail("lossless-ownership receipt builder received an invalid field set")

    def identity_payload(self) -> dict[str, object]:
        return _identity_payload(self, kind=self.kind, digest_field="receipt_sha256")

    def to_row(self) -> dict[str, object]:
        return _to_row(self)

    @classmethod
    def from_row(cls, value: object) -> Self:
        row = _strict_dataclass_row(value, cls=cls, label="lossless-ownership receipt row")
        try:
            return cls(**cast("Any", {item.name: row[item.name] for item in fields(cls)}))
        except LosslessOwnershipError:
            raise
        except (TypeError, ValueError, RecursionError):
            _fail("lossless-ownership receipt row failed semantic reconstruction")

    def canonical_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_row())


def _exact_assignments(
    inventory: ExpectedValueUnitInventoryV1,
    assignments: object,
) -> tuple[ValueRepresentationAssignmentV1, ...]:
    if type(assignments) is not tuple or len(assignments) > MAX_PUBLIC_VALUE_EXPECTED_UNITS:
        _fail("lossless-ownership assignment inventory is foreign or over-bound")
    exact = assignments
    if any(type(assignment) is not ValueRepresentationAssignmentV1 for assignment in exact):
        _fail("lossless-ownership assignment inventory contains a foreign DTO")
    rebuilt: list[ValueRepresentationAssignmentV1] = []
    if len(exact) != inventory.unit_count:
        _fail("lossless-ownership assignment denominator differs from expected units")
    for ordinal, (unit, assignment_value) in enumerate(zip(inventory.units, exact, strict=True)):
        assignment = cast("ValueRepresentationAssignmentV1", assignment_value)
        try:
            replayed = ValueRepresentationAssignmentV1.from_row(assignment.to_row())
            replayed.validate_for_unit(unit)
        except PublicValueTypesError as exc:
            raise LosslessOwnershipError(
                "lossless-ownership assignment fails exact expected-unit replay"
            ) from exc
        if replayed.unit_ordinal != ordinal or replayed.unit_sha256 != unit.unit_sha256:
            _fail("lossless-ownership assignments are foreign or reordered")
        rebuilt.append(replayed)
    if len({assignment.assignment_sha256 for assignment in rebuilt}) != len(rebuilt):
        _fail("lossless-ownership assignment inventory contains a duplicate")
    return tuple(rebuilt)


def _exact_dto_tuple(
    value: object,
    *,
    cls: type[object],
    maximum: int,
    label: str,
) -> tuple[Any, ...]:
    if type(value) is not tuple or len(value) > maximum:
        _fail(f"{label} is foreign or over-bound")
    exact = value
    if any(type(item) is not cls for item in exact):
        _fail(f"{label} contains a foreign DTO")
    return tuple(cast("Any", cls).from_row(cast("Any", item).to_row()) for item in exact)


def _derive_receipt(
    *,
    raw_authority_bundle_sha256: str,
    expected_unit_inventory: ExpectedValueUnitInventoryV1,
    representation_assignments: object,
    observations: object,
    partitions: object,
    bindings: object,
) -> tuple[
    LosslessOwnershipReceiptV1,
    ExpectedValueUnitInventoryV1,
    tuple[ValueRepresentationAssignmentV1, ...],
    tuple[LosslessObservationOwnershipV1, ...],
    tuple[LosslessOwnershipPartitionV1, ...],
    tuple[LosslessOwnershipBindingV1, ...],
]:
    _exact_sha256(raw_authority_bundle_sha256, field_name="raw authority bundle")
    if type(expected_unit_inventory) is not ExpectedValueUnitInventoryV1:
        _fail("lossless-ownership authority has a foreign expected-unit inventory")
    try:
        inventory = ExpectedValueUnitInventoryV1.from_row(expected_unit_inventory.to_row())
    except PublicValueTypesError as exc:
        raise LosslessOwnershipError(
            "lossless-ownership expected-unit inventory fails exact replay"
        ) from exc
    if inventory.raw_authority_bundle_sha256 != raw_authority_bundle_sha256:
        _fail("lossless-ownership expected-unit inventory belongs to a foreign bundle")
    exact_assignments = _exact_assignments(inventory, representation_assignments)
    exact_observations = cast(
        "tuple[LosslessObservationOwnershipV1, ...]",
        _exact_dto_tuple(
            observations,
            cls=LosslessObservationOwnershipV1,
            maximum=MAX_LOSSLESS_OWNERSHIP_OBSERVATIONS,
            label="lossless-ownership observation inventory",
        ),
    )
    exact_partitions = cast(
        "tuple[LosslessOwnershipPartitionV1, ...]",
        _exact_dto_tuple(
            partitions,
            cls=LosslessOwnershipPartitionV1,
            maximum=MAX_LOSSLESS_OWNERSHIP_PARTITIONS,
            label="lossless-ownership partition inventory",
        ),
    )
    exact_bindings = cast(
        "tuple[LosslessOwnershipBindingV1, ...]",
        _exact_dto_tuple(
            bindings,
            cls=LosslessOwnershipBindingV1,
            maximum=MAX_LOSSLESS_OWNERSHIP_BINDINGS,
            label="lossless-ownership binding inventory",
        ),
    )

    observation_by_ordinal: dict[int, LosslessObservationOwnershipV1] = {}
    seen_observation_sha256s: set[str] = set()
    seen_observation_record_sha256s: set[str] = set()
    for ordinal, observation in enumerate(exact_observations):
        if (
            observation.observation_ordinal != ordinal
            or observation.raw_authority_bundle_sha256 != raw_authority_bundle_sha256
        ):
            _fail("lossless-ownership observations are foreign or reordered")
        if (
            observation.observation_sha256 in seen_observation_sha256s
            or observation.observation_record_sha256 in seen_observation_record_sha256s
        ):
            _fail("lossless-ownership observation inventory contains a duplicate")
        seen_observation_sha256s.add(observation.observation_sha256)
        seen_observation_record_sha256s.add(observation.observation_record_sha256)
        observation_by_ordinal[ordinal] = observation

    for ordinal, unit in enumerate(inventory.units):
        observation = observation_by_ordinal.get(unit.observation_ordinal)
        if (
            unit.unit_ordinal != ordinal
            or observation is None
            or unit.observation_sha256 != observation.observation_sha256
        ):
            _fail("lossless-ownership expected unit references a foreign observation")

    partition_by_ordinal: dict[int, LosslessOwnershipPartitionV1] = {}
    partitions_by_observation: dict[int, list[LosslessOwnershipPartitionV1]] = {}
    used_unit_ordinals: set[int] = set()
    expected_next_observation_partition: dict[int, int] = {}
    for ordinal, partition in enumerate(exact_partitions):
        observation = observation_by_ordinal.get(partition.observation_ordinal)
        if (
            partition.partition_ordinal != ordinal
            or partition.raw_authority_bundle_sha256 != raw_authority_bundle_sha256
            or observation is None
            or partition.observation_record_sha256 != observation.observation_record_sha256
            or partition.observation_sha256 != observation.observation_sha256
        ):
            _fail("lossless-ownership partition references a foreign owner or order")
        partitions_by_observation.setdefault(partition.observation_ordinal, []).append(partition)
        expected_observation_partition = expected_next_observation_partition.get(
            partition.observation_ordinal,
            0,
        )
        if partition.observation_partition_ordinal != expected_observation_partition:
            _fail("lossless-ownership observation partition order is not contiguous")
        expected_next_observation_partition[partition.observation_ordinal] = (
            expected_observation_partition + 1
        )
        partition_by_ordinal[ordinal] = partition
        if partition.unit_ordinal is None:
            if partition.partition_kind != "response_residual" or partition.record_count != 0:
                _fail("lossless-ownership partition omits a required expected unit")
            continue
        if partition.unit_ordinal >= inventory.unit_count:
            _fail("lossless-ownership partition references a foreign expected unit")
        unit = inventory.units[partition.unit_ordinal]
        assignment = exact_assignments[partition.unit_ordinal]
        if (
            partition.unit_ordinal in used_unit_ordinals
            or partition.unit_sha256 != unit.unit_sha256
            or partition.assignment_sha256 != assignment.assignment_sha256
            or partition.partition_kind != unit.unit_kind
            or partition.observation_ordinal != unit.observation_ordinal
            or partition.observation_sha256 != unit.observation_sha256
            or partition.occurrence_sha256 != unit.occurrence_sha256
            or partition.occurrence_ordinal != unit.occurrence_ordinal
            or assignment.source_input_kind != observation.source_input_kind
        ):
            _fail("lossless-ownership partition has a duplicate or foreign unit binding")
        used_unit_ordinals.add(partition.unit_ordinal)
    if used_unit_ordinals != set(range(inventory.unit_count)):
        _fail("lossless-ownership authority leaves an expected unit orphaned")

    seen_binding_sha256s: set[str] = set()
    seen_source_record_sha256s: set[str] = set()
    bindings_by_partition: dict[int, list[LosslessOwnershipBindingV1]] = {}
    bindings_by_observation: dict[int, list[LosslessOwnershipBindingV1]] = {}
    next_observation_record_ordinal: dict[int, int] = {}
    last_binding_observation_ordinal = -1
    for ordinal, binding in enumerate(exact_bindings):
        observation = observation_by_ordinal.get(binding.observation_ordinal)
        partition = partition_by_ordinal.get(binding.partition_ordinal)
        if (
            binding.binding_ordinal != ordinal
            or binding.raw_authority_bundle_sha256 != raw_authority_bundle_sha256
            or observation is None
            or partition is None
            or binding.observation_record_sha256 != observation.observation_record_sha256
            or binding.observation_sha256 != observation.observation_sha256
            or partition.observation_ordinal != binding.observation_ordinal
        ):
            _fail("lossless-ownership binding is orphaned, foreign, or reordered")
        bindings_by_partition.setdefault(binding.partition_ordinal, []).append(binding)
        bindings_by_observation.setdefault(binding.observation_ordinal, []).append(binding)
        if binding.observation_ordinal < last_binding_observation_ordinal:
            _fail("lossless-ownership bindings reopen a completed observation")
        last_binding_observation_ordinal = binding.observation_ordinal
        expected_record_ordinal = next_observation_record_ordinal.get(
            binding.observation_ordinal,
            0,
        )
        if binding.observation_record_ordinal != expected_record_ordinal:
            _fail("lossless-ownership observation record order is not contiguous")
        next_observation_record_ordinal[binding.observation_ordinal] = expected_record_ordinal + 1
        if (
            binding.binding_sha256 in seen_binding_sha256s
            or binding.source_record_sha256 in seen_source_record_sha256s
        ):
            _fail("lossless-ownership binding inventory dual-assigns a source record")
        seen_binding_sha256s.add(binding.binding_sha256)
        seen_source_record_sha256s.add(binding.source_record_sha256)
        if binding.unit_ordinal >= inventory.unit_count:
            _fail("lossless-ownership binding references a foreign expected unit")
        unit = inventory.units[binding.unit_ordinal]
        assignment = exact_assignments[binding.unit_ordinal]
        if (
            binding.unit_sha256 != unit.unit_sha256
            or binding.assignment_sha256 != assignment.assignment_sha256
            or binding.ownership_kind != unit.unit_kind
            or binding.occurrence_sha256 != unit.occurrence_sha256
            or binding.occurrence_ordinal != unit.occurrence_ordinal
            or binding.unit_sha256 != partition.unit_sha256
            or binding.unit_ordinal != partition.unit_ordinal
            or binding.assignment_sha256 != partition.assignment_sha256
            or binding.ownership_kind != partition.partition_kind
            or binding.occurrence_sha256 != partition.occurrence_sha256
            or binding.occurrence_ordinal != partition.occurrence_ordinal
        ):
            _fail("lossless-ownership binding disagrees with its partition or unit")

    for partition in exact_partitions:
        owned_bindings = tuple(bindings_by_partition.get(partition.partition_ordinal, ()))
        _validate_partition_binding_roots(partition, owned_bindings)

    for observation in exact_observations:
        owned_partitions = tuple(partitions_by_observation.get(observation.observation_ordinal, ()))
        owned_bindings = tuple(bindings_by_observation.get(observation.observation_ordinal, ()))
        rebuilt = LosslessObservationOwnershipV1.build(
            raw_authority_bundle_sha256=raw_authority_bundle_sha256,
            observation_record_sha256=observation.observation_record_sha256,
            observation_sha256=observation.observation_sha256,
            observation_ordinal=observation.observation_ordinal,
            source_input_kind=observation.source_input_kind,
            partitions=owned_partitions,
            bindings=owned_bindings,
        )
        if rebuilt != observation:
            _fail("lossless observation differs from its exact partitions and bindings")

    assignment_root_sha256 = _ordered_root(
        kind=_ASSIGNMENT_ROOT_KIND,
        item_sha256s=tuple(assignment.assignment_sha256 for assignment in exact_assignments),
        maximum=MAX_PUBLIC_VALUE_EXPECTED_UNITS,
    )
    observation_root_sha256 = _ordered_root(
        kind=_AUTHORITY_OBSERVATION_ROOT_KIND,
        item_sha256s=tuple(
            observation.observation_ownership_sha256 for observation in exact_observations
        ),
        maximum=MAX_LOSSLESS_OWNERSHIP_OBSERVATIONS,
    )
    partition_root_sha256 = _ordered_root(
        kind=_AUTHORITY_PARTITION_ROOT_KIND,
        item_sha256s=tuple(partition.partition_sha256 for partition in exact_partitions),
        maximum=MAX_LOSSLESS_OWNERSHIP_PARTITIONS,
    )
    binding_root_sha256 = _ordered_root(
        kind=_AUTHORITY_BINDING_ROOT_KIND,
        item_sha256s=tuple(binding.binding_sha256 for binding in exact_bindings),
        maximum=MAX_LOSSLESS_OWNERSHIP_BINDINGS,
    )
    source_record_root_sha256 = _ordered_root(
        kind=_AUTHORITY_RECORD_ROOT_KIND,
        item_sha256s=tuple(binding.source_record_sha256 for binding in exact_bindings),
        maximum=MAX_LOSSLESS_OWNERSHIP_BINDINGS,
    )
    fixed_zero_partitions = tuple(
        partition
        for partition in exact_partitions
        if partition.partition_kind == "response_fixed_zero"
    )
    fixed_zero_landing_root_sha256 = _ordered_root(
        kind=_FIXED_ZERO_LANDING_ROOT_KIND,
        item_sha256s=tuple(
            cast("str", partition.fixed_zero_landing_sha256) for partition in fixed_zero_partitions
        ),
        maximum=MAX_LOSSLESS_OWNERSHIP_OBSERVATIONS,
    )
    occurrence_partitions = tuple(
        partition
        for partition in exact_partitions
        if partition.partition_kind == "result_occurrence"
    )
    residual_partitions = tuple(
        partition
        for partition in exact_partitions
        if partition.partition_kind == "response_residual"
    )
    receipt = LosslessOwnershipReceiptV1.build(
        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
        expected_unit_count=inventory.unit_count,
        expected_unit_inventory_sha256=inventory.inventory_sha256,
        expected_unit_root_sha256=inventory.unit_root_sha256,
        representation_assignment_count=len(exact_assignments),
        representation_assignment_root_sha256=assignment_root_sha256,
        observation_count=len(exact_observations),
        observation_root_sha256=observation_root_sha256,
        partition_count=len(exact_partitions),
        partition_root_sha256=partition_root_sha256,
        result_occurrence_partition_count=len(occurrence_partitions),
        zero_result_occurrence_partition_count=sum(
            partition.record_count == 0 for partition in occurrence_partitions
        ),
        result_occurrence_record_count=sum(
            partition.record_count for partition in occurrence_partitions
        ),
        response_residual_partition_count=len(residual_partitions),
        positive_response_residual_partition_count=sum(
            partition.record_count > 0 for partition in residual_partitions
        ),
        zero_response_residual_partition_count=sum(
            partition.record_count == 0 for partition in residual_partitions
        ),
        response_residual_record_count=sum(
            partition.record_count for partition in residual_partitions
        ),
        response_fixed_zero_partition_count=len(fixed_zero_partitions),
        fixed_zero_landing_root_sha256=fixed_zero_landing_root_sha256,
        binding_count=len(exact_bindings),
        binding_root_sha256=binding_root_sha256,
        source_record_count=len(exact_bindings),
        source_record_root_sha256=source_record_root_sha256,
    )
    return (
        receipt,
        inventory,
        exact_assignments,
        exact_observations,
        exact_partitions,
        exact_bindings,
    )


@dataclass(frozen=True, slots=True)
class LosslessOwnershipAuthorityV1:
    """In-memory closure over the receipt and every normalized ownership child."""

    receipt: LosslessOwnershipReceiptV1
    expected_unit_inventory: ExpectedValueUnitInventoryV1
    representation_assignments: tuple[ValueRepresentationAssignmentV1, ...]
    observations: tuple[LosslessObservationOwnershipV1, ...]
    partitions: tuple[LosslessOwnershipPartitionV1, ...]
    bindings: tuple[LosslessOwnershipBindingV1, ...]

    def __post_init__(self) -> None:
        if type(self.receipt) is not LosslessOwnershipReceiptV1:
            _fail("lossless-ownership authority has a foreign receipt DTO")
        replayed_receipt = LosslessOwnershipReceiptV1.from_row(self.receipt.to_row())
        (
            expected_receipt,
            expected_inventory,
            expected_assignments,
            expected_observations,
            expected_partitions,
            expected_bindings,
        ) = _derive_receipt(
            raw_authority_bundle_sha256=replayed_receipt.raw_authority_bundle_sha256,
            expected_unit_inventory=self.expected_unit_inventory,
            representation_assignments=self.representation_assignments,
            observations=self.observations,
            partitions=self.partitions,
            bindings=self.bindings,
        )
        if (
            replayed_receipt != expected_receipt
            or self.expected_unit_inventory != expected_inventory
            or self.representation_assignments != expected_assignments
            or self.observations != expected_observations
            or self.partitions != expected_partitions
            or self.bindings != expected_bindings
        ):
            _fail("lossless-ownership authority differs from its exact reconstructed closure")

    @classmethod
    def build(
        cls,
        *,
        raw_authority_bundle_sha256: str,
        expected_unit_inventory: ExpectedValueUnitInventoryV1,
        representation_assignments: tuple[ValueRepresentationAssignmentV1, ...],
        observations: tuple[LosslessObservationOwnershipV1, ...],
        partitions: tuple[LosslessOwnershipPartitionV1, ...],
        bindings: tuple[LosslessOwnershipBindingV1, ...],
    ) -> Self:
        (
            receipt,
            inventory,
            exact_assignments,
            exact_observations,
            exact_partitions,
            exact_bindings,
        ) = _derive_receipt(
            raw_authority_bundle_sha256=raw_authority_bundle_sha256,
            expected_unit_inventory=expected_unit_inventory,
            representation_assignments=representation_assignments,
            observations=observations,
            partitions=partitions,
            bindings=bindings,
        )
        return cls(
            receipt=receipt,
            expected_unit_inventory=inventory,
            representation_assignments=exact_assignments,
            observations=exact_observations,
            partitions=exact_partitions,
            bindings=exact_bindings,
        )


def build_lossless_ownership_authority(
    *,
    raw_authority_bundle_sha256: str,
    expected_unit_inventory: ExpectedValueUnitInventoryV1,
    representation_assignments: tuple[ValueRepresentationAssignmentV1, ...],
    observations: tuple[LosslessObservationOwnershipV1, ...],
    partitions: tuple[LosslessOwnershipPartitionV1, ...],
    bindings: tuple[LosslessOwnershipBindingV1, ...],
) -> LosslessOwnershipAuthorityV1:
    """Build one exact normalized ownership authority without importing adapters."""

    return LosslessOwnershipAuthorityV1.build(
        raw_authority_bundle_sha256=raw_authority_bundle_sha256,
        expected_unit_inventory=expected_unit_inventory,
        representation_assignments=representation_assignments,
        observations=observations,
        partitions=partitions,
        bindings=bindings,
    )
