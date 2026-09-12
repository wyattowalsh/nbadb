"""Immutable pre-intent discovery/foundation evidence for successor updates."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Self, cast

from nbadb.orchestrate.successor_update_contract import (
    RequestedRouteScope,
    SuccessorUpdateIntent,
    SuccessorUpdateMode,
    canonical_sha256,
)

if TYPE_CHECKING:
    from nbadb.orchestrate.successor_execution_plan import (
        SuccessorExecutionPlan,
        SuccessorExecutionPlanPublicIdentity,
    )
    from nbadb.orchestrate.successor_planning_generation_contract import (
        PlanningGenerationManifest,
        PlanningGenerationPublicIdentity,
    )

__all__ = [
    "SuccessorPlanningContractError",
    "SuccessorPlanningEvidence",
    "SuccessorPlanningPublicIdentity",
    "SuccessorPlanningRequest",
    "build_successor_planning_evidence",
    "finalize_successor_update_intent",
]

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SOURCE_SHA_RE = re.compile(r"[0-9a-f]{40}")


class SuccessorPlanningContractError(ValueError):
    """Raised when pre-intent evidence is incomplete, unsafe, or inconsistent."""


def _sha256(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise SuccessorPlanningContractError(f"{field_name} must be a lowercase SHA-256")
    return value


def _source_sha(value: object) -> str:
    if not isinstance(value, str) or _SOURCE_SHA_RE.fullmatch(value) is None:
        raise SuccessorPlanningContractError("source_sha must be a 40-character commit SHA")
    return value


def _positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise SuccessorPlanningContractError(f"{field_name} must be a positive integer")
    return value


def _utc(value: object, *, field_name: str) -> str:
    from datetime import datetime

    if not isinstance(value, str) or not value.endswith("Z"):
        raise SuccessorPlanningContractError(f"{field_name} must be canonical UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise SuccessorPlanningContractError(f"{field_name} must be canonical UTC") from exc
    canonical = parsed.isoformat(timespec="seconds").replace("+00:00", "Z")
    if canonical != value:
        raise SuccessorPlanningContractError(f"{field_name} must be canonical UTC")
    return value


def _exact_keys(payload: Mapping[str, object], expected: set[str], *, label: str) -> None:
    if set(payload) != expected:
        raise SuccessorPlanningContractError(f"{label} fields are invalid")


@dataclass(frozen=True, slots=True)
class SuccessorPlanningRequest:
    """Exact provider calls allowed to determine one final successor fan-out."""

    baseline_identity_sha256: str
    mode: SuccessorUpdateMode
    source_sha: str
    cutoff_utc: str
    as_of_utc: str
    workflow_run_id: int
    workflow_run_attempt: int
    requested_planning_scopes: tuple[RequestedRouteScope, ...]
    requested_planning_scopes_sha256: str = field(init=False)

    schema_version: ClassVar[int] = 1
    kind: ClassVar[str] = "successor_planning_request"

    def __post_init__(self) -> None:
        _sha256(self.baseline_identity_sha256, field_name="baseline_identity_sha256")
        if not isinstance(self.mode, SuccessorUpdateMode):
            raise SuccessorPlanningContractError("mode must be a SuccessorUpdateMode")
        _source_sha(self.source_sha)
        cutoff = _utc(self.cutoff_utc, field_name="cutoff_utc")
        as_of = _utc(self.as_of_utc, field_name="as_of_utc")
        if cutoff > as_of:
            raise SuccessorPlanningContractError("cutoff_utc must not be after as_of_utc")
        _positive_int(self.workflow_run_id, field_name="workflow_run_id")
        _positive_int(self.workflow_run_attempt, field_name="workflow_run_attempt")
        scopes = tuple(
            sorted(self.requested_planning_scopes, key=lambda item: item.identity_sha256)
        )
        if not scopes or any(not isinstance(item, RequestedRouteScope) for item in scopes):
            raise SuccessorPlanningContractError(
                "requested planning scopes must be nonempty RequestedRouteScope values"
            )
        keys = [item.uniqueness_key for item in scopes]
        if len(keys) != len(set(keys)):
            raise SuccessorPlanningContractError("requested planning scopes contain duplicates")
        object.__setattr__(self, "requested_planning_scopes", scopes)
        object.__setattr__(
            self,
            "requested_planning_scopes_sha256",
            canonical_sha256([item.to_dict() for item in scopes]),
        )

    @property
    def identity_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "baseline_identity_sha256": self.baseline_identity_sha256,
            "mode": self.mode.value,
            "source_sha": self.source_sha,
            "cutoff_utc": self.cutoff_utc,
            "as_of_utc": self.as_of_utc,
            "workflow_run_id": self.workflow_run_id,
            "workflow_run_attempt": self.workflow_run_attempt,
            "requested_planning_scopes": [
                item.to_dict() for item in self.requested_planning_scopes
            ],
            "requested_planning_scopes_sha256": self.requested_planning_scopes_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _exact_keys(
            payload,
            {
                "schema_version",
                "kind",
                "baseline_identity_sha256",
                "mode",
                "source_sha",
                "cutoff_utc",
                "as_of_utc",
                "workflow_run_id",
                "workflow_run_attempt",
                "requested_planning_scopes",
                "requested_planning_scopes_sha256",
            },
            label="successor planning request",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise SuccessorPlanningContractError("successor planning request schema is invalid")
        raw_mode = payload["mode"]
        try:
            mode = SuccessorUpdateMode(raw_mode)
        except (TypeError, ValueError) as exc:
            raise SuccessorPlanningContractError("successor planning mode is invalid") from exc
        raw_scopes = payload["requested_planning_scopes"]
        if not isinstance(raw_scopes, list):
            raise SuccessorPlanningContractError("requested planning scopes must be a list")
        scopes: list[RequestedRouteScope] = []
        for raw_scope in raw_scopes:
            if not isinstance(raw_scope, Mapping):
                raise SuccessorPlanningContractError("requested planning scope must be an object")
            scopes.append(RequestedRouteScope.from_dict(cast("Mapping[str, object]", raw_scope)))
        result = cls(
            baseline_identity_sha256=_sha256(
                payload["baseline_identity_sha256"], field_name="baseline_identity_sha256"
            ),
            mode=mode,
            source_sha=_source_sha(payload["source_sha"]),
            cutoff_utc=_utc(payload["cutoff_utc"], field_name="cutoff_utc"),
            as_of_utc=_utc(payload["as_of_utc"], field_name="as_of_utc"),
            workflow_run_id=_positive_int(payload["workflow_run_id"], field_name="workflow_run_id"),
            workflow_run_attempt=_positive_int(
                payload["workflow_run_attempt"], field_name="workflow_run_attempt"
            ),
            requested_planning_scopes=tuple(scopes),
        )
        if result.requested_planning_scopes_sha256 != _sha256(
            payload["requested_planning_scopes_sha256"],
            field_name="requested_planning_scopes_sha256",
        ):
            raise SuccessorPlanningContractError("planning-scope inventory digest differs")
        return result


@dataclass(frozen=True, slots=True)
class SuccessorPlanningEvidence:
    """Data-bearing planning authority for one immutable successor intent."""

    planning_generation_manifest: PlanningGenerationManifest
    execution_plan: SuccessorExecutionPlan = field(init=False)
    planned_route_replacement_bindings_sha256: str = field(init=False)

    schema_version: ClassVar[int] = 3
    kind: ClassVar[str] = "successor_planning_evidence"

    def __post_init__(self) -> None:
        from nbadb.orchestrate.successor_execution_plan import (
            build_successor_execution_plan,
        )
        from nbadb.orchestrate.successor_planning_generation_contract import (
            PlanningGenerationManifest,
        )

        if not isinstance(self.planning_generation_manifest, PlanningGenerationManifest):
            raise SuccessorPlanningContractError(
                "planning_generation_manifest must be a PlanningGenerationManifest"
            )
        execution_plan = build_successor_execution_plan(self.planning_generation_manifest)
        object.__setattr__(self, "execution_plan", execution_plan)
        object.__setattr__(
            self,
            "planned_route_replacement_bindings_sha256",
            execution_plan.planned_route_replacement_bindings_sha256,
        )

    @property
    def request(self) -> SuccessorPlanningRequest:
        return self.planning_generation_manifest.request

    @property
    def resolved_requested_scopes(self) -> tuple[RequestedRouteScope, ...]:
        scopes = tuple(
            scope
            for dispatch in self.execution_plan.dispatches
            for scope in dispatch.requested_scopes
        )
        return tuple(sorted(scopes, key=lambda scope: scope.identity_sha256))

    @property
    def identity_sha256(self) -> str:
        return canonical_sha256(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        """Private store encoding. Public reports must use :meth:`to_public_dict`."""

        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "planning_generation_manifest": self.planning_generation_manifest.to_dict(),
            "planning_generation_manifest_sha256": (
                self.planning_generation_manifest.identity_sha256
            ),
            "execution_plan": self.execution_plan.to_dict(),
            "execution_plan_sha256": self.execution_plan.identity_sha256,
            "planned_route_replacement_bindings_sha256": (
                self.planned_route_replacement_bindings_sha256
            ),
        }

    def to_public_dict(self) -> dict[str, Any]:
        """Path-free identities only; omit private planning bytes."""

        return SuccessorPlanningPublicIdentity.from_evidence(self).to_dict()

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _exact_keys(
            payload,
            {
                "schema_version",
                "kind",
                "planning_generation_manifest",
                "planning_generation_manifest_sha256",
                "execution_plan",
                "execution_plan_sha256",
                "planned_route_replacement_bindings_sha256",
            },
            label="successor planning evidence",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise SuccessorPlanningContractError("successor planning evidence schema is invalid")
        raw_manifest = payload["planning_generation_manifest"]
        raw_plan = payload["execution_plan"]
        if not isinstance(raw_manifest, Mapping) or not isinstance(raw_plan, Mapping):
            raise SuccessorPlanningContractError(
                "planning generation manifest and execution plan must be objects"
            )
        from nbadb.orchestrate.successor_execution_plan import SuccessorExecutionPlan
        from nbadb.orchestrate.successor_planning_generation_contract import (
            PlanningGenerationManifest,
        )

        try:
            manifest = PlanningGenerationManifest.from_dict(
                cast("Mapping[str, object]", raw_manifest)
            )
            supplied_plan = SuccessorExecutionPlan.from_dict(cast("Mapping[str, object]", raw_plan))
        except ValueError as exc:
            raise SuccessorPlanningContractError(
                f"planning generation evidence is invalid: {exc}"
            ) from exc
        result = cls(planning_generation_manifest=manifest)
        if supplied_plan.to_dict() != result.execution_plan.to_dict():
            raise SuccessorPlanningContractError(
                "execution plan differs from its planning generation manifest"
            )
        if result.planning_generation_manifest.identity_sha256 != _sha256(
            payload["planning_generation_manifest_sha256"],
            field_name="planning_generation_manifest_sha256",
        ) or result.execution_plan.identity_sha256 != _sha256(
            payload["execution_plan_sha256"], field_name="execution_plan_sha256"
        ):
            raise SuccessorPlanningContractError("planning authority digest differs")
        if result.planned_route_replacement_bindings_sha256 != _sha256(
            payload["planned_route_replacement_bindings_sha256"],
            field_name="planned_route_replacement_bindings_sha256",
        ):
            raise SuccessorPlanningContractError("planned route replacement binding digest differs")
        return result


@dataclass(frozen=True, slots=True)
class SuccessorPlanningPublicIdentity:
    """Path-free public projection of one private planning-evidence value."""

    planning_generation_manifest: PlanningGenerationPublicIdentity
    execution_plan: SuccessorExecutionPlanPublicIdentity
    planning_generation_manifest_sha256: str
    execution_plan_sha256: str
    planned_route_replacement_bindings_sha256: str

    schema_version: ClassVar[int] = 3
    kind: ClassVar[str] = "successor_planning_evidence"

    def __post_init__(self) -> None:
        from nbadb.orchestrate.successor_execution_plan import (
            SuccessorExecutionPlanPublicIdentity,
        )
        from nbadb.orchestrate.successor_planning_generation_contract import (
            PlanningGenerationPublicIdentity,
        )

        if not isinstance(self.planning_generation_manifest, PlanningGenerationPublicIdentity):
            raise SuccessorPlanningContractError(
                "planning_generation_manifest must be a PlanningGenerationPublicIdentity"
            )
        if not isinstance(self.execution_plan, SuccessorExecutionPlanPublicIdentity):
            raise SuccessorPlanningContractError(
                "execution_plan must be a SuccessorExecutionPlanPublicIdentity"
            )
        _sha256(
            self.planning_generation_manifest_sha256,
            field_name="planning_generation_manifest_sha256",
        )
        _sha256(self.execution_plan_sha256, field_name="execution_plan_sha256")
        _sha256(
            self.planned_route_replacement_bindings_sha256,
            field_name="planned_route_replacement_bindings_sha256",
        )
        if self.planning_generation_manifest.identity_sha256 != (
            self.planning_generation_manifest_sha256
        ):
            raise SuccessorPlanningContractError(
                "planning generation manifest identity differs from its digest"
            )
        if self.execution_plan.identity_sha256 != self.execution_plan_sha256:
            raise SuccessorPlanningContractError("execution plan identity differs from its digest")
        if (
            self.execution_plan.planned_route_replacement_bindings_sha256
            != self.planned_route_replacement_bindings_sha256
        ):
            raise SuccessorPlanningContractError(
                "planned route replacement binding digest differs from the execution plan"
            )
        artifact = self.planning_generation_manifest.artifact_identity
        if (
            artifact.planning_manifest_sha256 != self.execution_plan.planning_manifest_sha256
            or artifact.sealed_dispatch_inventory_sha256
            != self.execution_plan.sealed_dispatch_inventory_sha256
            or artifact.planning_request_sha256 != self.execution_plan.planning_request_sha256
        ):
            raise SuccessorPlanningContractError(
                "public planning identities do not close across manifest and execution plan"
            )

    @classmethod
    def from_evidence(cls, evidence: SuccessorPlanningEvidence) -> Self:
        if not isinstance(evidence, SuccessorPlanningEvidence):
            raise SuccessorPlanningContractError(
                "public identity requires SuccessorPlanningEvidence"
            )
        from nbadb.orchestrate.successor_execution_plan import (
            SuccessorExecutionPlanPublicIdentity,
        )
        from nbadb.orchestrate.successor_planning_generation_contract import (
            PlanningGenerationPublicIdentity,
        )

        return cls(
            planning_generation_manifest=PlanningGenerationPublicIdentity.from_manifest(
                evidence.planning_generation_manifest
            ),
            execution_plan=SuccessorExecutionPlanPublicIdentity.from_plan(evidence.execution_plan),
            planning_generation_manifest_sha256=(
                evidence.planning_generation_manifest.identity_sha256
            ),
            execution_plan_sha256=evidence.execution_plan.identity_sha256,
            planned_route_replacement_bindings_sha256=(
                evidence.planned_route_replacement_bindings_sha256
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "planning_generation_manifest": self.planning_generation_manifest.to_dict(),
            "planning_generation_manifest_sha256": self.planning_generation_manifest_sha256,
            "execution_plan": self.execution_plan.to_dict(),
            "execution_plan_sha256": self.execution_plan_sha256,
            "planned_route_replacement_bindings_sha256": (
                self.planned_route_replacement_bindings_sha256
            ),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        _exact_keys(
            payload,
            {
                "schema_version",
                "kind",
                "planning_generation_manifest",
                "planning_generation_manifest_sha256",
                "execution_plan",
                "execution_plan_sha256",
                "planned_route_replacement_bindings_sha256",
            },
            label="successor planning public identity",
        )
        if (
            type(payload["schema_version"]) is not int
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != cls.kind
        ):
            raise SuccessorPlanningContractError(
                "successor planning public identity schema is invalid"
            )
        from nbadb.orchestrate.successor_execution_plan import (
            SuccessorExecutionPlanPublicIdentity,
        )
        from nbadb.orchestrate.successor_planning_generation_contract import (
            PlanningGenerationPublicIdentity,
        )

        raw_manifest = payload["planning_generation_manifest"]
        raw_plan = payload["execution_plan"]
        if not isinstance(raw_manifest, Mapping) or not isinstance(raw_plan, Mapping):
            raise SuccessorPlanningContractError(
                "planning generation manifest and execution plan must be objects"
            )
        try:
            manifest = PlanningGenerationPublicIdentity.from_dict(
                cast("Mapping[str, object]", raw_manifest)
            )
            plan = SuccessorExecutionPlanPublicIdentity.from_dict(
                cast("Mapping[str, object]", raw_plan)
            )
        except ValueError as exc:
            raise SuccessorPlanningContractError(
                f"planning generation public identity is invalid: {exc}"
            ) from exc
        return cls(
            planning_generation_manifest=manifest,
            execution_plan=plan,
            planning_generation_manifest_sha256=_sha256(
                payload["planning_generation_manifest_sha256"],
                field_name="planning_generation_manifest_sha256",
            ),
            execution_plan_sha256=_sha256(
                payload["execution_plan_sha256"],
                field_name="execution_plan_sha256",
            ),
            planned_route_replacement_bindings_sha256=_sha256(
                payload["planned_route_replacement_bindings_sha256"],
                field_name="planned_route_replacement_bindings_sha256",
            ),
        )


def build_successor_planning_evidence(
    *,
    planning_generation_manifest: PlanningGenerationManifest,
) -> SuccessorPlanningEvidence:
    """Bind the data-bearing manifest and its exact UPDATE execution projection."""

    return SuccessorPlanningEvidence(
        planning_generation_manifest=planning_generation_manifest,
    )


def finalize_successor_update_intent(
    evidence: SuccessorPlanningEvidence,
) -> SuccessorUpdateIntent:
    """Construct the only final intent admitted from sealed planning evidence."""

    if not isinstance(evidence, SuccessorPlanningEvidence):
        raise SuccessorPlanningContractError(
            "final intent requires validated SuccessorPlanningEvidence"
        )
    request = evidence.request
    return SuccessorUpdateIntent(
        baseline_identity_sha256=request.baseline_identity_sha256,
        planning_generation_manifest_sha256=(evidence.planning_generation_manifest.identity_sha256),
        successor_execution_plan_sha256=evidence.execution_plan.identity_sha256,
        planned_route_replacement_bindings_sha256=(
            evidence.planned_route_replacement_bindings_sha256
        ),
        mode=request.mode,
        source_sha=request.source_sha,
        cutoff_utc=request.cutoff_utc,
        as_of_utc=request.as_of_utc,
        requested_scopes=evidence.resolved_requested_scopes,
    )
