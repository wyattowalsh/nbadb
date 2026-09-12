"""Strict UPDATE-only execution view over one sealed planning generation.

This module does not execute providers or authorize a production run.  It
projects the UPDATE phase of a validated :class:`PlanningGenerationManifest`
without deriving, widening, or rewriting any provider call.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any, ClassVar, Self, cast

from nbadb.orchestrate.successor_planning_generation_contract import (
    PlanningDispatchPhase,
    PlanningGenerationManifest,
    SealedProviderDispatch,
    SuccessorPlanningGenerationContractError,
    canonical_planning_json_bytes,
    canonical_planning_sha256,
)
from nbadb.orchestrate.successor_update_contract import (
    CallMutability,
    PlannedRouteReplacementBinding,
    RequestedRouteScope,
    SuccessorUpdateContractError,
    planned_route_replacement_bindings_sha256,
)

__all__ = [
    "SUCCESSOR_EXECUTION_PLAN_SCHEMA_VERSION",
    "SealedUpdateExecutionDispatch",
    "SuccessorExecutionPlan",
    "SuccessorExecutionPlanError",
    "SuccessorExecutionPlanPublicIdentity",
    "build_successor_execution_plan",
]

SUCCESSOR_EXECUTION_PLAN_SCHEMA_VERSION = 2
_SAFE_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}")


class SuccessorExecutionPlanError(ValueError):
    """Raised when a purported execution plan widens or rewrites its manifest."""


def _require_exact_keys(
    payload: Mapping[str, object],
    *,
    expected: frozenset[str],
    label: str,
) -> None:
    if frozenset(payload) != expected:
        raise SuccessorExecutionPlanError(f"{label} fields are invalid")


def _require_sha256(value: object, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SuccessorExecutionPlanError(f"{field_name} must be a lowercase SHA-256")
    return value


def _require_token(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SAFE_TOKEN_RE.fullmatch(value) is None:
        raise SuccessorExecutionPlanError(f"{field_name} must be an exact safe token")
    return value


def _require_mapping(value: object, *, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise SuccessorExecutionPlanError(f"{field_name} must be an object")
    return cast("Mapping[str, object]", value)


@dataclass(frozen=True, slots=True)
class SealedUpdateExecutionDispatch:
    """One exact UPDATE provider call copied from the sealed manifest."""

    order: int
    sealed_dispatch: SealedProviderDispatch
    requested_scopes: tuple[RequestedRouteScope, ...]

    schema_version: ClassVar[int] = SUCCESSOR_EXECUTION_PLAN_SCHEMA_VERSION
    kind: ClassVar[str] = "sealed_update_execution_dispatch"

    def __post_init__(self) -> None:
        if type(self.order) is not int or self.order < 0:
            raise SuccessorExecutionPlanError("dispatch order must be nonnegative")
        if not isinstance(self.sealed_dispatch, SealedProviderDispatch):
            raise SuccessorExecutionPlanError("sealed_dispatch must be a SealedProviderDispatch")
        if self.sealed_dispatch.phase is not PlanningDispatchPhase.UPDATE:
            raise SuccessorExecutionPlanError("execution dispatch phase must be update")
        if type(self.requested_scopes) is not tuple or not self.requested_scopes:
            raise SuccessorExecutionPlanError("requested_scopes must be a nonempty immutable tuple")
        if any(not isinstance(scope, RequestedRouteScope) for scope in self.requested_scopes):
            raise SuccessorExecutionPlanError(
                "requested_scopes must contain RequestedRouteScope values"
            )
        dispatch = self.sealed_dispatch
        if tuple(scope.identity_sha256 for scope in self.requested_scopes) != (
            dispatch.requested_scope_identity_sha256s
        ):
            raise SuccessorExecutionPlanError(
                "execution scopes differ from the sealed dispatch inventory"
            )
        if tuple(scope.route_id for scope in self.requested_scopes) != dispatch.staging_route_ids:
            raise SuccessorExecutionPlanError(
                "execution routes differ from the sealed dispatch inventory"
            )
        for scope in self.requested_scopes:
            if scope.endpoint_name != dispatch.endpoint_name:
                raise SuccessorExecutionPlanError(
                    "execution scope endpoint differs from the sealed dispatch"
                )
            if scope.parameters != dispatch.parameters:
                raise SuccessorExecutionPlanError(
                    "execution scope parameters differ from the sealed dispatch"
                )

    @property
    def endpoint_name(self) -> str:
        return self.sealed_dispatch.endpoint_name

    @property
    def parameters(self) -> dict[str, Any]:
        """Return a detached canonical provider-parameter mapping."""

        return self.sealed_dispatch.parameters

    @property
    def parameters_sha256(self) -> str:
        return self.sealed_dispatch.parameters_sha256

    @property
    def pattern(self) -> str:
        return self.sealed_dispatch.pattern

    @property
    def requested_scope_identity_sha256s(self) -> tuple[str, ...]:
        return self.sealed_dispatch.requested_scope_identity_sha256s

    @property
    def staging_route_ids(self) -> tuple[str, ...]:
        return self.sealed_dispatch.staging_route_ids

    @property
    def route_contract_sha256s(self) -> tuple[str, ...]:
        return tuple(scope.route_contract_sha256 for scope in self.requested_scopes)

    @property
    def mutabilities(self) -> tuple[CallMutability, ...]:
        return tuple(scope.mutability for scope in self.requested_scopes)

    @property
    def dependency_identity_sha256s(self) -> tuple[str, ...]:
        return self.sealed_dispatch.dependency_identity_sha256s

    @property
    def identity_sha256(self) -> str:
        return canonical_planning_sha256(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "order": self.order,
            "sealed_dispatch": self.sealed_dispatch.to_dict(),
            "sealed_dispatch_identity_sha256": self.sealed_dispatch.identity_sha256,
            "requested_scopes": [scope.to_dict() for scope in self.requested_scopes],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "order",
                    "sealed_dispatch",
                    "sealed_dispatch_identity_sha256",
                    "requested_scopes",
                }
            ),
            label="sealed update execution dispatch",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise SuccessorExecutionPlanError("sealed update execution dispatch schema is invalid")
        raw_order = payload["order"]
        if type(raw_order) is not int:
            raise SuccessorExecutionPlanError("dispatch order must be an integer")
        raw_scopes = payload["requested_scopes"]
        if not isinstance(raw_scopes, list):
            raise SuccessorExecutionPlanError("requested_scopes must be a list")
        try:
            dispatch = SealedProviderDispatch.from_dict(
                _require_mapping(payload["sealed_dispatch"], field_name="sealed_dispatch")
            )
            scopes = tuple(
                RequestedRouteScope.from_dict(
                    _require_mapping(scope, field_name=f"requested_scopes[{index}]")
                )
                for index, scope in enumerate(raw_scopes)
            )
        except (
            SuccessorPlanningGenerationContractError,
            SuccessorUpdateContractError,
        ) as exc:
            raise SuccessorExecutionPlanError(
                f"nested execution dispatch is invalid: {exc}"
            ) from exc
        if dispatch.identity_sha256 != _require_sha256(
            payload["sealed_dispatch_identity_sha256"],
            field_name="sealed_dispatch_identity_sha256",
        ):
            raise SuccessorExecutionPlanError("sealed dispatch identity digest differs")
        return cls(order=raw_order, sealed_dispatch=dispatch, requested_scopes=scopes)


@dataclass(frozen=True, slots=True)
class SuccessorExecutionPlan:
    """Canonical UPDATE-only execution authority derived from one manifest."""

    baseline_identity_sha256: str
    planning_generation_id: str
    planning_request_sha256: str
    planning_artifact_identity_sha256: str
    planning_manifest_sha256: str
    sealed_dispatch_inventory_sha256: str
    requested_route_scopes_sha256: str
    dispatches: tuple[SealedUpdateExecutionDispatch, ...]
    planned_route_replacement_bindings: tuple[PlannedRouteReplacementBinding, ...] = (
        dataclass_field(init=False)
    )
    planned_route_replacement_bindings_sha256: str = dataclass_field(init=False)

    schema_version: ClassVar[int] = SUCCESSOR_EXECUTION_PLAN_SCHEMA_VERSION
    kind: ClassVar[str] = "successor_execution_plan"

    def __post_init__(self) -> None:
        for field_name in (
            "baseline_identity_sha256",
            "planning_request_sha256",
            "planning_artifact_identity_sha256",
            "planning_manifest_sha256",
            "sealed_dispatch_inventory_sha256",
            "requested_route_scopes_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        _require_token(self.planning_generation_id, field_name="planning_generation_id")
        if type(self.dispatches) is not tuple or not self.dispatches:
            raise SuccessorExecutionPlanError("dispatches must be a nonempty immutable tuple")
        if any(
            not isinstance(dispatch, SealedUpdateExecutionDispatch) for dispatch in self.dispatches
        ):
            raise SuccessorExecutionPlanError(
                "dispatches must contain SealedUpdateExecutionDispatch values"
            )
        if tuple(dispatch.order for dispatch in self.dispatches) != tuple(
            range(len(self.dispatches))
        ):
            raise SuccessorExecutionPlanError(
                "execution dispatch order must be contiguous from zero"
            )
        scope_ids = [
            scope_id
            for dispatch in self.dispatches
            for scope_id in dispatch.requested_scope_identity_sha256s
        ]
        if len(scope_ids) != len(set(scope_ids)):
            raise SuccessorExecutionPlanError("an update scope is dispatched more than once")
        logical_call_keys = [
            (dispatch.endpoint_name, dispatch.parameters_sha256) for dispatch in self.dispatches
        ]
        if len(logical_call_keys) != len(set(logical_call_keys)):
            raise SuccessorExecutionPlanError(
                "a logical provider call is dispatched more than once"
            )
        try:
            bindings = tuple(
                sorted(
                    (
                        PlannedRouteReplacementBinding(
                            requested_scope_sha256=scope_id,
                            execution_dispatch_identity_sha256=dispatch.identity_sha256,
                            planning_dependency_identity_sha256s=(
                                dispatch.dependency_identity_sha256s
                            ),
                        )
                        for dispatch in self.dispatches
                        for scope_id in dispatch.requested_scope_identity_sha256s
                    ),
                    key=lambda binding: binding.requested_scope_sha256,
                )
            )
            bindings_sha256 = planned_route_replacement_bindings_sha256(bindings)
        except SuccessorUpdateContractError as exc:
            raise SuccessorExecutionPlanError(
                f"planned route replacement authority is invalid: {exc}"
            ) from exc
        object.__setattr__(self, "planned_route_replacement_bindings", bindings)
        object.__setattr__(
            self,
            "planned_route_replacement_bindings_sha256",
            bindings_sha256,
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
            "baseline_identity_sha256": self.baseline_identity_sha256,
            "planning_generation_id": self.planning_generation_id,
            "planning_request_sha256": self.planning_request_sha256,
            "planning_artifact_identity_sha256": self.planning_artifact_identity_sha256,
            "planning_manifest_sha256": self.planning_manifest_sha256,
            "sealed_dispatch_inventory_sha256": self.sealed_dispatch_inventory_sha256,
            "requested_route_scopes_sha256": self.requested_route_scopes_sha256,
            "dispatches": [dispatch.to_dict() for dispatch in self.dispatches],
            "planned_route_replacement_bindings": [
                binding.to_dict() for binding in self.planned_route_replacement_bindings
            ],
            "planned_route_replacement_bindings_sha256": (
                self.planned_route_replacement_bindings_sha256
            ),
        }

    def to_public_dict(self) -> dict[str, Any]:
        """Path-free identities only; omit sealed-dispatch parameter bodies."""

        return SuccessorExecutionPlanPublicIdentity.from_plan(self).to_dict()

    def validate_against_manifest(
        self,
        manifest: PlanningGenerationManifest,
    ) -> None:
        """Require exact equality to a fresh projection of the durable manifest."""

        expected = build_successor_execution_plan(manifest)
        if self.to_dict() != expected.to_dict():
            raise SuccessorExecutionPlanError(
                "execution plan differs from the durable planning manifest"
            )

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "baseline_identity_sha256",
                    "planning_generation_id",
                    "planning_request_sha256",
                    "planning_artifact_identity_sha256",
                    "planning_manifest_sha256",
                    "sealed_dispatch_inventory_sha256",
                    "requested_route_scopes_sha256",
                    "dispatches",
                    "planned_route_replacement_bindings",
                    "planned_route_replacement_bindings_sha256",
                }
            ),
            label="successor execution plan",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise SuccessorExecutionPlanError("successor execution plan schema is invalid")
        raw_dispatches = payload["dispatches"]
        if not isinstance(raw_dispatches, list):
            raise SuccessorExecutionPlanError("dispatches must be a list")
        raw_bindings = payload["planned_route_replacement_bindings"]
        if not isinstance(raw_bindings, list):
            raise SuccessorExecutionPlanError("planned_route_replacement_bindings must be a list")
        try:
            supplied_bindings = tuple(
                PlannedRouteReplacementBinding.from_dict(
                    _require_mapping(
                        binding,
                        field_name=f"planned_route_replacement_bindings[{index}]",
                    )
                )
                for index, binding in enumerate(raw_bindings)
            )
            supplied_bindings_sha256 = planned_route_replacement_bindings_sha256(supplied_bindings)
        except SuccessorUpdateContractError as exc:
            raise SuccessorExecutionPlanError(
                f"planned route replacement bindings are invalid: {exc}"
            ) from exc
        if supplied_bindings != tuple(
            sorted(supplied_bindings, key=lambda binding: binding.requested_scope_sha256)
        ):
            raise SuccessorExecutionPlanError(
                "planned route replacement bindings must use canonical scope order"
            )
        result = cls(
            baseline_identity_sha256=_require_sha256(
                payload["baseline_identity_sha256"],
                field_name="baseline_identity_sha256",
            ),
            planning_generation_id=_require_token(
                payload["planning_generation_id"], field_name="planning_generation_id"
            ),
            planning_request_sha256=_require_sha256(
                payload["planning_request_sha256"], field_name="planning_request_sha256"
            ),
            planning_artifact_identity_sha256=_require_sha256(
                payload["planning_artifact_identity_sha256"],
                field_name="planning_artifact_identity_sha256",
            ),
            planning_manifest_sha256=_require_sha256(
                payload["planning_manifest_sha256"], field_name="planning_manifest_sha256"
            ),
            sealed_dispatch_inventory_sha256=_require_sha256(
                payload["sealed_dispatch_inventory_sha256"],
                field_name="sealed_dispatch_inventory_sha256",
            ),
            requested_route_scopes_sha256=_require_sha256(
                payload["requested_route_scopes_sha256"],
                field_name="requested_route_scopes_sha256",
            ),
            dispatches=tuple(
                SealedUpdateExecutionDispatch.from_dict(
                    _require_mapping(dispatch, field_name=f"dispatches[{index}]")
                )
                for index, dispatch in enumerate(raw_dispatches)
            ),
        )
        if supplied_bindings != result.planned_route_replacement_bindings:
            raise SuccessorExecutionPlanError(
                "planned route replacement bindings differ from execution dispatches"
            )
        expected_bindings_sha256 = _require_sha256(
            payload["planned_route_replacement_bindings_sha256"],
            field_name="planned_route_replacement_bindings_sha256",
        )
        if (
            supplied_bindings_sha256 != expected_bindings_sha256
            or result.planned_route_replacement_bindings_sha256 != expected_bindings_sha256
        ):
            raise SuccessorExecutionPlanError("planned route replacement binding digest differs")
        return result

    @classmethod
    def from_canonical_bytes(cls, encoded: bytes) -> Self:
        """Decode only exact canonical JSON; durable authority still needs the manifest."""

        if not isinstance(encoded, bytes):
            raise SuccessorExecutionPlanError("execution plan encoding must be bytes")

        def reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise SuccessorExecutionPlanError(
                        f"execution plan contains duplicate key {key!r}"
                    )
                result[key] = value
            return result

        def reject_constant(value: str) -> object:
            raise SuccessorExecutionPlanError(
                f"execution plan contains non-finite JSON value {value}"
            )

        try:
            decoded = json.loads(
                encoded.decode("utf-8", errors="strict"),
                object_pairs_hook=reject_duplicate_pairs,
                parse_constant=reject_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SuccessorExecutionPlanError("execution plan is not strict UTF-8 JSON") from exc
        payload = _require_mapping(decoded, field_name="execution plan")
        if canonical_planning_json_bytes(payload) != encoded:
            raise SuccessorExecutionPlanError("execution plan bytes are not canonical")
        return cls.from_dict(payload)


@dataclass(frozen=True, slots=True)
class SuccessorExecutionPlanPublicIdentity:
    """Path-free public projection of one private UPDATE execution plan."""

    baseline_identity_sha256: str
    planning_generation_id: str
    planning_request_sha256: str
    planning_artifact_identity_sha256: str
    planning_manifest_sha256: str
    sealed_dispatch_inventory_sha256: str
    requested_route_scopes_sha256: str
    planned_route_replacement_bindings_sha256: str
    identity_sha256: str

    schema_version: ClassVar[int] = SUCCESSOR_EXECUTION_PLAN_SCHEMA_VERSION
    kind: ClassVar[str] = "successor_execution_plan"

    def __post_init__(self) -> None:
        for field_name in (
            "baseline_identity_sha256",
            "planning_request_sha256",
            "planning_artifact_identity_sha256",
            "planning_manifest_sha256",
            "sealed_dispatch_inventory_sha256",
            "requested_route_scopes_sha256",
            "planned_route_replacement_bindings_sha256",
            "identity_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name=field_name)
        _require_token(self.planning_generation_id, field_name="planning_generation_id")

    @classmethod
    def from_plan(cls, plan: SuccessorExecutionPlan) -> Self:
        if not isinstance(plan, SuccessorExecutionPlan):
            raise SuccessorExecutionPlanError("public identity requires a SuccessorExecutionPlan")
        return cls(
            baseline_identity_sha256=plan.baseline_identity_sha256,
            planning_generation_id=plan.planning_generation_id,
            planning_request_sha256=plan.planning_request_sha256,
            planning_artifact_identity_sha256=plan.planning_artifact_identity_sha256,
            planning_manifest_sha256=plan.planning_manifest_sha256,
            sealed_dispatch_inventory_sha256=plan.sealed_dispatch_inventory_sha256,
            requested_route_scopes_sha256=plan.requested_route_scopes_sha256,
            planned_route_replacement_bindings_sha256=(
                plan.planned_route_replacement_bindings_sha256
            ),
            identity_sha256=plan.identity_sha256,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "baseline_identity_sha256": self.baseline_identity_sha256,
            "planning_generation_id": self.planning_generation_id,
            "planning_request_sha256": self.planning_request_sha256,
            "planning_artifact_identity_sha256": self.planning_artifact_identity_sha256,
            "planning_manifest_sha256": self.planning_manifest_sha256,
            "sealed_dispatch_inventory_sha256": self.sealed_dispatch_inventory_sha256,
            "requested_route_scopes_sha256": self.requested_route_scopes_sha256,
            "planned_route_replacement_bindings_sha256": (
                self.planned_route_replacement_bindings_sha256
            ),
            "identity_sha256": self.identity_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _require_exact_keys(
            payload,
            expected=frozenset(
                {
                    "schema_version",
                    "kind",
                    "baseline_identity_sha256",
                    "planning_generation_id",
                    "planning_request_sha256",
                    "planning_artifact_identity_sha256",
                    "planning_manifest_sha256",
                    "sealed_dispatch_inventory_sha256",
                    "requested_route_scopes_sha256",
                    "planned_route_replacement_bindings_sha256",
                    "identity_sha256",
                }
            ),
            label="successor execution plan public identity",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise SuccessorExecutionPlanError(
                "successor execution plan public identity schema is invalid"
            )
        return cls(
            baseline_identity_sha256=_require_sha256(
                payload["baseline_identity_sha256"],
                field_name="baseline_identity_sha256",
            ),
            planning_generation_id=_require_token(
                payload["planning_generation_id"],
                field_name="planning_generation_id",
            ),
            planning_request_sha256=_require_sha256(
                payload["planning_request_sha256"],
                field_name="planning_request_sha256",
            ),
            planning_artifact_identity_sha256=_require_sha256(
                payload["planning_artifact_identity_sha256"],
                field_name="planning_artifact_identity_sha256",
            ),
            planning_manifest_sha256=_require_sha256(
                payload["planning_manifest_sha256"],
                field_name="planning_manifest_sha256",
            ),
            sealed_dispatch_inventory_sha256=_require_sha256(
                payload["sealed_dispatch_inventory_sha256"],
                field_name="sealed_dispatch_inventory_sha256",
            ),
            requested_route_scopes_sha256=_require_sha256(
                payload["requested_route_scopes_sha256"],
                field_name="requested_route_scopes_sha256",
            ),
            planned_route_replacement_bindings_sha256=_require_sha256(
                payload["planned_route_replacement_bindings_sha256"],
                field_name="planned_route_replacement_bindings_sha256",
            ),
            identity_sha256=_require_sha256(
                payload["identity_sha256"],
                field_name="identity_sha256",
            ),
        )


def build_successor_execution_plan(
    manifest: PlanningGenerationManifest,
) -> SuccessorExecutionPlan:
    """Project the exact sealed UPDATE dispatches without planning-receipt reuse."""

    if not isinstance(manifest, PlanningGenerationManifest):
        raise SuccessorExecutionPlanError("execution plan requires a PlanningGenerationManifest")
    try:
        validated = PlanningGenerationManifest.from_canonical_bytes(manifest.canonical_bytes)
    except SuccessorPlanningGenerationContractError as exc:
        raise SuccessorExecutionPlanError(f"planning manifest is invalid: {exc}") from exc
    scope_by_id = {scope.identity_sha256: scope for scope in validated.requested_route_scopes}
    update_dispatches = tuple(
        dispatch
        for dispatch in validated.sealed_dispatches
        if dispatch.phase is PlanningDispatchPhase.UPDATE
    )
    projected: list[SealedUpdateExecutionDispatch] = []
    for order, dispatch in enumerate(update_dispatches):
        try:
            scopes = tuple(
                scope_by_id[scope_id] for scope_id in dispatch.requested_scope_identity_sha256s
            )
        except KeyError as exc:  # pragma: no cover - manifest validation owns this invariant
            raise SuccessorExecutionPlanError(
                "sealed update dispatch references an unknown route scope"
            ) from exc
        projected.append(
            SealedUpdateExecutionDispatch(
                order=order,
                sealed_dispatch=dispatch,
                requested_scopes=scopes,
            )
        )
    artifact = validated.artifact_identity
    return SuccessorExecutionPlan(
        baseline_identity_sha256=validated.request.baseline_identity_sha256,
        planning_generation_id=artifact.planning_generation_id,
        planning_request_sha256=artifact.planning_request_sha256,
        planning_artifact_identity_sha256=artifact.identity_sha256,
        planning_manifest_sha256=artifact.planning_manifest_sha256,
        sealed_dispatch_inventory_sha256=artifact.sealed_dispatch_inventory_sha256,
        requested_route_scopes_sha256=validated.requested_route_scopes_sha256,
        dispatches=tuple(projected),
    )
