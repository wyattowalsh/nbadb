"""Strict value contracts for one durable successor-planning generation.

The values in this module are deliberately path-free.  They bind already
measured private planning artifacts and a sealed executable dispatch inventory;
they do not create storage, call a provider, or authorize production use.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Any, ClassVar, Self, cast

from nbadb.extract.bronze import (
    canonical_parameters_payload,
    canonical_parameters_sha256,
)
from nbadb.orchestrate.successor_planning_contract import SuccessorPlanningRequest
from nbadb.orchestrate.successor_planning_semantic_contract import (
    PlanningSemanticDescriptor,
    SuccessorPlanningSemanticContractError,
)
from nbadb.orchestrate.successor_update_contract import (
    SUCCESSOR_UPDATE_CONTRACT_SCHEMA_VERSION,
    CallMutability,
    RequestedRouteScope,
    SuccessorUpdateContractError,
    canonical_json_bytes,
    canonical_sha256,
)

__all__ = [
    "SUCCESSOR_PLANNING_GENERATION_SCHEMA_VERSION",
    "PlanningDataMember",
    "PlanningDispatchPhase",
    "PlanningGenerationManifest",
    "PlanningGenerationPublicIdentity",
    "SealedProviderDispatch",
    "SuccessorPlanningArtifactIdentity",
    "SuccessorPlanningGenerationContractError",
    "SuccessorPlanningWave",
    "canonical_planning_json_bytes",
    "canonical_planning_sha256",
]

SUCCESSOR_PLANNING_GENERATION_SCHEMA_VERSION = 2

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SAFE_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}")
_REASON_RE = re.compile(r"[a-z0-9][a-z0-9_]{0,127}")
_PATH_PARAMETER_KEY_RE = re.compile(
    r"(?:^|_)(?:cwd|dir|directory|file|filename|home|path|root)(?:$|_)",
    re.IGNORECASE,
)
_PATH_VALUE_RE = re.compile(r"(?:^[/~\\]|^\.\.?[/\\]|^[A-Za-z]:[/\\]|://|\\)")

type _ParameterScalar = str | int | float | bool | None
type _FrozenParameterValue = _ParameterScalar | tuple[_ParameterScalar, ...]
type _FrozenParameterItems = tuple[tuple[str, _FrozenParameterValue], ...]


class SuccessorPlanningGenerationContractError(ValueError):
    """Raised when durable planning authority is unsafe or inconsistent."""


class PlanningDispatchPhase(StrEnum):
    """Closed execution phases admitted by a sealed planning manifest."""

    PLANNING_WAVE_0 = "planning_wave_0"
    PLANNING_WAVE_1 = "planning_wave_1"
    UPDATE = "update"


def canonical_planning_json_bytes(payload: object) -> bytes:
    """Return the sole canonical JSON representation admitted by this contract."""

    return canonical_json_bytes(payload)


def canonical_planning_sha256(payload: object) -> str:
    """Return a digest over :func:`canonical_planning_json_bytes`."""

    return canonical_sha256(payload)


def _require_sha256(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise SuccessorPlanningGenerationContractError(f"{field_name} must be a lowercase SHA-256")
    return value


def _require_token(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SAFE_TOKEN_RE.fullmatch(value) is None:
        raise SuccessorPlanningGenerationContractError(
            f"{field_name} must be an exact path-free safe token"
        )
    return value


def _require_nonnegative_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise SuccessorPlanningGenerationContractError(
            f"{field_name} must be a nonnegative integer"
        )
    return value


def _require_positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise SuccessorPlanningGenerationContractError(f"{field_name} must be a positive integer")
    return value


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
    raise SuccessorPlanningGenerationContractError(
        f"{label} fields are invalid: {'; '.join(details)}"
    )


def _require_mapping(value: object, *, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise SuccessorPlanningGenerationContractError(
            f"{field_name} must be an object with string keys"
        )
    return cast("Mapping[str, object]", value)


def _require_list(value: object, *, field_name: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise SuccessorPlanningGenerationContractError(f"{field_name} must be a list")
    return value


def _require_sha256_tuple(
    values: object,
    *,
    field_name: str,
    nonempty: bool = True,
    unique: bool = True,
    sorted_values: bool = True,
) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise SuccessorPlanningGenerationContractError(f"{field_name} must be an immutable tuple")
    result = tuple(_require_sha256(value, field_name=field_name) for value in values)
    if nonempty and not result:
        raise SuccessorPlanningGenerationContractError(f"{field_name} must be nonempty")
    if unique and len(result) != len(set(result)):
        raise SuccessorPlanningGenerationContractError(f"{field_name} contains duplicates")
    if sorted_values and result != tuple(sorted(result)):
        raise SuccessorPlanningGenerationContractError(
            f"{field_name} must use canonical sorted order"
        )
    return result


def _sha256_tuple_from_list(value: object, *, field_name: str) -> tuple[str, ...]:
    return tuple(
        _require_sha256(item, field_name=field_name)
        for item in _require_list(value, field_name=field_name)
    )


def _parse_current_schema(
    payload: Mapping[str, object],
    *,
    kind: str,
    label: str,
) -> None:
    if (
        type(payload.get("schema_version")) is not int
        or payload.get("schema_version") != SUCCESSOR_PLANNING_GENERATION_SCHEMA_VERSION
        or payload.get("kind") != kind
    ):
        raise SuccessorPlanningGenerationContractError(f"{label} schema is invalid")


def _reject_path_parameters(parameters: Mapping[str, Any]) -> None:
    for key, raw_value in parameters.items():
        if _PATH_PARAMETER_KEY_RE.search(key):
            raise SuccessorPlanningGenerationContractError(
                f"dispatch parameter {key!r} is path-bearing"
            )
        values = raw_value if isinstance(raw_value, list) else [raw_value]
        if any(isinstance(value, str) and _PATH_VALUE_RE.search(value) for value in values):
            raise SuccessorPlanningGenerationContractError(
                f"dispatch parameter {key!r} contains a path or URI"
            )


def _freeze_parameters(parameters: Mapping[str, Any]) -> _FrozenParameterItems:
    return tuple(
        (
            key,
            tuple(value) if isinstance(value, list) else cast("_ParameterScalar", value),
        )
        for key, value in parameters.items()
    )


def _thaw_parameters(items: _FrozenParameterItems) -> dict[str, Any]:
    return {key: list(value) if isinstance(value, tuple) else value for key, value in items}


def _canonical_parameter_items(parameters: Mapping[str, Any]) -> _FrozenParameterItems:
    try:
        canonical = canonical_parameters_payload(parameters)
    except (TypeError, ValueError) as exc:
        raise SuccessorPlanningGenerationContractError(
            f"dispatch parameters are invalid: {exc}"
        ) from exc
    _reject_path_parameters(canonical)
    return _freeze_parameters(canonical)


@dataclass(frozen=True, slots=True)
class SuccessorPlanningArtifactIdentity:
    """Path-free identity of all durable bytes for one planning generation."""

    planning_request_sha256: str
    planning_generation_id: str
    planning_database_sha256: str
    planning_database_bytes: int
    planning_database_schema_sha256: str
    member_inventory_sha256: str
    private_generation_identity_sha256: str
    wave_inventory_sha256: str
    planning_manifest_sha256: str
    sealed_dispatch_inventory_sha256: str

    schema_version: ClassVar[int] = SUCCESSOR_PLANNING_GENERATION_SCHEMA_VERSION
    kind: ClassVar[str] = "successor_planning_artifact_identity"

    def __post_init__(self) -> None:
        _require_token(self.planning_generation_id, field_name="planning_generation_id")
        _require_positive_int(
            self.planning_database_bytes,
            field_name="planning_database_bytes",
        )
        for field_name in (
            "planning_request_sha256",
            "planning_database_sha256",
            "planning_database_schema_sha256",
            "member_inventory_sha256",
            "private_generation_identity_sha256",
            "wave_inventory_sha256",
            "planning_manifest_sha256",
            "sealed_dispatch_inventory_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)

    @property
    def identity_sha256(self) -> str:
        return canonical_planning_sha256(self.to_dict())

    def to_dict(self) -> dict[str, str | int]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "planning_request_sha256": self.planning_request_sha256,
            "planning_generation_id": self.planning_generation_id,
            "planning_database_sha256": self.planning_database_sha256,
            "planning_database_bytes": self.planning_database_bytes,
            "planning_database_schema_sha256": self.planning_database_schema_sha256,
            "member_inventory_sha256": self.member_inventory_sha256,
            "private_generation_identity_sha256": self.private_generation_identity_sha256,
            "wave_inventory_sha256": self.wave_inventory_sha256,
            "planning_manifest_sha256": self.planning_manifest_sha256,
            "sealed_dispatch_inventory_sha256": self.sealed_dispatch_inventory_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "schema_version",
                "kind",
                "planning_request_sha256",
                "planning_generation_id",
                "planning_database_sha256",
                "planning_database_bytes",
                "planning_database_schema_sha256",
                "member_inventory_sha256",
                "private_generation_identity_sha256",
                "wave_inventory_sha256",
                "planning_manifest_sha256",
                "sealed_dispatch_inventory_sha256",
            }
        )
        _require_exact_keys(payload, expected=expected, label="planning artifact identity")
        _parse_current_schema(payload, kind=cls.kind, label="planning artifact identity")
        return cls(
            planning_request_sha256=_require_sha256(
                payload["planning_request_sha256"], field_name="planning_request_sha256"
            ),
            planning_generation_id=_require_token(
                payload["planning_generation_id"], field_name="planning_generation_id"
            ),
            planning_database_sha256=_require_sha256(
                payload["planning_database_sha256"], field_name="planning_database_sha256"
            ),
            planning_database_bytes=_require_positive_int(
                payload["planning_database_bytes"], field_name="planning_database_bytes"
            ),
            planning_database_schema_sha256=_require_sha256(
                payload["planning_database_schema_sha256"],
                field_name="planning_database_schema_sha256",
            ),
            member_inventory_sha256=_require_sha256(
                payload["member_inventory_sha256"], field_name="member_inventory_sha256"
            ),
            private_generation_identity_sha256=_require_sha256(
                payload["private_generation_identity_sha256"],
                field_name="private_generation_identity_sha256",
            ),
            wave_inventory_sha256=_require_sha256(
                payload["wave_inventory_sha256"], field_name="wave_inventory_sha256"
            ),
            planning_manifest_sha256=_require_sha256(
                payload["planning_manifest_sha256"], field_name="planning_manifest_sha256"
            ),
            sealed_dispatch_inventory_sha256=_require_sha256(
                payload["sealed_dispatch_inventory_sha256"],
                field_name="sealed_dispatch_inventory_sha256",
            ),
        )


@dataclass(frozen=True, slots=True)
class PlanningDataMember:
    """One store artifact plus its partition-local semantic authority."""

    member_id: str
    wave_index: int
    producing_scope_sha256: str
    schema_sha256: str
    content_sha256: str
    row_count: int
    semantic: PlanningSemanticDescriptor
    typed_zero_reason_code: str | None = None

    schema_version: ClassVar[int] = SUCCESSOR_PLANNING_GENERATION_SCHEMA_VERSION
    kind: ClassVar[str] = "planning_data_member"

    def __post_init__(self) -> None:
        _require_token(self.member_id, field_name="member_id")
        if type(self.wave_index) is not int or self.wave_index not in {0, 1}:
            raise SuccessorPlanningGenerationContractError("wave_index must be exactly 0 or 1")
        for field_name in ("producing_scope_sha256", "schema_sha256", "content_sha256"):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        _require_nonnegative_int(self.row_count, field_name="row_count")
        if not isinstance(self.semantic, PlanningSemanticDescriptor):
            raise SuccessorPlanningGenerationContractError(
                "semantic must be a PlanningSemanticDescriptor"
            )
        if self.row_count == 0:
            if (
                not isinstance(self.typed_zero_reason_code, str)
                or _REASON_RE.fullmatch(self.typed_zero_reason_code) is None
            ):
                raise SuccessorPlanningGenerationContractError(
                    "zero-row planning members require a typed-zero reason"
                )
        elif self.typed_zero_reason_code is not None:
            raise SuccessorPlanningGenerationContractError(
                "nonempty planning members cannot claim typed zero"
            )
        if (
            self.semantic.value_count != self.row_count
            or self.semantic.typed_zero_reason_code != self.typed_zero_reason_code
        ):
            raise SuccessorPlanningGenerationContractError(
                "store member count or typed-zero disposition differs from semantic authority"
            )

    @property
    def identity_sha256(self) -> str:
        return canonical_planning_sha256(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "member_id": self.member_id,
            "wave_index": self.wave_index,
            "producing_scope_sha256": self.producing_scope_sha256,
            "schema_sha256": self.schema_sha256,
            "content_sha256": self.content_sha256,
            "row_count": self.row_count,
            "semantic": self.semantic.to_dict(),
            "typed_zero_reason_code": self.typed_zero_reason_code,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "schema_version",
                "kind",
                "member_id",
                "wave_index",
                "producing_scope_sha256",
                "schema_sha256",
                "content_sha256",
                "row_count",
                "semantic",
                "typed_zero_reason_code",
            }
        )
        _require_exact_keys(payload, expected=expected, label="planning data member")
        _parse_current_schema(payload, kind=cls.kind, label="planning data member")
        reason = payload["typed_zero_reason_code"]
        if reason is not None and not isinstance(reason, str):
            raise SuccessorPlanningGenerationContractError(
                "typed_zero_reason_code must be a string or null"
            )
        try:
            semantic = PlanningSemanticDescriptor.from_dict(
                _require_mapping(payload["semantic"], field_name="semantic")
            )
        except SuccessorPlanningSemanticContractError as exc:
            raise SuccessorPlanningGenerationContractError(
                f"planning data member semantic authority is invalid: {exc}"
            ) from exc
        return cls(
            member_id=_require_token(payload["member_id"], field_name="member_id"),
            wave_index=_require_nonnegative_int(payload["wave_index"], field_name="wave_index"),
            producing_scope_sha256=_require_sha256(
                payload["producing_scope_sha256"], field_name="producing_scope_sha256"
            ),
            schema_sha256=_require_sha256(payload["schema_sha256"], field_name="schema_sha256"),
            content_sha256=_require_sha256(payload["content_sha256"], field_name="content_sha256"),
            row_count=_require_nonnegative_int(payload["row_count"], field_name="row_count"),
            semantic=semantic,
            typed_zero_reason_code=reason,
        )


@dataclass(frozen=True, slots=True)
class SuccessorPlanningWave:
    """Immutable completion authority for one dependency-ordered planning wave."""

    wave_index: int
    parent_wave_identity_sha256: str | None
    requested_scope_identity_sha256s: tuple[str, ...]
    completed_scope_identity_sha256s: tuple[str, ...]
    member_identity_sha256s: tuple[str, ...]
    member_receipt_sha256s: tuple[str, ...]
    private_generation_identity_sha256: str
    completion_receipt_sha256: str
    requested_scopes_sha256: str = field(init=False)
    completed_scopes_sha256: str = field(init=False)
    member_inventory_sha256: str = field(init=False)
    member_receipts_sha256: str = field(init=False)

    schema_version: ClassVar[int] = SUCCESSOR_PLANNING_GENERATION_SCHEMA_VERSION
    kind: ClassVar[str] = "successor_planning_wave"

    def __post_init__(self) -> None:
        if type(self.wave_index) is not int or self.wave_index not in {0, 1}:
            raise SuccessorPlanningGenerationContractError("wave_index must be exactly 0 or 1")
        if self.wave_index == 0:
            if self.parent_wave_identity_sha256 is not None:
                raise SuccessorPlanningGenerationContractError("wave 0 cannot have a parent")
        elif self.parent_wave_identity_sha256 is None:
            raise SuccessorPlanningGenerationContractError("wave 1 requires its wave 0 parent")
        else:
            _require_sha256(
                self.parent_wave_identity_sha256,
                field_name="parent_wave_identity_sha256",
            )

        requested = _require_sha256_tuple(
            self.requested_scope_identity_sha256s,
            field_name="requested_scope_identity_sha256s",
        )
        completed = _require_sha256_tuple(
            self.completed_scope_identity_sha256s,
            field_name="completed_scope_identity_sha256s",
        )
        if completed != requested:
            raise SuccessorPlanningGenerationContractError(
                "completed scopes must exactly equal requested scopes"
            )
        members = _require_sha256_tuple(
            self.member_identity_sha256s,
            field_name="member_identity_sha256s",
        )
        receipts = _require_sha256_tuple(
            self.member_receipt_sha256s,
            field_name="member_receipt_sha256s",
            unique=False,
            sorted_values=False,
        )
        if len(receipts) != len(members):
            raise SuccessorPlanningGenerationContractError(
                "every planning member requires one exact receipt identity"
            )
        for field_name in (
            "private_generation_identity_sha256",
            "completion_receipt_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        object.__setattr__(
            self,
            "requested_scopes_sha256",
            canonical_planning_sha256(list(requested)),
        )
        object.__setattr__(
            self,
            "completed_scopes_sha256",
            canonical_planning_sha256(list(completed)),
        )
        object.__setattr__(
            self,
            "member_inventory_sha256",
            canonical_planning_sha256(list(members)),
        )
        object.__setattr__(
            self,
            "member_receipts_sha256",
            canonical_planning_sha256(
                [
                    {"member_identity_sha256": member, "receipt_sha256": receipt}
                    for member, receipt in zip(members, receipts, strict=True)
                ]
            ),
        )

    @property
    def identity_sha256(self) -> str:
        return canonical_planning_sha256(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "wave_index": self.wave_index,
            "parent_wave_identity_sha256": self.parent_wave_identity_sha256,
            "requested_scope_identity_sha256s": list(self.requested_scope_identity_sha256s),
            "requested_scopes_sha256": self.requested_scopes_sha256,
            "completed_scope_identity_sha256s": list(self.completed_scope_identity_sha256s),
            "completed_scopes_sha256": self.completed_scopes_sha256,
            "member_identity_sha256s": list(self.member_identity_sha256s),
            "member_inventory_sha256": self.member_inventory_sha256,
            "member_receipt_sha256s": list(self.member_receipt_sha256s),
            "member_receipts_sha256": self.member_receipts_sha256,
            "private_generation_identity_sha256": self.private_generation_identity_sha256,
            "completion_receipt_sha256": self.completion_receipt_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "schema_version",
                "kind",
                "wave_index",
                "parent_wave_identity_sha256",
                "requested_scope_identity_sha256s",
                "requested_scopes_sha256",
                "completed_scope_identity_sha256s",
                "completed_scopes_sha256",
                "member_identity_sha256s",
                "member_inventory_sha256",
                "member_receipt_sha256s",
                "member_receipts_sha256",
                "private_generation_identity_sha256",
                "completion_receipt_sha256",
            }
        )
        _require_exact_keys(payload, expected=expected, label="successor planning wave")
        _parse_current_schema(payload, kind=cls.kind, label="successor planning wave")
        parent = payload["parent_wave_identity_sha256"]
        if parent is not None:
            parent = _require_sha256(parent, field_name="parent_wave_identity_sha256")
        result = cls(
            wave_index=_require_nonnegative_int(payload["wave_index"], field_name="wave_index"),
            parent_wave_identity_sha256=parent,
            requested_scope_identity_sha256s=_sha256_tuple_from_list(
                payload["requested_scope_identity_sha256s"],
                field_name="requested_scope_identity_sha256s",
            ),
            completed_scope_identity_sha256s=_sha256_tuple_from_list(
                payload["completed_scope_identity_sha256s"],
                field_name="completed_scope_identity_sha256s",
            ),
            member_identity_sha256s=_sha256_tuple_from_list(
                payload["member_identity_sha256s"],
                field_name="member_identity_sha256s",
            ),
            member_receipt_sha256s=_sha256_tuple_from_list(
                payload["member_receipt_sha256s"],
                field_name="member_receipt_sha256s",
            ),
            private_generation_identity_sha256=_require_sha256(
                payload["private_generation_identity_sha256"],
                field_name="private_generation_identity_sha256",
            ),
            completion_receipt_sha256=_require_sha256(
                payload["completion_receipt_sha256"],
                field_name="completion_receipt_sha256",
            ),
        )
        for field_name in (
            "requested_scopes_sha256",
            "completed_scopes_sha256",
            "member_inventory_sha256",
            "member_receipts_sha256",
        ):
            if getattr(result, field_name) != _require_sha256(
                payload[field_name], field_name=field_name
            ):
                raise SuccessorPlanningGenerationContractError(
                    f"{field_name} does not match its exact inventory"
                )
        return result


@dataclass(frozen=True, slots=True)
class SealedProviderDispatch:
    """One executable provider call and its exact ordered result-route scopes."""

    phase: PlanningDispatchPhase
    endpoint_name: str
    requested_scope_identity_sha256s: tuple[str, ...]
    parameter_items: _FrozenParameterItems
    pattern: str
    staging_route_ids: tuple[str, ...]
    dependency_identity_sha256s: tuple[str, ...]
    parameters_sha256: str = field(init=False)

    schema_version: ClassVar[int] = SUCCESSOR_PLANNING_GENERATION_SCHEMA_VERSION
    kind: ClassVar[str] = "sealed_provider_dispatch"

    def __post_init__(self) -> None:
        if not isinstance(self.phase, PlanningDispatchPhase):
            raise SuccessorPlanningGenerationContractError("phase must be a PlanningDispatchPhase")
        _require_token(self.endpoint_name, field_name="endpoint_name")
        scopes = _require_sha256_tuple(
            self.requested_scope_identity_sha256s,
            field_name="requested_scope_identity_sha256s",
            sorted_values=False,
        )
        if type(self.parameter_items) is not tuple:
            raise SuccessorPlanningGenerationContractError(
                "parameter_items must be an immutable canonical tuple inventory"
            )
        if any(
            type(item) is not tuple or len(item) != 2 or not isinstance(item[0], str)
            for item in self.parameter_items
        ):
            raise SuccessorPlanningGenerationContractError(
                "parameter_items must contain exact string-keyed key/value tuples"
            )
        parameters = _thaw_parameters(self.parameter_items)
        canonical_items = _canonical_parameter_items(parameters)
        if self.parameter_items != canonical_items:
            raise SuccessorPlanningGenerationContractError(
                "parameter_items must be an immutable canonical sorted tuple inventory"
            )
        _require_token(self.pattern, field_name="pattern")
        if type(self.staging_route_ids) is not tuple or not self.staging_route_ids:
            raise SuccessorPlanningGenerationContractError(
                "staging_route_ids must be a nonempty immutable tuple"
            )
        routes = tuple(
            _require_token(route, field_name="staging_route_id") for route in self.staging_route_ids
        )
        if len(routes) != len(set(routes)):
            raise SuccessorPlanningGenerationContractError("staging_route_ids contains duplicates")
        if len(routes) != len(scopes):
            raise SuccessorPlanningGenerationContractError(
                "ordered route scopes and staging routes must have equal length"
            )
        dependencies = _require_sha256_tuple(
            self.dependency_identity_sha256s,
            field_name="dependency_identity_sha256s",
            nonempty=False,
        )
        if self.phase is PlanningDispatchPhase.PLANNING_WAVE_0:
            if dependencies:
                raise SuccessorPlanningGenerationContractError(
                    "wave 0 dispatch requires an empty dependency inventory"
                )
        elif not dependencies:
            raise SuccessorPlanningGenerationContractError(
                f"{self.phase.value} dispatch requires nonempty sealed dependencies"
            )
        object.__setattr__(
            self,
            "parameters_sha256",
            canonical_parameters_sha256(parameters),
        )

    @classmethod
    def from_parameters(
        cls,
        *,
        phase: PlanningDispatchPhase,
        endpoint_name: str,
        requested_scope_identity_sha256s: tuple[str, ...],
        parameters: Mapping[str, Any],
        pattern: str,
        staging_route_ids: tuple[str, ...],
        dependency_identity_sha256s: tuple[str, ...],
    ) -> Self:
        if not isinstance(parameters, Mapping):
            raise SuccessorPlanningGenerationContractError("parameters must be a mapping")
        return cls(
            phase=phase,
            endpoint_name=endpoint_name,
            requested_scope_identity_sha256s=requested_scope_identity_sha256s,
            parameter_items=_canonical_parameter_items(parameters),
            pattern=pattern,
            staging_route_ids=staging_route_ids,
            dependency_identity_sha256s=dependency_identity_sha256s,
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return _thaw_parameters(self.parameter_items)

    @property
    def identity_sha256(self) -> str:
        return canonical_planning_sha256(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "phase": self.phase.value,
            "endpoint_name": self.endpoint_name,
            "requested_scope_identity_sha256s": list(self.requested_scope_identity_sha256s),
            "parameters": self.parameters,
            "parameters_sha256": self.parameters_sha256,
            "pattern": self.pattern,
            "staging_route_ids": list(self.staging_route_ids),
            "dependency_identity_sha256s": list(self.dependency_identity_sha256s),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "schema_version",
                "kind",
                "phase",
                "endpoint_name",
                "requested_scope_identity_sha256s",
                "parameters",
                "parameters_sha256",
                "pattern",
                "staging_route_ids",
                "dependency_identity_sha256s",
            }
        )
        _require_exact_keys(payload, expected=expected, label="sealed provider dispatch")
        _parse_current_schema(payload, kind=cls.kind, label="sealed provider dispatch")
        try:
            phase = PlanningDispatchPhase(payload["phase"])
        except (TypeError, ValueError) as exc:
            raise SuccessorPlanningGenerationContractError(
                "sealed provider dispatch phase is invalid"
            ) from exc
        raw_routes = _require_list(payload["staging_route_ids"], field_name="staging_route_ids")
        result = cls.from_parameters(
            phase=phase,
            endpoint_name=_require_token(payload["endpoint_name"], field_name="endpoint_name"),
            requested_scope_identity_sha256s=_sha256_tuple_from_list(
                payload["requested_scope_identity_sha256s"],
                field_name="requested_scope_identity_sha256s",
            ),
            parameters=cast(
                "Mapping[str, Any]",
                _require_mapping(payload["parameters"], field_name="parameters"),
            ),
            pattern=_require_token(payload["pattern"], field_name="pattern"),
            staging_route_ids=tuple(
                _require_token(route, field_name="staging_route_id") for route in raw_routes
            ),
            dependency_identity_sha256s=_sha256_tuple_from_list(
                payload["dependency_identity_sha256s"],
                field_name="dependency_identity_sha256s",
            ),
        )
        if result.parameters_sha256 != _require_sha256(
            payload["parameters_sha256"], field_name="parameters_sha256"
        ):
            raise SuccessorPlanningGenerationContractError(
                "parameters_sha256 does not match canonical executable parameters"
            )
        return result


@dataclass(frozen=True, slots=True)
class PlanningGenerationManifest:
    """Canonical final evidence for two sealed waves and executable dispatches."""

    request: SuccessorPlanningRequest
    artifact_identity: SuccessorPlanningArtifactIdentity
    waves: tuple[SuccessorPlanningWave, SuccessorPlanningWave]
    members: tuple[PlanningDataMember, ...]
    requested_route_scopes: tuple[RequestedRouteScope, ...]
    sealed_dispatches: tuple[SealedProviderDispatch, ...]
    requested_route_scopes_sha256: str = field(init=False)

    schema_version: ClassVar[int] = SUCCESSOR_PLANNING_GENERATION_SCHEMA_VERSION
    requested_route_scope_schema_version: ClassVar[int] = SUCCESSOR_UPDATE_CONTRACT_SCHEMA_VERSION
    kind: ClassVar[str] = "planning_generation_manifest"

    @classmethod
    def seal(
        cls,
        *,
        request: SuccessorPlanningRequest,
        artifact_identity: SuccessorPlanningArtifactIdentity,
        waves: tuple[SuccessorPlanningWave, SuccessorPlanningWave],
        members: tuple[PlanningDataMember, ...],
        requested_route_scopes: tuple[RequestedRouteScope, ...],
        sealed_dispatches: tuple[SealedProviderDispatch, ...],
    ) -> Self:
        """Bind the final manifest self-digest and validate all topology.

        The caller supplies every measured artifact field.  Only the
        ``planning_manifest_sha256`` field is replaced because it is the digest
        of the canonical manifest body with that self-digest field omitted.
        """

        requested_scopes_sha256 = canonical_planning_sha256(
            [scope.to_dict() for scope in requested_route_scopes]
        )
        artifact_without_manifest_digest = artifact_identity.to_dict()
        artifact_without_manifest_digest.pop("planning_manifest_sha256")
        digest_payload = {
            "schema_version": cls.schema_version,
            "kind": cls.kind,
            "requested_route_scope_schema_version": cls.requested_route_scope_schema_version,
            "request": request.to_dict(),
            "artifact_identity_without_manifest_digest": artifact_without_manifest_digest,
            "waves": [wave.to_dict() for wave in waves],
            "members": [member.to_dict() for member in members],
            "requested_route_scopes": [scope.to_dict() for scope in requested_route_scopes],
            "requested_route_scopes_sha256": requested_scopes_sha256,
            "sealed_dispatches": [dispatch.to_dict() for dispatch in sealed_dispatches],
        }
        sealed_identity = replace(
            artifact_identity,
            planning_manifest_sha256=canonical_planning_sha256(digest_payload),
        )
        return cls(
            request=request,
            artifact_identity=sealed_identity,
            waves=waves,
            members=members,
            requested_route_scopes=requested_route_scopes,
            sealed_dispatches=sealed_dispatches,
        )

    def __post_init__(self) -> None:
        if not isinstance(self.request, SuccessorPlanningRequest):
            raise SuccessorPlanningGenerationContractError(
                "request must be a SuccessorPlanningRequest"
            )
        if not isinstance(self.artifact_identity, SuccessorPlanningArtifactIdentity):
            raise SuccessorPlanningGenerationContractError(
                "artifact_identity must be a SuccessorPlanningArtifactIdentity"
            )
        if (
            type(self.waves) is not tuple
            or len(self.waves) != 2
            or any(not isinstance(wave, SuccessorPlanningWave) for wave in self.waves)
        ):
            raise SuccessorPlanningGenerationContractError(
                "waves must contain exact wave 0 and wave 1 values"
            )
        wave_0, wave_1 = self.waves
        if (wave_0.wave_index, wave_1.wave_index) != (0, 1):
            raise SuccessorPlanningGenerationContractError(
                "planning waves must be ordered wave 0 then wave 1"
            )
        if wave_1.parent_wave_identity_sha256 != wave_0.identity_sha256:
            raise SuccessorPlanningGenerationContractError(
                "wave 1 parent does not match the exact sealed wave 0 identity"
            )

        if type(self.members) is not tuple:
            raise SuccessorPlanningGenerationContractError(
                "member inventory must be an immutable tuple"
            )
        members = self.members
        if not members or any(not isinstance(member, PlanningDataMember) for member in members):
            raise SuccessorPlanningGenerationContractError(
                "member inventory must be nonempty PlanningDataMember values"
            )
        if members != tuple(sorted(members, key=lambda member: member.identity_sha256)):
            raise SuccessorPlanningGenerationContractError(
                "member inventory must use canonical identity order"
            )
        member_ids = [member.member_id for member in members]
        identities = [member.identity_sha256 for member in members]
        if len(member_ids) != len(set(member_ids)) or len(identities) != len(set(identities)):
            raise SuccessorPlanningGenerationContractError("member inventory contains duplicates")
        for wave in self.waves:
            wave_members = tuple(
                member.identity_sha256 for member in members if member.wave_index == wave.wave_index
            )
            if wave_members != wave.member_identity_sha256s:
                raise SuccessorPlanningGenerationContractError(
                    f"wave {wave.wave_index} member inventory differs from canonical members"
                )
            producing_scopes = {
                member.producing_scope_sha256
                for member in members
                if member.wave_index == wave.wave_index
            }
            if producing_scopes != set(wave.requested_scope_identity_sha256s):
                raise SuccessorPlanningGenerationContractError(
                    f"wave {wave.wave_index} members do not exactly cover its requested scopes"
                )

        if type(self.requested_route_scopes) is not tuple:
            raise SuccessorPlanningGenerationContractError(
                "requested route scopes must be an immutable tuple"
            )
        scopes = self.requested_route_scopes
        if not scopes or any(not isinstance(scope, RequestedRouteScope) for scope in scopes):
            raise SuccessorPlanningGenerationContractError(
                "requested route scope inventory must contain current-schema values"
            )
        if scopes != tuple(sorted(scopes, key=lambda scope: scope.identity_sha256)):
            raise SuccessorPlanningGenerationContractError(
                "requested route scopes must use canonical identity order"
            )
        scope_ids = [scope.identity_sha256 for scope in scopes]
        if len(scope_ids) != len(set(scope_ids)):
            raise SuccessorPlanningGenerationContractError(
                "requested route scope inventory contains duplicates"
            )
        uniqueness_keys = [scope.uniqueness_key for scope in scopes]
        if len(uniqueness_keys) != len(set(uniqueness_keys)):
            raise SuccessorPlanningGenerationContractError(
                "requested route scope inventory contains duplicate route scopes"
            )
        scope_by_id = {scope.identity_sha256: scope for scope in scopes}

        if type(self.sealed_dispatches) is not tuple:
            raise SuccessorPlanningGenerationContractError(
                "sealed dispatch inventory must be an immutable tuple"
            )
        dispatches = self.sealed_dispatches
        if not dispatches or any(
            not isinstance(dispatch, SealedProviderDispatch) for dispatch in dispatches
        ):
            raise SuccessorPlanningGenerationContractError(
                "sealed dispatch inventory must be nonempty"
            )
        phase_rank = {
            PlanningDispatchPhase.PLANNING_WAVE_0: 0,
            PlanningDispatchPhase.PLANNING_WAVE_1: 1,
            PlanningDispatchPhase.UPDATE: 2,
        }
        ranks = [phase_rank[dispatch.phase] for dispatch in dispatches]
        if ranks != sorted(ranks):
            raise SuccessorPlanningGenerationContractError(
                "dispatches must be ordered wave 0, wave 1, then update"
            )
        if len({dispatch.identity_sha256 for dispatch in dispatches}) != len(dispatches):
            raise SuccessorPlanningGenerationContractError(
                "sealed dispatch inventory contains duplicates"
            )
        if PlanningDispatchPhase.UPDATE not in {dispatch.phase for dispatch in dispatches}:
            raise SuccessorPlanningGenerationContractError(
                "sealed dispatch inventory must contain final update dispatches"
            )

        phase_scope_ids: dict[PlanningDispatchPhase, list[str]] = {
            phase: [] for phase in PlanningDispatchPhase
        }
        wave_0_members = set(wave_0.member_identity_sha256s)
        all_members = set(identities)
        planning_dispatch_by_logical_call: dict[tuple[str, str], SealedProviderDispatch] = {}
        update_dispatch_by_logical_call: dict[tuple[str, str], SealedProviderDispatch] = {}
        for dispatch in dispatches:
            phase_scope_ids[dispatch.phase].extend(dispatch.requested_scope_identity_sha256s)
            logical_key = (dispatch.endpoint_name, dispatch.parameters_sha256)
            logical_inventory = (
                update_dispatch_by_logical_call
                if dispatch.phase is PlanningDispatchPhase.UPDATE
                else planning_dispatch_by_logical_call
            )
            if logical_key in logical_inventory:
                raise SuccessorPlanningGenerationContractError(
                    f"{dispatch.phase.value} dispatches one logical call more than once"
                )
            logical_inventory[logical_key] = dispatch
            for position, scope_id in enumerate(dispatch.requested_scope_identity_sha256s):
                scope = scope_by_id.get(scope_id)
                if scope is None:
                    raise SuccessorPlanningGenerationContractError(
                        "dispatch widens beyond the requested route scope inventory"
                    )
                if scope.endpoint_name != dispatch.endpoint_name:
                    raise SuccessorPlanningGenerationContractError(
                        "dispatch endpoint differs from its requested route scope"
                    )
                if scope.parameters != dispatch.parameters:
                    raise SuccessorPlanningGenerationContractError(
                        "dispatch parameters differ from its requested route scope"
                    )
                if scope.route_id != dispatch.staging_route_ids[position]:
                    raise SuccessorPlanningGenerationContractError(
                        "dispatch staging route differs from its requested route scope"
                    )
            dependencies = set(dispatch.dependency_identity_sha256s)
            if dispatch.phase is PlanningDispatchPhase.PLANNING_WAVE_1:
                if not dependencies <= wave_0_members:
                    raise SuccessorPlanningGenerationContractError(
                        "wave 1 dependency inventory contains a non-wave-0 member"
                    )
            elif dispatch.phase is PlanningDispatchPhase.UPDATE and not dependencies <= all_members:
                raise SuccessorPlanningGenerationContractError(
                    "update dependency inventory contains a non-planning member"
                )

        for phase, phase_scopes in phase_scope_ids.items():
            if len(phase_scopes) != len(set(phase_scopes)):
                raise SuccessorPlanningGenerationContractError(
                    f"a requested route scope is dispatched more than once in {phase.value}"
                )
        all_dispatched_scope_ids = {
            scope_id for phase_scopes in phase_scope_ids.values() for scope_id in phase_scopes
        }
        if all_dispatched_scope_ids != set(scope_ids):
            raise SuccessorPlanningGenerationContractError(
                "sealed dispatch inventory does not exactly cover requested route scopes"
            )
        if tuple(sorted(phase_scope_ids[PlanningDispatchPhase.PLANNING_WAVE_0])) != (
            wave_0.requested_scope_identity_sha256s
        ):
            raise SuccessorPlanningGenerationContractError(
                "wave 0 dispatch scopes differ from its sealed wave"
            )
        if tuple(sorted(phase_scope_ids[PlanningDispatchPhase.PLANNING_WAVE_1])) != (
            wave_1.requested_scope_identity_sha256s
        ):
            raise SuccessorPlanningGenerationContractError(
                "wave 1 dispatch scopes differ from its sealed wave"
            )
        request_scope_ids = tuple(
            sorted(scope.identity_sha256 for scope in self.request.requested_planning_scopes)
        )
        if request_scope_ids != wave_0.requested_scope_identity_sha256s:
            raise SuccessorPlanningGenerationContractError(
                "wave 0 must exactly execute the admitted planning request scopes"
            )
        member_ids_by_scope: dict[str, set[str]] = {}
        for member in members:
            member_ids_by_scope.setdefault(member.producing_scope_sha256, set()).add(
                member.identity_sha256
            )
        for logical_key, planning_dispatch in planning_dispatch_by_logical_call.items():
            planning_scopes = tuple(
                scope_by_id[scope_id]
                for scope_id in planning_dispatch.requested_scope_identity_sha256s
            )
            mutabilities = {scope.mutability for scope in planning_scopes}
            if len(mutabilities) != 1:
                raise SuccessorPlanningGenerationContractError(
                    "one planning logical call cannot mix route mutability"
                )
            if mutabilities != {CallMutability.MUTABLE}:
                continue
            update_dispatch = update_dispatch_by_logical_call.get(logical_key)
            if update_dispatch is None:
                raise SuccessorPlanningGenerationContractError(
                    "mutable planning logical calls must be re-dispatched during update"
                )
            if (
                update_dispatch.requested_scope_identity_sha256s
                != planning_dispatch.requested_scope_identity_sha256s
                or update_dispatch.staging_route_ids != planning_dispatch.staging_route_ids
            ):
                raise SuccessorPlanningGenerationContractError(
                    "mutable planning logical-call re-dispatch differs from its original routes"
                )
            expected_dependencies = tuple(
                sorted(
                    member_id
                    for scope_id in planning_dispatch.requested_scope_identity_sha256s
                    for member_id in member_ids_by_scope[scope_id]
                )
            )
            if update_dispatch.dependency_identity_sha256s != expected_dependencies:
                raise SuccessorPlanningGenerationContractError(
                    "mutable planning logical-call re-dispatch must depend on all emitted members"
                )

        object.__setattr__(
            self,
            "requested_route_scopes_sha256",
            canonical_planning_sha256([scope.to_dict() for scope in scopes]),
        )
        self._verify_artifact_identity()

    def _manifest_digest_payload(self) -> dict[str, Any]:
        artifact = self.artifact_identity.to_dict()
        artifact.pop("planning_manifest_sha256")
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "requested_route_scope_schema_version": self.requested_route_scope_schema_version,
            "request": self.request.to_dict(),
            "artifact_identity_without_manifest_digest": artifact,
            "waves": [wave.to_dict() for wave in self.waves],
            "members": [member.to_dict() for member in self.members],
            "requested_route_scopes": [scope.to_dict() for scope in self.requested_route_scopes],
            "requested_route_scopes_sha256": self.requested_route_scopes_sha256,
            "sealed_dispatches": [dispatch.to_dict() for dispatch in self.sealed_dispatches],
        }

    @property
    def computed_planning_manifest_sha256(self) -> str:
        """Digest the manifest body while excluding only its self-digest field."""

        return canonical_planning_sha256(self._manifest_digest_payload())

    def _verify_artifact_identity(self) -> None:
        identity = self.artifact_identity
        expected = {
            "planning_request_sha256": self.request.identity_sha256,
            "member_inventory_sha256": canonical_planning_sha256(
                [member.to_dict() for member in self.members]
            ),
            "private_generation_identity_sha256": canonical_planning_sha256(
                [wave.private_generation_identity_sha256 for wave in self.waves]
            ),
            "wave_inventory_sha256": canonical_planning_sha256(
                [wave.to_dict() for wave in self.waves]
            ),
            "sealed_dispatch_inventory_sha256": canonical_planning_sha256(
                [dispatch.to_dict() for dispatch in self.sealed_dispatches]
            ),
        }
        for field_name, expected_value in expected.items():
            if getattr(identity, field_name) != expected_value:
                raise SuccessorPlanningGenerationContractError(
                    f"{field_name} differs from the canonical manifest inventory"
                )
        if identity.planning_manifest_sha256 != self.computed_planning_manifest_sha256:
            raise SuccessorPlanningGenerationContractError(
                "planning_manifest_sha256 differs from the canonical manifest body"
            )

    @property
    def identity_sha256(self) -> str:
        return canonical_planning_sha256(self.to_dict())

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_planning_json_bytes(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Private store encoding. Public reports must use :meth:`to_public_dict`."""

        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "requested_route_scope_schema_version": self.requested_route_scope_schema_version,
            "request": self.request.to_dict(),
            "artifact_identity": self.artifact_identity.to_dict(),
            "waves": [wave.to_dict() for wave in self.waves],
            "members": [member.to_dict() for member in self.members],
            "requested_route_scopes": [scope.to_dict() for scope in self.requested_route_scopes],
            "requested_route_scopes_sha256": self.requested_route_scopes_sha256,
            "sealed_dispatches": [dispatch.to_dict() for dispatch in self.sealed_dispatches],
        }

    def to_public_dict(self) -> dict[str, Any]:
        """Path-free identities only; omit members, waves, and parameter bodies."""

        return PlanningGenerationPublicIdentity.from_manifest(self).to_dict()

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "schema_version",
                "kind",
                "requested_route_scope_schema_version",
                "request",
                "artifact_identity",
                "waves",
                "members",
                "requested_route_scopes",
                "requested_route_scopes_sha256",
                "sealed_dispatches",
            }
        )
        _require_exact_keys(payload, expected=expected, label="planning generation manifest")
        _parse_current_schema(payload, kind=cls.kind, label="planning generation manifest")
        if (
            type(payload["requested_route_scope_schema_version"]) is not int
            or payload["requested_route_scope_schema_version"]
            != cls.requested_route_scope_schema_version
        ):
            raise SuccessorPlanningGenerationContractError(
                "requested route scope schema is not current"
            )
        try:
            request = SuccessorPlanningRequest.from_dict(
                _require_mapping(payload["request"], field_name="request")
            )
            scopes = tuple(
                RequestedRouteScope.from_dict(
                    _require_mapping(item, field_name=f"requested_route_scopes[{index}]")
                )
                for index, item in enumerate(
                    _require_list(
                        payload["requested_route_scopes"],
                        field_name="requested_route_scopes",
                    )
                )
            )
        except (ValueError, SuccessorUpdateContractError) as exc:
            raise SuccessorPlanningGenerationContractError(
                f"nested planning request or requested route scope is invalid: {exc}"
            ) from exc
        raw_waves = _require_list(payload["waves"], field_name="waves")
        raw_members = _require_list(payload["members"], field_name="members")
        raw_dispatches = _require_list(payload["sealed_dispatches"], field_name="sealed_dispatches")
        result = cls(
            request=request,
            artifact_identity=SuccessorPlanningArtifactIdentity.from_dict(
                _require_mapping(payload["artifact_identity"], field_name="artifact_identity")
            ),
            waves=cast(
                "tuple[SuccessorPlanningWave, SuccessorPlanningWave]",
                tuple(
                    SuccessorPlanningWave.from_dict(
                        _require_mapping(item, field_name=f"waves[{index}]")
                    )
                    for index, item in enumerate(raw_waves)
                ),
            ),
            members=tuple(
                PlanningDataMember.from_dict(_require_mapping(item, field_name=f"members[{index}]"))
                for index, item in enumerate(raw_members)
            ),
            requested_route_scopes=scopes,
            sealed_dispatches=tuple(
                SealedProviderDispatch.from_dict(
                    _require_mapping(item, field_name=f"sealed_dispatches[{index}]")
                )
                for index, item in enumerate(raw_dispatches)
            ),
        )
        if result.requested_route_scopes_sha256 != _require_sha256(
            payload["requested_route_scopes_sha256"],
            field_name="requested_route_scopes_sha256",
        ):
            raise SuccessorPlanningGenerationContractError(
                "requested_route_scopes_sha256 differs from its exact inventory"
            )
        return result

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> Self:
        """Decode only the exact current-schema canonical JSON representation."""

        if not isinstance(encoded, bytes):
            raise SuccessorPlanningGenerationContractError(
                "planning manifest encoding must be bytes"
            )

        def reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise SuccessorPlanningGenerationContractError(
                        f"planning manifest contains duplicate key {key!r}"
                    )
                result[key] = value
            return result

        def reject_constant(value: str) -> object:
            raise SuccessorPlanningGenerationContractError(
                f"planning manifest contains non-finite JSON value {value}"
            )

        try:
            decoded = json.loads(
                encoded.decode("utf-8", errors="strict"),
                object_pairs_hook=reject_duplicate_pairs,
                parse_constant=reject_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SuccessorPlanningGenerationContractError(
                "planning manifest is not strict UTF-8 JSON"
            ) from exc
        payload = _require_mapping(decoded, field_name="planning manifest")
        if canonical_planning_json_bytes(payload) != encoded:
            raise SuccessorPlanningGenerationContractError(
                "planning manifest bytes are not canonical"
            )
        return cls.from_dict(payload)


@dataclass(frozen=True, slots=True)
class PlanningGenerationPublicIdentity:
    """Path-free public projection of one private planning-generation manifest."""

    artifact_identity: SuccessorPlanningArtifactIdentity
    identity_sha256: str
    requested_route_scopes_sha256: str

    schema_version: ClassVar[int] = SUCCESSOR_PLANNING_GENERATION_SCHEMA_VERSION
    requested_route_scope_schema_version: ClassVar[int] = SUCCESSOR_UPDATE_CONTRACT_SCHEMA_VERSION
    kind: ClassVar[str] = "planning_generation_manifest"

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_identity, SuccessorPlanningArtifactIdentity):
            raise SuccessorPlanningGenerationContractError(
                "artifact_identity must be a SuccessorPlanningArtifactIdentity"
            )
        _require_sha256(self.identity_sha256, field_name="identity_sha256")
        _require_sha256(
            self.requested_route_scopes_sha256,
            field_name="requested_route_scopes_sha256",
        )

    @classmethod
    def from_manifest(cls, manifest: PlanningGenerationManifest) -> Self:
        if not isinstance(manifest, PlanningGenerationManifest):
            raise SuccessorPlanningGenerationContractError(
                "public identity requires a PlanningGenerationManifest"
            )
        return cls(
            artifact_identity=manifest.artifact_identity,
            identity_sha256=manifest.identity_sha256,
            requested_route_scopes_sha256=manifest.requested_route_scopes_sha256,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "requested_route_scope_schema_version": self.requested_route_scope_schema_version,
            "artifact_identity": self.artifact_identity.to_dict(),
            "requested_route_scopes_sha256": self.requested_route_scopes_sha256,
            "identity_sha256": self.identity_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "schema_version",
                "kind",
                "requested_route_scope_schema_version",
                "artifact_identity",
                "requested_route_scopes_sha256",
                "identity_sha256",
            }
        )
        _require_exact_keys(
            payload,
            expected=expected,
            label="planning generation public identity",
        )
        _parse_current_schema(
            payload,
            kind=cls.kind,
            label="planning generation public identity",
        )
        if (
            type(payload["requested_route_scope_schema_version"]) is not int
            or payload["requested_route_scope_schema_version"]
            != cls.requested_route_scope_schema_version
        ):
            raise SuccessorPlanningGenerationContractError(
                "requested route scope schema is not current"
            )
        result = cls(
            artifact_identity=SuccessorPlanningArtifactIdentity.from_dict(
                _require_mapping(payload["artifact_identity"], field_name="artifact_identity")
            ),
            identity_sha256=_require_sha256(
                payload["identity_sha256"],
                field_name="identity_sha256",
            ),
            requested_route_scopes_sha256=_require_sha256(
                payload["requested_route_scopes_sha256"],
                field_name="requested_route_scopes_sha256",
            ),
        )
        return result
