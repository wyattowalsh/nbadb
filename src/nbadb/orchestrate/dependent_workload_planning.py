"""Receipt-bound post-foundation planning for observed matchup workloads.

This module deliberately has no discovery or provider fan-out.  It compiles only
from a committed public checkpoint, exact singleton discovery generations, and
the checkpoint's committed staging/journal receipts.  The resulting execution
plan is deterministic and can be handed between workflow jobs by content digest.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import duckdb
import polars as pl

from nbadb.extract.bronze import canonical_parameters_sha256
from nbadb.orchestrate.checkpoint_contract import CheckpointState, CheckpointTransaction
from nbadb.orchestrate.dependent_workload_builder import (
    DEPENDENT_WORKLOAD_COMPILER_SHA256,
    DEPENDENT_WORKLOAD_QUERY_PLAN_SHA256,
    DirectionalMatchupObservation,
    FoundationEvidenceState,
    FoundationScopeEvidence,
    RotationObservation,
    compile_dependent_workload,
)
from nbadb.orchestrate.dependent_workload_contract import (
    DependentExecutableUnit,
    DependentScopeDisposition,
    DependentWorkloadBundle,
    DependentWorkloadContractError,
    DependentWorkloadKind,
    FoundationAuthority,
    FoundationAuthorityKind,
    FoundationInputReceipt,
    ScopeDispositionRecord,
    SourceRowIdentity,
    WorkloadScope,
    canonical_json_bytes,
    canonical_sha256,
)
from nbadb.orchestrate.discovery_artifacts import DiscoveryArtifactScope
from nbadb.orchestrate.planning import PATTERN_PRIORITY, ExtractionPlanItem
from nbadb.orchestrate.staging_batches import frame_content_hash, frame_schema_hash
from nbadb.orchestrate.staging_map import STAGING_MAP, StagingEntry

if TYPE_CHECKING:
    from collections.abc import Mapping

DEPENDENT_EXECUTION_PLAN_SCHEMA_VERSION = 2
DEPENDENT_LANE_KIND = "post_foundation_dependent_matchup"
DEPENDENT_CALLS_PER_LANE = 32
DEPENDENT_ENDPOINTS = frozenset(
    {
        "player_vs_player",
        "team_vs_player",
        "team_and_players_vs",
        "team_and_players_vs_players",
    }
)

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SOURCE_SHA_RE = re.compile(r"[0-9a-f]{40}")
_FOUNDATION_TABLES_BY_ENDPOINT = {
    "box_score_matchups": ("stg_matchup",),
    "game_rotation": ("stg_rotation_away", "stg_rotation_home"),
}
_FOUNDATION_SIDES = {
    "stg_rotation_away": "away",
    "stg_rotation_home": "home",
}


def _sha256_path(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise DependentWorkloadContractError(f"required authority is not a regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _bare_sha256(value: str, *, field_name: str) -> str:
    normalized = value.strip().lower()
    if normalized.startswith("sha256:"):
        normalized = normalized.removeprefix("sha256:")
    if _SHA256_RE.fullmatch(normalized) is None:
        raise DependentWorkloadContractError(f"{field_name} must be a SHA-256")
    return normalized


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DependentWorkloadContractError(f"{label} is unreadable") from exc
    if not isinstance(payload, dict):
        raise DependentWorkloadContractError(f"{label} must be an object")
    return payload


def _route_ids(endpoint_name: str) -> tuple[str, ...]:
    routes = tuple(
        sorted(
            f"{entry.endpoint_name}:{entry.staging_key}:{entry.result_set_index}"
            for entry in STAGING_MAP
            if entry.endpoint_name == endpoint_name
        )
    )
    if not routes or len(routes) != len(set(routes)):
        raise DependentWorkloadContractError(
            f"endpoint {endpoint_name} lacks a unique physical staging route inventory"
        )
    return routes


def _entries(endpoint_name: str) -> list[StagingEntry]:
    entries = [entry for entry in STAGING_MAP if entry.endpoint_name == endpoint_name]
    if not entries or any(entry.param_pattern != "player_team_season" for entry in entries):
        raise DependentWorkloadContractError(
            f"dependent endpoint {endpoint_name} lacks its executable planner routes"
        )
    return entries


@dataclass(frozen=True, slots=True, order=True)
class DependentPhysicalCall:
    """One exact physical endpoint call derived from one observed semantic unit."""

    endpoint_name: str
    kind: DependentWorkloadKind
    unit_sha256: str
    parameters: tuple[tuple[str, int | str], ...]
    result_route_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.endpoint_name not in DEPENDENT_ENDPOINTS:
            raise DependentWorkloadContractError("dependent physical endpoint is invalid")
        if not isinstance(self.kind, DependentWorkloadKind):
            raise DependentWorkloadContractError("dependent physical call kind is invalid")
        if _SHA256_RE.fullmatch(self.unit_sha256) is None:
            raise DependentWorkloadContractError("dependent unit digest is invalid")
        unit = DependentExecutableUnit(
            kind=self.kind,
            parameters=tuple(self.parameters),
            occurrence_sha256s=("0" * 64,),
        )
        if unit.identity_sha256 != self.unit_sha256:
            raise DependentWorkloadContractError(
                "dependent physical call parameters differ from its unit identity"
            )
        if self.endpoint_name not in unit.endpoint_names:
            raise DependentWorkloadContractError(
                "dependent physical endpoint differs from its semantic unit"
            )
        routes = tuple(self.result_route_ids)
        if routes != tuple(sorted(routes)) or routes != _route_ids(self.endpoint_name):
            raise DependentWorkloadContractError(
                "dependent physical call route inventory is incomplete"
            )

    @property
    def parameters_sha256(self) -> str:
        return canonical_parameters_sha256(dict(self.parameters))

    @property
    def identity_sha256(self) -> str:
        return canonical_sha256(self.to_payload())

    def to_payload(self) -> dict[str, Any]:
        return {
            "endpoint_name": self.endpoint_name,
            "kind": self.kind.value,
            "unit_sha256": self.unit_sha256,
            "parameters": [{"name": name, "value": value} for name, value in self.parameters],
            "parameters_sha256": self.parameters_sha256,
            "result_route_ids": list(self.result_route_ids),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> DependentPhysicalCall:
        expected = {
            "endpoint_name",
            "kind",
            "unit_sha256",
            "parameters",
            "parameters_sha256",
            "result_route_ids",
        }
        if set(payload) != expected:
            raise DependentWorkloadContractError("dependent physical call fields are invalid")
        raw_parameters = payload["parameters"]
        raw_routes = payload["result_route_ids"]
        if (
            not isinstance(raw_parameters, list)
            or any(
                not isinstance(item, dict)
                or set(item) != {"name", "value"}
                or not isinstance(item["name"], str)
                for item in raw_parameters
            )
            or not isinstance(raw_routes, list)
            or any(not isinstance(route, str) for route in raw_routes)
        ):
            raise DependentWorkloadContractError("dependent physical call payload is malformed")
        call = cls(
            endpoint_name=str(payload["endpoint_name"]),
            kind=DependentWorkloadKind(str(payload["kind"])),
            unit_sha256=str(payload["unit_sha256"]),
            parameters=tuple((item["name"], item["value"]) for item in raw_parameters),
            result_route_ids=tuple(raw_routes),
        )
        if payload["parameters_sha256"] != call.parameters_sha256:
            raise DependentWorkloadContractError("dependent physical parameter digest changed")
        return call


def _scope_disposition_from_payload(payload: Mapping[str, Any]) -> ScopeDispositionRecord:
    expected = {
        "scope",
        "kind",
        "disposition",
        "reason_code",
        "occurrence_count",
        "executable_unit_count",
    }
    raw_scope = payload.get("scope")
    if set(payload) != expected or not isinstance(raw_scope, dict):
        raise DependentWorkloadContractError("dependent scope disposition is malformed")
    if set(raw_scope) != {
        "season",
        "season_type",
        "game_id",
        "foundation_receipt_sha256",
        "foundation_row_ordinal",
    }:
        raise DependentWorkloadContractError("dependent scope disposition scope is malformed")
    return ScopeDispositionRecord(
        scope=WorkloadScope(
            season=str(raw_scope["season"]),
            season_type=str(raw_scope["season_type"]),
            game_id=str(raw_scope["game_id"]),
            foundation_receipt_sha256=str(raw_scope["foundation_receipt_sha256"]),
            foundation_row_ordinal=raw_scope["foundation_row_ordinal"],
        ),
        kind=DependentWorkloadKind(str(payload["kind"])),
        disposition=DependentScopeDisposition(str(payload["disposition"])),
        reason_code=str(payload["reason_code"]),
        occurrence_count=payload["occurrence_count"],
        executable_unit_count=payload["executable_unit_count"],
    )


@dataclass(frozen=True, slots=True)
class DependentExecutionLane:
    """One bounded, content-addressed execution or scope-accounting shard."""

    lane_id: str
    role: str
    endpoint_name: str
    calls: tuple[DependentPhysicalCall, ...]
    scope_dispositions_sha256: str

    def __post_init__(self) -> None:
        if self.role not in {"execute", "scope_accounting"}:
            raise DependentWorkloadContractError("dependent lane role is invalid")
        calls = tuple(sorted(self.calls))
        if self.role == "scope_accounting":
            if self.endpoint_name or calls:
                raise DependentWorkloadContractError(
                    "scope-accounting lane cannot contain physical calls"
                )
        elif (
            self.endpoint_name not in DEPENDENT_ENDPOINTS
            or not calls
            or len(calls) > DEPENDENT_CALLS_PER_LANE
            or any(call.endpoint_name != self.endpoint_name for call in calls)
        ):
            raise DependentWorkloadContractError(
                "dependent execution lane endpoint or call bound is invalid"
            )
        if _SHA256_RE.fullmatch(self.scope_dispositions_sha256) is None:
            raise DependentWorkloadContractError(
                "dependent lane scope disposition digest is invalid"
            )
        object.__setattr__(self, "calls", calls)
        expected_lane_id = self.expected_lane_id
        if self.lane_id != expected_lane_id:
            raise DependentWorkloadContractError(
                "dependent lane ID differs from its canonical content"
            )

    @property
    def semantic_unit_count(self) -> int:
        return len({call.unit_sha256 for call in self.calls})

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.content_payload())

    @property
    def expected_lane_id(self) -> str:
        prefix = (
            "dependent-scope-accounting"
            if self.role == "scope_accounting"
            else f"dependent-{self.endpoint_name.replace('_', '-')}"
        )
        return f"{prefix}-{self.content_sha256[:16]}"

    def content_payload(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "endpoint_name": self.endpoint_name,
            "scope_dispositions_sha256": self.scope_dispositions_sha256,
            "calls": [call.to_payload() for call in self.calls],
        }

    def to_payload(self) -> dict[str, Any]:
        return {
            "lane_id": self.lane_id,
            "content_sha256": self.content_sha256,
            "physical_call_count": len(self.calls),
            "semantic_unit_count": self.semantic_unit_count,
            **self.content_payload(),
        }

    def to_extraction_plan_items(self) -> list[ExtractionPlanItem]:
        if not self.calls:
            return []
        return [
            ExtractionPlanItem(
                label=self.lane_id,
                pattern="player_team_season",
                entries=_entries(self.endpoint_name),
                params=[dict(call.parameters) for call in self.calls],
                priority=PATTERN_PRIORITY["player_team_season"],
            )
        ]


@dataclass(frozen=True, slots=True)
class DependentExecutionPlan:
    """Content-addressed physical plan handed to the post-foundation executor."""

    bundle_content_sha256: str
    checkpoint_transaction_sha256: str
    checkpoint_database_sha256: str
    source_sha: str
    provider_authority_sha256: str
    discovery_artifact_id: int
    discovery_artifact_run_id: int
    discovery_artifact_name: str
    discovery_artifact_digest: str
    scope_dispositions: tuple[ScopeDispositionRecord, ...]
    calls: tuple[DependentPhysicalCall, ...]

    schema_version: ClassVar[int] = DEPENDENT_EXECUTION_PLAN_SCHEMA_VERSION
    lane_kind: ClassVar[str] = DEPENDENT_LANE_KIND

    def __post_init__(self) -> None:
        for field_name in (
            "bundle_content_sha256",
            "checkpoint_transaction_sha256",
            "checkpoint_database_sha256",
            "provider_authority_sha256",
            "discovery_artifact_digest",
        ):
            if _SHA256_RE.fullmatch(str(getattr(self, field_name))) is None:
                raise DependentWorkloadContractError(f"{field_name} must be a SHA-256")
        if _SOURCE_SHA_RE.fullmatch(self.source_sha) is None:
            raise DependentWorkloadContractError("dependent plan source SHA is invalid")
        if type(self.discovery_artifact_id) is not int or self.discovery_artifact_id <= 0:
            raise DependentWorkloadContractError("discovery artifact ID must be positive")
        if type(self.discovery_artifact_run_id) is not int or self.discovery_artifact_run_id <= 0:
            raise DependentWorkloadContractError("discovery artifact run ID must be positive")
        if not self.discovery_artifact_name:
            raise DependentWorkloadContractError("discovery artifact name is empty")
        calls = tuple(sorted(self.calls))
        dispositions = tuple(
            sorted(self.scope_dispositions, key=lambda item: (item.scope, item.kind.value))
        )
        if not dispositions:
            raise DependentWorkloadContractError(
                "dependent plan scope disposition inventory is empty"
            )
        disposition_keys = [(item.scope, item.kind) for item in dispositions]
        if len(disposition_keys) != len(set(disposition_keys)):
            raise DependentWorkloadContractError(
                "dependent plan scope dispositions contain duplicates"
            )
        call_ids = [call.identity_sha256 for call in calls]
        if len(call_ids) != len(set(call_ids)):
            raise DependentWorkloadContractError("dependent physical calls contain duplicates")
        endpoints_by_unit: dict[str, set[str]] = {}
        expected_by_unit: dict[str, set[str]] = {}
        for call in calls:
            endpoints_by_unit.setdefault(call.unit_sha256, set()).add(call.endpoint_name)
            probe = DependentExecutableUnit(
                kind=call.kind,
                parameters=call.parameters,
                occurrence_sha256s=("0" * 64,),
            )
            expected_by_unit.setdefault(call.unit_sha256, set()).update(probe.endpoint_names)
        if endpoints_by_unit != expected_by_unit:
            raise DependentWorkloadContractError(
                "dependent physical plan does not conserve every endpoint alias"
            )
        object.__setattr__(self, "calls", calls)
        object.__setattr__(self, "scope_dispositions", dispositions)

    @property
    def scope_dispositions_sha256(self) -> str:
        return canonical_sha256([item.to_dict() for item in self.scope_dispositions])

    @property
    def execution_lanes(self) -> tuple[DependentExecutionLane, ...]:
        lanes: list[DependentExecutionLane] = []
        accounting_payload = {
            "role": "scope_accounting",
            "endpoint_name": "",
            "scope_dispositions_sha256": self.scope_dispositions_sha256,
            "calls": [],
        }
        accounting_digest = canonical_sha256(accounting_payload)
        lanes.append(
            DependentExecutionLane(
                lane_id=f"dependent-scope-accounting-{accounting_digest[:16]}",
                role="scope_accounting",
                endpoint_name="",
                calls=(),
                scope_dispositions_sha256=self.scope_dispositions_sha256,
            )
        )
        for endpoint_name in sorted(DEPENDENT_ENDPOINTS):
            endpoint_calls = [call for call in self.calls if call.endpoint_name == endpoint_name]
            for offset in range(0, len(endpoint_calls), DEPENDENT_CALLS_PER_LANE):
                chunk = tuple(endpoint_calls[offset : offset + DEPENDENT_CALLS_PER_LANE])
                content_payload = {
                    "role": "execute",
                    "endpoint_name": endpoint_name,
                    "scope_dispositions_sha256": self.scope_dispositions_sha256,
                    "calls": [call.to_payload() for call in chunk],
                }
                digest = canonical_sha256(content_payload)
                lanes.append(
                    DependentExecutionLane(
                        lane_id=(f"dependent-{endpoint_name.replace('_', '-')}-{digest[:16]}"),
                        role="execute",
                        endpoint_name=endpoint_name,
                        calls=chunk,
                        scope_dispositions_sha256=self.scope_dispositions_sha256,
                    )
                )
        return tuple(lanes)

    @property
    def lane_inventory_sha256(self) -> str:
        return canonical_sha256([lane.to_payload() for lane in self.execution_lanes])

    def lane(self, lane_id: str) -> DependentExecutionLane:
        matches = [lane for lane in self.execution_lanes if lane.lane_id == lane_id]
        if len(matches) != 1:
            raise DependentWorkloadContractError(
                "dependent lane is absent or ambiguous in the exact execution plan"
            )
        return matches[0]

    @property
    def content_sha256(self) -> str:
        return canonical_sha256(self.to_payload())

    def to_payload(self) -> dict[str, Any]:
        call_payloads = [call.to_payload() for call in self.calls]
        disposition_payloads = [item.to_dict() for item in self.scope_dispositions]
        lane_payloads = [lane.to_payload() for lane in self.execution_lanes]
        return {
            "schema_version": self.schema_version,
            "kind": "dependent_execution_plan",
            "lane_kind": self.lane_kind,
            "bundle_content_sha256": self.bundle_content_sha256,
            "checkpoint_transaction_sha256": self.checkpoint_transaction_sha256,
            "checkpoint_database_sha256": self.checkpoint_database_sha256,
            "source_sha": self.source_sha,
            "provider_authority_sha256": self.provider_authority_sha256,
            "discovery_artifact_id": self.discovery_artifact_id,
            "discovery_artifact_run_id": self.discovery_artifact_run_id,
            "discovery_artifact_name": self.discovery_artifact_name,
            "discovery_artifact_digest": self.discovery_artifact_digest,
            "scope_dispositions_sha256": self.scope_dispositions_sha256,
            "scope_dispositions": disposition_payloads,
            "calls": call_payloads,
            "execution_lanes": lane_payloads,
            "inventory": {
                "semantic_unit_count": len({call.unit_sha256 for call in self.calls}),
                "physical_call_count": len(self.calls),
                "endpoint_counts": {
                    endpoint: sum(call.endpoint_name == endpoint for call in self.calls)
                    for endpoint in sorted(DEPENDENT_ENDPOINTS)
                },
                "calls_sha256": canonical_sha256(call_payloads),
                "scope_disposition_count": len(disposition_payloads),
                "scope_disposition_counts": {
                    disposition.value: sum(
                        item.disposition is disposition for item in self.scope_dispositions
                    )
                    for disposition in DependentScopeDisposition
                },
                "execution_lane_count": len(lane_payloads),
                "lane_inventory_sha256": self.lane_inventory_sha256,
            },
        }

    def to_document(self) -> dict[str, Any]:
        return {**self.to_payload(), "content_sha256": self.content_sha256}

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_json_bytes(self.to_document()) + b"\n")

    def to_extraction_plan_items(self) -> list[ExtractionPlanItem]:
        plan: list[ExtractionPlanItem] = []
        for endpoint_name in sorted(DEPENDENT_ENDPOINTS):
            endpoint_calls = [call for call in self.calls if call.endpoint_name == endpoint_name]
            if not endpoint_calls:
                continue
            plan.append(
                ExtractionPlanItem(
                    label=f"dependent-{endpoint_name}",
                    pattern="player_team_season",
                    entries=_entries(endpoint_name),
                    params=[dict(call.parameters) for call in endpoint_calls],
                    priority=PATTERN_PRIORITY["player_team_season"],
                )
            )
        return plan

    @classmethod
    def read(cls, path: Path) -> DependentExecutionPlan:
        payload = _load_json_object(path, label="dependent execution plan")
        content_sha256 = payload.pop("content_sha256", None)
        inventory = payload.pop("inventory", None)
        raw_lanes = payload.pop("execution_lanes", None)
        raw_dispositions = payload.pop("scope_dispositions", None)
        raw_calls = payload.pop("calls", None)
        expected_scalars = {
            "schema_version",
            "kind",
            "lane_kind",
            "bundle_content_sha256",
            "checkpoint_transaction_sha256",
            "checkpoint_database_sha256",
            "source_sha",
            "provider_authority_sha256",
            "discovery_artifact_id",
            "discovery_artifact_run_id",
            "discovery_artifact_name",
            "discovery_artifact_digest",
            "scope_dispositions_sha256",
        }
        if (
            set(payload) != expected_scalars
            or payload["schema_version"] != cls.schema_version
            or payload["kind"] != "dependent_execution_plan"
            or payload["lane_kind"] != cls.lane_kind
            or not isinstance(raw_calls, list)
            or any(not isinstance(call, dict) for call in raw_calls)
            or not isinstance(raw_dispositions, list)
            or any(not isinstance(item, dict) for item in raw_dispositions)
            or not isinstance(raw_lanes, list)
            or not isinstance(inventory, dict)
        ):
            raise DependentWorkloadContractError("dependent execution plan is malformed")
        plan = cls(
            bundle_content_sha256=str(payload["bundle_content_sha256"]),
            checkpoint_transaction_sha256=str(payload["checkpoint_transaction_sha256"]),
            checkpoint_database_sha256=str(payload["checkpoint_database_sha256"]),
            source_sha=str(payload["source_sha"]),
            provider_authority_sha256=str(payload["provider_authority_sha256"]),
            discovery_artifact_id=payload["discovery_artifact_id"],
            discovery_artifact_run_id=payload["discovery_artifact_run_id"],
            discovery_artifact_name=str(payload["discovery_artifact_name"]),
            discovery_artifact_digest=str(payload["discovery_artifact_digest"]),
            scope_dispositions=tuple(
                _scope_disposition_from_payload(item) for item in raw_dispositions
            ),
            calls=tuple(DependentPhysicalCall.from_payload(call) for call in raw_calls),
        )
        expected_payload = plan.to_payload()
        if (
            payload["scope_dispositions_sha256"] != plan.scope_dispositions_sha256
            or raw_lanes != expected_payload["execution_lanes"]
            or content_sha256 != plan.content_sha256
            or inventory != expected_payload["inventory"]
        ):
            raise DependentWorkloadContractError("dependent execution plan digest changed")
        return plan


def build_dependent_execution_plan(bundle: DependentWorkloadBundle) -> DependentExecutionPlan:
    """Expand semantic units onto every exact physical endpoint route."""

    if not isinstance(bundle, DependentWorkloadBundle):
        raise DependentWorkloadContractError("dependent workload bundle is invalid")
    calls = tuple(
        DependentPhysicalCall(
            endpoint_name=endpoint_name,
            kind=unit.kind,
            unit_sha256=unit.identity_sha256,
            parameters=unit.parameters,
            result_route_ids=_route_ids(endpoint_name),
        )
        for unit in bundle.executable_units
        for endpoint_name in unit.endpoint_names
    )
    authority = bundle.authority
    return DependentExecutionPlan(
        bundle_content_sha256=bundle.content_sha256,
        checkpoint_transaction_sha256=authority.checkpoint_transaction_sha256,
        checkpoint_database_sha256=authority.checkpoint_database_sha256,
        source_sha=authority.source_sha,
        provider_authority_sha256=authority.provider_authority_sha256,
        discovery_artifact_id=authority.discovery_artifact_id,
        discovery_artifact_run_id=authority.discovery_artifact_run_id,
        discovery_artifact_name=authority.discovery_artifact_name,
        discovery_artifact_digest=authority.discovery_artifact_digest,
        scope_dispositions=bundle.scope_dispositions,
        calls=calls,
    )


def _row_multiset(frame: pl.DataFrame) -> Counter[str]:
    rows = Counter[str]()
    for row in frame.rows(named=True):
        rows[hashlib.sha256(canonical_json_bytes(row)).hexdigest()] += 1
    return rows


def _schema_payload(frame: pl.DataFrame) -> list[dict[str, str]]:
    return [{"name": name, "dtype": str(dtype)} for name, dtype in frame.schema.items()]


def _discovery_receipts_and_scopes(
    *,
    discovery_root: Path,
    checkpoint_frame: pl.DataFrame,
    provider_authority_sha256: str,
) -> tuple[tuple[FoundationInputReceipt, ...], dict[str, WorkloadScope]]:
    if discovery_root.is_symlink() or not discovery_root.is_dir():
        raise DependentWorkloadContractError("discovery generation root is invalid")
    manifest_paths = sorted(discovery_root.glob("league_game_log.*.json"))
    if not manifest_paths:
        raise DependentWorkloadContractError(
            "singleton league-game discovery manifests are missing"
        )

    receipts: list[FoundationInputReceipt] = []
    frames: list[pl.DataFrame] = []
    scopes_by_game: dict[str, WorkloadScope] = {}
    seen_pairs: set[tuple[str, str]] = set()
    for manifest_path in manifest_paths:
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise DependentWorkloadContractError("discovery manifest is not a regular file")
        manifest_sha256 = _sha256_path(manifest_path)
        payload = _load_json_object(manifest_path, label="discovery manifest")
        scope = payload.get("scope")
        content = payload.get("content")
        if (
            set(payload)
            != {
                "artifact_kind",
                "artifact_version",
                "scope",
                "content",
                "updated_at",
                "provenance",
            }
            or type(payload.get("artifact_version")) is not int
            or payload.get("artifact_version") != 2
            or payload.get("artifact_kind") != "league_game_log"
            or not isinstance(scope, dict)
            or set(scope) != {"kind", "seasons", "season_types", "variant"}
            or scope.get("kind") != "league_game_log"
            or scope.get("variant") != "default"
            or not isinstance(scope.get("seasons"), list)
            or len(scope["seasons"]) != 1
            or not isinstance(scope.get("season_types"), list)
            or len(scope["season_types"]) != 1
            or not isinstance(content, dict)
            or set(content) != {"format", "path", "row_count", "schema", "sha256"}
            or content.get("format") != "parquet"
            or not isinstance(payload.get("updated_at"), str)
            or not payload["updated_at"]
            or not isinstance(payload.get("provenance"), str)
            or not payload["provenance"]
        ):
            raise DependentWorkloadContractError(
                "discovery evidence must be an exact singleton v2 generation"
            )
        season = scope["seasons"][0]
        season_type = scope["season_types"][0]
        if not isinstance(season, str) or not isinstance(season_type, str):
            raise DependentWorkloadContractError("discovery singleton scope is malformed")
        artifact_scope = DiscoveryArtifactScope(
            kind="league_game_log",
            seasons=(season,),
            season_types=(season_type,),
            variant="default",
        )
        scope_digest = artifact_scope.digest()
        if manifest_path.name != f"league_game_log.{scope_digest}.json":
            raise DependentWorkloadContractError(
                "discovery singleton manifest name differs from its exact scope"
            )
        pair = (season, season_type)
        if pair in seen_pairs:
            raise DependentWorkloadContractError("discovery singleton scope is ambiguous")
        seen_pairs.add(pair)
        generation_name = content.get("path")
        content_sha256 = content.get("sha256")
        row_count = content.get("row_count")
        if (
            not isinstance(generation_name, str)
            or Path(generation_name).name != generation_name
            or not isinstance(content_sha256, str)
            or _SHA256_RE.fullmatch(content_sha256) is None
            or generation_name != f"league_game_log.{scope_digest}.{content_sha256}.parquet"
            or type(row_count) is not int
            or row_count < 0
        ):
            raise DependentWorkloadContractError("discovery generation content is invalid")
        generation_path = discovery_root / generation_name
        if _sha256_path(generation_path) != content_sha256:
            raise DependentWorkloadContractError("discovery generation digest changed")
        try:
            frame = pl.read_parquet(generation_path)
        except Exception as exc:
            raise DependentWorkloadContractError("discovery generation is unreadable") from exc
        if (
            frame.height != row_count
            or content.get("schema") != _schema_payload(frame)
            or "game_id" not in frame.columns
        ):
            raise DependentWorkloadContractError("discovery generation frame differs from manifest")
        parameters: dict[str, int | str] = {
            "season": season,
            "season_type": season_type,
        }
        receipt = FoundationInputReceipt(
            authority_kind=FoundationAuthorityKind.DISCOVERY_GENERATION,
            table_name="stg_league_game_log",
            chunk_id=content_sha256,
            endpoint_name="league_game_log",
            logical_call_receipt_sha256=None,
            discovery_manifest_sha256=manifest_sha256,
            logical_parameters=tuple(parameters.items()),
            logical_parameters_sha256=canonical_parameters_sha256(parameters),
            provider_authority_sha256=provider_authority_sha256,
            result_route_id="league_game_log:stg_league_game_log:0",
            persisted_content_sha256=content_sha256,
            persisted_schema_sha256=frame_schema_hash(frame),
            persisted_row_count=frame.height,
        )
        for ordinal, game_id in enumerate(frame.get_column("game_id").to_list()):
            if not isinstance(game_id, str) or not game_id:
                raise DependentWorkloadContractError(
                    "discovery generation contains an invalid game ID"
                )
            candidate = WorkloadScope(
                season=season,
                season_type=season_type,
                game_id=game_id,
                foundation_receipt_sha256=receipt.identity_sha256,
                foundation_row_ordinal=ordinal,
            )
            existing = scopes_by_game.setdefault(game_id, candidate)
            if existing.season != season or existing.season_type != season_type:
                raise DependentWorkloadContractError(
                    "game ID belongs to conflicting discovery singleton scopes"
                )
        receipts.append(receipt)
        frames.append(frame)

    if not frames:
        raise DependentWorkloadContractError("discovery scope inventory is empty")
    if not scopes_by_game:
        raise DependentWorkloadContractError("discovery scope inventory contains no games")
    if any(frame.schema != checkpoint_frame.schema for frame in frames):
        raise DependentWorkloadContractError(
            "discovery generation schema differs from installed checkpoint frame"
        )
    union = pl.concat(frames, how="vertical")
    if _row_multiset(union) != _row_multiset(checkpoint_frame):
        raise DependentWorkloadContractError(
            "discovery generation row multiset differs from installed checkpoint frame"
        )
    return tuple(receipts), scopes_by_game


def _table_exists(conn: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT count(*)
        FROM information_schema.tables
        WHERE table_schema = 'main' AND table_name = $1
        """,
        [table_name],
    ).fetchone()
    if row is None:
        raise DependentWorkloadContractError("checkpoint table inventory query returned no result")
    return row[0] == 1


def _chunk_frame(
    conn: duckdb.DuckDBPyConnection,
    *,
    staging_key: str,
    chunk_id: str,
    row_count: int,
) -> pl.DataFrame | None:
    internal = f"_staging_chunks__{staging_key}"
    if row_count == 0:
        if _table_exists(conn, internal):
            stored_count_row = conn.execute(
                f'SELECT count(*) FROM "{internal}" WHERE _nbadb_chunk_id = $1',
                [chunk_id],
            ).fetchone()
            if stored_count_row is None:
                raise DependentWorkloadContractError("staging chunk count query returned no result")
            stored_count = stored_count_row[0]
            if stored_count:
                raise DependentWorkloadContractError(
                    "zero-row staging receipt has persisted chunk rows"
                )
        return None
    if not _table_exists(conn, internal):
        raise DependentWorkloadContractError("receipt-bound staging chunk table is missing")
    columns = [
        str(row[0])
        for row in conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'main' AND table_name = $1
            ORDER BY ordinal_position
            """,
            [internal],
        ).fetchall()
        if str(row[0]) not in {"_nbadb_chunk_id", "_nbadb_chunk_index", "_nbadb_row_index"}
    ]
    quoted = ", ".join(f'"{column}"' for column in columns)
    frame = conn.execute(
        f"""
        SELECT {quoted}
        FROM "{internal}"
        WHERE _nbadb_chunk_id = $1
        ORDER BY _nbadb_row_index
        """,
        [chunk_id],
    ).pl()
    if frame.height != row_count:
        raise DependentWorkloadContractError("staging chunk row count differs from its receipt")
    return frame


@dataclass(frozen=True, slots=True)
class _FoundationCall:
    endpoint_name: str
    parameters: dict[str, int | str]
    logical_call_receipt_sha256: str
    receipts: tuple[FoundationInputReceipt, ...]
    frames: dict[str, pl.DataFrame | None]


def _staging_foundation_calls(
    *,
    conn: duckdb.DuckDBPyConnection,
    scopes_by_game: Mapping[str, WorkloadScope],
    provider_authority_sha256: str,
) -> tuple[tuple[_FoundationCall, ...], tuple[FoundationInputReceipt, ...]]:
    rows = conn.execute(
        """
        SELECT endpoint, params, logical_call_receipt_sha256,
               provider_authority_sha256, logical_parameters_sha256,
               result_route_ids_json
        FROM _extraction_journal
        WHERE status = 'done' AND endpoint IN ('box_score_matchups', 'game_rotation')
        ORDER BY endpoint, params
        """
    ).fetchall()
    calls: list[_FoundationCall] = []
    all_receipts: list[FoundationInputReceipt] = []
    seen_endpoint_games: set[tuple[str, str]] = set()
    for row in rows:
        endpoint_name = str(row[0])
        try:
            raw_parameters = json.loads(str(row[1]))
            raw_route_ids = json.loads(str(row[5]))
        except json.JSONDecodeError as exc:
            raise DependentWorkloadContractError(
                "foundation extraction journal parameters are invalid"
            ) from exc
        if (
            not isinstance(raw_parameters, dict)
            or set(raw_parameters) != {"game_id"}
            or not isinstance(raw_parameters["game_id"], str)
            or not isinstance(raw_route_ids, list)
            or any(not isinstance(route, str) for route in raw_route_ids)
        ):
            raise DependentWorkloadContractError(
                "foundation extraction journal scope is not one exact game"
            )
        game_id = raw_parameters["game_id"]
        if game_id not in scopes_by_game:
            raise DependentWorkloadContractError(
                "foundation extraction call is outside discovery scope authority"
            )
        key = (endpoint_name, game_id)
        if key in seen_endpoint_games:
            raise DependentWorkloadContractError("foundation extraction scope is ambiguous")
        seen_endpoint_games.add(key)
        logical_receipt = str(row[2] or "")
        provider_digest = str(row[3] or "")
        parameters_digest = str(row[4] or "")
        if (
            _SHA256_RE.fullmatch(logical_receipt) is None
            or provider_digest != provider_authority_sha256
            or parameters_digest != canonical_parameters_sha256(raw_parameters)
        ):
            raise DependentWorkloadContractError(
                "foundation extraction journal receipt is incomplete"
            )
        expected_tables = _FOUNDATION_TABLES_BY_ENDPOINT[endpoint_name]
        expected_routes = tuple(
            f"{endpoint_name}:{table_name}:{index}"
            for index, table_name in enumerate(expected_tables)
        )
        if tuple(raw_route_ids) != expected_routes:
            raise DependentWorkloadContractError(
                "foundation extraction journal route inventory is incomplete"
            )
        chunk_rows = conn.execute(
            """
            SELECT chunk_id, staging_key, persisted_row_count,
                   persisted_content_sha256, persisted_schema_sha256,
                   logical_call_receipt_sha256, provider_authority_sha256,
                   logical_parameters_sha256, result_route_id
            FROM _staging_chunk_journal
            WHERE logical_call_receipt_sha256 = $1
            ORDER BY result_route_id
            """,
            [logical_receipt],
        ).fetchall()
        if len(chunk_rows) != len(expected_tables):
            raise DependentWorkloadContractError(
                "foundation logical call lacks its exact staging receipt inventory"
            )
        receipts: list[FoundationInputReceipt] = []
        frames: dict[str, pl.DataFrame | None] = {}
        for chunk_row, expected_table, expected_route in zip(
            chunk_rows,
            expected_tables,
            expected_routes,
            strict=True,
        ):
            chunk_id = str(chunk_row[0])
            staging_key = str(chunk_row[1])
            persisted_row_count = chunk_row[2]
            persisted_content_sha256 = str(chunk_row[3] or "")
            persisted_schema_sha256 = str(chunk_row[4] or "")
            if (
                _SHA256_RE.fullmatch(chunk_id) is None
                or staging_key != expected_table
                or type(persisted_row_count) is not int
                or persisted_row_count < 0
                or str(chunk_row[5] or "") != logical_receipt
                or str(chunk_row[6] or "") != provider_authority_sha256
                or str(chunk_row[7] or "") != parameters_digest
                or str(chunk_row[8] or "") != expected_route
            ):
                raise DependentWorkloadContractError(
                    "foundation staging receipt differs from its logical call"
                )
            frame = _chunk_frame(
                conn,
                staging_key=staging_key,
                chunk_id=chunk_id,
                row_count=persisted_row_count,
            )
            if frame is not None and (
                frame_content_hash(frame) != persisted_content_sha256
                or frame_schema_hash(frame) != persisted_schema_sha256
            ):
                raise DependentWorkloadContractError(
                    "foundation staging chunk content differs from its receipt"
                )
            receipt = FoundationInputReceipt(
                authority_kind=FoundationAuthorityKind.STAGING_CHUNK,
                table_name=staging_key,
                chunk_id=chunk_id,
                endpoint_name=endpoint_name,
                logical_call_receipt_sha256=logical_receipt,
                discovery_manifest_sha256=None,
                logical_parameters=tuple(raw_parameters.items()),
                logical_parameters_sha256=parameters_digest,
                provider_authority_sha256=provider_authority_sha256,
                result_route_id=expected_route,
                persisted_content_sha256=persisted_content_sha256,
                persisted_schema_sha256=persisted_schema_sha256,
                persisted_row_count=persisted_row_count,
            )
            receipts.append(receipt)
            frames[staging_key] = frame
        call = _FoundationCall(
            endpoint_name=endpoint_name,
            parameters={"game_id": game_id},
            logical_call_receipt_sha256=logical_receipt,
            receipts=tuple(receipts),
            frames=frames,
        )
        calls.append(call)
        all_receipts.extend(receipts)
    return tuple(calls), tuple(all_receipts)


def _matchup_observations(
    call: _FoundationCall,
    scope: WorkloadScope,
) -> tuple[tuple[DirectionalMatchupObservation, ...], FoundationEvidenceState, str]:
    frame = call.frames["stg_matchup"]
    receipt = call.receipts[0]
    if frame is None or frame.is_empty():
        return (), FoundationEvidenceState.VALID_EMPTY, ""
    required = {"game_id", "off_team_id", "off_player_id", "def_team_id", "def_player_id"}
    if not required <= set(frame.columns):
        return (), FoundationEvidenceState.BLOCKED, "matchup_foundation_columns_invalid"
    observations: list[DirectionalMatchupObservation] = []
    try:
        for ordinal, row in enumerate(frame.iter_rows(named=True)):
            if row["game_id"] != scope.game_id:
                raise ValueError
            observations.append(
                DirectionalMatchupObservation(
                    scope=scope,
                    off_team_id=int(row["off_team_id"]),
                    off_player_id=int(row["off_player_id"]),
                    def_team_id=int(row["def_team_id"]),
                    def_player_id=int(row["def_player_id"]),
                    source_row=SourceRowIdentity(receipt.identity_sha256, ordinal),
                )
            )
    except (KeyError, TypeError, ValueError, DependentWorkloadContractError):
        return (), FoundationEvidenceState.BLOCKED, "matchup_foundation_rows_invalid"
    return tuple(observations), FoundationEvidenceState.COMPLETE, ""


def _rotation_observations(
    call: _FoundationCall,
    scope: WorkloadScope,
) -> tuple[tuple[RotationObservation, ...], FoundationEvidenceState, str]:
    observations: list[RotationObservation] = []
    total_rows = sum(receipt.persisted_row_count for receipt in call.receipts)
    if total_rows == 0:
        return (), FoundationEvidenceState.VALID_EMPTY, ""
    required = {"game_id", "team_id", "person_id", "in_time_real", "out_time_real"}
    try:
        for receipt in call.receipts:
            frame = call.frames[receipt.table_name]
            if frame is None or not required <= set(frame.columns):
                raise ValueError
            side = _FOUNDATION_SIDES[receipt.table_name]
            for ordinal, row in enumerate(frame.iter_rows(named=True)):
                if row["game_id"] != scope.game_id:
                    raise ValueError
                observations.append(
                    RotationObservation(
                        scope=scope,
                        side=side,
                        team_id=int(row["team_id"]),
                        player_id=int(row["person_id"]),
                        interval_start=Decimal(str(row["in_time_real"])),
                        interval_end=Decimal(str(row["out_time_real"])),
                        source_row=SourceRowIdentity(receipt.identity_sha256, ordinal),
                    )
                )
    except (KeyError, TypeError, ValueError, DependentWorkloadContractError):
        return (), FoundationEvidenceState.BLOCKED, "rotation_foundation_rows_invalid"
    return tuple(observations), FoundationEvidenceState.COMPLETE, ""


def compile_post_foundation_bundle(
    *,
    committed_manifest_path: Path,
    checkpoint_report_path: Path,
    checkpoint_database_path: Path,
    discovery_root: Path,
    discovery_artifact_id: int,
    discovery_artifact_run_id: int,
    discovery_artifact_name: str,
    discovery_artifact_digest: str,
) -> DependentWorkloadBundle:
    """Compile observed workloads from exact public foundation authorities."""

    manifest = _load_json_object(committed_manifest_path, label="committed manifest")
    chain_state = manifest.get("chain_state")
    if not isinstance(chain_state, dict) or not isinstance(
        chain_state.get("latest_checkpoint_transaction"), dict
    ):
        raise DependentWorkloadContractError(
            "committed manifest lacks the latest checkpoint transaction"
        )
    transaction = CheckpointTransaction.from_dict(chain_state["latest_checkpoint_transaction"])
    if transaction.state is not CheckpointState.COMMITTED or transaction.build is None:
        raise DependentWorkloadContractError("foundation checkpoint transaction is not committed")
    report_sha256 = _sha256_path(checkpoint_report_path)
    database_sha256 = _sha256_path(checkpoint_database_path)
    if (
        report_sha256 != transaction.build.report_sha256
        or database_sha256 != transaction.build.database_sha256
    ):
        raise DependentWorkloadContractError(
            "foundation checkpoint files differ from the committed transaction"
        )
    report = _load_json_object(checkpoint_report_path, label="checkpoint report")
    provider_authority_sha256 = str(report.get("provider_authority_sha256") or "")
    if (
        report.get("chain_id") != transaction.identity.chain_id
        or str(report.get("source_sha") or "").lower() != transaction.identity.source_sha
        or report.get("checkpoint_generation") != transaction.identity.generation
        or report.get("database_sha256") != database_sha256
        or report.get("terminal_ready") is not True
        or _SHA256_RE.fullmatch(provider_authority_sha256) is None
    ):
        raise DependentWorkloadContractError(
            "foundation checkpoint report provenance is incomplete"
        )

    conn = duckdb.connect(str(checkpoint_database_path), read_only=True)
    try:
        if not _table_exists(conn, "stg_league_game_log"):
            raise DependentWorkloadContractError(
                "installed checkpoint league-game foundation table is missing"
            )
        checkpoint_game_log = conn.execute("SELECT * FROM stg_league_game_log").pl()
        discovery_receipts, scopes_by_game = _discovery_receipts_and_scopes(
            discovery_root=discovery_root,
            checkpoint_frame=checkpoint_game_log,
            provider_authority_sha256=provider_authority_sha256,
        )
        calls, staging_receipts = _staging_foundation_calls(
            conn=conn,
            scopes_by_game=scopes_by_game,
            provider_authority_sha256=provider_authority_sha256,
        )
    finally:
        conn.close()

    by_endpoint_game = {
        (call.endpoint_name, str(call.parameters["game_id"])): call for call in calls
    }
    scope_evidence: list[FoundationScopeEvidence] = []
    matchup_observations: list[DirectionalMatchupObservation] = []
    rotation_observations: list[RotationObservation] = []
    for scope in sorted(scopes_by_game.values()):
        matchup_call = by_endpoint_game.get(("box_score_matchups", scope.game_id))
        if matchup_call is None:
            matchup_state = FoundationEvidenceState.BLOCKED
            matchup_reason = "matchup_foundation_not_scheduled"
            scope_matchups: tuple[DirectionalMatchupObservation, ...] = ()
        else:
            scope_matchups, matchup_state, matchup_reason = _matchup_observations(
                matchup_call,
                scope,
            )
        rotation_call = by_endpoint_game.get(("game_rotation", scope.game_id))
        if rotation_call is None:
            rotation_state = FoundationEvidenceState.BLOCKED
            rotation_reason = "rotation_foundation_not_scheduled"
            scope_rotations: tuple[RotationObservation, ...] = ()
        else:
            scope_rotations, rotation_state, rotation_reason = _rotation_observations(
                rotation_call,
                scope,
            )
        matchup_observations.extend(scope_matchups)
        rotation_observations.extend(scope_rotations)
        scope_evidence.append(
            FoundationScopeEvidence(
                scope=scope,
                matchup_state=matchup_state,
                rotation_state=rotation_state,
                matchup_reason_code=matchup_reason,
                rotation_reason_code=rotation_reason,
            )
        )
    if not staging_receipts:
        raise DependentWorkloadContractError(
            "checkpoint has no receipt-bound matchup or rotation foundation calls"
        )
    authority = FoundationAuthority(
        checkpoint_transaction=transaction,
        checkpoint_report_sha256=report_sha256,
        checkpoint_database_sha256=database_sha256,
        discovery_artifact_id=discovery_artifact_id,
        discovery_artifact_run_id=discovery_artifact_run_id,
        discovery_artifact_name=discovery_artifact_name,
        discovery_artifact_digest=_bare_sha256(
            discovery_artifact_digest,
            field_name="discovery_artifact_digest",
        ),
        provider_authority_sha256=provider_authority_sha256,
        source_sha=transaction.identity.source_sha,
        compiler_implementation_sha256=DEPENDENT_WORKLOAD_COMPILER_SHA256,
        query_plan_sha256=DEPENDENT_WORKLOAD_QUERY_PLAN_SHA256,
        input_receipts=(*discovery_receipts, *staging_receipts),
    )
    return compile_dependent_workload(
        authority=authority,
        scope_evidence=scope_evidence,
        matchup_observations=matchup_observations,
        rotation_observations=rotation_observations,
    )


def write_post_foundation_artifact(
    *,
    committed_manifest_path: Path,
    checkpoint_report_path: Path,
    checkpoint_database_path: Path,
    discovery_root: Path,
    discovery_artifact_id: int,
    discovery_artifact_run_id: int,
    discovery_artifact_name: str,
    discovery_artifact_digest: str,
    output_dir: Path,
) -> dict[str, Any]:
    """Compile and read back the immutable bundle and physical execution plan."""

    bundle = compile_post_foundation_bundle(
        committed_manifest_path=committed_manifest_path,
        checkpoint_report_path=checkpoint_report_path,
        checkpoint_database_path=checkpoint_database_path,
        discovery_root=discovery_root,
        discovery_artifact_id=discovery_artifact_id,
        discovery_artifact_run_id=discovery_artifact_run_id,
        discovery_artifact_name=discovery_artifact_name,
        discovery_artifact_digest=discovery_artifact_digest,
    )
    plan = build_dependent_execution_plan(bundle)
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / bundle.generation_basename
    bundle_path.write_bytes(bundle.canonical_bytes + b"\n")
    plan_path = output_dir / "dependent-execution-plan.json"
    plan.write(plan_path)
    readback = DependentExecutionPlan.read(plan_path)
    if readback.content_sha256 != plan.content_sha256:
        raise DependentWorkloadContractError(
            "dependent execution plan changed during artifact materialization"
        )
    inventory = plan.to_payload()["inventory"]
    summary = {
        "schema_version": 1,
        "kind": "dependent_workload_artifact_summary",
        "bundle_path": bundle_path.name,
        "bundle_content_sha256": bundle.content_sha256,
        "execution_plan_path": plan_path.name,
        "execution_plan_content_sha256": plan.content_sha256,
        "foundation_checkpoint_transaction_sha256": (plan.checkpoint_transaction_sha256),
        "foundation_checkpoint_database_sha256": plan.checkpoint_database_sha256,
        "scope_dispositions_sha256": plan.scope_dispositions_sha256,
        "lane_inventory_sha256": plan.lane_inventory_sha256,
        "inventory": inventory,
    }
    summary_path = output_dir / "dependent-workload-summary.json"
    summary_path.write_bytes(canonical_json_bytes(summary) + b"\n")
    if DependentExecutionPlan.read(plan_path).to_payload()["inventory"] != inventory:
        raise DependentWorkloadContractError(
            "dependent execution inventory changed during readback"
        )
    return summary
