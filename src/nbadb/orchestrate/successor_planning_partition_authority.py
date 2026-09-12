"""Bounded content-addressed partitions for successor planning route rows.

This module is deliberately storage-free.  It defines compact, strict codecs
and a descriptor-driven iterator; callers supply partition bytes through a
callable.  A verified iterator is non-admitting until it is exhausted.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import ClassVar, Final, Never, Self, cast

from nbadb.contracts.ordered_sha256_prefix_fold import (
    OrderedSha256PrefixFoldV1,
    compute_ordered_sha256_prefix_fold,
    empty_ordered_sha256_prefix_fold,
    extend_ordered_sha256_prefix_fold,
)

__all__ = [
    "MAX_SUCCESSOR_PLANNING_PARTITION_BYTES",
    "MAX_SUCCESSOR_PLANNING_PARTITION_DESCRIPTORS",
    "MAX_SUCCESSOR_PLANNING_PARTITION_ROWS",
    "MAX_SUCCESSOR_PLANNING_PLAN_ROWS",
    "SuccessorPlanningPartitionAuthorityError",
    "SuccessorPlanningPartitionByteLoader",
    "SuccessorPlanningPartitionDescriptorV1",
    "SuccessorPlanningPartitionHeaderV1",
    "SuccessorPlanningRouteDispatchPartitionV1",
    "SuccessorPlanningRouteDispatchRowV1",
    "build_successor_planning_partition_header",
    "empty_successor_planning_row_fold",
    "iter_verified_successor_planning_rows",
]

MAX_SUCCESSOR_PLANNING_PARTITION_ROWS: Final = 10_000
# The format contract is strictly below 12 MiB; this exported maximum is
# therefore the largest admitted inclusive canonical byte length.
MAX_SUCCESSOR_PLANNING_PARTITION_BYTES: Final = (12 * 1024 * 1024) - 1
MAX_SUCCESSOR_PLANNING_PARTITION_DESCRIPTORS: Final = 25
MAX_SUCCESSOR_PLANNING_PLAN_ROWS: Final = 250_000

_MAX_ROW_BYTES: Final = 64 * 1024
_MAX_HEADER_BYTES: Final = 128 * 1024
_MAX_DEPTH: Final = 32
_MAX_PARTITION_NODES: Final = 500_000
_MAX_ROW_NODES: Final = 2_048
_MAX_HEADER_NODES: Final = 4_096
_MAX_INTEGER: Final = (1 << 63) - 1
_ROW_FOLD_DOMAIN: Final = "successor-planning-route-dispatch-rows-v1"
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)
_SAFE_TOKEN_RE: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z", flags=re.ASCII)
_PATH_KEY_RE: Final = re.compile(
    r"(?:^|_)(?:cwd|dir|directory|file|filename|home|path|root)(?:$|_)",
    flags=re.IGNORECASE,
)
_PATH_VALUE_RE: Final = re.compile(r"(?:^[/~\\]|^\.\.?[/\\]|^[A-Za-z]:[/\\]|://|\\)")


class SuccessorPlanningPartitionAuthorityError(ValueError):
    """A planning partition, descriptor, or header is malformed."""


type SuccessorPlanningPartitionByteLoader = Callable[
    ["SuccessorPlanningPartitionDescriptorV1"], bytes
]


def _fail(message: str) -> Never:
    raise SuccessorPlanningPartitionAuthorityError(message) from None


def _sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be one exact lowercase SHA-256")
    return value


def _token(value: object, *, label: str) -> str:
    if type(value) is not str or _SAFE_TOKEN_RE.fullmatch(value) is None:
        _fail(f"{label} must be one exact path-free safe token")
    return value


def _count(value: object, *, label: str, positive: bool = False, maximum: int) -> int:
    minimum = 1 if positive else 0
    if type(value) is not int or not minimum <= value <= min(maximum, _MAX_INTEGER):
        qualifier = "positive" if positive else "nonnegative"
        _fail(f"{label} must be one exact bounded {qualifier} integer")
    return value


def _exact_keys(value: Mapping[str, object], expected: frozenset[str], *, label: str) -> None:
    if frozenset(value) != expected:
        _fail(f"{label} fields differ from the exact schema")


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("canonical JSON contains a duplicate object key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> Never:
    _fail("canonical JSON contains a non-finite number")


def _validate_graph(value: object, *, maximum_nodes: int, reject_paths: bool = False) -> None:
    stack: list[tuple[object, int, str | None]] = [(value, 0, None)]
    nodes = 0
    while stack:
        item, depth, key = stack.pop()
        nodes += 1
        if nodes > maximum_nodes or depth > _MAX_DEPTH:
            _fail("canonical JSON exceeds its structural bound")
        if item is None:
            continue
        if type(item) is bool:
            _fail("planning partition authority cannot contain booleans")
        if type(item) is int:
            if not -_MAX_INTEGER <= item <= _MAX_INTEGER:
                _fail("canonical JSON contains an over-bound integer")
            continue
        if type(item) is float:
            if not math.isfinite(item):
                _fail("canonical JSON contains a non-finite number")
            continue
        if type(item) is str:
            try:
                item.encode("utf-8", errors="strict")
            except UnicodeEncodeError:
                _fail("canonical JSON contains invalid Unicode")
            if reject_paths and (
                (key is not None and _PATH_KEY_RE.search(key)) or _PATH_VALUE_RE.search(item)
            ):
                _fail("canonical scope body cannot contain a physical path or URI")
            continue
        if type(item) is list:
            stack.extend((child, depth + 1, None) for child in reversed(item))
            continue
        if type(item) is dict:
            for child_key, child in reversed(tuple(item.items())):
                if type(child_key) is not str:
                    _fail("canonical JSON keys must be exact strings")
                if reject_paths and _PATH_KEY_RE.search(child_key):
                    _fail("canonical scope body cannot contain a physical path key")
                stack.append((child, depth + 1, child_key))
            continue
        _fail("canonical JSON contains a foreign exact type")


def _canonical_bytes(value: object, *, maximum: int, maximum_nodes: int) -> bytes:
    _validate_graph(value, maximum_nodes=maximum_nodes)
    try:
        raw = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8", errors="strict")
    except (MemoryError, RecursionError, TypeError, UnicodeEncodeError, ValueError):
        _fail("planning partition authority is not canonical JSON")
    if not raw or len(raw) > maximum:
        _fail("planning partition authority exceeds its canonical byte ceiling")
    return raw


def _decode(raw: object, *, maximum: int, maximum_nodes: int, label: str) -> object:
    if type(raw) is not bytes or not raw or len(raw) > maximum:
        _fail(f"{label} canonical bytes are empty, foreign, or oversized")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except SuccessorPlanningPartitionAuthorityError:
        raise
    except (MemoryError, RecursionError, TypeError, UnicodeError, ValueError):
        _fail(f"{label} canonical bytes cannot be decoded")
    _validate_graph(value, maximum_nodes=maximum_nodes)
    if _canonical_bytes(value, maximum=maximum, maximum_nodes=maximum_nodes) != raw:
        _fail(f"{label} bytes differ from exact canonical replay")
    return value


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        _fail(f"{label} must be one exact object")
    return cast("Mapping[str, object]", value)


def _sha_tuple(value: object, *, label: str) -> tuple[str, ...]:
    if type(value) is not list:
        _fail(f"{label} must be one exact array")
    result = tuple(_sha256(item, label=f"{label} member") for item in value)
    if result != tuple(sorted(set(result))):
        _fail(f"{label} must be sorted and unique")
    return result


def _scope_body(value: object) -> str:
    if type(value) is not str:
        _fail("canonical_scope_body must be exact text")
    try:
        raw = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        _fail("canonical_scope_body contains invalid Unicode")
    decoded = _decode(
        raw,
        maximum=_MAX_ROW_BYTES,
        maximum_nodes=_MAX_ROW_NODES,
        label="canonical scope body",
    )
    if type(decoded) is not dict:
        _fail("canonical scope body must contain one exact object")
    _validate_graph(decoded, maximum_nodes=_MAX_ROW_NODES, reject_paths=True)
    return value


@dataclass(frozen=True, slots=True)
class SuccessorPlanningRouteDispatchRowV1:
    """One exact requested route position inside one sealed provider dispatch."""

    global_ordinal: int
    dispatch_identity_sha256: str
    call_identity_sha256: str
    requested_scope_identity_sha256: str
    canonical_scope_body: str
    canonical_scope_body_sha256: str
    staging_route_id: str
    route_contract_identity_sha256: str
    endpoint_identity_sha256: str
    parameter_identity_sha256: str
    position: int
    dependency_identity_sha256s: tuple[str, ...]
    row_sha256: str = field(init=False)

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "successor_planning_route_dispatch_row_v1"

    def __post_init__(self) -> None:
        if type(self) is not SuccessorPlanningRouteDispatchRowV1:
            _fail("route-dispatch row subclasses are forbidden")
        _count(
            self.global_ordinal,
            label="global_ordinal",
            maximum=MAX_SUCCESSOR_PLANNING_PLAN_ROWS - 1,
        )
        _count(self.position, label="position", maximum=MAX_SUCCESSOR_PLANNING_PLAN_ROWS)
        for name in (
            "dispatch_identity_sha256",
            "call_identity_sha256",
            "requested_scope_identity_sha256",
            "canonical_scope_body_sha256",
            "route_contract_identity_sha256",
            "endpoint_identity_sha256",
            "parameter_identity_sha256",
        ):
            _sha256(getattr(self, name), label=name)
        _token(self.staging_route_id, label="staging_route_id")
        body = _scope_body(self.canonical_scope_body)
        body_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
        if body_sha256 != self.canonical_scope_body_sha256:
            _fail("canonical scope body digest differs")
        if self.parameter_identity_sha256 != body_sha256:
            _fail("parameter identity differs from the canonical scope body")
        if type(self.dependency_identity_sha256s) is not tuple:
            _fail("dependency identities must be one exact immutable tuple")
        dependencies = tuple(
            _sha256(item, label="dependency identity") for item in self.dependency_identity_sha256s
        )
        if dependencies != tuple(sorted(set(dependencies))):
            _fail("dependency identities must be sorted and unique")
        object.__setattr__(self, "row_sha256", hashlib.sha256(self.identity_bytes()).hexdigest())

    def __init_subclass__(cls, **_kwargs: object) -> Never:
        _fail("route-dispatch row subclasses are forbidden")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "call_identity_sha256": self.call_identity_sha256,
            "canonical_scope_body": self.canonical_scope_body,
            "canonical_scope_body_sha256": self.canonical_scope_body_sha256,
            "dependency_identity_sha256s": list(self.dependency_identity_sha256s),
            "dispatch_identity_sha256": self.dispatch_identity_sha256,
            "endpoint_identity_sha256": self.endpoint_identity_sha256,
            "global_ordinal": self.global_ordinal,
            "parameter_identity_sha256": self.parameter_identity_sha256,
            "position": self.position,
            "requested_scope_identity_sha256": self.requested_scope_identity_sha256,
            "route_contract_identity_sha256": self.route_contract_identity_sha256,
            "staging_route_id": self.staging_route_id,
        }

    def identity_bytes(self) -> bytes:
        return _canonical_bytes(self.identity_payload(), maximum=_MAX_ROW_BYTES, maximum_nodes=256)

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "row_sha256": self.row_sha256}

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict(), maximum=_MAX_ROW_BYTES, maximum_nodes=256)

    @classmethod
    def from_canonical_scope(
        cls,
        *,
        global_ordinal: int,
        dispatch_identity_sha256: str,
        call_identity_sha256: str,
        requested_scope_identity_sha256: str,
        canonical_scope: Mapping[str, object],
        staging_route_id: str,
        route_contract_identity_sha256: str,
        endpoint_identity_sha256: str,
        position: int,
        dependency_identity_sha256s: tuple[str, ...],
    ) -> Self:
        if cls is not SuccessorPlanningRouteDispatchRowV1 or type(canonical_scope) is not dict:
            _fail("route-dispatch row construction requires one exact scope object")
        _validate_graph(canonical_scope, maximum_nodes=_MAX_ROW_NODES, reject_paths=True)
        body = _canonical_bytes(
            dict(canonical_scope), maximum=_MAX_ROW_BYTES, maximum_nodes=_MAX_ROW_NODES
        ).decode("utf-8")
        body_sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
        return cls(
            global_ordinal=global_ordinal,
            dispatch_identity_sha256=dispatch_identity_sha256,
            call_identity_sha256=call_identity_sha256,
            requested_scope_identity_sha256=requested_scope_identity_sha256,
            canonical_scope_body=body,
            canonical_scope_body_sha256=body_sha256,
            staging_route_id=staging_route_id,
            route_contract_identity_sha256=route_contract_identity_sha256,
            endpoint_identity_sha256=endpoint_identity_sha256,
            parameter_identity_sha256=body_sha256,
            position=position,
            dependency_identity_sha256s=dependency_identity_sha256s,
        )

    @classmethod
    def _from_payload(cls, value: object) -> Self:
        payload = _mapping(value, label="route-dispatch row")
        expected = frozenset(
            {
                "schema_version",
                "kind",
                "call_identity_sha256",
                "canonical_scope_body",
                "canonical_scope_body_sha256",
                "dependency_identity_sha256s",
                "dispatch_identity_sha256",
                "endpoint_identity_sha256",
                "global_ordinal",
                "parameter_identity_sha256",
                "position",
                "requested_scope_identity_sha256",
                "route_contract_identity_sha256",
                "row_sha256",
                "staging_route_id",
            }
        )
        _exact_keys(payload, expected, label="route-dispatch row")
        if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
            _fail("route-dispatch row schema version is invalid")
        if type(payload["kind"]) is not str or payload["kind"] != cls.kind:
            _fail("route-dispatch row kind is invalid")
        row = cls(
            global_ordinal=cast("int", payload["global_ordinal"]),
            dispatch_identity_sha256=cast("str", payload["dispatch_identity_sha256"]),
            call_identity_sha256=cast("str", payload["call_identity_sha256"]),
            requested_scope_identity_sha256=cast("str", payload["requested_scope_identity_sha256"]),
            canonical_scope_body=cast("str", payload["canonical_scope_body"]),
            canonical_scope_body_sha256=cast("str", payload["canonical_scope_body_sha256"]),
            staging_route_id=cast("str", payload["staging_route_id"]),
            route_contract_identity_sha256=cast("str", payload["route_contract_identity_sha256"]),
            endpoint_identity_sha256=cast("str", payload["endpoint_identity_sha256"]),
            parameter_identity_sha256=cast("str", payload["parameter_identity_sha256"]),
            position=cast("int", payload["position"]),
            dependency_identity_sha256s=_sha_tuple(
                payload["dependency_identity_sha256s"], label="dependency identities"
            ),
        )
        if row.row_sha256 != _sha256(payload["row_sha256"], label="row_sha256"):
            _fail("route-dispatch row digest differs")
        return row

    @classmethod
    def from_canonical_bytes(cls, raw: object) -> SuccessorPlanningRouteDispatchRowV1:
        if cls is not SuccessorPlanningRouteDispatchRowV1:
            _fail("route-dispatch row subclasses are forbidden")
        row = cls._from_payload(
            _decode(raw, maximum=_MAX_ROW_BYTES, maximum_nodes=256, label="route-dispatch row")
        )
        if raw != row.canonical_bytes():
            _fail("route-dispatch row bytes differ from exact replay")
        return row


@dataclass(frozen=True, slots=True)
class SuccessorPlanningRouteDispatchPartitionV1:
    """One immutable contiguous route-row partition and cumulative prefix root."""

    partition_ordinal: int
    start_ordinal: int
    end_ordinal: int
    prior_row_root_sha256: str
    rows: tuple[SuccessorPlanningRouteDispatchRowV1, ...]
    row_count: int
    row_root_sha256: str

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "successor_planning_route_dispatch_partition_v1"

    def __post_init__(self) -> None:
        if type(self) is not SuccessorPlanningRouteDispatchPartitionV1:
            _fail("route-dispatch partition subclasses are forbidden")
        _count(
            self.partition_ordinal,
            label="partition_ordinal",
            maximum=MAX_SUCCESSOR_PLANNING_PARTITION_DESCRIPTORS - 1,
        )
        start = _count(
            self.start_ordinal, label="start_ordinal", maximum=MAX_SUCCESSOR_PLANNING_PLAN_ROWS - 1
        )
        end = _count(
            self.end_ordinal, label="end_ordinal", maximum=MAX_SUCCESSOR_PLANNING_PLAN_ROWS - 1
        )
        count = _count(
            self.row_count,
            label="row_count",
            positive=True,
            maximum=MAX_SUCCESSOR_PLANNING_PARTITION_ROWS,
        )
        _sha256(self.prior_row_root_sha256, label="prior_row_root_sha256")
        _sha256(self.row_root_sha256, label="row_root_sha256")
        if (
            type(self.rows) is not tuple
            or len(self.rows) != count
            or any(type(row) is not SuccessorPlanningRouteDispatchRowV1 for row in self.rows)
        ):
            _fail("partition rows differ from the exact row denominator")
        if end != start + count - 1:
            _fail("partition ordinal range differs from its row count")
        if tuple(row.global_ordinal for row in self.rows) != tuple(range(start, end + 1)):
            _fail("partition rows are not globally contiguous")
        try:
            folded = extend_ordered_sha256_prefix_fold(
                domain=_ROW_FOLD_DOMAIN,
                prior_count=start,
                prior_root_sha256=self.prior_row_root_sha256,
                appended_count=count,
                item_sha256s=(row.row_sha256 for row in self.rows),
            )
        except ValueError as exc:
            raise SuccessorPlanningPartitionAuthorityError("partition row fold is invalid") from exc
        if folded.root_sha256 != self.row_root_sha256:
            _fail("partition cumulative row root differs")
        if len(self.canonical_bytes()) > MAX_SUCCESSOR_PLANNING_PARTITION_BYTES:
            _fail("partition exceeds its fixed canonical byte ceiling")

    def __init_subclass__(cls, **_kwargs: object) -> Never:
        _fail("route-dispatch partition subclasses are forbidden")

    @classmethod
    def build(
        cls,
        *,
        partition_ordinal: int,
        prior_fold: OrderedSha256PrefixFoldV1,
        rows: tuple[SuccessorPlanningRouteDispatchRowV1, ...],
    ) -> Self:
        if cls is not SuccessorPlanningRouteDispatchPartitionV1:
            _fail("route-dispatch partition subclasses are forbidden")
        if (
            type(prior_fold) is not OrderedSha256PrefixFoldV1
            or prior_fold.domain != _ROW_FOLD_DOMAIN
        ):
            _fail("partition requires the exact prior planning-row fold")
        if type(rows) is not tuple or not rows:
            _fail("partition rows must be one nonempty exact tuple")
        try:
            folded = extend_ordered_sha256_prefix_fold(
                domain=_ROW_FOLD_DOMAIN,
                prior_count=prior_fold.count,
                prior_root_sha256=prior_fold.root_sha256,
                appended_count=len(rows),
                item_sha256s=(row.row_sha256 for row in rows),
            )
        except (AttributeError, ValueError) as exc:
            raise SuccessorPlanningPartitionAuthorityError(
                "partition rows cannot extend the prior fold"
            ) from exc
        return cls(
            partition_ordinal=partition_ordinal,
            start_ordinal=prior_fold.count,
            end_ordinal=folded.count - 1,
            prior_row_root_sha256=prior_fold.root_sha256,
            rows=rows,
            row_count=len(rows),
            row_root_sha256=folded.root_sha256,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "end_ordinal": self.end_ordinal,
            "partition_ordinal": self.partition_ordinal,
            "prior_row_root_sha256": self.prior_row_root_sha256,
            "row_count": self.row_count,
            "row_root_sha256": self.row_root_sha256,
            "rows": [row.to_dict() for row in self.rows],
            "start_ordinal": self.start_ordinal,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(
            self.to_dict(),
            maximum=MAX_SUCCESSOR_PLANNING_PARTITION_BYTES,
            maximum_nodes=_MAX_PARTITION_NODES,
        )

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    @property
    def row_fold(self) -> OrderedSha256PrefixFoldV1:
        """Return the exact cumulative fold state closed by this partition."""

        return OrderedSha256PrefixFoldV1(
            domain=_ROW_FOLD_DOMAIN,
            count=self.end_ordinal + 1,
            root_sha256=self.row_root_sha256,
        )

    @classmethod
    def from_canonical_bytes(cls, raw: object) -> Self:
        if cls is not SuccessorPlanningRouteDispatchPartitionV1:
            _fail("route-dispatch partition subclasses are forbidden")
        payload = _mapping(
            _decode(
                raw,
                maximum=MAX_SUCCESSOR_PLANNING_PARTITION_BYTES,
                maximum_nodes=_MAX_PARTITION_NODES,
                label="route-dispatch partition",
            ),
            label="route-dispatch partition",
        )
        expected = frozenset(
            {
                "schema_version",
                "kind",
                "end_ordinal",
                "partition_ordinal",
                "prior_row_root_sha256",
                "row_count",
                "row_root_sha256",
                "rows",
                "start_ordinal",
            }
        )
        _exact_keys(payload, expected, label="route-dispatch partition")
        if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
            _fail("route-dispatch partition schema version is invalid")
        if type(payload["kind"]) is not str or payload["kind"] != cls.kind:
            _fail("route-dispatch partition kind is invalid")
        raw_rows = payload["rows"]
        if (
            type(raw_rows) is not list
            or not 1 <= len(raw_rows) <= MAX_SUCCESSOR_PLANNING_PARTITION_ROWS
        ):
            _fail("route-dispatch partition row inventory is invalid")
        rows = tuple(SuccessorPlanningRouteDispatchRowV1._from_payload(row) for row in raw_rows)
        partition = cls(
            partition_ordinal=cast("int", payload["partition_ordinal"]),
            start_ordinal=cast("int", payload["start_ordinal"]),
            end_ordinal=cast("int", payload["end_ordinal"]),
            prior_row_root_sha256=cast("str", payload["prior_row_root_sha256"]),
            rows=rows,
            row_count=cast("int", payload["row_count"]),
            row_root_sha256=cast("str", payload["row_root_sha256"]),
        )
        if raw != partition.canonical_bytes():
            _fail("route-dispatch partition bytes differ from exact replay")
        return partition


@dataclass(frozen=True, slots=True)
class SuccessorPlanningPartitionDescriptorV1:
    """Compact immutable binding for one partition and its fold transition."""

    partition_ordinal: int
    start_ordinal: int
    end_ordinal: int
    row_count: int
    canonical_byte_length: int
    content_sha256: str
    prior_row_root_sha256: str
    row_root_sha256: str

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "successor_planning_partition_descriptor_v1"

    def __post_init__(self) -> None:
        if type(self) is not SuccessorPlanningPartitionDescriptorV1:
            _fail("planning partition descriptor subclasses are forbidden")
        _count(
            self.partition_ordinal,
            label="partition_ordinal",
            maximum=MAX_SUCCESSOR_PLANNING_PARTITION_DESCRIPTORS - 1,
        )
        start = _count(
            self.start_ordinal, label="start_ordinal", maximum=MAX_SUCCESSOR_PLANNING_PLAN_ROWS - 1
        )
        end = _count(
            self.end_ordinal, label="end_ordinal", maximum=MAX_SUCCESSOR_PLANNING_PLAN_ROWS - 1
        )
        count = _count(
            self.row_count,
            label="row_count",
            positive=True,
            maximum=MAX_SUCCESSOR_PLANNING_PARTITION_ROWS,
        )
        _count(
            self.canonical_byte_length,
            label="canonical_byte_length",
            positive=True,
            maximum=MAX_SUCCESSOR_PLANNING_PARTITION_BYTES,
        )
        _sha256(self.content_sha256, label="content_sha256")
        _sha256(self.prior_row_root_sha256, label="prior_row_root_sha256")
        _sha256(self.row_root_sha256, label="row_root_sha256")
        if end != start + count - 1:
            _fail("descriptor ordinal range differs from its row count")

    def __init_subclass__(cls, **_kwargs: object) -> Never:
        _fail("planning partition descriptor subclasses are forbidden")

    @classmethod
    def from_partition(cls, partition: SuccessorPlanningRouteDispatchPartitionV1) -> Self:
        if cls is not SuccessorPlanningPartitionDescriptorV1 or type(partition) is not (
            SuccessorPlanningRouteDispatchPartitionV1
        ):
            _fail("descriptor construction requires one exact planning partition")
        raw = partition.canonical_bytes()
        return cls(
            partition_ordinal=partition.partition_ordinal,
            start_ordinal=partition.start_ordinal,
            end_ordinal=partition.end_ordinal,
            row_count=partition.row_count,
            canonical_byte_length=len(raw),
            content_sha256=hashlib.sha256(raw).hexdigest(),
            prior_row_root_sha256=partition.prior_row_root_sha256,
            row_root_sha256=partition.row_root_sha256,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "canonical_byte_length": self.canonical_byte_length,
            "content_sha256": self.content_sha256,
            "end_ordinal": self.end_ordinal,
            "partition_ordinal": self.partition_ordinal,
            "prior_row_root_sha256": self.prior_row_root_sha256,
            "row_count": self.row_count,
            "row_root_sha256": self.row_root_sha256,
            "start_ordinal": self.start_ordinal,
        }

    @classmethod
    def _from_payload(cls, value: object) -> Self:
        payload = _mapping(value, label="planning partition descriptor")
        expected = frozenset(
            {
                "schema_version",
                "kind",
                "canonical_byte_length",
                "content_sha256",
                "end_ordinal",
                "partition_ordinal",
                "prior_row_root_sha256",
                "row_count",
                "row_root_sha256",
                "start_ordinal",
            }
        )
        _exact_keys(payload, expected, label="planning partition descriptor")
        if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
            _fail("planning partition descriptor schema version is invalid")
        if type(payload["kind"]) is not str or payload["kind"] != cls.kind:
            _fail("planning partition descriptor kind is invalid")
        return cls(
            partition_ordinal=cast("int", payload["partition_ordinal"]),
            start_ordinal=cast("int", payload["start_ordinal"]),
            end_ordinal=cast("int", payload["end_ordinal"]),
            row_count=cast("int", payload["row_count"]),
            canonical_byte_length=cast("int", payload["canonical_byte_length"]),
            content_sha256=cast("str", payload["content_sha256"]),
            prior_row_root_sha256=cast("str", payload["prior_row_root_sha256"]),
            row_root_sha256=cast("str", payload["row_root_sha256"]),
        )


@dataclass(frozen=True, slots=True)
class SuccessorPlanningPartitionHeaderV1:
    """Compact exact plan-wide row root plus at most twenty-five descriptors."""

    total_row_count: int
    total_row_root_sha256: str
    descriptors: tuple[SuccessorPlanningPartitionDescriptorV1, ...]
    descriptor_count: int
    header_sha256: str = field(init=False)

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "successor_planning_partition_header_v1"

    def __post_init__(self) -> None:
        if type(self) is not SuccessorPlanningPartitionHeaderV1:
            _fail("planning partition header subclasses are forbidden")
        total = _count(
            self.total_row_count,
            label="total_row_count",
            positive=True,
            maximum=MAX_SUCCESSOR_PLANNING_PLAN_ROWS,
        )
        _sha256(self.total_row_root_sha256, label="total_row_root_sha256")
        descriptor_count = _count(
            self.descriptor_count,
            label="descriptor_count",
            positive=True,
            maximum=MAX_SUCCESSOR_PLANNING_PARTITION_DESCRIPTORS,
        )
        if (
            type(self.descriptors) is not tuple
            or len(self.descriptors) != descriptor_count
            or any(
                type(item) is not SuccessorPlanningPartitionDescriptorV1
                for item in self.descriptors
            )
        ):
            _fail("header descriptors differ from their exact denominator")
        empty = empty_ordered_sha256_prefix_fold(domain=_ROW_FOLD_DOMAIN)
        expected_start = 0
        expected_prior_root = empty.root_sha256
        for ordinal, descriptor in enumerate(self.descriptors):
            if (
                descriptor.partition_ordinal != ordinal
                or descriptor.start_ordinal != expected_start
                or descriptor.prior_row_root_sha256 != expected_prior_root
            ):
                _fail("header descriptors are reordered, overlapping, gapped, or cross-chained")
            expected_start = descriptor.end_ordinal + 1
            expected_prior_root = descriptor.row_root_sha256
        if expected_start != total or expected_prior_root != self.total_row_root_sha256:
            _fail("header total row count/root differs from its descriptor chain")
        object.__setattr__(self, "header_sha256", hashlib.sha256(self.identity_bytes()).hexdigest())

    def __init_subclass__(cls, **_kwargs: object) -> Never:
        _fail("planning partition header subclasses are forbidden")

    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "descriptor_count": self.descriptor_count,
            "descriptors": [descriptor.to_dict() for descriptor in self.descriptors],
            "total_row_count": self.total_row_count,
            "total_row_root_sha256": self.total_row_root_sha256,
        }

    def identity_bytes(self) -> bytes:
        return _canonical_bytes(
            self.identity_payload(), maximum=_MAX_HEADER_BYTES, maximum_nodes=_MAX_HEADER_NODES
        )

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload(), "header_sha256": self.header_sha256}

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(
            self.to_dict(), maximum=_MAX_HEADER_BYTES, maximum_nodes=_MAX_HEADER_NODES
        )

    @classmethod
    def from_canonical_bytes(cls, raw: object) -> Self:
        if cls is not SuccessorPlanningPartitionHeaderV1:
            _fail("planning partition header subclasses are forbidden")
        payload = _mapping(
            _decode(
                raw,
                maximum=_MAX_HEADER_BYTES,
                maximum_nodes=_MAX_HEADER_NODES,
                label="planning partition header",
            ),
            label="planning partition header",
        )
        expected = frozenset(
            {
                "schema_version",
                "kind",
                "descriptor_count",
                "descriptors",
                "header_sha256",
                "total_row_count",
                "total_row_root_sha256",
            }
        )
        _exact_keys(payload, expected, label="planning partition header")
        if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
            _fail("planning partition header schema version is invalid")
        if type(payload["kind"]) is not str or payload["kind"] != cls.kind:
            _fail("planning partition header kind is invalid")
        raw_descriptors = payload["descriptors"]
        if type(raw_descriptors) is not list:
            _fail("planning partition header descriptors must be one exact array")
        header = cls(
            total_row_count=cast("int", payload["total_row_count"]),
            total_row_root_sha256=cast("str", payload["total_row_root_sha256"]),
            descriptors=tuple(
                SuccessorPlanningPartitionDescriptorV1._from_payload(item)
                for item in raw_descriptors
            ),
            descriptor_count=cast("int", payload["descriptor_count"]),
        )
        if header.header_sha256 != _sha256(payload["header_sha256"], label="header_sha256"):
            _fail("planning partition header digest differs")
        if raw != header.canonical_bytes():
            _fail("planning partition header bytes differ from exact replay")
        return header


def build_successor_planning_partition_header(
    partitions: object,
) -> SuccessorPlanningPartitionHeaderV1:
    """Build one compact header while retaining only its descriptor tuple."""

    if type(partitions) in {str, bytes, bytearray, memoryview}:
        _fail("planning partitions must be one iterable of exact partitions")
    try:
        iterator = iter(cast("Iterable[object]", partitions))
    except TypeError:
        _fail("planning partitions must be one iterable of exact partitions")
    descriptors: list[SuccessorPlanningPartitionDescriptorV1] = []
    for partition in iterator:
        if type(partition) is not SuccessorPlanningRouteDispatchPartitionV1:
            _fail("planning partition inventory contains a foreign value")
        descriptors.append(SuccessorPlanningPartitionDescriptorV1.from_partition(partition))
        if len(descriptors) > MAX_SUCCESSOR_PLANNING_PARTITION_DESCRIPTORS:
            _fail("planning partition descriptor inventory exceeds its exact bound")
    if not descriptors:
        _fail("planning partition descriptor inventory must be nonempty")
    final = descriptors[-1]
    return SuccessorPlanningPartitionHeaderV1(
        total_row_count=final.end_ordinal + 1,
        total_row_root_sha256=final.row_root_sha256,
        descriptors=tuple(descriptors),
        descriptor_count=len(descriptors),
    )


def empty_successor_planning_row_fold() -> OrderedSha256PrefixFoldV1:
    """Return the exact initial fold state for the first planning partition."""

    return empty_ordered_sha256_prefix_fold(domain=_ROW_FOLD_DOMAIN)


def iter_verified_successor_planning_rows(
    header: SuccessorPlanningPartitionHeaderV1,
    partition_byte_loader: SuccessorPlanningPartitionByteLoader,
) -> Iterator[SuccessorPlanningRouteDispatchRowV1]:
    """Strict-replay descriptor-selected partitions and yield their exact rows."""

    if type(header) is not SuccessorPlanningPartitionHeaderV1:
        _fail("streaming verification requires one exact planning partition header")
    if not callable(partition_byte_loader):
        _fail("streaming verification requires one exact partition-byte loader")
    state = empty_ordered_sha256_prefix_fold(domain=_ROW_FOLD_DOMAIN)
    for descriptor in header.descriptors:
        try:
            raw = partition_byte_loader(descriptor)
        except LookupError as exc:
            raise SuccessorPlanningPartitionAuthorityError(
                "partition-byte loader omitted one exact descriptor"
            ) from exc
        if type(raw) is not bytes:
            _fail("partition-byte loader returned a foreign exact type")
        if len(raw) != descriptor.canonical_byte_length:
            _fail("loaded partition byte length differs from its descriptor")
        if hashlib.sha256(raw).hexdigest() != descriptor.content_sha256:
            _fail("loaded partition content digest differs from its descriptor")
        partition = SuccessorPlanningRouteDispatchPartitionV1.from_canonical_bytes(raw)
        if SuccessorPlanningPartitionDescriptorV1.from_partition(partition) != descriptor:
            _fail("loaded partition differs from its exact descriptor")
        if (
            partition.start_ordinal != state.count
            or partition.prior_row_root_sha256 != state.root_sha256
        ):
            _fail("loaded partition crosses the verified row-prefix state")
        try:
            state = extend_ordered_sha256_prefix_fold(
                domain=_ROW_FOLD_DOMAIN,
                prior_count=state.count,
                prior_root_sha256=state.root_sha256,
                appended_count=partition.row_count,
                item_sha256s=(row.row_sha256 for row in partition.rows),
            )
        except ValueError as exc:
            raise SuccessorPlanningPartitionAuthorityError(
                "loaded partition cannot extend the verified row fold"
            ) from exc
        if state.root_sha256 != descriptor.row_root_sha256:
            _fail("loaded partition row root differs from its descriptor")
        yield from partition.rows
    if state.count != header.total_row_count or state.root_sha256 != header.total_row_root_sha256:
        _fail("loaded partition stream differs from the exact header total")


# Import-time closure proves the empty/root implementation uses the shared fold.
_EMPTY_ROW_FOLD: Final = compute_ordered_sha256_prefix_fold(
    domain=_ROW_FOLD_DOMAIN, count=0, item_sha256s=()
)
if empty_ordered_sha256_prefix_fold(domain=_ROW_FOLD_DOMAIN) != _EMPTY_ROW_FOLD:
    raise RuntimeError("successor planning row-fold contract is inconsistent")
