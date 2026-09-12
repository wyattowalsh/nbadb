"""Immutable assurance contract for daily and monthly successor generations.

This module is intentionally isolated from orchestration and persistence.  It defines
the fail-closed value objects and state transitions that those surfaces must consume
before an update may replace a fully assured baseline.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar, Self, cast

from nbadb.extract.bronze import (
    canonical_parameters_payload,
    canonical_parameters_sha256,
)

__all__ = [
    "SUCCESSOR_LIVE_UPDATE_ROOT_ENDPOINTS",
    "SUCCESSOR_SCOREBOARD_DERIVED_GAME_ENDPOINTS",
    "SUCCESSOR_UPDATE_CONTRACT_SCHEMA_VERSION",
    "BaselineAssuranceIdentity",
    "CallMutability",
    "DeltaDisposition",
    "ObservedDeltaReceipt",
    "PlannedRouteReplacementBinding",
    "RequestedRouteScope",
    "SuccessorAssuranceIdentity",
    "SuccessorGenerationBuild",
    "SuccessorGenerationState",
    "SuccessorUpdateContractError",
    "SuccessorUpdateIntent",
    "SuccessorUpdateMode",
    "SuccessorUpdateTransaction",
    "SuccessorUpdateTransitionError",
    "UpdateScopeClosureEvidenceKind",
    "canonical_json_bytes",
    "canonical_sha256",
    "is_scoreboard_derived_game_scope",
    "may_reuse_baseline_completion",
    "planned_route_replacement_bindings_sha256",
    "require_live_and_scoreboard_update_delta_closure",
    "require_update_replacement_delta_closure",
    "requires_update_replacement_delta_closure",
]

SUCCESSOR_UPDATE_CONTRACT_SCHEMA_VERSION = 6

_MAX_SIGNED_63 = (1 << 63) - 1

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SOURCE_SHA_RE = re.compile(r"[0-9a-f]{40}")
_SAFE_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}")
_DATASET_REF_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_REASON_CODE_RE = re.compile(r"[a-z0-9][a-z0-9_]{0,127}")
_UTC_INSTANT_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
_ASCII_GAME_ID_RE = re.compile(r"[0-9]{10}")
_PLANNED_ROUTE_REPLACEMENT_BINDINGS_DOMAIN = (
    "nbadb.successor-update.planned-route-replacement-bindings.v1"
)

SUCCESSOR_LIVE_UPDATE_ROOT_ENDPOINTS: frozenset[str] = frozenset(
    {
        "live_score_board",
        "live_odds",
        "live_play_by_play",
        "live_box_score",
    }
)
SUCCESSOR_SCOREBOARD_DERIVED_GAME_ENDPOINTS: frozenset[str] = frozenset(
    {
        "live_play_by_play",
        "live_box_score",
    }
)


class SuccessorUpdateContractError(ValueError):
    """Raised when successor provenance is incomplete or inconsistent."""


class SuccessorUpdateTransitionError(SuccessorUpdateContractError):
    """Raised when a successor transaction attempts an illegal transition."""


class SuccessorUpdateMode(StrEnum):
    DAILY = "daily"
    MONTHLY = "monthly"


class SuccessorGenerationState(StrEnum):
    CANDIDATE = "candidate"
    BUILT = "built"
    VALIDATED = "validated"
    PROMOTED = "promoted"


class CallMutability(StrEnum):
    IMMUTABLE = "immutable"
    MUTABLE = "mutable"


class DeltaDisposition(StrEnum):
    OBSERVED = "observed"
    TYPED_ZERO = "typed_zero"


class UpdateScopeClosureEvidenceKind(StrEnum):
    """Explicit claim for how one requested update scope is being closed."""

    OBSERVED_DELTA_REPLACEMENT = "observed_delta_replacement"
    PLANNING_WAVE_CAPTURE = "planning_wave_capture"
    RETAINED_BRONZE_SEAL = "retained_bronze_seal"
    JOURNAL_COMPLETION = "journal_completion"
    CAPTURE_COMPLETION = "capture_completion"


type _ParameterScalar = str | int | float | bool | None
type _FrozenParameterValue = _ParameterScalar | tuple[_ParameterScalar, ...]
type _FrozenParameterItems = tuple[tuple[str, _FrozenParameterValue], ...]


def canonical_json_bytes(payload: object) -> bytes:
    """Return the only JSON encoding admitted to successor contract digests."""

    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(payload: object) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def _require_sha256(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise SuccessorUpdateContractError(f"{field_name} must be a lowercase SHA-256")
    return value


def _require_source_sha(value: object, *, field_name: str = "source_sha") -> str:
    if not isinstance(value, str) or _SOURCE_SHA_RE.fullmatch(value) is None:
        raise SuccessorUpdateContractError(
            f"{field_name} must be a 40-character lowercase commit SHA"
        )
    return value


def _require_safe_token(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SAFE_TOKEN_RE.fullmatch(value) is None:
        raise SuccessorUpdateContractError(f"{field_name} must be an exact safe token")
    return value


def _require_dataset_ref(value: object, *, field_name: str = "remote_dataset") -> str:
    if not isinstance(value, str) or _DATASET_REF_RE.fullmatch(value) is None:
        raise SuccessorUpdateContractError(f"{field_name} must be an exact owner/dataset reference")
    return value


def _require_reason_code(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _REASON_CODE_RE.fullmatch(value) is None:
        raise SuccessorUpdateContractError(f"{field_name} must be a stable reason code")
    return value


def _require_positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 1:
        raise SuccessorUpdateContractError(f"{field_name} must be a positive integer")
    return value


def _require_nonnegative_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise SuccessorUpdateContractError(f"{field_name} must be a nonnegative integer")
    return value


def _require_nonnegative_signed63_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 0 or value > _MAX_SIGNED_63:
        raise SuccessorUpdateContractError(
            f"{field_name} must be a nonnegative signed-63-bit integer"
        )
    return value


def _require_utc_instant(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _UTC_INSTANT_RE.fullmatch(value) is None:
        raise SuccessorUpdateContractError(
            f"{field_name} must use canonical UTC form YYYY-MM-DDTHH:MM:SSZ"
        )
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise SuccessorUpdateContractError(
            f"{field_name} must use canonical UTC form YYYY-MM-DDTHH:MM:SSZ"
        ) from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise SuccessorUpdateContractError(
            f"{field_name} must use canonical UTC form YYYY-MM-DDTHH:MM:SSZ"
        )
    return value


def _require_mapping(value: object, *, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise SuccessorUpdateContractError(f"{field_name} must be an object with string keys")
    return cast("Mapping[str, object]", value)


def _require_sequence(value: object, *, field_name: str) -> Sequence[object]:
    if not isinstance(value, list):
        raise SuccessorUpdateContractError(f"{field_name} must be a list")
    return value


def _require_sha256_tuple(
    values: object,
    *,
    field_name: str,
    nonempty: bool = True,
) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise SuccessorUpdateContractError(f"{field_name} must be an immutable tuple")
    result = tuple(_require_sha256(value, field_name=field_name) for value in values)
    if nonempty and not result:
        raise SuccessorUpdateContractError(f"{field_name} must be nonempty")
    if len(result) != len(set(result)):
        raise SuccessorUpdateContractError(f"{field_name} contains duplicates")
    if result != tuple(sorted(result)):
        raise SuccessorUpdateContractError(f"{field_name} must use canonical sorted order")
    return result


def _sha256_tuple_from_list(value: object, *, field_name: str) -> tuple[str, ...]:
    return tuple(
        _require_sha256(item, field_name=field_name)
        for item in _require_sequence(value, field_name=field_name)
    )


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
    raise SuccessorUpdateContractError(f"{label} fields are invalid: {'; '.join(details)}")


@dataclass(frozen=True, slots=True)
class PlannedRouteReplacementBinding:
    """Path-free execution authority for one exact UPDATE result-route scope."""

    requested_scope_sha256: str
    execution_dispatch_identity_sha256: str
    planning_dependency_identity_sha256s: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_sha256(self.requested_scope_sha256, field_name="requested_scope_sha256")
        _require_sha256(
            self.execution_dispatch_identity_sha256,
            field_name="execution_dispatch_identity_sha256",
        )
        _require_sha256_tuple(
            self.planning_dependency_identity_sha256s,
            field_name="planning_dependency_identity_sha256s",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "requested_scope_sha256": self.requested_scope_sha256,
            "execution_dispatch_identity_sha256": self.execution_dispatch_identity_sha256,
            "planning_dependency_identity_sha256s": list(self.planning_dependency_identity_sha256s),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "requested_scope_sha256",
                    "execution_dispatch_identity_sha256",
                    "planning_dependency_identity_sha256s",
                }
            ),
            label="planned route replacement binding",
        )
        return cls(
            requested_scope_sha256=_require_sha256(
                payload["requested_scope_sha256"],
                field_name="requested_scope_sha256",
            ),
            execution_dispatch_identity_sha256=_require_sha256(
                payload["execution_dispatch_identity_sha256"],
                field_name="execution_dispatch_identity_sha256",
            ),
            planning_dependency_identity_sha256s=_sha256_tuple_from_list(
                payload["planning_dependency_identity_sha256s"],
                field_name="planning_dependency_identity_sha256s",
            ),
        )


def _canonical_planned_route_replacement_bindings(
    bindings: Sequence[PlannedRouteReplacementBinding],
) -> tuple[PlannedRouteReplacementBinding, ...]:
    result = tuple(bindings)
    if not result:
        raise SuccessorUpdateContractError(
            "planned route replacement binding inventory must be nonempty"
        )
    if any(not isinstance(binding, PlannedRouteReplacementBinding) for binding in result):
        raise SuccessorUpdateContractError(
            "planned route replacement bindings must contain current-schema values"
        )
    result = tuple(sorted(result, key=lambda binding: binding.requested_scope_sha256))
    scope_ids = tuple(binding.requested_scope_sha256 for binding in result)
    if len(scope_ids) != len(set(scope_ids)):
        raise SuccessorUpdateContractError(
            "planned route replacement binding inventory contains duplicate scopes"
        )
    return result


def planned_route_replacement_bindings_sha256(
    bindings: Sequence[PlannedRouteReplacementBinding],
) -> str:
    """Digest the canonical route-replacement inventory in its own domain."""

    canonical = _canonical_planned_route_replacement_bindings(bindings)
    return canonical_sha256(
        {
            "domain": _PLANNED_ROUTE_REPLACEMENT_BINDINGS_DOMAIN,
            "bindings": [binding.to_dict() for binding in canonical],
        }
    )


@dataclass(frozen=True, slots=True)
class BaselineAssuranceIdentity:
    """Exact identity of the fully assured dataset an update proposes to replace."""

    remote_dataset: str
    remote_dataset_version: int
    chain_id: str
    source_sha: str
    coverage_fingerprint: str
    data_tree_fingerprint: str
    remote_bundle_fingerprint_sha256: str
    installed_public_tree_sha256: str
    installed_public_tree_bytes: int
    assured_manifest_sha256: str
    terminal_assurance_report_sha256: str
    private_baseline_receipt_sha256: str
    checkpoint_database_sha256: str
    checkpoint_report_sha256: str
    contract_blocked_evidence_sha256: str
    provider_authority_sha256: str

    def __post_init__(self) -> None:
        _require_dataset_ref(self.remote_dataset)
        _require_positive_int(
            self.remote_dataset_version,
            field_name="remote_dataset_version",
        )
        _require_safe_token(self.chain_id, field_name="chain_id")
        _require_source_sha(self.source_sha)
        _require_nonnegative_signed63_int(
            self.installed_public_tree_bytes,
            field_name="installed_public_tree_bytes",
        )
        for field_name in (
            "coverage_fingerprint",
            "data_tree_fingerprint",
            "remote_bundle_fingerprint_sha256",
            "installed_public_tree_sha256",
            "assured_manifest_sha256",
            "terminal_assurance_report_sha256",
            "private_baseline_receipt_sha256",
            "checkpoint_database_sha256",
            "checkpoint_report_sha256",
            "contract_blocked_evidence_sha256",
            "provider_authority_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)

    @property
    def identity_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, str | int]:
        return {
            "remote_dataset": self.remote_dataset,
            "remote_dataset_version": self.remote_dataset_version,
            "chain_id": self.chain_id,
            "source_sha": self.source_sha,
            "coverage_fingerprint": self.coverage_fingerprint,
            "data_tree_fingerprint": self.data_tree_fingerprint,
            "remote_bundle_fingerprint_sha256": self.remote_bundle_fingerprint_sha256,
            "installed_public_tree_sha256": self.installed_public_tree_sha256,
            "installed_public_tree_bytes": self.installed_public_tree_bytes,
            "assured_manifest_sha256": self.assured_manifest_sha256,
            "terminal_assurance_report_sha256": self.terminal_assurance_report_sha256,
            "private_baseline_receipt_sha256": self.private_baseline_receipt_sha256,
            "checkpoint_database_sha256": self.checkpoint_database_sha256,
            "checkpoint_report_sha256": self.checkpoint_report_sha256,
            "contract_blocked_evidence_sha256": self.contract_blocked_evidence_sha256,
            "provider_authority_sha256": self.provider_authority_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "chain_id",
                "remote_dataset",
                "remote_dataset_version",
                "source_sha",
                "coverage_fingerprint",
                "data_tree_fingerprint",
                "remote_bundle_fingerprint_sha256",
                "installed_public_tree_sha256",
                "installed_public_tree_bytes",
                "assured_manifest_sha256",
                "terminal_assurance_report_sha256",
                "private_baseline_receipt_sha256",
                "checkpoint_database_sha256",
                "checkpoint_report_sha256",
                "contract_blocked_evidence_sha256",
                "provider_authority_sha256",
            }
        )
        _require_exact_keys(payload, expected=expected, label="baseline assurance identity")
        return cls(
            remote_dataset=_require_dataset_ref(payload["remote_dataset"]),
            remote_dataset_version=_require_positive_int(
                payload["remote_dataset_version"],
                field_name="remote_dataset_version",
            ),
            chain_id=_require_safe_token(payload["chain_id"], field_name="chain_id"),
            source_sha=_require_source_sha(payload["source_sha"]),
            coverage_fingerprint=_require_sha256(
                payload["coverage_fingerprint"], field_name="coverage_fingerprint"
            ),
            data_tree_fingerprint=_require_sha256(
                payload["data_tree_fingerprint"], field_name="data_tree_fingerprint"
            ),
            remote_bundle_fingerprint_sha256=_require_sha256(
                payload["remote_bundle_fingerprint_sha256"],
                field_name="remote_bundle_fingerprint_sha256",
            ),
            installed_public_tree_sha256=_require_sha256(
                payload["installed_public_tree_sha256"],
                field_name="installed_public_tree_sha256",
            ),
            installed_public_tree_bytes=_require_nonnegative_signed63_int(
                payload["installed_public_tree_bytes"],
                field_name="installed_public_tree_bytes",
            ),
            assured_manifest_sha256=_require_sha256(
                payload["assured_manifest_sha256"], field_name="assured_manifest_sha256"
            ),
            terminal_assurance_report_sha256=_require_sha256(
                payload["terminal_assurance_report_sha256"],
                field_name="terminal_assurance_report_sha256",
            ),
            private_baseline_receipt_sha256=_require_sha256(
                payload["private_baseline_receipt_sha256"],
                field_name="private_baseline_receipt_sha256",
            ),
            checkpoint_database_sha256=_require_sha256(
                payload["checkpoint_database_sha256"],
                field_name="checkpoint_database_sha256",
            ),
            checkpoint_report_sha256=_require_sha256(
                payload["checkpoint_report_sha256"], field_name="checkpoint_report_sha256"
            ),
            contract_blocked_evidence_sha256=_require_sha256(
                payload["contract_blocked_evidence_sha256"],
                field_name="contract_blocked_evidence_sha256",
            ),
            provider_authority_sha256=_require_sha256(
                payload["provider_authority_sha256"], field_name="provider_authority_sha256"
            ),
        )


@dataclass(frozen=True, slots=True)
class RequestedRouteScope:
    """Dispatch-independent identity for one exact requested result route and scope."""

    endpoint_name: str
    route_id: str
    route_contract_sha256: str
    parameter_items: _FrozenParameterItems
    mutability: CallMutability
    scope_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        _require_safe_token(self.endpoint_name, field_name="endpoint_name")
        _require_safe_token(self.route_id, field_name="route_id")
        _require_sha256(self.route_contract_sha256, field_name="route_contract_sha256")
        if not isinstance(self.mutability, CallMutability):
            raise SuccessorUpdateContractError("mutability must be a CallMutability")
        if type(self.parameter_items) is not tuple:
            raise SuccessorUpdateContractError(
                "parameter_items must be an immutable canonical tuple inventory"
            )
        if any(type(item) is not tuple or len(item) != 2 for item in self.parameter_items):
            raise SuccessorUpdateContractError(
                "parameter_items must contain exact key/value tuples"
            )
        keys = tuple(item[0] for item in self.parameter_items)
        if any(not isinstance(key, str) for key in keys):
            raise SuccessorUpdateContractError("parameter inventory keys must be strings")
        if len(keys) != len(set(keys)):
            raise SuccessorUpdateContractError("parameter inventory contains duplicate keys")
        parameters = {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in self.parameter_items
        }
        try:
            canonical_payload = canonical_parameters_payload(parameters)
        except (TypeError, ValueError) as exc:
            raise SuccessorUpdateContractError(
                f"logical parameter inventory is invalid: {exc}"
            ) from exc
        canonical_items = self._freeze_parameters(canonical_payload)
        if self.parameter_items != canonical_items:
            raise SuccessorUpdateContractError(
                "parameter_items must be an immutable canonical sorted tuple inventory"
            )
        object.__setattr__(
            self,
            "scope_sha256",
            canonical_parameters_sha256(canonical_payload),
        )

    @staticmethod
    def _freeze_parameters(parameters: Mapping[str, Any]) -> _FrozenParameterItems:
        return tuple(
            (
                key,
                tuple(value) if isinstance(value, list) else cast("_ParameterScalar", value),
            )
            for key, value in parameters.items()
        )

    @classmethod
    def from_parameters(
        cls,
        *,
        endpoint_name: str,
        route_id: str,
        route_contract_sha256: str,
        parameters: Mapping[str, Any],
        mutability: CallMutability,
    ) -> Self:
        """Build a scope from the exact executable logical-call parameters."""

        if not isinstance(parameters, Mapping):
            raise SuccessorUpdateContractError("parameters must be a mapping")
        try:
            canonical_payload = canonical_parameters_payload(parameters)
        except (TypeError, ValueError) as exc:
            raise SuccessorUpdateContractError(f"logical parameters are invalid: {exc}") from exc
        return cls(
            endpoint_name=endpoint_name,
            route_id=route_id,
            route_contract_sha256=route_contract_sha256,
            parameter_items=cls._freeze_parameters(canonical_payload),
            mutability=mutability,
        )

    @property
    def parameters(self) -> dict[str, Any]:
        """Return a detached JSON-compatible copy of the executable parameters."""

        return {
            key: list(value) if isinstance(value, tuple) else value
            for key, value in self.parameter_items
        }

    @property
    def identity_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    @property
    def uniqueness_key(self) -> tuple[str, str, str, str]:
        return (
            self.endpoint_name,
            self.route_id,
            self.route_contract_sha256,
            self.scope_sha256,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "endpoint_name": self.endpoint_name,
            "route_id": self.route_id,
            "route_contract_sha256": self.route_contract_sha256,
            "parameters": self.parameters,
            "scope_sha256": self.scope_sha256,
            "mutability": self.mutability.value,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "endpoint_name",
                    "route_id",
                    "route_contract_sha256",
                    "parameters",
                    "scope_sha256",
                    "mutability",
                }
            ),
            label="requested route scope",
        )
        raw_mutability = _require_safe_token(payload["mutability"], field_name="mutability")
        try:
            mutability = CallMutability(raw_mutability)
        except ValueError as exc:
            raise SuccessorUpdateContractError(
                f"unsupported call mutability: {raw_mutability}"
            ) from exc
        scope = cls.from_parameters(
            endpoint_name=_require_safe_token(payload["endpoint_name"], field_name="endpoint_name"),
            route_id=_require_safe_token(payload["route_id"], field_name="route_id"),
            route_contract_sha256=_require_sha256(
                payload["route_contract_sha256"], field_name="route_contract_sha256"
            ),
            parameters=_require_mapping(payload["parameters"], field_name="parameters"),
            mutability=mutability,
        )
        supplied_scope_sha256 = _require_sha256(payload["scope_sha256"], field_name="scope_sha256")
        if scope.scope_sha256 != supplied_scope_sha256:
            raise SuccessorUpdateContractError(
                "scope_sha256 does not match the canonical logical parameters"
            )
        return scope


def is_scoreboard_derived_game_scope(requested_scope: RequestedRouteScope) -> bool:
    """Return whether this scope is a sealed status-2 per-game live dispatch."""

    if not isinstance(requested_scope, RequestedRouteScope):
        raise SuccessorUpdateContractError("requested_scope must be a RequestedRouteScope")
    if requested_scope.endpoint_name not in SUCCESSOR_SCOREBOARD_DERIVED_GAME_ENDPOINTS:
        return False
    parameters = requested_scope.parameters
    game_id = parameters.get("game_id")
    return (
        set(parameters) == {"game_id"}
        and isinstance(game_id, str)
        and _ASCII_GAME_ID_RE.fullmatch(game_id) is not None
    )


def requires_update_replacement_delta_closure(requested_scope: RequestedRouteScope) -> bool:
    """Return whether update closure requires replacement/delta, not capture alone."""

    if not isinstance(requested_scope, RequestedRouteScope):
        raise SuccessorUpdateContractError("requested_scope must be a RequestedRouteScope")
    return (
        requested_scope.endpoint_name in SUCCESSOR_LIVE_UPDATE_ROOT_ENDPOINTS
        or is_scoreboard_derived_game_scope(requested_scope)
    )


def _canonical_sealed_live_game_ids(values: Sequence[object]) -> tuple[str, ...]:
    if type(values) is not tuple and type(values) is not list:
        raise SuccessorUpdateContractError(
            "sealed_live_game_ids must be a list or tuple of game IDs"
        )
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or _ASCII_GAME_ID_RE.fullmatch(value) is None:
            raise SuccessorUpdateContractError(
                "sealed live game_id must be an exact ten-digit string"
            )
        if value in seen:
            raise SuccessorUpdateContractError("sealed live game inventory contains duplicates")
        seen.add(value)
        result.append(value)
    return tuple(result)


def _bind_scoreboard_derived_game_scope(
    requested_scope: RequestedRouteScope,
    sealed_live_game_ids: tuple[str, ...],
) -> None:
    if requested_scope.endpoint_name not in SUCCESSOR_SCOREBOARD_DERIVED_GAME_ENDPOINTS:
        return
    derived = is_scoreboard_derived_game_scope(requested_scope)
    game_id = requested_scope.parameters.get("game_id") if derived else None
    if not sealed_live_game_ids:
        if derived:
            raise SuccessorUpdateContractError(
                "typed-zero sealed live game inventory cannot close a scoreboard-derived game scope"
            )
        return
    if not derived or game_id not in sealed_live_game_ids:
        raise SuccessorUpdateContractError(
            "scoreboard-derived game scope is not bound to the sealed live game inventory"
        )


def require_update_replacement_delta_closure(
    requested_scope: RequestedRouteScope,
    *,
    receipt: ObservedDeltaReceipt | None,
    evidence_kind: UpdateScopeClosureEvidenceKind,
    sealed_live_game_ids: Sequence[object] | None = None,
) -> ObservedDeltaReceipt:
    """Bind one live root or sealed game scope to replacement/delta closure."""

    if not requires_update_replacement_delta_closure(requested_scope):
        raise SuccessorUpdateContractError(
            "requested scope is not a live root or scoreboard-derived game scope"
        )
    if not isinstance(evidence_kind, UpdateScopeClosureEvidenceKind):
        raise SuccessorUpdateContractError(
            "evidence_kind must be an UpdateScopeClosureEvidenceKind"
        )
    sealed = (
        None
        if sealed_live_game_ids is None
        else _canonical_sealed_live_game_ids(sealed_live_game_ids)
    )
    if evidence_kind is not UpdateScopeClosureEvidenceKind.OBSERVED_DELTA_REPLACEMENT:
        raise SuccessorUpdateContractError(
            f"{evidence_kind.value} cannot close a live root or scoreboard-derived game scope"
        )
    if not isinstance(receipt, ObservedDeltaReceipt):
        raise SuccessorUpdateContractError(
            "live root and scoreboard-derived game scope closure requires an ObservedDeltaReceipt"
        )
    if receipt.requested_scope_sha256 != requested_scope.identity_sha256:
        raise SuccessorUpdateContractError(
            "observed delta receipt does not match the requested live or scoreboard-derived scope"
        )
    if receipt.source_scope_replacement_sha256 == receipt.logical_call_receipt_sha256:
        raise SuccessorUpdateContractError(
            "capture completion cannot substitute for source-scope replacement"
        )
    if sealed is not None:
        _bind_scoreboard_derived_game_scope(requested_scope, sealed)
    return receipt


def require_live_and_scoreboard_update_delta_closure(
    requested_scopes: Sequence[RequestedRouteScope],
    *,
    observed_delta_receipts: Sequence[ObservedDeltaReceipt],
    evidence_kind: UpdateScopeClosureEvidenceKind,
    sealed_live_game_ids: Sequence[object] | None = None,
) -> tuple[ObservedDeltaReceipt, ...]:
    """Bind every live root and sealed scoreboard-derived game scope to delta closure."""

    if type(requested_scopes) is not tuple and type(requested_scopes) is not list:
        raise SuccessorUpdateContractError("requested_scopes must be a list or tuple")
    if any(not isinstance(scope, RequestedRouteScope) for scope in requested_scopes):
        raise SuccessorUpdateContractError("requested scopes must be RequestedRouteScope values")
    if not isinstance(evidence_kind, UpdateScopeClosureEvidenceKind):
        raise SuccessorUpdateContractError(
            "evidence_kind must be an UpdateScopeClosureEvidenceKind"
        )
    requiring = tuple(
        scope for scope in requested_scopes if requires_update_replacement_delta_closure(scope)
    )
    if not requiring:
        return ()
    if evidence_kind is not UpdateScopeClosureEvidenceKind.OBSERVED_DELTA_REPLACEMENT:
        raise SuccessorUpdateContractError(
            f"{evidence_kind.value} cannot close a live root or scoreboard-derived game scope"
        )
    if type(observed_delta_receipts) is not tuple and type(observed_delta_receipts) is not list:
        raise SuccessorUpdateContractError("observed_delta_receipts must be a list or tuple")
    if any(not isinstance(receipt, ObservedDeltaReceipt) for receipt in observed_delta_receipts):
        raise SuccessorUpdateContractError(
            "observed delta receipts must be ObservedDeltaReceipt values"
        )
    by_scope: dict[str, ObservedDeltaReceipt] = {}
    for receipt in observed_delta_receipts:
        prior = by_scope.setdefault(receipt.requested_scope_sha256, receipt)
        if prior != receipt:
            raise SuccessorUpdateContractError(
                "observed delta receipt inventory contains conflicting live or "
                "scoreboard-derived closures"
            )
    return tuple(
        require_update_replacement_delta_closure(
            scope,
            receipt=by_scope.get(scope.identity_sha256),
            evidence_kind=evidence_kind,
            sealed_live_game_ids=sealed_live_game_ids,
        )
        for scope in requiring
    )


def may_reuse_baseline_completion(requested_scope: RequestedRouteScope) -> bool:
    """Return whether a prior completed call may satisfy this successor request.

    Mutable calls always require a fresh, receipt-backed observation.  Immutable calls
    may be omitted from a successor request only when separate baseline validation has
    already proved the exact same route and scope complete.  Live roots and sealed
    scoreboard-derived game scopes never reuse baseline completion.
    """

    if not isinstance(requested_scope, RequestedRouteScope):
        raise SuccessorUpdateContractError("requested_scope must be a RequestedRouteScope")
    if requires_update_replacement_delta_closure(requested_scope):
        return False
    return requested_scope.mutability is CallMutability.IMMUTABLE


@dataclass(frozen=True, slots=True)
class SuccessorUpdateIntent:
    """Immutable daily/monthly request bound to one exact assured baseline."""

    baseline_identity_sha256: str
    planning_generation_manifest_sha256: str
    successor_execution_plan_sha256: str
    planned_route_replacement_bindings_sha256: str
    mode: SuccessorUpdateMode
    source_sha: str
    cutoff_utc: str
    as_of_utc: str
    requested_scopes: tuple[RequestedRouteScope, ...]
    requested_scopes_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        _require_sha256(self.baseline_identity_sha256, field_name="baseline_identity_sha256")
        _require_sha256(
            self.planning_generation_manifest_sha256,
            field_name="planning_generation_manifest_sha256",
        )
        _require_sha256(
            self.successor_execution_plan_sha256,
            field_name="successor_execution_plan_sha256",
        )
        _require_sha256(
            self.planned_route_replacement_bindings_sha256,
            field_name="planned_route_replacement_bindings_sha256",
        )
        if not isinstance(self.mode, SuccessorUpdateMode):
            raise SuccessorUpdateContractError("mode must be a SuccessorUpdateMode")
        _require_source_sha(self.source_sha)
        cutoff = _require_utc_instant(self.cutoff_utc, field_name="cutoff_utc")
        as_of = _require_utc_instant(self.as_of_utc, field_name="as_of_utc")
        if cutoff > as_of:
            raise SuccessorUpdateContractError("cutoff_utc must not be after as_of_utc")

        scopes = tuple(self.requested_scopes)
        if not scopes:
            raise SuccessorUpdateContractError("requested scope inventory must be nonempty")
        if any(not isinstance(scope, RequestedRouteScope) for scope in scopes):
            raise SuccessorUpdateContractError(
                "requested scopes must be RequestedRouteScope values"
            )
        scopes = tuple(sorted(scopes, key=lambda scope: scope.identity_sha256))
        uniqueness_keys = [scope.uniqueness_key for scope in scopes]
        if len(uniqueness_keys) != len(set(uniqueness_keys)):
            raise SuccessorUpdateContractError("requested scope inventory contains duplicates")
        object.__setattr__(self, "requested_scopes", scopes)
        object.__setattr__(
            self,
            "requested_scopes_sha256",
            canonical_sha256([scope.to_dict() for scope in scopes]),
        )

    @property
    def identity_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_identity_sha256": self.baseline_identity_sha256,
            "planning_generation_manifest_sha256": (self.planning_generation_manifest_sha256),
            "successor_execution_plan_sha256": self.successor_execution_plan_sha256,
            "planned_route_replacement_bindings_sha256": (
                self.planned_route_replacement_bindings_sha256
            ),
            "mode": self.mode.value,
            "source_sha": self.source_sha,
            "cutoff_utc": self.cutoff_utc,
            "as_of_utc": self.as_of_utc,
            "requested_scopes": [scope.to_dict() for scope in self.requested_scopes],
            "requested_scopes_sha256": self.requested_scopes_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "baseline_identity_sha256",
                    "planning_generation_manifest_sha256",
                    "successor_execution_plan_sha256",
                    "planned_route_replacement_bindings_sha256",
                    "mode",
                    "source_sha",
                    "cutoff_utc",
                    "as_of_utc",
                    "requested_scopes",
                    "requested_scopes_sha256",
                }
            ),
            label="successor update intent",
        )
        raw_mode = _require_safe_token(payload["mode"], field_name="mode")
        try:
            mode = SuccessorUpdateMode(raw_mode)
        except ValueError as exc:
            raise SuccessorUpdateContractError(
                f"unsupported successor update mode: {raw_mode}"
            ) from exc
        raw_scopes = _require_sequence(payload["requested_scopes"], field_name="requested_scopes")
        result = cls(
            baseline_identity_sha256=_require_sha256(
                payload["baseline_identity_sha256"], field_name="baseline_identity_sha256"
            ),
            planning_generation_manifest_sha256=_require_sha256(
                payload["planning_generation_manifest_sha256"],
                field_name="planning_generation_manifest_sha256",
            ),
            successor_execution_plan_sha256=_require_sha256(
                payload["successor_execution_plan_sha256"],
                field_name="successor_execution_plan_sha256",
            ),
            planned_route_replacement_bindings_sha256=_require_sha256(
                payload["planned_route_replacement_bindings_sha256"],
                field_name="planned_route_replacement_bindings_sha256",
            ),
            mode=mode,
            source_sha=_require_source_sha(payload["source_sha"]),
            cutoff_utc=_require_utc_instant(payload["cutoff_utc"], field_name="cutoff_utc"),
            as_of_utc=_require_utc_instant(payload["as_of_utc"], field_name="as_of_utc"),
            requested_scopes=tuple(
                RequestedRouteScope.from_dict(
                    _require_mapping(raw_scope, field_name=f"requested_scopes[{index}]")
                )
                for index, raw_scope in enumerate(raw_scopes)
            ),
        )
        if result.requested_scopes_sha256 != _require_sha256(
            payload["requested_scopes_sha256"], field_name="requested_scopes_sha256"
        ):
            raise SuccessorUpdateContractError(
                "requested scope inventory digest does not match its inventory"
            )
        return result


@dataclass(frozen=True, slots=True)
class ObservedDeltaReceipt:
    """Receipt for a fresh successor observation of one requested route/scope."""

    baseline_identity_sha256: str
    update_intent_sha256: str
    source_sha: str
    requested_scope_sha256: str
    execution_dispatch_identity_sha256: str
    planning_dependency_identity_sha256s: tuple[str, ...]
    disposition: DeltaDisposition
    logical_call_receipt_sha256: str
    prior_persisted_content_sha256: str | None
    source_scope_replacement_sha256: str
    persisted_content_sha256: str
    persisted_schema_sha256: str
    persisted_row_count: int
    typed_zero_reason_code: str | None = None

    def __post_init__(self) -> None:
        _require_sha256(self.baseline_identity_sha256, field_name="baseline_identity_sha256")
        _require_sha256(self.update_intent_sha256, field_name="update_intent_sha256")
        _require_source_sha(self.source_sha)
        _require_sha256(self.requested_scope_sha256, field_name="requested_scope_sha256")
        _require_sha256(
            self.execution_dispatch_identity_sha256,
            field_name="execution_dispatch_identity_sha256",
        )
        _require_sha256_tuple(
            self.planning_dependency_identity_sha256s,
            field_name="planning_dependency_identity_sha256s",
        )
        if not isinstance(self.disposition, DeltaDisposition):
            raise SuccessorUpdateContractError("disposition must be a DeltaDisposition")
        _require_sha256(self.logical_call_receipt_sha256, field_name="logical_call_receipt_sha256")
        if self.prior_persisted_content_sha256 is not None:
            _require_sha256(
                self.prior_persisted_content_sha256,
                field_name="prior_persisted_content_sha256",
            )
        _require_sha256(
            self.source_scope_replacement_sha256,
            field_name="source_scope_replacement_sha256",
        )
        _require_sha256(self.persisted_content_sha256, field_name="persisted_content_sha256")
        _require_sha256(self.persisted_schema_sha256, field_name="persisted_schema_sha256")
        _require_nonnegative_int(self.persisted_row_count, field_name="persisted_row_count")

        if self.disposition is DeltaDisposition.OBSERVED:
            if self.persisted_row_count == 0:
                raise SuccessorUpdateContractError(
                    "zero-row observations must use the explicit typed_zero disposition"
                )
            if self.typed_zero_reason_code is not None:
                raise SuccessorUpdateContractError(
                    "observed delta receipt cannot contain a typed-zero reason"
                )
        else:
            if self.persisted_row_count != 0:
                raise SuccessorUpdateContractError(
                    "typed-zero delta receipt must have a zero row count"
                )
            _require_reason_code(self.typed_zero_reason_code, field_name="typed_zero_reason_code")

    @property
    def identity_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    @property
    def planned_route_replacement_binding(self) -> PlannedRouteReplacementBinding:
        return PlannedRouteReplacementBinding(
            requested_scope_sha256=self.requested_scope_sha256,
            execution_dispatch_identity_sha256=self.execution_dispatch_identity_sha256,
            planning_dependency_identity_sha256s=(self.planning_dependency_identity_sha256s),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_identity_sha256": self.baseline_identity_sha256,
            "update_intent_sha256": self.update_intent_sha256,
            "source_sha": self.source_sha,
            "requested_scope_sha256": self.requested_scope_sha256,
            "execution_dispatch_identity_sha256": (self.execution_dispatch_identity_sha256),
            "planning_dependency_identity_sha256s": list(self.planning_dependency_identity_sha256s),
            "disposition": self.disposition.value,
            "logical_call_receipt_sha256": self.logical_call_receipt_sha256,
            "prior_persisted_content_sha256": self.prior_persisted_content_sha256,
            "source_scope_replacement_sha256": self.source_scope_replacement_sha256,
            "persisted_content_sha256": self.persisted_content_sha256,
            "persisted_schema_sha256": self.persisted_schema_sha256,
            "persisted_row_count": self.persisted_row_count,
            "typed_zero_reason_code": self.typed_zero_reason_code,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "baseline_identity_sha256",
                    "update_intent_sha256",
                    "source_sha",
                    "requested_scope_sha256",
                    "execution_dispatch_identity_sha256",
                    "planning_dependency_identity_sha256s",
                    "disposition",
                    "logical_call_receipt_sha256",
                    "prior_persisted_content_sha256",
                    "source_scope_replacement_sha256",
                    "persisted_content_sha256",
                    "persisted_schema_sha256",
                    "persisted_row_count",
                    "typed_zero_reason_code",
                }
            ),
            label="observed delta receipt",
        )
        raw_disposition = _require_safe_token(payload["disposition"], field_name="disposition")
        try:
            disposition = DeltaDisposition(raw_disposition)
        except ValueError as exc:
            raise SuccessorUpdateContractError(
                f"unsupported delta disposition: {raw_disposition}"
            ) from exc
        raw_reason = payload["typed_zero_reason_code"]
        if raw_reason is not None and not isinstance(raw_reason, str):
            raise SuccessorUpdateContractError(
                "typed_zero_reason_code must be a stable reason code or null"
            )
        raw_prior_content = payload["prior_persisted_content_sha256"]
        if raw_prior_content is not None:
            raw_prior_content = _require_sha256(
                raw_prior_content,
                field_name="prior_persisted_content_sha256",
            )
        return cls(
            baseline_identity_sha256=_require_sha256(
                payload["baseline_identity_sha256"], field_name="baseline_identity_sha256"
            ),
            update_intent_sha256=_require_sha256(
                payload["update_intent_sha256"], field_name="update_intent_sha256"
            ),
            source_sha=_require_source_sha(payload["source_sha"]),
            requested_scope_sha256=_require_sha256(
                payload["requested_scope_sha256"], field_name="requested_scope_sha256"
            ),
            execution_dispatch_identity_sha256=_require_sha256(
                payload["execution_dispatch_identity_sha256"],
                field_name="execution_dispatch_identity_sha256",
            ),
            planning_dependency_identity_sha256s=_sha256_tuple_from_list(
                payload["planning_dependency_identity_sha256s"],
                field_name="planning_dependency_identity_sha256s",
            ),
            disposition=disposition,
            logical_call_receipt_sha256=_require_sha256(
                payload["logical_call_receipt_sha256"],
                field_name="logical_call_receipt_sha256",
            ),
            prior_persisted_content_sha256=raw_prior_content,
            source_scope_replacement_sha256=_require_sha256(
                payload["source_scope_replacement_sha256"],
                field_name="source_scope_replacement_sha256",
            ),
            persisted_content_sha256=_require_sha256(
                payload["persisted_content_sha256"], field_name="persisted_content_sha256"
            ),
            persisted_schema_sha256=_require_sha256(
                payload["persisted_schema_sha256"], field_name="persisted_schema_sha256"
            ),
            persisted_row_count=_require_nonnegative_int(
                payload["persisted_row_count"], field_name="persisted_row_count"
            ),
            typed_zero_reason_code=raw_reason,
        )


@dataclass(frozen=True, slots=True)
class SuccessorGenerationBuild:
    """Exact receipt inventory produced while building a successor generation."""

    baseline_identity_sha256: str
    update_intent_sha256: str
    source_sha: str
    observed_delta_receipts: tuple[ObservedDeltaReceipt, ...]
    observed_delta_receipts_sha256: str = field(init=False)
    planned_route_replacement_bindings: tuple[PlannedRouteReplacementBinding, ...] = field(
        init=False
    )
    planned_route_replacement_bindings_sha256: str = field(init=False)

    def __post_init__(self) -> None:
        _require_sha256(self.baseline_identity_sha256, field_name="baseline_identity_sha256")
        _require_sha256(self.update_intent_sha256, field_name="update_intent_sha256")
        _require_source_sha(self.source_sha)
        receipts = tuple(self.observed_delta_receipts)
        if not receipts:
            raise SuccessorUpdateContractError("observed delta receipt inventory must be nonempty")
        if any(not isinstance(receipt, ObservedDeltaReceipt) for receipt in receipts):
            raise SuccessorUpdateContractError(
                "observed delta receipts must be ObservedDeltaReceipt values"
            )
        mismatches: list[str] = []
        for receipt in receipts:
            if receipt.baseline_identity_sha256 != self.baseline_identity_sha256:
                mismatches.append("baseline_identity_sha256")
            if receipt.update_intent_sha256 != self.update_intent_sha256:
                mismatches.append("update_intent_sha256")
            if receipt.source_sha != self.source_sha:
                mismatches.append("source_sha")
        if mismatches:
            raise SuccessorUpdateContractError(
                "observed delta receipt authority does not match the build: "
                + ", ".join(sorted(set(mismatches)))
            )
        receipts = tuple(sorted(receipts, key=lambda receipt: receipt.requested_scope_sha256))
        scope_ids = [receipt.requested_scope_sha256 for receipt in receipts]
        if len(scope_ids) != len(set(scope_ids)):
            raise SuccessorUpdateContractError(
                "observed delta receipt inventory contains duplicate scopes"
            )
        dispatch_to_call: dict[str, str] = {}
        call_to_dispatch: dict[str, str] = {}
        dispatch_to_dependencies: dict[str, tuple[str, ...]] = {}
        for receipt in receipts:
            dispatch_id = receipt.execution_dispatch_identity_sha256
            call_id = receipt.logical_call_receipt_sha256
            prior_call = dispatch_to_call.setdefault(dispatch_id, call_id)
            if prior_call != call_id:
                raise SuccessorUpdateContractError(
                    "one execution dispatch is split across logical call receipts"
                )
            prior_dispatch = call_to_dispatch.setdefault(call_id, dispatch_id)
            if prior_dispatch != dispatch_id:
                raise SuccessorUpdateContractError(
                    "one logical call receipt is relabelled across execution dispatches"
                )
            prior_dependencies = dispatch_to_dependencies.setdefault(
                dispatch_id,
                receipt.planning_dependency_identity_sha256s,
            )
            if prior_dependencies != receipt.planning_dependency_identity_sha256s:
                raise SuccessorUpdateContractError(
                    "one execution dispatch has inconsistent planning dependencies"
                )
        bindings = _canonical_planned_route_replacement_bindings(
            tuple(receipt.planned_route_replacement_binding for receipt in receipts)
        )
        object.__setattr__(self, "observed_delta_receipts", receipts)
        object.__setattr__(
            self,
            "observed_delta_receipts_sha256",
            canonical_sha256([receipt.to_dict() for receipt in receipts]),
        )
        object.__setattr__(self, "planned_route_replacement_bindings", bindings)
        object.__setattr__(
            self,
            "planned_route_replacement_bindings_sha256",
            planned_route_replacement_bindings_sha256(bindings),
        )

    @property
    def identity_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_identity_sha256": self.baseline_identity_sha256,
            "update_intent_sha256": self.update_intent_sha256,
            "source_sha": self.source_sha,
            "observed_delta_receipts": [
                receipt.to_dict() for receipt in self.observed_delta_receipts
            ],
            "observed_delta_receipts_sha256": self.observed_delta_receipts_sha256,
            "planned_route_replacement_bindings": [
                binding.to_dict() for binding in self.planned_route_replacement_bindings
            ],
            "planned_route_replacement_bindings_sha256": (
                self.planned_route_replacement_bindings_sha256
            ),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "baseline_identity_sha256",
                    "update_intent_sha256",
                    "source_sha",
                    "observed_delta_receipts",
                    "observed_delta_receipts_sha256",
                    "planned_route_replacement_bindings",
                    "planned_route_replacement_bindings_sha256",
                }
            ),
            label="successor generation build",
        )
        raw_receipts = _require_sequence(
            payload["observed_delta_receipts"], field_name="observed_delta_receipts"
        )
        raw_bindings = _require_sequence(
            payload["planned_route_replacement_bindings"],
            field_name="planned_route_replacement_bindings",
        )
        supplied_bindings = tuple(
            PlannedRouteReplacementBinding.from_dict(
                _require_mapping(
                    raw_binding,
                    field_name=f"planned_route_replacement_bindings[{index}]",
                )
            )
            for index, raw_binding in enumerate(raw_bindings)
        )
        canonical_supplied_bindings = _canonical_planned_route_replacement_bindings(
            supplied_bindings
        )
        if supplied_bindings != canonical_supplied_bindings:
            raise SuccessorUpdateContractError(
                "planned route replacement bindings must use canonical scope order"
            )
        result = cls(
            baseline_identity_sha256=_require_sha256(
                payload["baseline_identity_sha256"], field_name="baseline_identity_sha256"
            ),
            update_intent_sha256=_require_sha256(
                payload["update_intent_sha256"], field_name="update_intent_sha256"
            ),
            source_sha=_require_source_sha(payload["source_sha"]),
            observed_delta_receipts=tuple(
                ObservedDeltaReceipt.from_dict(
                    _require_mapping(raw_receipt, field_name=f"observed_delta_receipts[{index}]")
                )
                for index, raw_receipt in enumerate(raw_receipts)
            ),
        )
        if result.observed_delta_receipts_sha256 != _require_sha256(
            payload["observed_delta_receipts_sha256"],
            field_name="observed_delta_receipts_sha256",
        ):
            raise SuccessorUpdateContractError(
                "observed delta receipt digest does not match its inventory"
            )
        if result.planned_route_replacement_bindings != supplied_bindings:
            raise SuccessorUpdateContractError(
                "planned route replacement binding inventory does not match receipts"
            )
        if result.planned_route_replacement_bindings_sha256 != _require_sha256(
            payload["planned_route_replacement_bindings_sha256"],
            field_name="planned_route_replacement_bindings_sha256",
        ):
            raise SuccessorUpdateContractError(
                "planned route replacement binding digest does not match receipts"
            )
        return result


@dataclass(frozen=True, slots=True)
class SuccessorAssuranceIdentity:
    """Validated identity of the candidate data tree after applying the exact delta."""

    baseline_identity_sha256: str
    update_intent_sha256: str
    source_sha: str
    generation: int
    requested_scopes_sha256: str
    observed_delta_receipts_sha256: str
    planned_route_replacement_bindings_sha256: str
    transform_inventory_sha256: str
    scan_report_sha256: str
    publication_resource_inventory_sha256: str
    installed_public_tree_sha256: str
    private_generation_receipt_sha256: str
    successor_data_tree_fingerprint: str
    successor_assured_manifest_sha256: str
    successor_validation_report_sha256: str

    def __post_init__(self) -> None:
        for field_name in (
            "baseline_identity_sha256",
            "update_intent_sha256",
            "requested_scopes_sha256",
            "observed_delta_receipts_sha256",
            "planned_route_replacement_bindings_sha256",
            "transform_inventory_sha256",
            "scan_report_sha256",
            "publication_resource_inventory_sha256",
            "installed_public_tree_sha256",
            "private_generation_receipt_sha256",
            "successor_data_tree_fingerprint",
            "successor_assured_manifest_sha256",
            "successor_validation_report_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        _require_source_sha(self.source_sha)
        _require_positive_int(self.generation, field_name="generation")

    @property
    def identity_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, str | int]:
        return {
            "baseline_identity_sha256": self.baseline_identity_sha256,
            "update_intent_sha256": self.update_intent_sha256,
            "source_sha": self.source_sha,
            "generation": self.generation,
            "requested_scopes_sha256": self.requested_scopes_sha256,
            "observed_delta_receipts_sha256": self.observed_delta_receipts_sha256,
            "planned_route_replacement_bindings_sha256": (
                self.planned_route_replacement_bindings_sha256
            ),
            "transform_inventory_sha256": self.transform_inventory_sha256,
            "scan_report_sha256": self.scan_report_sha256,
            "publication_resource_inventory_sha256": (self.publication_resource_inventory_sha256),
            "installed_public_tree_sha256": self.installed_public_tree_sha256,
            "private_generation_receipt_sha256": self.private_generation_receipt_sha256,
            "successor_data_tree_fingerprint": self.successor_data_tree_fingerprint,
            "successor_assured_manifest_sha256": self.successor_assured_manifest_sha256,
            "successor_validation_report_sha256": self.successor_validation_report_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "baseline_identity_sha256",
                "update_intent_sha256",
                "source_sha",
                "generation",
                "requested_scopes_sha256",
                "observed_delta_receipts_sha256",
                "planned_route_replacement_bindings_sha256",
                "transform_inventory_sha256",
                "scan_report_sha256",
                "publication_resource_inventory_sha256",
                "installed_public_tree_sha256",
                "private_generation_receipt_sha256",
                "successor_data_tree_fingerprint",
                "successor_assured_manifest_sha256",
                "successor_validation_report_sha256",
            }
        )
        _require_exact_keys(payload, expected=expected, label="successor assurance identity")
        return cls(
            baseline_identity_sha256=_require_sha256(
                payload["baseline_identity_sha256"], field_name="baseline_identity_sha256"
            ),
            update_intent_sha256=_require_sha256(
                payload["update_intent_sha256"], field_name="update_intent_sha256"
            ),
            source_sha=_require_source_sha(payload["source_sha"]),
            generation=_require_positive_int(payload["generation"], field_name="generation"),
            requested_scopes_sha256=_require_sha256(
                payload["requested_scopes_sha256"], field_name="requested_scopes_sha256"
            ),
            observed_delta_receipts_sha256=_require_sha256(
                payload["observed_delta_receipts_sha256"],
                field_name="observed_delta_receipts_sha256",
            ),
            planned_route_replacement_bindings_sha256=_require_sha256(
                payload["planned_route_replacement_bindings_sha256"],
                field_name="planned_route_replacement_bindings_sha256",
            ),
            transform_inventory_sha256=_require_sha256(
                payload["transform_inventory_sha256"],
                field_name="transform_inventory_sha256",
            ),
            scan_report_sha256=_require_sha256(
                payload["scan_report_sha256"],
                field_name="scan_report_sha256",
            ),
            publication_resource_inventory_sha256=_require_sha256(
                payload["publication_resource_inventory_sha256"],
                field_name="publication_resource_inventory_sha256",
            ),
            installed_public_tree_sha256=_require_sha256(
                payload["installed_public_tree_sha256"],
                field_name="installed_public_tree_sha256",
            ),
            private_generation_receipt_sha256=_require_sha256(
                payload["private_generation_receipt_sha256"],
                field_name="private_generation_receipt_sha256",
            ),
            successor_data_tree_fingerprint=_require_sha256(
                payload["successor_data_tree_fingerprint"],
                field_name="successor_data_tree_fingerprint",
            ),
            successor_assured_manifest_sha256=_require_sha256(
                payload["successor_assured_manifest_sha256"],
                field_name="successor_assured_manifest_sha256",
            ),
            successor_validation_report_sha256=_require_sha256(
                payload["successor_validation_report_sha256"],
                field_name="successor_validation_report_sha256",
            ),
        )


@dataclass(frozen=True, slots=True)
class SuccessorUpdateTransaction:
    """Four-state transaction for replacing one exact fully assured baseline."""

    state: SuccessorGenerationState
    generation: int
    baseline: BaselineAssuranceIdentity
    intent: SuccessorUpdateIntent
    build: SuccessorGenerationBuild | None = None
    assurance: SuccessorAssuranceIdentity | None = None

    schema_version: ClassVar[int] = SUCCESSOR_UPDATE_CONTRACT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.state, SuccessorGenerationState):
            raise SuccessorUpdateContractError("state must be a SuccessorGenerationState")
        _require_positive_int(self.generation, field_name="generation")
        if not isinstance(self.baseline, BaselineAssuranceIdentity):
            raise SuccessorUpdateContractError("baseline must be a BaselineAssuranceIdentity")
        if not isinstance(self.intent, SuccessorUpdateIntent):
            raise SuccessorUpdateContractError("intent must be a SuccessorUpdateIntent")
        if self.intent.baseline_identity_sha256 != self.baseline.identity_sha256:
            raise SuccessorUpdateContractError("update intent baseline identity does not match")

        expects_build = self.state is not SuccessorGenerationState.CANDIDATE
        expects_assurance = self.state in {
            SuccessorGenerationState.VALIDATED,
            SuccessorGenerationState.PROMOTED,
        }
        if (self.build is not None) != expects_build:
            raise SuccessorUpdateContractError(
                f"{self.state.value} successor has an invalid build contract"
            )
        if (self.assurance is not None) != expects_assurance:
            raise SuccessorUpdateContractError(
                f"{self.state.value} successor has an invalid assurance identity"
            )
        if self.build is not None:
            if not isinstance(self.build, SuccessorGenerationBuild):
                raise SuccessorUpdateContractError("build must be a SuccessorGenerationBuild")
            self._validate_build(self.build)
        if self.assurance is not None:
            if not isinstance(self.assurance, SuccessorAssuranceIdentity):
                raise SuccessorUpdateContractError("assurance must be a SuccessorAssuranceIdentity")
            assert self.build is not None
            self._validate_assurance(self.assurance, build=self.build)

    @property
    def generation_identity_sha256(self) -> str:
        """Return the state-independent identity used by journals and candidates."""

        return canonical_sha256(
            {
                "generation": self.generation,
                "baseline_identity_sha256": self.baseline.identity_sha256,
                "update_intent_sha256": self.intent.identity_sha256,
            }
        )

    @classmethod
    def candidate(
        cls,
        *,
        generation: int,
        baseline: BaselineAssuranceIdentity,
        intent: SuccessorUpdateIntent,
    ) -> Self:
        return cls(
            state=SuccessorGenerationState.CANDIDATE,
            generation=generation,
            baseline=baseline,
            intent=intent,
        )

    def mark_built(
        self,
        *,
        observed_delta_receipts: Sequence[ObservedDeltaReceipt],
    ) -> Self:
        self._require_state(SuccessorGenerationState.CANDIDATE, operation="mark built")
        build = SuccessorGenerationBuild(
            baseline_identity_sha256=self.baseline.identity_sha256,
            update_intent_sha256=self.intent.identity_sha256,
            source_sha=self.intent.source_sha,
            observed_delta_receipts=tuple(observed_delta_receipts),
        )
        self._validate_build(build)
        return replace(
            self,
            state=SuccessorGenerationState.BUILT,
            build=build,
        )

    def mark_validated(self, assurance: SuccessorAssuranceIdentity) -> Self:
        self._require_state(SuccessorGenerationState.BUILT, operation="mark validated")
        assert self.build is not None
        self._validate_assurance(assurance, build=self.build)
        return replace(
            self,
            state=SuccessorGenerationState.VALIDATED,
            assurance=assurance,
        )

    def promote(self) -> Self:
        self._require_state(SuccessorGenerationState.VALIDATED, operation="promote")
        return replace(self, state=SuccessorGenerationState.PROMOTED)

    @property
    def promoted_assurance(self) -> SuccessorAssuranceIdentity:
        self._require_state(
            SuccessorGenerationState.PROMOTED,
            operation="read promoted assurance",
        )
        assert self.assurance is not None
        return self.assurance

    def _require_state(self, expected: SuccessorGenerationState, *, operation: str) -> None:
        if self.state is expected:
            return
        raise SuccessorUpdateTransitionError(
            f"cannot {operation} successor from {self.state.value}; expected {expected.value}"
        )

    def _validate_build(self, build: SuccessorGenerationBuild) -> None:
        mismatches: list[str] = []
        if build.baseline_identity_sha256 != self.baseline.identity_sha256:
            mismatches.append("baseline_identity_sha256")
        if build.update_intent_sha256 != self.intent.identity_sha256:
            mismatches.append("update_intent_sha256")
        if build.source_sha != self.intent.source_sha:
            mismatches.append("source_sha")
        for receipt in build.observed_delta_receipts:
            if receipt.baseline_identity_sha256 != self.baseline.identity_sha256:
                mismatches.append("receipt.baseline_identity_sha256")
            if receipt.update_intent_sha256 != self.intent.identity_sha256:
                mismatches.append("receipt.update_intent_sha256")
            if receipt.source_sha != self.intent.source_sha:
                mismatches.append("receipt.source_sha")
        if mismatches:
            raise SuccessorUpdateContractError(
                "successor build authority does not match: " + ", ".join(sorted(set(mismatches)))
            )

        expected = {scope.identity_sha256 for scope in self.intent.requested_scopes}
        observed = {receipt.requested_scope_sha256 for receipt in build.observed_delta_receipts}
        if expected != observed:
            missing = sorted(expected - observed)
            unexpected = sorted(observed - expected)
            details: list[str] = []
            if missing:
                details.append("missing=" + ",".join(missing))
            if unexpected:
                details.append("unexpected=" + ",".join(unexpected))
            raise SuccessorUpdateContractError(
                "observed delta receipts do not exactly cover requested scopes: "
                + "; ".join(details)
            )
        binding_scopes = {
            binding.requested_scope_sha256 for binding in build.planned_route_replacement_bindings
        }
        if binding_scopes != expected:
            raise SuccessorUpdateContractError(
                "planned route replacement bindings do not exactly cover requested scopes"
            )
        if (
            build.planned_route_replacement_bindings_sha256
            != self.intent.planned_route_replacement_bindings_sha256
        ):
            raise SuccessorUpdateContractError(
                "observed planned route replacement bindings differ from the sealed plan"
            )
        require_live_and_scoreboard_update_delta_closure(
            self.intent.requested_scopes,
            observed_delta_receipts=build.observed_delta_receipts,
            evidence_kind=UpdateScopeClosureEvidenceKind.OBSERVED_DELTA_REPLACEMENT,
        )

    def _validate_assurance(
        self,
        assurance: SuccessorAssuranceIdentity,
        *,
        build: SuccessorGenerationBuild,
    ) -> None:
        expected: tuple[tuple[str, object, object], ...] = (
            (
                "baseline_identity_sha256",
                assurance.baseline_identity_sha256,
                self.baseline.identity_sha256,
            ),
            (
                "update_intent_sha256",
                assurance.update_intent_sha256,
                self.intent.identity_sha256,
            ),
            ("source_sha", assurance.source_sha, self.intent.source_sha),
            ("generation", assurance.generation, self.generation),
            (
                "requested_scopes_sha256",
                assurance.requested_scopes_sha256,
                self.intent.requested_scopes_sha256,
            ),
            (
                "observed_delta_receipts_sha256",
                assurance.observed_delta_receipts_sha256,
                build.observed_delta_receipts_sha256,
            ),
            (
                "planned_route_replacement_bindings_sha256",
                assurance.planned_route_replacement_bindings_sha256,
                build.planned_route_replacement_bindings_sha256,
            ),
        )
        mismatches = [field_name for field_name, actual, wanted in expected if actual != wanted]
        if mismatches:
            raise SuccessorUpdateContractError(
                "successor assurance does not match the built candidate: " + ", ".join(mismatches)
            )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "kind": "successor_update_transaction",
            "state": self.state.value,
            "generation": self.generation,
            "baseline": self.baseline.to_dict(),
            "intent": self.intent.to_dict(),
        }
        if self.build is not None:
            payload["build"] = self.build.to_dict()
        if self.assurance is not None:
            payload["assurance"] = self.assurance.to_dict()
        return payload

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes).hexdigest()

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        raw_state = _require_safe_token(payload.get("state"), field_name="state")
        try:
            state = SuccessorGenerationState(raw_state)
        except ValueError as exc:
            raise SuccessorUpdateContractError(
                f"unsupported successor generation state: {raw_state}"
            ) from exc

        expected = {
            "schema_version",
            "kind",
            "state",
            "generation",
            "baseline",
            "intent",
        }
        if state is not SuccessorGenerationState.CANDIDATE:
            expected.add("build")
        if state in {
            SuccessorGenerationState.VALIDATED,
            SuccessorGenerationState.PROMOTED,
        }:
            expected.add("assurance")
        _require_exact_keys(
            payload,
            expected=frozenset(expected),
            label=f"{state.value} successor update transaction",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
        ):
            raise SuccessorUpdateContractError(
                "successor update transaction has an unsupported schema version"
            )
        if payload["kind"] != "successor_update_transaction":
            raise SuccessorUpdateContractError("successor update transaction kind is invalid")

        build = (
            SuccessorGenerationBuild.from_dict(
                _require_mapping(payload["build"], field_name="build")
            )
            if state is not SuccessorGenerationState.CANDIDATE
            else None
        )
        assurance = (
            SuccessorAssuranceIdentity.from_dict(
                _require_mapping(payload["assurance"], field_name="assurance")
            )
            if state in {SuccessorGenerationState.VALIDATED, SuccessorGenerationState.PROMOTED}
            else None
        )
        return cls(
            state=state,
            generation=_require_positive_int(payload["generation"], field_name="generation"),
            baseline=BaselineAssuranceIdentity.from_dict(
                _require_mapping(payload["baseline"], field_name="baseline")
            ),
            intent=SuccessorUpdateIntent.from_dict(
                _require_mapping(payload["intent"], field_name="intent")
            ),
            build=build,
            assurance=assurance,
        )
