"""Strict path-free semantic authority for successor-planning members.

This module describes what one normalized planning member means without
embedding database paths or a generation-wide flattened value inventory.  A
descriptor binds one exact semantic partition to independently measured schema
and content identities; the compiler/runtime remains responsible for reading
and revalidating that partition from the planning database.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import ClassVar, Self, cast

from nbadb.orchestrate.successor_update_contract import canonical_json_bytes, canonical_sha256

__all__ = [
    "SUCCESSOR_PLANNING_SEMANTIC_SCHEMA_VERSION",
    "PlanningSemanticDescriptor",
    "PlanningSemanticKind",
    "SuccessorPlanningSemanticContractError",
]

SUCCESSOR_PLANNING_SEMANTIC_SCHEMA_VERSION = 1

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SEASON_RE = re.compile(r"[0-9]{4}-[0-9]{2}")
_UTC_INSTANT_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_SEASON_TYPE_RE = re.compile(r"[A-Za-z][A-Za-z ]{0,63}")
_REASON_RE = re.compile(r"[a-z0-9][a-z0-9_]{0,127}")

type _PartitionScalar = str | int | bool
type _PartitionItems = tuple[tuple[str, _PartitionScalar], ...]


class SuccessorPlanningSemanticContractError(ValueError):
    """Raised when planning-member semantic authority is unsafe or ambiguous."""


class PlanningSemanticKind(StrEnum):
    """Closed partition-local value semantics admitted by successor planning."""

    GAME_DATE_INDEX = "game_date_index"
    SEASON_PLAYER_UNIVERSE = "season_player_universe"
    SEASON_TEAM_UNIVERSE = "season_team_universe"
    CURRENT_TEAM_UNIVERSE = "current_team_universe"
    PLAYER_TEAM_SEASON_AFFILIATION = "player_team_season_affiliation"
    ACTIVE_LIVE_GAME_IDS = "active_live_game_ids"
    PLAYER_CUME_FOUNDATION_GAME_IDS = "player_cume_foundation_game_ids"
    TEAM_CUME_FOUNDATION_GAME_IDS = "team_cume_foundation_game_ids"
    AUXILIARY_NO_DERIVED_DATA = "auxiliary_no_derived_data"


_PARTITION_KEYS: dict[PlanningSemanticKind, frozenset[str]] = {
    PlanningSemanticKind.GAME_DATE_INDEX: frozenset({"season", "season_type"}),
    PlanningSemanticKind.SEASON_PLAYER_UNIVERSE: frozenset({"current_only", "season"}),
    PlanningSemanticKind.SEASON_TEAM_UNIVERSE: frozenset({"season"}),
    PlanningSemanticKind.CURRENT_TEAM_UNIVERSE: frozenset({"as_of_utc"}),
    PlanningSemanticKind.PLAYER_TEAM_SEASON_AFFILIATION: frozenset({"season", "season_type"}),
    PlanningSemanticKind.ACTIVE_LIVE_GAME_IDS: frozenset({"as_of_utc"}),
    PlanningSemanticKind.PLAYER_CUME_FOUNDATION_GAME_IDS: frozenset(
        {"player_id", "season", "season_type"}
    ),
    PlanningSemanticKind.TEAM_CUME_FOUNDATION_GAME_IDS: frozenset(
        {"season", "season_type", "team_id"}
    ),
    PlanningSemanticKind.AUXILIARY_NO_DERIVED_DATA: frozenset(),
}


def _require_sha256(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise SuccessorPlanningSemanticContractError(f"{field_name} must be a lowercase SHA-256")
    return value


def _require_nonnegative_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise SuccessorPlanningSemanticContractError(f"{field_name} must be a nonnegative integer")
    return value


def _require_mapping(value: object, *, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise SuccessorPlanningSemanticContractError(
            f"{field_name} must be an object with string keys"
        )
    return cast("Mapping[str, object]", value)


def _require_exact_keys(
    payload: Mapping[str, object],
    *,
    expected: frozenset[str],
    label: str,
) -> None:
    actual = frozenset(payload)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    details: list[str] = []
    if missing:
        details.append("missing=" + ",".join(missing))
    if unexpected:
        details.append("unexpected=" + ",".join(unexpected))
    raise SuccessorPlanningSemanticContractError(
        f"{label} fields are invalid: {'; '.join(details)}"
    )


def _validate_season(value: object) -> str:
    if not isinstance(value, str) or _SEASON_RE.fullmatch(value) is None:
        raise SuccessorPlanningSemanticContractError(
            "semantic partition season must use exact ASCII YYYY-YY"
        )
    start = int(value[:4])
    if int(value[-2:]) != (start + 1) % 100:
        raise SuccessorPlanningSemanticContractError(
            "semantic partition season must be consecutive"
        )
    return value


def _validate_season_type(value: object) -> str:
    if not isinstance(value, str) or _SEASON_TYPE_RE.fullmatch(value) is None:
        raise SuccessorPlanningSemanticContractError(
            "semantic partition season_type must be a path-free canonical label"
        )
    return value


def _validate_as_of_utc(value: object) -> str:
    if not isinstance(value, str) or _UTC_INSTANT_RE.fullmatch(value) is None:
        raise SuccessorPlanningSemanticContractError(
            "semantic partition as_of_utc must use canonical UTC seconds"
        )
    # The lexical shape is not enough: reject impossible calendar values while
    # retaining a dependency-free, timezone-unambiguous wire representation.
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise SuccessorPlanningSemanticContractError(
            "semantic partition as_of_utc must use canonical UTC seconds"
        ) from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise SuccessorPlanningSemanticContractError(
            "semantic partition as_of_utc must use canonical UTC seconds"
        )
    return value


def _validate_positive_id(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise SuccessorPlanningSemanticContractError(
            f"semantic partition {field_name} must be a positive integer"
        )
    return value


def _validate_partition_value(key: str, value: object) -> _PartitionScalar:
    if key == "season":
        return _validate_season(value)
    if key == "season_type":
        return _validate_season_type(value)
    if key == "as_of_utc":
        return _validate_as_of_utc(value)
    if key in {"player_id", "team_id"}:
        return _validate_positive_id(value, field_name=key)
    if key == "current_only":
        if type(value) is not bool:
            raise SuccessorPlanningSemanticContractError(
                "semantic partition current_only must be a boolean"
            )
        return value
    raise SuccessorPlanningSemanticContractError(f"semantic partition key {key!r} is not admitted")


def _freeze_partition(
    semantic_kind: PlanningSemanticKind,
    partition: Mapping[str, object],
) -> _PartitionItems:
    expected = _PARTITION_KEYS[semantic_kind]
    _require_exact_keys(partition, expected=expected, label=f"{semantic_kind.value} partition")
    return tuple((key, _validate_partition_value(key, partition[key])) for key in sorted(partition))


def _partition_from_dict(value: object) -> Mapping[str, object]:
    return _require_mapping(value, field_name="semantic partition")


@dataclass(frozen=True, slots=True)
class PlanningSemanticDescriptor:
    """Partition-local schema/content authority for one planning member.

    ``semantic_content_sha256`` binds the canonical typed values in exactly
    this partition.  Values are intentionally absent from the descriptor: a
    later compiler must read the independently attested planning database and
    recompute the partition digest rather than trusting a global ID list.
    """

    semantic_kind: PlanningSemanticKind
    partition_items: _PartitionItems
    semantic_schema_sha256: str
    semantic_content_sha256: str
    value_count: int
    typed_zero_reason_code: str | None = None

    schema_version: ClassVar[int] = SUCCESSOR_PLANNING_SEMANTIC_SCHEMA_VERSION
    kind: ClassVar[str] = "planning_semantic_descriptor"

    def __post_init__(self) -> None:
        if not isinstance(self.semantic_kind, PlanningSemanticKind):
            raise SuccessorPlanningSemanticContractError(
                "semantic_kind must be a PlanningSemanticKind"
            )
        if type(self.partition_items) is not tuple or any(
            type(item) is not tuple or len(item) != 2 or not isinstance(item[0], str)
            for item in self.partition_items
        ):
            raise SuccessorPlanningSemanticContractError(
                "partition_items must be an immutable key/value tuple inventory"
            )
        partition = dict(self.partition_items)
        if len(partition) != len(self.partition_items):
            raise SuccessorPlanningSemanticContractError(
                "semantic partition contains duplicate keys"
            )
        canonical = _freeze_partition(self.semantic_kind, partition)
        if self.partition_items != canonical:
            raise SuccessorPlanningSemanticContractError(
                "semantic partition keys must use canonical sorted order"
            )
        _require_sha256(
            self.semantic_schema_sha256,
            field_name="semantic_schema_sha256",
        )
        _require_sha256(
            self.semantic_content_sha256,
            field_name="semantic_content_sha256",
        )
        _require_nonnegative_int(self.value_count, field_name="value_count")
        if self.value_count == 0:
            if (
                not isinstance(self.typed_zero_reason_code, str)
                or _REASON_RE.fullmatch(self.typed_zero_reason_code) is None
            ):
                raise SuccessorPlanningSemanticContractError(
                    "zero-value semantic descriptors require a typed-zero reason"
                )
        elif self.typed_zero_reason_code is not None:
            raise SuccessorPlanningSemanticContractError(
                "nonempty semantic descriptors cannot claim typed zero"
            )

    @classmethod
    def from_partition(
        cls,
        *,
        semantic_kind: PlanningSemanticKind,
        partition: Mapping[str, object],
        semantic_schema_sha256: str,
        semantic_content_sha256: str,
        value_count: int,
        typed_zero_reason_code: str | None = None,
    ) -> Self:
        if not isinstance(semantic_kind, PlanningSemanticKind):
            raise SuccessorPlanningSemanticContractError(
                "semantic_kind must be a PlanningSemanticKind"
            )
        if not isinstance(partition, Mapping):
            raise SuccessorPlanningSemanticContractError("semantic partition must be a mapping")
        return cls(
            semantic_kind=semantic_kind,
            partition_items=_freeze_partition(semantic_kind, partition),
            semantic_schema_sha256=semantic_schema_sha256,
            semantic_content_sha256=semantic_content_sha256,
            value_count=value_count,
            typed_zero_reason_code=typed_zero_reason_code,
        )

    @property
    def partition(self) -> dict[str, _PartitionScalar]:
        """Return a detached canonical semantic partition mapping."""

        return dict(self.partition_items)

    @property
    def identity_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "semantic_kind": self.semantic_kind.value,
            "partition": self.partition,
            "semantic_schema_sha256": self.semantic_schema_sha256,
            "semantic_content_sha256": self.semantic_content_sha256,
            "value_count": self.value_count,
            "typed_zero_reason_code": self.typed_zero_reason_code,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "semantic_kind",
                    "partition",
                    "semantic_schema_sha256",
                    "semantic_content_sha256",
                    "value_count",
                    "typed_zero_reason_code",
                }
            ),
            label="planning semantic descriptor",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise SuccessorPlanningSemanticContractError(
                "planning semantic descriptor schema is invalid"
            )
        try:
            semantic_kind = PlanningSemanticKind(payload["semantic_kind"])
        except (TypeError, ValueError) as exc:
            raise SuccessorPlanningSemanticContractError(
                "planning semantic kind is invalid"
            ) from exc
        reason = payload["typed_zero_reason_code"]
        if reason is not None and not isinstance(reason, str):
            raise SuccessorPlanningSemanticContractError(
                "typed_zero_reason_code must be a string or null"
            )
        return cls.from_partition(
            semantic_kind=semantic_kind,
            partition=_partition_from_dict(payload["partition"]),
            semantic_schema_sha256=_require_sha256(
                payload["semantic_schema_sha256"],
                field_name="semantic_schema_sha256",
            ),
            semantic_content_sha256=_require_sha256(
                payload["semantic_content_sha256"],
                field_name="semantic_content_sha256",
            ),
            value_count=_require_nonnegative_int(payload["value_count"], field_name="value_count"),
            typed_zero_reason_code=reason,
        )

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> Self:
        """Decode only exact current-schema canonical UTF-8 JSON bytes."""

        if type(encoded) is not bytes:
            raise SuccessorPlanningSemanticContractError(
                "planning semantic descriptor encoding must be bytes"
            )

        def reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise SuccessorPlanningSemanticContractError(
                        f"planning semantic descriptor contains duplicate key {key!r}"
                    )
                result[key] = value
            return result

        def reject_constant(value: str) -> object:
            raise SuccessorPlanningSemanticContractError(
                f"planning semantic descriptor contains non-finite JSON value {value}"
            )

        try:
            decoded = json.loads(
                encoded.decode("utf-8", errors="strict"),
                object_pairs_hook=reject_duplicate_pairs,
                parse_constant=reject_constant,
            )
        except SuccessorPlanningSemanticContractError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise SuccessorPlanningSemanticContractError(
                "planning semantic descriptor is not strict UTF-8 JSON"
            ) from exc
        payload = _require_mapping(decoded, field_name="planning semantic descriptor")
        try:
            canonical = canonical_json_bytes(payload)
        except (TypeError, ValueError, RecursionError) as exc:
            raise SuccessorPlanningSemanticContractError(
                "planning semantic descriptor contains invalid JSON values"
            ) from exc
        if canonical != encoded:
            raise SuccessorPlanningSemanticContractError(
                "planning semantic descriptor bytes are not canonical"
            )
        result = cls.from_dict(payload)
        if result.canonical_bytes != encoded:
            raise SuccessorPlanningSemanticContractError(
                "planning semantic descriptor canonical bytes differ"
            )
        return result
